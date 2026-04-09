#!/usr/bin/env python3
"""
Obsidian Topic Tag Suggester

Uses an LLM to suggest topic/ tags for vault notes that are missing them.
Reads note content, presents the 35-tag topic taxonomy, and asks the LLM
to pick the 1-3 most appropriate tags.

Requirements:
    - OpenAI API key in .env file: OPENAI_API_KEY=sk-...
    - pip install openai python-dotenv
"""

import argparse
import json
import re
import sys
import os
import time
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass, field

try:
    from openai import OpenAI
    from dotenv import load_dotenv
except ImportError:
    print("Missing dependencies. Install with: pip install openai python-dotenv")
    sys.exit(1)

try:
    from obsidian_utils import get_all_notes, validate_vault_path
except ImportError:
    def get_all_notes(vault_path: Path, skip_trash: bool = True, skip_obsidian: bool = True) -> List[Path]:
        notes = []
        for md_file in vault_path.rglob("*.md"):
            if any(part.startswith('.') for part in md_file.parts):
                continue
            notes.append(md_file)
        return notes

    def validate_vault_path(vault_path: str) -> tuple:
        path = Path(vault_path)
        if not path.exists():
            return False, f"Vault path does not exist: {vault_path}"
        if not path.is_dir():
            return False, f"Vault path is not a directory: {vault_path}"
        return True, ""


# --- Configuration ---

OPENAI_MODEL = "gpt-4.1-mini"
BATCH_SIZE = 10  # Notes per API call
MAX_CONTENT_CHARS = 1500  # Max chars of note body to send

# Folders to skip entirely
SKIP_PREFIXES = [
    ".claude", ".copilot-index", ".obsidian", ".trash", ".git",
    "Templates", "Excalidraw", "Audios", "copilot-conversations",
]

# The 35 approved topic/ tags with keywords for the LLM prompt
TOPIC_TAXONOMY = """
## Infrastructure & PPP
- topic/ppp — PPP, concession, DBFM, BOT, P3, public-private partnership
- topic/project-finance — bankability, financing, SPV, lenders, financial close
- topic/infrastructure-delivery — procurement method, DBB, DB, CM/GC, delivery model
- topic/asset-management — lifecycle, maintenance, O&M, asset condition
- topic/value-for-money — VfM, PSC, fiscal responsibility, comparator
- topic/concessions — toll roads, revenue models, availability payments
- topic/fiscal-management — fiscal illusion, contingent liability, government accounting
- topic/risk-allocation — risk distribution, bankability testing, risk matrix
- topic/procurement — tender, evaluation, LCSP, bidding process
- topic/construction — construction productivity, delays, site management

## Risk & Resilience
- topic/risk — risk assessment, risk management, uncertainty
- topic/resilience — adaptation, disaster risk, recovery, robustness
- topic/climate-risk — climate change impact, extreme weather, warming
- topic/operational-risk — O&M risks, failure modes, operational disruption
- topic/demand-risk — traffic forecasting, optimism bias, revenue risk

## Sectors
- topic/transport — roads, highways, tolling, mobility, transport policy
- topic/roads — road-specific, pavement, road maintenance, road funds
- topic/rail — railways, high-speed rail, metro, light rail
- topic/water — water supply, wastewater, sanitation, water utility
- topic/energy — power generation, utilities, grid, renewable energy
- topic/digital-infrastructure — data networks, broadband, fiber, telecom

## Policy & Governance
- topic/governance — institutional frameworks, decision-making, reform
- topic/policy — public policy, strategic planning, national plans
- topic/regulation — legal frameworks, directives, regulatory bodies
- topic/transparency — accountability, disclosure, open data
- topic/public-sector — public sector capacity, reform, government

## Digital & AI
- topic/ai — artificial intelligence, LLM, GPT, machine learning applications
- topic/ml — machine learning, deep learning, neural networks
- topic/data — data governance, analytics, data quality
- topic/digital-transformation — digital tools, process innovation, Industry 4.0
- topic/digital-twins — simulation, predictive modeling, BIM
- topic/automation — AI agents, workflow automation, RPA

## Sustainability
- topic/sustainability — ESG, circular economy, sustainable development
- topic/climate-adaptation — climate-resilient infrastructure, adaptation planning
- topic/green-finance — green bonds, EU Taxonomy, sustainable finance
""".strip()


@dataclass
class TagSuggestion:
    rel_path: str
    current_tags: List[str]
    suggested_topics: List[str]
    confidence: str  # "high", "medium", "low"
    reasoning: str


