#!/usr/bin/env python3
"""
Delete low-value conversations based on analysis results.
"""

import json
import sys
from pathlib import Path


def main():
    report_path = Path("/Users/jose/obsidian/chatgpt_analysis_report.json")

    if not report_path.exists():
        print(f"❌ Report not found: {report_path}")
        sys.exit(1)

    # Load analysis report
    with open(report_path, 'r') as f:
        results = json.load(f)

    # Find conversations to delete
    to_delete = [r for r in results if r['analysis']['suggested_action'] == 'archive']

    print("=" * 80)
    print("DELETE LOW-VALUE CONVERSATIONS")
    print("=" * 80)
    print()
    print(f"Found {len(to_delete)} conversations marked for deletion")
    print()

    confirm = input(f"⚠️  Are you sure you want to DELETE {len(to_delete)} files? Type 'yes' to confirm: ")

    if confirm.lower() != 'yes':
        print("❌ Deletion cancelled")
        return

    print()
    print("Deleting conversations...")
    print()

    deleted = 0
    not_found = 0

    for result in to_delete:
        source_path = Path(result['path'])

        if not source_path.exists():
            not_found += 1
            continue

        try:
            source_path.unlink()
            deleted += 1

            if deleted % 50 == 0:
                print(f"  Deleted {deleted}/{len(to_delete)}...")

        except Exception as e:
            print(f"  ⚠️  Error deleting {source_path.name}: {e}")

    print()
    print("=" * 80)
    print("DELETION COMPLETE")
    print("=" * 80)
    print()
    print(f"Successfully deleted: {deleted}")
    print(f"Not found: {not_found}")
    print(f"Total: {len(to_delete)}")


if __name__ == '__main__':
    main()
