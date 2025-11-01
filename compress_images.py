#!/usr/bin/env python3
"""
Obsidian Image Compression Tool

Scans Obsidian vault's Attachments folder and subfolders for images larger than 500KB,
then compresses them while maintaining fair screen resolution.
"""

import argparse
import os
import random
import re
import shutil
from pathlib import Path
from typing import List, Tuple
from datetime import datetime

try:
    from PIL import Image
except ImportError:
    print("⚠️  Error: Pillow library not installed.")
    print("   Install with: pip install pillow")
    raise


class ImageCompressor:
    """Main class for finding and compressing large images in Obsidian attachments."""
    
    def __init__(self, vault_path: str, size_threshold_kb: int = 500, dry_run: bool = True):
        self.vault_path = Path(vault_path)
        self.attachments_path = self.vault_path / "Attachments"
        self.size_threshold_kb = size_threshold_kb
        self.size_threshold_bytes = size_threshold_kb * 1024
        self.dry_run = dry_run
        
        # Image file extensions to process
        self.image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif', '.webp', '.heic', '.heif'}
        
        # Trash path
        self.trash_path = self.vault_path / ".trash"
        self.trash_path.mkdir(exist_ok=True)
        
        # Central backup directory
        self.backup_path = self.vault_path / "Attachments" / "backup"
        
        # Statistics
        self.stats = {
            'images_scanned': 0,
            'large_images_found': 0,
            'images_compressed': 0,
            'compression_failed': 0,
            'space_saved_mb': 0.0,
            'references_updated': 0
        }
    
    def get_all_images(self) -> List[Path]:
        """Get all image files from the Attachments folder and subfolders."""
        if not self.attachments_path.exists():
            return []
        
        images = []
        for img_file in self.attachments_path.rglob("*"):
            # Skip the backup folder
            if 'backup' in img_file.parts:
                continue
            if img_file.is_file() and any(img_file.suffix.lower() == ext for ext in self.image_extensions):
                images.append(img_file)
        
        return images
    
    def format_size(self, bytes_size: float) -> str:
        """Format file size in human-readable format."""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if bytes_size < 1024.0:
                return f"{bytes_size:.2f} {unit}"
            bytes_size /= 1024.0
        return f"{bytes_size:.2f} TB"
    
    def get_image_info(self, img_path: Path) -> Tuple[int, int]:
        """Get image dimensions."""
        try:
            with Image.open(img_path) as img:
                return img.size  # (width, height)
        except Exception as e:
            print(f"  ⚠️  Error reading image info: {e}")
            return (0, 0)
    
    def get_all_notes(self) -> List[Path]:
        """Get all markdown files in the vault."""
        notes = []
        for md_file in self.vault_path.rglob("*.md"):
            # Skip hidden directories and trash
            if any(part.startswith('.') for part in md_file.parts):
                if '.trash' not in str(md_file) and '.obsidian' not in str(md_file):
                    continue
            notes.append(md_file)
        return notes
    
    def update_note_references(self, old_filename: str, new_filename: str):
        """Update image references in all notes when filename changes."""
        notes = self.get_all_notes()
        updated_count = 0
        
        for note in notes:
            try:
                content = note.read_text(encoding='utf-8', errors='ignore')
                original_content = content
                
                # Update Obsidian-style references: ![[image.HEIC]] -> ![[image.jpg]]
                # Also handle aliases: ![[image.HEIC|alt text]]
                content = re.sub(
                    re.escape(f"![[{old_filename}") + r"(\|[^\]]*)?\]\]",
                    f"![[{new_filename}\\1]]",
                    content
                )
                
                # Update markdown-style image references: ![alt](path/to/image.HEIC)
                # Also update links in markdown: [text](path/to/image.HEIC)
                # Pattern: ](path/to/image.HEIC)
                content = re.sub(
                    r'(]\([^)]*)' + re.escape(old_filename) + r'([)])',
                    r'\1' + new_filename + r'\2',
                    content
                )
                
                # Write back if changed
                if content != original_content:
                    note.write_text(content, encoding='utf-8')
                    updated_count += 1
            except Exception as e:
                print(f"  ⚠️  Error updating note {note}: {e}")
        
        if updated_count > 0:
            self.stats['references_updated'] += updated_count
            print(f"  📝 Updated references in {updated_count} note(s)")
    
    def compress_image(self, img_path: Path) -> bool:
        """
        Compress an image while maintaining fair screen resolution.
        Returns True if compression was successful.
        """
        try:
            # Get original size
            original_size = img_path.stat().st_size
            original_size_mb = original_size / (1024 * 1024)
            
            # Open and get image info
            with Image.open(img_path) as img:
                width, height = img.size
                
                # Get format - prefer from image metadata, fall back to extension
                pillow_format = img.format
                file_ext = img_path.suffix.lower()
                
                # Map common formats
                format_map = {
                    'JPEG': 'JPEG',
                    'JPG': 'JPEG',
                    'PNG': 'PNG',
                    'GIF': 'GIF',
                    'WEBP': 'WEBP',
                    'TIFF': 'TIFF',
                    'BMP': 'BMP',
                    'HEIC': 'HEIC',
                    'HEIF': 'HEIF'
                }
                
                # Determine format name for saving
                if pillow_format and pillow_format.upper() in format_map:
                    format_name = format_map[pillow_format.upper()]
                elif file_ext:
                    # Map from extension
                    ext_to_format = {
                        '.jpg': 'JPEG', '.jpeg': 'JPEG',
                        '.png': 'PNG',
                        '.gif': 'GIF',
                        '.webp': 'WEBP',
                        '.tiff': 'TIFF', '.tif': 'TIFF',
                        '.bmp': 'BMP',
                        '.heic': 'HEIC', '.heif': 'HEIF'
                    }
                    # Default to JPEG, but preserve PNG if that's what the file is
                    if file_ext == '.png':
                        format_name = 'PNG'
                    else:
                        format_name = ext_to_format.get(file_ext, 'JPEG')  # Default to JPEG
                else:
                    format_name = 'JPEG'
                
                format_name_lower = format_name.lower()
                
                print(f"  📷 Original: {width}x{height}, {self.format_size(original_size)}")
                
                # Calculate new dimensions for fair screen resolution
                # Target: Max 1440px on longest side (optimal for on-screen reading)
                max_dimension = 1440
                
                if width > height:
                    if width > max_dimension:
                        new_width = max_dimension
                        new_height = int(height * (max_dimension / width))
                    else:
                        new_width = width
                        new_height = height
                else:
                    if height > max_dimension:
                        new_height = max_dimension
                        new_width = int(width * (max_dimension / height))
                    else:
                        new_width = width
                        new_height = height
                
                # Resize if needed
                if new_width != width or new_height != height:
                    img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                    print(f"  🔧 Resized to: {new_width}x{new_height}")
                
                # Handle different image formats - PRESERVE original format and extension
                if format_name_lower in ['jpeg', 'jpg']:
                    quality = 85  # Good balance for JPEG
                    save_kwargs = {'quality': quality, 'optimize': True}
                elif format_name_lower == 'png':
                    # PNG compression - use maximum compression level
                    # IMPORTANT: PNG files MUST remain PNG format - NEVER convert to JPEG or any other format
                    # Also optimize color mode: convert RGBA to RGB if no transparency needed (still PNG format)
                    has_transparency = img.mode in ('RGBA', 'LA') or 'transparency' in img.info
                    
                    # Ensure format stays PNG (prevent any accidental conversion)
                    format_name = 'PNG'
                    format_name_lower = 'png'
                    
                    # Convert RGBA/LA to RGB if no actual transparency exists
                    if img.mode in ('RGBA', 'LA'):
                        # Check if image actually uses alpha channel (any pixel with alpha < 255)
                        # Use sampling for large images to avoid checking every pixel
                        try:
                            alpha_channel_index = 3 if img.mode == 'RGBA' else 1
                            alpha = img.split()[alpha_channel_index]
                            
                            # For efficiency, sample pixels for large images
                            alpha_data = list(alpha.getdata())
                            sample_size = min(10000, len(alpha_data))  # Check up to 10k pixels
                            if len(alpha_data) > sample_size:
                                sample_indices = random.sample(range(len(alpha_data)), sample_size)
                                sample_values = [alpha_data[i] for i in sample_indices]
                            else:
                                sample_values = alpha_data
                            
                            # Check if any sampled pixel has transparency (alpha < 255)
                            has_alpha_content = any(p < 255 for p in sample_values)
                            
                            if not has_alpha_content:
                                # No actual transparency, convert to RGB for better compression
                                rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                                if img.mode == 'RGBA':
                                    rgb_img.paste(img, mask=img.split()[3])
                                else:
                                    rgb_img.paste(img)
                                img = rgb_img
                                print(f"  🔄 Converted RGBA to RGB (no transparency detected)")
                        except Exception as e:
                            # If alpha detection fails, keep original mode
                            print(f"  ⚠️  Could not check alpha channel: {e}, keeping original mode")
                    
                    # Use maximum compression level (9) for PNG
                    # IMPORTANT: PNG files MUST remain PNG format - never convert to JPEG
                    save_kwargs = {'optimize': True, 'compress_level': 9}
                elif format_name_lower == 'webp':
                    quality = 85
                    save_kwargs = {'quality': quality, 'method': 6}
                elif format_name_lower == 'gif':
                    # For GIFs, keep as GIF
                    save_kwargs = {'optimize': True}
                elif format_name_lower in ['heic', 'heif']:
                    # Convert HEIC/HEIF to JPEG (Pillow doesn't support saving HEIC)
                    format_name = 'JPEG'
                    format_name_lower = 'jpeg'
                    save_kwargs = {'quality': 85, 'optimize': True}
                elif format_name_lower in ['bmp', 'tiff', 'tif']:
                    # Keep original format
                    save_kwargs = {'optimize': True}
                else:
                    # For other formats, try default optimization
                    save_kwargs = {'optimize': True}
                
                # Create backup path in central backup directory
                # Get relative path from attachments to preserve subfolder structure
                rel_path = img_path.relative_to(self.attachments_path)
                backup_path = self.backup_path / rel_path
                backup_path = self._get_unique_backup_path(backup_path)
                
                # Determine output extension based on final format
                # HEIC/HEIF gets converted to JPEG with .jpg extension
                # IMPORTANT: PNG files MUST keep .png extension - never convert to JPEG
                if format_name_lower in ['jpeg', 'jpg'] and img_path.suffix.lower() in ['.heic', '.heif']:
                    output_ext = '.jpg'
                elif img_path.suffix.lower() == '.png':
                    # Force PNG extension - never change PNG files to other formats
                    output_ext = '.png'
                    format_name = 'PNG'  # Ensure format stays PNG
                else:
                    output_ext = img_path.suffix  # Preserve original extension
                
                # Save compressed version to a temporary file first
                compressed_path = img_path.parent / f"{img_path.stem}_compressed{output_ext}"
                img.save(str(compressed_path), format=format_name, **save_kwargs)
                
                # Check if compression actually reduced size
                compressed_size = compressed_path.stat().st_size
                compression_ratio = (1 - compressed_size / original_size) * 100
                
                print(f"  📦 Compressed: {self.format_size(compressed_size)} ({compression_ratio:.1f}% reduction)")
                
                if compressed_size < original_size:
                    # Success! Replace original with compressed version
                    if not self.dry_run:
                        # Move original to backup
                        shutil.move(str(img_path), str(backup_path))
                        
                        # Replace with compressed version
                        # If extension changed (e.g., HEIC->JPG), update the filename and references
                        if output_ext.lower() != img_path.suffix.lower():
                            final_path = img_path.parent / f"{img_path.stem}{output_ext}"
                            shutil.move(str(compressed_path), str(final_path))
                            print(f"  🔄 Format changed from {img_path.suffix} to {output_ext}")
                            
                            # Update references in markdown notes
                            old_filename = img_path.name
                            new_filename = final_path.name
                            self.update_note_references(old_filename, new_filename)
                        else:
                            shutil.move(str(compressed_path), str(img_path))
                        
                        # Optionally remove backup after verification
                        # (keeping it for safety)
                        # backup_path.unlink()
                    else:
                        # In dry run, clean up the test compressed file
                        compressed_path.unlink()
                    
                    # Calculate space saved
                    space_saved = original_size - compressed_size
                    self.stats['space_saved_mb'] += space_saved / (1024 * 1024)
                    
                    print(f"  ✅ Success: Saved {self.format_size(space_saved)}")
                    if not self.dry_run:
                        backup_rel = backup_path.relative_to(self.vault_path)
                        print(f"  🔒 Backup saved: {backup_rel}")
                    return True
                else:
                    # Compression didn't help, remove the compressed file
                    compressed_path.unlink()
                    print(f"  ℹ️  Compression didn't reduce size, keeping original")
                    return False
                    
        except Exception as e:
            print(f"  ❌ Compression failed: {e}")
            return False
    
    def _get_unique_backup_path(self, path: Path) -> Path:
        """Get a unique backup path if the original exists."""
        # Ensure parent directory exists
        path.parent.mkdir(parents=True, exist_ok=True)
        
        if not path.exists():
            return path
        
        counter = 1
        stem = path.stem
        suffix = path.suffix
        parent = path.parent
        
        while path.exists():
            path = parent / f"{stem}_{counter}{suffix}"
            counter += 1
        
        return path
    
    def run(self):
        """Main execution logic."""
        print("🖼️  Obsidian Image Compression Tool")
        print(f"Vault: {self.vault_path}")
        print(f"Size threshold: {self.size_threshold_kb} KB")
        print("=" * 60)
        
        # Check if Attachments folder exists
        if not self.attachments_path.exists():
            print(f"\n❌ Attachments folder not found: {self.attachments_path}")
            return
        
        # Get all images
        print("\n📸 Scanning for images...")
        images = self.get_all_images()
        self.stats['images_scanned'] = len(images)
        print(f"Found {len(images)} image(s)")
        
        if not images:
            print("\n✅ No images found!")
            return
        
        # Filter large images
        print(f"\n🔍 Finding images larger than {self.size_threshold_kb} KB...")
        large_images = []
        for img in images:
            size = img.stat().st_size
            if size > self.size_threshold_bytes:
                large_images.append(img)
        
        self.stats['large_images_found'] = len(large_images)
        
        if not large_images:
            print("\n✅ No large images found to compress!")
            return
        
        print(f"\nFound {len(large_images)} large image(s):")
        for idx, img in enumerate(large_images, 1):
            size = img.stat().st_size
            print(f"  {idx}. {img.relative_to(self.attachments_path)} ({self.format_size(size)})")
        
        # Ask for confirmation
        print("\n" + "=" * 60)
        print("⚠️  CONFIRMATION REQUIRED")
        print("=" * 60)
        
        if self.dry_run:
            print("\n⚠️  DRY RUN MODE: No files will be modified.")
        else:
            print("\nThe script will compress these images while maintaining screen quality.")
            print("Original files will be backed up with '_backup' suffix.")
            print("\nWould you like to proceed? (yes/no): ", end='')
            response = input().strip().lower()
            
            if response not in ['yes', 'y']:
                print("\n❌ Compression cancelled by user.")
                return
        
        # Compress images
        print("\n🗜️  Compressing images...")
        print()
        
        for idx, img_path in enumerate(large_images, 1):
            print(f"{'=' * 60}")
            print(f"[{idx}/{len(large_images)}] {idx*100//len(large_images)}%")
            print(f"📄 {img_path.relative_to(self.attachments_path)}")
            print(f"{'=' * 60}")
            
            if self.compress_image(img_path):
                self.stats['images_compressed'] += 1
            else:
                self.stats['compression_failed'] += 1
            
            print()
        
        # Final summary
        print("=" * 60)
        print("📊 COMPRESSION SUMMARY")
        print("=" * 60)
        print(f"  • Images scanned: {self.stats['images_scanned']}")
        print(f"  • Large images found: {self.stats['large_images_found']}")
        print(f"  • Images compressed: {self.stats['images_compressed']}")
        print(f"  • Compression failed: {self.stats['compression_failed']}")
        print(f"  • Space saved: {self.format_size(self.stats['space_saved_mb'] * 1024 * 1024)}")
        if self.stats.get('references_updated', 0) > 0:
            print(f"  • References updated: {self.stats['references_updated']}")
        print("=" * 60)
        
        if self.dry_run:
            print("\n⚠️  This was a DRY RUN. Run with --no-dry-run to actually compress files.")


