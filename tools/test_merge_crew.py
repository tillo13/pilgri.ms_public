#!/usr/bin/env python3
"""
Single Character Crew Test Script - REWRITTEN
Focus: Generate individual well-cropped characters within strict Flux size limits
- Auto-crop characters from wide default images
- STRICT 1300px maximum width for ALL images sent to Flux
- Preserve aspect ratios in all cropping/resizing operations
- Save all files including crops in timestamped test_crew directory
- Optimized for Flux Kontext processing
"""

import utilities.flux_utils as flux_utils
import random
import os
from PIL import Image
import requests
from io import BytesIO
import webbrowser
import subprocess
import time
from datetime import datetime
import shutil

# Optional YOLO for auto-cropping characters
try:
    from ultralytics import YOLO
    import numpy as np
    YOLO_AVAILABLE = True
    print("✅ YOLO available for auto-cropping")
except ImportError as e:
    YOLO_AVAILABLE = False
    print(f"⚠️  YOLO not available - {e}")
    print("   Install with: pip install ultralytics numpy")

# Test data
CREW_COLORS = [
    'red', 'blue', 'green', 'purple', 'orange', 'yellow',
    'black', 'white', 'pink', 'cyan', 'magenta', 'gold'
]

CREW_STYLES = [
    # Your current working styles (keep these!)
    'minecraft-style blocky',
    'ghibli-style anime', 
    'claymation clay figure',
    
    # Popular character toy styles
    'funko pop vinyl figure',
    'chibi anime character',
    'soft plush toy with yarn texture',
    'polymer clay miniature figure',
    
    # Animation styles
    'pixar 3d animated character',
    'disney cartoon character',
    'south park paper cutout style',
    'the simpsons yellow character',
    'adventure time flat cartoon',
    
    # Craft/handmade styles  
    'felt wool character doll',
    'knitted yarn amigurumi toy',
    'wooden carved puppet figure',
    'papier-mache folk art figure',
    'bobblehead collectible figure',
    
    # Digital/gaming styles
    'lego brick construction',
    'pixel art 8-bit character',
    'retro arcade game sprite',
    'vinyl designer toy figure',
    'nendoroid action figure',
    
    # Art styles that transform characters
    'pop art comic book style',
    'watercolor painted character',
    'chalk pastel drawing style',
    'stained glass window art',
    'geometric low-poly character'
]

# STRICT Flux size limits - reduced for safety
MAX_WIDTH = 1300  # STRICT limit - never exceed
MAX_HEIGHT = 1300
MAX_PIXELS = MAX_WIDTH * MAX_HEIGHT

