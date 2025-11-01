#!/usr/bin/env python3
"""
Obsidian Attachment Statistics Tool

Scans Obsidian vault's Attachments folder and prints detailed statistics about
file sizes, including breakdown by file type.
"""

import argparse
from pathlib import Path
from typing import Dict, List
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
                print(f"  Processed {idx}/{self.total_files} files...")
            
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
    
    def run(self):
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
    stats.run()
    
    return 0


if __name__ == "__main__":
    exit(main())