def main():
    parser = argparse.ArgumentParser(
        description="Compress large images in Obsidian attachments while maintaining fair screen resolution",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run (preview only, safe default)
  python compress_images.py --vault /Users/jose/obsidian/JC
  
  # Actually compress images (prompts for confirmation)
  python compress_images.py --vault /Users/jose/obsidian/JC --no-dry-run
  
  # Custom size threshold (e.g., 1 MB)
  python compress_images.py --vault /Users/jose/obsidian/JC --threshold 1024
  
  # Simple run with default vault path
  python compress_images.py

Requirements:
  pip install pillow

Supported formats: JPG, PNG, GIF, BMP, TIFF, WEBP, HEIC/HEIF

The script will:
  1. Find all images larger than the threshold (default: 500KB)
  2. Resize to max 2048px on longest side (good screen resolution)
  3. Apply appropriate compression based on format
  4. Create backups of originals
  5. Replace originals with compressed versions
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
        help='Size threshold in KB (default: 500 KB)'
    )
    
    parser.add_argument(
        '--no-dry-run',
        action='store_true',
        help='Allow actual compression (prompts for confirmation). Default is dry-run mode.'
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
    
    # Run compression
    compressor = ImageCompressor(
        vault_path, 
        size_threshold_kb=args.threshold,
        dry_run=not args.no_dry_run
    )
    compressor.run()
    
    return 0


if __name__ == "__main__":
    exit(main())

