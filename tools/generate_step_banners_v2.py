#!/usr/bin/env python3
"""
Generate step progression banners for Pilgrims onboarding flow
Wide cinematic banners in cartoon video game style matching our other assets
Uses Pillow to crop to 3:1 wide banner format

Usage: python tools/generate_step_banners_v2.py
"""

import sys
import os
import time
import requests
from io import BytesIO

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image
from google.cloud import storage
from utilities.replicate_utils import FluxGenerator
from config import FLUX_MODEL

# GCS Configuration
GCP_PROJECT_ID = "galactica-character-game"
BUCKET_NAME = "galactica-pilgrim-assets"


def upload_image_bytes(file_data, destination_blob_name, content_type='image/png'):
    """Upload bytes directly to GCS"""
    storage_client = storage.Client(project=GCP_PROJECT_ID)
    bucket = storage_client.bucket(BUCKET_NAME)
    blob = bucket.blob(destination_blob_name)
    blob.upload_from_string(file_data, content_type=content_type)
    return f"https://storage.googleapis.com/{BUCKET_NAME}/{destination_blob_name}"

# Wide banners in our cartoon video game style
# Key style elements: bold outlines, stylized proportions, vibrant colors, Mars reds/oranges

STEP_BANNERS = {
    'step1_orbit': """Cartoon video game scene with bold outlines and stylized proportions:
wide panoramic view of spacecraft approaching Mars from space,
small sleek two-person rocket ship with glowing blue engines on left side,
huge red Mars planet dominating right half of image,
tiny blue Earth visible in far distance,
starfield background with colorful nebula,
dramatic lighting with sun behind Mars creating orange halo,
video game concept art style, vibrant saturated colors,
bold black outlines on spacecraft, stylized not realistic""",

    'step2_crew': """Cartoon video game scene with bold outlines and stylized proportions:
wide panoramic interior view of spacecraft cockpit,
two glowing cryosleep pods in foreground (one green glow, one blue glow),
holographic control panels and displays showing crew silhouettes,
curved viewport window showing red Mars surface approaching,
warm orange and amber interior lighting,
futuristic but cartoony style controls and buttons,
video game UI aesthetic, vibrant colors,
bold outlines, stylized proportions""",

    'step3_landing': """Cartoon video game scene with bold outlines and stylized proportions:
wide panoramic view of spacecraft landing on Mars surface,
small rocket ship descending with dramatic orange engine flames,
red rocky Martian landscape stretching to horizon,
glowing purple crystal formations visible on surface,
dust clouds billowing from landing,
dramatic orange sunset sky with stars appearing,
video game concept art style, vibrant saturated Mars reds and oranges,
bold black outlines, stylized not realistic""",
}


def generate_and_crop_banner(flux, name, prompt):
    """Generate a banner, then crop it to 3:1 wide format"""
    print(f"\n{'='*60}")
    print(f"Generating {name}...")

    # Generate the image
    replicate_url = flux.client.run(
        FLUX_MODEL,
        input={'prompt': prompt}
    )

    if isinstance(replicate_url, list):
        replicate_url = replicate_url[0]
    else:
        replicate_url = str(replicate_url)

    print(f"Replicate URL: {replicate_url}")

    # Download and process with Pillow
    response = requests.get(replicate_url)
    img = Image.open(BytesIO(response.content))
    original_size = img.size
    print(f"Original size: {original_size}")

    # Crop to 3:1 aspect ratio (wide banner)
    # Take the center horizontal strip
    width, height = img.size
    target_ratio = 3.0  # 3:1 wide banner

    current_ratio = width / height

    if current_ratio < target_ratio:
        # Image is too tall, crop top and bottom
        new_height = int(width / target_ratio)
        top = (height - new_height) // 2
        img = img.crop((0, top, width, top + new_height))
    else:
        # Image is too wide, crop left and right
        new_width = int(height * target_ratio)
        left = (width - new_width) // 2
        img = img.crop((left, 0, left + new_width, height))

    # Resize to consistent banner size (1200 x 400)
    img = img.resize((1200, 400), Image.Resampling.LANCZOS)

    print(f"Final size: {img.size}")

    # Save to bytes for upload
    output = BytesIO()
    img.save(output, format='PNG', optimize=True)
    output.seek(0)

    # Upload to GCS
    timestamp = int(time.time())
    blob_name = f"ui/banner_{name}_{timestamp}.png"

    gcs_url = upload_image_bytes(output.read(), blob_name, 'image/png')

    print(f"GCS URL: {gcs_url}")
    return gcs_url


def main():
    print("="*60)
    print("Generating Pilgrims Step Banners v2")
    print("Cartoon video game style, 3:1 wide banners")
    print("="*60)

    flux = FluxGenerator()
    results = {}

    for name, prompt in STEP_BANNERS.items():
        url = generate_and_crop_banner(flux, name, prompt)
        results[name] = url
        time.sleep(2)  # Rate limiting

    # Print summary
    print("\n" + "="*60)
    print("GENERATION COMPLETE")
    print("="*60)
    print("\nBanner URLs (copy these to templates):\n")

    for name, url in results.items():
        print(f"'{name}': '{url}',")

    print("\n\nTemplate usage:")
    print("""
Step 1 (home.html):
<img src="STEP1_URL" alt="Approaching Mars" style="width: 100%; border-radius: 12px; margin-bottom: 20px; box-shadow: 0 8px 32px rgba(0,0,0,0.3);">

Step 2 (crew.html):
<img src="STEP2_URL" alt="Crew Selection" style="width: 100%; border-radius: 12px; margin-bottom: 20px; box-shadow: 0 8px 32px rgba(0,0,0,0.3);">

Step 3 (deploy.html):
<img src="STEP3_URL" alt="Mars Landing" style="width: 100%; border-radius: 12px; margin-bottom: 20px; box-shadow: 0 8px 32px rgba(0,0,0,0.3);">
""")


if __name__ == "__main__":
    main()
