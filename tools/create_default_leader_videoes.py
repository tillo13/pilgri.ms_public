#!/usr/bin/env python3
"""
create_default_leaders_videos.py
Generates cartoon-style animated videos for all default leader images
Run from the project root directory (sibling to app.py)
"""

import os
import sys
import time
from pathlib import Path
from utilities.flux_utils import FluxGenerator

# Directories
IMAGES_DIR = Path("static/images/default_leaders")
VIDEOS_DIR = Path("static/videos/default_leaders")

# Super cartoonized prompt for character processing
EXTREME_CARTOON_PROMPT = (
    "transform into highly stylized cartoon video game character with bold thick outlines, "
    "exaggerated features, vibrant saturated colors, simplified geometry, cel-shaded appearance, "
    "comic book style rendering, standing on red martian terrain with rocky landscape and Earth "
    "visible as blue marble in starry sky, dressed in space exploration gear without helmet, "
    "complete full body visible with maximum cartoon stylization"
)

# Video animation prompt (reuse from config or customize)
VIDEO_ANIMATION_PROMPT = (
    "A cartoon character in space exploration gear without a helmet stands on a red martian ridge "
    "overlooking rust-colored valleys and distant mountains, with Earth visible as a small blue sphere "
    "in the star-filled black sky above. The character slowly raises their hand to shield their eyes "
    "from the pale sun as they gaze toward the distant Mars horizon. The character turns their head "
    "left and right, surveying the alien red landscape with a sense of wonder and determination, "
    "occasionally glancing up at Earth and the stars. They point toward distant martian landmarks and "
    "the Earth above with deliberate, slow movements. The camera smoothly pans left to right and back "
    "again, showing different angles of the character against the expansive red planet vista with the "
    "starry cosmos and Earth visible in the pink-orange sky. All movements are slow and deliberate - "
    "the character's gestures are unhurried, the head turns are gradual, and the camera movement is "
    "smooth and steady."
)

def process_leader_image_to_cartoon(flux_generator, image_path: Path, output_path: Path) -> str:
    """
    First pass: cartoonize the leader image heavily
    Returns URL of cartoonized image
    """
    print(f"\n  Step 1: Cartoonizing {image_path.name}...")
    
    with open(image_path, 'rb') as f:
        image_data = f.read()
    
    cartoon_url = flux_generator.process_image(
        image_data, 
        custom_prompt=EXTREME_CARTOON_PROMPT
    )
    
    print(f"  ✓ Cartoon image ready: {cartoon_url[:50]}...")
    return cartoon_url

def create_video_from_cartoon(flux_generator, cartoon_url: str, output_path: Path) -> str:
    """
    Second pass: animate the cartoonized image
    Returns URL of video
    """
    print(f"  Step 2: Animating cartoon character...")
    
    video_url = flux_generator.animate_character(
        cartoon_url,
        custom_prompt=VIDEO_ANIMATION_PROMPT
    )
    
    print(f"  ✓ Video ready: {video_url[:50]}...")
    return video_url

def download_video(video_url: str, output_path: Path):
    """Download video from URL to local path"""
    import requests
    
    print(f"  Step 3: Downloading video to {output_path.name}...")
    
    response = requests.get(video_url, timeout=120)
    response.raise_for_status()
    
    with open(output_path, 'wb') as f:
        f.write(response.content)
    
    file_size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"  ✓ Saved: {output_path.name} ({file_size_mb:.2f} MB)")

def process_all_leaders():
    """Main processing function"""
    print("="*70)
    print("DEFAULT LEADERS VIDEO GENERATOR")
    print("="*70)
    print(f"Images dir: {IMAGES_DIR}")
    print(f"Videos dir: {VIDEOS_DIR}")
    print("="*70)
    
    # Ensure directories exist
    if not IMAGES_DIR.exists():
        print(f"\nError: Images directory not found: {IMAGES_DIR}")
        sys.exit(1)
    
    VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    
    # Find all image files
    image_files = sorted([
        f for f in IMAGES_DIR.iterdir() 
        if f.suffix.lower() in ['.jpg', '.jpeg', '.png', '.webp']
    ])
    
    if not image_files:
        print(f"\nNo images found in {IMAGES_DIR}")
        sys.exit(1)
    
    print(f"\nFound {len(image_files)} leader image(s)")
    print("\nThis will take approximately 2-3 minutes per leader (cartoon + video)")
    
    # Ask for confirmation
    response = input("\nProceed? (y/n): ")
    if response.lower() != 'y':
        print("Cancelled.")
        return
    
    # Initialize Flux generator
    print("\nInitializing Flux generator...")
    flux = FluxGenerator()
    print("✓ Ready")
    
    # Process each leader
    total_start = time.time()
    successful = 0
    failed = 0
    
    for i, image_path in enumerate(image_files, 1):
        leader_start = time.time()
        
        print(f"\n{'='*70}")
        print(f"[{i}/{len(image_files)}] Processing: {image_path.name}")
        print(f"{'='*70}")
        
        # Determine output video path (same name, .mp4 extension)
        video_name = image_path.stem + ".mp4"
        video_path = VIDEOS_DIR / video_name
        
        # Skip if already exists
        if video_path.exists():
            print(f"  ⭐ Video already exists: {video_name}")
            successful += 1
            continue
        
        try:
            # Step 1: Cartoonize the image
            cartoon_url = process_leader_image_to_cartoon(flux, image_path, video_path)
            time.sleep(2)  # Brief pause between API calls
            
            # Step 2: Animate the cartoon
            video_url = create_video_from_cartoon(flux, cartoon_url, video_path)
            time.sleep(2)
            
            # Step 3: Download video
            download_video(video_url, video_path)
            
            leader_time = time.time() - leader_start
            print(f"\n  ✓ Complete in {leader_time:.1f}s")
            successful += 1
            
        except Exception as e:
            print(f"\n  ✗ Failed: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
            
            # Don't abort entire batch on one failure
            response = input("\n  Continue with remaining leaders? (y/n): ")
            if response.lower() != 'y':
                break
    
    # Summary
    total_time = time.time() - total_start
    print("\n" + "="*70)
    print("PROCESSING COMPLETE")
    print("="*70)
    print(f"Successful: {successful}")
    print(f"Failed: {failed}")
    print(f"Total time: {total_time/60:.1f} minutes")
    print(f"\nVideos saved to: {VIDEOS_DIR}")
    
    if successful > 0:
        print("\n✓ Leaders ready for game!")
        print("  Next steps:")
        print("  1. Review videos in static/videos/default_leaders/")
        print("  2. Upload to GCS with upload_default_leaders.py")
        print("  3. Update config.py with leader names and stats")

if __name__ == "__main__":
    try:
        process_all_leaders()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nFatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)