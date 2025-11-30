# Merge Markdown Files

A simple GUI application that merges multiple Markdown files into a single document with clear separators for easy LLM processing.

## Features

- **GUI Interface**: Easy-to-use file selection dialog
- **Batch Processing**: Select and merge multiple `.md` files at once
- **Clear Separators**: Each source file is clearly marked with headers and boundaries
- **LLM-Friendly**: Output format is optimized for AI/LLM processing
- **Cross-Platform**: Works on macOS, Windows, and Linux
- **Standalone Executable**: No Python installation required

## How It Works

1. **File Selection**: Choose multiple Markdown files through a user-friendly dialog
2. **Content Merging**: Combines all files with clear separators between each source
3. **Output**: Saves the merged content as `merged.md` in the same directory as your first selected file

## Output Format

Each source file in the merged document includes:

```
================================================================================
SOURCE FILE 1: filename.md
File Path: /full/path/to/filename.md
================================================================================

[Original file content]

================================================================================
END OF FILE: filename.md
================================================================================
```

This format makes it easy for LLMs to:
- Identify individual file boundaries
- Extract file metadata (name, path, sequence)
- Process content from specific source files
- Understand the document structure

## Usage

### Option 1: Run the Executable (Recommended)
1. Double-click `Merge Markdown Files` or `Merge Markdown Files.app`
2. Select multiple `.md` files in the file dialog
3. Click "Open"
4. Find your merged file as `merged.md` in the same folder as your first selected file

### Option 2: Run from Source
```bash
# Install dependencies (if any)
pip install -r requirements.txt

# Run the script
python merge_md_files.py
```

## Requirements

- **Python 3.6+** (for source code)
- **No external dependencies** - uses only Python standard library
- **Tkinter** (included with Python)

## File Structure

```
merge-md-notes/
├── merge_md_files.py          # Main Python script
├── requirements.txt           # Dependencies (none required)
├── Merge Markdown Files       # Standalone executable
├── Merge Markdown Files.app   # macOS application bundle
└── README.md                  # This file
```

## Building the Executable

To rebuild the executable from source:

```bash
# Install PyInstaller
pip install pyinstaller

# Build the executable
pyinstaller --onefile --windowed --name "Merge Markdown Files" merge_md_files.py
```

## Use Cases

- **Note Consolidation**: Merge multiple note files into a single document
- **Documentation**: Combine multiple documentation files
- **Research**: Consolidate research notes from different sources
- **LLM Processing**: Prepare documents for AI analysis with clear file boundaries
- **Content Management**: Organize scattered markdown content

## License

This project is open source and available under the MIT License.
