#!/usr/bin/env python3
"""
Escape inline hashtags in Obsidian notes to prevent them from being interpreted as tags.

This script finds hashtags in note content (outside of frontmatter and code blocks)
that are NOT valid taxonomy tags, and wraps them in backticks to escape them.

Common cases:
- Discord channel names: #general, #support, #announcements
- Social media hashtags: #AI, #coding
- Other inline hashtags that shouldn't be vault tags

Usage:
    python escape_inline_hashtags.py /path/to/vault          # Dry run (default)
    python escape_inline_hashtags.py /path/to/vault --execute # Actually modify files
    python escape_inline_hashtags.py /path/to/vault --report  # Show summary only
"""

import re
import argparse
from pathlib import Path
from typing import Set, List, Tuple, Dict
from collections import defaultdict

# Import shared utilities
from obsidian_utils import get_all_notes, validate_vault_path

# Valid taxonomy tags (these should NOT be escaped even if found inline)
VALID_TAGS: Set[str] = {
    # type/
    'type/article', 'type/book', 'type/chapter', 'type/chatgpt-conversation',
    'type/moc', 'type/note', 'type/project', 'type/reference', 'type/template',
    'type/video',
    # status/
    'status/archived', 'status/draft', 'status/expanded', 'status/idea',
    'status/in-progress', 'status/paused', 'status/published', 'status/review',
    'status/someday',
    # topic/ (35 tags)
    'topic/ai', 'topic/asset-management', 'topic/automation', 'topic/climate-adaptation',
    'topic/climate-risk', 'topic/concessions', 'topic/construction',
    'topic/data', 'topic/demand-risk', 'topic/digital-infrastructure',
    'topic/digital-transformation', 'topic/digital-twins', 'topic/energy',
    'topic/fiscal-management', 'topic/governance', 'topic/green-finance',
    'topic/infrastructure-delivery', 'topic/ml', 'topic/operational-risk',
    'topic/policy', 'topic/ppp', 'topic/procurement', 'topic/project-finance',
    'topic/public-sector', 'topic/rail', 'topic/regulation', 'topic/resilience',
    'topic/risk', 'topic/risk-allocation', 'topic/roads', 'topic/sustainability',
    'topic/transparency', 'topic/transport', 'topic/value-for-money', 'topic/water',
    # lang/
    'lang/en', 'lang/es',
    # source/
    'source/chatgpt', 'source/kindle', 'source/own-writing', 'source/pdf',
    'source/readwise', 'source/video', 'source/web', 'source/youtube',
    # context/
    'context/africa', 'context/europe', 'context/ireland', 'context/latam',
    'context/spain', 'context/typsa',
}

# Common Discord channel patterns to escape
DISCORD_CHANNEL_PATTERNS = [
    'general', 'support', 'announcements', 'welcome', 'rules', 'help',
    'chat', 'random', 'feedback', 'community', 'lounge', 'off-topic',
    'introductions', 'showcase', 'resources', 'faq', 'bugs', 'dev',
    'bot', 'bots', 'music', 'gaming', 'memes', 'art', 'media',
    'links', 'news', 'updates', 'voice', 'commands', 'logs', 'admin',
    'moderator', 'mod', 'test', 'testing', 'spam', 'nsfw', 'selfpromo',
    'promo', 'server', 'roles', 'verify', 'verification', 'tickets',
]


def extract_frontmatter_end(content: str) -> int:
    """Find where frontmatter ends (return 0 if no frontmatter)."""
    if not content.startswith('---'):
        return 0

    # Find the closing ---
    second_marker = content.find('---', 3)
    if second_marker == -1:
        return 0

    return second_marker + 3


def is_in_code_block(content: str, position: int) -> bool:
    """Check if a position is inside a code block."""
    # Count ``` before this position
    before = content[:position]

    # Count opening and closing triple backticks
    backtick_count = before.count('```')

    # If odd number, we're inside a code block
    return backtick_count % 2 == 1


