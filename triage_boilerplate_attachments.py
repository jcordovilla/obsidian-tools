#!/usr/bin/env python3
"""
Obsidian Boilerplate Attachment Triage Tool

Identifies notes with many boilerplate attachments (from web clippers) and tags them
for manual review. After review, can clean up by removing attachments and references.

Features:
- Identifies notes with >5 attachments
- Distinguishes screenshots (meaningful) from boilerplate attachments
- Tags notes with boilerplate attachments as "triage"
- Provides cleanup function to remove attachments and references from triaged notes
"""

import argparse
import re
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional
from datetime import datetime
from collections import defaultdict

# GUI imports
try:
    import tkinter as tk
    from tkinter import ttk, scrolledtext
    TKINTER_AVAILABLE = True
except ImportError:
    TKINTER_AVAILABLE = False

# Import pattern analysis from attachment_stats
try:
    from attachment_stats import AttachmentStats
except ImportError:
    AttachmentStats = None


class TriageGUI:
    """GUI for triaging notes with boilerplate attachments."""
    
    def __init__(self, root: tk.Tk, triage_obj: 'BoilerplateAttachmentTriage'):
        self.root = root
        self.triage = triage_obj
        self.current_index = 0
        self.notes_to_triage = triage_obj.notes_to_triage.copy()
        
        self.root.title("Obsidian Boilerplate Attachment Triage")
        self.root.geometry("1000x700")
        
        # Status label
        self.status_label = ttk.Label(
            root,
            text=f"Note 1 of {len(self.notes_to_triage)}",
            font=("Arial", 12, "bold")
        )
        self.status_label.pack(pady=10)
        
        # Note name label
        self.note_label = ttk.Label(
            root,
            text="",
            font=("Arial", 10),
            wraplength=950
        )
        self.note_label.pack(pady=5)
        
        # Note preview (first 30 lines)
        ttk.Label(root, text="Note Preview:", font=("Arial", 10, "bold")).pack(anchor="w", padx=20, pady=(10, 5))
        self.preview_text = scrolledtext.ScrolledText(
            root,
            height=10,
            width=120,
            wrap=tk.WORD,
            font=("Courier", 9)
        )
        self.preview_text.pack(padx=20, pady=5, fill=tk.BOTH, expand=True)
        
        # Attachments list
        ttk.Label(root, text="Attachments:", font=("Arial", 10, "bold")).pack(anchor="w", padx=20, pady=(10, 5))
        
        # Frame for attachments list and scrollbar
        attachments_frame = ttk.Frame(root)
        attachments_frame.pack(padx=20, pady=5, fill=tk.BOTH, expand=True)
        
        self.attachments_listbox = tk.Listbox(
            attachments_frame,
            height=8,
            font=("Courier", 9)
        )
        scrollbar = ttk.Scrollbar(attachments_frame, orient=tk.VERTICAL, command=self.attachments_listbox.yview)
        self.attachments_listbox.configure(yscrollcommand=scrollbar.set)
        self.attachments_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Buttons frame
        button_frame = ttk.Frame(root)
        button_frame.pack(pady=20)
        
        self.keep_button = ttk.Button(
            button_frame,
            text="Keep (Skip)",
            command=self.keep_note,
            width=15
        )
        self.keep_button.pack(side=tk.LEFT, padx=10)
        
        self.clean_button = ttk.Button(
            button_frame,
            text="Clean (Remove Attachments)",
            command=self.clean_note,
            width=25
        )
        self.clean_button.pack(side=tk.LEFT, padx=10)
        
        self.delete_button = ttk.Button(
            button_frame,
            text="Delete Note",
            command=self.delete_note,
            width=15
        )
        self.delete_button.pack(side=tk.LEFT, padx=10)
        
        # Results label
        self.results_label = ttk.Label(
            root,
            text="",
            font=("Arial", 9)
        )
        self.results_label.pack(pady=5)
        
        # Help label for keyboard shortcuts
        help_label = ttk.Label(
            root,
            text="Shortcuts: Enter/K = Keep, Space/C = Clean, D = Delete",
            font=("Arial", 8),
            foreground="gray"
        )
        help_label.pack(pady=2)
        
        # Keyboard shortcuts
        self.root.bind('<Return>', lambda e: self.keep_note())
        self.root.bind('<space>', lambda e: self.clean_note())
        self.root.bind('<c>', lambda e: self.clean_note())
        self.root.bind('<k>', lambda e: self.keep_note())
        self.root.bind('<d>', lambda e: self.delete_note())
        self.root.focus_set()  # Ensure window can receive keyboard events
        
        # Load first note
        if self.notes_to_triage:
            self.load_note(0)
        else:
            self.note_label.config(text="No notes to triage")
            self.clean_button.config(state=tk.DISABLED)
            self.keep_button.config(state=tk.DISABLED)
    
    def load_note(self, index: int):
        """Load a note at the given index."""
        if index >= len(self.notes_to_triage):
            # All notes processed - show summary and close
            summary_text = (
                f"✓ Triage Complete!\n\n"
                f"Notes cleaned: {self.triage.stats['notes_cleaned']}\n"
                f"Notes deleted: {self.triage.stats['notes_deleted']}\n"
                f"Attachments deleted: {self.triage.stats['attachments_deleted']}\n"
                f"References removed: {self.triage.stats['references_removed']}"
            )
            
            # Create summary window
            summary_window = tk.Toplevel(self.root)
            summary_window.title("Triage Complete")
            summary_window.geometry("400x200")
            
            ttk.Label(
                summary_window,
                text="Triage Complete!",
                font=("Arial", 14, "bold")
            ).pack(pady=20)
            
            ttk.Label(
                summary_window,
                text=summary_text,
                font=("Arial", 10)
            ).pack(pady=10)
            
            ttk.Button(
                summary_window,
                text="OK",
                command=lambda: [summary_window.destroy(), self.root.destroy()]
            ).pack(pady=10)
            
            return
        
        self.current_index = index
        note, attachments, total, screenshots = self.notes_to_triage[index]
        
        # Update status
        self.status_label.config(text=f"Note {index + 1} of {len(self.notes_to_triage)}")
        
        # Update note name
        rel_path = note.relative_to(self.triage.vault_path)
        self.note_label.config(text=str(rel_path))
        
        # Load note preview
        try:
            if not note.exists():
                self.preview_text.delete(1.0, tk.END)
                self.preview_text.insert(1.0, "Note file no longer exists (may have been deleted)")
            else:
                content = note.read_text(encoding='utf-8', errors='ignore')
                preview_lines = content.split('\n')[:30]
                preview = '\n'.join(preview_lines)
                if len(content.split('\n')) > 30:
                    preview += f"\n\n... ({len(content.split('\n')) - 30} more lines)"
                self.preview_text.delete(1.0, tk.END)
                self.preview_text.insert(1.0, preview)
        except Exception as e:
            self.preview_text.delete(1.0, tk.END)
            self.preview_text.insert(1.0, f"Error reading note: {e}")
        
        # Load attachments list
        self.attachments_listbox.delete(0, tk.END)
        boilerplate = total - screenshots
        for att in attachments:
            is_screenshot = self.triage.is_screenshot(att.name)
            icon = "📸" if is_screenshot else "📎"
            try:
                rel_att = att.relative_to(self.triage.attachments_path)
                self.attachments_listbox.insert(tk.END, f"{icon} {rel_att}")
            except ValueError:
                self.attachments_listbox.insert(tk.END, f"{icon} {att.name}")
        
        # Update results label
        self.results_label.config(
            text=f"Total: {total} | Screenshots: {screenshots} | Boilerplate: {boilerplate}"
        )
    
    def keep_note(self):
        """Skip this note, move to next."""
        self.load_note(self.current_index + 1)
    
    def clean_note(self):
        """Clean the current note: remove attachments and references."""
        if self.current_index >= len(self.notes_to_triage):
            return
        
        note, attachments, total, screenshots = self.notes_to_triage[self.current_index]
        
        # Filter out screenshots - only remove boilerplate
        boilerplate_attachments = [att for att in attachments if not self.triage.is_screenshot(att.name)]
        
        if not boilerplate_attachments:
            # No boilerplate to remove, just move to next
            self.keep_note()
            return
        
        # Find and remove resources folder
        # Resources folders are named after the note filename (without .md extension)
        note_name_without_ext = note.stem
        # Try direct match first
        resources_folder = self.triage.attachments_path / f"{note_name_without_ext}.resources"
        
        # If not found, try searching for any .resources folder containing these attachments
        if not resources_folder.exists():
            # Search for .resources folders that might match
            for att in boilerplate_attachments[:1]:  # Check first attachment path
                att_str = str(att)
                if '.resources' in att_str:
                    # Extract the resources folder path
                    parts = att_str.split('.resources')
                    if len(parts) > 0:
                        potential_resources = Path(parts[0] + '.resources')
                        if potential_resources.exists() and potential_resources.is_dir():
                            resources_folder = potential_resources
                            break
        
        cleaned_count = 0
        refs_removed = 0
        
        try:
            # Remove references from note
            refs_removed = self.triage.remove_attachment_references(note, boilerplate_attachments)
            
            # Move attachments to trash
            for attachment in boilerplate_attachments:
                if self.triage.move_attachment_to_trash(attachment):
                    cleaned_count += 1
            
            # Move resources folder to trash if it exists and contains the attachments we're removing
            if resources_folder.exists() and resources_folder.is_dir():
                # Check if any of the attachments we're removing are in this resources folder
                resources_folder_str = str(resources_folder)
                has_matching_attachments = any(resources_folder_str in str(att) for att in boilerplate_attachments)
                
                if has_matching_attachments:
                    if self.triage.dry_run:
                        print(f"    [DRY RUN] Would move to trash: {resources_folder.name}")
                    else:
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        run_trash = self.triage.trash_path / f"boilerplate_attachments_{timestamp}"
                        run_trash.mkdir(parents=True, exist_ok=True)
                        
                        dest = run_trash / resources_folder.name
                        counter = 1
                        while dest.exists():
                            dest = run_trash / f"{resources_folder.name}_{counter}"
                            counter += 1
                        
                        shutil.move(str(resources_folder), str(dest))
            
            # Update stats
            self.triage.stats['notes_cleaned'] += 1
            self.triage.stats['attachments_deleted'] += cleaned_count
            self.triage.stats['references_removed'] += refs_removed
            
            # Show success message
            self.results_label.config(
                text=f"✓ Cleaned: {cleaned_count} attachments removed, {refs_removed} references removed",
                foreground="green"
            )
            self.root.update()
            
            # Move to next note after a brief delay
            self.root.after(500, lambda: self.load_note(self.current_index + 1))
        
        except Exception as e:
            self.results_label.config(
                text=f"✗ Error cleaning note: {e}",
                foreground="red"
            )
    
    def delete_note(self):
        """Delete the current note and all its attachments."""
        if self.current_index >= len(self.notes_to_triage):
            return
        
        note, attachments, total, screenshots = self.notes_to_triage[self.current_index]
        
        # Confirm deletion
        import tkinter.messagebox as messagebox
        rel_path = note.relative_to(self.triage.vault_path)
        response = messagebox.askyesno(
            "Confirm Deletion",
            f"Are you sure you want to delete this note?\n\n{rel_path}\n\n"
            f"This will move the note and all {total} attachments to trash.",
            icon='warning'
        )
        
        if not response:
            return  # User cancelled
        
        try:
            deleted_count = 0
            
            # Create trash directory structure
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            run_trash = self.triage.trash_path / f"notes_{timestamp}"
            run_trash.mkdir(parents=True, exist_ok=True)
            
            # Move note to trash
            if note.exists():
                dest_note = run_trash / note.name
                counter = 1
                while dest_note.exists():
                    stem = note.stem
                    ext = note.suffix
                    dest_note = run_trash / f"{stem}_{counter}{ext}"
                    counter += 1
                
                shutil.move(str(note), str(dest_note))
                deleted_count += 1
            
            # Move all attachments (both screenshots and boilerplate) to trash
            attachments_trash = run_trash / "attachments"
            attachments_trash.mkdir(exist_ok=True)
            
            attachments_moved = 0
            for attachment in attachments:
                if attachment.exists():
                    dest_attachment = attachments_trash / attachment.name
                    counter = 1
                    while dest_attachment.exists():
                        stem = attachment.stem
                        ext = attachment.suffix
                        dest_attachment = attachments_trash / f"{stem}_{counter}{ext}"
                        counter += 1
                    
                    try:
                        shutil.move(str(attachment), str(dest_attachment))
                        attachments_moved += 1
                    except Exception as e:
                        print(f"    ⚠️  Error moving attachment {attachment.name}: {e}")
            
            # Find and move resources folder
            note_name_without_ext = note.stem
            resources_folder = self.triage.attachments_path / f"{note_name_without_ext}.resources"
            
            # If not found, try searching for any .resources folder containing these attachments
            if not resources_folder.exists():
                for att in attachments[:1]:  # Check first attachment path
                    att_str = str(att)
                    if '.resources' in att_str:
                        parts = att_str.split('.resources')
                        if len(parts) > 0:
                            potential_resources = Path(parts[0] + '.resources')
                            if potential_resources.exists() and potential_resources.is_dir():
                                resources_folder = potential_resources
                                break
            
            # Move resources folder to trash if it exists
            if resources_folder.exists() and resources_folder.is_dir():
                dest_resources = run_trash / resources_folder.name
                counter = 1
                while dest_resources.exists():
                    dest_resources = run_trash / f"{resources_folder.name}_{counter}"
                    counter += 1
                
                try:
                    shutil.move(str(resources_folder), str(dest_resources))
                except Exception as e:
                    print(f"    ⚠️  Error moving resources folder: {e}")
            
            # Update stats
            self.triage.stats['notes_deleted'] += 1
            self.triage.stats['attachments_deleted'] += attachments_moved
            
            # Show success message
            self.results_label.config(
                text=f"✓ Deleted: Note moved to trash with {attachments_moved} attachment(s)",
                foreground="green"
            )
            self.root.update()
            
            # Move to next note after a brief delay
            self.root.after(500, lambda: self.load_note(self.current_index + 1))
        
        except Exception as e:
            self.results_label.config(
                text=f"✗ Error deleting note: {e}",
                foreground="red"
            )


