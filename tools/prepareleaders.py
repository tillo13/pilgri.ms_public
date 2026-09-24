#!/usr/bin/env python3
"""
Default Leader Image Preparer for Pilgrims Game
Optimizes images for Flux Kontext Pro while preserving aspect ratio
"""

# ============================================================================
# SETTINGS FOR FLUX KONTEXT PRO
# ============================================================================

# Target size (longest side will be this)
TARGET_LONGEST_SIDE = 1024    # Keeps aspect ratio, scales longest side to this

# Quality settings
UPSCALE_METHOD = "enhanced_lanczos"
OUTPUT_FORMAT = "png"
PNG_COMPRESSION = 1

# File handling
CLEAN_FILENAMES = True
PRESERVE_CASE = False
OUTPUT_FOLDER_NAME = "processed_leaders"

PROCESS_SUBDIRECTORIES = False
SKIP_IF_OUTPUT_EXISTS = True

# ============================================================================

import os
import re
from pathlib import Path
import time
from PIL import Image, ImageFilter, ImageOps

class FluxKontextImagePreparer:
    def __init__(self):
        pass
    
    def clean_filename(self, filename: str) -> str:
        """Clean filename for web use"""
        if not CLEAN_FILENAMES:
            return filename
            
        name_part = Path(filename).stem
        ext_part = Path(filename).suffix
        
        clean_name = re.sub(r'[^a-zA-Z0-9_-]', '_', name_part)
        clean_name = re.sub(r'_{2,}', '_', clean_name)
        clean_name = clean_name.strip('_')
        
        if not PRESERVE_CASE:
            clean_name = clean_name.lower()
        
        if not clean_name:
            clean_name = "leader"
        
        return clean_name + ext_part.lower()
    
    def calculate_target_size(self, original_size):
        """Scale so longest side = TARGET_LONGEST_SIDE, preserve aspect ratio"""
        width, height = original_size
        longest = max(width, height)
        
        # If already at or below target, keep original
        if longest <= TARGET_LONGEST_SIDE:
            return original_size
        
        # Scale down so longest side = TARGET_LONGEST_SIDE
        scale_factor = TARGET_LONGEST_SIDE / longest
        new_width = int(width * scale_factor)
        new_height = int(height * scale_factor)
        
        return (new_width, new_height)
    
    def process_single_image(self, input_path: Path, base_dir: Path):
        """Process image for Flux Kontext"""
        try:
            output_path = self.get_output_path(input_path, base_dir)
            if SKIP_IF_OUTPUT_EXISTS and output_path.exists():
                return True, "already exists"
            
            # Load image
            image = Image.open(input_path)
            if image.mode in ('RGBA', 'LA'):
                # Convert transparency to white background
                background = Image.new('RGB', image.size, (255, 255, 255))
                if image.mode == 'RGBA':
                    background.paste(image, mask=image.split()[3])
                image = background
            else:
                image = image.convert('RGB')
            
            # Fix EXIF orientation
            image = ImageOps.exif_transpose(image)
            
            original_size = image.size
            target_size = self.calculate_target_size(original_size)
            
            # Resize if needed
            if target_size != original_size:
                # High-quality Lanczos with subtle sharpening
                upscaled = image.resize(target_size, Image.LANCZOS)
                sharpening = ImageFilter.UnsharpMask(radius=0.5, percent=50, threshold=3)
                image = upscaled.filter(sharpening)
            
            # Save with maximum quality
            save_kwargs = {
                "optimize": True,
                "compress_level": PNG_COMPRESSION
            }
            image.save(output_path, OUTPUT_FORMAT.upper(), **save_kwargs)
            
            return True, f"{original_size[0]}x{original_size[1]} → {target_size[0]}x{target_size[1]}"
            
        except Exception as e:
            return False, f"error: {e}"
    
    def get_output_path(self, input_path: Path, relative_to: Path) -> Path:
        """Generate output path"""
        current_dir = Path.cwd()
        output_dir = current_dir / OUTPUT_FOLDER_NAME
        output_dir.mkdir(exist_ok=True)
        
        clean_filename = self.clean_filename(input_path.name)
        clean_stem = Path(clean_filename).stem
        output_name = f"{clean_stem}.{OUTPUT_FORMAT}"
        
        return output_dir / output_name
    
    def find_image_files(self, directory: Path):
        """Find images in directory"""
        extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}
        image_files = []
        
        for item in directory.iterdir():
            if item.is_file() and item.suffix.lower() in extensions:
                if item.parent.name.lower() != OUTPUT_FOLDER_NAME.lower():
                    image_files.append(item)
        
        return sorted(image_files)
    
    def process_directory(self):
        """Process all images"""
        directory = Path.cwd()
        
        print("="*70)
        print("PILGRIMS DEFAULT LEADER IMAGE PROCESSOR")
        print("="*70)
        print(f"Processing: {directory}")
        print(f"Target: Longest side = {TARGET_LONGEST_SIDE}px (aspect ratio preserved)")
        print(f"Method: {UPSCALE_METHOD}")
        print(f"Format: {OUTPUT_FORMAT.upper()}")
        print(f"Output: {OUTPUT_FOLDER_NAME}/")
        print("="*70)
        
        image_files = self.find_image_files(directory)
        
        if not image_files:
            print("No images found in current directory!")
            return
        
        print(f"\nFound {len(image_files)} image(s)")
        
        successful = 0
        failed = 0
        start_time = time.time()
        
        for i, file_path in enumerate(image_files, 1):
            print(f"\n[{i}/{len(image_files)}] {file_path.name}")
            
            success, message = self.process_single_image(file_path, directory)
            
            if success:
                successful += 1
                print(f"  Success: {message}")
            else:
                failed += 1
                print(f"  Failed: {message}")
        
        elapsed = time.time() - start_time
        
        print("\n" + "="*70)
        print("PROCESSING COMPLETE")
        print("="*70)
        print(f"Successful: {successful}")
        print(f"Failed: {failed}")
        print(f"Time: {elapsed:.1f}s")
        print(f"Output: {directory / OUTPUT_FOLDER_NAME}")

def main():
    preparer = FluxKontextImagePreparer()
    preparer.process_directory()

if __name__ == "__main__":
    main()