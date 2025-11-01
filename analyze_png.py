#!/usr/bin/env python3
"""
PNG File Analysis Tool

Analyzes PNG files to understand why they cannot be compressed further
and suggests optimization options to reduce file sizes.
"""

import argparse
from pathlib import Path
from typing import List, Dict, Tuple
from collections import defaultdict

try:
    from PIL import Image
except ImportError:
    print("⚠️  Error: Pillow library not installed.")
    print("   Install with: pip install pillow")
    raise


class PNGAnalyzer:
    """Main class for analyzing PNG files in detail."""
    
    def __init__(self, vault_path: str, size_threshold_kb: int = 500):
        self.vault_path = Path(vault_path)
        self.attachments_path = self.vault_path / "Attachments"
        self.size_threshold_kb = size_threshold_kb
        self.size_threshold_bytes = size_threshold_kb * 1024
        
        # Statistics
        self.stats = {
            'total_pngs': 0,
            'large_pngs': 0,
            'rgba_pngs': 0,
            'rgb_pngs': 0,
            'palette_pngs': 0,
            'grayscale_pngs': 0,
            'with_alpha': 0,
            'without_alpha': 0,
            '16bit_pngs': 0,
            '8bit_pngs': 0,
        }
        
        self.png_files = []
        self.analysis_results = []
    
    def get_all_pngs(self) -> List[Path]:
        """Get all PNG files from the Attachments folder."""
        if not self.attachments_path.exists():
            return []
        
        pngs = []
        for file in self.attachments_path.rglob("*.png"):
            # Skip backup folders
            if 'backup' in file.parts:
                continue
            if file.is_file():
                pngs.append(file)
        
        return pngs
    
    def format_size(self, bytes_size: float) -> str:
        """Format file size in human-readable format."""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if bytes_size < 1024.0:
                return f"{bytes_size:.2f} {unit}"
            bytes_size /= 1024.0
        return f"{bytes_size:.2f} TB"
    
    def check_alpha_usage(self, img: Image.Image) -> Tuple[bool, bool]:
        """
        Check if image has alpha channel and if it's actually used.
        Returns: (has_alpha_channel, alpha_is_used)
        """
        has_alpha = img.mode in ('RGBA', 'LA', 'PA')
        alpha_used = False
        
        if has_alpha:
            try:
                if img.mode == 'RGBA':
                    alpha = img.split()[3]
                elif img.mode == 'LA':
                    alpha = img.split()[1]
                elif img.mode == 'PA':
                    # Palette with alpha - convert to RGBA to check
                    alpha = img.convert('RGBA').split()[3]
                else:
                    return (has_alpha, False)
                
                # Sample pixels to check if alpha is used (for efficiency)
                alpha_data = list(alpha.getdata())
                sample_size = min(10000, len(alpha_data))
                
                if len(alpha_data) > sample_size:
                    import random
                    sample_indices = random.sample(range(len(alpha_data)), sample_size)
                    sample_values = [alpha_data[i] for i in sample_indices]
                else:
                    sample_values = alpha_data
                
                # Check if any pixel has transparency (alpha < 255)
                alpha_used = any(p < 255 for p in sample_values)
            except Exception:
                alpha_used = True  # Assume used if we can't check
        
        return (has_alpha, alpha_used)
    
    def calculate_theoretical_size(self, width: int, height: int, mode: str) -> int:
        """Calculate theoretical uncompressed size based on dimensions and color mode."""
        bits_per_pixel = {
            '1': 1,      # 1-bit
            'L': 8,      # Grayscale 8-bit
            'P': 8,      # Palette 8-bit
            'RGB': 24,   # RGB 8-bit per channel
            'RGBA': 32,  # RGBA 8-bit per channel
            'LA': 16,    # Grayscale with alpha
            'PA': 16,    # Palette with alpha
        }
        
        # Get bits per pixel for mode
        bpp = bits_per_pixel.get(mode, 24)  # Default to RGB
        
        # Calculate size in bytes
        total_bits = width * height * bpp
        total_bytes = total_bits // 8
        
        return total_bytes
    
    def analyze_png(self, png_path: Path) -> Dict:
        """Analyze a single PNG file and return detailed information."""
        try:
            file_size = png_path.stat().st_size
            
            with Image.open(png_path) as img:
                width, height = img.size
                mode = img.mode
                
                # Get image info
                info = img.info.copy() if img.info else {}
                
                # Check alpha channel
                has_alpha, alpha_used = self.check_alpha_usage(img)
                
                # Get bit depth from mode
                is_16bit = False
                if mode in ('I;16', 'I', 'F'):  # 16-bit integer or float
                    is_16bit = True
                
                # Calculate theoretical size
                theoretical_size = self.calculate_theoretical_size(width, height, mode)
                compression_ratio = (1 - file_size / theoretical_size) * 100 if theoretical_size > 0 else 0
                
                # Analyze what optimizations are possible
                optimizations = []
                potential_savings = 0
                
                # Check 1: RGBA without alpha usage -> convert to RGB
                if has_alpha and not alpha_used:
                    rgb_theoretical = self.calculate_theoretical_size(width, height, 'RGB')
                    rgb_estimate = int(file_size * (rgb_theoretical / theoretical_size))
                    savings = file_size - rgb_estimate
                    if savings > 0:
                        optimizations.append({
                            'type': 'RGBA_TO_RGB',
                            'description': 'Convert RGBA to RGB (alpha channel not used)',
                            'current_size': file_size,
                            'estimated_size': rgb_estimate,
                            'potential_savings': savings,
                            'savings_percent': (savings / file_size * 100) if file_size > 0 else 0
                        })
                        potential_savings += savings
                
                # Check 2: Large dimensions -> resize
                max_dimension = 2048
                if width > max_dimension or height > max_dimension:
                    if width > height:
                        new_width = max_dimension
                        new_height = int(height * (max_dimension / width))
                    else:
                        new_height = max_dimension
                        new_width = int(width * (max_dimension / height))
                    
                    # Estimate new size (proportional to area reduction)
                    area_reduction = (new_width * new_height) / (width * height)
                    estimated_size = int(file_size * area_reduction)
                    savings = file_size - estimated_size
                    
                    if savings > 0:
                        optimizations.append({
                            'type': 'RESIZE',
                            'description': f'Resize from {width}x{height} to {new_width}x{new_height}',
                            'current_size': file_size,
                            'estimated_size': estimated_size,
                            'potential_savings': savings,
                            'savings_percent': (savings / file_size * 100) if file_size > 0 else 0
                        })
                        potential_savings += savings
                
                # Check 3: 16-bit -> 8-bit (if applicable)
                if is_16bit:
                    # Estimate 8-bit version would be roughly half the size
                    estimated_size = int(file_size * 0.5)
                    savings = file_size - estimated_size
                    optimizations.append({
                        'type': 'BIT_DEPTH',
                        'description': 'Convert 16-bit to 8-bit (may lose precision)',
                        'current_size': file_size,
                        'estimated_size': estimated_size,
                        'potential_savings': savings,
                        'savings_percent': (savings / file_size * 100) if file_size > 0 else 0,
                        'warning': 'May lose color precision'
                    })
                    potential_savings += savings
                
                # Check 4: Check current compression level
                compression_level = info.get('compression', None)
                if compression_level is not None and compression_level < 9:
                    optimizations.append({
                        'type': 'COMPRESSION_LEVEL',
                        'description': f'Increase compression level from {compression_level} to 9',
                        'current_size': file_size,
                        'estimated_size': int(file_size * 0.95),  # Rough estimate
                        'potential_savings': int(file_size * 0.05),
                        'savings_percent': 5.0,
                        'note': 'Small improvement expected'
                    })
                
                # Check 5: Palette mode optimization
                if mode == 'P':
                    # Check if we can optimize palette
                    optimizations.append({
                        'type': 'PALETTE_OPTIMIZE',
                        'description': 'Optimize color palette (reduce unused colors)',
                        'current_size': file_size,
                        'estimated_size': int(file_size * 0.90),  # Rough estimate
                        'potential_savings': int(file_size * 0.10),
                        'savings_percent': 10.0,
                        'note': 'May reduce color accuracy slightly'
                    })
                
                return {
                    'path': png_path,
                    'relative_path': png_path.relative_to(self.attachments_path),
                    'file_size': file_size,
                    'width': width,
                    'height': height,
                    'mode': mode,
                    'has_alpha': has_alpha,
                    'alpha_used': alpha_used,
                    'is_16bit': is_16bit,
                    'theoretical_size': theoretical_size,
                    'compression_ratio': compression_ratio,
                    'pixels': width * height,
                    'bytes_per_pixel': file_size / (width * height) if (width * height) > 0 else 0,
                    'optimizations': optimizations,
                    'total_potential_savings': potential_savings,
                    'info': info
                }
        except Exception as e:
            return {
                'path': png_path,
                'relative_path': png_path.relative_to(self.attachments_path),
                'error': str(e)
            }
    
    def analyze_all(self):
        """Analyze all PNG files."""
        print("🔍 Scanning for PNG files...")
        pngs = self.get_all_pngs()
        self.stats['total_pngs'] = len(pngs)
        
        if not pngs:
            print("❌ No PNG files found!")
            return
        
        print(f"Found {len(pngs)} PNG file(s)")
        print("\n📊 Analyzing PNG files...")
        
        large_pngs = []
        for idx, png in enumerate(pngs, 1):
            if idx % 20 == 0:
                print(f"  Processed {idx}/{len(pngs)} files...")
            
            analysis = self.analyze_png(png)
            
            if 'error' not in analysis:
                file_size = analysis['file_size']
                
                # Update statistics
                if analysis['has_alpha']:
                    self.stats['rgba_pngs'] += 1
                    if analysis['alpha_used']:
                        self.stats['with_alpha'] += 1
                    else:
                        self.stats['without_alpha'] += 1
                else:
                    if analysis['mode'] == 'RGB':
                        self.stats['rgb_pngs'] += 1
                    elif analysis['mode'] == 'P':
                        self.stats['palette_pngs'] += 1
                    elif analysis['mode'] in ('L', 'LA'):
                        self.stats['grayscale_pngs'] += 1
                
                if analysis['is_16bit']:
                    self.stats['16bit_pngs'] += 1
                else:
                    self.stats['8bit_pngs'] += 1
                
                if file_size > self.size_threshold_bytes:
                    self.stats['large_pngs'] += 1
                    large_pngs.append(analysis)
            
            self.analysis_results.append(analysis)
        
        # Sort large PNGs by potential savings
        large_pngs.sort(key=lambda x: x.get('total_potential_savings', 0), reverse=True)
        self.large_pngs = large_pngs
    
    def print_summary(self):
        """Print summary statistics."""
        print("\n" + "=" * 80)
        print("📊 PNG FILE ANALYSIS SUMMARY")
        print("=" * 80)
        
        print(f"\n📈 Overall Statistics:")
        print(f"  • Total PNG files: {self.stats['total_pngs']:,}")
        print(f"  • Large PNG files (> {self.size_threshold_kb} KB): {self.stats['large_pngs']:,}")
        
        print(f"\n🎨 Color Mode Distribution:")
        print(f"  • RGBA (with alpha): {self.stats['rgba_pngs']:,}")
        print(f"  • RGB (no alpha): {self.stats['rgb_pngs']:,}")
        print(f"  • Palette: {self.stats['palette_pngs']:,}")
        print(f"  • Grayscale: {self.stats['grayscale_pngs']:,}")
        
        print(f"\n🔍 Alpha Channel Analysis:")
        print(f"  • Files with alpha channel: {self.stats['with_alpha']:,}")
        print(f"  • Files with unused alpha: {self.stats['without_alpha']:,}")
        
        print(f"\n📏 Bit Depth:")
        print(f"  • 8-bit: {self.stats['8bit_pngs']:,}")
        print(f"  • 16-bit: {self.stats['16bit_pngs']:,}")
    
    def print_detailed_analysis(self):
        """Print detailed analysis of large PNG files."""
        if not self.large_pngs:
            print("\n✅ No large PNG files found!")
            return
        
        print("\n" + "=" * 80)
        print(f"🔍 DETAILED ANALYSIS OF {len(self.large_pngs)} LARGE PNG FILES")
        print("=" * 80)
        
        total_current_size = 0
        total_potential_savings = 0
        
        for idx, png in enumerate(self.large_pngs, 1):
            total_current_size += png['file_size']
            total_potential_savings += png.get('total_potential_savings', 0)
            
            print(f"\n{'=' * 80}")
            print(f"📄 [{idx}] {png['relative_path']}")
            print(f"{'=' * 80}")
            
            print(f"\n📊 File Information:")
            print(f"  • Size: {self.format_size(png['file_size'])}")
            print(f"  • Dimensions: {png['width']} x {png['height']} pixels")
            print(f"  • Total pixels: {png['pixels']:,}")
            print(f"  • Bytes per pixel: {png['bytes_per_pixel']:.2f}")
            print(f"  • Color mode: {png['mode']}")
            print(f"  • Has alpha channel: {png['has_alpha']}")
            if png['has_alpha']:
                print(f"  • Alpha channel used: {png['alpha_used']}")
            print(f"  • Bit depth: {'16-bit' if png['is_16bit'] else '8-bit'}")
            print(f"  • Compression ratio: {png['compression_ratio']:.1f}%")
            print(f"  • Theoretical size: {self.format_size(png['theoretical_size'])}")
            
            optimizations = png.get('optimizations', [])
            if optimizations:
                print(f"\n💡 Optimization Opportunities:")
                for opt in optimizations:
                    print(f"\n  🔧 {opt['type']}: {opt['description']}")
                    print(f"     Current: {self.format_size(opt['current_size'])}")
                    print(f"     Estimated: {self.format_size(opt['estimated_size'])}")
                    print(f"     Potential savings: {self.format_size(opt['potential_savings'])} ({opt['savings_percent']:.1f}%)")
                    if 'warning' in opt:
                        print(f"     ⚠️  {opt['warning']}")
                    if 'note' in opt:
                        print(f"     ℹ️  {opt['note']}")
                
                print(f"\n  💰 Total potential savings: {self.format_size(png['total_potential_savings'])}")
            else:
                print(f"\n  ℹ️  No obvious optimization opportunities found")
                print(f"     File may already be well-optimized or contain highly detailed/complex content")
        
        print("\n" + "=" * 80)
        print("💰 OVERALL OPTIMIZATION SUMMARY")
        print("=" * 80)
        print(f"\n  Total current size: {self.format_size(total_current_size)}")
        print(f"  Total potential savings: {self.format_size(total_potential_savings)}")
        if total_current_size > 0:
            savings_percent = (total_potential_savings / total_current_size * 100)
            print(f"  Potential reduction: {savings_percent:.1f}%")
        print("=" * 80)
    
    def print_recommendations(self):
        """Print optimization recommendations."""
        print("\n" + "=" * 80)
        print("💡 RECOMMENDATIONS")
        print("=" * 80)
        
        recommendations = []
        
        # Count optimization types
        opt_counts = defaultdict(int)
        total_savings_by_type = defaultdict(int)
        
        for png in self.large_pngs:
            for opt in png.get('optimizations', []):
                opt_type = opt['type']
                opt_counts[opt_type] += 1
                total_savings_by_type[opt_type] += opt['potential_savings']
        
        if opt_counts['RGBA_TO_RGB'] > 0:
            recommendations.append({
                'priority': 'HIGH',
                'title': 'Convert RGBA to RGB',
                'count': opt_counts['RGBA_TO_RGB'],
                'savings': total_savings_by_type['RGBA_TO_RGB'],
                'description': f'{opt_counts["RGBA_TO_RGB"]} PNG files have unused alpha channels. Converting to RGB can save approximately {self.format_size(total_savings_by_type["RGBA_TO_RGB"])}.',
                'action': 'Already implemented in compress_images.py - will be applied during compression.'
            })
        
        if opt_counts['RESIZE'] > 0:
            recommendations.append({
                'priority': 'HIGH',
                'title': 'Resize large images',
                'count': opt_counts['RESIZE'],
                'savings': total_savings_by_type['RESIZE'],
                'description': f'{opt_counts["RESIZE"]} PNG files exceed 2048px. Resizing can save approximately {self.format_size(total_savings_by_type["RESIZE"])}.',
                'action': 'Already implemented in compress_images.py - will be applied during compression.'
            })
        
        if opt_counts['BIT_DEPTH'] > 0:
            recommendations.append({
                'priority': 'MEDIUM',
                'title': 'Consider 16-bit to 8-bit conversion',
                'count': opt_counts['BIT_DEPTH'],
                'savings': total_savings_by_type['BIT_DEPTH'],
                'description': f'{opt_counts["BIT_DEPTH"]} PNG files use 16-bit depth. Converting to 8-bit can save ~50% but may lose color precision.',
                'action': 'NOT RECOMMENDED for photos/graphics - only if color precision is not critical.'
            })
        
        if opt_counts['COMPRESSION_LEVEL'] > 0:
            recommendations.append({
                'priority': 'LOW',
                'title': 'Increase compression level',
                'count': opt_counts['COMPRESSION_LEVEL'],
                'savings': total_savings_by_type['COMPRESSION_LEVEL'],
                'description': f'Some PNGs may benefit from maximum compression level (9).',
                'action': 'Already using maximum compression in compress_images.py.'
            })
        
        if opt_counts['PALETTE_OPTIMIZE'] > 0:
            recommendations.append({
                'priority': 'MEDIUM',
                'title': 'Optimize color palettes',
                'count': opt_counts['PALETTE_OPTIMIZE'],
                'savings': total_savings_by_type['PALETTE_OPTIMIZE'],
                'description': f'{opt_counts["PALETTE_OPTIMIZE"]} palette PNGs can be optimized by reducing unused colors.',
                'action': 'Can be done with external tools like pngquant or optipng.'
            })
        
        if not recommendations:
            print("\n  ✅ PNG files appear to be well-optimized already.")
            print("  Most files are already compressed efficiently.")
        else:
            for rec in sorted(recommendations, key=lambda x: {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2}[x['priority']]):
                print(f"\n  [{rec['priority']}] {rec['title']}")
                print(f"     {rec['description']}")
                print(f"     Action: {rec['action']}")
    
    def run(self):
        """Main execution logic."""
        print("🔍 PNG File Analysis Tool")
        print(f"Vault: {self.vault_path}")
        print(f"Size threshold: {self.size_threshold_kb} KB")
        print("=" * 80)
        
        # Check if Attachments folder exists
        if not self.attachments_path.exists():
            print(f"\n❌ Attachments folder not found: {self.attachments_path}")
            return
        
        # Analyze PNGs
        self.analyze_all()
        
        # Print results
        self.print_summary()
        self.print_detailed_analysis()
        self.print_recommendations()


def main():
    parser = argparse.ArgumentParser(
        description="Analyze PNG files to understand compression limitations and suggest optimizations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run with default vault path
  python analyze_png.py
  
  # Run with custom vault path
  python analyze_png.py --vault /Users/jose/obsidian/JC
  
  # Custom size threshold (e.g., 1 MB)
  python analyze_png.py --threshold 1024
        """
    )
    
    parser.add_argument(
        '--vault',
        type=str,
        default='/Users/jose/obsidian/JC',
        help='Path to Obsidian vault (default: /Users/jose/obsidian/JC)'
    )
    
    parser.add_argument(
        '--threshold',
        type=int,
        default=500,
        help='Size threshold in KB for detailed analysis (default: 500 KB)'
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
    
    # Run analysis
    analyzer = PNGAnalyzer(vault_path, size_threshold_kb=args.threshold)
    analyzer.run()
    
    return 0


if __name__ == "__main__":
    exit(main())

