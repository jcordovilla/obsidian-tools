#!/usr/bin/env python3
"""
Analyze ChatGPT conversation statistics to inform sampling strategy.

Calculates character counts, message counts, and distributions to help
determine optimal sampling thresholds for LLM analysis.
"""

import argparse
import json
import re
from pathlib import Path
from typing import Dict, List, Tuple
from dataclasses import dataclass
import statistics

# ============================================================================
# DATA MODELS
# ============================================================================

@dataclass
class ConversationStats:
    """Statistics for a single conversation."""
    path: Path
    title: str
    total_chars: int
    user_messages: int
    assistant_messages: int
    user_chars: int
    assistant_chars: int
    avg_user_msg_length: float
    avg_assistant_msg_length: float


# ============================================================================
# FILE PARSING
# ============================================================================

def extract_messages(content: str) -> Tuple[List[str], List[str]]:
    """Extract user and assistant messages from markdown.

    Returns:
        Tuple of (user_messages, assistant_messages)
    """
    user_messages = []
    assistant_messages = []

    # User messages: ### User, on ...
    user_pattern = r'###\s+User,\s+on\s+[^;]+;?\s*\n>\s*(.+?)(?=\n###|\n####|\n<details>|\n---|\Z)'
    for match in re.finditer(user_pattern, content, re.DOTALL):
        user_messages.append(match.group(1).strip())

    # Assistant messages: #### ChatGPT, on ...
    assistant_pattern = r'####\s+ChatGPT,\s+on\s+[^;]+;?\s*\n>>\s*(.+?)(?=\n###|\n####|\n<details>|\n---|\Z)'
    for match in re.finditer(assistant_pattern, content, re.DOTALL):
        assistant_messages.append(match.group(1).strip())

    return user_messages, assistant_messages


def analyze_conversation(file_path: Path) -> ConversationStats:
    """Analyze a single conversation file."""
    try:
        content = file_path.read_text(encoding='utf-8')

        # Extract title
        title_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
        title = title_match.group(1).strip() if title_match else file_path.stem

        # Extract messages
        user_messages, assistant_messages = extract_messages(content)

        # Calculate statistics
        user_chars = sum(len(msg) for msg in user_messages)
        assistant_chars = sum(len(msg) for msg in assistant_messages)
        total_chars = user_chars + assistant_chars

        avg_user_msg = user_chars / len(user_messages) if user_messages else 0
        avg_assistant_msg = assistant_chars / len(assistant_messages) if assistant_messages else 0

        return ConversationStats(
            path=file_path,
            title=title,
            total_chars=total_chars,
            user_messages=len(user_messages),
            assistant_messages=len(assistant_messages),
            user_chars=user_chars,
            assistant_chars=assistant_chars,
            avg_user_msg_length=avg_user_msg,
            avg_assistant_msg_length=avg_assistant_msg
        )
    except Exception as e:
        print(f"  ⚠️  Error analyzing {file_path.name}: {e}")
        return None


# ============================================================================
# STATISTICS CALCULATION
# ============================================================================

def calculate_coverage(stats: List[ConversationStats], user_limit: int, assistant_limit: int,
                       max_messages: int = 3) -> Dict:
    """Calculate what % of content would be captured with given limits."""
    total_content = 0
    captured_content = 0

    for conv in stats:
        # Total content
        total_content += conv.user_chars + conv.assistant_chars

        # Captured content with limits
        if conv.user_messages <= 2:  # Single-turn logic
            user_captured = min(conv.user_chars, user_limit * conv.user_messages)
            assistant_captured = min(conv.assistant_chars, assistant_limit * conv.assistant_messages)
        else:  # Multi-turn logic
            user_msgs_sampled = min(conv.user_messages, max_messages)
            assistant_msgs_sampled = min(conv.assistant_messages, max_messages)

            # Approximate: assume messages are roughly equal length
            avg_user = conv.user_chars / conv.user_messages if conv.user_messages > 0 else 0
            avg_assistant = conv.assistant_chars / conv.assistant_messages if conv.assistant_messages > 0 else 0

            user_captured = min(user_msgs_sampled * min(avg_user, user_limit), conv.user_chars)
            assistant_captured = min(assistant_msgs_sampled * min(avg_assistant, assistant_limit), conv.assistant_chars)

        captured_content += user_captured + assistant_captured

    coverage_pct = (captured_content / total_content * 100) if total_content > 0 else 0

    return {
        'total_chars': total_content,
        'captured_chars': int(captured_content),
        'coverage_pct': coverage_pct
    }


