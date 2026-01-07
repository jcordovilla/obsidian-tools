#!/usr/bin/env python3
"""
Shared utilities for Obsidian vault management tools.

This module provides common functionality used across multiple scripts:
- File discovery (notes, attachments)
- File size formatting
- Trash management with dry-run support
- Vault path validation
- Obsidian link parsing
"""

import hashlib
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Set, Optional, Tuple
from collections import defaultdict


def format_size(bytes_size: float) -> str:
    """Format file size in human-readable format (B, KB, MB, GB, TB)."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.2f} TB"


def validate_vault_path(vault_path: str) -> Tuple[bool, str]:
    """
    Validate that a vault path exists and is a directory.

    Returns:
        Tuple of (is_valid, error_message)
    """
    path = Path(vault_path)
    if not path.exists():
        return False, f"Vault path does not exist: {vault_path}"
    if not path.is_dir():
        return False, f"Vault path is not a directory: {vault_path}"
    return True, ""


def is_hidden_path(file_path: Path) -> bool:
    """Check if any part of the path starts with a dot (hidden)."""
    return any(part.startswith('.') for part in file_path.parts)


def should_skip_path(file_path: Path, skip_trash: bool = True, skip_obsidian: bool = True) -> bool:
    """
    Determine if a path should be skipped during scanning.

    Skips hidden directories by default, but allows .trash and .obsidian
    to be optionally included.
    """
    if not is_hidden_path(file_path):
        return False

    path_str = str(file_path)

    # Check for .trash
    if '.trash' in path_str:
        return skip_trash

    # Check for .obsidian
    if '.obsidian' in path_str:
        return skip_obsidian

    # Skip other hidden paths
    return True


def get_all_notes(vault_path: Path, skip_trash: bool = True, skip_obsidian: bool = True) -> List[Path]:
    """
    Get all markdown files in the vault.

    Args:
        vault_path: Path to the Obsidian vault
        skip_trash: Whether to skip .trash directory (default: True)
        skip_obsidian: Whether to skip .obsidian directory (default: True)

    Returns:
        List of Path objects for all markdown files
    """
    notes = []
    for md_file in vault_path.rglob("*.md"):
        if should_skip_path(md_file, skip_trash, skip_obsidian):
            continue
        notes.append(md_file)
    return notes


def get_all_attachments(vault_path: Path, skip_backup: bool = True) -> List[Path]:
    """
    Get all files from the Attachments folder.

    Args:
        vault_path: Path to the Obsidian vault
        skip_backup: Whether to skip backup folders (default: True)

    Returns:
        List of Path objects for all attachment files
    """
    attachments_path = vault_path / "Attachments"
    if not attachments_path.exists():
        return []

    attachments = []
    for file in attachments_path.rglob("*"):
        if skip_backup and 'backup' in file.parts:
            continue
        if file.is_file():
            attachments.append(file)

    return attachments


def get_attachments_by_extension(vault_path: Path, extensions: Set[str], skip_backup: bool = True) -> List[Path]:
    """
    Get attachments filtered by file extension.

    Args:
        vault_path: Path to the Obsidian vault
        extensions: Set of extensions to match (e.g., {'.jpg', '.png'})
        skip_backup: Whether to skip backup folders

    Returns:
        List of matching attachment paths
    """
    all_attachments = get_all_attachments(vault_path, skip_backup)
    return [f for f in all_attachments if f.suffix.lower() in extensions]


def move_to_trash(
    file_path: Path,
    vault_path: Path,
    dry_run: bool = True,
    prefix: str = "cleanup",
    verbose: bool = True
) -> bool:
    """
    Move a file to the vault's .trash directory.

    Args:
        file_path: Path to the file to move
        vault_path: Path to the Obsidian vault
        dry_run: If True, only print what would happen
        prefix: Prefix for the timestamped trash subfolder
        verbose: Whether to print status messages

    Returns:
        True if successful (or would be successful in dry-run)
    """
    trash_path = vault_path / ".trash"

    if dry_run:
        if verbose:
            print(f"  [DRY RUN] Would move to trash: {file_path.name}")
        return True

    try:
        # Create timestamped subdirectory
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_trash = trash_path / f"{prefix}_{timestamp}"
        run_trash.mkdir(parents=True, exist_ok=True)

        dest = run_trash / file_path.name

        # Handle name collisions
        counter = 1
        while dest.exists():
            stem = file_path.stem
            ext = file_path.suffix
            dest = run_trash / f"{stem}_{counter}{ext}"
            counter += 1

        shutil.move(str(file_path), str(dest))
        if verbose:
            print(f"  Moved to trash: {dest}")
        return True
    except Exception as e:
        if verbose:
            print(f"  Error moving {file_path} to trash: {e}")
        return False


def compute_file_hash(file_path: Path, algorithm: str = 'md5') -> str:
    """
    Compute hash of file content.

    Args:
        file_path: Path to the file
        algorithm: Hash algorithm ('md5', 'sha1', 'sha256')

    Returns:
        Hex digest string, or empty string on error
    """
    try:
        if algorithm == 'md5':
            hasher = hashlib.md5()
        elif algorithm == 'sha1':
            hasher = hashlib.sha1()
        elif algorithm == 'sha256':
            hasher = hashlib.sha256()
        else:
            hasher = hashlib.md5()

        with open(file_path, 'rb') as f:
            # Read in chunks for large files
            for chunk in iter(lambda: f.read(4096), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception as e:
        print(f"Error computing hash for {file_path}: {e}")
        return ""


# =============================================================================
# Obsidian Link Parsing
# =============================================================================

def extract_wiki_links(text: str) -> List[str]:
    """
    Extract Obsidian wiki-style links from text.

    Matches: [[target]] or [[target|alias]]
    Returns the target part (before the pipe if present).
    """
    links = []
    pattern = r'\[\[([^\]]+)\]\]'
    for match in re.findall(pattern, text):
        # Remove alias if present
        target = match.split('|')[0].strip()
        if target:
            links.append(target)
    return links


def extract_markdown_links(text: str) -> List[Tuple[str, str]]:
    """
    Extract markdown-style links and images from text.

    Matches: [alt](url) and ![alt](url)
    Returns list of (alt_text, url) tuples.
    """
    pattern = r'!?\[([^\]]*)\]\(([^)]+)\)'
    return re.findall(pattern, text)


def find_attachment_references(vault_path: Path) -> Set[str]:
    """
    Find all attachments referenced in notes.

    Returns set of attachment relative paths (from Attachments/ root).
    """
    attachments_path = vault_path / "Attachments"
    if not attachments_path.exists():
        return set()

    notes = get_all_notes(vault_path)
    referenced = set()

    # Build lookup map for fast filename searches
    filename_to_paths = defaultdict(list)
    for attachment_file in attachments_path.rglob("*"):
        if attachment_file.is_file():
            filename_to_paths[attachment_file.name].append(attachment_file)

    for note in notes:
        try:
            content = note.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            continue

        # Extract wiki links
        wiki_links = extract_wiki_links(content)
        for link in wiki_links:
            # Check if path contains attachments/ (case insensitive)
            parts = re.split(r'(?i)attachments/', link)
            if len(parts) > 1:
                file_part = parts[-1]
                file_part = re.sub(r'\.\./', '', file_part)  # Normalize
                attachment = attachments_path / file_part
                if attachment.exists() and attachment.is_file():
                    rel_path = attachment.relative_to(attachments_path)
                    referenced.add(str(rel_path).replace('\\', '/'))
            else:
                # Direct filename reference
                if link in filename_to_paths:
                    for attachment_file in filename_to_paths[link]:
                        rel_path = attachment_file.relative_to(attachments_path)
                        referenced.add(str(rel_path).replace('\\', '/'))

        # Extract markdown links
        md_links = extract_markdown_links(content)
        for alt, link in md_links:
            parts = re.split(r'(?i)attachments/', link)
            if len(parts) > 1:
                rel_path_str = parts[-1].split('?')[0]  # Remove query params
                rel_path_str = re.sub(r'\.\./', '', rel_path_str)
                attachment = attachments_path / rel_path_str
                if attachment.exists() and attachment.is_file():
                    rel_path = attachment.relative_to(attachments_path)
                    referenced.add(str(rel_path).replace('\\', '/'))

    return referenced


# =============================================================================
# Base class for CLI tools (optional use)
# =============================================================================

class ObsidianToolBase:
    """
    Base class for Obsidian vault management tools.

    Provides common initialization and utility methods.
    """

    def __init__(self, vault_path: str, dry_run: bool = True):
        self.vault_path = Path(vault_path)
        self.attachments_path = self.vault_path / "Attachments"
        self.trash_path = self.vault_path / ".trash"
        self.dry_run = dry_run
        self.stats = {}

    def setup_trash(self):
        """Create trash directory if it doesn't exist."""
        if not self.dry_run:
            self.trash_path.mkdir(exist_ok=True)

    def get_all_notes(self) -> List[Path]:
        """Get all markdown files in the vault."""
        return get_all_notes(self.vault_path)

    def get_all_attachments(self) -> List[Path]:
        """Get all files from the Attachments folder."""
        return get_all_attachments(self.vault_path)

    def format_size(self, bytes_size: float) -> str:
        """Format file size in human-readable format."""
        return format_size(bytes_size)

    def move_to_trash(self, file_path: Path, prefix: str = "cleanup") -> bool:
        """Move a file to trash."""
        return move_to_trash(file_path, self.vault_path, self.dry_run, prefix)
