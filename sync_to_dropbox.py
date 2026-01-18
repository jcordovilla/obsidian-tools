#!/usr/bin/env python3
"""
Obsidian Vault Sync to Dropbox

Compares the Obsidian vault with a Dropbox backup and syncs changes:
- Copies new files that don't exist in the backup
- Replaces files that have been modified (based on content hash)
- Optionally removes files from backup that no longer exist in source

Uses dry-run mode by default for safety.
"""

import argparse
import hashlib
import shutil
from pathlib import Path
from typing import Dict, List, Tuple, Set
from dataclasses import dataclass

from obsidian_utils import format_size, validate_vault_path


@dataclass
class SyncStats:
    """Track sync operation statistics."""
    files_scanned: int = 0
    files_new: int = 0
    files_modified: int = 0
    files_unchanged: int = 0
    files_deleted: int = 0
    bytes_copied: int = 0
    errors: int = 0


class VaultSync:
    """Sync Obsidian vault to Dropbox backup."""

    # Files/directories to always skip (not worth backing up)
    SKIP_NAMES = {'.DS_Store', '__pycache__', '.git', '.venv', 'node_modules'}

    def __init__(
        self,
        source_path: str,
        backup_path: str,
        dry_run: bool = True,
        delete_orphans: bool = False
    ):
        self.source_path = Path(source_path)
        self.backup_path = Path(backup_path)
        self.dry_run = dry_run
        self.delete_orphans = delete_orphans
        self.stats = SyncStats()

        # Track files for orphan detection
        self.source_files: Set[str] = set()
        self.backup_files: Set[str] = set()

    def should_skip(self, path: Path) -> bool:
        """Check if a path should be skipped."""
        for part in path.parts:
            if part in self.SKIP_NAMES:
                return True
        return False

    def compute_hash(self, file_path: Path) -> str:
        """Compute MD5 hash of file content."""
        try:
            hasher = hashlib.md5()
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except Exception as e:
            print(f"  Error hashing {file_path}: {e}")
            return ""

    def get_all_files(self, root_path: Path) -> Dict[str, Path]:
        """
        Get all files under a root path.

        Returns dict mapping relative path (str) to absolute Path.
        """
        files = {}
        for file_path in root_path.rglob("*"):
            if file_path.is_file():
                rel_path = file_path.relative_to(root_path)
                if not self.should_skip(rel_path):
                    files[str(rel_path)] = file_path
        return files

    def copy_file(self, source: Path, dest: Path) -> bool:
        """Copy a file, creating parent directories as needed."""
        if self.dry_run:
            return True

        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
            return True
        except Exception as e:
            print(f"  Error copying {source} -> {dest}: {e}")
            self.stats.errors += 1
            return False

    def delete_file(self, file_path: Path) -> bool:
        """Delete a file from the backup."""
        if self.dry_run:
            return True

        try:
            file_path.unlink()
            # Remove empty parent directories
            parent = file_path.parent
            while parent != self.backup_path:
                if not any(parent.iterdir()):
                    parent.rmdir()
                    parent = parent.parent
                else:
                    break
            return True
        except Exception as e:
            print(f"  Error deleting {file_path}: {e}")
            self.stats.errors += 1
            return False

    def sync_file(self, rel_path: str, source_files: Dict[str, Path], backup_files: Dict[str, Path]) -> Tuple[str, int]:
        """
        Sync a single file.

        Returns: (action, bytes_copied)
            action: 'new', 'modified', 'unchanged', 'error'
        """
        source_file = source_files[rel_path]
        dest_file = self.backup_path / rel_path

        if rel_path not in backup_files:
            # New file
            file_size = source_file.stat().st_size
            if self.dry_run:
                print(f"  [NEW] {rel_path} ({format_size(file_size)})")
            else:
                print(f"  Copying new: {rel_path}")

            if self.copy_file(source_file, dest_file):
                return ('new', file_size)
            return ('error', 0)

        # File exists in backup - check if modified
        backup_file = backup_files[rel_path]
        source_hash = self.compute_hash(source_file)
        backup_hash = self.compute_hash(backup_file)

        if not source_hash or not backup_hash:
            return ('error', 0)

        if source_hash != backup_hash:
            # File modified
            file_size = source_file.stat().st_size
            if self.dry_run:
                print(f"  [MODIFIED] {rel_path} ({format_size(file_size)})")
            else:
                print(f"  Updating: {rel_path}")

            if self.copy_file(source_file, dest_file):
                return ('modified', file_size)
            return ('error', 0)

        # File unchanged
        return ('unchanged', 0)

    def find_orphans(self, source_files: Dict[str, Path], backup_files: Dict[str, Path]) -> List[str]:
        """Find files in backup that don't exist in source."""
        source_set = set(source_files.keys())
        backup_set = set(backup_files.keys())
        return sorted(backup_set - source_set)

    def run(self):
        """Execute the sync operation."""
        print("🔄 Obsidian Vault Sync to Dropbox")
        print("=" * 60)
        print(f"Source:  {self.source_path}")
        print(f"Backup:  {self.backup_path}")
        print(f"Mode:    {'DRY RUN' if self.dry_run else 'LIVE'}")
        print(f"Delete:  {'Yes' if self.delete_orphans else 'No'}")
        print("=" * 60)

        # Validate paths
        is_valid, error = validate_vault_path(str(self.source_path))
        if not is_valid:
            print(f"\n❌ Error: {error}")
            return 1

        # Create backup directory if it doesn't exist
        if not self.backup_path.exists():
            if self.dry_run:
                print(f"\n[DRY RUN] Would create backup directory: {self.backup_path}")
            else:
                print(f"\nCreating backup directory: {self.backup_path}")
                self.backup_path.mkdir(parents=True, exist_ok=True)

        # Scan files
        print("\n📂 Scanning source vault...")
        source_files = self.get_all_files(self.source_path)
        self.stats.files_scanned = len(source_files)
        print(f"   Found {len(source_files)} files")

        print("\n📂 Scanning backup...")
        backup_files = self.get_all_files(self.backup_path)
        print(f"   Found {len(backup_files)} files")

        # Sync files
        print("\n🔄 Syncing files...")
        new_files = []
        modified_files = []

        for rel_path in sorted(source_files.keys()):
            action, bytes_copied = self.sync_file(rel_path, source_files, backup_files)

            if action == 'new':
                self.stats.files_new += 1
                self.stats.bytes_copied += bytes_copied
                new_files.append(rel_path)
            elif action == 'modified':
                self.stats.files_modified += 1
                self.stats.bytes_copied += bytes_copied
                modified_files.append(rel_path)
            elif action == 'unchanged':
                self.stats.files_unchanged += 1
            # errors are counted in copy_file

        # Handle orphans (files in backup but not in source)
        orphans = self.find_orphans(source_files, backup_files)

        if orphans:
            print(f"\n🗑️  Found {len(orphans)} orphaned files in backup:")
            for rel_path in orphans[:20]:  # Show first 20
                print(f"   {rel_path}")
            if len(orphans) > 20:
                print(f"   ... and {len(orphans) - 20} more")

            if self.delete_orphans:
                print("\n   Deleting orphaned files...")
                for rel_path in orphans:
                    backup_file = self.backup_path / rel_path
                    if self.dry_run:
                        print(f"   [DELETE] {rel_path}")
                    else:
                        print(f"   Deleting: {rel_path}")

                    if self.delete_file(backup_file):
                        self.stats.files_deleted += 1
            else:
                print("\n   Use --delete to remove these files from backup")

        # Summary
        print("\n" + "=" * 60)
        print("📊 SYNC SUMMARY:")
        print(f"   Files scanned:   {self.stats.files_scanned}")
        print(f"   New files:       {self.stats.files_new}")
        print(f"   Modified files:  {self.stats.files_modified}")
        print(f"   Unchanged files: {self.stats.files_unchanged}")
        if self.delete_orphans:
            print(f"   Deleted files:   {self.stats.files_deleted}")
        if orphans and not self.delete_orphans:
            print(f"   Orphaned files:  {len(orphans)} (not deleted)")
        print(f"   Data copied:     {format_size(self.stats.bytes_copied)}")
        if self.stats.errors > 0:
            print(f"   Errors:          {self.stats.errors}")

        if self.dry_run:
            print("\n⚠️  This was a DRY RUN. Run with --no-dry-run to sync files.")
        else:
            print("\n✅ Sync complete!")

        return 0