def create_test_directory():
    """Create timestamped test directory and return path"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    test_dir = f"test_crew/{timestamp}"
    os.makedirs(test_dir, exist_ok=True)
    print(f"📁 Created test directory: {test_dir}")
    return test_dir

def resize_preserve_aspect(image, max_width=MAX_WIDTH, max_height=MAX_HEIGHT):
    """Resize image to fit within limits while STRICTLY preserving aspect ratio"""
    try:
        original_width, original_height = image.size
        
        # Check if resize is needed
        if original_width <= max_width and original_height <= max_height:
            print(f"✅ Image size OK: {original_width}x{original_height}")
            return image
        
        # Calculate scaling factor - use the most restrictive dimension
        scale_width = max_width / original_width
        scale_height = max_height / original_height
        scale_factor = min(scale_width, scale_height)
        
        # Calculate new dimensions preserving aspect ratio
        new_width = int(original_width * scale_factor)
        new_height = int(original_height * scale_factor)
        
        # Ensure multiples of 32 for Flux (but don't exceed limits)
        new_width = min((new_width // 32) * 32, max_width)
        new_height = min((new_height // 32) * 32, max_height)
        
        # Double-check we haven't exceeded limits
        if new_width > max_width or new_height > max_height:
            print(f"⚠️  Dimension check failed, using safer values")
            new_width = min(new_width, max_width)
            new_height = min(new_height, max_height)
        
        # Resize with high quality
        resized_image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        print(f"📏 Resized (aspect preserved): {original_width}x{original_height} → {new_width}x{new_height}")
        return resized_image
        
    except Exception as e:
        print(f"❌ Resize failed: {e}")
        return image

def smart_center_crop(image, save_path=None):
    """Smart center crop with aspect ratio preservation for character focus"""
    try:
        width, height = image.size
        
        # Calculate crop parameters for character focus
        if width > height * 1.5:
            # Very wide landscape - crop from sides to focus on center character
            target_width = int(height * 1.2)  # Slightly wider than square for character
            left_offset = (width - target_width) // 2
            right = left_offset + target_width
            cropped = image.crop((left_offset, 0, right, height))
            print(f"📐 Smart crop (landscape): {width}x{height} → {cropped.width}x{cropped.height}")
            
        else:
            # Image proportions are already good
            cropped = image
            print(f"📐 No crop needed: {width}x{height}")
        
        # Save cropped version if path provided
        if save_path and cropped != image:
            cropped.save(save_path)
            print(f"💾 Saved cropped version: {os.path.basename(save_path)}")
        
        return cropped
        
    except Exception as e:
        print(f"❌ Smart crop failed: {e}")
        return image

def auto_crop_character(image_path, save_path=None):
    """Use YOLO to detect and crop the main character with aspect ratio preservation"""
    if not YOLO_AVAILABLE:
        print("⚠️  YOLO not available - using smart center crop")
        return None
    
    try:
        # Load YOLO model
        model = YOLO('yolov8n.pt')
        
        # Run detection
        results = model(image_path, classes=[0], conf=0.25)
        
        if not results or len(results) == 0 or not results[0].boxes or len(results[0].boxes) == 0:
            print("❌ No persons detected - will use smart center crop")
            return None
        
        # Get best detection
        result = results[0]
        boxes = result.boxes.xyxy.cpu().numpy()
        confidences = result.boxes.conf.cpu().numpy()
        
        # Pick largest person with decent confidence
        if len(boxes) > 1:
            areas = [(box[2] - box[0]) * (box[3] - box[1]) for box in boxes]
            scores = [areas[i] * confidences[i] for i in range(len(boxes))]
            best_idx = max(range(len(scores)), key=lambda i: scores[i])
            best_box = boxes[best_idx]
            best_conf = confidences[best_idx]
        else:
            best_box = boxes[0]
            best_conf = confidences[0]
        
        # Load and crop image with smart padding
        original_img = Image.open(image_path)
        x1, y1, x2, y2 = best_box
        
        img_width, img_height = original_img.size
        detected_width = x2 - x1
        detected_height = y2 - y1
        
        # Smart padding - percentage based with minimums
        padding_x = max(30, int(detected_width * 0.2))
        padding_y = max(30, int(detected_height * 0.2))
        
        # Apply padding while staying in bounds
        x1 = max(0, int(x1 - padding_x))
        y1 = max(0, int(y1 - padding_y))
        x2 = min(img_width, int(x2 + padding_x))
        y2 = min(img_height, int(y2 + padding_y))
        
        # Crop the character
        cropped_img = original_img.crop((x1, y1, x2, y2))
        
        # Save auto-cropped version if path provided
        if save_path:
            cropped_img.save(save_path)
            print(f"💾 Saved auto-cropped version: {os.path.basename(save_path)}")
        
        print(f"🎯 Auto-cropped character: {cropped_img.width}x{cropped_img.height} (conf: {best_conf:.2f})")
        return cropped_img
        
    except Exception as e:
        print(f"❌ Auto-crop failed: {e}")
        return None

def save_url_image(url, filepath, description=""):
    """Download and save image from URL to filepath"""
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        
        with open(filepath, 'wb') as f:
            f.write(response.content)
        
        print(f"💾 Saved {description}: {os.path.basename(filepath)}")
        return True
    except Exception as e:
        print(f"❌ Failed to save {description}: {e}")
        return False

def open_image_in_browser(url, delay=2):
    """Open image URL in browser"""
    try:
        print(f"🌐 Opening: {url}")
        subprocess.run(['open', '-a', 'Google Chrome', url], check=True)
        time.sleep(delay)
    except Exception as e:
        print(f"Could not open browser: {e}")
        try:
            webbrowser.open(url)
        except:
            print("Could not open any browser")

def get_processed_leader(used_leaders=None, test_dir=""):
    """Get random default leader with all cropping and resizing applied"""
    if used_leaders is None:
        used_leaders = set()
        
    try:
        default_dir = "static/images/default_leaders"
        
        if not os.path.exists(default_dir):
            print(f"❌ Default leaders directory not found: {default_dir}")
            return None, used_leaders
        
        png_files = [f for f in os.listdir(default_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]

        
        if not png_files:
            print(f"❌ No PNG files found in {default_dir}")
            return None, used_leaders
        
        # Filter out already used leaders
        available_leaders = [f for f in png_files if f not in used_leaders]
        
        if not available_leaders:
            print(f"🔄 All {len(png_files)} leaders used, starting over...")
            available_leaders = png_files
            used_leaders.clear()
        
        random_leader = random.choice(available_leaders)
        used_leaders.add(random_leader)
        
        print(f"🎲 Selected: {random_leader} ({len(used_leaders)}/{len(png_files)} used)")
        
        leader_path = os.path.join(default_dir, random_leader)
        base_name = random_leader.replace('.png', '')
        
        # Step 1: Try auto-cropping first
        processed_img = None
        processing_steps = []
        
        if YOLO_AVAILABLE:
            auto_crop_path = f"{test_dir}/{base_name}_01_autocrop.png" if test_dir else None
            print(f"🎯 Auto-cropping {random_leader}...")
            processed_img = auto_crop_character(leader_path, auto_crop_path)
            if processed_img:
                processing_steps.append("autocropped")
                print(f"✅ Auto-crop successful")
        
        # Step 2: Fall back to smart center crop if auto-crop failed
        if not processed_img:
            print(f"📐 Using smart center crop on {random_leader}...")
            original_img = Image.open(leader_path)
            smart_crop_path = f"{test_dir}/{base_name}_01_smartcrop.png" if test_dir else None
            processed_img = smart_center_crop(original_img, save_path=smart_crop_path)
            processing_steps.append("smartcropped")
        
        # Step 3: Final resize to ensure within strict limits
        print(f"📏 Final resize to ensure < {MAX_WIDTH}px width...")
        final_img = resize_preserve_aspect(processed_img, MAX_WIDTH, MAX_HEIGHT)
        
        # Save final processed version
        if test_dir:
            final_path = f"{test_dir}/{base_name}_02_final.png"
            final_img.save(final_path)
            print(f"💾 Saved final processed: {os.path.basename(final_path)}")
        
        # Convert to bytes for Flux
        img_byte_arr = BytesIO()
        final_img.save(img_byte_arr, format='PNG')
        image_data = img_byte_arr.getvalue()
        
        final_filename = f"{base_name}_{'_'.join(processing_steps)}"
        
        return (image_data, final_filename, leader_path), used_leaders
            
    except Exception as e:
        print(f"❌ Error processing leader: {e}")
        return None, used_leaders

def download_image_from_url(url):
    """Download image from URL and return PIL Image"""
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return Image.open(BytesIO(response.content))
    except Exception as e:
        print(f"❌ Error downloading image from {url}: {e}")
        return None

def merge_images_strict_width(image_urls, max_total_width=MAX_WIDTH, test_dir="", save_name="composite"):
    """Merge images side by side with STRICT width limit and aspect ratio preservation"""
    try:
        print(f"🔗 Merging {len(image_urls)} images (STRICT max: {max_total_width}px)...")
        
        # Download all images
        images = []
        for i, url in enumerate(image_urls):
            img = download_image_from_url(url)
            if not img:
                print(f"❌ Failed to download image {i+1}")
                return None
            if img.mode != 'RGB':
                img = img.convert('RGB')
            images.append(img)
        
        # Calculate allocation per image
        num_images = len(images)
        target_width_per_image = max_total_width // num_images
        
        # Find the limiting height (use smallest to avoid excessive scaling)
        min_height = min(img.height for img in images)
        target_height = min(min_height, MAX_HEIGHT)
        
        # Resize each image to fit allocated space while preserving aspect ratio
        resized_images = []
        total_actual_width = 0
        
        for i, img in enumerate(images):
            # Calculate what width this image would need at target height
            aspect_ratio = img.width / img.height
            natural_width = int(target_height * aspect_ratio)
            
            # Use the smaller of allocated width or natural width
            final_width = min(target_width_per_image, natural_width)
            final_height = int(final_width / aspect_ratio)
            
            # Ensure we don't exceed target height
            if final_height > target_height:
                final_height = target_height
                final_width = int(final_height * aspect_ratio)
            
            # Ensure multiples of 32
            final_width = (final_width // 32) * 32
            final_height = (final_height // 32) * 32
            
            resized_img = img.resize((final_width, final_height), Image.Resampling.LANCZOS)
            resized_images.append(resized_img)
            total_actual_width += final_width
            
            print(f"  Image {i+1}: {img.width}x{img.height} → {final_width}x{final_height}")
        
        # Verify total width is within limits
        if total_actual_width > max_total_width:
            print(f"⚠️  Total width {total_actual_width}px exceeds {max_total_width}px, scaling down...")
            scale_factor = max_total_width / total_actual_width
            
            rescaled_images = []
            total_actual_width = 0
            
            for img in resized_images:
                new_width = int(img.width * scale_factor)
                new_height = int(img.height * scale_factor)
                
                # Ensure multiples of 32
                new_width = (new_width // 32) * 32
                new_height = (new_height // 32) * 32
                
                rescaled_img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                rescaled_images.append(rescaled_img)
                total_actual_width += new_width
            
            resized_images = rescaled_images
        
        # Create composite
        max_height_in_set = max(img.height for img in resized_images)
        composite = Image.new('RGB', (total_actual_width, max_height_in_set), color='white')
        
        # Paste images side by side, centered vertically
        x_offset = 0
        for img in resized_images:
            y_offset = (max_height_in_set - img.height) // 2
            composite.paste(img, (x_offset, y_offset))
            x_offset += img.width
        
        # Save composite
        if test_dir:
            composite_path = f"{test_dir}/{save_name}.png"
            composite.save(composite_path)
            print(f"💾 Saved composite: {os.path.basename(composite_path)}")
        
        print(f"✅ Merged: {composite.width}x{composite.height} (STRICT limit respected)")
        return composite
        
    except Exception as e:
        print(f"❌ Error merging images: {e}")
        return None

def save_image_for_flux(image, filepath):
    """Save image and return bytes for Flux processing"""
    try:
        image.save(filepath)
        print(f"💾 Saved for Flux: {os.path.basename(filepath)}")
        
        # Convert to bytes
        img_byte_arr = BytesIO()
        image.save(img_byte_arr, format='PNG')
        return img_byte_arr.getvalue()
        
    except Exception as e:
        print(f"❌ Error saving for Flux: {e}")
        return None

def create_run_summary(test_dir, characters, team_color, team_style):
    """Create summary file with run details"""
    summary_path = f"{test_dir}/RUN_SUMMARY.txt"
    
    try:
        with open(summary_path, 'w') as f:
            f.write("=== SINGLE CHARACTER CREW TEST SUMMARY (REWRITTEN) ===\n")
            f.write(f"Timestamp: {os.path.basename(test_dir)}\n")
            f.write(f"Team Color: {team_color.upper()}\n")
            f.write(f"Team Style: {team_style.upper()}\n")
            f.write(f"Generated Characters: {len(characters)}\n")
            f.write(f"YOLO Auto-Crop: {'Enabled' if YOLO_AVAILABLE else 'Disabled'}\n")
            
            f.write(f"\n=== STRICT FLUX SIZE LIMITS ===\n")
            f.write(f"Max Width: {MAX_WIDTH}px (STRICT - never exceed)\n")
            f.write(f"Max Height: {MAX_HEIGHT}px\n")
            f.write(f"Max Pixels: {MAX_PIXELS:,}\n")
            
            f.write(f"\n=== GENERATED CHARACTERS ===\n")
            for i, char in enumerate(characters, 1):
                f.write(f"\nCharacter {i}:\n")
                f.write(f"  Original: {char.get('original', 'N/A')}\n")
                f.write(f"  Processing: {char.get('processing_steps', 'N/A')}\n")
                f.write(f"  Final Name: {char.get('final_name', 'N/A')}\n")
                f.write(f"  Styled URL: {char.get('final_styled', 'N/A')}\n")
                f.write(f"  Color: {char.get('color', 'N/A')}\n")
                f.write(f"  Style: {char.get('style', 'N/A')}\n")
        
        print(f"📝 Summary saved: {summary_path}")
        
    except Exception as e:
        print(f"❌ Failed to create summary: {e}")

def test_crew_generation():
    """Test complete crew generation with strict size limits and aspect ratio preservation"""
    
    # Setup
    test_dir = create_test_directory()
    flux = flux_utils.FluxGenerator()
    
    # Pick random theme
    team_color = random.choice(CREW_COLORS)
    team_style = random.choice(CREW_STYLES)
    
    characters = []
    used_leaders = set()
    
    print("\n" + "="*60)
    print("🎯 COMPLETE CREW GENERATION TEST (REWRITTEN)")
    print("="*60)
    print(f"📁 Test Directory: {test_dir}")
    print(f"🎨 Team Color: {team_color.upper()}")
    print(f"🎭 Team Style: {team_style.upper()}")
    print(f"📏 STRICT Size Limits: {MAX_WIDTH}x{MAX_HEIGHT} max ({MAX_PIXELS:,} pixels)")
    print(f"🤖 Auto-Crop: {'Enabled' if YOLO_AVAILABLE else 'Disabled (Smart Crop)'}")
    print(f"🛡️  Aspect Ratios: PRESERVED throughout all operations")
    
    # === STEP 1: Generate Individual Characters ===
    print(f"\n🎯 STEP 1: INDIVIDUAL CHARACTER GENERATION")
    print("="*60)
    
    for i in range(3):
        char_name = f"Character_{chr(65 + i)}"  # A, B, C
        print(f"\n{'='*20} {char_name} {'='*20}")
        
        try:
            # Get fully processed leader (cropped and resized)
            leader_result, used_leaders = get_processed_leader(used_leaders, test_dir)
            if not leader_result:
                print(f"❌ Failed to process leader for {char_name}")
                continue
                
            image_data, final_name, original_path = leader_result
            
            # Copy original to test directory for reference
            original_save_path = f"{test_dir}/{char_name}_00_original.png"
            try:
                shutil.copy2(original_path, original_save_path)
                print(f"📋 Saved original reference: {os.path.basename(original_save_path)}")
            except Exception as e:
                print(f"⚠️  Could not copy original: {e}")
            
            # Create character transformation prompt
            character_prompt = (
                f"transform this character into a {team_style} video game character, "
                f"focus ONLY on the main character, ignore any background elements, "
                f"create a full body character from head to feet, "
                f"dress the character in 100% {team_color} adventurer outfit, "
                f"complete {team_color} clothing and gear, "
                f"full body standing pose showing all limbs, "
                f"single character only, {team_style} art style, "
                f"clean background, character-focused composition"
            )
            
            print(f"🎨 Generating styled character (image guaranteed < {MAX_WIDTH}px)...")
            
            # Process through Flux
            styled_url = flux.process_image(image_data, character_prompt)
            
            if styled_url:
                # Save styled result
                styled_save_path = f"{test_dir}/{char_name}_03_styled.png"
                save_url_image(styled_url, styled_save_path, f"{char_name} styled")
                
                # Store character info
                characters.append({
                    'name': char_name,
                    'original': os.path.basename(original_path),
                    'final_name': final_name,
                    'final_styled': styled_url,
                    'styled_path': styled_save_path,
                    'color': team_color,
                    'style': team_style,
                    'processing_steps': final_name.split('_')[-1] if '_' in final_name else 'processed',
                    'prompt': character_prompt
                })
                
                print(f"✅ {char_name} created successfully (width guaranteed < {MAX_WIDTH}px)!")
                open_image_in_browser(styled_url, delay=1)
                
            else:
                print(f"❌ Failed to generate {char_name}")
                
        except Exception as e:
            print(f"❌ Error generating {char_name}: {e}")
    
    if len(characters) < 2:
        print(f"\n❌ Need at least 2 characters for team building (got {len(characters)})")
        create_run_summary(test_dir, characters, team_color, team_style)
        return characters
    
    print(f"\n✅ Generated {len(characters)} individual characters")
    
    # === STEP 2: Team Building with Strict Size Limits ===
    print(f"\n🏗️  STEP 2: TEAM BUILDING (STRICT {MAX_WIDTH}px LIMIT)")
    print("="*60)
    
    # Build 2-person team
    if len(characters) >= 2:
        print(f"\n👥 Creating 2-person team...")
        try:
            two_person_urls = [characters[0]['final_styled'], characters[1]['final_styled']]
            
            # Merge with strict width limits
            composite_2 = merge_images_strict_width(
                two_person_urls, 
                MAX_WIDTH, 
                test_dir, 
                "04_team_2person_composite"
            )
            
            if composite_2:
                # Process through Flux
                team_2_data = save_image_for_flux(composite_2, f"{test_dir}/05_team_2person_input.png")
                
                team_prompt_2 = (





                    f"Keep the left person and right person as two completely different individuals with "
                    f"their own unique facial features, hair, and body types. The left character has "
                    f"[describe left character's key features] and the right character has [describe right character's key features]. "
                    f"Place both characters in an epic {team_style} mountain adventure setting while "
                    f"preserving each person's distinct identity and {team_color} adventurer gear exactly as shown. "
                    f"Show them celebrating as friends but keep them as two separate, different-looking people. "
                    f"Never blend or merge their appearances - maintain two distinct individuals with "
                    f"completely different faces and features"


                )
                
                team_2_url = flux.process_image(team_2_data, team_prompt_2)
                
                if team_2_url:
                    team_2_path = f"{test_dir}/06_team_2person_final.png"
                    save_url_image(team_2_url, team_2_path, "2-person team")
                    
                    characters.append({
                        'name': '2PERSON_TEAM',
                        'final_styled': team_2_url,
                        'styled_path': team_2_path,
                        'team_size': 2,
                        'prompt': team_prompt_2
                    })
                    
                    print(f"✅ 2-person team created (< {MAX_WIDTH}px): {team_2_url}")
                    open_image_in_browser(team_2_url, delay=2)
                
            else:
                print("❌ Failed to create 2-person composite")
                
        except Exception as e:
            print(f"❌ Failed 2-person team: {e}")
    
    # Build 3-person team
    if len([c for c in characters if 'Character_' in c['name']]) >= 3:
        print(f"\n👥👤👤 Creating 3-person team...")
        try:
            three_person_urls = [
                characters[0]['final_styled'],
                characters[1]['final_styled'],
                characters[2]['final_styled']
            ]
            
            # Merge with strict width limits
            composite_3 = merge_images_strict_width(
                three_person_urls,
                MAX_WIDTH,
                test_dir,
                "07_team_3person_composite"
            )
            
            if composite_3:
                # Process through Flux
                final_team_data = save_image_for_flux(composite_3, f"{test_dir}/08_team_3person_input.png")
                
                final_team_prompt = (




                    f"Place the left character, center character, and right character in the same scene "
                    f"while maintaining their exact same facial features, expressions, and individual appearances. "
                    f"Change the background to an epic {team_style} mountain adventure setting with dramatic vista "
                    f"while preserving their distinct faces and {team_color} adventurer gear exactly as shown. "
                    f"Show all 3 characters celebrating together as best friends - high-fiving, cheering with "
                    f"raised arms, or excitedly pointing at the vista ahead. Create a joyful team moment with "
                    f"all characters facing forward toward the adventure, showing friendship and excitement "
                    f"to explore together. Keep each character's unique facial features and individual look "
                    f"completely unchanged while allowing natural celebratory poses"


                )
                
                final_team_url = flux.process_image(final_team_data, final_team_prompt)
                
                if final_team_url:
                    final_team_path = f"{test_dir}/09_FINAL_3PERSON_TEAM.png"
                    save_url_image(final_team_url, final_team_path, "FINAL 3-PERSON TEAM")
                    
                    characters.append({
                        'name': 'FINAL_3PERSON_TEAM',
                        'final_styled': final_team_url,
                        'styled_path': final_team_path,
                        'team_size': 3,
                        'prompt': final_team_prompt
                    })
                    
                    print(f"\n🎉 FINAL 3-PERSON TEAM CREATED (< {MAX_WIDTH}px)!")
                    print(f"🔗 URL: {final_team_url}")
                    open_image_in_browser(final_team_url, delay=0)
                
            else:
                print("❌ Failed to create 3-person composite")
                
        except Exception as e:
            print(f"❌ Failed 3-person team: {e}")
    
    # Create summary
    create_run_summary(test_dir, characters, team_color, team_style)
    
    print(f"\n{'='*60}")
    print(f"🏁 CREW GENERATION COMPLETE!")
    print(f"📁 Results saved in: {test_dir}")
    print(f"✅ Individual characters: {len([c for c in characters if 'Character_' in c['name']])}/3")
    print(f"🏆 Team results: {len([c for c in characters if 'TEAM' in c['name']])}")
    print(f"📐 ALL images guaranteed < {MAX_WIDTH}px width with preserved aspect ratios")
    print(f"📝 Summary: {test_dir}/RUN_SUMMARY.txt")
    print(f"{'='*60}")
    
    return characters

if __name__ == "__main__":
    test_crew_generation()