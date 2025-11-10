#!/usr/bin/env python3
"""
Obsidian Attachment Statistics Tool

Scans Obsidian vault's Attachments folder and prints detailed statistics about
file sizes, including breakdown by file type.
"""

import argparse
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple
from collections import defaultdict


class AttachmentStats:
    """Main class for analyzing attachment statistics."""
    
    def __init__(self, vault_path: str):
        self.vault_path = Path(vault_path)
        self.attachments_path = self.vault_path / "Attachments"
        
        # Statistics by file type
        self.stats_by_type: Dict[str, Dict] = defaultdict(lambda: {
            'count': 0,
            'total_size': 0,
            'sizes': []
        })
        
        # Overall statistics
        self.total_files = 0
        self.total_size = 0
        
        # Store individual files with sizes for top-100 analysis
        self.all_files: List[tuple] = []  # List of (path, size, file_type) tuples
        
    def get_all_attachments(self) -> List[Path]:
        """Get all files from the Attachments folder and subfolders."""
        if not self.attachments_path.exists():
            return []
        
        attachments = []
        for file in self.attachments_path.rglob("*"):
            # Skip backup folders
            if 'backup' in file.parts:
                continue
            if file.is_file():
                attachments.append(file)
        
        return attachments
    
    def format_size(self, bytes_size: float) -> str:
        """Format file size in human-readable format."""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if bytes_size < 1024.0:
                return f"{bytes_size:.2f} {unit}"
            bytes_size /= 1024.0
        return f"{bytes_size:.2f} TB"
    
    def get_file_type(self, file_path: Path) -> str:
        """Get file type from extension, or 'no extension' if none."""
        ext = file_path.suffix.lower()
        if not ext:
            return 'no extension'
        # Remove the dot
        return ext[1:] if ext.startswith('.') else ext
    
    def analyze_attachments(self):
        """Analyze all attachments and collect statistics."""
        print("📊 Scanning attachments...")
        attachments = self.get_all_attachments()
        
        if not attachments:
            print("❌ No attachments found!")
            return
        
        self.total_files = len(attachments)
        
        print(f"Found {self.total_files} file(s)")
        print("Analyzing file sizes...")
        
        for idx, attachment in enumerate(attachments, 1):
            if idx % 100 == 0:
                print(f"  Processed {idx}/{self.total_files} files...", flush=True)
            
            try:
                file_size = attachment.stat().st_size
                file_type = self.get_file_type(attachment)
                
                # Store file info for top-100 analysis
                self.all_files.append((attachment, file_size, file_type))
                
                # Update type-specific stats
                self.stats_by_type[file_type]['count'] += 1
                self.stats_by_type[file_type]['total_size'] += file_size
                self.stats_by_type[file_type]['sizes'].append(file_size)
                
                # Update overall stats
                self.total_size += file_size
            except Exception as e:
                print(f"  ⚠️  Error reading {attachment}: {e}")
    
    def print_statistics(self):
        """Print comprehensive statistics."""
        if self.total_files == 0:
            return
        
        print("\n" + "=" * 70)
        print("📊 ATTACHMENT STATISTICS")
        print("=" * 70)
        
        # Overall statistics
        print("\n📈 OVERALL STATISTICS:")
        print(f"  • Total files: {self.total_files:,}")
        print(f"  • Total size: {self.format_size(self.total_size)}")
        avg_size = self.total_size / self.total_files if self.total_files > 0 else 0
        print(f"  • Average file size: {self.format_size(avg_size)}")
        
        # Statistics by file type
        print("\n" + "=" * 70)
        print("📁 STATISTICS BY FILE TYPE")
        print("=" * 70)
        
        # Sort by total size (descending)
        sorted_types = sorted(
            self.stats_by_type.items(),
            key=lambda x: x[1]['total_size'],
            reverse=True
        )
        
        for file_type, stats in sorted_types:
            count = stats['count']
            total_size = stats['total_size']
            sizes = stats['sizes']
            
            avg_size = total_size / count if count > 0 else 0
            min_size = min(sizes) if sizes else 0
            max_size = max(sizes) if sizes else 0
            
            percentage = (total_size / self.total_size * 100) if self.total_size > 0 else 0
            
            print(f"\n📄 {file_type.upper()}:")
            print(f"  • Count: {count:,} file(s)")
            print(f"  • Total size: {self.format_size(total_size)} ({percentage:.1f}% of total)")
            print(f"  • Average size: {self.format_size(avg_size)}")
            print(f"  • Min size: {self.format_size(min_size)}")
            print(f"  • Max size: {self.format_size(max_size)}")
            
            # Show size distribution if there are multiple files
            if len(sizes) > 1:
                sorted_sizes = sorted(sizes)
                median_idx = len(sorted_sizes) // 2
                median_size = sorted_sizes[median_idx] if len(sorted_sizes) % 2 == 1 else (sorted_sizes[median_idx - 1] + sorted_sizes[median_idx]) / 2
                print(f"  • Median size: {self.format_size(median_size)}")
        
        # Summary table
        print("\n" + "=" * 70)
        print("📋 SUMMARY TABLE")
        print("=" * 70)
        print(f"{'File Type':<20} {'Count':>10} {'Total Size':>15} {'Avg Size':>15} {'% of Total':>12}")
        print("-" * 70)
        
        for file_type, stats in sorted_types:
            count = stats['count']
            total_size = stats['total_size']
            avg_size = total_size / count if count > 0 else 0
            percentage = (total_size / self.total_size * 100) if self.total_size > 0 else 0
            
            print(f"{file_type[:19]:<20} {count:>10,} {self.format_size(total_size):>15} {self.format_size(avg_size):>15} {percentage:>11.1f}%")
        
        print("=" * 70)
        
        # Top-100 heaviest files statistics
        self.print_top100_statistics()
    
    def print_top100_statistics(self):
        """Print statistics for the top 100 heaviest files."""
        if not self.all_files:
            return
        
        # Sort by file size (descending) and take top 100
        sorted_files = sorted(self.all_files, key=lambda x: x[1], reverse=True)
        top100 = sorted_files[:100]
        
        if not top100:
            return
        
        # Calculate stats for top 100
        top100_total_size = sum(size for _, size, _ in top100)
        top100_stats_by_type: Dict[str, Dict] = defaultdict(lambda: {
            'count': 0,
            'total_size': 0,
            'sizes': []
        })
        
        for _, file_size, file_type in top100:
            top100_stats_by_type[file_type]['count'] += 1
            top100_stats_by_type[file_type]['total_size'] += file_size
            top100_stats_by_type[file_type]['sizes'].append(file_size)
        
        print("\n" + "=" * 70)
        print("🔝 TOP-100 HEAVIEST FILES STATISTICS")
        print("=" * 70)
        
        # Overall statistics for top 100
        print("\n📈 TOP-100 OVERALL STATISTICS:")
        print(f"  • Files in top 100: {len(top100):,}")
        print(f"  • Total size: {self.format_size(top100_total_size)}")
        top100_percentage = (top100_total_size / self.total_size * 100) if self.total_size > 0 else 0
        print(f"  • Percentage of total vault size: {top100_percentage:.1f}%")
        avg_size = top100_total_size / len(top100) if len(top100) > 0 else 0
        print(f"  • Average file size: {self.format_size(avg_size)}")
        min_size_top100 = min(size for _, size, _ in top100)
        max_size_top100 = max(size for _, size, _ in top100)
        print(f"  • Size range: {self.format_size(min_size_top100)} - {self.format_size(max_size_top100)}")
        
        # Statistics by file type for top 100
        print("\n📁 TOP-100 STATISTICS BY FILE TYPE")
        print("=" * 70)
        
        # Sort by total size (descending)
        sorted_top100_types = sorted(
            top100_stats_by_type.items(),
            key=lambda x: x[1]['total_size'],
            reverse=True
        )
        
        for file_type, stats in sorted_top100_types:
            count = stats['count']
            total_size = stats['total_size']
            sizes = stats['sizes']
            
            avg_size = total_size / count if count > 0 else 0
            min_size = min(sizes) if sizes else 0
            max_size = max(sizes) if sizes else 0
            
            percentage_of_top100 = (total_size / top100_total_size * 100) if top100_total_size > 0 else 0
            
            print(f"\n📄 {file_type.upper()}:")
            print(f"  • Count: {count:,} file(s)")
            print(f"  • Total size: {self.format_size(total_size)} ({percentage_of_top100:.1f}% of top-100)")
            print(f"  • Average size: {self.format_size(avg_size)}")
            print(f"  • Min size: {self.format_size(min_size)}")
            print(f"  • Max size: {self.format_size(max_size)}")
            
            # Show size distribution if there are multiple files
            if len(sizes) > 1:
                sorted_sizes = sorted(sizes)
                median_idx = len(sorted_sizes) // 2
                median_size = sorted_sizes[median_idx] if len(sorted_sizes) % 2 == 1 else (sorted_sizes[median_idx - 1] + sorted_sizes[median_idx]) / 2
                print(f"  • Median size: {self.format_size(median_size)}")
        
        # Summary table for top 100
        print("\n" + "=" * 70)
        print("📋 TOP-100 SUMMARY TABLE")
        print("=" * 70)
        print(f"{'File Type':<20} {'Count':>10} {'Total Size':>15} {'Avg Size':>15} {'% of Top-100':>15}")
        print("-" * 70)
        
        for file_type, stats in sorted_top100_types:
            count = stats['count']
            total_size = stats['total_size']
            avg_size = total_size / count if count > 0 else 0
            percentage = (total_size / top100_total_size * 100) if top100_total_size > 0 else 0
            
            print(f"{file_type[:19]:<20} {count:>10,} {self.format_size(total_size):>15} {self.format_size(avg_size):>15} {percentage:>14.1f}%")
        
        print("=" * 70)
        
        # List the actual top files
        print("\n📋 TOP 10 HEAVIEST FILES:")
        print("-" * 70)
        for idx, (file_path, file_size, file_type) in enumerate(top100[:10], 1):
            rel_path = file_path.relative_to(self.attachments_path)
            print(f"  {idx:2d}. {self.format_size(file_size):>12}  [{file_type:>8}]  {rel_path}")
        
        if len(top100) > 10:
            print(f"\n  ... and {len(top100) - 10} more files in the top 100")
        
        print("=" * 70)
    
    def analyze_filename_patterns(self) -> Dict[str, any]:
        """
        Analyze filename patterns across all attachments to identify screenshot patterns
        and other meaningful naming conventions.
        
        Returns a dictionary with discovered patterns and insights.
        """
        print("\n" + "=" * 70)
        print("🔍 FILENAME PATTERN ANALYSIS")
        print("=" * 70)
        
        if not self.all_files:
            print("  No files to analyze. Run analyze_attachments() first.")
            return {}
        
        attachments = self.get_all_attachments()
        if not attachments:
            print("  No attachments found!")
            return {}
        
        # Collect all filenames
        all_filenames = [f.name for f in attachments]
        total_files = len(all_filenames)
        
        print(f"\nAnalyzing {total_files:,} attachment filename(s)...")
        
        # Patterns to analyze
        patterns = {
            'has_date_time': [],
            'has_date_only': [],
            'has_uuid': [],
            'has_hash': [],
            'has_sequential': [],
            'has_common_words': [],
            'short_names': [],
            'long_names': [],
            'no_extension': [],
            'unknown_patterns': []
        }
        
        # Common screenshot-related words
        screenshot_words = {'screenshot', 'screen', 'shot', 'img', 'image', 'photo', 'pic', 'snap', 'capture'}
        
        # Date/time pattern detection
        date_patterns = [
            r'\d{4}-\d{2}-\d{2}',  # YYYY-MM-DD
            r'\d{2}-\d{2}-\d{4}',  # MM-DD-YYYY
            r'\d{8}',  # YYYYMMDD
        ]
        
        time_patterns = [
            r'\d{1,2}\.\d{2}\.\d{2}',  # H.MM.SS or HH.MM.SS
            r'\d{6}',  # HHMMSS
            r'\d{2}:\d{2}:\d{2}',  # HH:MM:SS
        ]
        
        # UUID pattern (8-4-4-4-12 hexadecimal)
        uuid_pattern = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
        
        # Hash-like pattern (long alphanumeric strings)
        hash_pattern = r'^[0-9a-f]{16,}$'
        
        # Sequential pattern (contains numbers in parentheses or underscores)
        sequential_pattern = r'\(?\d+\)?'
        
        for filename in all_filenames:
            name_lower = filename.lower()
            name_without_ext = Path(filename).stem
            
            # Check for date patterns
            has_date = any(re.search(pattern, filename) for pattern in date_patterns)
            has_time = any(re.search(pattern, filename) for pattern in time_patterns)
            
            if has_date and has_time:
                patterns['has_date_time'].append(filename)
            elif has_date:
                patterns['has_date_only'].append(filename)
            
            # Check for UUID
            if re.search(uuid_pattern, filename, re.IGNORECASE):
                patterns['has_uuid'].append(filename)
            
            # Check for hash-like patterns
            if re.match(hash_pattern, name_without_ext, re.IGNORECASE):
                patterns['has_hash'].append(filename)
            
            # Check for sequential numbering
            if re.search(sequential_pattern, filename):
                patterns['has_sequential'].append(filename)
            
            # Check for common screenshot words
            has_screenshot_word = any(word in name_lower for word in screenshot_words)
            if has_screenshot_word:
                patterns['has_common_words'].append(filename)
            
            # Short names (likely boilerplate)
            if len(name_without_ext) < 5:
                patterns['short_names'].append(filename)
            
            # Long names (likely meaningful)
            if len(name_without_ext) > 30:
                patterns['long_names'].append(filename)
            
            # No extension
            if not Path(filename).suffix:
                patterns['no_extension'].append(filename)
        
        # Analyze common prefixes and suffixes
        prefix_counts = defaultdict(int)
        suffix_counts = defaultdict(int)
        word_counts = defaultdict(int)
        
        for filename in all_filenames:
            name_without_ext = Path(filename).stem
            
            # Extract prefix (first 3-10 chars)
            if len(name_without_ext) >= 3:
                for prefix_len in [3, 5, 7, 10]:
                    if len(name_without_ext) >= prefix_len:
                        prefix = name_without_ext[:prefix_len].lower()
                        prefix_counts[prefix] += 1
            
            # Extract suffix (last 3-10 chars)
            if len(name_without_ext) >= 3:
                for suffix_len in [3, 5, 7, 10]:
                    if len(name_without_ext) >= suffix_len:
                        suffix = name_without_ext[-suffix_len:].lower()
                        suffix_counts[suffix] += 1
            
            # Extract words
            words = re.findall(r'[A-Za-z]{3,}', name_without_ext)
            for word in words:
                word_counts[word.lower()] += 1
        
        # Find most common prefixes (likely screenshot patterns)
        top_prefixes = sorted(prefix_counts.items(), key=lambda x: x[1], reverse=True)[:20]
        top_suffixes = sorted(suffix_counts.items(), key=lambda x: x[1], reverse=True)[:20]
        top_words = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)[:30]
        
        # Identify likely screenshot patterns
        likely_screenshot_patterns = []
        
        # Patterns that contain date/time + screenshot words
        for filename in patterns['has_date_time']:
            name_lower = filename.lower()
            if any(word in name_lower for word in screenshot_words):
                likely_screenshot_patterns.append(filename)
        
        # Patterns with screenshot words + sequential numbers
        for filename in patterns['has_common_words']:
            if any(char.isdigit() for char in filename):
                likely_screenshot_patterns.append(filename)
        
        # Print analysis results
        print(f"\n📊 PATTERN SUMMARY:")
        print(f"  Files with date+time: {len(patterns['has_date_time']):,} ({len(patterns['has_date_time'])/total_files*100:.1f}%)")
        print(f"  Files with date only: {len(patterns['has_date_only']):,} ({len(patterns['has_date_only'])/total_files*100:.1f}%)")
        print(f"  Files with UUID: {len(patterns['has_uuid']):,} ({len(patterns['has_uuid'])/total_files*100:.1f}%)")
        print(f"  Files with hash-like names: {len(patterns['has_hash']):,} ({len(patterns['has_hash'])/total_files*100:.1f}%)")
        print(f"  Files with sequential numbers: {len(patterns['has_sequential']):,} ({len(patterns['has_sequential'])/total_files*100:.1f}%)")
        print(f"  Files with screenshot-related words: {len(patterns['has_common_words']):,} ({len(patterns['has_common_words'])/total_files*100:.1f}%)")
        print(f"  Short names (<5 chars): {len(patterns['short_names']):,} ({len(patterns['short_names'])/total_files*100:.1f}%)")
        print(f"  Long names (>30 chars): {len(patterns['long_names']):,} ({len(patterns['long_names'])/total_files*100:.1f}%)")
        
        print(f"\n🔝 TOP 10 COMMON PREFIXES:")
        for prefix, count in top_prefixes[:10]:
            percentage = (count / total_files * 100) if total_files > 0 else 0
            print(f"  '{prefix}': {count:,} files ({percentage:.1f}%)")
        
        print(f"\n🔝 TOP 10 COMMON SUFFIXES:")
        for suffix, count in top_suffixes[:10]:
            percentage = (count / total_files * 100) if total_files > 0 else 0
            print(f"  '{suffix}': {count:,} files ({percentage:.1f}%)")
        
        print(f"\n🔝 TOP 15 COMMON WORDS:")
        for word, count in top_words[:15]:
            percentage = (count / total_files * 100) if total_files > 0 else 0
            print(f"  '{word}': {count:,} files ({percentage:.1f}%)")
        
        # Identify discovered screenshot patterns
        print(f"\n📸 LIKELY SCREENSHOT PATTERNS DISCOVERED:")
        if likely_screenshot_patterns:
            # Group by pattern type
            screenshot_pattern_types = defaultdict(list)
            for filename in likely_screenshot_patterns[:50]:  # Sample up to 50
                name_without_ext = Path(filename).stem
                
                # Categorize pattern
                if re.search(r'\d{4}-\d{2}-\d{2}.*\d+\.\d+\.\d+', filename):
                    screenshot_pattern_types['date_time_formatted'].append(filename)
                elif re.search(r'screenshot.*\d', filename, re.IGNORECASE):
                    screenshot_pattern_types['screenshot_numbered'].append(filename)
                elif re.search(r'img.*\d', filename, re.IGNORECASE):
                    screenshot_pattern_types['img_numbered'].append(filename)
                else:
                    screenshot_pattern_types['other'].append(filename)
            
            for pattern_type, examples in screenshot_pattern_types.items():
                if examples:
                    print(f"\n  {pattern_type.upper()}:")
                    for example in examples[:5]:
                        print(f"    • {example}")
                    if len(examples) > 5:
                        print(f"    ... and {len(examples) - 5} more")
        else:
            print("  No obvious screenshot patterns detected from analysis")
        
        # Generate regex patterns from discovered patterns
        discovered_patterns = []
        
        # Pattern 1: Date-time with screenshot word
        if patterns['has_date_time'] and patterns['has_common_words']:
            # Look for common format
            date_time_examples = [f for f in patterns['has_date_time'] if any(w in f.lower() for w in screenshot_words)][:10]
            if date_time_examples:
                discovered_patterns.append({
                    'type': 'screenshot_date_time',
                    'description': 'Files with date-time stamps and screenshot-related words',
                    'examples': date_time_examples[:5]
                })
        
        # Pattern 2: Screenshot + sequential numbers
        sequential_screenshot = [f for f in patterns['has_sequential'] if any(w in f.lower() for w in screenshot_words)]
        if sequential_screenshot:
            discovered_patterns.append({
                'type': 'screenshot_sequential',
                'description': 'Files with screenshot words and sequential numbers',
                'examples': sequential_screenshot[:5]
            })
        
        # Pattern 3: IMG + numbers pattern
        img_patterns = [f for f in all_filenames if re.match(r'^IMG[_\-]\d+', f, re.IGNORECASE)]
        if img_patterns:
            discovered_patterns.append({
                'type': 'img_sequential',
                'description': 'Files starting with IMG followed by numbers',
                'examples': img_patterns[:5]
            })
        
        print(f"\n💡 DISCOVERED SCREENSHOT PATTERNS:")
        for idx, pattern_info in enumerate(discovered_patterns, 1):
            print(f"\n  Pattern {idx}: {pattern_info['description']}")
            print(f"    Examples:")
            for example in pattern_info['examples']:
                print(f"      • {example}")
        
        # Return analysis results
        return {
            'patterns': patterns,
            'top_prefixes': top_prefixes,
            'top_suffixes': top_suffixes,
            'top_words': top_words,
            'likely_screenshot_patterns': likely_screenshot_patterns,
            'discovered_patterns': discovered_patterns,
            'total_files': total_files
        }
    
    def run(self, analyze_patterns: bool = False):
        """Main execution logic."""
        print("📊 Obsidian Attachment Statistics Tool")
        print(f"Vault: {self.vault_path}")
        print("=" * 70)
        
        # Check if Attachments folder exists
        if not self.attachments_path.exists():
            print(f"\n❌ Attachments folder not found: {self.attachments_path}")
            return
        
        # Analyze attachments
        self.analyze_attachments()
        
        # Print statistics
        self.print_statistics()
        
        # Analyze filename patterns if requested
        if analyze_patterns:
            self.analyze_filename_patterns()


def main():
    parser = argparse.ArgumentParser(
        description="Print detailed statistics about Obsidian attachments",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run with default vault path
  python attachment_stats.py
  
  # Run with custom vault path
  python attachment_stats.py --vault /Users/jose/obsidian/JC
        """
    )
    
    parser.add_argument(
        '--vault',
        type=str,
        default='/Users/jose/obsidian/JC',
        help='Path to Obsidian vault (default: /Users/jose/obsidian/JC)'
    )
    
    parser.add_argument(
        '--analyze-patterns',
        action='store_true',
        help='Analyze filename patterns to identify screenshot patterns'
    )
    
    args = parser.parse_args()
    
    # Validate vault path
    vault_path = Path(args.vault)
    if not vault_path.exists():
        print(f"Error: Vault path does not exist: {vault_path}")
        return 1
    
    if not vault_path.is_dir():
        print(f"Error: Vault path is not a directory: {vault_path}")
        return 1
    
    # Run statistics
    stats = AttachmentStats(vault_path)
    stats.run(analyze_patterns=args.analyze_patterns)
    
    return 0


if __name__ == "__main__":
    exit(main())

