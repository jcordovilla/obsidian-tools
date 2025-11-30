#!/usr/bin/env python3
"""
ChatGPT Conversation Enrichment and Cleanup Tool

Uses OpenAI GPT-4o-mini to:
1. Perform stringent quality analysis and cleanup
2. Add semantic topic tags
3. Extract frameworks and methodologies
4. Mine valuable questions for content ideas
5. Analyze writing style patterns

Usage:
    python chatgpt_enrichment.py --vault /path/to/vault analyze          # Analyze with LLM
    python chatgpt_enrichment.py --vault /path/to/vault tag              # Add topic tags
    python chatgpt_enrichment.py --vault /path/to/vault extract          # Extract frameworks
    python chatgpt_enrichment.py --vault /path/to/vault mine-questions   # Mine questions
    python chatgpt_enrichment.py --vault /path/to/vault cleanup          # Archive low-value

Prerequisites:
    - OpenAI API key in .env file: OPENAI_API_KEY=sk-...
    - pip install openai python-dotenv
"""

import argparse
import json
import re
import sys
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from shutil import move

try:
    from openai import OpenAI
    from dotenv import load_dotenv
except ImportError:
    print("❌ Missing dependencies. Install with: pip install openai python-dotenv")
    sys.exit(1)

# ============================================================================
# CONFIGURATION
# ============================================================================

# Load environment variables
load_dotenv()

CHATGPT_FOLDER = "3.RECURSOS/AI & ML/ChatGPT Conversations"
ARCHIVE_FOLDER = "4.ARCHIVO/ChatGPT Conversations (Low Value)"

# OpenAI model configuration
OPENAI_MODEL = "gpt-5-mini-2025-08-07"

# Initialize OpenAI client
openai_client = None
try:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("❌ OPENAI_API_KEY not found in .env file")
        sys.exit(1)
    openai_client = OpenAI(api_key=api_key)
except Exception as e:
    print(f"❌ Error initializing OpenAI client: {e}")
    sys.exit(1)

# Topic taxonomy from vault (will be auto-discovered)
TOPIC_KEYWORDS = {
    'ppp': ['ppp', 'p3', 'public-private partnership', 'concession', 'project finance'],
    'infrastructure': ['infrastructure', 'road', 'railway', 'bridge', 'transport', 'highway'],
    'resilience': ['resilience', 'climate', 'adaptation', 'risk', 'disaster'],
    'digital': ['digital twin', 'bim', 'ai', 'automation', 'technology'],
    'finance': ['finance', 'investment', 'funding', 'revenue', 'toll'],
    'consulting': ['consulting', 'advisory', 'feasibility', 'due diligence', 'analysis'],
    'rram': ['rram', 'road asset', 'maintenance', 'pavement'],
    'python': ['python', 'code', 'script', 'programming'],
    'obsidian': ['obsidian', 'note', 'pkm', 'knowledge management'],
}

# ============================================================================
# DATA MODELS
# ============================================================================

@dataclass
class ChatAnalysis:
    """Results from LLM analysis of a chat."""
    quality_score: float  # 0-100
    is_valuable: bool
    primary_topics: List[str]
    reasoning: str
    has_framework: bool
    framework_description: Optional[str]
    key_questions: List[str]
    suggested_action: str  # 'keep', 'archive', 'review'


@dataclass
class ConversationFile:
    """Represents a ChatGPT conversation file."""
    path: Path
    frontmatter: Dict
    title: str
    messages: List[Dict]
    create_time: str
    source: str
    tags: List[str]


# ============================================================================
# FILE PARSING
# ============================================================================

def extract_frontmatter(content: str) -> Tuple[Dict, str]:
    """Extract YAML frontmatter and remaining content."""
    if not content.startswith('---'):
        return {}, content

    end = content.find('\n---\n', 3)
    if end == -1:
        return {}, content

    fm_content = content[3:end].strip()
    remaining = content[end + 5:]

    frontmatter = {}
    for line in fm_content.split('\n'):
        if ':' in line:
            key, value = line.split(':', 1)
            key = key.strip()
            value = value.strip()

            # Parse tags list
            if key == 'tags' and value.startswith('['):
                value = [t.strip() for t in value.strip('[]').split(',')]

            frontmatter[key] = value

    return frontmatter, remaining


