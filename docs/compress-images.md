# Image Compression Tool

Compresses images (PNG, JPG, etc.) in the Obsidian vault's Attachments folder while maintaining screen-readable quality.

## Features

- Scans Attachments folder for large images (>500KB by default)
- Compresses while preserving reasonable screen resolution
- Updates image references in notes when filenames change
- Dry-run mode by default for safety
- Backs up originals before compression

## Requirements

```bash
pip install pillow
```

## Usage

```bash
cd ~/mylab/obsidian-tools
source venv/bin/activate

# Dry run (preview only)
python compress_images.py --vault /Users/jose/obsidian/JC

# Custom threshold (e.g., 1MB)
python compress_images.py --vault /Users/jose/obsidian/JC --threshold 1024

# Actually compress
python compress_images.py --vault /Users/jose/obsidian/JC --no-dry-run
```

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `--vault` | `/Users/jose/obsidian/JC` | Path to Obsidian vault |
| `--threshold` | 500 | Size threshold in KB |
| `--no-dry-run` | false | Actually apply compression |

## Supported Formats

- JPEG/JPG
- PNG
- GIF
- BMP
- TIFF
- WebP
- HEIC/HEIF

## How It Works

1. Scans Attachments folder for images above threshold
2. Compresses each image (reduces dimensions if needed, applies JPEG compression)
3. Backs up originals to `Attachments/backup/`
4. Updates all note references if filename changes
5. Reports space saved

## Notes

- Skips images in the backup folder
- Preserves image aspect ratios
- Updates wikilinks and markdown image references in notes
