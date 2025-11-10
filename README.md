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
Compress PDFs >500KB in Attachments folder.

```bash
python compress_pdfs.py --vault /path/to/vault              # Dry run
python compress_pdfs.py --vault /path/to/vault --no-dry-run # Compress
```

### `attachment_stats.py`
Print detailed statistics about Obsidian attachments, including filename pattern analysis.

```bash
# Basic statistics
python attachment_stats.py --vault /path/to/vault

# Include filename pattern analysis (discovers screenshot patterns)
python attachment_stats.py --vault /path/to/vault --analyze-patterns
```

### `triage_boilerplate_attachments.py`
Identify notes with many boilerplate attachments (from web clippers) and tag them for review. After manual review, clean up by removing attachments and references.

**Automatically analyzes your vault to discover screenshot patterns** before scanning, improving detection accuracy.

```bash
# Scan and tag notes with boilerplate attachments (dry run, with pattern analysis)
python triage_boilerplate_attachments.py --vault /path/to/vault scan

# Scan and tag notes (actually tag them)
python triage_boilerplate_attachments.py --vault /path/to/vault scan --no-dry-run

# Clean triaged notes (remove boilerplate attachments and references)
python triage_boilerplate_attachments.py --vault /path/to/vault clean --no-dry-run

# Use custom minimum attachment threshold
python triage_boilerplate_attachments.py --vault /path/to/vault scan --min-attachments 10

# Skip pattern analysis (use default patterns only)
python triage_boilerplate_attachments.py --vault /path/to/vault scan --skip-pattern-analysis
```

## Safety

- All scripts use dry-run mode by default
- Files are moved to trash (not permanently deleted)
- Timestamped trash folders for easy recovery
