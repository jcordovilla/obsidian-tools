#!/usr/bin/env python3
"""
Obsidian Audio Transcription Tool

Scans Obsidian vault for audio files (m4a, mp3, wav) embedded in notes,
transcribes them to high-quality text using local Whisper model, appends transcriptions
to notes, and moves audio files to trash.
"""

import argparse
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import List, Set, Tuple, Optional
from datetime import datetime

try:
    import whisper
except ImportError:
    print("⚠️  Error: Whisper library not installed.")
    print("   Install with: pip install openai-whisper")
    raise

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


class AudioTranscriber:
    """Main class for finding and transcribing audio files in Obsidian notes."""
    
    def __init__(
        self, 
        vault_path: str,
        model_size: str = "base"
    ):
        self.vault_path = Path(vault_path)
        self.attachments_path = self.vault_path / "Attachments"
        
        # Audio file extensions
        self.audio_extensions = {'.m4a', '.mp3', '.wav', '.mp4', '.mpeg', '.mpga', '.webm'}
        
        # Load Whisper model
        print(f"📦 Loading Whisper model '{model_size}' (this may take a moment on first run)...")
        self.model = whisper.load_model(model_size)
        print(f"✅ Whisper model '{model_size}' loaded successfully")
        
        # Trash path
        self.trash_path = self.vault_path / ".trash"
        self.trash_path.mkdir(exist_ok=True)
        
        # Statistics
        self.stats = {
            'notes_scanned': 0,
            'audio_files_found': 0,
            'already_transcribed': 0,
            'transcriptions_successful': 0,
            'transcriptions_failed': 0,
            'files_moved': 0
        }
        
        # Store files to process
        self.audio_files_to_process = []  # List of (note_path, audio_path, audio_link) tuples
        
        # Cache for fast audio file lookups
        self.audio_cache = {}  # filename -> Path mapping
    
    def build_audio_cache(self):
        """Scan Attachments folder once and build cache of audio files."""
        if not self.attachments_path.exists():
            return
        
        print("📁 Building audio file cache...")
        audio_count = 0
        for audio_file in self.attachments_path.rglob("*"):
            if audio_file.is_file() and any(audio_file.name.lower().endswith(ext) for ext in self.audio_extensions):
                # Store by filename for fast lookup
                if audio_file.name not in self.audio_cache:
                    self.audio_cache[audio_file.name] = audio_file
                audio_count += 1
        
        print(f"  Found {audio_count} audio files in cache")
    
    def get_all_notes(self) -> List[Path]:
        """Get all markdown files in the vault."""
        notes = []
        for md_file in self.vault_path.rglob("*.md"):
            # Skip hidden directories and trash
            if any(part.startswith('.') for part in md_file.parts):
                if '.trash' not in str(md_file) and '.obsidian' not in str(md_file):
                    continue
            notes.append(md_file)
        return notes
    
    def find_audio_in_note(self, note_path: Path) -> List[Tuple[Path, str]]:
        """
        Find all audio files referenced in a note.
        Returns list of (audio_path, original_link) tuples.
        """
        if not self.attachments_path.exists():
            return []
        
        try:
            content = note_path.read_text(encoding='utf-8', errors='ignore')
        except Exception as e:
            print(f"Error reading note {note_path}: {e}")
            return []
        
        audio_files = []
        
        # Look for Obsidian audio embed syntax: ![[audio.m4a]]
        obsidian_pattern = r'!\[\[([^\]]+)\]\]'
        obsidian_matches = re.findall(obsidian_pattern, content)
        
        # Look for markdown audio syntax: ![alt](Attachments/audio.m4a)
        md_pattern = r'!\[([^\]]*)\]\(([^)]+)\)'
        md_matches = re.findall(md_pattern, content)
        
        # Process Obsidian-style references
        for match in obsidian_matches:
            # Remove aliases
            match = match.split('|')[0]
            
            # Check if it's an audio file
            if any(match.lower().endswith(ext) for ext in self.audio_extensions):
                # Look up in cache (fast)
                if match in self.audio_cache:
                    audio_path = self.audio_cache[match]
                    audio_files.append((audio_path, f"![[{match}]]"))
        
        # Process markdown-style references
        for alt, link in md_matches:
            if any(link.lower().endswith(ext) for ext in self.audio_extensions):
                # Extract path from Attachments/
                parts = re.split(r'(?i)attachments/', link)
                if len(parts) > 1:
                    rel_path_str = parts[-1].split('?')[0]  # Remove query params
                    rel_path_str = re.sub(r'\.\./', '', rel_path_str)  # Normalize
                    audio_path = self.attachments_path / rel_path_str
                    if audio_path.exists() and audio_path.is_file():
                        audio_files.append((audio_path, f"![{alt}]({link})"))
        
        return audio_files
    
    def already_has_transcript(self, note_path: Path) -> bool:
        """
        Check if note already contains a transcript section.
        Looking for '## Transcript' or '## Audio Transcript' heading.
        """
        try:
            content = note_path.read_text(encoding='utf-8', errors='ignore')
            # Look for transcript section markers
            transcript_markers = [
                r'##\s+Transcript',
                r'##\s+Audio\s+Transcript',
                r'###\s+Transcript',
                r'###\s+Audio\s+Transcript'
            ]
            for marker in transcript_markers:
                if re.search(marker, content, re.IGNORECASE):
                    return True
        except Exception:
            pass
        return False
    
    def transcribe_audio_file(self, audio_path: Path) -> Optional[str]:
        """
        Transcribe an audio file using local Whisper model.
        Returns transcription text or None on failure.
        """
        # Get file size for progress
        file_size_mb = audio_path.stat().st_size / (1024 * 1024)
        
        print(f"  🎤 Transcribing {audio_path.name} ({file_size_mb:.1f}MB)...")
        print(f"  ⏳ Processing... (this may take 2-3x the audio duration)")
        start_time = time.time()
        
        try:
            result = self.model.transcribe(str(audio_path))
            transcript = result["text"]
            
            elapsed = time.time() - start_time
            words = len(transcript.split()) if transcript else 0
            print(f"  ✅ Transcription complete: {words} words in {elapsed:.1f}s ({words/(elapsed/60) if elapsed > 0 else 0:.0f} words/min)")
            return transcript
        except Exception as e:
            elapsed = time.time() - start_time
            print(f"  ❌ Transcription failed after {elapsed:.1f}s: {e}")
            return None
    
    def append_transcript_to_note(self, note_path: Path, transcript: str, audio_filename: str) -> bool:
        """
        Append transcript to the very end of the note as a distinct section.
        Returns True if successful.
        """
        try:
            print(f"  📝 Appending transcript to note...")
            content = note_path.read_text(encoding='utf-8', errors='ignore')
            
            # Create transcript section with clear separation
            transcript_section = f"""

---

## Audio Transcript

*Transcribed from: {audio_filename}*

{transcript}

"""
            
            # Append to the end
            new_content = content + transcript_section
            
            note_path.write_text(new_content, encoding='utf-8')
            print(f"  ✅ Transcript appended")
            return True
        except Exception as e:
            print(f"  ❌ Failed to append transcript: {e}")
            return False
    
    def move_audio_to_trash(self, audio_path: Path) -> bool:
        """Move audio file to trash folder."""
        try:
            print(f"  🗑️  Moving audio to trash...")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            trash_folder = self.trash_path / f"transcribed_audio_{timestamp}"
            trash_folder.mkdir(parents=True, exist_ok=True)
            
            dest_path = trash_folder / audio_path.name
            shutil.move(str(audio_path), str(dest_path))
            print(f"  ✅ Audio moved to trash")
            return True
        except Exception as e:
            print(f"  ❌ Failed to move to trash: {e}")
            return False
    
    def scan_and_process(self):
        """Main processing loop: scan notes, find audio, transcribe, update notes."""
        print("🔍 Scanning vault for notes with audio files...")
        print()
        
        # Build audio cache first for fast lookups
        self.build_audio_cache()
        print()
        
        notes = self.get_all_notes()
        self.stats['notes_scanned'] = len(notes)
        print(f"  Scanning {len(notes)} notes...")
        
        for idx, note in enumerate(notes):
            if idx > 0 and idx % 500 == 0:
                print(f"  Processed {idx}/{len(notes)} notes (found {self.stats['audio_files_found']} audio files)...")
            
            audio_files = self.find_audio_in_note(note)
            if audio_files:
                self.stats['audio_files_found'] += len(audio_files)
                for audio_path, audio_link in audio_files:
                    self.audio_files_to_process.append((note, audio_path, audio_link))
        
        print(f"✅ Scanned {len(notes)} notes")
        print(f"📊 Found {self.stats['audio_files_found']} audio files in notes")
        print()
        
        if not self.audio_files_to_process:
            print("✅ No audio files to transcribe!")
            return
        
        # Calculate total file size for estimate
        total_size_mb = sum(p.stat().st_size for _, p, _ in self.audio_files_to_process) / (1024 * 1024)
        print(f"📦 Total audio size: {total_size_mb:.1f}MB")
        print(f"⏱️  Estimated time: ~{int(total_size_mb * 2)} seconds (rough estimate)")
        print()
        
        # Process each audio file
        process_start_time = time.time()
        completed_count = 0
        for idx, (note_path, audio_path, audio_link) in enumerate(self.audio_files_to_process, 1):
            # Calculate progress and ETA
            elapsed_total = time.time() - process_start_time
            if completed_count > 0:
                avg_time_per_file = elapsed_total / completed_count
                remaining_files = len(self.audio_files_to_process) - idx + 1
                eta_seconds = avg_time_per_file * remaining_files
            else:
                eta_seconds = 0
            
            print(f"\n{'=' * 60}")
            print(f"[{idx}/{len(self.audio_files_to_process)}] {idx*100//len(self.audio_files_to_process)}%")
            print(f"📄 Note: {note_path.relative_to(self.vault_path)}")
            print(f"🎵 Audio: {audio_path.relative_to(self.attachments_path)}")
            if idx > 1 and completed_count > 0:
                print(f"⏱️  ETA: {eta_seconds/60:.1f} minutes remaining")
            print(f"⏱️  Elapsed: {elapsed_total/60:.1f} minutes")
            print(f"{'=' * 60}")
            
            # Check if already transcribed
            if self.already_has_transcript(note_path):
                print("  ℹ️  Note already contains a transcript (skipping)")
                self.stats['already_transcribed'] += 1
                continue
            
            # Transcribe
            transcript = self.transcribe_audio_file(audio_path)
            if not transcript:
                self.stats['transcriptions_failed'] += 1
                continue
            
            # Append to note
            if self.append_transcript_to_note(note_path, transcript, audio_path.name):
                self.stats['transcriptions_successful'] += 1
            
            # Move audio to trash
            if self.move_audio_to_trash(audio_path):
                self.stats['files_moved'] += 1
            
            # Increment completed count for ETA calculations
            completed_count += 1
    
    def print_summary(self):
        """Print final statistics summary."""
        print()
        print("=" * 60)
        print("📊 TRANSCRIPTION SUMMARY")
        print("=" * 60)
        print(f"  • Notes scanned: {self.stats['notes_scanned']}")
        print(f"  • Audio files found: {self.stats['audio_files_found']}")
        print(f"  • Already transcribed: {self.stats['already_transcribed']}")
        print(f"  • Transcriptions successful: {self.stats['transcriptions_successful']}")
        print(f"  • Transcriptions failed: {self.stats['transcriptions_failed']}")
        print(f"  • Files moved to trash: {self.stats['files_moved']}")
        print("=" * 60)
    
    def run(self):
        """Main entry point."""
        start_time = time.time()
        self.scan_and_process()
        total_elapsed = time.time() - start_time
        
        self.print_summary()
        
        # Print total time
        print()
        print(f"⏱️  Total time: {total_elapsed:.1f} seconds ({total_elapsed/60:.1f} minutes)")
        print()