def extract_messages(content: str) -> List[Dict]:
    """Extract user and assistant messages from markdown."""
    messages = []

    # User messages: ### User, on ...
    user_pattern = r'###\s+User,\s+on\s+([^;]+);?\s*\n>\s*(.+?)(?=\n###|\n####|\n<details>|\n---|\Z)'
    for match in re.finditer(user_pattern, content, re.DOTALL):
        messages.append({
            'role': 'user',
            'content': match.group(2).strip(),
            'timestamp': match.group(1).strip()
        })

    # Assistant messages: #### ChatGPT, on ...
    assistant_pattern = r'####\s+ChatGPT,\s+on\s+([^;]+);?\s*\n>>\s*(.+?)(?=\n###|\n####|\n<details>|\n---|\Z)'
    for match in re.finditer(assistant_pattern, content, re.DOTALL):
        messages.append({
            'role': 'assistant',
            'content': match.group(2).strip(),
            'timestamp': match.group(1).strip()
        })

    return messages


def parse_conversation_file(file_path: Path) -> Optional[ConversationFile]:
    """Parse a ChatGPT conversation markdown file."""
    try:
        content = file_path.read_text(encoding='utf-8')
        frontmatter, remaining = extract_frontmatter(content)

        # Extract title
        title_match = re.search(r'^#\s+(.+)$', remaining, re.MULTILINE)
        title = title_match.group(1).strip() if title_match else file_path.stem

        # Extract messages
        messages = extract_messages(remaining)

        return ConversationFile(
            path=file_path,
            frontmatter=frontmatter,
            title=title,
            messages=messages,
            create_time=frontmatter.get('create_time', ''),
            source=frontmatter.get('source', 'unknown'),
            tags=frontmatter.get('tags', [])
        )
    except Exception as e:
        print(f"  ❌ Error parsing {file_path.name}: {e}")
        return None


# ============================================================================
# OPENAI LLM INTERFACE
# ============================================================================

def call_openai(prompt: str, system_prompt: Optional[str] = None) -> str:
    """Call OpenAI API with a prompt and return response."""
    try:
        messages = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        messages.append({"role": "user", "content": prompt})

        response = openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            max_completion_tokens=1000
        )

        return response.choices[0].message.content.strip()

    except Exception as e:
        return f"ERROR: {str(e)}"


