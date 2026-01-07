# Audio Transcription Tool

Transcribes audio files embedded in Obsidian notes using OpenAI's Whisper model (runs locally). Appends transcriptions to the notes and optionally removes the audio files.

## Features

- Finds audio files (m4a, mp3, wav) embedded in notes
- Transcribes using local Whisper model (no API costs)
- Appends transcription directly to the note
- Multiple model sizes for speed/accuracy tradeoff
- Moves processed audio to trash (optional)

## Requirements

```bash
pip install openai-whisper
```

Note: First run downloads the Whisper model (~140MB for base).

## Usage

```bash
cd ~/mylab/obsidian-tools
source venv/bin/activate

# Transcribe with base model (default)
python transcribe_audio.py --vault /Users/jose/obsidian/JC

# Use smaller/faster model
python transcribe_audio.py --vault /Users/jose/obsidian/JC --model tiny

# Use larger/more accurate model
python transcribe_audio.py --vault /Users/jose/obsidian/JC --model medium
```

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `--vault` | `/Users/jose/obsidian/JC` | Path to Obsidian vault |
| `--model` | `base` | Whisper model size |

## Model Sizes

| Model | Size | Speed | Accuracy | Best For |
|-------|------|-------|----------|----------|
| `tiny` | 39MB | Fastest | Lower | Quick notes, clear audio |
| `base` | 142MB | Fast | Good | General use (recommended) |
| `small` | 466MB | Medium | Better | Important recordings |
| `medium` | 1.5GB | Slow | High | Professional transcription |
| `large` | 2.9GB | Slowest | Best | Maximum accuracy needed |

## Supported Formats

- M4A (iPhone voice memos)
- MP3
- WAV

## How It Works

1. Scans notes for embedded audio links: `![[recording.m4a]]`
2. Extracts and transcribes each audio file
3. Appends transcription to the note under a `## Transcription` heading
4. Moves audio file to trash (space savings)

## Output Example

In your note:
```markdown
## Meeting Notes

![[meeting-audio.m4a]]

## Transcription

So we discussed the project timeline and agreed that...
```

## Use Cases

- Voice memos captured on iPhone
- Meeting recordings
- Audio notes from field work
- Podcast notes