def main():
    parser = argparse.ArgumentParser(
        description="Sync Obsidian vault to Dropbox backup",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run (preview only, safe default)
  python sync_to_dropbox.py

  # Actually sync files
  python sync_to_dropbox.py --no-dry-run

  # Sync and delete orphaned files from backup
  python sync_to_dropbox.py --no-dry-run --delete

  # Use custom paths
  python sync_to_dropbox.py --source /path/to/vault --backup /path/to/backup
        """
    )

    parser.add_argument(
        '--source',
        type=str,
        default='/Users/jose/obsidian/JC',
        help='Path to source Obsidian vault (default: /Users/jose/obsidian/JC)'
    )

    parser.add_argument(
        '--backup',
        type=str,
        default='/Users/jose/Dropbox/_Copia Seguridad/obsidian_JC',
        help='Path to Dropbox backup folder (default: /Users/jose/Dropbox/_Copia Seguridad/obsidian_JC)'
    )

    parser.add_argument(
        '--no-dry-run',
        action='store_true',
        help='Actually sync files. Default is dry-run mode (preview only).'
    )

    parser.add_argument(
        '--delete',
        action='store_true',
        help='Delete files from backup that no longer exist in source.'
    )

    args = parser.parse_args()

    sync = VaultSync(
        source_path=args.source,
        backup_path=args.backup,
        dry_run=not args.no_dry_run,
        delete_orphans=args.delete
    )

    return sync.run()


if __name__ == "__main__":
    exit(main())
