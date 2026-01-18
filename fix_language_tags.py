#!/usr/bin/env python3
"""
Obsidian Language Tag Fixer

Scans Obsidian vault for notes, detects the main language (English or Spanish),
and updates the lang/ tag in frontmatter accordingly.

Uses langdetect library for language detection with custom heuristics
for mixed-language content common in bilingual vaults.
"""

import argparse
import re
import sys
from pathlib import Path
from typing import Optional, Tuple, List, Dict

try:
    from langdetect import detect_langs, LangDetectException
except ImportError:
    print("Error: langdetect is required. Install with: pip install langdetect")
    sys.exit(1)

# Import shared utilities
try:
    from obsidian_utils import get_all_notes, validate_vault_path
except ImportError:
    # Fallback if running from different directory
    def get_all_notes(vault_path: Path, skip_trash: bool = True, skip_obsidian: bool = True) -> List[Path]:
        notes = []
        for md_file in vault_path.rglob("*.md"):
            if any(part.startswith('.') for part in md_file.parts):
                if '.trash' in str(md_file) or '.obsidian' in str(md_file):
                    continue
            notes.append(md_file)
        return notes

    def validate_vault_path(vault_path: str) -> Tuple[bool, str]:
        path = Path(vault_path)
        if not path.exists():
            return False, f"Vault path does not exist: {vault_path}"
        if not path.is_dir():
            return False, f"Vault path is not a directory: {vault_path}"
        return True, ""


