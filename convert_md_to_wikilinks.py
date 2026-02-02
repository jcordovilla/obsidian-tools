#!/usr/bin/env python3
"""
Convert markdown relative path links to Obsidian wikilinks.

Transforms: [text](../path/to/Note Name.md)
        To: [[Note Name|text]] or [[Note Name]] if text matches note name

Handles:
- Relative paths with ../
- URL-encoded spaces (%20)
- Anchor links (#section)
- Preserves display text when different from note name

Usage:
    python convert_md_to_wikilinks.py                    # Dry run
    python convert_md_to_wikilinks.py --no-dry-run      # Apply changes
    python convert_md_to_wikilinks.py --file path.md    # Single file
"""

import re
import os
import argparse
from pathlib import Path
from urllib.parse import unquote
from collections import defaultdict

VAULT_PATH = Path("/Users/jose/obsidian/JC")

# Files/folders to skip
SKIP_PATTERNS = [
    ".obsidian",
    ".git",
    ".trash",
    "node_modules",
    ".copilot-index",
]

# Pattern to match markdown links to .md files
# Matches: [display text](path/to/file.md) or [display text](path/to/file.md#anchor)
MD_LINK_PATTERN = re.compile(
    r'\[([^\]]+)\]\(([^)]+\.md(?:#[^)]*)?)\)',
    re.IGNORECASE
)


def should_skip(path: Path) -> bool:
    """Check if path should be skipped."""
    path_str = str(path)
    return any(pattern in path_str for pattern in SKIP_PATTERNS)


def extract_note_name(link_path: str) -> tuple[str, str | None]:
    """
    Extract note name and optional anchor from a link path.

    Args:
        link_path: Path like '../folder/Note Name.md#section'

    Returns:
        Tuple of (note_name, anchor_or_none)
    """
    # Handle anchor
    anchor = None
    if '#' in link_path:
        link_path, anchor = link_path.rsplit('#', 1)

    # URL decode (handles %20 for spaces)
    link_path = unquote(link_path)

    # Get just the filename without .md
    note_name = Path(link_path).stem

    return note_name, anchor


def convert_to_wikilink(display_text: str, link_path: str) -> str:
    """
    Convert a markdown link to a wikilink.

    Args:
        display_text: The [text] part
        link_path: The (path/to/file.md) part

    Returns:
        Wikilink format string
    """
    note_name, anchor = extract_note_name(link_path)

    # Build the wikilink target
    target = note_name
    if anchor:
        target = f"{note_name}#{anchor}"

    # If display text matches note name (case-insensitive), use simple format
    if display_text.lower().strip() == note_name.lower().strip():
        return f"[[{target}]]"
    else:
        return f"[[{target}|{display_text}]]"


def process_file(file_path: Path, dry_run: bool = True) -> dict:
    """
    Process a single markdown file, converting md links to wikilinks.

    Returns:
        Dict with stats about conversions made
    """
    stats = {
        "file": str(file_path),
        "conversions": [],
        "changed": False,
    }

    try:
        content = file_path.read_text(encoding='utf-8')
    except Exception as e:
        stats["error"] = str(e)
        return stats

    # Find all markdown links
    def replace_link(match):
        display_text = match.group(1)
        link_path = match.group(2)

        # Skip external URLs that happen to end in .md
        if link_path.startswith(('http://', 'https://', 'ftp://')):
            return match.group(0)

        wikilink = convert_to_wikilink(display_text, link_path)
        stats["conversions"].append({
            "from": match.group(0),
            "to": wikilink,
        })
        return wikilink

    new_content = MD_LINK_PATTERN.sub(replace_link, content)

    if new_content != content:
        stats["changed"] = True
        if not dry_run:
            file_path.write_text(new_content, encoding='utf-8')

    return stats


def check_duplicate_note_names(vault_path: Path) -> dict[str, list[Path]]:
    """
    Find notes with duplicate names (could cause ambiguity in wikilinks).

    Returns:
        Dict mapping note names to list of paths where duplicates exist
    """
    note_names = defaultdict(list)

    for md_file in vault_path.rglob("*.md"):
        if should_skip(md_file):
            continue
        note_names[md_file.stem.lower()].append(md_file)

    # Return only duplicates
    return {name: paths for name, paths in note_names.items() if len(paths) > 1}


def main():
    parser = argparse.ArgumentParser(
        description="Convert markdown relative links to Obsidian wikilinks"
    )
    parser.add_argument(
        "--no-dry-run",
        action="store_true",
        help="Actually apply changes (default is dry run)"
    )
    parser.add_argument(
        "--file",
        type=Path,
        help="Process single file instead of whole vault"
    )
    parser.add_argument(
        "--check-duplicates",
        action="store_true",
        help="Only check for duplicate note names (ambiguity risk)"
    )
    args = parser.parse_args()

    dry_run = not args.no_dry_run

    print("=" * 60)
    print("MARKDOWN TO WIKILINK CONVERTER")
    print(f"Mode: {'DRY RUN' if dry_run else 'APPLYING CHANGES'}")
    print("=" * 60)

    # Check for duplicates first
    if args.check_duplicates or dry_run:
        print("\nChecking for duplicate note names...")
        duplicates = check_duplicate_note_names(VAULT_PATH)
        if duplicates:
            print(f"\n⚠️  Found {len(duplicates)} duplicate note names:")
            for name, paths in sorted(duplicates.items())[:10]:
                print(f"  '{name}':")
                for p in paths:
                    print(f"    - {p.relative_to(VAULT_PATH)}")
            if len(duplicates) > 10:
                print(f"  ... and {len(duplicates) - 10} more")
            print("\nThese may cause ambiguous wikilinks.")
        else:
            print("✓ No duplicate note names found")

        if args.check_duplicates:
            return

    # Process files
    if args.file:
        files_to_process = [args.file]
    else:
        files_to_process = [
            f for f in VAULT_PATH.rglob("*.md")
            if not should_skip(f)
        ]

    print(f"\nProcessing {len(files_to_process)} files...")

    total_conversions = 0
    files_changed = 0
    all_conversions = []

    for file_path in files_to_process:
        stats = process_file(file_path, dry_run=dry_run)

        if stats.get("error"):
            print(f"  Error in {file_path}: {stats['error']}")
            continue

        if stats["changed"]:
            files_changed += 1
            total_conversions += len(stats["conversions"])
            all_conversions.extend([
                (file_path, c["from"], c["to"])
                for c in stats["conversions"]
            ])

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Files scanned: {len(files_to_process)}")
    print(f"Files with changes: {files_changed}")
    print(f"Total conversions: {total_conversions}")

    if all_conversions and dry_run:
        print("\nSample conversions (first 20):")
        for file_path, from_link, to_link in all_conversions[:20]:
            rel_path = file_path.relative_to(VAULT_PATH) if file_path.is_relative_to(VAULT_PATH) else file_path
            print(f"\n  {rel_path}:")
            print(f"    FROM: {from_link}")
            print(f"    TO:   {to_link}")

        if len(all_conversions) > 20:
            print(f"\n  ... and {len(all_conversions) - 20} more conversions")

    if dry_run:
        print("\n⚠️  DRY RUN - No changes made")
        print("Run with --no-dry-run to apply changes")
    else:
        print(f"\n✓ Applied {total_conversions} conversions to {files_changed} files")


if __name__ == "__main__":
    main()