def analyze_chat_quality(conv: ConversationFile) -> ChatAnalysis:
    """Use LLM to analyze chat quality and extract insights."""

    # Build context for LLM
    user_messages = [m for m in conv.messages if m['role'] == 'user']
    assistant_messages = [m for m in conv.messages if m['role'] == 'assistant']

    # Sample messages (first 3 user, first 3 assistant to avoid token limits)
    sample_user = '\n'.join([m['content'][:500] for m in user_messages[:3]])
    sample_assistant = '\n'.join([m['content'][:500] for m in assistant_messages[:3]])

    system_prompt = """You are a strict evaluator of ChatGPT conversations for PROFESSIONAL knowledge value.

VALUABLE conversations (score 70+, keep):
- Work-related problem solving and analysis
- Professional skill development (programming, consulting, technical)
- Reusable frameworks, methodologies, or approaches developed
- Deep multi-turn exploration of complex professional topics
- Learning that advances career or expertise

LOW-VALUE conversations (score <40, archive):
- Personal queries (vacation planning, shopping, entertainment, cooking)
- Simple factual lookups without depth ("what is X?")
- One-off questions with no follow-up exploration
- Social/creative content (songs, jokes, personal stories)
- General interest topics unrelated to professional development

MEDIUM conversations (40-69, review):
- Borderline professional value
- Short but potentially useful technical queries
- Personal topics that might inform professional work

A "framework" is a systematic methodology or approach developed in the conversation, NOT:
- Existing tools mentioned (like DALL-E, ChatGPT)
- General concepts explained
- Simple lists or recommendations

Be STRICT: Personal interest ≠ Professional value. Score conservatively.

Respond in JSON format only."""

    prompt = f"""Analyze this ChatGPT conversation and return a JSON object with:
- quality_score: number 0-100 (higher = more valuable)
- is_valuable: boolean (should it be kept?)
- primary_topics: list of 1-3 main topics (e.g., ["ppp", "infrastructure"])
- reasoning: brief explanation (1-2 sentences)
- has_framework: boolean (does it develop a methodology/framework?)
- framework_description: string or null (if has_framework, describe it)
- key_questions: list of interesting questions asked (max 3)
- suggested_action: "keep", "archive", or "review"

Title: {conv.title}
Source: {conv.source}
Number of exchanges: {len(user_messages)}
Current tags: {conv.tags}

Sample user messages:
{sample_user}

Sample assistant responses:
{sample_assistant}

Return only valid JSON, no markdown code blocks."""

    response = call_openai(prompt, system_prompt)

    # Parse JSON response
    try:
        # Remove markdown code blocks if present
        response = response.replace('```json', '').replace('```', '').strip()

        # Extract JSON object (find first { and matching })
        start = response.find('{')
        if start == -1:
            raise json.JSONDecodeError("No JSON object found", response, 0)

        # Find matching closing brace
        brace_count = 0
        end = start
        for i, char in enumerate(response[start:], start):
            if char == '{':
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0:
                    end = i + 1
                    break

        json_str = response[start:end]
        data = json.loads(json_str)

        return ChatAnalysis(
            quality_score=float(data.get('quality_score', 50)),
            is_valuable=bool(data.get('is_valuable', True)),
            primary_topics=data.get('primary_topics', []),
            reasoning=data.get('reasoning', ''),
            has_framework=bool(data.get('has_framework', False)),
            framework_description=data.get('framework_description'),
            key_questions=data.get('key_questions', []),
            suggested_action=data.get('suggested_action', 'keep')
        )
    except json.JSONDecodeError as e:
        print(f"  ⚠️  JSON parse error: {e}")
        print(f"  Response was: {response[:200]}")
        # Return conservative default
        return ChatAnalysis(
            quality_score=50,
            is_valuable=True,
            primary_topics=[],
            reasoning="Error parsing LLM response",
            has_framework=False,
            framework_description=None,
            key_questions=[],
            suggested_action='review'
        )


# ============================================================================
# ANALYSIS MODES
# ============================================================================

def analyze_conversations(vault_path: Path, dry_run: bool = True, limit: Optional[int] = None):
    """Deep analysis of conversations with LLM."""
    chatgpt_path = vault_path / CHATGPT_FOLDER

    if not chatgpt_path.exists():
        print(f"❌ ChatGPT folder not found: {chatgpt_path}")
        return

    # Find all conversations
    all_convs = sorted(chatgpt_path.glob('**/*.md'))

    if limit:
        all_convs = all_convs[:limit]

    print(f"Analyzing {len(all_convs)} conversations with model: {OPENAI_MODEL}")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print("="*80)

    results = []

    for i, conv_path in enumerate(all_convs, 1):
        print(f"\n[{i}/{len(all_convs)}] {conv_path.name}")

        conv = parse_conversation_file(conv_path)
        if not conv:
            continue

        # Analyze with LLM
        analysis = analyze_chat_quality(conv)

        print(f"  Score: {analysis.quality_score:.0f}/100")
        print(f"  Action: {analysis.suggested_action}")
        print(f"  Topics: {', '.join(analysis.primary_topics)}")
        print(f"  Framework: {'Yes - ' + analysis.framework_description[:50] + '...' if analysis.has_framework else 'No'}")
        print(f"  Reasoning: {analysis.reasoning[:100]}")

        results.append({
            'path': str(conv_path),
            'title': conv.title,
            'analysis': analysis
        })

    # Generate report
    report_path = vault_path.parent / 'chatgpt_analysis_report.json'
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, default=lambda x: x.__dict__)

    print(f"\n{'='*80}")
    print(f"Analysis complete!")
    print(f"Report saved to: {report_path}")
    print(f"{'='*80}")

    # Summary statistics
    to_keep = sum(1 for r in results if r['analysis'].suggested_action == 'keep')
    to_archive = sum(1 for r in results if r['analysis'].suggested_action == 'archive')
    to_review = sum(1 for r in results if r['analysis'].suggested_action == 'review')
    has_framework = sum(1 for r in results if r['analysis'].has_framework)

    print(f"\nSummary:")
    print(f"  Keep: {to_keep}")
    print(f"  Archive: {to_archive}")
    print(f"  Review: {to_review}")
    print(f"  Has framework: {has_framework}")