class BoilerplateAttachmentTriage:
    """Main class for triaging notes with boilerplate attachments."""
    
    def __init__(self, vault_path: str, dry_run: bool = True, min_attachments: int = 5):
        self.vault_path = Path(vault_path)
        self.attachments_path = self.vault_path / "Attachments"
        self.dry_run = dry_run
        self.min_attachments = min_attachments
        self.trash_path = self.vault_path / ".trash"
        
        # Statistics
        self.stats = {
            'notes_scanned': 0,
            'notes_with_many_attachments': 0,
            'notes_tagged_triage': 0,
            'notes_cleaned': 0,
            'notes_deleted': 0,
            'attachments_deleted': 0,
            'references_removed': 0
        }
        
        # Pattern for macOS screenshots: "Screen Shot YYYY-MM-DD at HH.MM.SS AM/PM.png"
        # or "Screenshot YYYY-MM-DD at HH.MM.SS AM/PM.png"
        self.macos_screenshot_pattern = re.compile(
            r'^Screen(?:shot)?\s+\d{4}-\d{2}-\d{2}\s+at\s+\d+\.\d+\.\d+\s+(AM|PM)\.(png|jpg|jpeg)$',
            re.IGNORECASE
        )
        
        # Pattern for Windows screenshots: "Screenshot (1).png" or "Screenshot YYYY-MM-DD HHMMSS.png"
        self.windows_screenshot_pattern = re.compile(
            r'^Screenshot(?:\s+\(\d+\)|\s+\d{4}-\d{2}-\d{2}\s+\d{6})?\.(png|jpg|jpeg)$',
            re.IGNORECASE
        )
        
        # Additional discovered patterns from vault analysis
        self.discovered_patterns: List[re.Pattern] = []
        self.use_vault_patterns = False
        
        # Store notes to tag
        self.notes_to_triage: List[Tuple[Path, List[Path], int, int]] = []  # (note, attachments, total, screenshots)
        
        # Store notes to clean (already triaged)
        self.triaged_notes: List[Path] = []
        
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
    
    def analyze_vault_patterns(self):
        """
        Analyze vault attachments to discover screenshot patterns.
        Uses AttachmentStats to identify common screenshot naming conventions.
        """
        if not AttachmentStats:
            print("  ⚠️  Cannot analyze patterns: attachment_stats module not available")
            return
        
        print("  🧠 Analyzing vault to discover screenshot patterns...", flush=True)
        print("  Step 1/2: Scanning all attachments...", flush=True)
        try:
            stats = AttachmentStats(str(self.vault_path))
            stats.analyze_attachments()
            print("  Step 2/2: Analyzing filename patterns...", flush=True)
            pattern_analysis = stats.analyze_filename_patterns()
            
            if not pattern_analysis:
                print("  ⚠️  No pattern analysis results")
                return
            
            # Extract discovered patterns and create regex patterns
            discovered_info = pattern_analysis.get('discovered_patterns', [])
            top_words = pattern_analysis.get('top_words', [])
            likely_patterns = pattern_analysis.get('likely_screenshot_patterns', [])
            
            # Build regex patterns from discovered patterns
            new_patterns = []
            
            # Pattern 1: Files with IMG_ or img_ prefix followed by numbers
            img_pattern_count = sum(1 for f in likely_patterns if re.match(r'^IMG[_\-]\d+', f, re.IGNORECASE))
            if img_pattern_count > 10:  # If common enough
                new_patterns.append(re.compile(r'^IMG[_\-]\d+.*\.(png|jpg|jpeg)$', re.IGNORECASE))
                print(f"    ✓ Discovered pattern: IMG_* numbered files ({img_pattern_count} examples)")
            
            # Pattern 2: Common words that appear frequently with screenshots
            screenshot_keywords = {'screenshot', 'screen', 'shot', 'img', 'image', 'photo', 'pic', 'snap', 'capture'}
            common_screenshot_words = [(word, count) for word, count in top_words if word in screenshot_keywords]
            
            for word, count in common_screenshot_words[:5]:  # Top 5
                if count > 20:  # Common enough
                    # Pattern: word + optional separator + numbers
                    pattern = re.compile(
                        rf'^{re.escape(word)}[_\- ]?\d+.*\.(png|jpg|jpeg)$',
                        re.IGNORECASE
                    )
                    new_patterns.append(pattern)
                    print(f"    ✓ Discovered pattern: {word}* numbered files ({count} examples)")
            
            # Pattern 3: Date-time patterns (YYYY-MM-DD HH.MM.SS or variations)
            date_time_examples = [f for f in likely_patterns if re.search(r'\d{4}[_-]\d{2}[_-]\d{2}', f)]
            if len(date_time_examples) > 10:
                # More flexible date-time pattern
                new_patterns.append(re.compile(
                    r'^.*\d{4}[_-]\d{2}[_-]\d{2}.*\d+[\.:]\d+[\.:]\d+.*\.(png|jpg|jpeg)$',
                    re.IGNORECASE
                ))
                print(f"    ✓ Discovered pattern: date-time format files ({len(date_time_examples)} examples)")
            
            # Pattern 4: Files with screenshot words and underscore/number separators
            underscore_patterns = [f for f in likely_patterns 
                                 if any(word in f.lower() for word in screenshot_keywords) 
                                 and ('_' in f or re.search(r'\d', f))]
            if len(underscore_patterns) > 15:
                # Pattern: screenshot_word + _ + numbers or date
                new_patterns.append(re.compile(
                    r'^(screenshot|screen|shot|img|image|photo|pic|snap)[_\-]\d+.*\.(png|jpg|jpeg)$',
                    re.IGNORECASE
                ))
                print(f"    ✓ Discovered pattern: screenshot_word_separator_number ({len(underscore_patterns)} examples)")
            
            self.discovered_patterns = new_patterns
            self.use_vault_patterns = len(new_patterns) > 0
            
            if self.use_vault_patterns:
                print(f"  ✓ Loaded {len(new_patterns)} vault-specific screenshot pattern(s)")
            else:
                print("  ℹ️  Using default patterns only")
        
        except Exception as e:
            print(f"  ⚠️  Error analyzing vault patterns: {e}")
            print("  ℹ️  Continuing with default patterns")
    
    def is_screenshot(self, filename: str) -> bool:
        """
        Determine if a filename looks like a screenshot (macOS or Windows).
        Screenshots have predictable naming patterns, unlike boilerplate web clipper images.
        Uses both predefined patterns and discovered vault-specific patterns.
        """
        # Check macOS screenshot patterns
        if self.macos_screenshot_pattern.match(filename):
            return True
        
        # Check Windows screenshot patterns
        if self.windows_screenshot_pattern.match(filename):
            return True
        
        # Additional built-in patterns: common screenshot names
        screenshot_patterns = [
            r'^Screenshot_\d{8}_\d{6}\.(png|jpg|jpeg)$',  # Some tools
            r'^screenshot-\d{8}-\d{6}\.(png|jpg|jpeg)$',  # Another variant
            r'^IMG_\d{8}_\d{6}\.(png|jpg|jpeg)$',  # Some Android/iOS patterns
            r'^Photo_\d{8}_\d{6}\.(png|jpg|jpeg)$',  # Photo patterns
            r'^P\d{8}_\d{6}\.(png|jpg|jpeg)$',  # Short photo pattern
        ]
        
        for pattern in screenshot_patterns:
            if re.match(pattern, filename, re.IGNORECASE):
                return True
        
        # Check discovered vault-specific patterns
        if self.use_vault_patterns:
            for pattern in self.discovered_patterns:
                if pattern.match(filename):
                    return True
        
        return False
    
    def find_attachments_for_note(self, note: Path) -> List[Path]:
        """
        Find all attachments referenced in a note.
        Returns list of attachment file paths.
        """
        if not self.attachments_path.exists():
            return []
        
        try:
            content = note.read_text(encoding='utf-8', errors='ignore')
        except Exception as e:
            print(f"  ⚠️  Error reading note {note}: {e}")
            return []
        
        referenced_attachments = []
        
        # Build filename lookup map for fast searches
        filename_to_paths = defaultdict(list)
        for attachment_file in self.attachments_path.rglob("*"):
            if attachment_file.is_file():
                filename_to_paths[attachment_file.name].append(attachment_file)
        
        # Look for markdown image/link syntax: ![[image.png]] or [[file.pdf]]
        pattern = r'\[\[([^\]]+)\]\]'
        matches = re.findall(pattern, content)
        
        # Check markdown image syntax: ![](Attachments/image.png)
        md_image_pattern = r'!\[([^\]]*)\]\(([^)]+)\)'
        md_matches = re.findall(md_image_pattern, content)
        
        # Process [[link]] style references
        seen_paths = set()
        for match in matches:
            # Remove Obsidian aliases (|alias)
            match = match.split('|')[0]
            
            # If path contains attachments/ or Attachments/, extract the file part
            parts = re.split(r'(?i)attachments/', match)
            if len(parts) > 1:
                file_part = parts[-1]
                file_part = re.sub(r'\.\./', '', file_part)  # Remove relative paths
                attachment = self.attachments_path / file_part
                if attachment.exists() and attachment.is_file():
                    path_str = str(attachment)
                    if path_str not in seen_paths:
                        referenced_attachments.append(attachment)
                        seen_paths.add(path_str)
            else:
                # Direct reference by filename
                if match in filename_to_paths:
                    for attachment_file in filename_to_paths[match]:
                        path_str = str(attachment_file)
                        if path_str not in seen_paths:
                            referenced_attachments.append(attachment_file)
                            seen_paths.add(path_str)
        
        # Process markdown image syntax
        for alt, link in md_matches:
            parts = re.split(r'(?i)attachments/', link)
            if len(parts) > 1:
                rel_path_str = parts[-1].split('?')[0]  # Remove query params
                rel_path_str = re.sub(r'\.\./', '', rel_path_str)
                attachment = self.attachments_path / rel_path_str
                if attachment.exists() and attachment.is_file():
                    path_str = str(attachment)
                    if path_str not in seen_paths:
                        referenced_attachments.append(attachment)
                        seen_paths.add(path_str)
        
        return referenced_attachments
    
    def analyze_note_attachments(self, note: Path) -> Tuple[List[Path], int, int]:
        """
        Analyze attachments for a note.
        Returns: (list of attachments, total count, screenshot count)
        """
        attachments = self.find_attachments_for_note(note)
        total_count = len(attachments)
        
        screenshot_count = 0
        for attachment in attachments:
            if self.is_screenshot(attachment.name):
                screenshot_count += 1
        
        return attachments, total_count, screenshot_count
    
    def has_triage_tag(self, note: Path) -> bool:
        """Check if note already has #triage tag."""
        try:
            content = note.read_text(encoding='utf-8', errors='ignore')
            # Check for #triage tag (can be anywhere, but often at top or in frontmatter)
            return '#triage' in content or 'tags: [triage]' in content or 'tags: triage' in content
        except Exception:
            return False
    
    def add_triage_tag(self, note: Path) -> bool:
        """Add #triage tag to note (prepend to frontmatter or add at top)."""
        if self.dry_run:
            print(f"  [DRY RUN] Would add #triage tag to: {note.name}")
            return True
        
        try:
            content = note.read_text(encoding='utf-8', errors='ignore')
            
            # Check if already has triage tag
            if self.has_triage_tag(note):
                return False
            
            # Try to add to frontmatter if it exists
            frontmatter_match = re.match(r'^---\n(.*?)\n---\n(.*)$', content, re.DOTALL)
            if frontmatter_match:
                frontmatter = frontmatter_match.group(1)
                body = frontmatter_match.group(2)
                
                # Add tags field if it doesn't exist
                if 'tags:' in frontmatter:
                    # Add to existing tags
                    frontmatter = re.sub(
                        r'tags:\s*\[([^\]]+)\]',
                        lambda m: f'tags: [{m.group(1)}, triage]' if 'triage' not in m.group(1) else m.group(0),
                        frontmatter
                    )
                    frontmatter = re.sub(
                        r'tags:\s*([^\n]+)',
                        lambda m: f'tags: [{m.group(1)}, triage]' if 'triage' not in m.group(1) else m.group(0),
                        frontmatter
                    )
                else:
                    # Add new tags field
                    frontmatter += '\ntags: [triage]'
                
                new_content = f'---\n{frontmatter}\n---\n{body}'
            else:
                # No frontmatter, add tag at top of file
                new_content = f'#triage\n\n{content}'
            
            note.write_text(new_content, encoding='utf-8')
            return True
        except Exception as e:
            print(f"  ✗ Error adding triage tag to {note}: {e}")
            return False
    
    def find_triaged_notes(self) -> List[Path]:
        """Find all notes that have #triage tag."""
        notes = self.get_all_notes()
        triaged = []
        for note in notes:
            if self.has_triage_tag(note):
                triaged.append(note)
        return triaged
    
    def scan_and_tag(self, analyze_patterns: bool = True):
        """
        Scan notes and tag those with boilerplate attachments.
        
        Args:
            analyze_patterns: If True, analyze vault to discover screenshot patterns first
        """
        # Analyze vault patterns first if requested
        if analyze_patterns:
            self.analyze_vault_patterns()
        
        print("\n🔍 Scanning notes for boilerplate attachments...")
        notes = self.get_all_notes()
        self.stats['notes_scanned'] = len(notes)
        
        print(f"Found {len(notes)} note(s)")
        print(f"Looking for notes with >={self.min_attachments} attachments...")
        print("=" * 70)
        
        for idx, note in enumerate(notes, 1):
            if idx % 50 == 0:
                print(f"  Processed {idx}/{len(notes)} notes... (found {len(self.notes_to_triage)} to triage so far)", flush=True)
            
            attachments, total_count, screenshot_count = self.analyze_note_attachments(note)
            
            if total_count >= self.min_attachments:
                self.stats['notes_with_many_attachments'] += 1
                
                # Determine if mostly boilerplate (non-screenshot)
                boilerplate_count = total_count - screenshot_count
                
                # If most attachments are NOT screenshots, it's likely boilerplate
                # Use threshold: if < 30% are screenshots, consider it boilerplate
                if screenshot_count / total_count < 0.3:
                    self.notes_to_triage.append((note, attachments, total_count, screenshot_count))
                    rel_path = note.relative_to(self.vault_path)
                    print(f"  → Found candidate: {rel_path} ({total_count} attachments, {screenshot_count} screenshots, {boilerplate_count} boilerplate)", flush=True)
        
        print(f"\nFound {len(self.notes_to_triage)} note(s) with mostly boilerplate attachments")
        print("=" * 70)
        
        # Display notes to tag
        for idx, (note, attachments, total, screenshots) in enumerate(self.notes_to_triage, 1):
            rel_path = note.relative_to(self.vault_path)
            boilerplate = total - screenshots
            print(f"\n{idx}. {rel_path}")
            print(f"   Total attachments: {total}")
            print(f"   Screenshots: {screenshots}")
            print(f"   Boilerplate: {boilerplate}")
            
            # Show sample attachment names
            print(f"   Sample attachments:")
            for att in attachments[:5]:
                is_screenshot = "📸" if self.is_screenshot(att.name) else "📎"
                rel_att = att.relative_to(self.attachments_path)
                print(f"     {is_screenshot} {rel_att}")
            if len(attachments) > 5:
                print(f"     ... and {len(attachments) - 5} more")
        
        # Tag notes or show GUI
        if self.notes_to_triage:
            # Limit notes for testing if requested
            if hasattr(self, '_test_limit') and self._test_limit:
                self.notes_to_triage = self.notes_to_triage[:self._test_limit]
                print(f"\n⚠️  TEST MODE: Processing only first {len(self.notes_to_triage)} note(s)")
            
            # Show GUI if tkinter available and (not dry-run OR test mode)
            if TKINTER_AVAILABLE and (not self.dry_run or (hasattr(self, '_test_limit') and self._test_limit)):
                # Use GUI for interactive triage
                print("\n" + "=" * 70)
                print("🖥️  Launching GUI for interactive triage...")
                print("=" * 70)
                print(f"Found {len(self.notes_to_triage)} note(s) to review")
                print("GUI will show each note with its attachments for review.")
                if self.dry_run:
                    print("⚠️  DRY-RUN MODE: No changes will be made to files")
                print()
                
                root = tk.Tk()
                gui = TriageGUI(root, self)
                root.mainloop()
                
                # Print summary after GUI closes
                print("\n" + "=" * 70)
                print("📊 TRIAGE SUMMARY:")
                print("=" * 70)
                print(f"  Notes cleaned: {self.stats['notes_cleaned']}")
                print(f"  Notes deleted: {self.stats['notes_deleted']}")
                print(f"  Attachments deleted: {self.stats['attachments_deleted']}")
                print(f"  References removed: {self.stats['references_removed']}")
                print("=" * 70)
            else:
                # Tag notes (non-interactive or dry-run)
                if self.dry_run:
                    print("\n" + "=" * 70)
                    print("🏷️  TAGGING NOTES (DRY RUN)...")
                    print("=" * 70)
                else:
                    print("\n" + "=" * 70)
                    print("🏷️  TAGGING NOTES...")
                    print("=" * 70)
                    if not TKINTER_AVAILABLE:
                        print("⚠️  tkinter not available, falling back to automatic tagging")
                        print("   Install tkinter for interactive GUI triage")
                
                for note, attachments, total, screenshots in self.notes_to_triage:
                    if self.add_triage_tag(note):
                        self.stats['notes_tagged_triage'] += 1
        
        print("\n" + "=" * 70)
        print("📊 SUMMARY:")
        print(f"  Notes scanned: {self.stats['notes_scanned']}")
        print(f"  Notes with >={self.min_attachments} attachments: {self.stats['notes_with_many_attachments']}")
        print(f"  Notes tagged as triage: {self.stats['notes_tagged_triage']}")
    
    def remove_attachment_references(self, note: Path, attachment_paths: List[Path]) -> int:
        """
        Remove all references to attachments from note content.
        Returns number of references removed.
        """
        try:
            # Check if note file exists
            if not note.exists():
                print(f"    ⚠️  Note file does not exist: {note}")
                return 0
            
            content = note.read_text(encoding='utf-8', errors='ignore')
            original_content = content
            references_removed = 0
            
            # Build set of filenames and relative paths to remove
            attachment_names = {att.name for att in attachment_paths}
            attachment_rel_paths = set()
            for att in attachment_paths:
                try:
                    rel_path = str(att.relative_to(self.attachments_path)).replace('\\', '/')
                    attachment_rel_paths.add(rel_path)
                    # Also add with Attachments/ prefix
                    attachment_rel_paths.add(f'Attachments/{rel_path}')
                    attachment_rel_paths.add(f'attachments/{rel_path}')
                except ValueError:
                    pass
            
            # Remove markdown image/link syntax: ![[image.png]] or [[file.pdf]]
            for attachment_name in attachment_names:
                try:
                    escaped_name = re.escape(attachment_name)
                    
                    # Remove both ![[filename]] and [[filename]] patterns
                    # Pattern matches: optional !, then [[ followed by anything containing filename, then ]]
                    pattern = r'!?\[\[[^\]]*' + escaped_name + r'[^\]]*\]\]'
                    matches_before = len(re.findall(pattern, content))
                    if matches_before > 0:
                        content = re.sub(pattern, '', content)
                        references_removed += matches_before
                except re.error as e:
                    print(f"    ⚠️  Regex error for {attachment_name}: {e}")
                    # Fallback: simple string replacement for this attachment
                    old_content = content
                    content = content.replace(f'![[{attachment_name}]]', '')
                    content = content.replace(f'[[{attachment_name}]]', '')
                    if content != old_content:
                        references_removed += 1
            
            # Remove markdown image syntax: ![](Attachments/image.png)
            for rel_path in attachment_rel_paths:
                try:
                    escaped_path = re.escape(rel_path)
                    # Pattern: ![alt](path) where path contains our attachment path
                    pattern = r'!\[[^\]]*\]\([^)]*' + escaped_path + r'[^)]*\)'
                    matches_before = len(re.findall(pattern, content))
                    if matches_before > 0:
                        content = re.sub(pattern, '', content)
                        references_removed += matches_before
                except re.error as e:
                    print(f"    ⚠️  Regex error for path {rel_path}: {e}")
                    # Fallback: simple string replacement
                    content = content.replace(f'({rel_path})', '')
                    references_removed += 1
            
            # Clean up empty lines (remove triple+ newlines)
            content = re.sub(r'\n\n\n+', '\n\n', content)
            
            if content != original_content:
                if not self.dry_run:
                    note.write_text(content, encoding='utf-8')
                return references_removed
        
        except Exception as e:
            print(f"  ✗ Error removing references from {note}: {e}")
        
        return 0
    
    def move_attachment_to_trash(self, attachment: Path) -> bool:
        """Move an attachment to the trash directory."""
        if self.dry_run:
            rel_path = attachment.relative_to(self.attachments_path)
            print(f"    [DRY RUN] Would move to trash: {rel_path}")
            return True
        
        try:
            # Create a subdirectory in trash for this run
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            run_trash = self.trash_path / f"boilerplate_attachments_{timestamp}"
            run_trash.mkdir(parents=True, exist_ok=True)
            
            dest = run_trash / attachment.name
            
            # Handle name collisions
            counter = 1
            while dest.exists():
                stem = attachment.stem
                ext = attachment.suffix
                dest = run_trash / f"{stem}_{counter}{ext}"
                counter += 1
            
            shutil.move(str(attachment), str(dest))
            return True
        except Exception as e:
            print(f"    ✗ Error moving {attachment} to trash: {e}")
            return False
    
    def clean_triaged_notes(self):
        """Clean up triaged notes by removing attachments and references."""
        print("🧹 Finding triaged notes to clean...")
        triaged_notes = self.find_triaged_notes()
        
        if not triaged_notes:
            print("No triaged notes found!")
            return
        
        print(f"Found {len(triaged_notes)} triaged note(s)")
        print("=" * 70)
        
        for note in triaged_notes:
            print(f"\n📝 Processing: {note.relative_to(self.vault_path)}")
            attachments = self.find_attachments_for_note(note)
            
            if not attachments:
                print("  No attachments found, skipping...")
                continue
            
            # Count screenshots vs boilerplate
            screenshot_count = sum(1 for att in attachments if self.is_screenshot(att.name))
            boilerplate_attachments = [att for att in attachments if not self.is_screenshot(att.name)]
            
            print(f"  Total attachments: {len(attachments)}")
            print(f"  Screenshots: {screenshot_count}")
            print(f"  Boilerplate to remove: {len(boilerplate_attachments)}")
            
            if boilerplate_attachments:
                # Remove references
                refs_removed = self.remove_attachment_references(note, boilerplate_attachments)
                if refs_removed > 0:
                    self.stats['references_removed'] += refs_removed
                    print(f"  ✓ Removed {refs_removed} reference(s) from note")
                
                # Move attachments to trash
                print(f"  Moving {len(boilerplate_attachments)} attachment(s) to trash...")
                for attachment in boilerplate_attachments:
                    if self.move_attachment_to_trash(attachment):
                        self.stats['attachments_deleted'] += 1
                
                self.stats['notes_cleaned'] += 1
        
        print("\n" + "=" * 70)
        print("📊 CLEANUP SUMMARY:")
        print(f"  Notes cleaned: {self.stats['notes_cleaned']}")
        print(f"  Attachments deleted: {self.stats['attachments_deleted']}")
        print(f"  References removed: {self.stats['references_removed']}")
    
    def run(self, mode: str = 'scan', analyze_patterns: bool = True, test_limit: Optional[int] = None):
        """
        Main execution logic.
        mode: 'scan' to identify and tag notes, 'clean' to clean triaged notes
        analyze_patterns: If True, analyze vault patterns before scanning (only for scan mode)
        test_limit: If set, limit the number of notes to process (for testing)
        """
        print("🧹 Obsidian Boilerplate Attachment Triage Tool")
        print(f"Vault: {self.vault_path}")
        print("=" * 70)
        
        self.setup_trash()
        
        if mode == 'scan':
            self.scan_and_tag(analyze_patterns=analyze_patterns)
        elif mode == 'clean':
            self.clean_triaged_notes()
        else:
            print(f"Unknown mode: {mode}")


