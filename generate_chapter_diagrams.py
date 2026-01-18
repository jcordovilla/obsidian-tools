#!/usr/bin/env python3
"""
Chapter Diagram Generator

Scans chapter-processed books in INBOX and generates AI infographic diagrams
for each chapter's summary section using Nano Banana Pro (Gemini 3 Pro Image).

Usage:
    # Dry run (preview only)
    python generate_chapter_diagrams.py

    # Actually generate diagrams
    python generate_chapter_diagrams.py --no-dry-run

    # Process specific book
    python generate_chapter_diagrams.py --book "Principles of Project Finance"

    # Process specific chapter
    python generate_chapter_diagrams.py --chapter "Ch09 - Risk Analysis"
"""

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


class ChapterDiagramGenerator:
    """Generate AI diagrams for book chapter notes."""

    VAULT_PATH = Path("/Users/jose/obsidian/JC")
    INBOX_PATH = VAULT_PATH / "0.INBOX"
    ATTACHMENTS_PATH = VAULT_PATH / "Attachments"
    DIAGRAM_GEN_PATH = Path("/Users/jose/mylab/diagram-gen")

    # JC Visual Style template
    STYLE_TEMPLATE = """
=== JC VISUAL STYLE (MANDATORY) ===

TYPOGRAPHY: Two font families only
- Serif (Playfair Display, Georgia) for titles and key insights
- Sans-serif (Inter, Source Sans Pro) for all other text

COLORS:
- Background: #e8e6e3 (warm gray)
- Accent: #00b764 (green) - single focal point only
- Text: #1e2640 (dark navy)
- Labels: white pills with subtle shadow
- Connectors: #1a1a1a dashed black lines

LAYOUT:
- Reference density mode (6+ ideas, 20-30% whitespace)
- Asymmetric composition
- Dashed connector lines (not solid)
- Pill-shaped rounded labels

VISUAL ELEMENTS:
- Minimal engineering line drawings (bridges, roads, infrastructure) if appropriate
- NO clipart, NO icons, NO US imagery
- NO progress bars or gauges
- NO symmetrical grids

OUTPUT: 4K, horizontal aspect ratio
"""

    def __init__(self, dry_run: bool = True, book_filter: Optional[str] = None,
                 chapter_filter: Optional[str] = None):
        self.dry_run = dry_run
        self.book_filter = book_filter
        self.chapter_filter = chapter_filter

        # Statistics
        self.stats = {
            'books_found': 0,
            'chapters_found': 0,
            'chapters_with_diagrams': 0,
            'chapters_processed': 0,
            'errors': 0
        }

    def find_chapter_folders(self) -> list[Path]:
        """Find all *-Chapters folders in INBOX."""
        folders = []
        for item in self.INBOX_PATH.iterdir():
            if item.is_dir() and item.name.endswith(" - Chapters"):
                if self.book_filter:
                    book_name = item.name.replace(" - Chapters", "")
                    if self.book_filter.lower() not in book_name.lower():
                        continue
                folders.append(item)
        return sorted(folders)

    def get_chapter_files(self, folder: Path) -> list[Path]:
        """Get all chapter markdown files in a folder."""
        chapters = []
        for f in folder.glob("*.md"):
            if self.chapter_filter:
                if self.chapter_filter.lower() not in f.stem.lower():
                    continue
            chapters.append(f)
        return sorted(chapters, key=lambda p: p.stem)

    def has_diagram(self, content: str) -> bool:
        """Check if note already has a chapter diagram."""
        # Look for diagram embedding pattern
        patterns = [
            r'!\[\[.*chapter.*diagram.*\.png\]\]',
            r'!\[\[.*diagram.*chapter.*\.png\]\]',
            r'!\[\[Attachments/diagram_\d{8}_\d{6}\.png\]\]',
            r'## Visual Summary',
        ]
        for pattern in patterns:
            if re.search(pattern, content, re.IGNORECASE):
                return True
        return False

    def extract_chapter_content(self, content: str) -> dict:
        """Extract relevant sections from chapter note."""
        result = {
            'title': '',
            'book': '',
            'overview': '',
            'key_arguments': '',
            'core_concepts': '',
        }

        # Extract frontmatter
        fm_match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
        if fm_match:
            fm = fm_match.group(1)
            title_match = re.search(r'title:\s*"?([^"\n]+)"?', fm)
            book_match = re.search(r'book:\s*"?([^"\n]+)"?', fm)
            if title_match:
                result['title'] = title_match.group(1).strip()
            if book_match:
                result['book'] = book_match.group(1).strip()

        # Extract Chapter Overview section
        overview_match = re.search(
            r'## Chapter Overview\n\n(.*?)(?=\n## |\n---|\Z)',
            content,
            re.DOTALL
        )
        if overview_match:
            result['overview'] = overview_match.group(1).strip()

        # Extract Key Arguments section
        args_match = re.search(
            r'## Key Arguments\n\n(.*?)(?=\n## |\n---|\Z)',
            content,
            re.DOTALL
        )
        if args_match:
            result['key_arguments'] = args_match.group(1).strip()

        # Extract Core Concepts section
        concepts_match = re.search(
            r'## Core Concepts\n\n(.*?)(?=\n## |\n---|\Z)',
            content,
            re.DOTALL
        )
        if concepts_match:
            result['core_concepts'] = concepts_match.group(1).strip()

        return result

    def build_prompt(self, chapter_info: dict) -> str:
        """Build the AI image generation prompt from chapter content."""
        title = chapter_info['title'] or "Chapter Summary"
        book = chapter_info['book'] or "Book"
        overview = chapter_info['overview'][:800] if chapter_info['overview'] else ""
        key_args = chapter_info['key_arguments'][:600] if chapter_info['key_arguments'] else ""
        concepts = chapter_info['core_concepts'][:600] if chapter_info['core_concepts'] else ""

        # Extract bullet points from key arguments
        key_points = []
        for line in key_args.split('\n'):
            if line.strip().startswith('- **'):
                # Extract the bold text
                match = re.search(r'\*\*([^*]+)\*\*', line)
                if match:
                    key_points.append(match.group(1))

        # Build concept list from core concepts
        concept_headers = re.findall(r'###\s+(.+)', concepts)

        prompt = f"""Create a professional concept map infographic summarizing:

CHAPTER: {title}
FROM: {book}

OVERVIEW:
{overview[:400]}

KEY CONCEPTS TO VISUALIZE:
{chr(10).join(f"- {c}" for c in concept_headers[:6]) if concept_headers else chr(10).join(f"- {p}" for p in key_points[:6])}

MAIN ARGUMENTS:
{chr(10).join(f"- {p}" for p in key_points[:4]) if key_points else ""}

Create a concept map showing relationships between these ideas. Use arrows and connections to show how concepts relate. Place the chapter title prominently at top.

{self.STYLE_TEMPLATE}
"""
        return prompt

    def generate_diagram(self, prompt: str, chapter_name: str) -> Optional[Path]:
        """Call the diagram generator script."""
        if self.dry_run:
            print(f"    [DRY RUN] Would generate diagram for: {chapter_name}")
            return None

        # Sanitize filename
        safe_name = re.sub(r'[^\w\s-]', '', chapter_name).strip().replace(' ', '_')
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"chapter_diagram_{safe_name}_{timestamp}.png"
        output_path = self.ATTACHMENTS_PATH / output_filename

        try:
            # Run the diagram generator
            cmd = [
                str(self.DIAGRAM_GEN_PATH / ".venv" / "bin" / "python"),
                str(self.DIAGRAM_GEN_PATH / "generate_diagram.py"),
                prompt,
                str(output_path)
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(self.DIAGRAM_GEN_PATH)
            )

            if result.returncode != 0:
                print(f"    ERROR: {result.stderr}")
                return None

            if output_path.exists():
                print(f"    Generated: {output_path.name}")
                return output_path
            else:
                print(f"    ERROR: Output file not created")
                return None

        except subprocess.TimeoutExpired:
            print(f"    ERROR: Diagram generation timed out")
            return None
        except Exception as e:
            print(f"    ERROR: {e}")
            return None

    def insert_diagram_in_note(self, note_path: Path, diagram_path: Path) -> bool:
        """Insert diagram reference into note before Chapter/Book Overview."""
        if self.dry_run:
            print(f"    [DRY RUN] Would insert diagram into: {note_path.name}")
            return True

        try:
            content = note_path.read_text(encoding='utf-8')

            # Find the Chapter Overview or Book Overview heading
            overview_match = re.search(r'(## (?:Chapter|Book|Part) Overview\n)', content)
            if not overview_match:
                print(f"    WARNING: No Overview section found")
                return False

            # Build the diagram embed
            diagram_embed = f"""## Visual Summary

![[{diagram_path.name}]]

"""

            # Insert before Chapter Overview
            insert_pos = overview_match.start()
            new_content = content[:insert_pos] + diagram_embed + content[insert_pos:]

            note_path.write_text(new_content, encoding='utf-8')
            print(f"    Inserted diagram into: {note_path.name}")
            return True

        except Exception as e:
            print(f"    ERROR inserting diagram: {e}")
            return False

    def process_chapter(self, chapter_path: Path) -> bool:
        """Process a single chapter note."""
        try:
            content = chapter_path.read_text(encoding='utf-8')
        except Exception as e:
            print(f"  ERROR reading {chapter_path.name}: {e}")
            self.stats['errors'] += 1
            return False

        # Check if already has diagram
        if self.has_diagram(content):
            print(f"  SKIP (has diagram): {chapter_path.name}")
            self.stats['chapters_with_diagrams'] += 1
            return False

        # Extract content for prompt
        chapter_info = self.extract_chapter_content(content)
        if not chapter_info['overview'] and not chapter_info['key_arguments']:
            print(f"  SKIP (no overview/arguments): {chapter_path.name}")
            return False

        print(f"  Processing: {chapter_path.name}")

        # Build prompt
        prompt = self.build_prompt(chapter_info)

        # Generate diagram
        diagram_path = self.generate_diagram(prompt, chapter_path.stem)

        if diagram_path:
            # Insert into note
            if self.insert_diagram_in_note(chapter_path, diagram_path):
                self.stats['chapters_processed'] += 1
                return True
        elif self.dry_run:
            self.stats['chapters_processed'] += 1
            return True

        return False

    def run(self):
        """Main execution."""
        print("=" * 60)
        print("Chapter Diagram Generator")
        print("=" * 60)
        print(f"Vault: {self.VAULT_PATH}")
        print(f"Mode: {'DRY RUN' if self.dry_run else 'LIVE'}")
        if self.book_filter:
            print(f"Book filter: {self.book_filter}")
        if self.chapter_filter:
            print(f"Chapter filter: {self.chapter_filter}")
        print()

        # Find chapter folders
        folders = self.find_chapter_folders()
        self.stats['books_found'] = len(folders)

        if not folders:
            print("No chapter folders found in INBOX.")
            return

        print(f"Found {len(folders)} book(s) with chapters:\n")

        for folder in folders:
            book_name = folder.name.replace(" - Chapters", "")
            chapters = self.get_chapter_files(folder)
            self.stats['chapters_found'] += len(chapters)

            print(f"\n📚 {book_name} ({len(chapters)} chapters)")
            print("-" * 50)

            for chapter in chapters:
                self.process_chapter(chapter)

        # Summary
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print(f"Books found: {self.stats['books_found']}")
        print(f"Chapters found: {self.stats['chapters_found']}")
        print(f"Already have diagrams: {self.stats['chapters_with_diagrams']}")
        print(f"Chapters processed: {self.stats['chapters_processed']}")
        print(f"Errors: {self.stats['errors']}")

        if self.dry_run:
            print("\nThis was a DRY RUN. Use --no-dry-run to generate diagrams.")


def main():
    parser = argparse.ArgumentParser(
        description="Generate AI diagrams for book chapter summaries",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        '--no-dry-run',
        action='store_true',
        help='Actually generate diagrams (default is dry-run)'
    )

    parser.add_argument(
        '--book',
        type=str,
        help='Filter to specific book (partial match)'
    )

    parser.add_argument(
        '--chapter',
        type=str,
        help='Filter to specific chapter (partial match)'
    )

    args = parser.parse_args()

    # Check environment
    if not args.no_dry_run:
        pass  # Dry run doesn't need API key
    elif not os.environ.get("GOOGLE_API_KEY"):
        print("ERROR: GOOGLE_API_KEY environment variable not set")
        print("Set it or use dry-run mode to preview.")
        sys.exit(1)

    generator = ChapterDiagramGenerator(
        dry_run=not args.no_dry_run,
        book_filter=args.book,
        chapter_filter=args.chapter
    )

    generator.run()


if __name__ == "__main__":
    main()
