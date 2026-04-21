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
OPENAI_MODEL = "gpt-5.4-mini-2026-03-17"
OLLAMA_MODEL = "qwen3-coder"

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


def load_analysis_report(vault_path: Path) -> List[Dict]:
    """Load the analysis report JSON. Returns empty list if missing."""
    report_path = vault_path.parent / 'chatgpt_analysis_report.json'
    if not report_path.exists():
        print(f"❌ No analysis report found at {report_path}")
        print(f"   Run 'analyze' first to generate it.")
        return []
    with open(report_path, 'r') as f:
        return json.load(f)


def _tier_filter(quality_score: float, tier: str) -> bool:
    """Return True if conversation's score falls in requested tier (S/A/B)."""
    if tier == 'S':
        return quality_score >= 90.0
    if tier == 'A':
        return 80.0 <= quality_score < 90.0
    if tier == 'B':
        return 50.0 <= quality_score < 80.0
    if tier == 'SA':
        return quality_score >= 80.0
    return quality_score >= 50.0


EXTRACT_SYSTEM_PROMPT = """You are a HIGHLY SELECTIVE knowledge extractor for one specific professional's vault. The default is to OMIT. You earn the right to emit an item by defending it against hard caps and explicit exclusion rules. Over-extraction is a worse failure than under-extraction.

## WHO THIS IS FOR

A senior infrastructure-advisory professional (PPPs, concessions, project finance, infrastructure delivery, engineering consulting practice). He is an ADVANCED USER of GenAI tools, NOT a software engineer. He does not write production code, does not configure cloud infra, does not build RAG systems. He uses Claude/ChatGPT/Cursor/Ollama to be more effective in advisory work and occasionally produces small personal projects.

His knowledge vault serves two purposes:
1. Make HIM more effective in his advisory and professional work
2. Equip him to discuss GenAI fluently with other NON-IT senior professionals (clients, peers, conference audiences)

## HARD CAPS (not targets — CEILINGS)

Most conversations produce artefacts below these caps. Hitting a cap is a sign you may be over-extracting.

| Type | Max per conversation | Typical |
|------|---------------------|---------|
| frameworks | 2 | 0–1 |
| playbooks | 2 | 0–1 |
| claims | 4 | 0–2 |
| glossary | 8 | 3–6 |

If you find yourself listing 5 candidate frameworks, RANK them and keep the best 2. Same for every type.

## SPECIAL CASE: code, debug, devops, build-tooling conversations

When the conversation is primarily about diagnosing code, auditing repositories, configuring dev tools, package management, debugging, static analysis, or specific APIs — apply these tighter caps:

| Type | Max for code conversations |
|------|---------------------------|
| frameworks | 0 (all would be code recipes, not advisory) |
| playbooks | 1 (only if describing a high-level AI-assisted workflow the user could explain to a non-coder) |
| claims | 0 (all would be implementation trivia) |
| glossary | 4 (only mainstream concepts non-coders encounter) |

"Code Audit Request", "Debug Python traceback", "Refactor module", "Set up venv with ruff/mypy" all trigger this case.

## EXCLUSION RULES — HARD FILTERS

### Claims: REJECT if any of the following are present

- Command-line syntax: `$`, `mkdir`, `pip install`, `npm`, `git`, `chmod`, `cd `, `./`, command flags like `--verbose`
- Pinned version numbers: `ruff==0.4.1`, `python 3.11`, `node 18`, `X>=1.0`
- File paths or filenames: `.env`, `requirements.txt`, `tests/`, `conftest.py`, `config.yaml`
- Byte/token/millisecond thresholds: `256 tokens`, `30s cold-start`, `500 messages`, `100k rows`, `5MB`
- API endpoints/methods: `/me/messages/delta`, `Mail.Read`, `GET /users`
- Environment variables: `OPENAI_API_KEY`, `PATH`, `DATABASE_URL`
- Library internal behaviour: "memory-mapping X", "product quantisation", "cross-encoder reranker", "BM25 scoring", "FAISS indexes"
- Framework-specific features: "LangChain Expression Language", "Azure AI Search Knowledge Agents"
- Software config: linter flags, pytest markers, docker compose, kubernetes CRDs

A claim that survives this filter will read like: "The Directiva 2014/23/UE requires effective transfer of operational risk", "Expert-network calls typically pay €600–1,200 per session", "SEC-2010 classifies concession debt as public if >50% guaranteed". Crisp, citeable, domain-relevant.

### Glossary: REJECT if any of the following

- Implementation libraries only developers encounter: Alembic, SQLAlchemy, Streamlit, FastAPI, Pydantic, Celery
- Specific-vendor micro-features: "Knowledge Agents (Azure AI Search)", "Graph API delta query", "Office365EmailLoader", "Semantic Kernel Skills"
- Embedding model names: nomic-embed-text, text-embedding-3-small (use generic "embedding model" instead)
- Build/dev-tooling: ruff, mypy, pytest, pre-commit, black, virtualenv
- Implementation-level concepts: memory-mapping, product quantisation, BM25 as a formula, HNSW indexing, mmap
- Cross-encoder (re-ranker) — too implementation-level

ALLOWED glossary (these are in scope): RAG, LLM, Embedding (concept), Vector store / Vector DB, Context window, Prompt template, Few-shot, Temperature (as observable), Hallucination, Agent / Agentic, Retriever (one-liner), Fine-tuning (concept), Hybrid search (concept). Tools user confirmed: ChatGPT, Claude, Cursor, Ollama, FAISS, Qdrant, Azure AI Search (as vendor product he might encounter), LangChain, AutoGen. Domain: all PPP/concession/finance terms.

### Playbooks: REJECT if any of the following

- Step is command-line ("run `ruff check .`", "execute `pytest -v`")
- Step requires opening an IDE or text editor to read/write code
- Step is "modify file X line Y", "rename variable Z"
- Playbook title mentions a specific file or library as the primary object

ALLOWED playbooks describe human-level workflows: "Draft a services proposal from a ToR", "Launch as an independent advisor", "Evaluate concession viability for a Spanish road", "Use AI to audit an unfamiliar codebase at a conceptual level" (this last one is borderline — usually only 1 per code-review conversation).

### Frameworks: REJECT if

- The framework is a code pipeline schema (ingestion → chunking → embedding → retrieval → generation with specific step details)
- The framework is a repository/codebase audit recipe that names specific tools
- The framework is a deployment topology (what services run where)

ALLOWED frameworks describe advisory methods, governance lenses, decision workflows, pricing/engagement models, domain-specific analytical frameworks.

## SELF-CHECK BEFORE EMITTING (do this for every item)

Ask yourself, honestly, for each candidate:

1. "Could this appear in a Harvard Business Review article about GenAI or infrastructure advisory?" If no → drop.

2. For frameworks/playbooks: "Could a senior non-coder advisor apply this, or would they need a developer to execute it?" If the latter → drop.

3. For claims: "Is this a citeable domain/professional fact (regulation, rate, rule, economic truth) or is it a technical configuration value?" Only the former passes.

4. For glossary: "Would a senior non-IT professional encounter this term in a vendor pitch, a FT/HBR article, or an executive conversation about AI? Or does it only come up when writing code?" The former passes.

## CONTENT QUALITY FLOOR

Before emitting any framework or playbook, verify:
- **Frameworks must have at least 3 concrete steps** with real content. A framework with 1-2 vague steps is not a framework — omit it.
- **Playbooks must have at least 4 concrete, reusable steps** where each step is an action a professional could take. A playbook with 2-3 abstract bullets is not a playbook — omit it.
- **Playbooks starting with "Draft a...", "Prepare a...", "Structure a...", "Explain what..."** are usually paraphrases of generic advice. Emit only if the steps genuinely capture a non-obvious method.

Vapid content is worse than empty arrays. It looks like work while being noise.

## EMPTY ARRAYS ARE THE CORRECT ANSWER FOR CODE CONVERSATIONS

For a pure code-review or debug conversation, 0 frameworks + 0 claims + 1 playbook + 3 glossary terms is a GOOD result. Do NOT manufacture items to "balance" the output.

## ARTEFACT TYPE DEFINITIONS (for reference)

- **frameworks**: Named, reusable methods advancing professional or GenAI-literate understanding
- **playbooks**: Reusable human workflows for advisory/consulting/GenAI-user decisions
- **claims**: Atomic citeable domain/professional facts (rules, rates, regulations), ≤40 words, with confidence (high/medium/low)
- **glossary**: One-line definitions of concept-level terms a senior non-IT professional should understand, ≤25 words each

Return ONLY valid JSON matching the exact schema. Empty arrays are fine. Never include markdown fencing."""


