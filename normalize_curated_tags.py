#!/usr/bin/env python3
"""
Normalize tags in curated Evernote notes to match the approved JC vault taxonomy.

This script:
1. Finds notes with inline array tags format: tags: ['tag1', 'tag2', ...]
2. Maps bare tags to approved topic/type/status/source/lang/context categories
3. Removes unmappable tags (they add noise, not value)
4. Converts inline array format to YAML list format

Usage:
    python normalize_curated_tags.py                    # Dry run (default)
    python normalize_curated_tags.py --execute          # Actually modify files
    python normalize_curated_tags.py --report           # Generate tag frequency report
"""

import argparse
import re
from pathlib import Path
from collections import Counter
from typing import Dict, List, Set, Tuple, Optional

# =============================================================================
# APPROVED TAG TAXONOMY (70 tags)
# =============================================================================

APPROVED_TAGS = {
    # TYPE/ (10)
    'type/article', 'type/book', 'type/chatgpt-conversation', 'type/course',
    'type/idea', 'type/meeting', 'type/moc', 'type/note', 'type/project',
    'type/reference',

    # STATUS/ (9)
    'status/idea', 'status/outline', 'status/expanded', 'status/draft',
    'status/review', 'status/published', 'status/active', 'status/paused',
    'status/archived',

    # TOPIC/ (35)
    'topic/ppp', 'topic/project-finance', 'topic/infrastructure-delivery',
    'topic/asset-management', 'topic/value-for-money', 'topic/concessions',
    'topic/fiscal-management', 'topic/risk-allocation', 'topic/procurement',
    'topic/construction', 'topic/risk', 'topic/resilience', 'topic/climate-risk',
    'topic/operational-risk', 'topic/demand-risk', 'topic/transport', 'topic/roads',
    'topic/rail', 'topic/water', 'topic/energy', 'topic/digital-infrastructure',
    'topic/governance', 'topic/policy', 'topic/regulation', 'topic/transparency',
    'topic/public-sector', 'topic/ai', 'topic/ml', 'topic/data',
    'topic/digital-transformation', 'topic/digital-twins', 'topic/automation',
    'topic/sustainability', 'topic/climate-adaptation', 'topic/green-finance',

    # LANG/ (2)
    'lang/en', 'lang/es',

    # SOURCE/ (8)
    'source/own-writing', 'source/chatgpt', 'source/web', 'source/book',
    'source/course', 'source/pdf', 'source/linkedin', 'source/meeting',

    # CONTEXT/ (6)
    'context/typsa', 'context/spain', 'context/africa', 'context/ireland',
    'context/latam', 'context/europe',
}

# =============================================================================
# TAG MAPPING: bare tag -> approved tag (or None to remove)
# =============================================================================

