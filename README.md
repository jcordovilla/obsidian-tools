# Obsidian Vault Management Tools

Python scripts for managing Obsidian vaults.

## Installation

```bash
python3.13 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
brew install ffmpeg  # For transcribe_audio.py
```

**Note:** Requires Python 3.10-3.13 (not 3.14+)

## Scripts

### `deduplicate.py`
Remove duplicate notes (with numeric suffixes). Moves duplicates to trash.

```bash
python deduplicate.py --vault /path/to/vault              # Dry run
python deduplicate.py --vault /path/to/vault --no-dry-run # Delete
```

### `deduplicate_attachments.py`
Remove duplicate and orphaned attachments.

```bash
python deduplicate_attachments.py --vault /path/to/vault              # Dry run
python deduplicate_attachments.py --vault /path/to/vault --no-dry-run # Delete
```

### `transcribe_audio.py`
Transcribe audio files in notes using local Whisper model. Appends transcript and moves audio to trash.

```bash
python -u transcribe_audio.py --vault /path/to/vault [--model base|small|medium|large]
```

### `compress_images.py`
Compress images >500KB in Attachments folder (max 2048px, maintains quality).

```bash
python compress_images.py --vault /path/to/vault              # Dry run
python compress_images.py --vault /path/to/vault --no-dry-run # Compress
```

### `compress_pdfs.py`
Compress PDFs >500KB with SSIM quality verification. Backs up originals to `PDF_backups/`.

```bash
python compress_pdfs.py --vault /path/to/vault              # Dry run
python compress_pdfs.py --vault /path/to/vault --no-dry-run # Compress
python compress_pdfs.py --file /path/to/file.pdf            # Single file mode
```

### `attachment_stats.py`
Print detailed statistics about Obsidian attachments, including filename pattern analysis.

```bash
python attachment_stats.py --vault /path/to/vault
python attachment_stats.py --vault /path/to/vault --analyze-patterns
```

### `delete_files_from_md.py`
Extract file paths from markdown files (wiki-links, backticks, bare paths) and optionally delete them.

```bash
python delete_files_from_md.py file.md                           # Extract paths (dry run)
python delete_files_from_md.py file.md --wiki-only               # Only [[...]] targets
python delete_files_from_md.py file.md --base-dir /path/to/base  # Resolve relative paths
python delete_files_from_md.py file.md --match-basenames         # Search recursively by basename
python delete_files_from_md.py file.md --no-dry-run              # Actually delete
```

### `chatgpt_enrichment.py`
LLM-powered ChatGPT conversation analysis and cleanup using OpenAI API.

```bash
# Analyze conversations (dry run, test on 10 files)
python chatgpt_enrichment.py --vault /path/to/vault analyze --limit 10

# Use Ollama instead of OpenAI
python chatgpt_enrichment.py --vault /path/to/vault analyze --provider ollama

# Archive low-value conversations based on analysis
python chatgpt_enrichment.py --vault /path/to/vault cleanup              # Dry run
python chatgpt_enrichment.py --vault /path/to/vault cleanup --no-dry-run # Actually archive
```

**Prerequisites**: Requires OpenAI API key in `.env` file (`OPENAI_API_KEY=sk-...`), or [Ollama](https://ollama.ai) for local models.

## Subprojects

### `merge-md-notes/`
GUI tool (tkinter) for merging multiple markdown files with clear separators for LLM processing.

```bash
python merge-md-notes/merge_md_files.py
```

### `sample-md-notes/`
CLI tool to randomly sample n notes from a vault into a single directory.

```bash
python sample-md-notes/obsidian_sampler.py 50 --vault /path/to/vault --sample /path/to/output
```

## Shared Utilities

### `obsidian_utils.py`
Common utilities shared across scripts:
- `format_size()` - Human-readable file sizes
- `get_all_notes()` / `get_all_attachments()` - File discovery
- `move_to_trash()` - Safe deletion with dry-run support
- `compute_file_hash()` - Content hashing for deduplication
- `extract_wiki_links()` / `find_attachment_references()` - Obsidian link parsing

## Safety

- All scripts use dry-run mode by default
- Files are moved to trash (not permanently deleted)
- Timestamped trash folders for easy recovery