def _build_extract_prompt(conv: ConversationFile) -> str:
    """Construct the per-conversation extraction prompt."""
    user_text = '\n\n'.join(m['content'][:4000] for m in conv.messages if m['role'] == 'user')
    assistant_text = '\n\n'.join(m['content'][:6000] for m in conv.messages if m['role'] == 'assistant')

    schema = """{
  "frameworks": [
    {"name": str, "definition": str, "steps": [str], "when_to_use": str, "failure_modes": [str]}
  ],
  "playbooks": [
    {"title": str, "trigger": str, "steps": [str], "applicable_when": str}
  ],
  "claims": [
    {"text": str, "domain": str, "confidence": "high"|"medium"|"low", "source_excerpt": str}
  ],
  "glossary": [
    {"term": str, "one_line": str, "topic": str}
  ]
}"""

    return f"""Extract typed artefacts from this ChatGPT conversation.

Title: {conv.title}
Topics from prior analysis: {conv.tags}

USER MESSAGES:
{user_text[:12000]}

ASSISTANT RESPONSES:
{assistant_text[:18000]}

Return JSON matching this schema exactly:
{schema}

Rules:
- Empty arrays if nothing qualifies — do not force items.
- Each framework/playbook should be distinct and self-contained.
- Claims: only specific numbers, rates, or named rules with identifiable provenance.
- Glossary terms: domain-specific, not common English.
"""


