#!/usr/bin/env python3
"""
Obsidian Deduplication Tool

Scans Obsidian vault for duplicate notes with numeric suffixes and moves them to trash.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from typing import Dict, List, Set, Tuple
from datetime import datetime
import difflib


class ObsidianDeduplicator:
    """Main class for detecting and removing duplicate Obsidian notes."""
    
    def __init__(self, vault_path: str, dry_run: bool = True):
        self.vault_path = Path(vault_path)
        self.attachments_path = self.vault_path / "Attachments"
        self.dry_run = dry_run
        self.trash_path = self.vault_path / ".trash"
        
        # Pattern to match duplicate suffixes: filename (1).md, filename (2).md, etc.
        self.duplicate_pattern = re.compile(r'^(.+) \((\d+)\)\.md$')
        
        # Statistics
        self.stats = {
            'notes_scanned': 0,
            'duplicates_found': 0,
            'notes_deleted': 0,
            'attachments_moved': 0
        }
        
        # Attachments mapping: original note -> list of attachment files
        self.attachment_cache = {}
        
        # Store confirmed duplicates for deletion
        self.confirmed_duplicates = []  # List of (original, duplicates, attachments) tuples
        
    def setup_trash(self):
        """Create trash directory if it doesn't exist."""
        if not self.dry_run:
            self.trash_path.mkdir(exist_ok=True)
            
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
    
    def parse_duplicate_name(self, filename: str) -> Tuple[str, int]:
        """
        Parse a filename like 'note (1).md' into ('note', 1).
        Returns None if not a duplicate.
        """
        match = self.duplicate_pattern.match(filename)
        if match:
            base_name = match.group(1)
            suffix = int(match.group(2))
            return (base_name, suffix)
        return None
    
    def group_duplicates(self, notes: List[Path]) -> Dict[str, List[Tuple[Path, int]]]:
        """
        Group notes by their base name, including originals and duplicates.
        
        Returns: {base_name: [(path, suffix)]}
                  where suffix=0 for original, suffix=N for duplicates
        """
        groups = {}
        
        for note in notes:
            base_name = note.stem  # filename without extension
            base_match = self.parse_duplicate_name(note.name)
            
            if base_match:
                # It's a duplicate (has suffix)
                actual_base, suffix = base_match
                key = f"{actual_base}.md"
                if key not in groups:
                    groups[key] = []
                groups[key].append((note, suffix))
            else:
                # It's a potential original
                key = f"{base_name}.md"
                if key not in groups:
                    groups[key] = []
                groups[key].append((note, 0))
        
        # Filter to only groups that have duplicates (suffix > 0)
        return {k: v for k, v in groups.items() if any(suffix > 0 for _, suffix in v)}
    
    def read_note_content(self, path: Path) -> bytes:
        """Read note content with error handling."""
        try:
            return path.read_bytes()
        except Exception as e:
            print(f"Error reading {path}: {e}")
            return b""
    
    def compute_hash(self, content: bytes) -> str:
        """Compute MD5 hash of content."""
        return hashlib.md5(content).hexdigest()
    
    def are_notes_duplicates(self, path1: Path, path2: Path, threshold: float = 0.95) -> bool:
        """
        Compare two notes to determine if they're duplicates.
        Uses both hash comparison and content similarity.
        """
        content1 = path1.read_bytes()
        content2 = path2.read_bytes()
        
        # Quick check: if hashes match, they're identical
        if content1 == content2:
            return True
        
        # Content-based similarity check
        lines1 = content1.decode('utf-8', errors='ignore').splitlines()
        lines2 = content2.decode('utf-8', errors='ignore').splitlines()
        
        similarity = difflib.SequenceMatcher(None, lines1, lines2).ratio()
        return similarity >= threshold
    
    def find_note_attachments(self, note_path: Path) -> Set[str]:
        """
        Find attachments referenced in a note.
        Attachments are in the Attachments/ subfolder.
        """
        if not self.attachments_path.exists():
            return set()
        
        try:
            content = note_path.read_text(encoding='utf-8', errors='ignore')
        except Exception as e:
            print(f"Error reading note {note_path}: {e}")
            return set()
        
        # Look for markdown image/link syntax: ![[image.png]] or [[file.pdf]]
        pattern = r'\[\[([^\]]+)\]\]'
        matches = re.findall(pattern, content)
        
        # Also check for markdown image syntax: ![](Attachments/image.png)
        md_image_pattern = r'!\[([^\]]*)\]\(([^)]+)\)'
        md_matches = re.findall(md_image_pattern, content)
        
        attachments = set()
        
        # Process [[link]] style references
        for match in matches:
            # Check if this is an attachment
            attachment = self.attachments_path / match
            if attachment.exists():
                attachments.add(attachment.name)
        
        # Process markdown image syntax
        for alt, link in md_matches:
            # Extract filename if link is to Attachments/
            if 'Attachments/' in link:
                filename = link.split('Attachments/')[-1]
                attachments.add(filename)
        
        return attachments
    
    def find_original_and_duplicates(self, group: List[Tuple[Path, int]]) -> Tuple[Path, List[Path]]:
        """
        Identify the original note and its duplicates from a group.
        Returns (original_path, [duplicate_paths]).
        """
        # Sort by suffix (0 is original, 1, 2, 3... are duplicates)
        sorted_group = sorted(group, key=lambda x: x[1])
        original = sorted_group[0][0]  # First item should be original
        duplicates = [path for path, suffix in sorted_group[1:]]
        
        return original, duplicates
    
    def move_to_trash(self, path: Path) -> bool:
        """Move a file to the trash directory."""
        if self.dry_run:
            print(f"  [DRY RUN] Would move to trash: {path.name}")
            return True
        
        try:
            # Create a subdirectory in trash for this run
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            run_trash = self.trash_path / f"dedup_{timestamp}"
            run_trash.mkdir(parents=True, exist_ok=True)
            
            dest = run_trash / path.name
            
            # Handle name collisions
            counter = 1
            while dest.exists():
                stem = path.stem
                ext = path.suffix
                dest = run_trash / f"{stem}_{counter}{ext}"
                counter += 1
            
            shutil.move(str(path), str(dest))
            print(f"  Moved to trash: {dest}")
            return True
        except Exception as e:
            print(f"  Error moving {path} to trash: {e}")
            return False
    
    def process_group(self, base_name: str, group: List[Tuple[Path, int]]):
        """Process a group of duplicate notes - detection phase only."""
        original, duplicates = self.find_original_and_duplicates(group)
        
        print(f"\n📄 Checking duplicates for: {original.name}")
        
        # Get attachments for original
        original_attachments = self.find_note_attachments(original)
        
        # Verify duplicates
        confirmed_duplicates = []
        for dup in duplicates:
            if self.are_notes_duplicates(original, dup):
                confirmed_duplicates.append(dup)
                print(f"  ✓ Confirmed duplicate: {dup.name}")
            else:
                print(f"  ✗ NOT a duplicate (content differs): {dup.name}")
        
        if not confirmed_duplicates:
            print("  → No confirmed duplicates to remove")
            return
        
        # Show content diff for first duplicate (for verification)
        if confirmed_duplicates:
            print(f"\n  Diff comparison ({original.name} vs {confirmed_duplicates[0].name}):")
            self.show_diff(original, confirmed_duplicates[0])
        
        # Get attachments for duplicates
        all_attachments = set(original_attachments)
        for dup in confirmed_duplicates:
            dup_attachments = self.find_note_attachments(dup)
            if dup_attachments:
                print(f"  Has {len(dup_attachments)} attachment(s): {', '.join(dup_attachments)}")
                all_attachments.update(dup_attachments)
        
        # Store for deletion phase
        self.confirmed_duplicates.append((original, confirmed_duplicates, all_attachments))
        self.stats['duplicates_found'] += len(confirmed_duplicates)
    
    def show_diff(self, path1: Path, path2: Path, max_lines: int = 20):
        """Show a diff between two files."""
        try:
            lines1 = path1.read_text(encoding='utf-8', errors='ignore').splitlines()
            lines2 = path2.read_text(encoding='utf-8', errors='ignore').splitlines()
            
            diff = list(difflib.unified_diff(
                lines1, lines2,
                fromfile=str(path1.name),
                tofile=str(path2.name),
                lineterm='',
                n=3
            ))
            
            if diff:
                print("  " + "\n  ".join(diff[:max_lines]))
                if len(diff) > max_lines:
                    print(f"  ... ({len(diff) - max_lines} more lines)")
            else:
                print("  (files are identical)")
        except Exception as e:
            print(f"  Error generating diff: {e}")
    
    def check_orphaned_attachments(self, all_attachments: Set[str], notes: List[Path]):
        """
        Check if any attachments are only referenced in duplicates.
        If so, consider moving them to trash.
        """
        # Find which notes reference which attachments
        attachment_refs = {att: [] for att in all_attachments}
        
        for note in notes:
            attachments = self.find_note_attachments(note)
            for att in attachments:
                if att in attachment_refs:
                    attachment_refs[att].append(note)
        
        # Find orphaned attachments (only in deleted notes)
        for att, ref_notes in attachment_refs.items():
            if len(ref_notes) == 1:  # Only referenced in one note
                # Check if that note is being deleted
                if ref_notes[0] in notes[1:]:  # Not the original
                    att_path = self.attachments_path / att
                    if att_path.exists():
                        print(f"  Orphaned attachment found: {att}")
                        self.move_to_trash(att_path)
    
    def execute_deletion(self):
        """Execute the deletion of confirmed duplicates."""
        if not self.confirmed_duplicates:
            return
        
        print("\n" + "=" * 60)
        print("🗑️  DELETION PHASE")
        print("=" * 60)
        
        for original, confirmed_duplicates, all_attachments in self.confirmed_duplicates:
            print(f"\n📄 Processing: {original.name}")
            
            # Process duplicates
            for dup in confirmed_duplicates:
                if self.move_to_trash(dup):
                    self.stats['notes_deleted'] += 1
            
            # Check for orphaned attachments
            if all_attachments:
                self.check_orphaned_attachments(all_attachments, [original, *confirmed_duplicates])
                if not self.dry_run:
                    self.stats['attachments_moved'] += len([a for a in all_attachments if (self.attachments_path / a).exists()])
    
    def run(self):
        """Main execution logic."""
        print("🔍 Obsidian Deduplication Tool")
        print(f"Vault: {self.vault_path}")
        print("=" * 60)
        
        # Setup
        self.setup_trash()
        
        # PHASE 1: Detection
        print("\n📚 PHASE 1: Scanning for notes...")
        all_notes = self.get_all_notes()
        self.stats['notes_scanned'] = len(all_notes)
        print(f"Found {len(all_notes)} note(s)")
        
        print("\n🔎 PHASE 2: Grouping potential duplicates...")
        duplicate_groups = self.group_duplicates(all_notes)
        self.stats['duplicates_found'] = 0  # Will be incremented during verification
        print(f"Found {len(duplicate_groups)} potential duplicate group(s)")
        
        if not duplicate_groups:
            print("\n✅ No duplicates found!")
            return
        
        print("\n🔬 PHASE 3: Verifying duplicates...")
        # Process each group (detection only)
        for base_name, group in sorted(duplicate_groups.items()):
            self.process_group(base_name, group)
        
        # Print detection summary
        print("\n" + "=" * 60)
        print("📊 DETECTION SUMMARY:")
        print(f"  Notes scanned: {self.stats['notes_scanned']}")
        print(f"  Duplicate groups found: {len(duplicate_groups)}")
        print(f"  Confirmed duplicates to delete: {self.stats['duplicates_found']}")
        
        if not self.confirmed_duplicates:
            print("\n✅ No confirmed duplicates found!")
            return
        
        # PHASE 4: Request permission
        print("\n" + "=" * 60)
        print("⚠️  CONFIRMATION REQUIRED")
        print("=" * 60)
        print(f"\nThe tool has found {self.stats['duplicates_found']} confirmed duplicate(s) to delete.")
        print("Files will be moved to: .trash/dedup_<timestamp>/")
        
        if self.dry_run:
            print("\n⚠️  DRY RUN MODE: No files will be deleted.")
            self.execute_deletion()
            print("\n⚠️  This was a DRY RUN. Run with --no-dry-run to actually delete files.")
        else:
            print("\nWould you like to proceed with deletion? (yes/no): ", end='')
            response = input().strip().lower()
            
            if response in ['yes', 'y']:
                self.execute_deletion()
            else:
                print("\n❌ Deletion cancelled by user.")
                return
        
        # Final summary
        print("\n" + "=" * 60)
        print("📊 FINAL SUMMARY:")
        print(f"  Notes scanned: {self.stats['notes_scanned']}")
        print(f"  Duplicate groups found: {len(duplicate_groups)}")
        print(f"  Notes deleted: {self.stats['notes_deleted']}")
        print(f"  Attachments moved: {self.stats['attachments_moved']}")