def main():
    parser = argparse.ArgumentParser(
        description="Transcribe audio files in Obsidian notes using local Whisper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example:
  python transcribe_audio.py --vault /path/to/vault
  python transcribe_audio.py --vault /path/to/vault --model large

Whisper Model Sizes:
  - tiny: 39M params, ~1GB VRAM, fastest but least accurate
  - base: 74M params, ~1GB VRAM, good balance
  - small: 244M params, ~2GB VRAM, better accuracy
  - medium: 769M params, ~5GB VRAM, high accuracy
  - large: 1550M params, ~10GB VRAM, best accuracy (slowest)
  
Requirements:
  pip install openai-whisper
  
The script will:
  1. Find all audio files (m4a, mp3, wav, mp4, etc.) referenced in notes
  2. Skip notes that already contain transcripts
  3. Transcribe each audio file using local Whisper model
  4. Append transcript to the end of the note
  5. Move audio file to trash

Audio files are moved to: .trash/transcribed_audio_<timestamp>/
        """
    )
    parser.add_argument(
        '--vault',
        type=str,
        default='/Users/jose/obsidian/JC',
        help='Path to Obsidian vault (default: /Users/jose/obsidian/JC)'
    )
    parser.add_argument(
        '--model',
        type=str,
        default='base',
        choices=['tiny', 'base', 'small', 'medium', 'large'],
        help='Whisper model size (default: base)'
    )
    
    args = parser.parse_args()
    
    transcriber = AudioTranscriber(
        vault_path=args.vault,
        model_size=args.model
    )
    
    transcriber.run()


if __name__ == "__main__":
    main()

