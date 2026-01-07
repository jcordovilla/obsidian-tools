# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

A collection of Python utilities for managing Obsidian vaults. All scripts operate on a vault path (default: `/Users/jose/obsidian/JC`) and use dry-run mode by default for safety.

## Development Setup

```bash
python3.13 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
brew install ffmpeg  # Required for transcribe_audio.py
```

**Python Version**: Requires 3.10-3.13 (NOT 3.14+ due to Whisper compatibility)

## Key Dependencies

- `openai-whisper` - Audio transcription (transcribe_audio.py)
- `pillow` - Image compression (compress_images.py)
- `pymupdf` + `numpy` - PDF compression with SSIM quality checks (compress_pdfs.py)
- `openai` + `python-dotenv` - LLM analysis (chatgpt_enrichment.py requires `.env` with `OPENAI_API_KEY`)

## Running Scripts

All scripts follow the same pattern:
```bash
python <script>.py --vault /path/to/vault              # Dry run (safe preview)
python <script>.py --vault /path/to/vault --no-dry-run # Actually modify files
```

## Architecture

### Shared Module: `obsidian_utils.py`
Common utilities consolidated here to reduce duplication:
- `format_size()` - Human-readable file sizes
- `get_all_notes()` / `get_all_attachments()` - File discovery (skips `.trash`, `.obsidian`)
- `move_to_trash()` - Safe deletion with dry-run support and timestamped folders
- `compute_file_hash()` - MD5 hashing for deduplication
- `extract_wiki_links()` / `find_attachment_references()` - Obsidian link parsing
- `ObsidianToolBase` - Optional base class for CLI tools

When adding new scripts, import from `obsidian_utils` rather than duplicating these patterns.

### Vault Structure Assumptions
Scripts expect this standard Obsidian layout:
- `Attachments/` - Images, PDFs, audio files
- `.trash/` - Deleted files moved here (timestamped subfolders)
- Markdown notes anywhere in vault

### Reference Detection
Scripts parse both Obsidian wiki-links and markdown syntax:
- `![[filename]]` or `[[filename]]` - Obsidian style
- `![alt](Attachments/file.png)` - Standard markdown

### Quality Safeguards
- `compress_pdfs.py` uses SSIM (Structural Similarity Index) to verify compression doesn't degrade quality below threshold (default 0.92)
- `compress_images.py` backs up originals to `Attachments/backup/`
- `deduplicate.py` uses content hash + difflib similarity (95% threshold) for duplicate detection

## Script-Specific Notes

### chatgpt_enrichment.py
Expects ChatGPT conversations in `3.RECURSOS/AI & ML/ChatGPT Conversations/`. Archives low-value content to `4.ARCHIVO/`. Uses OpenAI API by default, can switch to Ollama with `--provider ollama`.

### transcribe_audio.py
Runs without dry-run mode. Processes `.m4a`, `.mp3`, `.wav` files, appends transcript to note, moves audio to trash. Model sizes: tiny/base/small/medium/large (base is default).

### delete_files_from_md.py
Parses markdown files for file paths (wiki-links, backticks, bare paths). Key flags:
- `--wiki-only` - Only extract `[[...]]` targets
- `--base-dir` - Resolve relative paths against this directory
- `--match-basenames` - Search recursively for files by basename

## Subprojects

### merge-md-notes/
GUI tool (tkinter) for merging multiple markdown files with clear separators for LLM processing.

### sample-md-notes/
CLI tool to randomly sample n notes from a vault into a single directory (handles filename conflicts).