def extract_frameworks(vault_path: Path, dry_run: bool = True,
                        tier: str = 'S', limit: Optional[int] = None,
                        output_path: Optional[Path] = None):
    """Per-conversation typed extraction (§4.1 of Distillation Strategy).

    Reads analysis report, filters to tier, for each conversation calls the
    LLM with a strict JSON schema and appends the result to a JSONL report.
    No vault writes — apply.py consumes the report separately.

    Args:
        tier: S (≥90), A (80-89), SA (≥80), B (50-79), or any value <=0 for all
        limit: cap number of conversations processed (for dry-run testing)
        output_path: override JSONL output path
    """
    global openai_client
    if openai_client is None:
        from openai import OpenAI
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            print("❌ OPENAI_API_KEY not set")
            return
        openai_client = OpenAI(api_key=api_key)

    results = load_analysis_report(vault_path)
    if not results:
        return

    # Filter by tier
    candidates = [
        r for r in results
        if _tier_filter(r['analysis'].get('quality_score', 0), tier)
    ]
    # Filter out conversations explicitly excluded from distillation
    # (personal code experiments, off-topic). Saves LLM calls.
    pre_skip = len(candidates)
    candidates = [
        r for r in candidates
        if not _should_skip(r.get('title', ''), r['analysis'].get('primary_topics', []))
    ]
    skipped = pre_skip - len(candidates)
    if skipped:
        print(f"Skipped {skipped} conversations matching SKIP_CONVERSATION_PATTERNS")
    candidates.sort(key=lambda r: -r['analysis']['quality_score'])

    if limit:
        candidates = candidates[:limit]

    # Default output path
    if output_path is None:
        reports_dir = Path(__file__).parent / 'reports'
        reports_dir.mkdir(exist_ok=True)
        output_path = reports_dir / f'chatgpt_extract_tier{tier}_{datetime.now().strftime("%Y-%m-%d")}.jsonl'

    print(f"Tier {tier}: {len(candidates)} conversations to extract")
    print(f"Output: {output_path}")
    print(f"Mode: {'DRY RUN (no LLM calls)' if dry_run else 'LIVE'}")
    print("=" * 80)

    if not candidates:
        return

    if dry_run:
        print("\nTier-S/A preview (first 10):")
        for r in candidates[:10]:
            print(f"  {r['analysis']['quality_score']:.0f}  {Path(r['path']).stem[:70]}")
        print(f"\nDry-run complete. Rerun with --no-dry-run to call the LLM and write JSONL.")
        return

    # Resume support: skip conversations already in the JSONL
    processed_ids = set()
    if output_path.exists():
        with open(output_path, 'r') as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    processed_ids.add(entry.get('conv_id'))
                except json.JSONDecodeError:
                    continue
        print(f"Resuming: {len(processed_ids)} conversations already in report, skipping.")

    total_frameworks = 0
    total_playbooks = 0
    total_claims = 0
    total_glossary = 0
    errors = 0

    chatgpt_folder = vault_path / CHATGPT_FOLDER

    with open(output_path, 'a') as out_f:
        for idx, r in enumerate(candidates, 1):
            conv_path = Path(r['path'])
            conv_id = str(conv_path.relative_to(vault_path)) if conv_path.is_relative_to(vault_path) else str(conv_path)

            if conv_id in processed_ids:
                continue

            if not conv_path.exists():
                print(f"  [{idx}/{len(candidates)}] MISSING: {conv_path.name}")
                continue

            # Parse conversation
            conv = parse_conversation_file(conv_path)
            if not conv:
                errors += 1
                continue

            prompt = _build_extract_prompt(conv)
            score = r['analysis']['quality_score']

            try:
                response = openai_client.chat.completions.create(
                    model=OPENAI_MODEL,
                    messages=[
                        {"role": "system", "content": EXTRACT_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt}
                    ],
                    max_completion_tokens=6000,
                    response_format={"type": "json_object"}
                )
                raw = response.choices[0].message.content
                data = json.loads(raw)
            except json.JSONDecodeError as e:
                print(f"  [{idx}/{len(candidates)}] JSON PARSE ERROR: {conv.title[:60]} — {e}")
                errors += 1
                continue
            except Exception as e:
                print(f"  [{idx}/{len(candidates)}] API ERROR: {conv.title[:60]} — {e}")
                errors += 1
                continue

            frameworks = data.get('frameworks', [])
            playbooks = data.get('playbooks', [])
            claims = data.get('claims', [])
            glossary = data.get('glossary', [])

            total_frameworks += len(frameworks)
            total_playbooks += len(playbooks)
            total_claims += len(claims)
            total_glossary += len(glossary)

            entry = {
                'conv_id': conv_id,
                'title': conv.title,
                'score': score,
                'primary_topics': r['analysis'].get('primary_topics', []),
                'extracted_at': datetime.now().isoformat(timespec='seconds'),
                'model': OPENAI_MODEL,
                'frameworks': frameworks,
                'playbooks': playbooks,
                'claims': claims,
                'glossary': glossary,
                'input_tokens': response.usage.prompt_tokens,
                'output_tokens': response.usage.completion_tokens,
            }

            out_f.write(json.dumps(entry, ensure_ascii=False) + '\n')
            out_f.flush()

            print(f"  [{idx}/{len(candidates)}] {score:3.0f} {conv.title[:50]:50s} "
                  f"→ F{len(frameworks)} P{len(playbooks)} C{len(claims)} G{len(glossary)}")

    print(f"\n{'=' * 80}")
    print(f"Extraction complete.")
    print(f"  Frameworks: {total_frameworks}")
    print(f"  Playbooks:  {total_playbooks}")
    print(f"  Claims:     {total_claims}")
    print(f"  Glossary:   {total_glossary}")
    print(f"  Errors:     {errors}")
    print(f"Report: {output_path}")


