#!/usr/bin/env python3
"""
Generate email assets using Flux:
1. Mars banner header image (panoramic Mars landscape)
2. Fantasy-style icons for email sections (legendary artifact, rare finds, explorers, etc.)

These will be uploaded to GCS for use in FOMO emails.
"""

import sys
import os
import time
import requests
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utilities.replicate_utils import FluxGenerator, get_secret
import replicate


def generate_image_direct(prompt: str, aspect_ratio: str = "1:1", output_format: str = "png"):
    """Generate an image directly using Replicate Flux"""
    token = get_secret("REPLICATE_API_TOKEN")
    client = replicate.Client(api_token=token)

    print(f"  Generating: {prompt[:60]}...")

    output = client.run(
        "black-forest-labs/flux-schnell",
        input={
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "output_format": output_format,
            "num_outputs": 1
        }
    )

    # Get the URL from output
    if isinstance(output, list) and len(output) > 0:
        return str(output[0])
    return str(output)


def download_image(url: str, output_path: str) -> bool:
    """Download image from URL"""
    try:
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        with open(output_path, 'wb') as f:
            f.write(response.content)
        return True
    except Exception as e:
        print(f"  Failed to download: {e}")
        return False


def upload_email_asset(local_path: str, asset_name: str) -> str:
    """Upload asset to GCS and return public URL"""
    from google.cloud import storage

    GCP_PROJECT_ID = "galactica-character-game"
    BUCKET_NAME = "galactica-pilgrim-assets"

    blob_name = f"email_assets/{asset_name}"

    with open(local_path, 'rb') as f:
        file_data = f.read()

    storage_client = storage.Client(project=GCP_PROJECT_ID)
    bucket = storage_client.bucket(BUCKET_NAME)
    blob = bucket.blob(blob_name)

    content_type = 'image/png' if asset_name.endswith('.png') else 'image/jpeg'
    blob.upload_from_string(file_data, content_type=content_type)

    public_url = f"https://storage.googleapis.com/{BUCKET_NAME}/{blob_name}"
    print(f"  Uploaded: {public_url}")
    return public_url


def main():
    print("=" * 70)
    print("GENERATING EMAIL ASSETS")
    print("=" * 70)

    # Create temp directory for downloads
    temp_dir = tempfile.mkdtemp()

    assets_to_generate = [
        # Mars banner header - wide panoramic
        {
            "name": "mars_banner_header.jpg",
            "prompt": "Panoramic Mars landscape at sunset, red rocky terrain stretching to horizon, dusty atmosphere with orange sky, distant mountains and craters, cinematic sci-fi vista, dramatic lighting, no people, no text, photorealistic, 8k quality",
            "aspect_ratio": "16:9",
            "format": "jpg"
        },
        # Icon: Legendary artifact (star/crystal)
        {
            "name": "icon_legendary.png",
            "prompt": "Fantasy game icon, glowing golden crystal artifact with sparkles, magical aura, dark background, simple clean design, game UI style, no text",
            "aspect_ratio": "1:1",
            "format": "png"
        },
        # Icon: Rare finds (purple gem)
        {
            "name": "icon_rare.png",
            "prompt": "Fantasy game icon, glowing purple amethyst gem, magical energy, dark background, simple clean design, game UI style, no text",
            "aspect_ratio": "1:1",
            "format": "png"
        },
        # Icon: Explorers/Captains (helmet/figure)
        {
            "name": "icon_explorers.png",
            "prompt": "Fantasy game icon, futuristic space helmet with visor glow, sci-fi explorer, dark background, simple clean design, game UI style, no text",
            "aspect_ratio": "1:1",
            "format": "png"
        },
        # Icon: Discovery (telescope/eye)
        {
            "name": "icon_discovery.png",
            "prompt": "Fantasy game icon, glowing ancient telescope or mystical eye symbol, discovery theme, dark background, simple clean design, game UI style, no text",
            "aspect_ratio": "1:1",
            "format": "png"
        },
        # Icon: Value/Shards (crystal pile)
        {
            "name": "icon_shards.png",
            "prompt": "Fantasy game icon, pile of glowing teal energy crystals, valuable resources, dark background, simple clean design, game UI style, no text",
            "aspect_ratio": "1:1",
            "format": "png"
        },
    ]

    generated_urls = {}

    for asset in assets_to_generate:
        print(f"\n{asset['name']}:")

        try:
            # Generate image
            image_url = generate_image_direct(
                asset['prompt'],
                aspect_ratio=asset['aspect_ratio'],
                output_format=asset['format']
            )
            print(f"  Generated: {image_url[:60]}...")

            # Download
            local_path = os.path.join(temp_dir, asset['name'])
            if download_image(image_url, local_path):
                # Upload to GCS
                gcs_url = upload_email_asset(local_path, asset['name'])
                generated_urls[asset['name']] = gcs_url

                # Clean up local file
                os.unlink(local_path)

            # Small delay between generations
            time.sleep(2)

        except Exception as e:
            print(f"  ERROR: {e}")

    # Summary
    print("\n" + "=" * 70)
    print("GENERATED ASSETS")
    print("=" * 70)

    for name, url in generated_urls.items():
        print(f"{name}:")
        print(f"  {url}")

    # Output Python dict for easy copy-paste
    print("\n# Python dict for gmail_utils.py:")
    print("EMAIL_ASSETS = {")
    for name, url in generated_urls.items():
        key = name.replace('.png', '').replace('.jpg', '')
        print(f"    '{key}': '{url}',")
    print("}")

    # Cleanup temp dir
    os.rmdir(temp_dir)


if __name__ == "__main__":
    main()
