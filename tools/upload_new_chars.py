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

def list_existing_gcs_files():
    """List what's currently in GCS"""
    client = storage.Client(project=GCP_PROJECT_ID)
    bucket = client.bucket(BUCKET_NAME)
    
    print("\n" + "="*70)
    print("EXISTING FILES IN GCS")
    print("="*70)
    
    print("\nImages:")
    image_blobs = list(bucket.list_blobs(prefix='default_leaders/images/'))
    for blob in image_blobs:
        print(f"  - {blob.name}")
    
    print(f"\nTotal images: {len(image_blobs)}")
    
    print("\nVideos:")
    video_blobs = list(bucket.list_blobs(prefix='default_leaders/videos/'))
    for blob in video_blobs:
        print(f"  - {blob.name}")
    
    print(f"\nTotal videos: {len(video_blobs)}")
    
    return image_blobs, video_blobs

def delete_all_existing():
    """Delete all existing default leaders from GCS"""
    client = storage.Client(project=GCP_PROJECT_ID)
    bucket = client.bucket(BUCKET_NAME)
    
    print("\n🗑️  Deleting existing files from GCS...")
    
    # Delete images
    image_blobs = list(bucket.list_blobs(prefix='default_leaders/images/'))
    for blob in image_blobs:
        blob.delete()
        print(f"  Deleted: {blob.name}")
    
    # Delete videos
    video_blobs = list(bucket.list_blobs(prefix='default_leaders/videos/'))
    for blob in video_blobs:
        blob.delete()
        print(f"  Deleted: {blob.name}")
    
    print(f"✅ Deleted {len(image_blobs)} images and {len(video_blobs)} videos")

def upload_defaults():
    client = storage.Client(project=GCP_PROJECT_ID)
    bucket = client.bucket(BUCKET_NAME)
    
    # Show existing files first
    list_existing_gcs_files()
    
    # Discover local pairs
    pairs = discover_pairs()
    
    if not pairs:
        print("\n❌ No matching image/video pairs found locally!")
        return
    
    print("\n" + "="*70)
    print("LOCAL FILES TO UPLOAD")
    print("="*70)
    print(f"\nFound {len(pairs)} leader(s) to upload:")
    for leader_id, _, _ in pairs:
        print(f"  - {leader_id}")
    
    # Ask if user wants to delete existing first
    response = input("\n⚠️  Delete ALL existing files in GCS first? (y/n): ")
    if response.lower() == 'y':
        delete_all_existing()
    
    # Confirm upload
    response = input(f"\nUpload {len(pairs)} leaders to GCS? (y/n): ")
    if response.lower() != 'y':
        print("Cancelled.")
        return
    
    print("\n📤 Uploading...")
    
    for leader_id, img_path, vid_path in pairs:
        # Upload image
        img_blob = bucket.blob(f"default_leaders/images/{leader_id}.png")
        img_blob.upload_from_filename(str(img_path), content_type='image/png')
        print(f"  ✅ Uploaded image: {leader_id}.png")
        
        # Upload video
        vid_blob = bucket.blob(f"default_leaders/videos/{leader_id}.mp4")
        vid_blob.upload_from_filename(str(vid_path), content_type='video/mp4')
        print(f"  ✅ Uploaded video: {leader_id}.mp4")
    
    print(f"\n" + "="*70)
    print(f"✅ ALL {len(pairs)} LEADERS UPLOADED TO GCS!")
    print("="*70)
    print(f"Base URL: https://storage.googleapis.com/{BUCKET_NAME}/default_leaders/")
    
    # Show final state
    print("\n" + "="*70)
    print("FINAL GCS STATE")
    print("="*70)
    list_existing_gcs_files()

if __name__ == "__main__":
    upload_defaults()