def mine_questions(vault_path: Path, dry_run: bool = True,
                    min_cluster_size: int = 3, min_score: float = 70.0,
                    output_path: Optional[Path] = None):
    """Cross-corpus question clustering via LanceDB embeddings (§4.2).

    Extracts user-question turns from conversations with quality score ≥
    min_score, embeds each with sentence-transformers (via Ollama's
    nomic-embed-text model used by vault_pipeline), clusters by cosine
    similarity, and outputs a TSV of canonical questions.

    For now this is a simpler implementation: group by embedding-space
    clusters using HDBSCAN on normalized vectors. Full LanceDB integration
    and "best answer" scoring deferred to a follow-up pass.
    """
    results = load_analysis_report(vault_path)
    if not results:
        return

    # For now, mine_questions uses the key_questions already extracted
    # during the analyze phase. Full transcript re-scan is a later refinement.
    pool = []
    for r in results:
        if r['analysis'].get('quality_score', 0) < min_score:
            continue
        for q in r['analysis'].get('key_questions', []):
            q = q.strip()
            if len(q) < 10 or len(q) > 400:
                continue
            pool.append({
                'question': q,
                'source': str(Path(r['path']).relative_to(vault_path)) if Path(r['path']).is_relative_to(vault_path) else r['path'],
                'title': Path(r['path']).stem,
                'score': r['analysis']['quality_score'],
                'topics': r['analysis'].get('primary_topics', []),
            })

    print(f"Candidate questions: {len(pool)} (score ≥ {min_score})")
    print(f"Min cluster size: {min_cluster_size}")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print("=" * 80)

    if not pool:
        return

    # Default output
    if output_path is None:
        reports_dir = Path(__file__).parent / 'reports'
        reports_dir.mkdir(exist_ok=True)
        output_path = reports_dir / f'chatgpt_questions_{datetime.now().strftime("%Y-%m-%d")}.tsv'

    if dry_run:
        print(f"Would write to: {output_path}")
        print(f"Sample questions:")
        for p in pool[:10]:
            print(f"  [{p['score']:.0f}] {p['question'][:100]}")
        print(f"\nDry-run complete. Full clustering requires embedding model; rerun with --no-dry-run.")
        return

    # Embed each question via Ollama (nomic-embed-text matches the vault_pipeline)
    print("Computing embeddings via Ollama (nomic-embed-text)...")
    try:
        import httpx
    except ImportError:
        print("❌ httpx required for Ollama embedding calls. Install with: pip install httpx")
        return

    embeddings = []
    for idx, p in enumerate(pool):
        if idx % 50 == 0:
            print(f"  {idx}/{len(pool)}")
        try:
            resp = httpx.post(
                "http://localhost:11434/api/embeddings",
                json={"model": "nomic-embed-text", "prompt": p['question']},
                timeout=30.0
            )
            resp.raise_for_status()
            embeddings.append(resp.json()['embedding'])
        except Exception as e:
            print(f"  Embedding error at {idx}: {e}")
            embeddings.append(None)

    # Simple clustering: for each question, find all others with cosine > 0.85
    import numpy as np
    valid = [(i, np.array(e)) for i, e in enumerate(embeddings) if e is not None]
    if not valid:
        print("❌ No embeddings computed. Is Ollama running?")
        return

    # Normalize
    for i, v in valid:
        n = np.linalg.norm(v)
        if n > 0:
            v /= n

    threshold = 0.75
    assigned = {}
    cluster_id = 0
    clusters = {}

    for i, v in valid:
        if i in assigned:
            continue
        cluster_id += 1
        assigned[i] = cluster_id
        clusters[cluster_id] = [i]
        for j, w in valid:
            if j <= i or j in assigned:
                continue
            if float(np.dot(v, w)) >= threshold:
                assigned[j] = cluster_id
                clusters[cluster_id].append(j)

    # Filter to clusters of min size, output canonical = highest-score question
    recurring = [(cid, members) for cid, members in clusters.items() if len(members) >= min_cluster_size]
    recurring.sort(key=lambda x: -len(x[1]))

    # Write TSV
    with open(output_path, 'w') as f:
        f.write("cluster_id\tsize\tcanonical_question\tmember_titles\ttopics\n")
        for cid, members in recurring:
            # Canonical: highest-score member
            best = max(members, key=lambda m: pool[m]['score'])
            titles = '; '.join(sorted({pool[m]['title'] for m in members}))
            all_topics = set()
            for m in members:
                all_topics.update(pool[m]['topics'])
            topics_str = ', '.join(sorted(all_topics))
            f.write(f"{cid}\t{len(members)}\t{pool[best]['question']}\t{titles}\t{topics_str}\n")

    print(f"\n{'=' * 80}")
    print(f"Total questions:      {len(pool)}")
    print(f"Embedded:             {len(valid)}")
    print(f"Recurring clusters:   {len(recurring)} (size ≥ {min_cluster_size})")
    print(f"Singletons:           {len(valid) - sum(len(m) for _, m in recurring)}")
    print(f"Report: {output_path}")


# ============================================================================
# APPLY: gated write from extract JSONL (§4.3)
# ============================================================================

# Conversations whose entire content is skipped — no artefacts written.
# These are personal tooling/coding experiments (user archive: raw chat only),
# and off-topic personal content (music, health, philosophy).
SKIP_CONVERSATION_PATTERNS = [
    # Personal code / tooling projects (cluster 7 — archive raw, no distillation)
    'discord bot', 'discord-bot', 'discord.py', 'bot permission', 'bot invitation',
    'bot accept invitation', 'sesh bot', 'discord event management',
    'network architect guidance',
    'custom gpt data integration', 'gpt instruction design',
    'situational contract advice gpt', 'specialized gpt design',
    'pepe app', 'agent evaluation', 'test-prompt design',
    'fixing duplicate detection', 'duplicate detection',
    'dev env recommendations', 'python development environment',
    'vs code configuration', 'deshacer cambios en git', 'restore vs reset',
    'git restore', 'git reset',
    'beta functionality design',
    # Personal productivity tools / user-side coding trivia
    'outlook obsidian', 'outlook-obsidian', 'calendar integration',
    'hoja de gastos', 'expense automation', 'expense-automation',
    'extraer correos', 'outlook email extraction',
    'mejoras para mini-app', 'credential management',
    'consolidate enex', 'enex attachments', 'attachments consolidation',
    'm4a chunk', 'audio chunking', 'ffmpeg', 'pydub',
    'selenium', 'xpath', 'web scraping',
    'parse base64', 'base64 as xml', 'base64 xml',
    'unicode character warning', 'unicode normalization',
    'despliegue en nube', 'cloud deployment', 'kubernetes',
    'accessing ted api', 'ted api access', 'python api integration',
    'conexión api ted', 'conexion api ted',
    # iPhone / Siri / voice-capture tooling
    'siri', 'iphone-based', 'iphone approval', 'driving notes',
    'voz en obsidian', 'voice-note capture', 'capture driving',
    # Meta-vault / Obsidian personal-use
    'obsidian notes for querying', 'structure obsidian notes',
    'classify a note into projects', 'para method routing',
    'prepare obsidian notes for ai',
    # Personal finance / domestic
    'electricity contract', 'electricity supplier', 'solar surplus',
    # Personal social-media tooling
    'ai-curated linkedin', 'manual approval loop for ai',
    'scheduled external workflow', 'discord poll',
    # IDE / dev-environment tooling
    'continue in vs code', 'github branch rulesets',
    'pull-request approval',
    # Inspection/diagnosis one-liners
    'diagnose and stop', 'streamlit background process',
    'inspect a json file',
    # Personal / off-topic (cluster 8 — out of pipeline)
    'basement concert', 'live sound setup', 'microphone placement',
    'recording workflow', 'concert sound setup',
    'hidradenitis', 'biologic and novel',
    'apología de sócrates', 'apología sócrates', 'apologia sócrates',
    'motivos del juicio',
    'diferencias entre evangelios', 'gospels', 'biblical theology',
    'perfil musical', 'banda versiones', 'musical profiling',
    'repertoire curation',
]


