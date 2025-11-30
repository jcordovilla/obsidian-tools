#!/usr/bin/env python3
"""
Obsidian Note Sampler

A Python application that samples n notes from an Obsidian vault and stores them
in a sample directory, preserving the folder structure.
"""

import os
import shutil
import random
import argparse
from pathlib import Path
from typing import List, Tuple
import sys


class ObsidianSampler:
    def __init__(self, vault_path: str, sample_path: str):
        """
        Initialize the Obsidian sampler.
        
        Args:
            vault_path: Path to the Obsidian vault
            sample_path: Path where sampled notes will be stored
        """
        self.vault_path = Path(vault_path)
        self.sample_path = Path(sample_path)
        
        if not self.vault_path.exists():
            raise FileNotFoundError(f"Vault path does not exist: {vault_path}")
    
    def discover_notes(self) -> List[Path]:
        """
        Discover all markdown notes in the vault.
        
        Returns:
            List of Path objects for all markdown files
        """
        notes = []
        
        # Walk through all directories in the vault
        for root, dirs, files in os.walk(self.vault_path):
            # Skip certain directories that might not contain actual notes
            skip_dirs = {'attachments', 'backup', 'logs', 'reports'}
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            
            for file in files:
                if file.endswith('.md'):
                    notes.append(Path(root) / file)
        
        return notes
    
    def filter_notes(self, notes: List[Path]) -> List[Path]:
        """
        Filter out notes that might not be actual content notes.
        
        Args:
            notes: List of note paths
            
        Returns:
            Filtered list of note paths
        """
        filtered_notes = []
        
        for note in notes:
            # Skip very small files (likely empty or template files)
            if note.stat().st_size < 100:  # Less than 100 bytes
                continue
            
            # Skip files that are likely system files
            if note.name.lower() in {'readme.md', 'index.md', '.obsidian'}:
                continue
            
            filtered_notes.append(note)
        
        return filtered_notes
    
    def sample_notes(self, notes: List[Path], n: int) -> List[Path]:
        """
        Randomly sample n notes from the list.
        
        Args:
            notes: List of note paths
            n: Number of notes to sample
            
        Returns:
            List of sampled note paths
        """
        if n >= len(notes):
            print(f"Requested {n} notes, but only {len(notes)} available. Returning all notes.")
            return notes
        
        return random.sample(notes, n)
    
    def copy_notes(self, sampled_notes: List[Path]) -> None:
        """
        Copy sampled notes to the sample directory in a single folder.
        
        Args:
            sampled_notes: List of note paths to copy
        """
        # Create sample directory if it doesn't exist
        self.sample_path.mkdir(parents=True, exist_ok=True)
        
        copied_count = 0
        
        for note in sampled_notes:
            # Use just the filename for the destination
            dest_path = self.sample_path / note.name
            
            # Handle filename conflicts by adding a number suffix
            counter = 1
            original_dest = dest_path
            while dest_path.exists():
                stem = original_dest.stem
                suffix = original_dest.suffix
                dest_path = self.sample_path / f"{stem}_{counter}{suffix}"
                counter += 1
            
            # Copy the file
            try:
                shutil.copy2(note, dest_path)
                print(f"Copied: {note.name} -> {dest_path.name}")
                copied_count += 1
            except Exception as e:
                print(f"Error copying {note}: {e}")
        
        print(f"\nSuccessfully copied {copied_count} notes to {self.sample_path}")
    
    def run(self, n: int) -> None:
        """
        Run the complete sampling process.
        
        Args:
            n: Number of notes to sample
        """
        print(f"Discovering notes in {self.vault_path}...")
        all_notes = self.discover_notes()
        print(f"Found {len(all_notes)} markdown files")
        
        print("Filtering notes...")
        filtered_notes = self.filter_notes(all_notes)
        print(f"After filtering: {len(filtered_notes)} notes")
        
        if not filtered_notes:
            print("No notes found to sample!")
            return
        
        print(f"Sampling {n} notes...")
        sampled_notes = self.sample_notes(filtered_notes, n)
        
        print("Copying sampled notes...")
        self.copy_notes(sampled_notes)
        
        print("\nSampling complete!")


def main():
    """Main entry point for the application."""
    parser = argparse.ArgumentParser(
        description="Sample notes from an Obsidian vault",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python obsidian_sampler.py 10
  python obsidian_sampler.py 50 --vault /path/to/vault --sample /path/to/sample
        """
    )
    
    parser.add_argument(
        'n',
        type=int,
        help='Number of notes to sample'
    )
    
    parser.add_argument(
        '--vault',
        default='/Users/jose/Documents/Obsidian/Ever-output',
        help='Path to Obsidian vault (default: /Users/jose/Documents/Obsidian/Ever-output)'
    )
    
    parser.add_argument(
        '--sample',
        default='/Users/jose/Documents/Obsidian/Ever-sample',
        help='Path to sample directory (default: /Users/jose/Documents/Obsidian/Ever-sample)'
    )
    
    args = parser.parse_args()
    
    if args.n <= 0:
        print("Error: Number of notes must be positive")
        sys.exit(1)
    
    try:
        sampler = ObsidianSampler(args.vault, args.sample)
        sampler.run(args.n)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