def is_in_inline_code(content: str, position: int) -> bool:
    """Check if a position is inside inline code (single backticks)."""
    # Find the start of the current line
    line_start = content.rfind('\n', 0, position) + 1
    line_end = content.find('\n', position)
    if line_end == -1:
        line_end = len(content)

    line = content[line_start:line_end]
    pos_in_line = position - line_start

    # Count single backticks before this position in the line
    before_in_line = line[:pos_in_line]

    # Simple check: odd number of backticks means we're inside
    # (This is a simplification but works for most cases)
    single_count = before_in_line.count('`') - before_in_line.count('```') * 3
    return single_count % 2 == 1


def is_in_wikilink(content: str, position: int) -> bool:
    """Check if position is inside a wikilink [[...]]."""
    # Look backwards for [[ without closing ]]
    before = content[:position]
    last_open = before.rfind('[[')
    if last_open == -1:
        return False

    last_close = before.rfind(']]', last_open)
    return last_close < last_open


def is_in_markdown_link(content: str, position: int) -> bool:
    """Check if position is inside a markdown link [text](url)."""
    # Look for pattern: either in [text] or in (url) part
    # Check for [...] context
    before = content[:position]

    # Check if we're in the URL part (...)
    last_paren_open = before.rfind('(')
    if last_paren_open != -1:
        # Check if there's a ] before the (
        if last_paren_open > 0 and content[last_paren_open - 1] == ']':
            last_paren_close = before.rfind(')', last_paren_open)
            if last_paren_close < last_paren_open:
                return True

    return False


def should_escape_tag(tag: str) -> bool:
    """Determine if a hashtag should be escaped."""
    tag_lower = tag.lower()

    # Don't escape valid taxonomy tags (exact match)
    if tag_lower in VALID_TAGS:
        return False

    # Tags with valid category prefix that exist in taxonomy should not be escaped
    # This handles inline references like #status/active in documentation
    if '/' in tag:
        # Check if this is a valid taxonomy tag
        if tag_lower in VALID_TAGS:
            return False
        # Check if prefix is from valid category
        known_prefixes = {'type', 'status', 'topic', 'lang', 'source', 'context'}
        prefix = tag.split('/')[0].lower()
        if prefix in known_prefixes:
            # This might be a typo or new tag - let's not escape it
            # since it follows the taxonomy pattern
            return False

    # Always escape Discord channel-like patterns
    if tag_lower in DISCORD_CHANNEL_PATTERNS:
        return True

    # Escape if it contains hyphen and looks like a channel (no /)
    if '-' in tag_lower and '/' not in tag:
        return True

    # Escape bare tags (no category prefix) - these are the problematic ones
    if '/' not in tag:
        return True

    return False


def find_inline_hashtags(content: str) -> List[Tuple[int, int, str]]:
    """
    Find all inline hashtags that should be escaped.

    Returns list of (start_pos, end_pos, tag_text) tuples.
    """
    results = []

    # Skip frontmatter
    content_start = extract_frontmatter_end(content)

    # Pattern: # followed by optional emoji(s) then word characters
    # This captures:
    # - Nested tags like #status/active
    # - Bare tags like #general
    # - Emoji-prefixed Discord channels like #❓q-and-a-questions or #📚resources-library
    # But not already in backticks
    # Emoji range includes common emoji blocks
    pattern = r'(?<![`\w])#([\U0001F300-\U0001F9FF\u2600-\u27BF]*[a-zA-Z][a-zA-Z0-9_/-]*)'

    for match in re.finditer(pattern, content[content_start:]):
        abs_pos = content_start + match.start()
        tag_text = match.group(1)

        # Skip if in code block, inline code, or links
        if is_in_code_block(content, abs_pos):
            continue
        if is_in_inline_code(content, abs_pos):
            continue
        if is_in_wikilink(content, abs_pos):
            continue
        if is_in_markdown_link(content, abs_pos):
            continue

        # Check if this tag should be escaped
        if should_escape_tag(tag_text):
            end_pos = abs_pos + len(match.group(0))
            results.append((abs_pos, end_pos, tag_text))

    return results