def _should_skip(title: str, primary_topics: List[str]) -> bool:
    """Return True if the conversation should produce zero distilled artefacts."""
    haystack = ' '.join([title] + list(primary_topics)).lower()
    return any(p in haystack for p in SKIP_CONVERSATION_PATTERNS)


# Conversation → target area routing (heuristic, conversation-level).
# Each rule: (list of phrase patterns, target path segments from 3.RECURSOS/).
# Order matters: first matching rule wins. Evaluated against conversation
# title + primary_topics concatenated (lowercase).
ROUTING_RULES = [
    # Career, consulting business, pricing, strategy — Professional Dev
    (['career', 'engagement model', 'consulting rates', 'consulting business',
      'freelance', 'freelancing', 'fractional', 'non-executive director',
      ' ned ', 'professional network', 'pricing strategy', 'pricing -',
      'transición', 'cambio profesional', 'day rate', 'billable',
      # Business strategy / consulting market
      'strategy principle', 'strategic case', 'kernel in 3', 'kernel strategy',
      'market sizing', 'market intelligence', 'business strategy',
      'consulting services', 'consulting scope', 'engineering consulting',
      'engineering firm', 'valuing engineering', 'sales & marketing',
      'sales enablement', 'marketing enablement', 'business development',
      'valuing data',
      # CV, executive productivity, personal fiscal
      'cv summarization', 'professional branding',
      'executive productivity', 'delegation and automation',
      'asesoría fiscal', 'asesoria fiscal', 'fatca', 'w-8ben', 'w8ben',
      'international tax',
      # Firm-level financial analysis (TYPSA etc.)
      'salud financiera', 'industry benchmarking',
      'engineering consultancy sector'],
     ['Professional Dev']),

    # PPPs, concessions, project finance, engineering contracts — PPPs folder
    (['ppp', 'p3 ', 'concession', 'concesion', 'project finance',
      'bankability', 'availability payment', 'spv', 'dbfo', 'dbfm',
      'offtake', 'psc ', 'value for money', 'vfm ', 'shadow toll',
      'riesgo operacional', 'equilibrio económico',
      # G2G as PPP variant
      'g2g ', 'government-to-government', 'government to government',
      'pago por disponibilidad',
      # Engineering contracts, procurement, RFP / OE / EPC
      ' epc', 'epc vs', 'epc commercial', 'epc contract', 'design & build',
      'design and build',
      "owner's engineer", 'owner engineer', 'oe roles', 'oe commercial',
      'oe proposal',
      'construction contracts', 'comparison of construction contracts',
      'project 13', 'nec4', 'nec 4 ecc', 'nec4 ecc',
      'liability limitation', 'ie report liability',
      'work packages', 'wp summary',
      'tender', 'pliego', 'rfp ', 'rfp/tor', ' tor ', 'tor summary',
      'rfp summary', 'rfp scope', 'scope summary',
      'procurement methods', 'procurement compliance', 'public procurement',
      'rfp / procurement',
      'asociaciones público-privadas', 'asociaciones publico-privadas',
      'app bid', 'asesoría consultoría app', 'asesoria consultoria app',
      'project tender', 'construction management',
      'concurso desalación', 'concurso desalacion', 'desalination',
      'proposal pricing', 'proposal optimization',
      'contractual risk mitigation', 'packaging and bundling',
      'services procurement'],
     ['Domain Knowledge', 'PPPs']),

    # AI / LLM / agentic / asset mgmt / digital twin / GIS → Digital Transformation
    # User rule: asset management ALWAYS goes to Digital Transformation.
    (['rag', 'llm', 'agentic', 'prompt engineering', 'prompt optimization',
      'prompt optimisation', 'embedding', 'vector store', 'vector database',
      'gpt-', 'claude ', 'openai', 'ollama', 'faiss', 'langchain', 'langgraph',
      'ai architecture', 'ai assistant', 'ai agent', 'ai solution',
      'generative ai', 'fine-tun', 'retrieval-augmented',
      # Asset management applied to infrastructure
      'asset management', 'asset lifecycle', 'asset maintenance',
      'maintenance strategy', 'road asset management', 'resilient road asset',
      'rram', 'ssatp', 'afera', 'agepar', 'asset monitoring',
      'predictive maintenance', 'infrastructure monitoring',
      'infrastructure asset management',
      # GIS / geospatial / satellite / applied AI in civil engineering
      'geoai', 'qgis', 'satellite data', 'geospatial', 'gis',
      'satellite remote sensing', 'remote sensing',
      'ai in civil engineering', 'ai disruption in civil',
      'ai in infrastructure', 'ia generativa', 'inteligencia artificial',
      # Digital twin / digitalización / Industry 4.0
      'digital twin', 'gemelo digital',
      'digitalización de infraestructuras', 'digitalización', 'digitalizacion',
      'infraestructuras 4.0', 'industry 4.0',
      # Data architecture, workflows, AI impact
      'data governance', 'data valuation', 'data integration',
      'data architecture', 'modern data stack',
      'workflow integration', 'ai workflow',
      'construction tech', 'ai-based risk',
      'ai trends', 'ai adoption', 'ai impact', 'ai growth',
      'rail digitization', 'rail automation',
      # AI/ML foundations (for user literacy)
      'transformers', 'self-attention', 'deep learning', 'meta-learning'],
     ['Domain Knowledge', 'Digital Transformation']),

    # Risk, resilience, climate
    (['risk management', 'climate risk', 'resilience', 'disaster risk',
      'asset exposure', 'vulnerability', 'hazard', 'insurance',
      'cascading risk'],
     ['Domain Knowledge', 'Risk Management']),

    # Policy, regulation, governance, ITS, water governance, admin reform
    (['policy', 'regulation', 'regulatory', 'governance', 'public sector reform',
      'legal framework', 'lcsp', 'directive', 'sector público', 'transparency',
      'real decreto', 'sistemas inteligentes de transporte',
      'intelligent transport systems', 'water governance', 'water policy',
      'road funds', 'road maintenance funds',
      'análisis jurídico', 'concesión administrativa',
      # Public administration reform
      'public administration reform', 'civil service reform',
      "reforma de l'administració", 'reforma administración',
      'reforma administracion', 'administración pública', 'administracion publica'],
     ['Domain Knowledge', 'Infrastructure Policy']),

    # Investment, funds, bonds, financing, cost estimation, market analysis
    (['infrastructure investment', 'infrastructure fund', 'investment fund',
      'green bond', 'infrastructure bond', 'pension fund', 'blended finance',
      'infrastructure financing', 'urban rail financing', 'transport financing',
      'rail financing', 'water financing', 'transit financing', 'financing model',
      'financing models', 'flood financing', 'urban rail', 'rail concession',
      'financial model', 'financial modeling',
      # Investment evaluation, road/metro planning
      'road investment evaluation', 'road funding analysis', 'road funding',
      'mrt financing', 'mrt management', 'metro planning', 'metro sevilla',
      'metro línea', 'línea 2',
      # Cost estimation / market analysis
      'soft costs', 'transit cost estimation', 'as-built cost analysis',
      'road works market', 'road construction market',
      'industrial master planning', 'investor targeting',
      'urban development planning', 'land value capture',
      'capex', ' opex'],
     ['Domain Knowledge', 'Infrastructure Investment']),

    # Sustainability, ESG, green
    (['sustainability', 'esg', 'green finance', 'circular economy',
      'climate adaptation', 'eu taxonomy'],
     ['Domain Knowledge', 'Sustainability']),
]

