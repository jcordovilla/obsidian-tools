#!/usr/bin/env python3
"""
Obsidian Vault Health Scanner

Performs diagnostic checks on an Obsidian vault, calibrated to the JC vault's
actual structure (PARA + a large derived knowledge layer):

- Tag coverage gaps (missing type/, lang/, topic/) on taggable notes
- Orphan notes (no outgoing / incoming wikilinks) within the linkable working set
- Status/location mismatches (genuine misplacements only)
- Stub notes (< 50 words) among substantive prose, with the short-by-design
  layers (glossary, indexes, drawings) reported separately

Every check is driven by a single note classifier so the derived/structural
layers do not masquerade as health problems. See `_note_class`.
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

    # Folders that are not vault prose content at all.
    SKIP_FOLDERS = {'.obsidian', '.git', '.trash', '.claude', 'Templates',
                    'copilot-custom-prompts'}
    REQUIRED_TAGS = {'type', 'lang', 'topic'}

    # Numbered structural files: 00-Index, 01-To-Do, 02-Log, 03-Issues, etc.
    INDEX_RE = re.compile(r'^\d{2}-')

    # Note classes excluded from the prose-oriented checks.
    NONPROSE_CLASSES = {'hidden', 'excalidraw', 'template'}
    # Classes whose short length is by design (reported separately, not as stubs).
    BY_DESIGN_SHORT = {'hidden', 'excalidraw', 'template', 'derived', 'index'}
    # Classes that participate in the link graph as a "working set".
    LINKABLE_CLASSES = {'core', 'reference', 'index'}

    def __init__(self, vault_path: str):
        self.vault_path = Path(vault_path)
        self.notes = self._get_notes()
        # Cache parsed data per note: (frontmatter, body, tags, class)
        self._cache: Dict[Path, Tuple[Dict, str, Set[str], str]] = {}
        for note in self.notes:
            self._cache[note] = self._analyse(note)
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
            if any(part in self.SKIP_FOLDERS for part in md_file.parts):
                continue
            notes.append(md_file)
        return notes

    def _read_note(self, note_path: Path) -> str:
        try:
            return note_path.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            return ""

    def _parse_frontmatter(self, content: str) -> Tuple[Dict, str]:
        """Parse YAML frontmatter and return (frontmatter_dict, body_content)."""
        lines = content.split('\n')

        if not lines or lines[0].strip() != '---':
            return {}, content

        end_idx = -1
        for i in range(1, len(lines)):
            if lines[i].strip() == '---':
                end_idx = i
                break

        if end_idx == -1:
            return {}, content

        fm_lines = lines[1:end_idx]
        body_lines = lines[end_idx + 1:]

        fm = {}
        current_key = None
        current_list = []

        for line in fm_lines:
            stripped = line.lstrip()

            if stripped.startswith('- '):
                if current_key is not None:
                    item = stripped[2:].strip()
                    current_list.append(item)
            elif ':' in stripped:
                if current_key is not None and current_list:
                    fm[current_key] = current_list
                    current_list = []

                key, val = stripped.split(':', 1)
                key = key.strip()
                val = val.strip()
                current_key = key

                if val:
                    fm[key] = val
                    current_key = None

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

        if isinstance(tags_value, list):
            for tag in tags_value:
                tags.add(str(tag).strip())
        else:
            tags_str = str(tags_value)
            if ',' in tags_str:
                for tag in tags_str.split(','):
                    tag = tag.strip()
                    if tag:
                        tags.add(tag)
            else:
                for tag in tags_str.split():
                    tag = tag.strip()
                    if tag:
                        tags.add(tag)

        return tags

    def _count_words(self, text: str) -> int:
        return len(text.split())

    def _rel(self, note_path: Path) -> str:
        return str(note_path.relative_to(self.vault_path))

    def _get_para_category(self, note_path: Path) -> Optional[str]:
        """Extract top-level PARA category from note path."""
        try:
            parts = note_path.relative_to(self.vault_path).parts
            if parts and parts[0] in {'0.INBOX', '1.PROYECTOS', '2.AREAS',
                                      '3.RECURSOS', '4.ARCHIVO'}:
                return parts[0]
        except ValueError:
            pass
        return None

    def _status(self, tags: Set[str]) -> Optional[str]:
        for tag in tags:
            if tag.startswith('status/'):
                return tag.split('/', 1)[1]
        return None

    def _note_class(self, note: Path, fm: Dict, tags: Set[str]) -> str:
        """Classify a note so each check can target the right population.

        Classes:
          hidden      - dotfiles / operational files (.sync-*.md)
          excalidraw  - drawings, not prose
          template    - template scaffolds
          derived     - distilled / atomic knowledge layer
                        (anything nested inside a Domain Knowledge subfolder:
                         Glossary, PPPs courses, ChatGPT-distilled notes, ...)
          index       - numbered structural files (00-Index, 01-To-Do, ...) or type/moc hubs
          archive     - 4.ARCHIVO
          inbox       - 0.INBOX
          reference   - 3.RECURSOS authored material (hubs, summaries, etc.)
          core        - active substantive notes (1.PROYECTOS, 2.AREAS, ...)
        """
        name = note.name
        rel = self._rel(note)
        parts = note.relative_to(self.vault_path).parts
        top = self._get_para_category(note)

        if name.startswith('.'):
            return 'hidden'
        if name.endswith('.excalidraw.md'):
            return 'excalidraw'
        if name.startswith('_Template') or 'Template' in name:
            return 'template'
        # Derived knowledge layer: nested under a Domain Knowledge subfolder.
        if (len(parts) >= 4 and parts[0] == '3.RECURSOS'
                and parts[1] == 'Domain Knowledge'):
            return 'derived'
        if self.INDEX_RE.match(name) or 'type/moc' in tags:
            return 'index'
        if top == '4.ARCHIVO':
            return 'archive'
        if top == '0.INBOX':
            return 'inbox'
        if top == '3.RECURSOS':
            return 'reference'
        return 'core'

    def _analyse(self, note: Path) -> Tuple[Dict, str, Set[str], str]:
        content = self._read_note(note)
        fm, body = self._parse_frontmatter(content)
        tags = self._extract_tags(fm)
        cls = self._note_class(note, fm, tags)
        return fm, body, tags, cls

    # ------------------------------------------------------------------ checks

    def check_tag_coverage(self) -> Dict:
        """Find taggable notes missing required tag categories.

        Excludes non-prose classes (drawings, dotfiles, templates).
        """
        results = {
            'total_checked': 0,
            'by_missing_tag': defaultdict(list),
            'by_note': {},
            'summary': {}
        }

        checked = 0
        for note, (fm, _body, tags, cls) in self._cache.items():
            if cls in self.NONPROSE_CLASSES:
                continue
            checked += 1

            tag_categories = {t.split('/')[0] for t in tags if '/' in t}
            missing = self.REQUIRED_TAGS - tag_categories

            if missing:
                rel = self._rel(note)
                results['by_note'][rel] = sorted(missing)
                for category in missing:
                    results['by_missing_tag'][category].append(rel)

        results['total_checked'] = checked
        for category in self.REQUIRED_TAGS:
            count = len(results['by_missing_tag'][category])
            results['summary'][category] = {
                'missing_count': count,
                'coverage_pct': 100.0 * (checked - count) / checked if checked else 0
            }

        results['by_missing_tag'] = dict(results['by_missing_tag'])
        return results

    def _linkable_notes(self) -> List[Path]:
        return [n for n, (_f, _b, _t, cls) in self._cache.items()
                if cls in self.LINKABLE_CLASSES]

    def check_orphan_notes_outgoing(self) -> Dict:
        """Notes in the linkable working set with zero outgoing wikilinks."""
        results = {'total_orphans': 0, 'checked': 0,
                   'by_folder': defaultdict(list), 'orphan_percentage': 0.0}

        linkable = self._linkable_notes()
        for note in linkable:
            content = self._read_note(note)
            if not extract_wiki_links(content):
                rel = self._rel(note)
                results['by_folder'][self._get_para_category(note) or 'Other'].append(rel)
                results['total_orphans'] += 1

        results['checked'] = len(linkable)
        results['orphan_percentage'] = (100.0 * results['total_orphans'] / len(linkable)
                                        if linkable else 0)
        results['by_folder'] = dict(results['by_folder'])
        return results

    @staticmethod
    def _link_basename(link: str) -> str:
        """Normalise a wikilink target to its file basename (drop alias/anchor/path)."""
        target = link.split('|', 1)[0].split('#', 1)[0].strip()
        return Path(target).stem

    def check_orphan_notes_incoming(self) -> Dict:
        """Linkable notes never referenced by any other note (single-pass index)."""
        results = {'total_orphans': 0, 'checked': 0,
                   'by_folder': defaultdict(list), 'orphan_percentage': 0.0}

        # Build the set of referenced basenames once, scanning every note's links.
        referenced: Set[str] = set()
        for note in self.notes:
            for link in extract_wiki_links(self._read_note(note)):
                referenced.add(self._link_basename(link))

        linkable = self._linkable_notes()
        for note in linkable:
            if note.stem not in referenced:
                rel = self._rel(note)
                results['by_folder'][self._get_para_category(note) or 'Other'].append(rel)
                results['total_orphans'] += 1

        results['checked'] = len(linkable)
        results['orphan_percentage'] = (100.0 * results['total_orphans'] / len(linkable)
                                        if linkable else 0)
        results['by_folder'] = dict(results['by_folder'])
        return results

    def check_status_location_mismatches(self) -> Dict:
        """Genuine status/location misplacements only.

        Flags:
          - active-status notes sitting in 4.ARCHIVO
          - archived/published notes still parked in 0.INBOX (should be filed)
          - a project whose 00-Index is status/archived but still under 1.PROYECTOS

        Does NOT flag archived reference material in 3.RECURSOS or archived
        sub-notes inside active project folders: those are normal.
        """
        results = {
            'active_in_archivo': [],
            'stuck_in_inbox': [],
            'archived_project_not_moved': [],
            'total_issues': 0
        }

        for note, (_fm, _body, tags, _cls) in self._cache.items():
            status = self._status(tags)
            if status is None:
                continue
            rel = self._rel(note)
            top = self._get_para_category(note)

            if status == 'active' and top == '4.ARCHIVO':
                results['active_in_archivo'].append(rel)
            elif status in ('archived', 'published') and top == '0.INBOX':
                results['stuck_in_inbox'].append(rel)
            elif (status == 'archived' and top == '1.PROYECTOS'
                  and note.name == '00-Index.md'):
                results['archived_project_not_moved'].append(rel)

        results['total_issues'] = (len(results['active_in_archivo'])
                                   + len(results['stuck_in_inbox'])
                                   + len(results['archived_project_not_moved']))
        return results

    def check_stub_notes(self, min_words: int = 50) -> Dict:
        """Short notes among substantive prose, with by-design-short reported apart."""
        results = {
            'stub_threshold_words': min_words,
            'stubs': [],
            'total_stubs': 0,
            'checked': 0,
            'stub_percentage': 0.0,
            'short_by_design': 0,
            'short_by_design_by_class': defaultdict(int),
        }

        checked = 0
        for note, (_fm, body, _tags, cls) in self._cache.items():
            words = self._count_words(body.strip())
            if cls in self.BY_DESIGN_SHORT:
                if words < min_words:
                    results['short_by_design'] += 1
                    results['short_by_design_by_class'][cls] += 1
                continue
            checked += 1
            if words < min_words:
                results['stubs'].append({'path': self._rel(note), 'words': words})
                results['total_stubs'] += 1

        results['checked'] = checked
        results['stub_percentage'] = (100.0 * results['total_stubs'] / checked
                                      if checked else 0)
        results['short_by_design_by_class'] = dict(results['short_by_design_by_class'])
        return results

    def class_distribution(self) -> Dict[str, int]:
        dist = defaultdict(int)
        for _n, (_f, _b, _t, cls) in self._cache.items():
            dist[cls] += 1
        return dict(dist)

    def scan(self, checks: Optional[List[str]] = None) -> Dict:
        if checks is None:
            checks = ['tags', 'orphans', 'status', 'stubs']

        self.results['class_distribution'] = self.class_distribution()

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
        summary = {
            'vault': {
                'path': str(self.vault_path),
                'total_notes': len(self.notes),
                'scan_date': self.results['scan_date']
            },
            'health_metrics': {}
        }
        checks = self.results.get('checks', {})
        hm = summary['health_metrics']

        if 'tag_coverage' in checks:
            tc = checks['tag_coverage']
            s = tc['summary']
            coverage = sum(v['coverage_pct'] for v in s.values()) / len(s) if s else 0
            hm['tag_coverage_pct'] = round(coverage, 1)
            hm['taggable_checked'] = tc['total_checked']
            hm['notes_missing_tags'] = len(tc['by_note'])

        if 'orphan_outgoing' in checks:
            oo = checks['orphan_outgoing']
            hm['orphan_outgoing_pct'] = round(oo['orphan_percentage'], 1)
            hm['orphan_outgoing_count'] = oo['total_orphans']

        if 'orphan_incoming' in checks:
            oi = checks['orphan_incoming']
            hm['orphan_incoming_pct'] = round(oi['orphan_percentage'], 1)
            hm['orphan_incoming_count'] = oi['total_orphans']

        if 'status_location' in checks:
            hm['status_location_issues'] = checks['status_location']['total_issues']

        if 'stubs' in checks:
            st = checks['stubs']
            hm['core_stub_pct'] = round(st['stub_percentage'], 1)
            hm['core_stubs'] = st['total_stubs']
            hm['short_by_design'] = st['short_by_design']

        return summary


def format_section(title: str, width: int = 80) -> str:
    return f"\n{'=' * width}\n{title.center(width)}\n{'=' * width}\n"


def print_results(scanner: VaultHealthScanner, summary: Dict, verbose: bool = False):
    print(format_section("VAULT HEALTH SCAN"))
    print(f"Vault:       {summary['vault']['path']}")
    print(f"Date:        {summary['vault']['scan_date']}")
    print(f"Total Notes: {summary['vault']['total_notes']}")

    dist = scanner.results.get('class_distribution', {})
    if dist:
        order = ['core', 'reference', 'index', 'derived', 'inbox', 'archive',
                 'excalidraw', 'template', 'hidden']
        parts = [f"{k} {dist[k]}" for k in order if dist.get(k)]
        print("Note classes: " + ", ".join(parts))

    print(format_section("HEALTH METRICS"))
    for metric, value in summary['health_metrics'].items():
        if isinstance(value, float):
            print(f"  {metric:<35} {value:>6.1f}%")
        else:
            print(f"  {metric:<35} {value:>6}")

    checks = scanner.results.get('checks', {})

    if 'tag_coverage' in checks:
        tc = checks['tag_coverage']
        print(format_section("TAG COVERAGE (taggable notes)"))
        print(f"  Checked: {tc['total_checked']} notes "
              f"(non-prose classes excluded)\n")
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

    if 'orphan_outgoing' in checks:
        oo = checks['orphan_outgoing']
        print(format_section("ORPHANS - No Outgoing Links (working set)"))
        print(f"  {oo['total_orphans']} of {oo['checked']} linkable notes "
              f"({oo['orphan_percentage']:.1f}%)\n")
        if verbose:
            for folder in sorted(oo['by_folder']):
                paths = oo['by_folder'][folder]
                print(f"  {folder}: {len(paths)}")
                for path in sorted(paths)[:5]:
                    print(f"      - {path}")
                if len(paths) > 5:
                    print(f"      ... and {len(paths) - 5} more")

    if 'orphan_incoming' in checks:
        oi = checks['orphan_incoming']
        print(format_section("ORPHANS - No Incoming Links (working set)"))
        print(f"  {oi['total_orphans']} of {oi['checked']} linkable notes "
              f"({oi['orphan_percentage']:.1f}%)\n")
        if verbose:
            for folder in sorted(oi['by_folder']):
                paths = oi['by_folder'][folder]
                print(f"  {folder}: {len(paths)}")
                for path in sorted(paths)[:5]:
                    print(f"      - {path}")
                if len(paths) > 5:
                    print(f"      ... and {len(paths) - 5} more")

    if 'status_location' in checks:
        sl = checks['status_location']
        print(format_section("STATUS / LOCATION MISMATCHES"))

        def block(label, items):
            if items:
                print(f"  {label} ({len(items)}):")
                for path in sorted(items)[:10]:
                    print(f"      - {path}")
                if len(items) > 10:
                    print(f"      ... and {len(items) - 10} more")
                print()

        block("Active status in 4.ARCHIVO", sl['active_in_archivo'])
        block("Archived/published parked in 0.INBOX", sl['stuck_in_inbox'])
        block("Archived project still under 1.PROYECTOS", sl['archived_project_not_moved'])
        if sl['total_issues'] == 0:
            print("  No genuine mismatches found.")

    if 'stubs' in checks:
        st = checks['stubs']
        print(format_section("STUB NOTES (< 50 words, substantive prose)"))
        print(f"  {st['total_stubs']} of {st['checked']} substantive notes "
              f"({st['stub_percentage']:.1f}%)")
        by_cls = st.get('short_by_design_by_class', {})
        detail = ", ".join(f"{k} {v}" for k, v in sorted(by_cls.items())) if by_cls else "none"
        print(f"  Short by design (excluded): {st['short_by_design']}  [{detail}]\n")
        if verbose and st['stubs']:
            for stub in sorted(st['stubs'], key=lambda x: x['words'])[:10]:
                print(f"      {stub['path']:<50} ({stub['words']:>3} words)")
            if len(st['stubs']) > 10:
                print(f"      ... and {len(st['stubs']) - 10} more")

    print(format_section("END OF SCAN"))


def main():
    parser = argparse.ArgumentParser(
        description='Scan an Obsidian vault for health issues, calibrated to the '
                    'JC vault structure (active working set vs derived layers).'
    )
    parser.add_argument('--vault', type=str,
                        default=str(Path.home() / 'obsidian' / 'JC'),
                        help='Path to Obsidian vault (default: ~/obsidian/JC)')
    parser.add_argument('--check', type=str,
                        help='Run only specific check(s): tags, orphans, status, '
                             'stubs, all (comma-separated).')
    parser.add_argument('--verbose', action='store_true',
                        help='List individual file paths in results')
    parser.add_argument('--json', action='store_true',
                        help='Output results as JSON')

    args = parser.parse_args()

    vault_path = Path(args.vault)
    if not vault_path.exists():
        print(f"Error: Vault path does not exist: {args.vault}")
        return 1
    if not vault_path.is_dir():
        print(f"Error: Vault path is not a directory: {args.vault}")
        return 1

    checks = None
    if args.check:
        if args.check == 'all':
            checks = ['tags', 'orphans', 'status', 'stubs']
        else:
            checks = [c.strip() for c in args.check.split(',')]
            valid_checks = {'tags', 'orphans', 'status', 'stubs'}
            for check in checks:
                if check not in valid_checks:
                    print(f"Error: Invalid check type '{check}'. "
                          f"Valid options: {', '.join(sorted(valid_checks))}")
                    return 1

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
