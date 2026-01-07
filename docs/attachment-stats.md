# Attachment Statistics Tool

Analyzes and reports statistics about attachments in the Obsidian vault, including size breakdown by file type.

## Features

- Counts files by type (PDF, images, etc.)
- Calculates total size per file type
- Identifies largest files
- Analyzes filename patterns (useful for identifying screenshot naming conventions)

## Requirements

No additional dependencies (uses Python standard library).

## Usage

```bash
cd ~/mylab/obsidian-tools
source venv/bin/activate

# Basic statistics
python attachment_stats.py --vault /Users/jose/obsidian/JC

# Include pattern analysis
python attachment_stats.py --vault /Users/jose/obsidian/JC --analyze-patterns
```

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `--vault` | `/Users/jose/obsidian/JC` | Path to Obsidian vault |
| `--analyze-patterns` | false | Analyze filename patterns |

## Output Example

```
Attachment Statistics for /Users/jose/obsidian/JC
================================================

By File Type:
  PDF:  478 MB (342 files)
  PNG:  129 MB (762 files)
  JPG:   45 MB (234 files)
  ...

Largest Files:
  1. document.pdf (47 MB)
  2. report.pdf (44 MB)
  ...

Total: 652 MB (1,338 files)
```

## Use Cases

- Audit vault size before cleanup
- Identify which file types consume most space
- Find candidates for compression or removal
- Analyze screenshot naming patterns to identify web clipper artifacts
