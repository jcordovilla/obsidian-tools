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

## Safety

- All scripts use dry-run mode by default
- Files are moved to trash (not permanently deleted)
- Timestamped trash folders for easy recovery
