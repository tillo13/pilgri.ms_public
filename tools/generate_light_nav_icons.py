#!/usr/bin/env python3
"""
Generate light mode nav bar icons for Pilgrims using Flux Kontext
Takes existing dark mode icons and transforms them for light backgrounds

Usage: python tools/generate_light_nav_icons.py
"""

import sys
import os
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utilities.replicate_utils import FluxGenerator
from utilities.google_cloud_storage_utils import upload_blob_from_url
from config import FLUX_MODEL

# Current dark mode icons (dark purple background)
DARK_ICONS = {
    'base': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/base_icon_1767579866_nav.png',
    'crew': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/crew_icon_1767579874_nav.png',
    'depot': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/depot_icon_1767579883_nav.png',
    'expeditions': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/expeditions_icon_1767579891_nav.png',
    'inventory': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/inventory_icon_1767579900_nav.png',
    'lore': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/lore_icon_1767820192_nav.png',
}

# Kontext prompt for light mode transformation
LIGHT_MODE_PROMPT = """Transform this icon for light mode UI:
- Change the dark purple background to a warm cream/off-white color (#faf8f5)
- Keep the icon shape and symbol exactly the same
- Adjust the icon color if needed for visibility on light background
- Maintain the flat, minimal app icon style
- Keep crisp edges and geometric shapes"""


def transform_icon_to_light(flux, name, dark_url):
    """Use Kontext to transform dark icon to light mode"""
    print(f"\n{'='*50}")
    print(f"Transforming {name} icon to light mode...")
    print(f"Source: {dark_url}")

    try:
        output = flux.client.run(
            FLUX_MODEL,
            input={
                'prompt': LIGHT_MODE_PROMPT,
                'image': dark_url,
                'guidance_scale': 3.5,
                'steps': 30,
            }
        )

        if isinstance(output, list):
            replicate_url = output[0]
        else:
            replicate_url = str(output)

        print(f"Replicate URL: {replicate_url}")

        # Upload to GCS with light suffix
        timestamp = int(time.time())
        blob_name = f"ui/{name}_icon_{timestamp}_nav_light.png"

        gcs_url = upload_blob_from_url(replicate_url, blob_name, 'image/png')

        print(f"GCS URL: {gcs_url}")
        return gcs_url

    except Exception as e:
        print(f"Error transforming {name}: {e}")
        return None


def main():
    print("Generating Light Mode Nav Icons")
    print("=" * 50)

    flux = FluxGenerator()
    results = {}

    for name, dark_url in DARK_ICONS.items():
        light_url = transform_icon_to_light(flux, name, dark_url)
        if light_url:
            results[name] = light_url
        time.sleep(3)  # Rate limiting

    # Print summary
    print("\n" + "=" * 50)
    print("GENERATION COMPLETE")
    print("=" * 50)
    print("\nLight mode icon URLs:\n")

    for name, url in results.items():
        print(f"'{name}_light': '{url}',")

    print("\n\nUpdate base.html to use theme-aware icons:")
    print("""
<!-- Example for base icon -->
<picture>
    <source srcset="{{ icon_dark }}" media="(prefers-color-scheme: dark)">
    <img src="{{ icon_light }}" alt="Base" class="nav-icon-img">
</picture>

Or use CSS to swap based on data-theme attribute.
""")


if __name__ == "__main__":
    main()
