# Delete Files from Markdown Tool

Utility script that reads a markdown file containing a list of file paths and deletes those files. Useful for batch cleanup operations where you've exported a list of files to delete.

## Features

- Reads file paths from a markdown file
- Supports wikilink format `[[filename]]`
- Supports plain file paths
- Dry-run mode by default
- Optional limit on number of deletions

## Requirements

No additional dependencies (uses Python standard library).

## Usage

```bash
cd ~/mylab/obsidian-tools
source venv/bin/activate

# Dry run (preview what would be deleted)
python delete_files_from_md.py "/path/to/file-list.md"

# Actually delete files
python delete_files_from_md.py "/path/to/file-list.md" --yes

# Limit to first 10 files
python delete_files_from_md.py "/path/to/file-list.md" --yes --limit 10

# Extract targets from wikilinks only
python delete_files_from_md.py "/path/to/file-list.md" --wiki-only --base-dir /Users/jose/obsidian/JC
```

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `mdfile` | (required) | Path to markdown file with file list |
| `--yes` | false | Actually delete (default is dry-run) |
| `--limit` | 0 | Max files to delete (0 = no limit) |
| `--base-dir` | md file's dir | Base directory for relative paths |
| `--wiki-only` | false | Only extract `[[...]]` wikilinks |
| `--prefer-wiki` | false | Prefer wikilink targets over plain paths |

## Input Format

The markdown file can contain file paths in various formats:

```markdown
# Files to Delete

## Orphaned Attachments
- [[old-image.png]]
- [[unused-document.pdf]]

## By Path
/Users/jose/obsidian/JC/Attachments/screenshot.png
Attachments/another-file.jpg
```

## Use Cases

- Delete orphaned files identified by another tool
- Batch cleanup from exported Obsidian search results
- Process output from Obsidian's "Show orphaned files" plugin
- Delete files listed in a review/triage note