TAG_MAPPING: Dict[str, Optional[str]] = {
    # === DIRECT MAPPINGS (tag already has correct value, just needs prefix) ===
    'asset-management': 'topic/asset-management',
    'climate-change': 'topic/climate-risk',
    'climate-risk': 'topic/climate-risk',
    'climate-adaptation': 'topic/climate-adaptation',
    'digital-transformation': 'topic/digital-transformation',
    'digital-infrastructure': 'topic/digital-infrastructure',
    'digital-twins': 'topic/digital-twins',
    'digital-twin': 'topic/digital-twins',
    'infrastructure-delivery': 'topic/infrastructure-delivery',
    'project-finance': 'topic/project-finance',
    'public-private-partnerships': 'topic/ppp',
    'risk-allocation': 'topic/risk-allocation',
    'risk-management': 'topic/risk',
    'risk-assessment': 'topic/risk',
    'risk-mitigation': 'topic/risk',
    'risk-analysis': 'topic/risk',
    'sustainability': 'topic/sustainability',
    'sustainable-development': 'topic/sustainability',
    'sustainable-development-goals': 'topic/sustainability',
    'green-finance': 'topic/green-finance',
    'governance': 'topic/governance',
    'transparency': 'topic/transparency',
    'regulation': 'topic/regulation',
    'policy': 'topic/policy',
    'procurement': 'topic/procurement',
    'construction': 'topic/construction',
    'resilience': 'topic/resilience',
    'resilience-planning': 'topic/resilience',

    # === SECTOR MAPPINGS ===
    'renewable-energy': 'topic/energy',
    'energy-transition': 'topic/energy',
    'solar-energy': 'topic/energy',
    'wind-energy': 'topic/energy',
    'hydropower': 'topic/energy',
    'power-generation': 'topic/energy',
    'electricity-generation': 'topic/energy',
    'electricity-market': 'topic/energy',
    'energy-efficiency': 'topic/energy',
    'energy-infrastructure': 'topic/energy',

    'water-infrastructure': 'topic/water',
    'water-management': 'topic/water',
    'water-governance': 'topic/water',
    'water-supply': 'topic/water',
    'water-resources': 'topic/water',
    'sanitation-systems': 'topic/water',
    'wastewater-services': 'topic/water',
    'desalination': 'topic/water',
    'clean-water': 'topic/water',
    'fecal-sludge-management': 'topic/water',

    'traffic-management': 'topic/transport',
    'transportation-infrastructure': 'topic/transport',
    'transport-infrastructure': 'topic/transport',
    'mobility-solutions': 'topic/transport',
    'autonomous-vehicles': 'topic/transport',
    'electric-vehicles': 'topic/transport',
    'high-speed-rail': 'topic/rail',
    'railways': 'topic/rail',
    'hsr': 'topic/rail',
    'toll-roads': 'topic/roads',
    'road-network': 'topic/roads',
    'road-maintenance': 'topic/roads',

    # === AI/DIGITAL MAPPINGS ===
    'artificial-intelligence': 'topic/ai',
    'machine-learning': 'topic/ml',
    'deep-learning': 'topic/ml',
    'data-analytics': 'topic/data',
    'data-analysis': 'topic/data',
    'data-collection': 'topic/data',
    'data-management': 'topic/data',
    'big-data': 'topic/data',
    'data-sharing': 'topic/data',
    'open-data': 'topic/data',
    'geospatial-data': 'topic/data',
    'smart-systems': 'topic/digital-transformation',
    'smart-cities': 'topic/digital-transformation',
    'smart-infrastructure': 'topic/digital-transformation',
    'technology-adoption': 'topic/digital-transformation',
    'technology-innovation': 'topic/digital-transformation',
    'construction-technology': 'topic/digital-transformation',
    'internet-of-things': 'topic/digital-infrastructure',
    'sensors': 'topic/digital-infrastructure',

    # === GOVERNANCE/POLICY MAPPINGS ===
    'regulatory-compliance': 'topic/regulation',
    'regulatory-framework': 'topic/regulation',
    'regulatory-frameworks': 'topic/regulation',
    'policy-development': 'topic/policy',
    'policy-analysis': 'topic/policy',
    'public-policy': 'topic/policy',
    'governance-framework': 'topic/governance',
    'corporate-governance': 'topic/governance',
    'stakeholder-engagement': 'topic/governance',
    'accountability': 'topic/transparency',
    'anti-corruption': 'topic/transparency',
    'public-sector': 'topic/public-sector',
    'public-administration': 'topic/public-sector',
    'institutional-capacity': 'topic/public-sector',

    # === FINANCE/INVESTMENT MAPPINGS ===
    'investment-strategies': 'topic/project-finance',
    'investment-strategy': 'topic/project-finance',
    'infrastructure-investment': 'topic/project-finance',
    'financial-structures': 'topic/project-finance',
    'funding-mechanisms': 'topic/project-finance',
    'impact-investing': 'topic/project-finance',
    'fiscal-management': 'topic/fiscal-management',
    'value-for-money': 'topic/value-for-money',
    'concessions': 'topic/concessions',

    # === RISK MAPPINGS ===
    'critical-infrastructure': 'topic/risk',
    'cybersecurity': 'topic/risk',
    'cyber-security': 'topic/risk',
    'ciberseguridad': 'topic/risk',
    'security-frameworks': 'topic/risk',
    'threat-mitigation': 'topic/risk',
    'business-continuity': 'topic/risk',
    'vulnerability-analysis': 'topic/risk',
    'vulnerability-assessment': 'topic/risk',
    'natural-disasters': 'topic/climate-risk',
    'extreme-weather': 'topic/climate-risk',
    'flood-risk': 'topic/climate-risk',
    'operational-risk': 'topic/operational-risk',
    'demand-risk': 'topic/demand-risk',

    # === SPANISH TERMS ===
    'sostenibilidad': 'topic/sustainability',
    'gobernanza': 'topic/governance',
    'transparencia': 'topic/transparency',
    'infraestructura': 'topic/infrastructure-delivery',
    'infraestructura-crítica': 'topic/risk',
    'crecimiento-económico': None,  # Too generic
    'gestión-de-riesgos': 'topic/risk',
    'políticas-públicas': 'topic/policy',

    # === LANGUAGE TAGS (already correct) ===
    'lang/en': 'lang/en',
    'lang/es': 'lang/es',

    # === SOURCE TAGS ===
    'chatgpt': 'source/chatgpt',

    # === STATUS TAG FIXES ===
    'status/finished': 'status/archived',

    # === GEOGRAPHIC CONTEXT (topic/* -> context/*) ===
    'topic/africa': 'context/africa',
    'topic/spain': 'context/spain',
    'topic/europe': 'context/europe',

    # === TYPE FIXES ===
    'type/documentation': 'type/reference',

    # === TAGS TO REMOVE (too generic, not in taxonomy, or noise) ===
    'topic/infrastructure': None,  # Too generic
    'topic/finance': None,  # Too generic (use project-finance)
    'topic/digital': None,  # Too generic (use digital-transformation)
    'topic/consulting': None,  # Not in taxonomy
    'topic/python': None,  # Not in taxonomy
    'topic/obsidian': None,  # Not in taxonomy
    'topic/knowledge-management': None,  # Not in taxonomy
    'excalidraw': None,
    'professional-profile': None,
    'innovation': None,
    'resource-management': None,
    'environmental-impact': None,
    'decision-making': None,
    'blockchain-technology': None,
    'blockchain': None,
    'distributed-ledger': None,
    'digital-currency': None,
    'cryptocurrency': None,
    'smart-contracts': None,
    'public-health': None,
    'economic-growth': None,
    'economic-development': None,
    'economic-recovery': None,
    'urban-development': None,
    'urban-planning': None,
    'research-and-development': None,
    'case-studies': None,
    'collaboration': None,
    'capacity-building': None,
    'civil-engineering': None,
    'supply-chain': None,
    'strategic-planning': None,
    'project-management': None,
    'productivity-growth': None,
    'real-time-data': None,
    'backup': None,
    'meta': None,
    'agent': None,
    'work': None,
    'claude-code': None,
    'obsidian': None,
    'typsa': 'context/typsa',
    'typsa-gpt': None,

    # Generic catch-alls to remove
    'compliance': None,
    'innovation': None,
    'social-impact': None,
    'market-growth': None,
    'education': None,
    'leadership': None,
    'professionalism': None,
}

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def parse_inline_tags(tags_line: str) -> List[str]:
    """Parse inline array format: tags: ['tag1', 'tag2', ...]"""
    # Extract the array part
    match = re.search(r'\[([^\]]+)\]', tags_line)
    if not match:
        return []

    array_content = match.group(1)
    # Split by comma and clean up quotes
    tags = []
    for tag in array_content.split(','):
        tag = tag.strip().strip("'\"")
        if tag:
            tags.append(tag)
    return tags