def extract_frontmatter(content: str) -> Tuple[Optional[str], str]:
    """Extract frontmatter and body from note content."""
    if not content.startswith('---'):
        return None, content
    end_match = re.search(r'\n---\s*\n', content[3:])
    if not end_match:
        return None, content
    end_pos = end_match.end() + 3
    return content[:end_pos], content[end_pos:]


def get_tags(frontmatter: str) -> List[str]:
    """Extract all tags from frontmatter."""
    tags = []
    # Multiline YAML list format
    tags_match = re.search(r'^tags:\s*\n((?:\s*-\s*.+\n)+)', frontmatter, re.MULTILINE)
    if tags_match:
        for line in tags_match.group(1).strip().split('\n'):
            tag = line.strip().lstrip('- ').strip().strip("'\"")
            if tag:
                tags.append(tag)
    else:
        # Inline array format
        inline = re.search(r'^tags:\s*\[(.*?)\]', frontmatter, re.MULTILINE | re.DOTALL)
        if inline:
            for t in inline.group(1).split(','):
                tag = t.strip().strip("'\"")
                if tag:
                    tags.append(tag)
    return tags


def has_topic_tag(tags: List[str]) -> bool:
    """Check if tags list includes any topic/ tag."""
    return any(t.startswith('topic/') for t in tags)


def extract_body_text(content: str) -> str:
    """Extract clean body text for LLM analysis."""
    _, body = extract_frontmatter(content)
    # Remove code blocks
    body = re.sub(r'```[\s\S]*?```', '', body)
    body = re.sub(r'`[^`]+`', '', body)
    # Remove URLs
    body = re.sub(r'https?://\S+', '', body)
    # Remove image embeds
    body = re.sub(r'!\[\[.*?\]\]', '', body)
    body = re.sub(r'!\[.*?\]\(.*?\)', '', body)
    # Keep wikilink text
    body = re.sub(r'\[\[([^\]|]+)\|([^\]]+)\]\]', r'\2', body)
    body = re.sub(r'\[\[([^\]]+)\]\]', r'\1', body)
    # Remove HTML
    body = re.sub(r'<[^>]+>', '', body)
    # Remove markdown formatting
    body = re.sub(r'^#+\s*', '', body, flags=re.MULTILINE)
    body = re.sub(r'\*\*([^*]+)\*\*', r'\1', body)
    body = re.sub(r'\*([^*]+)\*', r'\1', body)
    # Collapse whitespace
    body = re.sub(r'\s+', ' ', body).strip()
    return body


def add_topic_tags(content: str, new_topics: List[str]) -> str:
    """Add topic/ tags to frontmatter, inserting before the closing ---."""
    if not content.startswith('---'):
        return content

    # Find the closing --- of frontmatter
    end_match = re.search(r'\n(---\s*\n)', content[3:])
    if not end_match:
        return content

    # Position of the closing --- in the full content
    close_pos = end_match.start(1) + 3

    # Check existing topics to avoid duplicates
    frontmatter = content[:close_pos]
    existing = set(re.findall(r'topic/[\w-]+', frontmatter))
    new = [t for t in new_topics if t.replace('topic/', '') not in
           {e.replace('topic/', '') for e in existing}]

    if not new:
        return content

    # Insert new tags just before the closing ---
    insertion = ''.join(f'  - {t}\n' for t in new)
    return content[:close_pos] + insertion + content[close_pos:]


def build_batch_prompt(notes: List[Dict]) -> str:
    """Build the LLM prompt for a batch of notes."""
    notes_text = []
    for i, note in enumerate(notes):
        title = Path(note['path']).stem
        folder = str(Path(note['path']).parent)
        existing = ', '.join(note['tags']) if note['tags'] else '(none)'
        body = note['body'][:MAX_CONTENT_CHARS]
        if len(note['body']) > MAX_CONTENT_CHARS:
            body += '...'

        notes_text.append(f"""### Note {i+1}
**Path:** {note['path']}
**Title:** {title}
**Folder:** {folder}
**Existing tags:** {existing}
**Content:**
{body}
""")

    return f"""You are a knowledge management assistant for a professional vault about infrastructure, PPPs, risk management, and engineering advisory.

Given the topic taxonomy below, suggest 1-3 topic/ tags for each note. Pick ONLY from this taxonomy:

{TOPIC_TAXONOMY}

---

{chr(10).join(notes_text)}

---

For each note, respond in this JSON format (no markdown fencing):
[
  {{
    "note_index": 1,
    "topics": ["topic/ppp", "topic/risk"],
    "confidence": "high",
    "reasoning": "Brief explanation"
  }},
  ...
]

Rules:
- Pick 1-3 tags from the taxonomy ONLY. Never invent new tags.
- Use "high" confidence when the note clearly fits the topic.
- Use "medium" when the fit is reasonable but the note is short or ambiguous.
- Use "low" when you're guessing — prefer omitting tags over low-confidence ones.
- If the note has NO relation to any topic in the taxonomy, return an empty topics array.
- Consider the folder path as context (e.g., "Domain Knowledge/PPPs" suggests PPP topics).
"""


