#!/usr/bin/env python3
"""
Generate step progression banners for Pilgrims onboarding flow
Wide cinematic banners showing the journey: Orbit → Crew Selection → Landing

Usage: python tools/generate_step_banners.py
"""

import sys
import os
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utilities.replicate_utils import FluxGenerator
from utilities.google_cloud_storage_utils import upload_blob_from_url
from config import FLUX_MODEL

# Wide cinematic banners - 16:9 or wider aspect ratio prompts
# Each tells part of the journey story

STEP_BANNERS = {
    'step1_orbit': """Ultra-wide cinematic banner, spacecraft approaching Mars from Earth orbit,
small sleek two-person capsule in foreground with glowing engines,
red Mars planet filling right side of frame, blue Earth small in distance on left,
stars and space dust, engine trail streaking across image,
dramatic lighting, sense of vast journey beginning,
video game concept art style, rich colors, 21:9 ultrawide aspect ratio composition,
horizontal banner format, no text""",

    'step2_crew': """Ultra-wide cinematic banner, interior of spacecraft cockpit looking out at Mars,
two cryosleep pods visible in foreground (one captain, one scientist),
holographic displays showing crew stats and vitals,
Mars surface visible through curved viewport window,
warm amber interior lighting contrasting with red Mars outside,
video game UI aesthetic, futuristic but grounded,
horizontal banner format, 21:9 ultrawide composition, no text""",

    'step3_landing': """Ultra-wide cinematic banner, spacecraft descending through Mars atmosphere,
dramatic entry flames and heat shield glow,
red Martian landscape visible below through clouds of dust,
ancient crystal formations glinting on surface catching sunlight,
two small figures visible through capsule window,
epic moment of arrival, video game cinematic style,
horizontal banner format, 21:9 ultrawide composition, no text""",
}


def generate_banner(flux, name, prompt):
    """Generate a single banner and upload to GCS"""
    print(f"\n{'='*60}")
    print(f"Generating {name}...")
    print(f"Prompt preview: {prompt[:80]}...")

    replicate_url = flux.client.run(
        FLUX_MODEL,
        input={
            'prompt': prompt,
            'aspect_ratio': '21:9'  # Ultrawide cinematic
        }
    )

    if isinstance(replicate_url, list):
        replicate_url = replicate_url[0]
    else:
        replicate_url = str(replicate_url)

    print(f"Replicate URL: {replicate_url}")

    # Upload to GCS
    timestamp = int(time.time())
    blob_name = f"ui/banner_{name}_{timestamp}.png"

    gcs_url = upload_blob_from_url(replicate_url, blob_name, 'image/png')

    print(f"GCS URL: {gcs_url}")
    return gcs_url


def main():
    print("="*60)
    print("Generating Pilgrims Step Banners")
    print("Cinematic 21:9 ultrawide banners for onboarding flow")
    print("="*60)

    flux = FluxGenerator()
    results = {}

    for name, prompt in STEP_BANNERS.items():
        url = generate_banner(flux, name, prompt)
        results[name] = url
        time.sleep(2)  # Rate limiting

    # Print summary
    print("\n" + "="*60)
    print("GENERATION COMPLETE")
    print("="*60)
    print("\nBanner URLs:\n")

    for name, url in results.items():
        print(f"'{name}': '{url}',")

    print("\n\nUsage in templates:")
    print("""
<!-- Step 1: Orbit - Home page -->
<img src="STEP1_URL" alt="Approaching Mars" style="width: 100%; border-radius: 12px; margin-bottom: 20px;">

<!-- Step 2: Crew Selection - Crew page -->
<img src="STEP2_URL" alt="Crew Selection" style="width: 100%; border-radius: 12px; margin-bottom: 20px;">

<!-- Step 3: Landing - Deploy page -->
<img src="STEP3_URL" alt="Mars Landing" style="width: 100%; border-radius: 12px; margin-bottom: 20px;">
""")


if __name__ == "__main__":
    main()
