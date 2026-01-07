# Note Deduplication Tool

Finds and removes duplicate notes with numeric suffixes (e.g., "Note 1.md", "Note 2.md") that often result from sync conflicts or copy operations.

## Features

- Detects notes with numeric suffixes (e.g., "Meeting Notes 1.md")
- Compares content to find true duplicates
- Moves duplicates to vault trash
- Dry-run mode by default for safety

## Requirements

No additional dependencies (uses Python standard library).

## Usage

```bash
cd ~/mylab/obsidian-tools
source venv/bin/activate

# Dry run (preview duplicates)
python deduplicate.py --vault /Users/jose/obsidian/JC

# Actually remove duplicates
python deduplicate.py --vault /Users/jose/obsidian/JC --no-dry-run
```

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `--vault` | `/Users/jose/obsidian/JC` | Path to Obsidian vault |
| `--no-dry-run` | false | Actually move duplicates to trash |

## How It Works

1. Scans vault for notes with numeric suffixes (pattern: `name 1.md`, `name 2.md`)
2. Groups notes by base name
3. Compares content using hashing and diff
4. Identifies which version to keep (usually the original without suffix)
5. Moves duplicates to `.trash/`

## Detection Patterns

Matches filenames like:
- `Meeting Notes 1.md`
- `Project Plan 2.md`
- `Ideas 3.md`

Does NOT match:
- `Chapter 1.md` (intentional numbering)
- `2024-01-15.md` (date-based names)

## Safety

- Always runs in dry-run mode first
- Moves to vault trash (recoverable)
- Shows diff comparison before deletion
