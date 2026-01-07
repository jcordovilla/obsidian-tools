#!/usr/bin/env python3
"""
Re-analyze conversations that had JSON parsing errors.

This script identifies conversations where the LLM response was truncated
(all have 1000 output tokens and "Error parsing LLM response" reasoning),
and re-analyzes them with increased token limits.
"""

import json
import sys
import os
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI
import chatgpt_enrichment
from chatgpt_enrichment import analyze_chat_quality, parse_conversation_file
import time


def main():
    # Load environment variables
    load_dotenv()

    # Initialize OpenAI client
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("❌ OPENAI_API_KEY not found in .env file")
        sys.exit(1)

    chatgpt_enrichment.openai_client = OpenAI(api_key=api_key)
    print("✓ OpenAI client initialized\n")

    report_path = Path("/Users/jose/obsidian/chatgpt_analysis_report.json")

    if not report_path.exists():
        print(f"❌ Report not found: {report_path}")
        sys.exit(1)

    # Load existing report
    print("Loading existing report...")
    with open(report_path, 'r') as f:
        all_data = json.load(f)

    # Find failed conversations
    failed_convs = [
        c for c in all_data
        if c['analysis'].get('reasoning') == 'Error parsing LLM response'
    ]

    print(f"\nFound {len(failed_convs)} conversations with parsing errors")
    print(f"These will be re-analyzed with increased token limit (2000)\n")

    print("="*80)
    print("RE-ANALYZING FAILED CONVERSATIONS")
    print("="*80)
    print()

    success_count = 0
    still_failed = 0
    start_time = time.time()

    for i, conv_data in enumerate(failed_convs, 1):
        file_path = Path(conv_data['path'])

        print(f"[{i}/{len(failed_convs)}] {file_path.name}")

        try:
            # Parse the conversation file
            conv = parse_conversation_file(file_path)

            if not conv:
                print(f"  ⚠️  Failed to parse file")
                still_failed += 1
                print()
                continue

            # Re-analyze with OpenAI
            analysis = analyze_chat_quality(conv, provider='openai')

            # Update the conversation data
            conv_data['analysis'] = {
                'quality_score': analysis.quality_score,
                'is_valuable': analysis.is_valuable,
                'primary_topics': analysis.primary_topics,
                'reasoning': analysis.reasoning,
                'has_framework': analysis.has_framework,
                'framework_description': analysis.framework_description,
                'key_questions': analysis.key_questions,
                'suggested_action': analysis.suggested_action,
                'input_tokens': analysis.input_tokens,
                'output_tokens': analysis.output_tokens,
                'processing_time': analysis.processing_time
            }

            # Check if still failed
            if analysis.reasoning == 'Error parsing LLM response':
                still_failed += 1
                print(f"  ⚠️  Still failed to parse")
            else:
                success_count += 1
                print(f"  ✓ Score: {analysis.quality_score}/100")
                print(f"    Action: {analysis.suggested_action}")

            print(f"    Tokens: {analysis.input_tokens} in + {analysis.output_tokens} out")
            print()

            # Save progress every 10 conversations
            if i % 10 == 0:
                with open(report_path, 'w') as f:
                    json.dump(all_data, f, indent=2)
                print(f"  💾 Progress saved ({i}/{len(failed_convs)})")
                print()

        except Exception as e:
            print(f"  ❌ Error: {e}")
            still_failed += 1
            print()

    # Final save
    with open(report_path, 'w') as f:
        json.dump(all_data, f, indent=2)

    elapsed = time.time() - start_time

    print("="*80)
    print("RE-ANALYSIS COMPLETE")
    print("="*80)
    print(f"\nResults:")
    print(f"  Successfully re-analyzed: {success_count}")
    print(f"  Still failed: {still_failed}")
    print(f"\nTime: {elapsed/60:.1f} minutes")
    print(f"\nUpdated report saved to: {report_path}")

    # Show new distribution
    stats = {
        'keep': sum(1 for c in all_data if c['analysis']['suggested_action'] == 'keep'),
        'archive': sum(1 for c in all_data if c['analysis']['suggested_action'] == 'archive'),
        'review': sum(1 for c in all_data if c['analysis']['suggested_action'] == 'review')
    }

    print(f"\nNew distribution:")
    print(f"  Keep: {stats['keep']}")
    print(f"  Archive: {stats['archive']}")
    print(f"  Review: {stats['review']}")


if __name__ == '__main__':
    main()
