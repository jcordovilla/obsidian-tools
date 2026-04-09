#!/usr/bin/env python3
"""Apply topic tags from a TSV report, inserting them correctly into frontmatter."""

import csv
import re
import sys
from pathlib import Path


VAULT = Path("/Users/jose/obsidian/JC")


def apply_tags(file_path: Path, topics: list[str], dry_run: bool = True) -> bool:
    """Insert topic/ tags into frontmatter, just before the closing ---."""
    try:
        content = file_path.read_text(encoding='utf-8', errors='ignore')
    except Exception as e:
        print(f"  ERROR reading {file_path}: {e}")
        return False

    if not content.startswith('---'):
        print(f"  SKIP (no frontmatter): {file_path.name}")
        return False

    # Find the closing --- of frontmatter
    end_match = re.search(r'\n(---\s*\n)', content[3:])
    if not end_match:
        print(f"  SKIP (no closing ---): {file_path.name}")
        return False

    # Position of the closing --- in the full content
    close_pos = end_match.start(1) + 3  # +3 for the opening ---

    # Check if topics already exist
    frontmatter = content[:close_pos]
    existing_topics = re.findall(r'topic/[\w-]+', frontmatter)
    new_topics = [t for t in topics if t.replace('topic/', '') not in
                  [et.replace('topic/', '') for et in existing_topics]]

    if not new_topics:
        return False

    # Build insertion text
    insertion = ''.join(f'  - {t}\n' for t in new_topics)

    # Insert just before the closing ---
    updated = content[:close_pos] + insertion + content[close_pos:]

    if dry_run:
        print(f"  [DRY] {file_path.relative_to(VAULT)}: +{', '.join(new_topics)}")
    else:
        file_path.write_text(updated, encoding='utf-8')

    return True


def main():
    report_path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/suggest_tags_report.tsv"
    dry_run = "--no-dry-run" not in sys.argv

    print(f"Applying tags from: {report_path}")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print("=" * 60)

    applied = 0
    skipped = 0
    errors = 0

    with open(report_path, 'r') as f:
        reader = csv.DictReader(f, delimiter='\t')
        for row in reader:
            rel_path = row['Path']
            topics_str = row['Suggested Topics']
            topics = [t.strip() for t in topics_str.split(';') if t.strip()]

            file_path = VAULT / rel_path
            if not file_path.exists():
                skipped += 1
                continue

            if apply_tags(file_path, topics, dry_run):
                applied += 1
            else:
                skipped += 1

    print(f"\n{'=' * 60}")
    print(f"Applied: {applied}  Skipped: {skipped}  Errors: {errors}")
    if dry_run:
        print("DRY RUN — use --no-dry-run to apply")


if __name__ == '__main__':
    main()