def map_tag(bare_tag: str) -> Optional[str]:
    """Map a bare tag to an approved tag, or None to remove it."""
    # Already approved?
    if bare_tag in APPROVED_TAGS:
        return bare_tag

    # Check mapping
    if bare_tag in TAG_MAPPING:
        return TAG_MAPPING[bare_tag]

    # Try with topic/ prefix
    with_topic = f'topic/{bare_tag}'
    if with_topic in APPROVED_TAGS:
        return with_topic

    # Not mappable - will be removed
    return None


def format_yaml_tags(tags: List[str]) -> str:
    """Format tags as YAML list."""
    if not tags:
        return "tags: []"

    lines = ["tags:"]
    for tag in sorted(set(tags)):
        lines.append(f"  - {tag}")
    return "\n".join(lines)


def process_note(file_path: Path, dry_run: bool = True) -> Tuple[bool, List[str], List[str]]:
    """
    Process a single note file.

    Returns:
        (was_modified, kept_tags, removed_tags)
    """
    content = file_path.read_text(encoding='utf-8')

    # Check for inline array tags format
    match = re.search(r'^tags:\s*\[[^\]]+\]', content, re.MULTILINE)
    if not match:
        return False, [], []

    tags_line = match.group(0)
    bare_tags = parse_inline_tags(tags_line)

    # Map tags
    kept_tags = []
    removed_tags = []

    for tag in bare_tags:
        mapped = map_tag(tag)
        if mapped:
            kept_tags.append(mapped)
        else:
            removed_tags.append(tag)

    # Deduplicate while preserving order
    seen = set()
    unique_tags = []
    for tag in kept_tags:
        if tag not in seen:
            seen.add(tag)
            unique_tags.append(tag)
    kept_tags = unique_tags

    # Generate new YAML tags block
    new_tags_block = format_yaml_tags(kept_tags)

    # Replace in content
    new_content = content.replace(tags_line, new_tags_block)

    if not dry_run and new_content != content:
        file_path.write_text(new_content, encoding='utf-8')

    return True, kept_tags, removed_tags