class LanguageTagFixer:
    """Main class for detecting and fixing language tags in Obsidian notes."""

    # Supported languages
    SUPPORTED_LANGS = {'en', 'es'}

    # Minimum text length for reliable detection
    MIN_TEXT_LENGTH = 50

    # Confidence threshold for detection
    CONFIDENCE_THRESHOLD = 0.7

    # Spanish-specific patterns (common words/patterns)
    SPANISH_INDICATORS = {
        'el', 'la', 'los', 'las', 'de', 'del', 'en', 'que', 'y', 'con',
        'para', 'por', 'una', 'uno', 'es', 'como', 'más', 'pero', 'este',
        'esta', 'estos', 'estas', 'su', 'sus', 'se', 'no', 'al', 'lo',
        'han', 'ha', 'sin', 'sobre', 'entre', 'también', 'hasta', 'donde',
        'muy', 'puede', 'todos', 'así', 'nos', 'ya', 'porque', 'cuando',
        'él', 'ella', 'ellos', 'ellas', 'ser', 'están', 'está', 'son',
        'desde', 'cada', 'todo', 'hacer', 'tiene', 'tienen', 'sido',
        'ñ', 'á', 'é', 'í', 'ó', 'ú', '¿', '¡'  # Spanish-specific characters
    }

    # English-specific patterns
    ENGLISH_INDICATORS = {
        'the', 'of', 'and', 'to', 'in', 'is', 'it', 'that', 'for', 'was',
        'with', 'as', 'be', 'on', 'at', 'by', 'this', 'which', 'or', 'an',
        'from', 'are', 'but', 'not', 'you', 'all', 'can', 'had', 'her',
        'were', 'one', 'our', 'out', 'has', 'his', 'they', 'been', 'have',
        'their', 'would', 'what', 'there', 'when', 'who', 'will', 'more',
        'if', 'some', 'them', 'into', 'than', 'then', 'its', 'over',
        'such', 'only', 'other', 'new', 'these', 'could', 'after', 'use'
    }

    def __init__(self, vault_path: str, dry_run: bool = True, verbose: bool = False,
                 add_only: bool = False, min_confidence: float = 0.5):
        self.vault_path = Path(vault_path)
        self.dry_run = dry_run
        self.verbose = verbose
        self.add_only = add_only  # Only add missing tags, don't change existing
        self.min_confidence = min_confidence

        # Statistics
        self.stats = {
            'notes_scanned': 0,
            'notes_with_correct_tags': 0,
            'notes_fixed': 0,
            'notes_tag_added': 0,
            'notes_tag_changed': 0,
            'notes_skipped_short': 0,
            'notes_skipped_uncertain': 0,
            'notes_skipped_no_frontmatter': 0,
            'detection_errors': 0,
            'detected_en': 0,
            'detected_es': 0
        }

        # Track changes for reporting
        self.changes: List[Dict] = []

    def extract_frontmatter(self, content: str) -> Tuple[Optional[str], str]:
        """
        Extract frontmatter and body from note content.

        Returns (frontmatter, body) where frontmatter may be None.
        """
        if not content.startswith('---'):
            return None, content

        # Find closing ---
        end_match = re.search(r'\n---\s*\n', content[3:])
        if not end_match:
            return None, content

        end_pos = end_match.end() + 3
        frontmatter = content[:end_pos]
        body = content[end_pos:]

        return frontmatter, body

    def extract_text_for_detection(self, content: str) -> str:
        """
        Extract clean text suitable for language detection.

        Removes:
        - Frontmatter
        - AI-generated curator summaries (detect from original body only)
        - Code blocks
        - URLs
        - Wikilinks (keep link text)
        - Markdown syntax
        - HTML tags
        """
        _, body = self.extract_frontmatter(content)

        # Remove AI-generated curator summary section
        # Pattern: ## Curator Summary ... --- (horizontal rule)
        curator_pattern = r'##\s*Curator Summary[\s\S]*?(?=\n---\s*\n)'
        body = re.sub(curator_pattern, '', body)

        # Remove code blocks (``` and ~~~)
        body = re.sub(r'```[\s\S]*?```', '', body)
        body = re.sub(r'~~~[\s\S]*?~~~', '', body)

        # Remove inline code
        body = re.sub(r'`[^`]+`', '', body)

        # Remove URLs
        body = re.sub(r'https?://\S+', '', body)
        body = re.sub(r'\[([^\]]*)\]\([^)]+\)', r'\1', body)  # Keep link text

        # Remove wikilinks but keep text
        body = re.sub(r'\[\[([^\]|]+)\|([^\]]+)\]\]', r'\2', body)  # [[link|text]] -> text
        body = re.sub(r'\[\[([^\]]+)\]\]', r'\1', body)  # [[link]] -> link

        # Remove HTML tags
        body = re.sub(r'<[^>]+>', '', body)

        # Remove markdown headers
        body = re.sub(r'^#+\s*', '', body, flags=re.MULTILINE)

        # Remove markdown emphasis
        body = re.sub(r'\*\*([^*]+)\*\*', r'\1', body)
        body = re.sub(r'\*([^*]+)\*', r'\1', body)
        body = re.sub(r'__([^_]+)__', r'\1', body)
        body = re.sub(r'_([^_]+)_', r'\1', body)

        # Remove image references
        body = re.sub(r'!\[\[.*?\]\]', '', body)
        body = re.sub(r'!\[.*?\]\(.*?\)', '', body)

        # Remove extra whitespace
        body = re.sub(r'\s+', ' ', body).strip()

        return body

    def count_language_indicators(self, text: str) -> Tuple[int, int]:
        """
        Count Spanish and English indicator words in text.

        Returns (spanish_count, english_count).
        """
        words = set(re.findall(r'\b\w+\b', text.lower()))

        spanish_count = len(words & self.SPANISH_INDICATORS)
        english_count = len(words & self.ENGLISH_INDICATORS)

        # Count Spanish-specific characters
        spanish_chars = sum(1 for c in text if c in 'ñáéíóúü¿¡')
        spanish_count += spanish_chars

        return spanish_count, english_count

    def detect_language(self, text: str) -> Tuple[Optional[str], float]:
        """
        Detect the main language of text.

        Returns (language_code, confidence) or (None, 0.0) if uncertain.
        Language code is 'en' or 'es'.
        """
        if len(text) < self.MIN_TEXT_LENGTH:
            return None, 0.0

        try:
            # Primary detection using langdetect
            langs = detect_langs(text)

            # Find best supported language
            best_lang = None
            best_prob = 0.0

            for lang in langs:
                if lang.lang in self.SUPPORTED_LANGS and lang.prob > best_prob:
                    best_lang = lang.lang
                    best_prob = lang.prob

            # If langdetect is uncertain, use word indicators
            if best_prob < self.CONFIDENCE_THRESHOLD:
                es_count, en_count = self.count_language_indicators(text)

                total = es_count + en_count
                if total > 5:  # Need enough indicators
                    if es_count > en_count * 1.5:
                        return 'es', min(0.9, es_count / total)
                    elif en_count > es_count * 1.5:
                        return 'en', min(0.9, en_count / total)

            if best_lang and best_prob >= self.CONFIDENCE_THRESHOLD:
                return best_lang, best_prob

            # Low confidence - use indicator words as tiebreaker
            if best_lang:
                es_count, en_count = self.count_language_indicators(text)
                if best_lang == 'es' and es_count >= en_count:
                    return 'es', max(best_prob, 0.6)
                elif best_lang == 'en' and en_count >= es_count:
                    return 'en', max(best_prob, 0.6)
                elif es_count > en_count * 2:
                    return 'es', 0.6
                elif en_count > es_count * 2:
                    return 'en', 0.6

            return best_lang, best_prob

        except LangDetectException as e:
            if self.verbose:
                print(f"  Detection error: {e}")
            return None, 0.0

    def get_current_lang_tag(self, frontmatter: str) -> Optional[str]:
        """Extract current lang/ tag from frontmatter."""
        # Look for lang/en or lang/es in tags
        match = re.search(r"'lang/(en|es)'|\"lang/(en|es)\"|lang/(en|es)", frontmatter)
        if match:
            return match.group(1) or match.group(2) or match.group(3)
        return None

    def update_frontmatter(self, content: str, detected_lang: str) -> Tuple[str, Dict]:
        """
        Update frontmatter with correct lang/ tag.

        Returns (updated_content, changes_dict).
        """
        frontmatter, body = self.extract_frontmatter(content)
        changes = {
            'tag_added': False,
            'tag_changed': False,
            'old_tag': None
        }

        if frontmatter is None:
            return content, changes

        new_frontmatter = frontmatter
        current_tag = self.get_current_lang_tag(frontmatter)

        if current_tag is None:
            # Add lang tag to tags list
            # Try inline format first: tags: [...]
            tags_match = re.search(r'^tags:\s*\[(.*?)\]', new_frontmatter, re.MULTILINE | re.DOTALL)
            if tags_match:
                old_tags = tags_match.group(1)
                if old_tags.strip():
                    new_tags = f"{old_tags.rstrip()}, 'lang/{detected_lang}'"
                else:
                    new_tags = f"'lang/{detected_lang}'"
                new_frontmatter = new_frontmatter[:tags_match.start(1)] + new_tags + new_frontmatter[tags_match.end(1):]
                changes['tag_added'] = True
            else:
                # Try multiline format: tags:\n  - tag1\n  - tag2
                tags_multi_match = re.search(r'^tags:\s*\n((?:\s*-\s*.+\n)+)', new_frontmatter, re.MULTILINE)
                if tags_multi_match:
                    old_content = tags_multi_match.group(1)
                    new_frontmatter = new_frontmatter.replace(
                        old_content,
                        f"{old_content}  - lang/{detected_lang}\n"
                    )
                    changes['tag_added'] = True

        elif current_tag != detected_lang:
            # Replace existing tag
            patterns = [
                f"'lang/{current_tag}'",
                f'"lang/{current_tag}"',
                f'lang/{current_tag}'
            ]
            replacements = [
                f"'lang/{detected_lang}'",
                f'"lang/{detected_lang}"',
                f'lang/{detected_lang}'
            ]
            for pattern, replacement in zip(patterns, replacements):
                if pattern in new_frontmatter:
                    new_frontmatter = new_frontmatter.replace(pattern, replacement)
                    changes['tag_changed'] = True
                    changes['old_tag'] = current_tag
                    break

        return new_frontmatter + body, changes

    def process_note(self, note_path: Path) -> bool:
        """
        Process a single note: detect language and fix tag if needed.

        Returns True if changes were made (or would be made in dry-run).
        """
        try:
            content = note_path.read_text(encoding='utf-8', errors='ignore')
        except Exception as e:
            if self.verbose:
                print(f"Error reading {note_path}: {e}")
            self.stats['detection_errors'] += 1
            return False

        # Check for frontmatter
        frontmatter, _ = self.extract_frontmatter(content)
        if frontmatter is None:
            if self.verbose:
                print(f"  Skipped (no frontmatter): {note_path.name}")
            self.stats['notes_skipped_no_frontmatter'] += 1
            return False

        # Extract text for detection
        text = self.extract_text_for_detection(content)

        if len(text) < self.MIN_TEXT_LENGTH:
            if self.verbose:
                print(f"  Skipped (too short): {note_path.name}")
            self.stats['notes_skipped_short'] += 1
            return False

        # Detect language
        detected_lang, confidence = self.detect_language(text)

        if detected_lang is None or confidence < self.min_confidence:
            if self.verbose:
                print(f"  Skipped (uncertain): {note_path.name} (conf: {confidence:.2f})")
            self.stats['notes_skipped_uncertain'] += 1
            return False

        # Track detection
        if detected_lang == 'en':
            self.stats['detected_en'] += 1
        else:
            self.stats['detected_es'] += 1

        # Check current tag
        current_tag = self.get_current_lang_tag(frontmatter)

        # Already correct
        if current_tag == detected_lang:
            self.stats['notes_with_correct_tags'] += 1
            return False

        # In add-only mode, skip if existing tag differs from detected
        if self.add_only and current_tag is not None and current_tag != detected_lang:
            if self.verbose:
                print(f"  Skipped (add-only): {note_path.name} "
                      f"(has lang/{current_tag}, detected {detected_lang})")
            self.stats['notes_with_correct_tags'] += 1  # Trust existing tag
            return False

        # Update frontmatter
        updated_content, changes = self.update_frontmatter(content, detected_lang)

        if not changes['tag_added'] and not changes['tag_changed']:
            return False

        # Record change
        self.changes.append({
            'path': str(note_path.relative_to(self.vault_path)),
            'detected': detected_lang,
            'confidence': confidence,
            **changes
        })

        # Update statistics
        if changes['tag_added']:
            self.stats['notes_tag_added'] += 1
        if changes['tag_changed']:
            self.stats['notes_tag_changed'] += 1

        self.stats['notes_fixed'] += 1

        # Write changes
        if self.dry_run:
            if self.verbose:
                if changes['tag_added']:
                    print(f"  [DRY RUN] {note_path.name}: add lang/{detected_lang}")
                elif changes['tag_changed']:
                    print(f"  [DRY RUN] {note_path.name}: lang/{changes['old_tag']} -> lang/{detected_lang}")
        else:
            try:
                note_path.write_text(updated_content, encoding='utf-8')
                if self.verbose:
                    print(f"  Fixed: {note_path.name}")
            except Exception as e:
                print(f"  Error writing {note_path}: {e}")
                return False

        return True

    def run(self, subfolder: Optional[str] = None):
        """Main execution logic."""
        print("Language Tag Fixer for Obsidian")
        print(f"Vault: {self.vault_path}")
        if subfolder:
            print(f"Subfolder: {subfolder}")
        print("=" * 60)

        if self.dry_run:
            print("MODE: Dry run (no changes will be made)")
        else:
            print("MODE: Live run (changes will be applied)")
        if self.add_only:
            print("ADD-ONLY: Will only add missing tags, not change existing ones")
        print(f"MIN CONFIDENCE: {self.min_confidence}")
        print()

        # Get notes to process
        if subfolder:
            scan_path = self.vault_path / subfolder
            if not scan_path.exists():
                print(f"Error: Subfolder does not exist: {subfolder}")
                return
            notes = list(scan_path.rglob("*.md"))
            notes = [n for n in notes if not any(part.startswith('.') for part in n.parts)]
        else:
            notes = get_all_notes(self.vault_path)

        self.stats['notes_scanned'] = len(notes)
        print(f"Found {len(notes)} note(s) to process\n")

        # Process notes
        for i, note in enumerate(notes, 1):
            if i % 100 == 0:
                print(f"Progress: {i}/{len(notes)} notes processed...")
            self.process_note(note)

        # Print summary
        self.print_summary()

        # Print changes for review
        if self.changes:
            self.print_changes_report()

    def print_summary(self):
        """Print statistics summary."""
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print(f"Notes scanned:              {self.stats['notes_scanned']}")
        print(f"Notes with correct tags:    {self.stats['notes_with_correct_tags']}")
        print(f"Notes fixed:                {self.stats['notes_fixed']}")
        print(f"  - Tag added:              {self.stats['notes_tag_added']}")
        print(f"  - Tag changed:            {self.stats['notes_tag_changed']}")
        print(f"Notes skipped (too short):  {self.stats['notes_skipped_short']}")
        print(f"Notes skipped (uncertain):  {self.stats['notes_skipped_uncertain']}")
        print(f"Notes skipped (no frontmatter): {self.stats['notes_skipped_no_frontmatter']}")
        print(f"Detection errors:           {self.stats['detection_errors']}")
        print()
        print(f"Language distribution:")
        print(f"  - English: {self.stats['detected_en']}")
        print(f"  - Spanish: {self.stats['detected_es']}")

        if self.dry_run and self.stats['notes_fixed'] > 0:
            print("\nThis was a DRY RUN. Run with --no-dry-run to apply changes.")

    def print_changes_report(self):
        """Print detailed changes report."""
        print("\n" + "=" * 60)
        print("CHANGES REPORT")
        print("=" * 60)

        tag_changes = [c for c in self.changes if c['tag_changed']]
        tag_adds = [c for c in self.changes if c['tag_added']]

        if tag_adds:
            print(f"\nTags to add ({len(tag_adds)}):")
            for c in tag_adds[:20]:
                print(f"  {c['path']}: lang/{c['detected']} (conf: {c['confidence']:.2f})")
            if len(tag_adds) > 20:
                print(f"  ... and {len(tag_adds) - 20} more")

        if tag_changes:
            print(f"\nTags to change ({len(tag_changes)}):")
            for c in tag_changes[:20]:
                print(f"  {c['path']}")
                print(f"    lang/{c['old_tag']} -> lang/{c['detected']} (conf: {c['confidence']:.2f})")
            if len(tag_changes) > 20:
                print(f"  ... and {len(tag_changes) - 20} more")