# Default: land in _Uncategorized under Domain Knowledge, to force manual
# review. Nothing should auto-land in a real domain folder without a match.
DEFAULT_ROUTING = ['Domain Knowledge', '_Uncategorized']


def _route_conversation(title: str, primary_topics: List[str]) -> List[str]:
    """Decide target area once per conversation. Returns path segments from
    3.RECURSOS/. All artefacts from the same conversation share this route."""
    haystack = ' '.join([title] + list(primary_topics)).lower()
    for patterns, segments in ROUTING_RULES:
        if any(p in haystack for p in patterns):
            return segments
    return DEFAULT_ROUTING


def _slug(text: str, max_len: int = 80) -> str:
    """Produce a filesystem-safe slug from a title. Preserves accents."""
    # Replace path separators and invalid chars
    s = re.sub(r'[/\\:*?"<>|]', '-', text)
    s = re.sub(r'\s+', ' ', s).strip()
    if len(s) > max_len:
        s = s[:max_len].rsplit(' ', 1)[0]
    return s


def _frontmatter_block(artefact_type: str, source_title: str, source_path: str,
                       topics: List[str], extra: Dict = None) -> str:
    """Standard frontmatter for distilled artefacts."""
    topic_tags = [f"  - topic/{t.lower().replace(' ', '-')}"
                  for t in topics[:3] if t and len(t) < 40]
    lines = [
        "---",
        f"date: {datetime.now().strftime('%Y-%m-%d')}",
        "tags:",
        f"  - type/{artefact_type}",
        "  - source/chatgpt-distilled",
        "  - status/review",
        "  - lang/en",
    ]
    lines.extend(topic_tags)
    lines.extend([
        f"source_conversation: \"[[{Path(source_path).stem}]]\"",
        f"distilled_from_score: {extra.get('score') if extra else 'null'}",
        "---",
        "",
    ])
    return '\n'.join(lines)