def add_topic_tags(vault_path: Path, dry_run: bool = True):
    """Add semantic topic tags to conversations based on content analysis."""
    # This would analyze content and add topic tags
    # For now, placeholder
    print("Topic tagging not yet implemented")
    print("Will analyze content and add tags like: topic/ppp, topic/infrastructure, etc.")


def extract_frameworks(vault_path: Path, dry_run: bool = True):
    """Extract frameworks and methodologies from conversations."""
    print("Framework extraction not yet implemented")
    print("Will identify conversations with frameworks and create distilled notes")


def mine_questions(vault_path: Path, dry_run: bool = True):
    """Mine valuable questions for content ideas."""
    print("Question mining not yet implemented")
    print("Will extract user questions and identify patterns for content creation")


def cleanup_conversations(vault_path: Path, threshold: float = 40.0, dry_run: bool = True):
    """Archive low-value conversations based on LLM analysis."""
    # Load analysis report
    report_path = vault_path.parent / 'chatgpt_analysis_report.json'

    if not report_path.exists():
        print(f"❌ No analysis report found. Run 'analyze' first.")
        return

    with open(report_path, 'r') as f:
        results = json.load(f)

    archive_base = vault_path / ARCHIVE_FOLDER

    to_archive = [r for r in results if r['analysis']['suggested_action'] == 'archive']

    print(f"Found {len(to_archive)} conversations to archive")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print("="*80)

    archived = 0

    for result in to_archive:
        source_path = Path(result['path'])

        if not source_path.exists():
            continue

        # Maintain folder structure
        rel_path = source_path.relative_to(vault_path / CHATGPT_FOLDER)
        dest_path = archive_base / rel_path

        if dry_run:
            print(f"  Would archive: {source_path.name}")
        else:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            move(str(source_path), str(dest_path))
            print(f"  ✓ Archived: {source_path.name}")

        archived += 1

    print(f"\n{'='*80}")
    print(f"{'Would archive' if dry_run else 'Archived'}: {archived} conversations")
    print(f"{'='*80}")


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='ChatGPT Conversation Enrichment and Cleanup',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument('--vault', type=Path, required=True,
                       help='Path to Obsidian vault')

    parser.add_argument('command', choices=['analyze', 'tag', 'extract', 'mine-questions', 'cleanup'],
                       help='Command to run')

    parser.add_argument('--no-dry-run', action='store_true',
                       help='Actually perform actions (default is dry-run)')

    parser.add_argument('--limit', type=int,
                       help='Limit number of files to process (for testing)')

    parser.add_argument('--threshold', type=float, default=40.0,
                       help='Quality threshold for cleanup (default: 40.0)')

    args = parser.parse_args()

    vault_path = args.vault.resolve()
    dry_run = not args.no_dry_run

    if not vault_path.exists():
        print(f"❌ Vault not found: {vault_path}")
        sys.exit(1)

    print(f"ChatGPT Conversation Enrichment")
    print(f"Vault: {vault_path}")
    print(f"Command: {args.command}")
    print(f"Model: {OPENAI_MODEL}")
    print("="*80)
    print()

    if args.command == 'analyze':
        analyze_conversations(vault_path, dry_run, args.limit)
    elif args.command == 'tag':
        add_topic_tags(vault_path, dry_run)
    elif args.command == 'extract':
        extract_frameworks(vault_path, dry_run)
    elif args.command == 'mine-questions':
        mine_questions(vault_path, dry_run)
    elif args.command == 'cleanup':
        cleanup_conversations(vault_path, args.threshold, dry_run)


if __name__ == '__main__':
    main()
