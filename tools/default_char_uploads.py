#!/usr/bin/env python3
"""
One-time script to upload default leaders to GCS
Auto-discovers all matching image/video pairs
"""
from google.cloud import storage
from pathlib import Path
import os

GCP_PROJECT_ID = "galactica-character-game"
BUCKET_NAME = "galactica-pilgrim-assets"
IMAGES_DIR = "static/images/default_leaders"
VIDEOS_DIR = "static/videos/default_leaders"

def discover_pairs():
    """Find all matching image/video pairs"""
    pairs = []
    
    if not os.path.exists(IMAGES_DIR) or not os.path.exists(VIDEOS_DIR):
        print(f"Error: Directories not found")
        return pairs
    
    # Get all image files
    for img_file in Path(IMAGES_DIR).glob('*.png'):
        leader_id = img_file.stem
        video_file = Path(VIDEOS_DIR) / f"{leader_id}.mp4"
        
        if video_file.exists():
            pairs.append((leader_id, img_file, video_file))
        else:
            print(f"Warning: No video for {leader_id}")
    
    return pairs

def upload_defaults():
    client = storage.Client(project=GCP_PROJECT_ID)
    bucket = client.bucket(BUCKET_NAME)
    
    pairs = discover_pairs()
    
    if not pairs:
        print("No matching image/video pairs found!")
        return
    
    print(f"Found {len(pairs)} leader(s) to upload:")
    for leader_id, _, _ in pairs:
        print(f"  - {leader_id}")
    
    print("\nUploading...")
    
    for leader_id, img_path, vid_path in pairs:
        # Upload image
        img_blob = bucket.blob(f"default_leaders/images/{leader_id}.png")
        img_blob.upload_from_filename(str(img_path), content_type='image/png')
        print(f"Uploaded image: {leader_id}.png")
        
        # Upload video
        vid_blob = bucket.blob(f"default_leaders/videos/{leader_id}.mp4")
        vid_blob.upload_from_filename(str(vid_path), content_type='video/mp4')
        print(f"Uploaded video: {leader_id}.mp4")
    
    print(f"\nAll {len(pairs)} leaders uploaded to GCS!")
    print(f"Base URL: https://storage.googleapis.com/{BUCKET_NAME}/default_leaders/")

if __name__ == "__main__":
    upload_defaults()