def _write_framework_note(vault: Path, entry: Dict, fw: Dict) -> Optional[Path]:
    """Emit a Framework Card note. Returns the path written, or None if skipped."""
    name = fw.get('name', '').strip()
    if not name:
        return None

    segments = _route_conversation(entry.get('title', ''), entry.get('primary_topics', []))
    target_dir = vault / '3.RECURSOS'
    for seg in segments:
        target_dir = target_dir / seg
    target_dir = target_dir / 'Frameworks'
    target_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{_slug(name)}.md"
    path = target_dir / filename
    if path.exists():
        return None  # Dedup: skip duplicates by exact filename

    fm = _frontmatter_block(
        'framework', entry['title'], entry['conv_id'],
        entry.get('primary_topics', []),
        extra={'score': entry.get('score')}
    )

    body = [f"# {name}", ""]
    if fw.get('definition'):
        body += ["## Definition", "", fw['definition'].strip(), ""]
    if fw.get('when_to_use'):
        body += ["## When to Use", "", fw['when_to_use'].strip(), ""]
    if fw.get('steps'):
        body += ["## Steps", ""] + [f"{i+1}. {s.strip()}" for i, s in enumerate(fw['steps'])] + [""]
    if fw.get('failure_modes'):
        body += ["## Failure Modes", ""] + [f"- {fm.strip()}" for fm in fw['failure_modes']] + [""]

    body += [
        "## Source",
        "",
        f"Distilled from [[{Path(entry['conv_id']).stem}]] "
        f"(quality score {entry.get('score', '?')}).",
        "",
    ]

    path.write_text(fm + '\n'.join(body), encoding='utf-8')
    return path


def _write_playbook_note(vault: Path, entry: Dict, pb: Dict) -> Optional[Path]:
    """Emit a Playbook note."""
    title = pb.get('title', '').strip()
    if not title:
        return None

    segments = _route_conversation(entry.get('title', ''), entry.get('primary_topics', []))
    target_dir = vault / '3.RECURSOS'
    for seg in segments:
        target_dir = target_dir / seg
    target_dir = target_dir / 'Playbooks'
    target_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{_slug(title)}.md"
    path = target_dir / filename
    if path.exists():
        return None

    fm = _frontmatter_block(
        'playbook', entry['title'], entry['conv_id'],
        entry.get('primary_topics', []),
        extra={'score': entry.get('score')}
    )

    body = [f"# {title}", ""]
    if pb.get('trigger'):
        body += ["## Trigger", "", pb['trigger'].strip(), ""]
    if pb.get('applicable_when'):
        body += ["## Applicable When", "", pb['applicable_when'].strip(), ""]
    if pb.get('steps'):
        body += ["## Steps", ""] + [f"{i+1}. {s.strip()}" for i, s in enumerate(pb['steps'])] + [""]
    body += [
        "## Source",
        "",
        f"Distilled from [[{Path(entry['conv_id']).stem}]] "
        f"(quality score {entry.get('score', '?')}).",
        "",
    ]

    path.write_text(fm + '\n'.join(body), encoding='utf-8')
    return path


def _write_claim_note(vault: Path, entry: Dict, cl: Dict) -> Optional[Path]:
    """Emit a Claim Card. Only high-confidence claims are written."""
    text = cl.get('text', '').strip()
    if not text or len(text) < 15:
        return None

    # Policy: discard medium and low confidence outright.
    # Rationale: signal-to-noise for a citation database.
    confidence = (cl.get('confidence') or '').lower().strip()
    if confidence != 'high':
        return None

    segments = _route_conversation(entry.get('title', ''), entry.get('primary_topics', []))
    target_dir = vault / '3.RECURSOS'
    for seg in segments:
        target_dir = target_dir / seg
    target_dir = target_dir / 'Claims'
    target_dir.mkdir(parents=True, exist_ok=True)

    # Claim filenames: first N words of text
    slug_source = ' '.join(text.split()[:10])
    filename = f"{_slug(slug_source, max_len=80)}.md"
    path = target_dir / filename
    if path.exists():
        return None

    fm = _frontmatter_block(
        'claim', entry['title'], entry['conv_id'],
        entry.get('primary_topics', []),
        extra={'score': entry.get('score')}
    )

    body = [
        f"# {slug_source[:80]}",
        "",
        "## Claim",
        "",
        text,
        "",
        f"**Domain:** {cl.get('domain', '—')}  ",
        f"**Confidence:** {cl.get('confidence', '—')}",
        "",
    ]
    if cl.get('source_excerpt'):
        body += ["## Source Excerpt", "", f"> {cl['source_excerpt'].strip()}", ""]
    body += [
        "## Source",
        "",
        f"Distilled from [[{Path(entry['conv_id']).stem}]].",
        "",
    ]

    path.write_text(fm + '\n'.join(body), encoding='utf-8')
    return path


def _write_glossary_note(vault: Path, entry: Dict, g: Dict) -> Optional[Path]:
    """Emit a Glossary entry."""
    term = g.get('term', '').strip()
    one_line = g.get('one_line', '').strip()
    if not term or not one_line:
        return None

    target_dir = vault / '3.RECURSOS' / 'Domain Knowledge' / 'Glossary'
    target_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{_slug(term, max_len=80)}.md"
    path = target_dir / filename
    if path.exists():
        return None  # Glossary dedup: skip existing terms

    fm = _frontmatter_block(
        'glossary-term', entry['title'], entry['conv_id'],
        entry.get('primary_topics', []),
        extra={'score': entry.get('score')}
    )

    body = [
        f"# {term}",
        "",
        one_line,
        "",
        f"**Topic:** {g.get('topic', '—')}",
        "",
        "## Source",
        "",
        f"Distilled from [[{Path(entry['conv_id']).stem}]].",
        "",
    ]

    path.write_text(fm + '\n'.join(body), encoding='utf-8')
    return path