def find_curated_notes(vault_path: Path) -> List[Path]:
    """Find all notes with inline array tags format."""
    notes = []

    for md_file in vault_path.rglob("*.md"):
        # Skip hidden directories
        if any(part.startswith('.') for part in md_file.parts):
            continue

        try:
            content = md_file.read_text(encoding='utf-8')
            if re.search(r'^tags:\s*\[[^\]]+\]', content, re.MULTILINE):
                notes.append(md_file)
        except Exception:
            continue

    return notes


# =============================================================================
# MAIN FUNCTIONS
# =============================================================================

def generate_report(vault_path: Path):
    """Generate a report of all unmapped tags."""
    notes = find_curated_notes(vault_path)
    print(f"Found {len(notes)} notes with inline array tags format\n")

    all_removed = Counter()
    all_kept = Counter()

    for note in notes:
        _, kept, removed = process_note(note, dry_run=True)
        for tag in kept:
            all_kept[tag] += 1
        for tag in removed:
            all_removed[tag] += 1

    print("=" * 60)
    print("TAGS BEING REMOVED (unmapped)")
    print("=" * 60)
    for tag, count in all_removed.most_common(100):
        print(f"  {count:4d}  {tag}")

    print("\n" + "=" * 60)
    print("TAGS BEING KEPT (mapped to approved taxonomy)")
    print("=" * 60)
    for tag, count in all_kept.most_common(50):
        print(f"  {count:4d}  {tag}")

    print(f"\nTotal unique tags removed: {len(all_removed)}")
    print(f"Total unique tags kept: {len(all_kept)}")


def run_normalization(vault_path: Path, dry_run: bool = True):
    """Run the normalization process."""
    notes = find_curated_notes(vault_path)
    print(f"Found {len(notes)} notes with inline array tags format")
    print(f"Mode: {'DRY RUN' if dry_run else 'EXECUTING'}\n")

    modified_count = 0
    total_kept = 0
    total_removed = 0

    for note in notes:
        was_modified, kept, removed = process_note(note, dry_run=dry_run)

        if was_modified:
            modified_count += 1
            total_kept += len(kept)
            total_removed += len(removed)

            if removed:  # Only print if we're removing tags
                rel_path = note.relative_to(vault_path)
                print(f"{'[DRY RUN] ' if dry_run else ''}Modified: {rel_path}")
                if len(removed) <= 5:
                    print(f"  Removed: {', '.join(removed)}")
                else:
                    print(f"  Removed: {len(removed)} tags")

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Notes processed: {len(notes)}")
    print(f"Notes modified: {modified_count}")
    print(f"Tags kept: {total_kept}")
    print(f"Tags removed: {total_removed}")

    if dry_run:
        print("\nThis was a DRY RUN. Use --execute to apply changes.")


def main():
    parser = argparse.ArgumentParser(
        description="Normalize curated Evernote tags to JC vault taxonomy"
    )
    parser.add_argument(
        "--vault",
        default="/Users/jose/obsidian/JC",
        help="Path to Obsidian vault"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually modify files (default is dry run)"
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Generate tag frequency report"
    )

    args = parser.parse_args()
    vault_path = Path(args.vault)

    if not vault_path.exists():
        print(f"Error: Vault path does not exist: {vault_path}")
        return 1

    if args.report:
        generate_report(vault_path)
    else:
        run_normalization(vault_path, dry_run=not args.execute)

    return 0


if __name__ == "__main__":
    exit(main())
