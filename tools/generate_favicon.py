#!/usr/bin/env python3
"""
Generate favicon and PWA icons for Pilgrims

Creates a distinctive Mars + Sepolia crystal icon that works as:
- Favicon (small, recognizable)
- PWA icon (192x192, 512x512)
- Apple touch icon

Usage: python tools/generate_favicon.py
"""

import sys
import os
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utilities.replicate_utils import FluxGenerator
from utilities.google_cloud_storage_utils import upload_blob_from_url
from config import FLUX_MODEL

# The Pilgrims icon should represent:
# - Mars (red planet, dusty terrain)
# - Sepolia crystals (purple/violet with orange inner fire)
# - Ancient mystery, exploration
# - Clean enough to work at small sizes

FAVICON_PROMPT = """App icon design, glowing purple-violet Sepolia crystal cluster emerging from red Martian rock,
crystal has subtle orange inner fire glow, iconic Mars red-orange terrain base,
dark space background with subtle stars, game icon style,
clean bold shapes that read well at small sizes, centered composition,
no text, minimalist but striking, video game app icon aesthetic,
high contrast, the crystal is the hero element"""

FAVICON_PROMPT_ALT = """App icon, single glowing purple crystal shard on Mars surface,
red-orange dusty terrain, crystal emits soft violet and orange light,
dark starry background, bold silhouette, game app icon style,
reads clearly at 32px, centered, square format, no text"""

# More abstract/symbolic version
FAVICON_PROMPT_MINIMAL = """Minimalist app icon, stylized purple crystal shape on Mars red circle,
geometric, flat design with subtle glow effect, dark background,
bold simple shapes, works at favicon size, game branding icon,
purple and orange color accent, no text, centered"""


def generate_icon(flux, prompt, name_suffix=""):
    """Generate an icon and upload to GCS"""
    print(f"\n{'='*60}")
    print(f"Generating favicon{name_suffix}...")
    print(f"Prompt: {prompt[:100]}...")

    try:
        replicate_url = flux.client.run(
            FLUX_MODEL,
            input={
                'prompt': prompt,
                'aspect_ratio': '1:1',  # Square for icons
            }
        )

        if isinstance(replicate_url, list):
            replicate_url = replicate_url[0]
        else:
            replicate_url = str(replicate_url)

        print(f"Replicate URL: {replicate_url}")

        # Upload to GCS
        timestamp = int(time.time())
        blob_name = f"ui/favicon{name_suffix}_{timestamp}.png"

        gcs_url = upload_blob_from_url(replicate_url, blob_name, 'image/png')

        print(f"GCS URL: {gcs_url}")
        print(f"{'='*60}")
        return gcs_url

    except Exception as e:
        print(f"Error generating icon: {e}")
        return None


def main():
    print("=" * 60)
    print("PILGRIMS FAVICON GENERATOR")
    print("=" * 60)

    flux = FluxGenerator()

    # Generate multiple options to choose from
    results = []

    # Main favicon
    url = generate_icon(flux, FAVICON_PROMPT, "_crystal")
    if url:
        results.append(('Crystal cluster', url))

    # Alternative - single shard
    url = generate_icon(flux, FAVICON_PROMPT_ALT, "_shard")
    if url:
        results.append(('Single shard', url))

    # Minimal/geometric
    url = generate_icon(flux, FAVICON_PROMPT_MINIMAL, "_minimal")
    if url:
        results.append(('Minimal', url))

    print("\n" + "=" * 60)
    print("GENERATED ICONS:")
    print("=" * 60)
    for name, url in results:
        print(f"\n{name}:")
        print(f"  {url}")

    print("\n" + "=" * 60)
    print("NEXT STEPS:")
    print("=" * 60)
    print("""
1. View the generated icons and pick your favorite
2. Update templates/base.html with the new favicon URL:
   <link rel="icon" type="image/png" href="YOUR_CHOSEN_URL">

3. For PWA icons, download the image and resize to:
   - 192x192 for icon-192.png
   - 512x512 for icon-512.png
   Save to static/images/

4. Update static/manifest.json if using GCS URLs instead of local files
""")


if __name__ == '__main__':
    main()