def main():
    parser = argparse.ArgumentParser(
        description="Identify and clean boilerplate attachments in Obsidian notes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Scan and tag notes with boilerplate attachments (dry run)
  python triage_boilerplate_attachments.py --vault /path/to/vault scan
  
  # Scan and use interactive GUI to triage notes (when --no-dry-run)
  python triage_boilerplate_attachments.py --vault /path/to/vault scan --no-dry-run
  # The GUI will show each note with preview and attachments.
  # Use "Clean" to remove attachments or "Keep" to skip.
  # Keyboard shortcuts: Enter/K = Keep, Space/C = Clean
  
  # Test GUI with only first 3 notes (safe dry-run mode - no changes made)
  python triage_boilerplate_attachments.py --vault /path/to/vault scan --test-gui 3
  
  # Test GUI with actual changes (limited to first 3 notes)
  python triage_boilerplate_attachments.py --vault /path/to/vault scan --no-dry-run --test-gui 3
  
  # Clean triaged notes (remove boilerplate attachments and references)
  python triage_boilerplate_attachments.py --vault /path/to/vault clean --no-dry-run
  
  # Use custom minimum attachment threshold
  python triage_boilerplate_attachments.py --vault /path/to/vault scan --min-attachments 10
        """
    )
    
    parser.add_argument(
        'mode',
        choices=['scan', 'clean'],
        help='Operation mode: "scan" to identify and tag notes, "clean" to clean triaged notes'
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
        help='Allow actual changes (default is dry-run mode)'
    )
    
    parser.add_argument(
        '--min-attachments',
        type=int,
        default=5,
        help='Minimum number of attachments to consider a note (default: 5)'
    )
    
    parser.add_argument(
        '--skip-pattern-analysis',
        action='store_true',
        help='Skip vault pattern analysis (uses default patterns only)'
    )
    
    parser.add_argument(
        '--test-gui',
        type=int,
        metavar='N',
        help='Test GUI with only the first N notes (for testing)'
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
    
    # Run tool
    triage = BoilerplateAttachmentTriage(
        vault_path,
        dry_run=not args.no_dry_run,
        min_attachments=args.min_attachments
    )
    
    # Set test limit if provided
    if args.test_gui and args.test_gui > 0:
        triage._test_limit = args.test_gui
        # In test mode with dry-run, show GUI but don't actually delete anything
        if not args.no_dry_run:
            print(f"⚠️  TEST MODE: GUI will be shown but no changes will be made (dry-run)")
        else:
            print(f"⚠️  TEST MODE: GUI will make actual changes (non-dry-run)")
    
    triage.run(mode=args.mode, analyze_patterns=not args.skip_pattern_analysis)
    
    return 0


if __name__ == "__main__":
    exit(main())