def main():
    parser = argparse.ArgumentParser(
        description="Detect and fix lang/ tags in Obsidian notes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run on entire vault (preview only, safe default)
  python fix_language_tags.py

  # Dry run on specific subfolder
  python fix_language_tags.py --subfolder "3.RECURSOS/Domain Knowledge"

  # Actually fix language tags (applies changes)
  python fix_language_tags.py --no-dry-run

  # Verbose output for debugging
  python fix_language_tags.py --verbose

  # Only add missing tags (safe for bilingual notes with existing tags)
  python fix_language_tags.py --add-only --no-dry-run

  # Higher confidence threshold (more conservative)
  python fix_language_tags.py --min-confidence 0.7
        """
    )

    parser.add_argument(
        '--vault',
        type=str,
        default='/Users/jose/obsidian/JC',
        help='Path to Obsidian vault (default: /Users/jose/obsidian/JC)'
    )

    parser.add_argument(
        '--subfolder',
        type=str,
        default=None,
        help='Process only a specific subfolder (relative path from vault root)'
    )

    parser.add_argument(
        '--no-dry-run',
        action='store_true',
        help='Apply changes (default is dry-run mode)'
    )

    parser.add_argument(
        '--add-only',
        action='store_true',
        help='Only add missing lang/ tags, do not change existing ones'
    )

    parser.add_argument(
        '--min-confidence',
        type=float,
        default=0.5,
        help='Minimum confidence threshold for detection (default: 0.5, max: 1.0)'
    )

    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show detailed progress for each note'
    )

    args = parser.parse_args()

    # Validate vault path
    valid, error = validate_vault_path(args.vault)
    if not valid:
        print(f"Error: {error}")
        return 1

    # Run fixer
    fixer = LanguageTagFixer(
        args.vault,
        dry_run=not args.no_dry_run,
        verbose=args.verbose,
        add_only=args.add_only,
        min_confidence=args.min_confidence
    )
    fixer.run(subfolder=args.subfolder)

    return 0


if __name__ == "__main__":
    exit(main())