def parse_llm_response(response_text: str) -> List[Dict]:
    """Parse LLM JSON response."""
    # Strip markdown code fencing if present
    text = response_text.strip()
    if text.startswith('```'):
        text = re.sub(r'^```\w*\n', '', text)
        text = re.sub(r'\n```$', '', text)
        text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON array in the response
        match = re.search(r'\[[\s\S]*\]', text)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    return []


# Valid topic tags for validation
VALID_TOPICS = {
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
}


def process_batch(client: OpenAI, notes: List[Dict]) -> List[Dict]:
    """Send a batch of notes to the LLM and parse results."""
    prompt = build_batch_prompt(notes)

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=2000,
        )
        result_text = response.choices[0].message.content
        parsed = parse_llm_response(result_text)

        # Validate and filter tags
        validated = []
        for item in parsed:
            valid_topics = [t for t in item.get('topics', []) if t in VALID_TOPICS]
            item['topics'] = valid_topics
            validated.append(item)

        return validated

    except Exception as e:
        print(f"  API error: {e}")
        return []


def main():
    parser = argparse.ArgumentParser(
        description="LLM-assisted topic/ tag suggestion for Obsidian notes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run on entire vault (preview suggestions)
  python suggest_tags.py

  # Process a specific subfolder
  python suggest_tags.py --subfolder "3.RECURSOS/Domain Knowledge/PPPs"

  # Test with a small batch
  python suggest_tags.py --limit 5

  # Apply suggestions to notes
  python suggest_tags.py --no-dry-run

  # Only apply high-confidence suggestions
  python suggest_tags.py --no-dry-run --min-confidence high
        """
    )
    parser.add_argument(
        '--vault', default='/Users/jose/obsidian/JC',
        help='Path to Obsidian vault'
    )
    parser.add_argument(
        '--subfolder', default=None,
        help='Process only a specific subfolder (relative path)'
    )
    parser.add_argument(
        '--no-dry-run', action='store_true',
        help='Apply changes (default is dry-run mode)'
    )
    parser.add_argument(
        '--limit', type=int, default=None,
        help='Limit number of notes to process'
    )
    parser.add_argument(
        '--min-confidence', choices=['high', 'medium', 'low'], default='medium',
        help='Minimum confidence to apply (default: medium)'
    )
    parser.add_argument(
        '--verbose', '-v', action='store_true',
        help='Show detailed progress'
    )
    parser.add_argument(
        '--report', default=None,
        help='Save TSV report to file path'
    )

    args = parser.parse_args()

    # Validate vault
    valid, error = validate_vault_path(args.vault)
    if not valid:
        print(f"Error: {error}")
        sys.exit(1)

    vault_path = Path(args.vault)

    # Load API key
    env_path = Path(__file__).parent / '.env'
    if env_path.exists():
        load_dotenv(env_path)

    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        print("Error: OPENAI_API_KEY not found in .env file")
        sys.exit(1)

    client = OpenAI(api_key=api_key)

    # Confidence ordering for filtering
    confidence_levels = {'high': 3, 'medium': 2, 'low': 1}
    min_conf_level = confidence_levels[args.min_confidence]

    # Header
    dry_label = "DRY RUN" if not args.no_dry_run else "LIVE RUN"
    print(f"Topic Tag Suggester for Obsidian")
    print(f"Vault: {vault_path}")
    print(f"Model: {OPENAI_MODEL}")
    print(f"Mode: {dry_label}")
    print(f"Min confidence: {args.min_confidence}")
    if args.subfolder:
        print(f"Subfolder: {args.subfolder}")
    if args.limit:
        print(f"Limit: {args.limit}")
    print("=" * 60)

    # Discover notes
    if args.subfolder:
        scan_path = vault_path / args.subfolder
        if not scan_path.exists():
            print(f"Error: Subfolder does not exist: {args.subfolder}")
            sys.exit(1)
        all_notes = list(scan_path.rglob("*.md"))
        all_notes = [n for n in all_notes if not any(p.startswith('.') for p in n.parts)]
    else:
        all_notes = get_all_notes(vault_path)

    # Filter: notes missing topic/ tags
    candidates = []
    for note_path in all_notes:
        rel = str(note_path.relative_to(vault_path))

        # Skip excluded prefixes
        if any(rel.startswith(p) for p in SKIP_PREFIXES):
            continue

        try:
            content = note_path.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            continue

        frontmatter, body = extract_frontmatter(content)
        if frontmatter is None:
            continue

        tags = get_tags(frontmatter)
        if has_topic_tag(tags):
            continue

        body_text = extract_body_text(content)
        if len(body_text) < 30:
            continue

        candidates.append({
            'path': rel,
            'full_path': note_path,
            'tags': tags,
            'body': body_text,
            'content': content,
        })

    if args.limit:
        candidates = candidates[:args.limit]

    print(f"\nFound {len(candidates)} notes missing topic/ tags")

    if not candidates:
        print("Nothing to do.")
        return

    # Process in batches
    all_suggestions: List[TagSuggestion] = []
    total_batches = (len(candidates) + BATCH_SIZE - 1) // BATCH_SIZE

    for batch_idx in range(0, len(candidates), BATCH_SIZE):
        batch = candidates[batch_idx:batch_idx + BATCH_SIZE]
        batch_num = batch_idx // BATCH_SIZE + 1
        print(f"\nBatch {batch_num}/{total_batches} ({len(batch)} notes)...")

        results = process_batch(client, batch)

        for item in results:
            idx = item.get('note_index', 0) - 1
            if 0 <= idx < len(batch):
                note = batch[idx]
                topics = item.get('topics', [])
                conf = item.get('confidence', 'low')
                reasoning = item.get('reasoning', '')

                if topics:
                    suggestion = TagSuggestion(
                        rel_path=note['path'],
                        current_tags=note['tags'],
                        suggested_topics=topics,
                        confidence=conf,
                        reasoning=reasoning,
                    )
                    all_suggestions.append(suggestion)

                    if args.verbose:
                        print(f"  {note['path']}: {', '.join(topics)} [{conf}]")

        # Rate limiting
        if batch_idx + BATCH_SIZE < len(candidates):
            time.sleep(0.5)

    # Filter by confidence
    accepted = [s for s in all_suggestions
                if confidence_levels.get(s.confidence, 0) >= min_conf_level]
    rejected = len(all_suggestions) - len(accepted)

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Notes processed:    {len(candidates)}")
    print(f"Suggestions made:   {len(all_suggestions)}")
    print(f"Accepted (>={args.min_confidence}): {len(accepted)}")
    if rejected:
        print(f"Rejected (low conf): {rejected}")

    # Print suggestions
    if accepted:
        print(f"\n{'=' * 60}")
        print("SUGGESTIONS")
        print("=" * 60)
        for s in accepted:
            flag = "[DRY RUN] " if not args.no_dry_run else ""
            print(f"\n{flag}{s.rel_path}")
            print(f"  + {', '.join(s.suggested_topics)}  [{s.confidence}]")
            if s.reasoning:
                print(f"  Reason: {s.reasoning}")

    # Apply changes
    if args.no_dry_run and accepted:
        applied = 0
        for s in accepted:
            note_path = vault_path / s.rel_path
            try:
                content = note_path.read_text(encoding='utf-8', errors='ignore')
                updated = add_topic_tags(content, s.suggested_topics)
                if updated != content:
                    note_path.write_text(updated, encoding='utf-8')
                    applied += 1
            except Exception as e:
                print(f"  Error writing {s.rel_path}: {e}")

        print(f"\nApplied tags to {applied} notes.")
    elif not args.no_dry_run and accepted:
        print(f"\nThis was a DRY RUN. Use --no-dry-run to apply changes.")

    # Save report
    if args.report and accepted:
        with open(args.report, 'w') as f:
            f.write("Path\tCurrent Tags\tSuggested Topics\tConfidence\tReasoning\n")
            for s in accepted:
                current = '; '.join(s.current_tags)
                suggested = '; '.join(s.suggested_topics)
                f.write(f"{s.rel_path}\t{current}\t{suggested}\t{s.confidence}\t{s.reasoning}\n")
        print(f"Report saved to: {args.report}")


if __name__ == '__main__':
    main()
