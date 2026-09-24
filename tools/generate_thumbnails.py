#!/usr/bin/env python3
"""
Generate optimized thumbnails for UI elements.

PROBLEM: Our UI icons are 400-1200 KB each but displayed at 24-48px.
This script creates properly sized thumbnails for fast loading.

Usage:
    python tools/generate_thumbnails.py

This will:
1. Download original images from GCS
2. Create properly sized thumbnails
3. Upload to GCS with _thumb suffix
4. Output new URLs to use in templates
"""

import os
import sys
import tempfile
from io import BytesIO

# Add parent to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image
import requests
from google.cloud import storage

# GCS bucket
BUCKET_NAME = "galactica-pilgrim-assets"

# Images to optimize with their display sizes
# Format: (original_path, display_size, output_suffix)
UI_IMAGES = [
    # Nav icons - displayed at 24px
    ("ui/base_icon_1767579866.png", 48, "nav"),  # 2x for retina
    ("ui/crew_icon_1767579874.png", 48, "nav"),
    ("ui/depot_icon_1767579883.png", 48, "nav"),
    ("ui/expeditions_icon_1767579891.png", 48, "nav"),
    ("ui/inventory_icon_1767579900.png", 48, "nav"),
    ("ui/shard_icon_1767577370.png", 48, "nav"),
    ("ui/favicon_icon_1767579909.png", 64, "nav"),  # Favicon needs a bit more

    # ARIA avatar - displayed at 40px
    ("aria/concept_aria_rock_v3_1767666240.png", 80, "thumb"),  # 2x for retina

    # Hero images - displayed at ~400px width typically
    ("ui/hero_base_hq_1767642994.png", 800, "hero"),  # 2x for retina
    ("ui/hero_depot_1767643003.png", 800, "hero"),
    ("ui/hero_expeditions_1767643013.png", 800, "hero"),
    ("ui/hero_inventory_1767643020.png", 800, "hero"),

    # Banner images
    ("ui/banner_step1_orbit_1767634740.png", 800, "banner"),
    ("ui/banner_step2_crew_1767634751.png", 800, "banner"),
    ("ui/banner_step3_landing_1767634761.png", 800, "banner"),

    # Background images - displayed at various sizes
    ("ui/mars_surface_bg_1767636111.png", 600, "bg"),
    ("ui/crew_card_bg_1767636038.png", 400, "bg"),
]


def download_image(gcs_path):
    """Download image from GCS."""
    url = f"https://storage.googleapis.com/{BUCKET_NAME}/{gcs_path}"
    print(f"  📥 Downloading: {url}")
    response = requests.get(url)
    if response.status_code != 200:
        print(f"  ❌ Failed to download: {response.status_code}")
        return None
    return Image.open(BytesIO(response.content))


def create_thumbnail(img, max_size):
    """Create a thumbnail maintaining aspect ratio."""
    # Convert to RGBA if needed
    if img.mode not in ('RGBA', 'RGB'):
        img = img.convert('RGBA')

    # Resize using high-quality downsampling
    img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
    return img


def upload_to_gcs(img, gcs_path, content_type='image/png'):
    """Upload image to GCS."""
    client = storage.Client()
    bucket = client.bucket(BUCKET_NAME)
    blob = bucket.blob(gcs_path)

    # Save to bytes
    buffer = BytesIO()
    img.save(buffer, format='PNG', optimize=True)
    buffer.seek(0)

    blob.upload_from_file(buffer, content_type=content_type)
    blob.cache_control = 'public, max-age=31536000'  # 1 year cache
    blob.patch()

    return f"https://storage.googleapis.com/{BUCKET_NAME}/{gcs_path}"


def get_thumb_path(original_path, suffix):
    """Generate thumbnail path from original."""
    base, ext = os.path.splitext(original_path)
    return f"{base}_{suffix}{ext}"


def main():
    print("🖼️  Generating optimized thumbnails for UI images...\n")

    results = []

    for gcs_path, max_size, suffix in UI_IMAGES:
        print(f"\n📸 Processing: {gcs_path}")

        # Download original
        img = download_image(gcs_path)
        if not img:
            continue

        original_size = img.size
        print(f"  📐 Original size: {original_size[0]}x{original_size[1]}")

        # Create thumbnail
        thumb = create_thumbnail(img, max_size)
        thumb_size = thumb.size
        print(f"  📐 Thumbnail size: {thumb_size[0]}x{thumb_size[1]}")

        # Upload thumbnail
        thumb_path = get_thumb_path(gcs_path, suffix)
        url = upload_to_gcs(thumb, thumb_path)
        print(f"  ✅ Uploaded: {thumb_path}")

        # Check new size
        response = requests.head(url)
        new_size = int(response.headers.get('content-length', 0))
        print(f"  📦 New size: {new_size:,} bytes ({new_size/1024:.1f} KB)")

        results.append({
            'original': gcs_path,
            'thumb': thumb_path,
            'url': url,
            'original_dimensions': original_size,
            'thumb_dimensions': thumb_size,
            'size_bytes': new_size
        })

    print("\n" + "="*60)
    print("📋 SUMMARY - Use these URLs in templates:\n")

    for r in results:
        print(f"Original: {r['original']}")
        print(f"Thumb:    {r['url']}")
        print(f"Size:     {r['size_bytes']/1024:.1f} KB")
        print()

    print("="*60)
    print("\n✨ Done! Update templates to use the thumbnail URLs.")
    print("\nExample change in base.html:")
    print("  OLD: https://storage.googleapis.com/.../base_icon_1767579866.png")
    print("  NEW: https://storage.googleapis.com/.../base_icon_1767579866_nav.png")


if __name__ == "__main__":
    main()
