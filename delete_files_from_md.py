#!/usr/bin/env python3
"""
delete_files_from_md.py

Reads a markdown file containing a list of file paths and deletes the files.

Usage examples:
  python delete_files_from_md.py \
    "/Users/jose/obsidian/JC/orphaned files output.md" --dry-run

  python delete_files_from_md.py \
    "/Users/jose/obsidian/JC/orphaned files output.md" --yes

By default the script performs a dry-run and prints what would be deleted.
Pass --yes to actually delete.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Iterable, List


def extract_paths_from_markdown(text: str) -> List[str]:
    """Extract absolute POSIX paths from markdown text.

    Heuristics used (in order):
    - Markdown links like [name](/absolute/path)
    - Backtick-wrapped paths: `/absolute/path`
    - Lines that start with an absolute path (leading spaces allowed)
    - Fallback: any substring that starts with '/' and contains no closing paren or bracket

    Returns a list of unique normalized paths in the order found.
    """
    paths: List[str] = []
    seen = set()

    # Wiki-style links [[...]] (Obsidian style). We capture the target before a pipe if present
    # Example: [[Attachments/image.png]] or [[file name|alias]] -> captures 'Attachments/image.png' and 'file name'
    for m in re.finditer(r"\[\[([^\]]+)\]\]", text):
        content = m.group(1).strip()
        if not content:
            continue
        # split alias syntax [[target|alias]] -> take target
        content = content.split("|", 1)[0].strip()
        if content and content not in seen:
            seen.add(content)
            paths.append(content)

    # 1) markdown link parentheses: ( /path )
    for m in re.finditer(r"\((/[^)]+)\)", text):
        p = m.group(1).strip()
        if p and p not in seen:
            seen.add(p)
            paths.append(p)

    # 2) backtick paths `...`
    for m in re.finditer(r"`(/[^`]+)`", text):
        p = m.group(1).strip()
        if p and p not in seen:
            seen.add(p)
            paths.append(p)

    # 3) lines that start with a slash
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        # skip code fence indicators and headings
        if s.startswith('```') or s.startswith('#'):
            continue
        if s.startswith('/'):
            # trim trailing punctuation commonly found in lists
            p = s.rstrip(',.')
            # remove leading list markers if present
            p = re.sub(r"^[\-*+]\s*", "", p)
            if p and p not in seen:
                seen.add(p)
                paths.append(p)

    # 4) fallback: any substring starting with /Users or /
    # This tries to capture remaining absolute paths (may be conservative)
    for m in re.finditer(r"(/Users[^\s)\]]+|/[^\s)\]]+)", text):
        p = m.group(1).strip()
        # avoid duplicates
        if p and p not in seen:
            seen.add(p)
            paths.append(p)

    # 5) angle-bracket style links: <...>
    for m in re.finditer(r"<([^>]+)>", text):
        candidate = m.group(1).strip()
        # accept if looks like a path (has a slash) or a filename with extension
        if candidate and candidate not in seen:
            if '/' in candidate or re.search(r"\.[A-Za-z0-9]{2,6}$", candidate):
                seen.add(candidate)
                paths.append(candidate)

    # 6) filenames with common extensions (bare filenames). This captures items like
    #    unknown_filename.png or report-2024.pdf appearing anywhere in the text.
    #    Keep the extension list reasonably broad but avoid extremely generic matches.
    ext_pattern = r"(?:png|jpg|jpeg|gif|webp|svg|heic|pdf|bin|txt|md|html|csv|zip|tar|gz|mp4|mov|m4a)"
    for m in re.finditer(rf"\b([^\s\)\]\"']+\.(?:{ext_pattern}))\b", text, flags=re.IGNORECASE):
        p = m.group(1).strip()
        if p and p not in seen:
            seen.add(p)
            paths.append(p)

    return paths


def confirm_and_delete(paths: Iterable[str], do_delete: bool) -> int:
    """Attempt to delete each path. If do_delete is False, only report.

    Returns the number of files successfully deleted (0 in dry-run).
    """
    deleted = 0
    for p in paths:
        try:
            path = Path(p).expanduser()
            if not path.exists():
                print(f"MISSING: {path}")
                continue
            if path.is_dir():
                print(f"SKIP (is directory): {path}")
                continue
            if do_delete:
                path.unlink()
                print(f"DELETED: {path}")
                deleted += 1
            else:
                print(f"WILL DELETE: {path}")
        except PermissionError:
            print(f"PERMISSION ERROR: {p}")
        except OSError as e:
            print(f"ERROR deleting {p}: {e}")
    return deleted


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Delete files listed in a markdown file. Default: dry-run",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("mdfile", help="Path to markdown file that lists files to delete")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Actually delete files. Without this flag the script runs as a dry-run",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional: maximum number of files to delete (0 = no limit)",
    )
    parser.add_argument(
        "--base-dir",
        dest="base_dir",
        help=(
            "Optional base directory to resolve relative paths found in the markdown. "
            "If not provided, relative paths are resolved relative to the markdown file's directory."
        ),
    )
    parser.add_argument(
        "--wiki-only",
        action="store_true",
        help=(
            "Only extract targets inside wiki-style [[...]] links from the markdown and treat each as a filename "
            "to resolve inside --base-dir."
        ),
    )
    parser.add_argument(
        "--prefer-wiki",
        action="store_true",
        help=(
            "If wiki-style [[...]] links are present, prefer them over other extraction heuristics. "
            "If none are found, fall back to normal extraction."
        ),
    )
    parser.add_argument(
        "--match-basenames",
        action="store_true",
        help=(
            "When a resolved path does not exist, search the base directory recursively for files "
            "with the same basename and include any matches. Useful when the markdown lists "
            "filenames or fragments but files live in nested subfolders."
        ),
    )

    args = parser.parse_args(argv)

    md_path = Path(args.mdfile).expanduser()
    if not md_path.exists():
        print(f"Markdown file not found: {md_path}")
        return 2

    text = md_path.read_text(encoding="utf-8")
    # If wiki-only requested, extract only wiki entries. If prefer-wiki, use wiki entries when present.
    wiki_matches = []
    for m in re.finditer(r"\[\[([^\]]+)\]\]", text):
        content = m.group(1).strip()
        if not content:
            continue
        content = content.split("|", 1)[0].strip()
        if content:
            wiki_matches.append(content)

    if args.wiki_only:
        raw_paths = wiki_matches
    elif args.prefer_wiki and wiki_matches:
        raw_paths = wiki_matches
    else:
        raw_paths = extract_paths_from_markdown(text)

    # Resolve relative paths: if a path does not start with '/', treat it as relative
    # and join with the provided base_dir or the markdown file's parent directory.
    paths: List[str] = []
    base_dir = Path(args.base_dir).expanduser() if args.base_dir else md_path.parent
    for p in raw_paths:
        # Heuristic: if path starts with /Users (or /home) assume it's a true absolute path
        # If it starts with '/' but not with '/Users' (or other common roots), it's likely
        # a path fragment (e.g. '/filename.png') coming from the markdown; join with base_dir.
        if p.startswith('/') and (p.startswith('/Users') or p.startswith('/home') or p.startswith('/Volumes')):
            resolved = p
        elif p.startswith('/'):
            # strip leading slash and join with base_dir
            resolved = str((base_dir / p.lstrip('/')).resolve())
        else:
            resolved = str((base_dir / p).resolve())
        paths.append(resolved)

    # remove duplicates while preserving order
    seen = set()
    unique_paths: List[str] = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            unique_paths.append(p)
    paths = unique_paths

    if not paths:
        print("No paths found in the markdown file.")
        return 0

    # Optionally apply limit
    if args.limit > 0:
        paths = paths[: args.limit]

    # If requested, try to find missing files by matching basenames under base_dir.
    if args.match_basenames:
        expanded: List[str] = []
        for p in paths:
            ppath = Path(p)
            if ppath.exists():
                expanded.append(str(ppath))
                continue
            # Search base_dir for files with same name
            basename = ppath.name
            matches = list(base_dir.rglob(basename))
            if matches:
                for m in matches:
                    expanded.append(str(m.resolve()))
            else:
                expanded.append(str(ppath))
        # dedupe while preserving order
        seen2 = set()
        final: List[str] = []
        for p in expanded:
            if p not in seen2:
                seen2.add(p)
                final.append(p)
        paths = final

    print(f"Found {len(paths)} candidate paths (showing first 100):")
    for p in paths[:100]:
        print("  ", p)

    if not args.yes:
        print("\nDRY-RUN: no files will be deleted. Re-run with --yes to delete.")
        confirm_and_delete(paths, do_delete=False)
        return 0

    # final confirmation: require explicit --yes (already present)
    print("\nProceeding to delete the listed files...")
    deleted = confirm_and_delete(paths, do_delete=True)
    print(f"Deleted {deleted} files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
