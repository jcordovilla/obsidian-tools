# Obsidian Note Sampler

A Python application that randomly samples n notes from an Obsidian vault and stores them in a single sample directory.

## Features

- **Random Sampling**: Randomly selects n notes from your Obsidian vault
- **Single Folder Output**: All sampled notes are saved in a single folder for easy access
- **Smart Filtering**: Automatically filters out system files, empty notes, and non-content files
- **Command Line Interface**: Easy-to-use CLI with customizable paths
- **No Dependencies**: Uses only Python standard library

## Usage

### Basic Usage

```bash
python obsidian_sampler.py 10
```

This will sample 10 random notes from the default vault (`/Users/jose/Documents/Obsidian/Ever-output`) and store them in the default sample directory (`/Users/jose/Documents/Obsidian/Ever-sample`).

### Custom Paths

```bash
python obsidian_sampler.py 25 --vault /path/to/your/vault --sample /path/to/sample/directory
```

### Command Line Options

- `n`: Number of notes to sample (required)
- `--vault`: Path to Obsidian vault (default: `/Users/jose/Documents/Obsidian/Ever-output`)
- `--sample`: Path to sample directory (default: `/Users/jose/Documents/Obsidian/Ever-sample`)

## Requirements

- Python 3.6 or higher
- No external dependencies (uses only standard library)

## How It Works

1. **Discovery**: Recursively scans the vault directory for all `.md` files
2. **Filtering**: Removes system files, empty notes, and non-content files
3. **Sampling**: Randomly selects the requested number of notes
4. **Copying**: Copies selected notes to the sample directory in a single folder

## Examples

```bash
# Sample 5 notes
python obsidian_sampler.py 5

# Sample 50 notes with custom paths
python obsidian_sampler.py 50 --vault ~/MyVault --sample ~/MySample

# Sample all available notes (if you request more than available)
python obsidian_sampler.py 1000
```

## Notes

- The application will create the sample directory if it doesn't exist
- If you request more notes than available, it will return all available notes
- The random sampling ensures different results each time you run the application
- All notes are saved in a single folder for easy access and management
- Filename conflicts are automatically resolved by adding number suffixes
