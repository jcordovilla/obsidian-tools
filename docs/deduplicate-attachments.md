# Attachment Deduplication Tool

Finds duplicate and orphaned attachments in the vault:
- **Duplicates**: Files with identical content (detected by hash)
- **Orphans**: Attachments not referenced by any note

## Features

- Hash-based duplicate detection (finds identical files regardless of name)
- Orphan detection (attachments not linked from any note)
- Optional thorough orphan verification
- Dry-run mode by default

## Requirements

No additional dependencies (uses Python standard library).

## Usage

```bash
cd ~/mylab/obsidian-tools
source venv/bin/activate

# Dry run (find duplicates and orphans)
python deduplicate_attachments.py --vault /Users/jose/obsidian/JC

# Thorough orphan check (slower but more accurate)
python deduplicate_attachments.py --vault /Users/jose/obsidian/JC --verify-orphans

# Actually remove duplicates/orphans
python deduplicate_attachments.py --vault /Users/jose/obsidian/JC --no-dry-run
```

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `--vault` | `/Users/jose/obsidian/JC` | Path to Obsidian vault |
| `--no-dry-run` | false | Actually move files to trash |
| `--verify-orphans` | false | Double-check orphans by searching all notes |

## How It Works

### Duplicate Detection
1. Calculates SHA-256 hash for each attachment
2. Groups files with identical hashes
3. Keeps one copy, marks others as duplicates

### Orphan Detection
1. Scans all markdown files for attachment references
2. Checks wikilinks: `![[image.png]]`
3. Checks markdown links: `![](image.png)`
4. Flags attachments with no references

## Output

```
Duplicate Attachments:
  Hash abc123... (3 files, keeping: image.png)
    - image copy.png (duplicate)
    - image 1.png (duplicate)

Orphaned Attachments:
  - old_screenshot.png (0 references)
  - unused_diagram.pdf (0 references)

Summary:
  Duplicates: 15 files (45 MB)
  Orphans: 23 files (12 MB)
  Potential savings: 57 MB
```

## Safety

- Dry-run by default
- Moves to vault trash (recoverable)
- `--verify-orphans` provides extra safety for orphan detection