def print_statistics(stats: List[ConversationStats]):
    """Print comprehensive statistics about conversations."""
    if not stats:
        print("No conversations to analyze")
        return

    # Basic counts
    total_convs = len(stats)
    single_turn = sum(1 for s in stats if s.user_messages <= 2)
    multi_turn = total_convs - single_turn

    # Character statistics
    total_chars = [s.total_chars for s in stats]
    user_chars = [s.user_chars for s in stats]
    assistant_chars = [s.assistant_chars for s in stats]

    # Message counts
    user_msg_counts = [s.user_messages for s in stats]
    assistant_msg_counts = [s.assistant_messages for s in stats]

    # Message lengths
    user_msg_lengths = [s.avg_user_msg_length for s in stats if s.user_messages > 0]
    assistant_msg_lengths = [s.avg_assistant_msg_length for s in stats if s.assistant_messages > 0]

    print("="*80)
    print("CHATGPT CONVERSATION STATISTICS")
    print("="*80)

    print(f"\n📊 Overall Counts:")
    print(f"  Total conversations: {total_convs}")
    print(f"  Single-turn (≤2 user msgs): {single_turn} ({single_turn/total_convs*100:.1f}%)")
    print(f"  Multi-turn (>2 user msgs): {multi_turn} ({multi_turn/total_convs*100:.1f}%)")

    print(f"\n💬 Message Counts:")
    print(f"  User messages per conversation:")
    print(f"    Mean: {statistics.mean(user_msg_counts):.1f}")
    print(f"    Median: {statistics.median(user_msg_counts):.0f}")
    print(f"    Min/Max: {min(user_msg_counts)}/{max(user_msg_counts)}")
    print(f"  Assistant messages per conversation:")
    print(f"    Mean: {statistics.mean(assistant_msg_counts):.1f}")
    print(f"    Median: {statistics.median(assistant_msg_counts):.0f}")
    print(f"    Min/Max: {min(assistant_msg_counts)}/{max(assistant_msg_counts)}")

    print(f"\n📝 Character Counts:")
    print(f"  Total characters per conversation:")
    print(f"    Mean: {statistics.mean(total_chars):,.0f}")
    print(f"    Median: {statistics.median(total_chars):,.0f}")
    print(f"    Min/Max: {min(total_chars):,}/{max(total_chars):,}")
    print(f"  User characters per conversation:")
    print(f"    Mean: {statistics.mean(user_chars):,.0f}")
    print(f"    Median: {statistics.median(user_chars):,.0f}")
    print(f"  Assistant characters per conversation:")
    print(f"    Mean: {statistics.mean(assistant_chars):,.0f}")
    print(f"    Median: {statistics.median(assistant_chars):,.0f}")

    print(f"\n📏 Average Message Lengths:")
    print(f"  User messages:")
    print(f"    Mean: {statistics.mean(user_msg_lengths):,.0f} chars")
    print(f"    Median: {statistics.median(user_msg_lengths):,.0f} chars")
    print(f"  Assistant messages:")
    print(f"    Mean: {statistics.mean(assistant_msg_lengths):,.0f} chars")
    print(f"    Median: {statistics.median(assistant_msg_lengths):,.0f} chars")

    # Percentiles
    print(f"\n📈 Character Count Percentiles:")
    percentiles = [50, 75, 80, 90, 95, 99]
    for p in percentiles:
        val = sorted(total_chars)[int(len(total_chars) * p / 100)]
        print(f"  {p}th percentile: {val:,} chars")

    # Coverage analysis with different sampling strategies
    print(f"\n🎯 Sampling Coverage Analysis:")
    print(f"  (Shows % of total content captured with different limits)")
    print()

    strategies = [
        ("Current (2000/500×3)", 2000, 500, 3),
        ("Conservative (1000/300×3)", 1000, 300, 3),
        ("Aggressive (3000/800×5)", 3000, 800, 5),
        ("Full single/500×5", 999999, 500, 5),
    ]

    for name, user_limit, asst_limit, max_msgs in strategies:
        coverage = calculate_coverage(stats, user_limit, asst_limit, max_msgs)
        print(f"  {name}:")
        print(f"    Coverage: {coverage['coverage_pct']:.1f}%")
        print(f"    Captured: {coverage['captured_chars']:,} / {coverage['total_chars']:,} chars")
        print()

    # Distribution by conversation length
    print(f"\n📊 Conversation Length Distribution:")
    bins = [(0, 1000), (1000, 5000), (5000, 10000), (10000, 20000), (20000, 999999)]
    for min_chars, max_chars in bins:
        count = sum(1 for s in stats if min_chars <= s.total_chars < max_chars)
        pct = count / total_convs * 100
        label = f"{min_chars:,}-{max_chars:,}" if max_chars < 999999 else f"{min_chars:,}+"
        print(f"  {label:20} chars: {count:4} ({pct:5.1f}%)")


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Analyze ChatGPT conversation statistics'
    )

    parser.add_argument('--vault', type=Path, required=True,
                       help='Path to Obsidian vault')

    parser.add_argument('--output', type=Path,
                       help='Save detailed stats to JSON file')

    args = parser.parse_args()

    vault_path = args.vault.resolve()
    chatgpt_path = vault_path / "3.RECURSOS/AI & ML/ChatGPT Conversations"

    if not chatgpt_path.exists():
        print(f"❌ ChatGPT folder not found: {chatgpt_path}")
        return

    # Find all conversations
    all_files = sorted(chatgpt_path.glob('**/*.md'))

    print(f"Analyzing {len(all_files)} conversations...")
    print()

    # Analyze each conversation
    stats = []
    for i, file_path in enumerate(all_files, 1):
        if i % 100 == 0:
            print(f"  Processed {i}/{len(all_files)}...")

        conv_stats = analyze_conversation(file_path)
        if conv_stats:
            stats.append(conv_stats)

    print(f"  Completed: {len(stats)} conversations analyzed")
    print()

    # Print statistics
    print_statistics(stats)

    # Save to JSON if requested
    if args.output:
        output_data = [
            {
                'path': str(s.path),
                'title': s.title,
                'total_chars': s.total_chars,
                'user_messages': s.user_messages,
                'assistant_messages': s.assistant_messages,
                'user_chars': s.user_chars,
                'assistant_chars': s.assistant_chars,
                'avg_user_msg_length': s.avg_user_msg_length,
                'avg_assistant_msg_length': s.avg_assistant_msg_length
            }
            for s in stats
        ]

        args.output.write_text(json.dumps(output_data, indent=2))
        print(f"\n✅ Detailed statistics saved to: {args.output}")


if __name__ == '__main__':
    main()
