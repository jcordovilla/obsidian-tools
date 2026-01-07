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
import time
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

# Model configuration
OPENAI_MODEL = "gpt-5-mini-2025-08-07"
OLLAMA_MODEL = "deepseek-r1:32b"

# Initialize OpenAI client (only if using OpenAI)
openai_client = None

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
    input_tokens: int = 0
    output_tokens: int = 0
    processing_time: float = 0.0


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
# LLM INTERFACE
# ============================================================================

def call_ollama(prompt: str, system_prompt: Optional[str] = None) -> Tuple[str, int, int]:
    """Call Ollama with a prompt and return response with estimated token counts.

    Returns:
        Tuple of (response_text, estimated_input_tokens, estimated_output_tokens)
    """
    try:
        import subprocess

        # Call ollama via subprocess
        result = subprocess.run(
            ['ollama', 'run', OLLAMA_MODEL],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=120
        )

        if result.returncode != 0:
            return f"ERROR: Ollama error: {result.stderr}", 0, 0

        response = result.stdout.strip()

        # Estimate tokens (rough: ~4 chars per token)
        est_input_tokens = len(prompt) // 4
        est_output_tokens = len(response) // 4

        return response, est_input_tokens, est_output_tokens

    except subprocess.TimeoutExpired:
        return "ERROR: Ollama timeout", 0, 0
    except Exception as e:
        return f"ERROR: {str(e)}", 0, 0


def call_openai(prompt: str, system_prompt: Optional[str] = None) -> Tuple[str, int, int]:
    """Call OpenAI API with a prompt and return response with token counts.

    Returns:
        Tuple of (response_text, input_tokens, output_tokens)
    """
    try:
        messages = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        messages.append({"role": "user", "content": prompt})

        response = openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            max_completion_tokens=2000
        )

        response_text = response.choices[0].message.content.strip()
        input_tokens = response.usage.prompt_tokens
        output_tokens = response.usage.completion_tokens

        return response_text, input_tokens, output_tokens

    except Exception as e:
        return f"ERROR: {str(e)}", 0, 0


