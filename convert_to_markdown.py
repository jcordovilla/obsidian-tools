#!/usr/bin/env python3
"""
Convert files to Markdown using Microsoft's markitdown library.

Supports: PDF, DOCX, PPTX, XLSX, XLS, HTML, CSV, JSON, XML,
          JPG, PNG, WAV, MP3, EPUB, ZIP

Output is saved in the same folder as the source file.

Usage:
    python convert_to_markdown.py --file report.pdf                  # Dry run
    python convert_to_markdown.py --file report.pdf --no-dry-run     # Convert
    python convert_to_markdown.py --dir /path/to/folder              # Batch dry run
    python convert_to_markdown.py --dir /path/to/folder --no-dry-run # Batch convert
    python convert_to_markdown.py --dir . --ext pdf,docx             # Filter by extension
    python convert_to_markdown.py --dir . --recursive --no-dry-run   # Include subdirs
"""

import argparse
import sys
from pathlib import Path

try:
    from markitdown import MarkItDown
except ImportError:
    print("Error: markitdown is required. Install with: pip install 'markitdown[all]'")
    sys.exit(1)

from obsidian_utils import format_size

SUPPORTED_EXTENSIONS = {
    '.pdf', '.docx', '.pptx', '.xlsx', '.xls',
    '.html', '.htm', '.csv', '.json', '.xml',
    '.jpg', '.jpeg', '.png',
    '.wav', '.mp3',
    '.epub', '.zip',
}


def convert_file(file_path: Path, converter: MarkItDown,
                 dry_run: bool = True, overwrite: bool = False) -> dict:
    """Convert a single file to markdown.

    Returns a stats dict with keys: file, output, converted, skipped, error.
    """
    stats = {
        'file': file_path,
        'output': None,
        'converted': False,
        'skipped': False,
        'error': None,
    }

    output_path = file_path.with_suffix('.md')
    stats['output'] = output_path
    size = file_path.stat().st_size

    if output_path.exists() and not overwrite:
        print(f"  {file_path.name} ({format_size(size)}) -> {output_path.name} "
              f"[SKIP: already exists]")
        stats['skipped'] = True
        return stats

    if dry_run:
        print(f"  {file_path.name} ({format_size(size)}) -> {output_path.name}")
        stats['converted'] = True
        return stats

    try:
        result = converter.convert(str(file_path))
        output_path.write_text(result.text_content, encoding='utf-8')
        print(f"  {file_path.name} ({format_size(size)}) -> {output_path.name} [OK]")
        stats['converted'] = True
    except Exception as e:
        print(f"  {file_path.name} ({format_size(size)}) -> ERROR: {e}")
        stats['error'] = str(e)

    return stats


def collect_files(dir_path: Path, extensions: set | None = None,
                  recursive: bool = False) -> list[Path]:
    """Collect supported files from a directory."""
    exts = extensions or SUPPORTED_EXTENSIONS
    files = []

    if recursive:
        items = dir_path.rglob('*')
    else:
        items = dir_path.iterdir()

    for item in sorted(items):
        if item.is_file() and item.suffix.lower() in exts:
            # Skip hidden files/directories
            if any(part.startswith('.') for part in item.relative_to(dir_path).parts):
                continue
            files.append(item)

    return files


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Convert files to Markdown using markitdown',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python convert_to_markdown.py --file report.pdf                  # Dry run
  python convert_to_markdown.py --file report.pdf --no-dry-run     # Convert
  python convert_to_markdown.py --dir /path/to/folder              # Batch dry run
  python convert_to_markdown.py --dir . --ext pdf,docx --no-dry-run
  python convert_to_markdown.py --dir . --recursive --no-dry-run

Supported formats:
  PDF, DOCX, PPTX, XLSX, XLS, HTML, CSV, JSON, XML,
  JPG, PNG, WAV, MP3, EPUB, ZIP
        """,
    )
    parser.add_argument('--file', type=str, help='Path to a single file to convert')
    parser.add_argument('--dir', type=str, help='Path to directory for batch conversion')
    parser.add_argument('--ext', type=str,
                        help='Comma-separated extensions to filter (e.g. pdf,docx,pptx)')
    parser.add_argument('--recursive', action='store_true',
                        help='Include subdirectories in batch mode')
    parser.add_argument('--overwrite', action='store_true',
                        help='Overwrite existing .md files (default: skip)')
    parser.add_argument('--no-dry-run', action='store_true',
                        help='Actually write .md files (default is dry-run)')

    args = parser.parse_args()
    dry_run = not args.no_dry_run

    if not args.file and not args.dir:
        parser.error('Either --file or --dir is required')

    # Parse extension filter
    extensions = None
    if args.ext:
        extensions = {f'.{e.strip().lower().lstrip(".")}' for e in args.ext.split(',')}
        unsupported = extensions - SUPPORTED_EXTENSIONS
        if unsupported:
            print(f"Warning: unsupported extensions ignored: "
                  f"{', '.join(sorted(unsupported))}")
            extensions = extensions & SUPPORTED_EXTENSIONS
            if not extensions:
                print("Error: no valid extensions remain after filtering")
                return 1

    # Collect files
    files = []
    if args.file:
        fp = Path(args.file)
        if not fp.exists():
            print(f"Error: file not found: {fp}")
            return 1
        if fp.suffix.lower() not in SUPPORTED_EXTENSIONS:
            print(f"Error: unsupported format: {fp.suffix}")
            print(f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}")
            return 1
        files = [fp]
    else:
        dp = Path(args.dir)
        if not dp.is_dir():
            print(f"Error: directory not found: {dp}")
            return 1
        files = collect_files(dp, extensions, args.recursive)
        if not files:
            print("No supported files found.")
            return 0

    # Header
    mode = "DRY RUN" if dry_run else "CONVERTING"
    print(f"\n{mode} — {'no files will be written' if dry_run else 'writing .md files'}\n")
    print(f"Found {len(files)} file(s) to convert:")

    # Convert
    converter = MarkItDown()
    results = []
    for f in files:
        stats = convert_file(f, converter, dry_run, args.overwrite)
        results.append(stats)

    # Summary
    converted = sum(1 for r in results if r['converted'])
    skipped = sum(1 for r in results if r['skipped'])
    failed = sum(1 for r in results if r['error'])

    print(f"\nSummary: {converted} {'would be ' if dry_run else ''}converted"
          f"{f', {skipped} skipped' if skipped else ''}"
          f"{f', {failed} failed' if failed else ''}")

    if failed:
        print("\nFailed files:")
        for r in results:
            if r['error']:
                print(f"  {r['file'].name}: {r['error']}")

    return 1 if failed and not dry_run else 0


if __name__ == '__main__':
    sys.exit(main())
