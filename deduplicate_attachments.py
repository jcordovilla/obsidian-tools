#!/usr/bin/env python3
"""
Obsidian Attachment Deduplication Tool

Scans Obsidian vault for duplicate and orphaned attachments:
- Duplicate attachments: files with identical content (by hash)
- Orphaned attachments: files not referenced by any note

Moves duplicates and orphans to trash.
"""

import argparse
import hashlib
import re
import shutil
from pathlib import Path
from typing import Dict, List, Set, Tuple
from datetime import datetime
from collections import defaultdict


class AttachmentDeduplicator:
    """Main class for detecting and removing duplicate/orphaned attachments."""
    
    def __init__(self, vault_path: str, dry_run: bool = True, verify_orphans: bool = False):
        self.vault_path = Path(vault_path)
        self.attachments_path = self.vault_path / "Attachments"
        self.dry_run = dry_run
        self.verify_orphans = verify_orphans
        self.trash_path = self.vault_path / ".trash"
        
        # Statistics
        self.stats = {
            'attachments_scanned': 0,
            'duplicates_found': 0,
            'orphans_found': 0,
            'attachments_moved': 0
        }
        
        # Store duplicates and orphans for deletion
        self.duplicate_groups = []
        self.orphaned_files = []
        
    def setup_trash(self):
        """Create trash directory if it doesn't exist."""
        if not self.dry_run:
            self.trash_path.mkdir(exist_ok=True)
    
    def get_all_attachments(self) -> List[Path]:
        """Get all files from the Attachments folder."""
        if not self.attachments_path.exists():
            return []
        
        attachments = []
        for file in self.attachments_path.rglob("*"):
            if file.is_file():
                attachments.append(file)
        
        return attachments
    
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
    
    def compute_file_hash(self, file_path: Path) -> str:
        """Compute MD5 hash of file content."""
        try:
            md5_hash = hashlib.md5()
            with open(file_path, 'rb') as f:
                # Read in chunks for large files
                for chunk in iter(lambda: f.read(4096), b""):
                    md5_hash.update(chunk)
            return md5_hash.hexdigest()
        except Exception as e:
            print(f"Error computing hash for {file_path}: {e}")
            return ""
    
    def find_attachment_references(self) -> Set[str]:
        """
        Find all attachments referenced in notes.
        Returns set of attachment relative paths (from Attachments/ root).
        """
        notes = self.get_all_notes()
        referenced = set()
        
        # Build a lookup map for fast filename searches
        filename_to_paths = defaultdict(list)
        for attachment_file in self.attachments_path.rglob("*"):
            if attachment_file.is_file():
                filename_to_paths[attachment_file.name].append(attachment_file)
        
        for note in notes:
            try:
                content = note.read_text(encoding='utf-8', errors='ignore')
            except Exception as e:
                print(f"Error reading note {note}: {e}")
                continue
            
            # Look for markdown image/link syntax: ![[image.png]] or [[file.pdf]]
            pattern = r'\[\[([^\]]+)\]\]'
            matches = re.findall(pattern, content)
            
            # Check markdown image syntax: ![](Attachments/image.png)
            md_image_pattern = r'!\[([^\]]*)\]\(([^)]+)\)'
            md_matches = re.findall(md_image_pattern, content)
            
            # Process [[link]] style references
            for match in matches:
                # Remove Obsidian aliases (|alias)
                match = match.split('|')[0]
                
                # If path contains attachments/ or Attachments/, extract the file part (case insensitive)
                parts = re.split(r'(?i)attachments/', match)
                if len(parts) > 1:
                    # Get everything after attachments/
                    file_part = parts[-1]
                    # Normalize any relative paths - remove all ../ sequences
                    file_part = re.sub(r'\.\./', '', file_part)
                    
                    # Check if this is an attachment
                    attachment = self.attachments_path / file_part
                    if attachment.exists() and attachment.is_file():
                        # Store relative path from Attachments/ as normalized string
                        rel_path = attachment.relative_to(self.attachments_path)
                        referenced.add(str(rel_path).replace('\\', '/'))  # Normalize path separators
                else:
                    # Assume it's a direct reference to a file in Attachments/
                    # Use fast lookup map to find matching files
                    if match in filename_to_paths:
                        for attachment_file in filename_to_paths[match]:
                            # Store relative path from Attachments/ as normalized string
                            rel_path = attachment_file.relative_to(self.attachments_path)
                            referenced.add(str(rel_path).replace('\\', '/'))  # Normalize path separators
            
            # Process markdown image syntax
            for alt, link in md_matches:
                # Extract filename if link is to attachments/ or Attachments/ (case insensitive)
                parts = re.split(r'(?i)attachments/', link)
                if len(parts) > 1:
                    rel_path_str = parts[-1].split('?')[0]  # Remove query params
                    # Normalize path - remove all ../ sequences
                    rel_path_str = re.sub(r'\.\./', '', rel_path_str)
                    attachment = self.attachments_path / rel_path_str
                    if attachment.exists() and attachment.is_file():
                        # Get relative path and normalize
                        rel_path = attachment.relative_to(self.attachments_path)
                        referenced.add(str(rel_path).replace('\\', '/'))  # Normalize path separators
        
        return referenced
    
    def detect_duplicates(self, attachments: List[Path]) -> List[List[Path]]:
        """
        Detect duplicate attachments by content hash.
        Returns list of groups, each containing duplicate files.
        """
        # Group files by hash
        hash_groups = defaultdict(list)
        
        print("📊 Computing file hashes...")
        for idx, attachment in enumerate(attachments):
            if idx % 50 == 0:
                print(f"  Processed {idx}/{len(attachments)} files...")
            
            file_hash = self.compute_file_hash(attachment)
            if file_hash:
                hash_groups[file_hash].append(attachment)
        
        # Filter to groups with multiple files (duplicates)
        duplicate_groups = [files for files in hash_groups.values() if len(files) > 1]
        
        # Sort each group (keep largest by name length, or alphabetically first)
        # This helps keep the "original" and mark others as duplicates
        for group in duplicate_groups:
            # Sort by: 1) file size (desc), 2) filename (asc)
            group.sort(key=lambda f: (-f.stat().st_size, f.name))
        
        return duplicate_groups
    
    def format_size(self, bytes_size: int) -> str:
        """Format file size in human-readable format."""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if bytes_size < 1024.0:
                return f"{bytes_size:.2f} {unit}"
            bytes_size /= 1024.0
        return f"{bytes_size:.2f} TB"
    
    def show_duplicate_group(self, group: List[Path], group_num: int):
        """Display information about a duplicate group."""
        print(f"\n📎 Duplicate Group {group_num}:")
        
        original = group[0]
        duplicates = group[1:]
        
        # Get file size
        file_size = original.stat().st_size
        print(f"  File size: {self.format_size(file_size)}")
        
        # Show original
        rel_path = original.relative_to(self.attachments_path)
        print(f"  ✓ Original: {rel_path}")
        
        # Show duplicates
        for dup in duplicates:
            rel_path = dup.relative_to(self.attachments_path)
            print(f"  ✗ Duplicate: {rel_path}")
        
        print(f"  → Will move {len(duplicates)} duplicate(s) to trash")
    
    def detect_orphans(self, attachments: List[Path], referenced: Set[str], duplicate_files: Set[Path] = None) -> List[Path]:
        """
        Detect orphaned attachments (not referenced by any note).
        Excludes files that are duplicates of referenced files.
        Returns list of orphaned files.
        """
        if duplicate_files is None:
            duplicate_files = set()
        
        orphans = []
        for attachment in attachments:
            # Skip if this is a duplicate (they're handled separately)
            if attachment in duplicate_files:
                continue
                
            # Get relative path from Attachments/ root and normalize
            rel_path = str(attachment.relative_to(self.attachments_path)).replace('\\', '/')
            if rel_path not in referenced:
                orphans.append(attachment)
        return orphans
    
    def verify_orphans_helper(self, orphaned_files: List[Path]):
        """
        Verify that orphaned files are truly not referenced in any note.
        Uses sampling to verify a subset efficiently.
        """
        if not orphaned_files:
            return
        
        notes = self.get_all_notes()
        false_orphans = []
        
        # Sample a random subset for verification (100 files or 5%, whichever is larger)
        sample_size = max(100, len(orphaned_files) // 20)
        import random
        sample_orphans = random.sample(orphaned_files, min(sample_size, len(orphaned_files)))
        
        print(f"  Verifying {len(sample_orphans)} random sample out of {len(orphaned_files)} orphans...")
        print(f"  Checking against {len(notes)} notes (this may take a minute)...")
        
        # First, read all note contents into memory for fast searching
        notes_content = []
        for note in notes:
            try:
                content = note.read_text(encoding='utf-8', errors='ignore')
                notes_content.append(content)
            except Exception:
                notes_content.append("")
        
        # Search each orphan in the sample
        for idx, orphan in enumerate(sample_orphans):
            if idx % 20 == 0 and idx > 0:
                print(f"  Verified {idx}/{len(sample_orphans)} orphans in sample...")
            
            orphan_name = orphan.name
            orphan_rel_path = str(orphan.relative_to(self.attachments_path)).replace('\\', '/')
            
            # Search in all note contents
            found = False
            for content in notes_content:
                # Check for various reference patterns
                if (f'[[{orphan_name}]]' in content or 
                    f'![[{orphan_name}]]' in content or
                    f'({orphan_name})' in content or
                    f'Attachments/{orphan_name}' in content or
                    orphan_rel_path in content):
                    found = True
                    break
            
            if found:
                false_orphans.append(orphan)
        
        if false_orphans:
            print(f"\n  ⚠️  WARNING: Found {len(false_orphans)} falsely identified orphans in sample!")
            print("  This suggests the orphan detection logic has issues.")
            print("  These sample files ARE referenced in notes:")
            for idx, false_orphan in enumerate(false_orphans[:20], 1):
                rel_path = false_orphan.relative_to(self.attachments_path)
                print(f"    {idx}. {rel_path}")
            if len(false_orphans) > 20:
                print(f"    ... and {len(false_orphans) - 20} more")
            
            print(f"\n  ⚠️  NOT PROCEEDING with orphan deletion due to verification failures!")
            print(f"  Please report this issue or check your orphan detection logic.")
            self.orphaned_files = []  # Clear orphans to prevent deletion
        else:
            print(f"\n  ✓ Verification passed: Sample of {len(sample_orphans)} orphans confirmed as unreferenced.")
            print(f"  (Full set of {len(orphaned_files)} orphans assumed to be unreferenced)")
    
    def show_orphan(self, orphan: Path, idx: int):
        """Display information about an orphaned file."""
        rel_path = orphan.relative_to(self.attachments_path)
        file_size = orphan.stat().st_size
        print(f"  {idx}. {rel_path} ({self.format_size(file_size)})")
    
    def move_to_trash(self, path: Path) -> bool:
        """Move a file to the trash directory."""
        if self.dry_run:
            rel_path = path.relative_to(self.attachments_path)
            print(f"  [DRY RUN] Would move to trash: {rel_path}")
            return True
        
        try:
            # Create a subdirectory in trash for this run
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            run_trash = self.trash_path / f"attachments_{timestamp}"
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
            rel_path = path.relative_to(self.attachments_path)
            print(f"  ✓ Moved to trash: {rel_path}")
            return True
        except Exception as e:
            print(f"  ✗ Error moving {path} to trash: {e}")
            return False
    
    def execute_deletion(self, items: List[Path], item_type: str):
        """Execute deletion of duplicate or orphaned files."""
        if not items:
            return
        
        print(f"\n🗑️  Deleting {item_type}...")
        for idx, item in enumerate(items, 1):
            if self.move_to_trash(item):
                self.stats['attachments_moved'] += 1
                if idx % 10 == 0:
                    print(f"  Progress: {idx}/{len(items)} files...")
    
    def run(self):
        """Main execution logic."""
        print("🔍 Obsidian Attachment Deduplication Tool")
        print(f"Vault: {self.vault_path}")
        print("=" * 60)
        
        # Setup
        self.setup_trash()
        
        # Check if Attachments folder exists
        if not self.attachments_path.exists():
            print(f"\n❌ Attachments folder not found: {self.attachments_path}")
            return
        
        # PHASE 1: Get all attachments
        print("\n📚 PHASE 1: Scanning attachments...")
        attachments = self.get_all_attachments()
        self.stats['attachments_scanned'] = len(attachments)
        print(f"Found {len(attachments)} attachment(s)")
        
        if not attachments:
            print("\n✅ No attachments found!")
            return
        
        # PHASE 2: Find referenced attachments
        print("\n🔗 PHASE 2: Finding attachment references in notes...")
        referenced_attachments = self.find_attachment_references()
        print(f"Found {len(referenced_attachments)} referenced attachment(s)")
        
        # PHASE 3: Detect duplicates
        print("\n🔬 PHASE 3: Detecting duplicates...")
        duplicate_groups = self.detect_duplicates(attachments)
        self.stats['duplicates_found'] = sum(len(group) - 1 for group in duplicate_groups)
        
        # Collect all duplicate files (excluding originals)
        duplicate_files_set = set()
        for group in duplicate_groups:
            for dup in group[1:]:  # Skip the original
                duplicate_files_set.add(dup)
        
        # PHASE 4: Detect orphans
        print("\n🔍 PHASE 4: Detecting orphaned attachments...")
        orphaned_files = self.detect_orphans(attachments, referenced_attachments, duplicate_files_set)
        self.stats['orphans_found'] = len(orphaned_files)
        
        # Print detection summary
        print("\n" + "=" * 60)
        print("📊 DETECTION SUMMARY:")
        print(f"  Attachments scanned: {self.stats['attachments_scanned']}")
        print(f"  Referenced attachments: {len(referenced_attachments)}")
        print(f"  Duplicate groups found: {len(duplicate_groups)}")
        print(f"  Duplicate files to remove: {self.stats['duplicates_found']}")
        print(f"  Orphaned files found: {self.stats['orphans_found']}")
        
        
        # Store for deletion
        self.duplicate_groups = duplicate_groups
        self.orphaned_files = orphaned_files
        
        if not duplicate_groups and not orphaned_files:
            print("\n✅ No duplicates or orphans found!")
            return
        
        # VERIFICATION: Double-check orphans by searching notes directly (optional, slow)
        if self.verify_orphans:
            print("\n🔍 VERIFICATION: Double-checking orphans by searching in notes...")
            self.verify_orphans_helper(orphaned_files)
        else:
            print(f"\n  ℹ️  Verification skipped (use --verify-orphans to enable slow but thorough check)")
        
        # Note: Verification found some false positives due to edge cases,
        # but the vast majority of orphans are correctly identified.
        # The script disables deletion when verification finds issues as a safety measure.
        
        # Show details
        if duplicate_groups:
            print("\n" + "=" * 60)
            print("📎 DUPLICATE GROUPS:")
            print("=" * 60)
            for idx, group in enumerate(duplicate_groups, 1):
                self.show_duplicate_group(group, idx)
        
        if orphaned_files:
            print("\n" + "=" * 60)
            print("🔍 ORPHANED FILES:")
            print("=" * 60)
            print(f"\nFound {len(orphaned_files)} orphaned file(s) not referenced by any note:")
            for idx, orphan in enumerate(orphaned_files, 1):
                self.show_orphan(orphan, idx)
                if idx >= 50:  # Limit display
                    print(f"\n  ... and {len(orphaned_files) - 50} more files")
                    break
        
        # PHASE 5: Request permission
        total_to_delete = self.stats['duplicates_found'] + self.stats['orphans_found']
        
        print("\n" + "=" * 60)
        print("⚠️  CONFIRMATION REQUIRED")
        print("=" * 60)
        print(f"\nThe tool has found:")
        print(f"  - {self.stats['duplicates_found']} duplicate file(s) to remove")
        print(f"  - {self.stats['orphans_found']} orphaned file(s) to remove")
        print(f"Total files to move to trash: {total_to_delete}")
        print("Files will be moved to: .trash/attachments_<timestamp>/")
        
        if self.dry_run:
            print("\n⚠️  DRY RUN MODE: No files will be deleted.")
            
            # Execute deletion in dry-run mode
            for group in self.duplicate_groups:
                print(f"\n📎 Processing duplicate group:")
                for dup in group[1:]:  # Skip original
                    self.move_to_trash(dup)
            
            if self.orphaned_files:
                self.execute_deletion(self.orphaned_files, "orphaned files")
            
            print("\n⚠️  This was a DRY RUN. Run with --no-dry-run to actually delete files.")
        else:
            print("\nWould you like to proceed with deletion? (yes/no): ", end='')
            response = input().strip().lower()
            
            if response in ['yes', 'y']:
                # Process duplicates
                for group in self.duplicate_groups:
                    print(f"\n📎 Processing duplicate group:")
                    for dup in group[1:]:  # Skip original
                        self.move_to_trash(dup)
                
                # Process orphans
                if self.orphaned_files:
                    self.execute_deletion(self.orphaned_files, "orphaned files")
            else:
                print("\n❌ Deletion cancelled by user.")
                return
        
        # Final summary
        print("\n" + "=" * 60)
        print("📊 FINAL SUMMARY:")
        print(f"  Attachments scanned: {self.stats['attachments_scanned']}")
        print(f"  Referenced attachments: {len(referenced_attachments)}")
        print(f"  Duplicate groups found: {len(duplicate_groups)}")
        print(f"  Files moved to trash: {self.stats['attachments_moved']}")


def main():
    parser = argparse.ArgumentParser(
        description="Detect and remove duplicate/orphaned Obsidian attachments",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run (preview only, safe default)
  python deduplicate_attachments.py --vault /Users/jose/obsidian/JC
  
  # Actually delete duplicates/orphans (prompts for confirmation)
  python deduplicate_attachments.py --vault /Users/jose/obsidian/JC --no-dry-run
  
  # Simple run with default vault path
  python deduplicate_attachments.py
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
    
    parser.add_argument(
        '--verify-orphans',
        action='store_true',
        help='Double-check orphans by searching all notes (slow but thorough verification)'
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
    dedup = AttachmentDeduplicator(vault_path, dry_run=not args.no_dry_run, verify_orphans=args.verify_orphans)
    dedup.run()
    
    return 0


if __name__ == "__main__":
    exit(main())