def escape_hashtags_in_content(content: str) -> Tuple[str, List[str]]:
    """
    Escape inline hashtags by wrapping them in backticks.

    Returns (modified_content, list_of_escaped_tags).
    """
    hashtags = find_inline_hashtags(content)

    if not hashtags:
        return content, []

    # Process in reverse order to maintain positions
    escaped_tags = []
    for start, end, tag in reversed(hashtags):
        original = content[start:end]
        escaped = f'`{original}`'
        content = content[:start] + escaped + content[end:]
        escaped_tags.append(tag)

    escaped_tags.reverse()  # Return in original order
    return content, escaped_tags


def process_vault(vault_path: Path, dry_run: bool = True, report_only: bool = False) -> Dict:
    """Process all notes in vault, escaping inline hashtags."""
    notes = get_all_notes(vault_path)

    stats = {
        'total_notes': len(notes),
        'notes_with_hashtags': 0,
        'total_hashtags_escaped': 0,
        'hashtag_counts': defaultdict(int),
        'files_modified': [],
    }

    for note in notes:
        try:
            content = note.read_text(encoding='utf-8')
        except Exception as e:
            print(f"Error reading {note}: {e}")
            continue

        hashtags = find_inline_hashtags(content)

        if not hashtags:
            continue

        stats['notes_with_hashtags'] += 1
        stats['total_hashtags_escaped'] += len(hashtags)

        for _, _, tag in hashtags:
            stats['hashtag_counts'][tag] += 1

        if report_only:
            continue

        # Escape the hashtags
        new_content, escaped = escape_hashtags_in_content(content)

        if dry_run:
            rel_path = note.relative_to(vault_path)
            print(f"\n[DRY RUN] Would escape in {rel_path}:")
            for tag in escaped:
                print(f"  #{tag} -> `#{tag}`")
        else:
            note.write_text(new_content, encoding='utf-8')
            rel_path = note.relative_to(vault_path)
            stats['files_modified'].append(str(rel_path))
            print(f"Escaped {len(escaped)} hashtags in {rel_path}")

    return stats


def print_report(stats: Dict):
    """Print summary report."""
    print("\n" + "=" * 60)
    print("INLINE HASHTAG ESCAPE REPORT")
    print("=" * 60)

    print(f"\nTotal notes scanned: {stats['total_notes']}")
    print(f"Notes with escapable hashtags: {stats['notes_with_hashtags']}")
    print(f"Total hashtags to escape: {stats['total_hashtags_escaped']}")

    if stats['hashtag_counts']:
        print("\nTop hashtags by frequency:")
        sorted_tags = sorted(stats['hashtag_counts'].items(),
                           key=lambda x: x[1], reverse=True)
        for tag, count in sorted_tags[:30]:
            print(f"  #{tag}: {count}")

    if stats['files_modified']:
        print(f"\nFiles modified: {len(stats['files_modified'])}")


def main():
    parser = argparse.ArgumentParser(
        description='Escape inline hashtags in Obsidian notes'
    )
    parser.add_argument('vault_path', help='Path to Obsidian vault')
    parser.add_argument('--execute', action='store_true',
                       help='Actually modify files (default is dry run)')
    parser.add_argument('--report', action='store_true',
                       help='Only show report, no file details')

    args = parser.parse_args()

    # Validate vault path
    is_valid, error = validate_vault_path(args.vault_path)
    if not is_valid:
        print(f"Error: {error}")
        return 1

    vault_path = Path(args.vault_path)
    dry_run = not args.execute

    if dry_run and not args.report:
        print("=" * 60)
        print("DRY RUN MODE - No files will be modified")
        print("Use --execute to actually modify files")
        print("=" * 60)

    stats = process_vault(vault_path, dry_run=dry_run, report_only=args.report)
    print_report(stats)

    if dry_run and stats['notes_with_hashtags'] > 0:
        print("\nRun with --execute to apply changes")

    return 0


if __name__ == '__main__':
    exit(main())
