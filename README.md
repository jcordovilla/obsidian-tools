# Obsidian Vault Management Tools

Python utilities for managing Obsidian vaults. All scripts use **dry-run mode by default** for safety.

## Installation

```bash
python3.13 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
brew install ffmpeg  # For transcribe_audio.py
```

**Note:** Requires Python 3.10-3.13 (not 3.14+ due to Whisper compatibility)

## Quick Start

```bash
# All scripts follow the same pattern:
python <script>.py --vault /path/to/vault              # Dry run (preview)
python <script>.py --vault /path/to/vault --no-dry-run # Execute
```

## Scripts by Category

### Vault Maintenance

| Script | Description |
|--------|-------------|
| `deduplicate.py` | Find/remove duplicate notes (content hash + similarity) |
| `deduplicate_attachments.py` | Find duplicate/orphaned attachments |
| `compress_images.py` | Compress images >500KB (max 2048px) |
| `compress_pdfs.py` | Compress PDFs >500KB with SSIM quality checks |
| `attachment_stats.py` | Analyze attachment sizes by file type |

### Backup & Sync

| Script | Description |
|--------|-------------|
| `sync_to_dropbox.py` | Sync vault to Dropbox (hash-based diff, handles deletions) |

### Content Enrichment

| Script | Description |
|--------|-------------|
| `chatgpt_enrichment.py` | LLM analysis/tagging of ChatGPT exports |
| `transcribe_audio.py` | Whisper transcription of audio in notes |
| `generate_chapter_diagrams.py` | AI diagrams for book chapter summaries |

### Tag & Metadata

| Script | Description |
|--------|-------------|
| `fix_language_tags.py` | Auto-detect language, set `lang/` tags |
| `escape_inline_hashtags.py` | Escape non-taxonomy hashtags |
| `normalize_curated_tags.py` | Map Evernote tags to vault taxonomy |
| `normalise_archivo.py` | Add frontmatter to archived notes |

### Validation

| Script | Description |
|--------|-------------|
| `validate_agents.py` | Validate Claude Code agents/skills YAML |

### Session Analysis

| Script | Description |
|--------|-------------|
| `extract_session_prompts.py` | Extract user-typed prompts from Claude Code session JSONL logs (filters tool results, system reminders, slash-command echoes); chronologically sorted, with substantive-prompt subset |

### Utilities

| Script | Description |
|--------|-------------|
| `obsidian_utils.py` | Shared module (file discovery, hashing, trash) |
| `delete_files_from_md.py` | Delete files listed in a markdown file |

## Detailed Usage

### sync_to_dropbox.py

Sync vault to Dropbox backup using content hashing to detect changes.

```bash
python sync_to_dropbox.py                           # Dry run
python sync_to_dropbox.py --no-dry-run              # Sync files
python sync_to_dropbox.py --no-dry-run --delete     # Sync + remove orphans from backup
```

### chatgpt_enrichment.py

LLM-powered ChatGPT conversation analysis. Requires `.env` with `OPENAI_API_KEY`.

```bash
python chatgpt_enrichment.py --vault /path analyze --limit 10    # Test on 10 files
python chatgpt_enrichment.py --vault /path analyze --provider ollama  # Use Ollama
python chatgpt_enrichment.py --vault /path cleanup --no-dry-run  # Archive low-value
```

### compress_pdfs.py

```bash
python compress_pdfs.py --vault /path              # Dry run
python compress_pdfs.py --vault /path --no-dry-run # Compress all
python compress_pdfs.py --file /path/to/file.pdf   # Single file
```

### transcribe_audio.py

```bash
python -u transcribe_audio.py --vault /path [--model base|small|medium|large]
```

### validate_agents.py

```bash
python validate_agents.py                    # Validate default vault
python validate_agents.py --vault /path      # Custom vault
python validate_agents.py --agents-only      # Skip skills
```

### extract_session_prompts.py

Extract user-typed prompts from Claude Code session `.jsonl` logs. Useful for self-reflection exercises (e.g. "what have I been asking Claude over the past month?").

```bash
# Default: JC vault project, output to /tmp/jc_prompts/
python extract_session_prompts.py

# List available projects under ~/.claude/projects/
python extract_session_prompts.py --list

# Different project, custom output, higher substantive-prompt threshold
python extract_session_prompts.py \
  --project -Users-jose-mylab-paco \
  --output ~/Desktop/paco_prompts \
  --threshold 200

# Date-filtered (UTC)
python extract_session_prompts.py --since 2026-04-01 --until 2026-04-19
```

**Outputs** (in the chosen output directory):

- `all_prompts.jsonl` — every user message that survived the noise filter, one JSON line per prompt with `{ts, sid, len, text}`
- `substantive_prompts.jsonl` — same shape, filtered to prompts ≥ `--threshold` chars (default 80)
- `substantive_prompts.txt` — human-readable plain text, separator-delimited, chronological

**Filters out:** tool results, `<system-reminder>`, `<command-name>` / `<local-command-*>`, `<bash-input/stdout/stderr>`, `[Request interrupted ...]`, `Caveat:`, session continuation markers, "Tool loaded.".

**Stats printed to stdout:** total prompts, total characters, length distribution, prompts per ISO week, substantive count.

### delete_files_from_md.py

```bash
python delete_files_from_md.py file.md                    # Extract paths (dry run)
python delete_files_from_md.py file.md --wiki-only        # Only [[...]] targets
python delete_files_from_md.py file.md --match-basenames  # Search by basename
python delete_files_from_md.py file.md --no-dry-run       # Delete files
```

## Subprojects

### merge-md-notes/

GUI tool (tkinter) for merging markdown files with separators for LLM processing.

```bash
python merge-md-notes/merge_md_files.py
```

### sample-md-notes/

CLI tool to randomly sample notes from a vault.

```bash
python sample-md-notes/obsidian_sampler.py 50 --vault /path --sample /output
```

## Shared Utilities (`obsidian_utils.py`)

- `format_size()` - Human-readable file sizes
- `get_all_notes()` / `get_all_attachments()` - File discovery
- `move_to_trash()` - Safe deletion with dry-run support
- `compute_file_hash()` - MD5 content hashing
- `extract_wiki_links()` - Parse Obsidian `[[links]]`

## Safety Features

- **Dry-run by default** - All scripts preview changes first
- **Trash, not delete** - Files moved to `.trash/` with timestamps
- **Quality checks** - SSIM verification for PDF compression
- **Backups** - Image originals saved to `Attachments/backup/`
