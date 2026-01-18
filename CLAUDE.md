# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## Overview

Python utilities for managing Obsidian vaults. All scripts operate on a vault path (default: `/Users/jose/obsidian/JC`) and use **dry-run mode by default** for safety.

## Development Setup

```bash
python3.13 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
brew install ffmpeg  # Required for transcribe_audio.py
```

**Python Version**: 3.10-3.13 (NOT 3.14+ due to Whisper compatibility)

## Running Scripts

All scripts follow the same pattern:
```bash
python <script>.py --vault /path/to/vault              # Dry run (safe preview)
python <script>.py --vault /path/to/vault --no-dry-run # Actually modify files
```

## Script Categories

### Vault Maintenance

| Script | Purpose |
|--------|---------|
| `deduplicate.py` | Find and remove duplicate notes (by content hash + similarity) |
| `deduplicate_attachments.py` | Find duplicate/orphaned attachments |
| `compress_images.py` | Compress images >500KB while maintaining quality |
| `compress_pdfs.py` | Compress PDFs >500KB with SSIM quality checks |
| `attachment_stats.py` | Analyze attachment sizes by file type |

### Backup & Sync

| Script | Purpose |
|--------|---------|
| `sync_to_dropbox.py` | Sync vault to Dropbox backup (hash-based diff, handles deletions) |

### Content Enrichment

| Script | Purpose |
|--------|---------|
| `chatgpt_enrichment.py` | LLM-powered quality analysis and tagging of ChatGPT exports |
| `transcribe_audio.py` | Whisper transcription of audio files in notes |
| `generate_chapter_diagrams.py` | Generate AI diagrams for book chapter summaries |

### Tag & Metadata Normalization

| Script | Purpose |
|--------|---------|
| `fix_language_tags.py` | Auto-detect note language and set `lang/` tags |
| `escape_inline_hashtags.py` | Escape non-taxonomy hashtags (e.g., Discord channels) |
| `normalize_curated_tags.py` | Map Evernote tags to vault taxonomy |
| `normalise_archivo.py` | Add frontmatter to archived notes |

### Validation

| Script | Purpose |
|--------|---------|
| `validate_agents.py` | Validate Claude Code agents/skills YAML format |

### ChatGPT Pipeline Helpers

These support `chatgpt_enrichment.py` workflow:

| Script | Purpose |
|--------|---------|
| `analyze_chat_stats.py` | Calculate stats for sampling strategy |
| `delete_low_value.py` | Delete conversations marked low-value |
| `reanalyze_failed.py` | Retry failed LLM analyses with higher token limits |
| `triage_reviews.py` | GUI for manual keep/archive decisions |

### Utilities

| Script | Purpose |
|--------|---------|
| `obsidian_utils.py` | Shared module (file discovery, hashing, trash handling) |
| `delete_files_from_md.py` | Delete files listed in a markdown file |

## Architecture

### Shared Module: `obsidian_utils.py`

Common utilities to reduce duplication:
- `format_size()` - Human-readable file sizes
- `get_all_notes()` / `get_all_attachments()` - File discovery (skips `.trash`, `.obsidian`)
- `move_to_trash()` - Safe deletion with dry-run support
- `compute_file_hash()` - MD5 hashing
- `extract_wiki_links()` / `find_attachment_references()` - Obsidian link parsing

### Vault Structure Assumptions

Scripts expect this standard Obsidian layout:
- `Attachments/` - Images, PDFs, audio files
- `.trash/` - Deleted files (timestamped subfolders)
- Markdown notes anywhere in vault

### Quality Safeguards

- `compress_pdfs.py` uses SSIM to verify compression quality (default threshold: 0.92)
- `compress_images.py` backs up originals to `Attachments/backup/`
- `deduplicate.py` uses content hash + difflib similarity (95% threshold)

## Key Dependencies

| Package | Used By |
|---------|---------|
| `openai-whisper` | transcribe_audio.py |
| `pillow` | compress_images.py |
| `pymupdf` + `numpy` | compress_pdfs.py |
| `openai` + `python-dotenv` | chatgpt_enrichment.py |
| `langdetect` | fix_language_tags.py |

## Subprojects

### merge-md-notes/

GUI tool (tkinter) for merging multiple markdown files with separators for LLM processing.

### sample-md-notes/

CLI tool to randomly sample n notes from a vault into a single directory.
