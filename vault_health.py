#!/usr/bin/env python3
"""
Obsidian Vault Health Scanner

Performs diagnostic checks on an Obsidian vault:
- Tag coverage gaps (missing type/, lang/, topic/)
- Orphan notes (no outgoing or incoming wikilinks)
- Status/location mismatches
- Stub notes (< 50 words of body content)

Outputs a comprehensive health report with metrics and actionable insights.
"""

import argparse
import json
import re
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple
from collections import defaultdict
from datetime import datetime

from obsidian_utils import get_all_notes, extract_wiki_links


class VaultHealthScanner:
    """Scanner for detecting vault health issues."""

    SKIP_FOLDERS = {'.obsidian', '.git', '.trash', '.claude', 'Templates'}
    REQUIRED_TAGS = {'type', 'lang', 'topic'}

    def __init__(self, vault_path: str):
        self.vault_path = Path(vault_path)
        self.notes = self._get_notes()
        self.results = {
            'scan_date': datetime.now().isoformat(),
            'vault_path': str(self.vault_path),
            'total_notes': len(self.notes),
            'checks': {}
        }

    def _get_notes(self) -> List[Path]:
        """Get all notes, excluding skip folders."""
        notes = []
        for md_file in self.vault_path.rglob("*.md"):
            # Check if any part of path is in skip list
            if any(part in self.SKIP_FOLDERS for part in md_file.parts):
                continue
            notes.append(md_file)
        return notes

    def _read_note(self, note_path: Path) -> str:
        """Safely read note content."""
        try:
            return note_path.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            return ""

    def _parse_frontmatter(self, content: str) -> Tuple[Dict, str]:
        """
        Parse YAML frontmatter and return (frontmatter_dict, body_content).

        Handles both:
        ---
        key: value
        tags:
          - tag1
          - tag2
        ---

        And:
        ---
        key: value
        tags: tag1, tag2
        ---
        """
        lines = content.split('\n')

        if not lines or lines[0].strip() != '---':
            return {}, content

        # Find closing ---
        end_idx = -1
        for i in range(1, len(lines)):
            if lines[i].strip() == '---':
                end_idx = i
                break

        if end_idx == -1:
            return {}, content

        fm_lines = lines[1:end_idx]
        body_lines = lines[end_idx + 1:]

        # Parse YAML-like frontmatter (handle nested lists)
        fm = {}
        current_key = None
        current_list = []

        for line in fm_lines:
            stripped = line.lstrip()
            indent = len(line) - len(stripped)

            if stripped.startswith('- '):
                # List item
                if current_key is not None:
                    item = stripped[2:].strip()
                    current_list.append(item)
            elif ':' in stripped:
                # Key-value pair
                if current_key is not None and current_list:
                    fm[current_key] = current_list
                    current_list = []

                key, val = stripped.split(':', 1)
                key = key.strip()
                val = val.strip()
                current_key = key

                if val:  # Value on same line
                    fm[key] = val
                    current_key = None

        # Flush any remaining list
        if current_key is not None and current_list:
            fm[current_key] = current_list

        body = '\n'.join(body_lines)
        return fm, body

    def _extract_tags(self, frontmatter: Dict) -> Set[str]:
        """Extract tags from frontmatter, handling both string and list formats."""
        tags = set()

        if 'tags' not in frontmatter:
            return tags

        tags_value = frontmatter['tags']

        # Handle list format (YAML array)
        if isinstance(tags_value, list):
            for tag in tags_value:
                tags.add(str(tag).strip())
        else:
            # Handle string format (comma-separated or space-separated)
            tags_str = str(tags_value)
            # Try comma-separated first
            if ',' in tags_str:
                for tag in tags_str.split(','):
                    tag = tag.strip()
                    if tag:
                        tags.add(tag)
            else:
                # Try space-separated
                for tag in tags_str.split():
                    tag = tag.strip()
                    if tag:
                        tags.add(tag)

        return tags

    def _count_words(self, text: str) -> int:
        """Count words in text."""
        return len(text.split())

    def _get_para_category(self, note_path: Path) -> Optional[str]:
        """Extract top-level PARA category from note path."""
        try:
            relative = note_path.relative_to(self.vault_path)
            parts = relative.parts
            if parts:
                first = parts[0]
                if first in {'0.INBOX', '1.PROYECTOS', '2.AREAS', '3.RECURSOS', '4.ARCHIVO'}:
                    return first
        except ValueError:
            pass
        return None

    def check_tag_coverage(self) -> Dict:
        """Find notes missing required tag categories."""
        results = {
            'total_checked': len(self.notes),
            'by_missing_tag': defaultdict(list),
            'by_note': defaultdict(set),
            'summary': {}
        }

        for note in self.notes:
            content = self._read_note(note)
            fm, _ = self._parse_frontmatter(content)
            tags = self._extract_tags(fm)

            # Extract tag categories
            tag_categories = set()
            for tag in tags:
                if '/' in tag:
                    category = tag.split('/')[0]
                    tag_categories.add(category)

            # Check for missing required categories
            missing = self.REQUIRED_TAGS - tag_categories

            if missing:
                rel_path = note.relative_to(self.vault_path)
                results['by_note'][str(rel_path)] = missing
                for category in missing:
                    results['by_missing_tag'][category].append(str(rel_path))

        # Summary
        for category in self.REQUIRED_TAGS:
            count = len(results['by_missing_tag'][category])
            results['summary'][category] = {
                'missing_count': count,
                'coverage_pct': 100.0 * (len(self.notes) - count) / len(self.notes) if self.notes else 0
            }

        results['by_missing_tag'] = dict(results['by_missing_tag'])
        results['by_note'] = dict(results['by_note'])

        return results

    def check_orphan_notes_outgoing(self) -> Dict:
        """Find notes with zero outgoing wikilinks."""
        results = {
            'total_orphans': 0,
            'by_folder': defaultdict(list),
            'orphan_percentage': 0.0
        }

        for note in self.notes:
            content = self._read_note(note)
            links = extract_wiki_links(content)

            if not links:
                rel_path = note.relative_to(self.vault_path)
                category = self._get_para_category(note)
                if category:
                    results['by_folder'][category].append(str(rel_path))
                else:
                    results['by_folder']['Other'].append(str(rel_path))
                results['total_orphans'] += 1

        results['orphan_percentage'] = 100.0 * results['total_orphans'] / len(self.notes) if self.notes else 0
        results['by_folder'] = dict(results['by_folder'])

        return results

    def check_orphan_notes_incoming(self) -> Dict:
        """Find notes that are never linked to from other notes."""
        results = {
            'total_orphans': 0,
            'by_folder': defaultdict(list),
            'orphan_percentage': 0.0
        }

        # Build set of all note basenames (without .md)
        note_basenames = {note.stem: note for note in self.notes}

        # Track which notes are referenced
        referenced = set()

        for note in self.notes:
            content = self._read_note(note)
            links = extract_wiki_links(content)

            for link in links:
                # Link might be "Note Name" or "folder/Note Name"
                # We check both exact match and basename match
                target_basename = Path(link).stem

                # Direct basename match
                if target_basename in note_basenames:
                    referenced.add(target_basename)

                # Also handle "path/to/Note Name" format
                for basename, note_path in note_basenames.items():
                    if link.endswith(basename) or link.endswith(basename + '.md'):
                        referenced.add(basename)

        # Find unreferenced notes
        for basename, note in note_basenames.items():
            if basename not in referenced:
                rel_path = note.relative_to(self.vault_path)
                category = self._get_para_category(note)
                if category:
                    results['by_folder'][category].append(str(rel_path))
                else:
                    results['by_folder']['Other'].append(str(rel_path))
                results['total_orphans'] += 1

        results['orphan_percentage'] = 100.0 * results['total_orphans'] / len(self.notes) if self.notes else 0
        results['by_folder'] = dict(results['by_folder'])

        return results

    def check_status_location_mismatches(self) -> Dict:
        """Find status/location mismatches."""
        results = {
            'active_in_archivo': [],
            'archived_in_active': [],
            'total_issues': 0
        }

        for note in self.notes:
            content = self._read_note(note)
            fm, _ = self._parse_frontmatter(content)
            tags = self._extract_tags(fm)

            # Extract status tag
            status = None
            for tag in tags:
                if tag.startswith('status/'):
                    status = tag.split('/')[1]
                    break

            rel_path = note.relative_to(self.vault_path)
            rel_str = str(rel_path)

            # Check location
            in_archivo = rel_str.startswith('4.ARCHIVO')
            in_active = rel_str.startswith(('0.INBOX', '1.PROYECTOS', '2.AREAS', '3.RECURSOS'))

            if status == 'active' and in_archivo:
                results['active_in_archivo'].append(rel_str)
                results['total_issues'] += 1
            elif status == 'archived' and in_active:
                results['archived_in_active'].append(rel_str)
                results['total_issues'] += 1

        return results

    def check_stub_notes(self, min_words: int = 50) -> Dict:
        """Find notes with very little body content."""
        results = {
            'stub_threshold_words': min_words,
            'stubs': [],
            'total_stubs': 0,
            'stub_percentage': 0.0
        }

        for note in self.notes:
            content = self._read_note(note)
            fm, body = self._parse_frontmatter(content)

            word_count = self._count_words(body.strip())

            if word_count < min_words:
                rel_path = note.relative_to(self.vault_path)
                results['stubs'].append({
                    'path': str(rel_path),
                    'words': word_count
                })
                results['total_stubs'] += 1

        results['stub_percentage'] = 100.0 * results['total_stubs'] / len(self.notes) if self.notes else 0

        return results

    def scan(self, checks: Optional[List[str]] = None) -> Dict:
        """Run all or specified health checks."""
        if checks is None:
            checks = ['tags', 'orphans', 'status', 'stubs']

        if 'tags' in checks:
            self.results['checks']['tag_coverage'] = self.check_tag_coverage()

        if 'orphans' in checks:
            self.results['checks']['orphan_outgoing'] = self.check_orphan_notes_outgoing()
            self.results['checks']['orphan_incoming'] = self.check_orphan_notes_incoming()

        if 'status' in checks:
            self.results['checks']['status_location'] = self.check_status_location_mismatches()

        if 'stubs' in checks:
            self.results['checks']['stubs'] = self.check_stub_notes()

        return self.results

    def get_summary(self) -> Dict:
        """Generate a summary dashboard."""
        summary = {
            'vault': {
                'path': str(self.vault_path),
                'total_notes': len(self.notes),
                'scan_date': self.results['scan_date']
            },
            'health_metrics': {}
        }

        checks = self.results.get('checks', {})

        # Tag coverage
        if 'tag_coverage' in checks:
            tc = checks['tag_coverage']['summary']
            coverage = sum(v['coverage_pct'] for v in tc.values()) / len(tc) if tc else 0
            summary['health_metrics']['tag_coverage_pct'] = round(coverage, 1)
            summary['health_metrics']['notes_with_all_tags'] = len(self.notes) - len(checks['tag_coverage']['by_note'])

        # Orphans
        if 'orphan_outgoing' in checks:
            summary['health_metrics']['orphan_outgoing_pct'] = round(checks['orphan_outgoing']['orphan_percentage'], 1)
            summary['health_metrics']['notes_with_outgoing_links'] = len(self.notes) - checks['orphan_outgoing']['total_orphans']

        if 'orphan_incoming' in checks:
            summary['health_metrics']['orphan_incoming_pct'] = round(checks['orphan_incoming']['orphan_percentage'], 1)
            summary['health_metrics']['notes_with_incoming_links'] = len(self.notes) - checks['orphan_incoming']['total_orphans']

        # Status mismatches
        if 'status_location' in checks:
            summary['health_metrics']['status_location_issues'] = checks['status_location']['total_issues']

        # Stubs
        if 'stubs' in checks:
            summary['health_metrics']['stub_pct'] = round(checks['stubs']['stub_percentage'], 1)
            summary['health_metrics']['substantial_notes'] = len(self.notes) - checks['stubs']['total_stubs']

        return summary


