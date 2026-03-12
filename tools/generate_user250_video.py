#!/usr/bin/env python3
"""
Generate video for User 250 (Trustable) only - their video was missing.
"""

import sys
import os
import time
import tempfile
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utilities.flux_utils import FluxGenerator
from utilities.video_utils import extract_thumbnail, upload_video_to_gcs, upload_thumbnail_to_gcs
from utilities.postgres_utils import db_cursor


def download_video(url: str, output_path: str) -> bool:
    """Download video from URL"""
    try:
        response = requests.get(url, timeout=120)
        response.raise_for_status()
        with open(output_path, 'wb') as f:
            f.write(response.content)
        return True
    except Exception as e:
        print(f"Failed to download: {e}")
        return False


def main():
    print("=" * 70)
    print("GENERATE VIDEO FOR USER 250 (Trustable)")
    print("=" * 70)

    # Get User 250's commander image
    with db_cursor() as cur:
        cur.execute("""
            SELECT commander_name, gcs_url
            FROM pilgrim.replicate_assets
            WHERE user_id = 250 AND asset_type IN ('flux_image', 'edited_image')
            AND gcs_url IS NOT NULL
            ORDER BY is_primary_character DESC NULLS LAST, created_at DESC
            LIMIT 1
        """)
        commander = cur.fetchone()

    if not commander:
        print("No commander found for User 250!")
        return

    commander_name = commander['commander_name'] or 'Captain'
    commander_image_url = commander['gcs_url']

    print(f"Captain: {commander_name}")
    print(f"Image: {commander_image_url[:60]}...")

    # Initialize Flux
    print("\nInitializing FluxGenerator...")
    flux_generator = FluxGenerator()

    # Generate video
    print("\nGenerating video...")
    video_prompt = "A space commander walking confidently across the Martian landscape, red rocky terrain, dust particles floating, cinematic lighting, dramatic sky with distant stars visible, slow deliberate movement, heroic pose"

    video_url = flux_generator.animate_character(
        commander_image_url,
        custom_prompt=video_prompt,
        num_frames=81,
        resolution="480p",
        go_fast=True
    )

    print(f"Replicate returned: {video_url[:60]}...")

    # Download
    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
        tmp_mp4 = tmp.name

    if not download_video(video_url, tmp_mp4):
        print("Download failed!")
        return

    mp4_size = os.path.getsize(tmp_mp4) / (1024 * 1024)
    print(f"Downloaded: {mp4_size:.2f} MB")

    # Extract thumbnail
    tmp_thumb = tmp_mp4.replace('.mp4', '_thumb.jpg')
    if not extract_thumbnail(tmp_mp4, tmp_thumb, timestamp="00:00:02", width=480, add_play_button=True):
        print("Thumbnail extraction failed!")
        os.unlink(tmp_mp4)
        return

    # Upload to GCS
    print("\nUploading to GCS...")
    video_gcs_url = upload_video_to_gcs(tmp_mp4, 250, "captain_fomo")
    thumbnail_gcs_url = upload_thumbnail_to_gcs(tmp_thumb, 250, "captain_fomo")

    # Cleanup
    os.unlink(tmp_mp4)
    os.unlink(tmp_thumb)

    print("\n" + "=" * 70)
    print("SUCCESS!")
    print("=" * 70)
    print(f"Video URL: {video_gcs_url}")
    print(f"Thumbnail URL: {thumbnail_gcs_url}")
    print("\nAdd to USER_VIDEOS dict:")
    print(f"""    250: {{
        'video_url': '{video_gcs_url}',
        'thumbnail_url': '{thumbnail_gcs_url}'
    }},""")


if __name__ == "__main__":
    main()
