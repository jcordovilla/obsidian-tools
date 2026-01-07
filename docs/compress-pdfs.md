# PDF Compression Tool

Compresses PDF files in an Obsidian vault while preserving visual quality. Uses SSIM (Structural Similarity Index) to ensure compressed files maintain acceptable quality before applying changes.

## Features

- **Quality-aware compression**: Rejects compression if visual quality drops below threshold
- **Interactive confirmation**: Shows size/quality summary and asks before applying
- **Safe file operations**: Rollback mechanism if file swap fails
- **External backups**: Original files backed up outside the vault
- **Single file or batch mode**: Process one PDF or scan entire vault

## Requirements

```bash
pip install pymupdf pillow numpy
```

## Usage

### Single File Mode (Recommended)

Process one PDF with interactive confirmation:

```bash
cd ~/mylab/obsidian-tools
source venv/bin/activate
python compress_pdfs.py --file "/path/to/file.pdf"
```

### Batch Mode

Scan vault for large PDFs:

```bash
# Dry run (preview only)
python compress_pdfs.py --vault /Users/jose/obsidian/JC --threshold 5000

# With confirmation per file
python compress_pdfs.py --vault /Users/jose/obsidian/JC --threshold 5000 --no-dry-run
```

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `--file` | - | Process a single PDF file (ignores --threshold) |
| `--vault` | `/Users/jose/obsidian/JC` | Path to Obsidian vault |
| `--threshold` | 500 | Size threshold in KB for batch mode |
| `--quality` | 0.92 | SSIM quality threshold (0-1). Higher = stricter |
| `--no-dry-run` | false | Actually apply compression (batch mode) |

## Quality Threshold Guide

| SSIM Score | Meaning |
|------------|---------|
| 1.0 | Identical |
| 0.95+ | Imperceptible difference |
| 0.92+ | Very minor, acceptable (default) |
| 0.85-0.92 | Noticeable but usable |
| <0.85 | Significant quality loss |

## How It Works

1. **Compression**: Reduces embedded image DPI and applies JPEG compression
2. **Quality Check**: Renders sample pages (first, middle, last) and compares via SSIM
3. **Confirmation**: Shows summary with size reduction and quality score
4. **Safe Swap**:
   - Moves original to backup folder
   - Moves compressed to original location
   - Rolls back if any step fails

## Output Example

```
📚 Obsidian PDF Compression Tool (Single File Mode)
File: /path/to/document.pdf
Quality threshold: 0.92
Backup location: /Users/jose/mylab/obsidian-tools/PDF_backups
============================================================

  📄 Original size: 46.68 MB
  📊 Pages: 117
  📝 Detected: Text-based PDF (image-to-text ratio: 0.0005)
  🖼️  Found 142 image(s), compressed 141, skipped 1
  📦 Compressed size: 11.48 MB (75.4% reduction)
  🔍 Checking quality (threshold: 0.92)...
  📊 Quality score (SSIM): 0.9680

  --------------------------------------------------
  📋 SUMMARY:
     Original:   46.68 MB
     Compressed: 11.48 MB (75.4% smaller)
     Quality:    0.9680 (threshold: 0.92) ✓
     Savings:    35.20 MB
  --------------------------------------------------

  Apply compression? (yes/no): yes
  ✅ Success: Saved 35.20 MB
  🔒 Backup saved: /Users/jose/mylab/obsidian-tools/PDF_backups/document.pdf

============================================================
📊 FINAL RESULT
============================================================
  ✅ Compression applied successfully
  • Space saved: 35.20 MB
  • Original backed up to: .../PDF_backups
============================================================
```

## Backup Location

Original files are moved to:
```
~/mylab/obsidian-tools/PDF_backups/
```

This keeps backups outside the Obsidian vault to avoid bloating vault size.

## PDF Type Detection

The tool automatically detects:

- **Text-based PDFs**: Standard settings (150 DPI, quality 50)
- **Scanned PDFs**: More aggressive settings (120 DPI, quality 60, grayscale conversion)

Detection is based on image-to-text ratio across sampled pages.

## Compression Settings

| PDF Type | Target DPI | JPEG Quality | Max Dimension |
|----------|------------|--------------|---------------|
| Text-based | 150 | 50 | 1024px |
| Scanned | 120 | 60 | 1600px |

## Error Handling

- **Quality below threshold**: Compression rejected, original unchanged
- **Compression increases size**: Original kept, no changes
- **File swap failure**: Automatic rollback to original
- **Any exception**: Temp files cleaned up, original preserved