def main():
    parser = argparse.ArgumentParser(
        description="Detect and remove duplicate Obsidian notes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run (preview only, safe default)
  python deduplicate.py --vault /Users/jose/obsidian/JC
  
  # Actually delete duplicates (prompts for confirmation)
  python deduplicate.py --vault /Users/jose/obsidian/JC --no-dry-run
  
  # Simple run with default vault path
  python deduplicate.py
        """
    )
    
    parser.add_argument(
        '--vault',
        type=str,
        default='/Users/jose/obsidian/JC',
        help='Path to Obsidian vault (default: /Users/jose/obsidian/JC)'
    )
    
    parser.add_argument(
        '--no-dry-run',
        action='store_true',
        help='Allow actual deletion (prompts for confirmation). Default is dry-run mode.'
    )
    
    args = parser.parse_args()
    
    # Validate vault path
    vault_path = Path(args.vault)
    if not vault_path.exists():
        print(f"Error: Vault path does not exist: {vault_path}")
        return 1
    
    if not vault_path.is_dir():
        print(f"Error: Vault path is not a directory: {vault_path}")
        return 1
    
    # Run deduplication
    dedup = ObsidianDeduplicator(vault_path, dry_run=not args.no_dry_run)
    dedup.run()
    
    return 0


if __name__ == "__main__":
    exit(main())

