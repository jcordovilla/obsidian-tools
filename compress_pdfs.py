#!/usr/bin/env python3
"""
Obsidian PDF Compression Tool

Scans Obsidian vault's Attachments folder and subfolders for PDF files larger than 500KB,
then compresses them while maintaining screen readability.
"""

import argparse
import os
import random
import shutil
from pathlib import Path
from typing import List, Tuple
from io import BytesIO

try:
    import fitz  # PyMuPDF
except ImportError:
    print("⚠️  Error: PyMuPDF library not installed.")
    print("   Install with: pip install pymupdf")
    raise

try:
    from PIL import Image
except ImportError:
    print("⚠️  Error: Pillow library not installed.")
    print("   Install with: pip install pillow")
    raise


class PDFCompressor:
    """Main class for finding and compressing large PDF files in Obsidian attachments."""
    
    def __init__(self, vault_path: str, size_threshold_kb: int = 500, dry_run: bool = True):
        self.vault_path = Path(vault_path)
        self.attachments_path = self.vault_path / "Attachments"
        self.size_threshold_kb = size_threshold_kb
        self.size_threshold_bytes = size_threshold_kb * 1024
        self.dry_run = dry_run
        
        # PDF file extension
        self.pdf_extensions = {'.pdf'}
        
        # Backup directory in vault root
        self.backup_path = self.vault_path / "PDF_backups"
        
        # Statistics
        self.stats = {
            'pdfs_scanned': 0,
            'large_pdfs_found': 0,
            'pdfs_compressed': 0,
            'compression_failed': 0,
            'space_saved_mb': 0.0,
        }
    
    def get_all_pdfs(self) -> List[Path]:
        """Get all PDF files from the Attachments folder and subfolders."""
        pdfs = []
        
        # Search in Attachments folder if it exists
        if self.attachments_path.exists():
            for pdf_file in self.attachments_path.rglob("*.pdf"):
                # Skip backup folders
                if 'backup' in pdf_file.parts or 'PDF_backups' in pdf_file.parts:
                    continue
                if pdf_file.is_file():
                    pdfs.append(pdf_file)
        
        # Also search in vault root for PDFs (not just Attachments)
        for pdf_file in self.vault_path.glob("*.pdf"):
            if pdf_file.is_file():
                pdfs.append(pdf_file)
        
        # Search in vault subdirectories (but skip .obsidian, .trash, etc.)
        for pdf_file in self.vault_path.rglob("*.pdf"):
            if pdf_file.is_file():
                # Skip hidden directories and known folders
                if any(part.startswith('.') for part in pdf_file.parts):
                    if '.trash' not in str(pdf_file) and '.obsidian' not in str(pdf_file):
                        continue
                # Skip if already in Attachments or in backup folders
                if 'backup' in pdf_file.parts or 'PDF_backups' in pdf_file.parts:
                    continue
                # Skip if already added (could be in Attachments)
                if pdf_file not in pdfs:
                    pdfs.append(pdf_file)
        
        return pdfs
    
    def format_size(self, bytes_size: float) -> str:
        """Format file size in human-readable format."""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if bytes_size < 1024.0:
                return f"{bytes_size:.2f} {unit}"
            bytes_size /= 1024.0
        return f"{bytes_size:.2f} TB"
    
    def is_scanned_pdf(self, pdf_document) -> Tuple[bool, float]:
        """
        Detect if PDF is scanned (image-based) vs text-based.
        Returns (is_scanned, image_to_text_ratio)
        A PDF is considered scanned if it has high image-to-text ratio.
        """
        total_text_length = 0
        total_image_count = 0
        
        # Sample first 10 pages and last 10 pages to get a representative sample
        sample_pages = list(range(min(10, len(pdf_document))))
        if len(pdf_document) > 20:
            sample_pages.extend(list(range(len(pdf_document) - 10, len(pdf_document))))
        else:
            sample_pages = list(range(len(pdf_document)))
        
        for page_num in sample_pages:
            try:
                page = pdf_document[page_num]
                # Extract text
                text = page.get_text()
                total_text_length += len(text.strip())
                
                # Count images
                images = page.get_images(full=True)
                total_image_count += len(images)
            except:
                continue
        
        # If we have very little text but many images, it's likely scanned
        avg_text_per_page = total_text_length / len(sample_pages) if sample_pages else 0
        avg_images_per_page = total_image_count / len(sample_pages) if sample_pages else 0
        
        # Consider scanned if:
        # 1. Very little text (< 200 chars per page) AND at least 0.5 images per page
        # 2. OR more images per page than meaningful text (images per page > 0.8 and text < 300)
        # 3. OR ratio of images to text is very high (suggests image-based content)
        image_to_text_ratio = avg_images_per_page / (avg_text_per_page + 1)  # +1 to avoid division by zero
        is_scanned = (
            (avg_text_per_page < 200 and avg_images_per_page >= 0.5) or  # Low text, has images
            (avg_images_per_page >= 0.8 and avg_text_per_page < 300) or  # Many images, low text
            (avg_images_per_page > 0 and image_to_text_ratio > 0.005)  # High image-to-text ratio
        )
        
        return is_scanned, image_to_text_ratio
    
    def compress_pdf(self, pdf_path: Path) -> bool:
        """
        Compress a PDF file while maintaining screen readability.
        Returns True if compression was successful.
        """
        try:
            # Get original size
            original_size = pdf_path.stat().st_size
            original_size_mb = original_size / (1024 * 1024)
            
            print(f"  📄 Original size: {self.format_size(original_size)}")
            
            # Open PDF
            pdf_document = fitz.open(pdf_path)
            page_count = len(pdf_document)
            
            print(f"  📊 Pages: {page_count}")
            
            # Detect if PDF is scanned (image-based)
            is_scanned, image_ratio = self.is_scanned_pdf(pdf_document)
            
            if is_scanned:
                print(f"  📸 Detected: Scanned PDF (image-to-text ratio: {image_ratio:.4f})")
                # More aggressive settings for scanned PDFs
                target_dpi = 120  # Lower DPI for scanned docs (often over-scanned at 300+ DPI)
                image_quality = 60  # JPEG quality (balanced for text readability)
                max_image_dimension = 1600  # Increased for better text readability in scanned docs
                convert_to_grayscale = True  # Convert color scanned docs to grayscale
            else:
                print(f"  📝 Detected: Text-based PDF (image-to-text ratio: {image_ratio:.4f})")
                # Standard settings for text-based PDFs
                target_dpi = 150
                image_quality = 50
                max_image_dimension = 1024
                convert_to_grayscale = False
            
            images_compressed = 0
            images_skipped = 0  # Images where compression didn't help
            images_found = 0
            
            # Process each page
            for page_num in range(page_count):
                page = pdf_document[page_num]
                
                # Get images on this page
                image_list = page.get_images(full=True)
                images_found += len(image_list)
                
                for img_index, img in enumerate(image_list):
                    xref = img[0]
                    
                    try:
                        # Extract image
                        base_image = pdf_document.extract_image(xref)
                        original_image_bytes = base_image["image"]
                        original_image_size = len(original_image_bytes)
                        image_ext = base_image["ext"]
                        
                        # Open image with PIL
                        image = Image.open(BytesIO(original_image_bytes))
                        original_width, original_height = image.size
                        
                        # Calculate current DPI (if available)
                        current_dpi = image.info.get('dpi', (72, 72))[0]
                        
                        # Determine if we should resize this image
                        should_resize = False
                        new_width = original_width
                        new_height = original_height
                        
                        # Resize if image is too large (for screen viewing)
                        if original_width > max_image_dimension or original_height > max_image_dimension:
                            should_resize = True
                            if original_width > original_height:
                                new_width = max_image_dimension
                                new_height = int(original_height * (max_image_dimension / original_width))
                            else:
                                new_height = max_image_dimension
                                new_width = int(original_width * (max_image_dimension / original_height))
                        # Also resize if DPI is much higher than target
                        elif current_dpi > target_dpi * 1.2:  # 20% tolerance
                            should_resize = True
                            scale_factor = target_dpi / current_dpi
                            new_width = int(original_width * scale_factor)
                            new_height = int(original_height * scale_factor)
                        
                        # Always resize/resample to target dimensions for consistency
                        if should_resize:
                            image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
                        
                        # For scanned PDFs, convert to grayscale for better compression
                        if convert_to_grayscale and image.mode in ('RGB', 'RGBA', 'CMYK'):
                            # Check if image is already mostly grayscale (color variation is minimal)
                            if image.mode == 'RGB':
                                # Sample to check color variation
                                pixels = list(image.getdata())
                                sample_size = min(1000, len(pixels))
                                sample = random.sample(pixels, sample_size) if len(pixels) > sample_size else pixels
                                # Calculate color variance
                                color_variance = sum(
                                    abs(r - g) + abs(g - b) + abs(r - b) 
                                    for r, g, b in sample
                                ) / (len(sample) * 3)
                                # Convert to grayscale if color variance is low (scanned docs often have low color)
                                if color_variance < 30:  # Threshold for "mostly grayscale"
                                    image = image.convert('L').convert('RGB')  # L -> RGB for JPEG
                        
                        # Convert to JPEG for compression (unless transparency needed)
                        # For screen viewing, JPEG is usually fine
                        img_buffer = BytesIO()
                        
                        # If image has transparency, keep as PNG but compress
                        if image.mode in ('RGBA', 'LA'):
                            # Check if alpha is actually used
                            has_transparency = False
                            if image.mode == 'RGBA':
                                alpha = image.split()[3]
                                alpha_data = list(alpha.getdata())
                                # Sample every 100th pixel for efficiency
                                sample = alpha_data[::100] if len(alpha_data) > 100 else alpha_data
                                has_transparency = any(p < 255 for p in sample)
                            else:
                                has_transparency = True
                            
                            if has_transparency:
                                # Keep as PNG with compression
                                image.save(img_buffer, format="PNG", optimize=True, compress_level=9)
                            else:
                                # No transparency, convert to RGB JPEG
                                rgb_image = Image.new('RGB', image.size, (255, 255, 255))
                                rgb_image.paste(image, mask=image.split()[3] if image.mode == 'RGBA' else None)
                                rgb_image.save(img_buffer, format="JPEG", quality=image_quality, optimize=True)
                        else:
                            # Convert to appropriate mode for JPEG
                            if image.mode not in ('RGB', 'L'):
                                image = image.convert('RGB')
                            elif image.mode == 'L' and not convert_to_grayscale:
                                # For non-scanned PDFs, keep grayscale as RGB for consistency
                                image = image.convert('RGB')
                            # For scanned PDFs that are grayscale, keep as L and convert to RGB for JPEG
                            elif image.mode == 'L':
                                image = image.convert('RGB')
                            
                            image.save(img_buffer, format="JPEG", quality=image_quality, optimize=True)
                        
                        img_buffer.seek(0)
                        compressed_image_bytes = img_buffer.read()
                        compressed_image_size = len(compressed_image_bytes)
                        
                        # Only replace if compressed version is smaller
                        if compressed_image_size < original_image_size:
                            # Replace image in PDF - use stream= keyword argument
                            page.replace_image(xref, stream=compressed_image_bytes)
                            images_compressed += 1
                        else:
                            # Compressed version is larger, skip this image
                            images_skipped += 1
                        
                    except Exception as e:
                        # If image extraction/compression fails, continue with other images
                        print(f"    ⚠️  Warning: Could not compress image {img_index} on page {page_num + 1}: {e}")
                        continue
            
            if images_found > 0:
                if images_skipped > 0:
                    print(f"  🖼️  Found {images_found} image(s), compressed {images_compressed}, skipped {images_skipped} (compression didn't help)")
                else:
                    print(f"  🖼️  Found {images_found} image(s), compressed {images_compressed}")
            
            # Remove metadata to save space (keep essential info only) - do this before saving
            try:
                # Get current metadata
                metadata = pdf_document.metadata
                # Clean up metadata - keep only essentials
                pdf_document.set_metadata({
                    'title': metadata.get('title', ''),
                    'author': metadata.get('author', ''),
                    'subject': '',
                    'creator': '',
                    'producer': '',
                    'keywords': '',
                })
            except:
                pass  # Metadata cleanup is optional
            
            # Save compressed PDF to temporary file
            temp_path = pdf_path.parent / f"{pdf_path.stem}_compressed.pdf"
            
            # Use incremental save with compression and optimization
            pdf_document.save(
                str(temp_path),
                garbage=4,  # Remove unused objects (0-4, 4=max cleanup)
                deflate=1,  # Use deflate compression (1=enable)
                clean=1,  # Clean and sanitize content streams (1=enable)
                ascii=0,  # Keep binary (0=binary, smaller)
                no_new_id=1,  # Don't create new IDs (saves space)
                encryption=0,  # No encryption (0=no encryption)
                preserve_metadata=0,  # Don't preserve all metadata (saves space)
            )
            pdf_document.close()
            
            # Check compressed size
            compressed_size = temp_path.stat().st_size
            compression_ratio = (1 - compressed_size / original_size) * 100
            
            print(f"  📦 Compressed size: {self.format_size(compressed_size)} ({compression_ratio:.1f}% reduction)")
            
            if compressed_size < original_size:
                # Success! Replace original with compressed version
                if not self.dry_run:
                    # Create backup directory structure preserving relative path
                    rel_path = pdf_path.relative_to(self.vault_path)
                    backup_path = self.backup_path / rel_path
                    backup_path = self._get_unique_backup_path(backup_path)
                    backup_path.parent.mkdir(parents=True, exist_ok=True)
                    
                    # Move original to backup
                    shutil.move(str(pdf_path), str(backup_path))
                    
                    # Replace with compressed version (preserving exact filename)
                    shutil.move(str(temp_path), str(pdf_path))
                    
                    # Calculate space saved
                    space_saved = original_size - compressed_size
                    self.stats['space_saved_mb'] += space_saved / (1024 * 1024)
                    
                    print(f"  ✅ Success: Saved {self.format_size(space_saved)}")
                    backup_rel = backup_path.relative_to(self.vault_path)
                    print(f"  🔒 Backup saved: {backup_rel}")
                    return True
                else:
                    # In dry run, clean up the test compressed file
                    temp_path.unlink()
                    space_saved = original_size - compressed_size
                    self.stats['space_saved_mb'] += space_saved / (1024 * 1024)
                    print(f"  ✅ Would save: {self.format_size(space_saved)}")
                    return True
            else:
                # Compression didn't help, remove the compressed file
                temp_path.unlink()
                print(f"  ℹ️  Compression didn't reduce size, keeping original")
                return False
                
        except Exception as e:
            print(f"  ❌ Compression failed: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _get_unique_backup_path(self, path: Path) -> Path:
        """Get a unique backup path if the original exists."""
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
        print("📚 Obsidian PDF Compression Tool")
        print(f"Vault: {self.vault_path}")
        print(f"Size threshold: {self.size_threshold_kb} KB")
        print("=" * 60)
        
        # Get all PDFs
        print("\n📄 Scanning for PDF files...")
        pdfs = self.get_all_pdfs()
        self.stats['pdfs_scanned'] = len(pdfs)
        print(f"Found {len(pdfs)} PDF file(s)")
        
        if not pdfs:
            print("\n✅ No PDF files found!")
            return
        
        # Filter large PDFs
        print(f"\n🔍 Finding PDFs larger than {self.size_threshold_kb} KB...")
        large_pdfs = []
        for pdf in pdfs:
            size = pdf.stat().st_size
            if size > self.size_threshold_bytes:
                large_pdfs.append(pdf)
        
        self.stats['large_pdfs_found'] = len(large_pdfs)
        
        if not large_pdfs:
            print("\n✅ No large PDFs found to compress!")
            return
        
        print(f"\nFound {len(large_pdfs)} large PDF file(s):")
        for idx, pdf in enumerate(large_pdfs, 1):
            size = pdf.stat().st_size
            rel_path = pdf.relative_to(self.vault_path) if pdf.is_relative_to(self.vault_path) else pdf
            print(f"  {idx}. {rel_path} ({self.format_size(size)})")
        
        # Ask for confirmation
        print("\n" + "=" * 60)
        print("⚠️  CONFIRMATION REQUIRED")
        print("=" * 60)
        
        if self.dry_run:
            print("\n⚠️  DRY RUN MODE: No files will be modified.")
        else:
            print("\nThe script will compress these PDFs while maintaining screen quality.")
            print(f"Original files will be backed up to: {self.backup_path.relative_to(self.vault_path)}")
            print("\nWould you like to proceed? (yes/no): ", end='')
            response = input().strip().lower()
            
            if response not in ['yes', 'y']:
                print("\n❌ Compression cancelled by user.")
                return
        
        # Compress PDFs
        print("\n🗜️  Compressing PDFs...")
        print()
        
        for idx, pdf_path in enumerate(large_pdfs, 1):
            print(f"{'=' * 60}")
            print(f"[{idx}/{len(large_pdfs)}] {idx*100//len(large_pdfs)}%")
            # Show relative path - prefer attachments path if in Attachments, otherwise vault path
            if pdf_path.is_relative_to(self.attachments_path):
                rel_path = pdf_path.relative_to(self.attachments_path)
            elif pdf_path.is_relative_to(self.vault_path):
                rel_path = pdf_path.relative_to(self.vault_path)
            else:
                rel_path = pdf_path
            print(f"📄 {rel_path}")
            print(f"{'=' * 60}")
            
            if self.compress_pdf(pdf_path):
                self.stats['pdfs_compressed'] += 1
            else:
                self.stats['compression_failed'] += 1
            
            print()
        
        # Final summary
        print("=" * 60)
        print("📊 COMPRESSION SUMMARY")
        print("=" * 60)
        print(f"  • PDFs scanned: {self.stats['pdfs_scanned']}")
        print(f"  • Large PDFs found: {self.stats['large_pdfs_found']}")
        print(f"  • PDFs compressed: {self.stats['pdfs_compressed']}")
        print(f"  • Compression failed: {self.stats['compression_failed']}")
        print(f"  • Space saved: {self.format_size(self.stats['space_saved_mb'] * 1024 * 1024)}")
        print("=" * 60)
        
        if self.dry_run:
            print("\n⚠️  This was a DRY RUN. Run with --no-dry-run to actually compress files.")


def main():
    parser = argparse.ArgumentParser(
        description="Compress large PDF files in Obsidian vault while maintaining screen readability",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run (preview only, safe default)
  python compress_pdfs.py --vault /Users/jose/obsidian/JC
  
  # Actually compress PDFs (prompts for confirmation)
  python compress_pdfs.py --vault /Users/jose/obsidian/JC --no-dry-run
  
  # Custom size threshold (e.g., 1 MB)
  python compress_pdfs.py --vault /Users/jose/obsidian/JC --threshold 1024
  
  # Simple run with default vault path
  python compress_pdfs.py

Requirements:
  pip install pymupdf pillow

The script will:
  1. Find all PDF files larger than the threshold (default: 500KB)
  2. Compress embedded images to 150 DPI (good for screen viewing)
  3. Resize large images to max 1920px (screen resolution)
  4. Apply JPEG compression (quality 75) to embedded images
  5. Use PDF object compression and cleanup
  6. Create backups of originals in PDF_backups folder
  7. Replace originals with compressed versions (preserving exact filename)
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
    compressor = PDFCompressor(
        vault_path, 
        size_threshold_kb=args.threshold,
        dry_run=not args.no_dry_run
    )
    compressor.run()
    
    return 0


if __name__ == "__main__":
    exit(main())

