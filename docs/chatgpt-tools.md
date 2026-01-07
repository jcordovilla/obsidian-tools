# ChatGPT Conversation Tools

A suite of tools for analyzing, enriching, and cleaning up exported ChatGPT conversations in your Obsidian vault.

## Overview

These tools work together to:
1. Analyze conversation quality using GPT-4o-mini
2. Add semantic topic tags
3. Extract frameworks and methodologies
4. Mine valuable questions for content ideas
5. Archive low-value conversations

## Scripts

| Script | Purpose |
|--------|---------|
| `chatgpt_enrichment.py` | Main tool - analyze, tag, extract, cleanup |
| `analyze_chat_stats.py` | Calculate statistics to inform sampling |
| `delete_low_value.py` | Delete conversations marked for archive |
| `reanalyze_failed.py` | Re-run analyses that had JSON parsing errors |
| `triage_reviews.py` | Interactive GUI for manual triage decisions |

## Requirements

```bash
pip install openai python-dotenv
```

Create `.env` file in obsidian-tools folder:
```
OPENAI_API_KEY=sk-your-key-here
```

## Main Tool: chatgpt_enrichment.py

### Commands

```bash
cd ~/mylab/obsidian-tools
source venv/bin/activate

# Analyze conversations with LLM
python chatgpt_enrichment.py --vault /Users/jose/obsidian/JC analyze

# Add topic tags based on content
python chatgpt_enrichment.py --vault /Users/jose/obsidian/JC tag

# Extract frameworks and methodologies
python chatgpt_enrichment.py --vault /Users/jose/obsidian/JC extract

# Mine questions for content ideas
python chatgpt_enrichment.py --vault /Users/jose/obsidian/JC mine-questions

# Archive low-value conversations
python chatgpt_enrichment.py --vault /Users/jose/obsidian/JC cleanup
```

### Analysis Criteria

The LLM evaluates each conversation for:
- **Usefulness**: Practical value of the content
- **Uniqueness**: Original insights vs generic information
- **Timelessness**: Will it remain relevant?
- **Your input**: Did you add significant context?

### Actions

Based on analysis, conversations are marked:
- **keep**: High-value, retain in vault
- **review**: Uncertain, needs manual decision
- **archive**: Low-value, safe to remove

## Support Scripts

### analyze_chat_stats.py

Calculates statistics to understand your ChatGPT corpus:
- Character counts and distributions
- Message counts per conversation
- Helps determine sampling thresholds

```bash
python analyze_chat_stats.py --vault /Users/jose/obsidian/JC
```

### delete_low_value.py

Processes the analysis report and deletes conversations marked for archive:

```bash
python delete_low_value.py
```

Reads from: `/Users/jose/obsidian/chatgpt_analysis_report.json`

### reanalyze_failed.py

Re-runs analysis on conversations where the LLM response was truncated (JSON parsing errors):

```bash
python reanalyze_failed.py
```

### triage_reviews.py

Opens a GUI for manually triaging conversations marked "review":

```bash
python triage_reviews.py
```

Features:
- Shows conversation summary and analysis
- Two buttons: KEEP or ARCHIVE
- Updates the JSON report in real-time

## Workflow

1. **Analyze**: Run `analyze` command to assess all conversations
2. **Review**: Use `triage_reviews.py` GUI for uncertain cases
3. **Cleanup**: Run `cleanup` to archive low-value conversations
4. **Enrich**: Run `tag` and `extract` on remaining conversations

## Configuration

Conversations are expected in:
```
3.RECURSOS/AI & ML/ChatGPT Conversations/
```

Analysis report saved to:
```
/Users/jose/obsidian/chatgpt_analysis_report.json
```

## Cost Estimate

Uses GPT-4o-mini which is inexpensive:
- ~$0.15 per 1M input tokens
- ~$0.60 per 1M output tokens
- Typical analysis of 100 conversations: ~$0.50
