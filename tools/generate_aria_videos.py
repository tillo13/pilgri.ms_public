#!/usr/bin/env python3
"""
Generate ARIA animation videos using WAN 2.2 model.

Takes the selected ARIA concept image and creates various animation videos
showing her moving around, crystals pulsing, etc.

Usage:
    python tools/generate_aria_videos.py
"""

import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utilities.replicate_utils import FluxGenerator
from utilities.google_cloud_storage_utils import upload_blob_from_url
from config import WAN_VIDEO_MODEL

# The selected ARIA concept from Round 12, v3
ARIA_IMAGE_URL = "https://storage.googleapis.com/galactica-pilgrim-assets/aria/concept_aria_rock_v3_1767666240.png"

# Different animation prompts for ARIA
ARIA_ANIMATIONS = {
    'aria_idle_v1': """cute rock golem creature gently swaying side to side, purple crystals on head pulsing with soft purple-orange glow, big warm eyes blinking slowly, stone body shifting slightly, subtle idle animation, friendly curious expression, smooth looping motion""",

    'aria_wave_v1': """adorable rock creature raising one stone mitten hand in friendly wave gesture, purple crystals glowing brighter as it waves, warm eyes looking at camera, happy welcoming expression, gentle rocking motion on stone treads""",

    'aria_look_v1': """cute rock golem turning head side to side curiously, big eyes looking around with interest, purple crystals catching light as head moves, stone body stable, inquisitive searching animation""",

    'aria_happy_v1': """rock creature doing small happy bounce, purple crystals pulsing rapidly with excitement, eyes squinting with joy, stone mitten hands moving happily, adorable celebration wiggle""",

    'aria_crystals_v1': """stone creature staying still while purple crystals on head pulse and glow with inner orange fire, magical energy radiating outward, crystals shimmer and sparkle, mesmerizing Sepolia energy effect""",
}


def generate_video(flux, name, prompt):
    """Generate a single ARIA animation video"""
    print(f"\n{'='*60}")
    print(f"Generating ARIA video: {name}")
    print(f"Prompt: {prompt[:80]}...")
    print(f"{'='*60}")

    # Use WAN 2.2 model with the ARIA image
    video_url = flux.client.run(
        WAN_VIDEO_MODEL,
        input={
            "image": ARIA_IMAGE_URL,
            "prompt": prompt,
            "go_fast": True,
            "num_frames": 81,  # ~3 seconds at 24fps
            "resolution": "480p",
            "sample_shift": 8.0,
            "frames_per_second": 24,
        }
    )

    video_url = str(video_url)
    print(f"Replicate URL: {video_url[:80]}...")

    # Upload to GCS
    timestamp = int(time.time())
    blob_name = f"aria/video_{name}_{timestamp}.mp4"

    gcs_url = upload_blob_from_url(video_url, blob_name, 'video/mp4')

    print(f"GCS URL: {gcs_url}")
    return gcs_url


def main():
    print("=" * 60)
    print("ARIA Animation Video Generator")
    print("=" * 60)
    print(f"\nSource image: {ARIA_IMAGE_URL}")
    print(f"Generating {len(ARIA_ANIMATIONS)} animation videos...\n")

    flux = FluxGenerator()

    results = {}
    for name, prompt in ARIA_ANIMATIONS.items():
        try:
            url = generate_video(flux, name, prompt)
            results[name] = url
            time.sleep(2)  # Rate limiting
        except Exception as e:
            print(f"Error generating {name}: {e}")
            results[name] = None

    print("\n" + "=" * 60)
    print("ARIA ANIMATION VIDEOS COMPLETE")
    print("=" * 60)

    for name, url in results.items():
        status = "OK" if url else "FAILED"
        print(f"  {status} {name}: {url or 'FAILED'}")

    return results


if __name__ == '__main__':
    main()