def format_section(title: str, width: int = 80) -> str:
    """Format a section header."""
    return f"\n{'=' * width}\n{title.center(width)}\n{'=' * width}\n"


def print_results(scanner: VaultHealthScanner, summary: Dict, verbose: bool = False):
    """Pretty-print results to console."""
    print(format_section("VAULT HEALTH SCAN"))

    print(f"Vault:       {summary['vault']['path']}")
    print(f"Date:        {summary['vault']['scan_date']}")
    print(f"Total Notes: {summary['vault']['total_notes']}")

    print(format_section("HEALTH METRICS"))

    for metric, value in summary['health_metrics'].items():
        if isinstance(value, float):
            print(f"  {metric:<35} {value:>6.1f}%")
        else:
            print(f"  {metric:<35} {value:>6}")

    checks = scanner.results.get('checks', {})

    # Tag Coverage
    if 'tag_coverage' in checks:
        tc = checks['tag_coverage']
        print(format_section("TAG COVERAGE"))

        for category in ['type', 'lang', 'topic']:
            if category in tc['summary']:
                missing = tc['summary'][category]['missing_count']
                coverage = tc['summary'][category]['coverage_pct']
                print(f"  {category:<20} Missing: {missing:>4}  Coverage: {coverage:>6.1f}%")

                if verbose and tc['by_missing_tag'].get(category):
                    for path in sorted(tc['by_missing_tag'][category])[:10]:
                        print(f"      - {path}")
                    if len(tc['by_missing_tag'][category]) > 10:
                        print(f"      ... and {len(tc['by_missing_tag'][category]) - 10} more")

    # Orphans - Outgoing
    if 'orphan_outgoing' in checks:
        oo = checks['orphan_outgoing']
        print(format_section("ORPHAN NOTES (No Outgoing Links)"))
        print(f"  Total: {oo['total_orphans']} notes ({oo['orphan_percentage']:.1f}%)\n")

        if verbose:
            for folder in sorted(oo['by_folder'].keys()):
                paths = oo['by_folder'][folder]
                print(f"  {folder}: {len(paths)}")
                for path in sorted(paths)[:5]:
                    print(f"      - {path}")
                if len(paths) > 5:
                    print(f"      ... and {len(paths) - 5} more")

    # Orphans - Incoming
    if 'orphan_incoming' in checks:
        oi = checks['orphan_incoming']
        print(format_section("ORPHAN NOTES (No Incoming Links)"))
        print(f"  Total: {oi['total_orphans']} notes ({oi['orphan_percentage']:.1f}%)\n")

        if verbose:
            for folder in sorted(oi['by_folder'].keys()):
                paths = oi['by_folder'][folder]
                print(f"  {folder}: {len(paths)}")
                for path in sorted(paths)[:5]:
                    print(f"      - {path}")
                if len(paths) > 5:
                    print(f"      ... and {len(paths) - 5} more")

    # Status/Location Mismatches
    if 'status_location' in checks:
        sl = checks['status_location']
        print(format_section("STATUS/LOCATION MISMATCHES"))

        if sl['active_in_archivo']:
            print(f"  Active status in ARCHIVO ({len(sl['active_in_archivo'])}):")
            for path in sorted(sl['active_in_archivo'])[:10]:
                print(f"      - {path}")
            if len(sl['active_in_archivo']) > 10:
                print(f"      ... and {len(sl['active_in_archivo']) - 10} more")

        if sl['archived_in_active']:
            print(f"\n  Archived status in active folders ({len(sl['archived_in_active'])}):")
            for path in sorted(sl['archived_in_active'])[:10]:
                print(f"      - {path}")
            if len(sl['archived_in_active']) > 10:
                print(f"      ... and {len(sl['archived_in_active']) - 10} more")

        if not sl['active_in_archivo'] and not sl['archived_in_active']:
            print("  No issues found!")

    # Stubs
    if 'stubs' in checks:
        stubs = checks['stubs']
        print(format_section("STUB NOTES (< 50 words)"))
        print(f"  Total: {stubs['total_stubs']} notes ({stubs['stub_percentage']:.1f}%)\n")

        if verbose and stubs['stubs']:
            for stub in sorted(stubs['stubs'], key=lambda x: x['words'])[:10]:
                print(f"      {stub['path']:<50} ({stub['words']:>3} words)")
            if len(stubs['stubs']) > 10:
                print(f"      ... and {len(stubs['stubs']) - 10} more")

    print(format_section("END OF SCAN"))


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Scan Obsidian vault for health issues and report on tag coverage, orphan notes, and more.'
    )
    parser.add_argument(
        '--vault',
        type=str,
        default=str(Path.home() / 'obsidian' / 'JC'),
        help='Path to Obsidian vault (default: ~/obsidian/JC)'
    )
    parser.add_argument(
        '--check',
        type=str,
        help='Run only specific check(s). Options: tags, orphans, status, stubs, all. Use comma-separated list for multiple (e.g. "tags,orphans")'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='List individual file paths in results'
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='Output results as JSON'
    )

    args = parser.parse_args()

    # Validate vault path
    vault_path = Path(args.vault)
    if not vault_path.exists():
        print(f"Error: Vault path does not exist: {args.vault}")
        return 1
    if not vault_path.is_dir():
        print(f"Error: Vault path is not a directory: {args.vault}")
        return 1

    # Determine which checks to run
    checks = None
    if args.check:
        if args.check == 'all':
            checks = ['tags', 'orphans', 'status', 'stubs']
        else:
            checks = [c.strip() for c in args.check.split(',')]
            # Validate check types
            valid_checks = {'tags', 'orphans', 'status', 'stubs'}
            for check in checks:
                if check not in valid_checks:
                    print(f"Error: Invalid check type '{check}'. Valid options: {', '.join(sorted(valid_checks))}")
                    return 1

    # Run scanner
    scanner = VaultHealthScanner(str(vault_path))
    results = scanner.scan(checks)
    summary = scanner.get_summary()

    if args.json:
        print(json.dumps(results, indent=2, default=str))
    else:
        print_results(scanner, summary, verbose=args.verbose)

    return 0


if __name__ == '__main__':
    exit(main())