def apply_extracts(vault_path: Path, report_path: Optional[Path] = None,
                    dry_run: bool = True, types: Optional[List[str]] = None,
                    limit: Optional[int] = None):
    """Read an extract JSONL report and write typed artefact notes.

    Mirror of apply_tags_from_report.py (§4.3 of strategy).
    Dedup: skips if a file with the same generated filename already exists
    in the target folder (simple name-based; LanceDB embedding dedup deferred).

    Args:
        report_path: JSONL file to consume. Defaults to most recent in reports/.
        types: subset of ['framework', 'playbook', 'claim', 'glossary'].
               Defaults to all.
        limit: cap number of conversations processed.
    """
    if types is None:
        types = ['framework', 'playbook', 'claim', 'glossary']

    # Default: latest report
    if report_path is None:
        reports_dir = Path(__file__).parent / 'reports'
        if not reports_dir.exists():
            print(f"❌ No reports directory at {reports_dir}. Run 'extract' first.")
            return
        candidates = sorted(reports_dir.glob('chatgpt_extract_*.jsonl'))
        if not candidates:
            print(f"❌ No extract reports found. Run 'extract' first.")
            return
        report_path = candidates[-1]

    if not report_path.exists():
        print(f"❌ Report not found: {report_path}")
        return

    print(f"Report: {report_path}")
    print(f"Types:  {', '.join(types)}")
    print(f"Mode:   {'DRY RUN' if dry_run else 'LIVE'}")
    print("=" * 80)

    entries = []
    with open(report_path, 'r') as f:
        for line in f:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    if limit:
        entries = entries[:limit]

    # Filter out skipped-pattern conversations (in case the JSONL was
    # produced before the skip patterns were defined)
    pre_skip = len(entries)
    entries = [
        e for e in entries
        if not _should_skip(e.get('title', ''), e.get('primary_topics', []))
    ]
    if pre_skip != len(entries):
        print(f"Skipped {pre_skip - len(entries)} conversations matching SKIP_CONVERSATION_PATTERNS")

    print(f"Loaded {len(entries)} conversation entries.")

    writers = {
        'framework': (_write_framework_note, 'frameworks'),
        'playbook': (_write_playbook_note, 'playbooks'),
        'claim': (_write_claim_note, 'claims'),
        'glossary': (_write_glossary_note, 'glossary'),
    }

    stats = {t: {'written': 0, 'skipped': 0} for t in writers}

    for entry in entries:
        for art_type, (writer, key) in writers.items():
            if art_type not in types:
                continue
            for artefact in entry.get(key, []):
                if dry_run:
                    # Simulate routing and filename
                    if art_type == 'glossary':
                        name = artefact.get('term', '(unnamed)')
                    elif art_type == 'claim':
                        name = ' '.join(artefact.get('text', '(unnamed)').split()[:10])
                    else:
                        name = artefact.get('name') or artefact.get('title') or '(unnamed)'
                    stats[art_type]['written'] += 1
                    if len(name) > 0:
                        if art_type == 'glossary':
                            folder_hint = 'Domain Knowledge/Glossary'
                        else:
                            segs = _route_conversation(
                                entry.get('title', ''),
                                entry.get('primary_topics', [])
                            )
                            folder_hint = '/'.join(segs + [art_type.capitalize() + 's'])
                        print(f"  [DRY] {art_type:10s} → {folder_hint}/{_slug(name, 60)}.md")
                else:
                    path = writer(vault_path, entry, artefact)
                    if path is not None:
                        stats[art_type]['written'] += 1
                    else:
                        stats[art_type]['skipped'] += 1

    print(f"\n{'=' * 80}")
    print(f"Results:")
    for art_type in writers:
        if art_type in types:
            s = stats[art_type]
            print(f"  {art_type:10s}  written: {s['written']:4d}  skipped: {s['skipped']:4d}")


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

    parser.add_argument('command', choices=['analyze', 'update-frontmatter', 'tag', 'extract', 'apply', 'mine-questions', 'cleanup'],
                       help='Command to run')

    parser.add_argument('--provider', choices=['openai', 'ollama'], default='openai',
                       help='LLM provider: openai or ollama (default: openai)')

    parser.add_argument('--no-dry-run', action='store_true',
                       help='Actually perform actions (default is dry-run)')

    parser.add_argument('--limit', type=int,
                       help='Limit number of files to process (for testing)')

    parser.add_argument('--threshold', type=float, default=40.0,
                       help='Quality threshold for cleanup (default: 40.0)')

    parser.add_argument('--min-score', type=float, default=70.0,
                       help='Minimum quality score for mine-questions (default: 70.0)')

    parser.add_argument('--tier', default='S', choices=['S', 'A', 'SA', 'B', 'all'],
                       help='Conversation tier for extract (S≥90, A 80-89, SA≥80, B 50-79, all). Default: S')

    parser.add_argument('--min-cluster-size', type=int, default=3,
                       help='Minimum cluster size for mine-questions recurring themes (default: 3)')

    parser.add_argument('--output', type=Path,
                       help='Output path for extract/mine-questions report (default: ./reports/...)')

    parser.add_argument('--model', default=None,
                       help='Override OPENAI_MODEL for this run (default: gpt-5-mini-2025-08-07)')

    parser.add_argument('--report', type=Path,
                       help='JSONL report to apply (default: latest in ./reports/)')

    parser.add_argument('--types', nargs='+',
                       choices=['framework', 'playbook', 'claim', 'glossary'],
                       help='Artefact types to apply (default: all)')

    args = parser.parse_args()

    vault_path = args.vault.resolve()
    dry_run = not args.no_dry_run

    # Per-run model override (lets us A/B test different OpenAI models)
    if args.model:
        global OPENAI_MODEL
        OPENAI_MODEL = args.model
        print(f"Model override: {OPENAI_MODEL}")

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
        tier = 'all' if args.tier == 'all' else args.tier
        extract_frameworks(vault_path, dry_run, tier, args.limit, args.output)
    elif args.command == 'apply':
        apply_extracts(vault_path, args.report, dry_run, args.types, args.limit)
    elif args.command == 'mine-questions':
        mine_questions(vault_path, dry_run, args.min_cluster_size, args.min_score, args.output)
    elif args.command == 'cleanup':
        cleanup_conversations(vault_path, args.threshold, dry_run)


if __name__ == '__main__':
    main()
