#!/usr/bin/env python3
"""
Generate hero/banner images for Pilgrims anonymous pages
Usage: python tools/generate_hero_images.py
"""

import sys
import os
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utilities.flux_utils import FluxGenerator
from utilities.google_cloud_storage_utils import upload_blob_from_url
from config import FLUX_MODEL

# Hero image prompts - Mars themed, cinematic, game style
HERO_IMAGES = {
    'mars_landing': """Cinematic wide shot of Mars surface at dawn, red rocky terrain stretching to horizon,
small spacecraft descending with engine glow, dramatic orange sky with dust clouds,
two tiny human silhouettes visible near landing zone, ancient crystal formations
glowing faintly in foreground, epic science fiction scene, video game concept art style,
vibrant Mars color palette, atmospheric perspective, 16:9 aspect ratio""",

    'mars_journey': """Space scene showing spacecraft traveling between Earth and Mars,
blue Earth in background, red Mars ahead, trail of stars,
small two-person capsule with engine glow, vast emptiness of space,
hopeful and adventurous mood, clean vector game art style,
vibrant colors against black space, sense of scale and journey""",

    'crystal_discovery': """Close-up of ancient glowing Sepolia crystal formation emerging from red Martian soil,
purple and blue bioluminescent glow, mysterious energy patterns,
astronaut gloved hand reaching toward it, dust particles floating,
sense of wonder and discovery, video game item art style,
dramatic lighting, vibrant purples and blues against red terrain""",

    'two_person_crew': """Stylized illustration of two astronauts standing together on Mars surface,
one in captain pose (confident stance), one with scientific equipment,
red Mars landscape behind them, small habitat dome in distance,
team spirit, adventure, determination, cartoon video game character style,
bold outlines, vibrant colors, heroic composition""",

    'mars_base_horizon': """Wide panoramic view of Mars horizon at sunset,
small colony structures silhouetted against orange sky,
solar panels and communication dishes visible,
two astronaut figures walking toward base,
hopeful frontier atmosphere, video game environment art,
warm oranges and purples, sense of new beginning""",
}


def generate_image(flux, name, prompt):
    """Generate a single hero image and upload to GCS"""
    print(f"\n{'='*50}")
    print(f"Generating {name}...")
    print(f"Prompt: {prompt[:100]}...")

    replicate_url = flux.client.run(
        FLUX_MODEL,
        input={'prompt': prompt}
    )

    if isinstance(replicate_url, list):
        replicate_url = replicate_url[0]
    else:
        replicate_url = str(replicate_url)

    print(f"Replicate URL: {replicate_url}")

    # Upload to GCS
    timestamp = int(time.time())
    blob_name = f"ui/hero_{name}_{timestamp}.png"

    gcs_url = upload_blob_from_url(replicate_url, blob_name, 'image/png')

    print(f"GCS URL: {gcs_url}")
    return gcs_url


def main():
    print("Generating Pilgrims Hero Images")
    print("=" * 50)

    flux = FluxGenerator()
    results = {}

    for name, prompt in HERO_IMAGES.items():
        url = generate_image(flux, name, prompt)
        results[name] = url
        time.sleep(2)  # Rate limiting

    # Print summary
    print("\n" + "=" * 50)
    print("GENERATION COMPLETE")
    print("=" * 50)
    print("\nHero image URLs:\n")

    for name, url in results.items():
        print(f"'{name}': '{url}',")

    print("\n\nUsage in templates:")
    print("""
<!-- Mars Landing Hero -->
<div style="width: 100%; height: 200px; background: url('URL_HERE') center/cover; border-radius: 12px; margin-bottom: 20px;"></div>

<!-- Or as img -->
<img src="URL_HERE" alt="Mars" style="width: 100%; border-radius: 12px; margin-bottom: 20px;">
""")


if __name__ == "__main__":
    main()