def analyze_chat_quality(conv: ConversationFile, provider: str = 'openai') -> ChatAnalysis:
    """Use LLM to analyze chat quality and extract insights.

    Args:
        conv: Conversation file to analyze
        provider: 'openai' or 'ollama'
    """
    start_time = time.time()

    # Build context for LLM
    user_messages = [m for m in conv.messages if m['role'] == 'user']
    assistant_messages = [m for m in conv.messages if m['role'] == 'assistant']

    # Sampling strategy based on 90th percentile coverage (45,520 chars total)
    # Average assistant message: 2,519 chars, so sample ~3000 to capture most fully
    if len(user_messages) <= 2:
        # Single-turn: capture up to 10,000 chars to get full responses
        sample_user = '\n'.join([m['content'][:10000] for m in user_messages])
        sample_assistant = '\n'.join([m['content'][:10000] for m in assistant_messages])
    else:
        # Multi-turn: sample first 5 messages with 3000 chars each
        sample_user = '\n'.join([m['content'][:3000] for m in user_messages[:5]])
        sample_assistant = '\n'.join([m['content'][:3000] for m in assistant_messages[:5]])

    system_prompt = """You are a strict evaluator of ChatGPT conversations for PROFESSIONAL knowledge value.

CORE PRINCIPLE: Keep conversations that contain distilled knowledge or raw material to generate knowledge. Archive outdated, shallow, or easily web-searchable information.

VALUABLE conversations (score 70+, keep):
- Professional-level conceptual explanations: Explains WHY/HOW with specific mechanisms, trade-offs, or professional insights (not general/consumer-level)
- Distilled knowledge: Multiple specific points/principles with professional reuse value (like "5 reasons why X works")
- Raw material for knowledge distillation: Deep multi-turn explorations worth synthesizing
- Unique professional problem-solving not easily replicated via web search
- Developed methodologies or systematic approaches (true frameworks)
- Technical skill development with substantive depth and specificity

CRITICALLY PENALIZE (score <30, archive):
- Outdated information (pre-2023 technology/tools/data that's been surpassed)
- Failed conversations: assistant says "knowledge cutoff prevents me from answering"
- Truncated/incomplete responses: good question but weak/partial answer with no real insights
- One-off calculations or data lookups without reusable methodology
- Consumer-level Q&A: General discussions about AI/technology without professional depth ("will AI replace humans?")
- WHAT IS questions: Basic definitions easily found via web search
- Single-turn shallow Q&A without substantive content
- Personal queries (vacation, entertainment, shopping, cooking, gardening)
- Social/creative content (songs, jokes, stories)

BORDERLINE (40-60, review):
- Professional topics but too brief/shallow to extract knowledge
- Potentially useful but incomplete or truncated responses
- Basic professional queries that lack depth

KEY DISTINCTIONS:
- Professional-level WHY/HOW with multiple specific points (green financing advantages with 5 reasons) → KEEP even if single-turn
- Consumer-level general Q&A (will AI replace humans?) → ARCHIVE
- Factual WHAT (definitions, lists) → ARCHIVE
- Good question + complete substantive answer → KEEP
- Good question + truncated/weak/outdated answer → ARCHIVE
- Reusable professional CONCEPTS → KEEP
- One-off CALCULATIONS → ARCHIVE
- True FRAMEWORKS (systematic methodology) vs simple lists → Only systematic methodologies count

Be STRICT and DECISIVE: Err toward archiving. Score <40 if easily replaceable. Score 70+ for conceptual/distillable knowledge even if brief.

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

    # Call appropriate LLM
    if provider == 'ollama':
        response, input_tokens, output_tokens = call_ollama(prompt, system_prompt)
    else:
        response, input_tokens, output_tokens = call_openai(prompt, system_prompt)

    processing_time = time.time() - start_time

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
            suggested_action=data.get('suggested_action', 'keep'),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            processing_time=processing_time
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
            suggested_action='review',
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            processing_time=processing_time
        )


# ============================================================================
# ANALYSIS MODES
# ============================================================================

def analyze_conversations(vault_path: Path, provider: str = 'openai', dry_run: bool = True, limit: Optional[int] = None):
    """Deep analysis of conversations with LLM.

    Args:
        vault_path: Path to Obsidian vault
        provider: 'openai' or 'ollama'
        dry_run: If True, don't modify files
        limit: Max number of conversations to analyze
    """
    chatgpt_path = vault_path / CHATGPT_FOLDER

    if not chatgpt_path.exists():
        print(f"❌ ChatGPT folder not found: {chatgpt_path}")
        return

    # Initialize OpenAI client if needed
    global openai_client
    if provider == 'openai' and openai_client is None:
        try:
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                print("❌ OPENAI_API_KEY not found in .env file")
                sys.exit(1)
            openai_client = OpenAI(api_key=api_key)
        except Exception as e:
            print(f"❌ Error initializing OpenAI client: {e}")
            sys.exit(1)

    # Find all conversations
    all_convs = sorted(chatgpt_path.glob('**/*.md'))

    if limit:
        all_convs = all_convs[:limit]

    model_name = OPENAI_MODEL if provider == 'openai' else OLLAMA_MODEL
    print(f"Analyzing {len(all_convs)} conversations with {provider}: {model_name}")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print("="*80)

    results = []
    total_time = 0.0
    total_input_tokens = 0
    total_output_tokens = 0

    for i, conv_path in enumerate(all_convs, 1):
        print(f"\n[{i}/{len(all_convs)}] {conv_path.name}")

        conv = parse_conversation_file(conv_path)
        if not conv:
            continue

        # Analyze with LLM
        analysis = analyze_chat_quality(conv, provider)

        # Track totals
        total_time += analysis.processing_time
        total_input_tokens += analysis.input_tokens
        total_output_tokens += analysis.output_tokens

        print(f"  Score: {analysis.quality_score:.0f}/100")
        print(f"  Action: {analysis.suggested_action}")
        print(f"  Topics: {', '.join(analysis.primary_topics)}")
        print(f"  Framework: {'Yes - ' + analysis.framework_description[:50] + '...' if analysis.has_framework else 'No'}")
        print(f"  Reasoning: {analysis.reasoning[:100]}")
        print(f"  Tokens: {analysis.input_tokens} in + {analysis.output_tokens} out | Time: {analysis.processing_time:.1f}s")

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

    # Token and cost statistics
    total_tokens = total_input_tokens + total_output_tokens
    avg_time_per_conv = total_time / len(results) if results else 0

    # OpenAI pricing for gpt-4o-mini (as of 2024): $0.150/1M input, $0.600/1M output
    input_cost = (total_input_tokens / 1_000_000) * 0.150
    output_cost = (total_output_tokens / 1_000_000) * 0.600
    total_cost = input_cost + output_cost

    print(f"\nToken Usage:")
    print(f"  Input tokens: {total_input_tokens:,}")
    print(f"  Output tokens: {total_output_tokens:,}")
    print(f"  Total tokens: {total_tokens:,}")
    print(f"  Cost: ${total_cost:.4f}")

    print(f"\nTiming:")
    print(f"  Total time: {total_time:.1f}s ({total_time/60:.1f} min)")
    print(f"  Average per conversation: {avg_time_per_conv:.1f}s")

    # Estimate for full batch
    if limit:
        total_convs = len(list(chatgpt_path.glob('**/*.md')))
        est_total_tokens = int((total_tokens / len(results)) * total_convs)
        est_total_cost = (total_cost / len(results)) * total_convs
        est_total_time = (total_time / len(results)) * total_convs

        print(f"\n{'='*80}")
        print(f"ESTIMATE FOR ALL {total_convs} CONVERSATIONS:")
        print(f"  Total tokens: ~{est_total_tokens:,}")
        print(f"  Total cost: ~${est_total_cost:.2f}")
        print(f"  Total time: ~{est_total_time/60:.0f} min ({est_total_time/3600:.1f} hours)")
        print(f"{'='*80}")


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


def update_frontmatter(vault_path: Path, dry_run: bool = True):
    """Update file frontmatter with analysis metadata."""
    import re

    # Load analysis report
    report_path = vault_path.parent / 'chatgpt_analysis_report.json'

    if not report_path.exists():
        print(f"❌ No analysis report found. Run 'analyze' first.")
        return

    with open(report_path, 'r') as f:
        results = json.load(f)

    print(f"Updating frontmatter for {len(results)} conversations")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print("="*80)

    updated = 0
    for result in results:
        file_path = Path(result['path'])

        if not file_path.exists():
            continue

        analysis = result['analysis']

        # Read current file
        content = file_path.read_text(encoding='utf-8')

        # Extract existing frontmatter
        if not content.startswith('---'):
            print(f"  ⚠️  Skipping {file_path.name} (no frontmatter)")
            continue

        end = content.find('\n---\n', 3)
        if end == -1:
            print(f"  ⚠️  Skipping {file_path.name} (malformed frontmatter)")
            continue

        frontmatter = content[3:end]
        remaining = content[end + 5:]

        # Remove existing analysis section if present
        frontmatter_lines = frontmatter.split('\n')
        new_lines = []
        skip_analysis = False

        for line in frontmatter_lines:
            if line.strip() == 'analysis:':
                skip_analysis = True
                continue
            if skip_analysis and line and not line[0].isspace():
                skip_analysis = False
            if not skip_analysis:
                new_lines.append(line)

        # Build analysis section
        analysis_yaml = f"""analysis:
  quality_score: {analysis['quality_score']}
  action: {analysis['suggested_action']}
  topics: [{', '.join(analysis['primary_topics'])}]
  has_framework: {str(analysis['has_framework']).lower()}
  framework_description: {analysis['framework_description'] if analysis['framework_description'] else 'null'}"""

        if analysis.get('key_questions'):
            analysis_yaml += "\n  key_questions:"
            for q in analysis['key_questions']:
                # Escape quotes and format as YAML list
                q_escaped = q.replace('"', '\\"')
                analysis_yaml += f'\n    - "{q_escaped}"'

        if analysis.get('reasoning'):
            # Multi-line string in YAML
            reasoning = analysis['reasoning'].replace('\n', '\n    ')
            analysis_yaml += f"\n  reasoning: |\n    {reasoning}"

        analysis_yaml += f"\n  analyzed_date: {datetime.now().strftime('%Y-%m-%d')}"
        analysis_yaml += f"\n  analyzed_model: {OPENAI_MODEL if 'openai' in str(result.get('provider', 'openai')) else OLLAMA_MODEL}"

        # Rebuild frontmatter
        new_frontmatter = '\n'.join(new_lines).strip() + '\n' + analysis_yaml
        new_content = f"---\n{new_frontmatter}\n---\n{remaining}"

        if dry_run:
            print(f"  Would update: {file_path.name}")
        else:
            file_path.write_text(new_content, encoding='utf-8')
            print(f"  ✓ Updated: {file_path.name}")

        updated += 1

    print(f"\n{'='*80}")
    print(f"{'Would update' if dry_run else 'Updated'}: {updated} files")
    print(f"{'='*80}")


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

    parser.add_argument('command', choices=['analyze', 'update-frontmatter', 'tag', 'extract', 'mine-questions', 'cleanup'],
                       help='Command to run')

    parser.add_argument('--provider', choices=['openai', 'ollama'], default='openai',
                       help='LLM provider: openai or ollama (default: openai)')

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
    print(f"Provider: {args.provider}")
    print("="*80)
    print()

    if args.command == 'analyze':
        analyze_conversations(vault_path, args.provider, dry_run, args.limit)
    elif args.command == 'update-frontmatter':
        update_frontmatter(vault_path, dry_run)
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
