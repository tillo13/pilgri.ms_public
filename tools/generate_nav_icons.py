#!/usr/bin/env python3
"""
Generate custom nav bar icons for Pilgrims
Usage: python tools/generate_nav_icons.py
"""

import sys
import os
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utilities.replicate_utils import FluxGenerator
from utilities.google_cloud_storage_utils import upload_blob_from_url
from config import FLUX_MODEL

# Icon prompts - consistent style with the shard icon
# Mars-themed, glowing, game UI style, clean vector appearance

NAV_ICONS = {
    'base': """Flat icon, simple Mars dome habitat silhouette, single color orange-red,
solid dark purple background, minimal detail, app icon style,
geometric shape, no gradients, no texture, crisp edges,
centered, square format, looks good at 24px""",

    'crew': """Flat icon, simple astronaut helmet silhouette, single color white,
solid dark purple background, minimal detail, app icon style,
geometric shape, no gradients, no texture, crisp edges,
centered, square format, looks good at 24px""",

    'depot': """Flat icon, simple supply crate or shop building silhouette, single color teal,
solid dark purple background, minimal detail, app icon style,
geometric shape, no gradients, no texture, crisp edges,
centered, square format, looks good at 24px""",

    'expeditions': """Flat icon, simple compass or map marker silhouette, single color orange,
solid dark purple background, minimal detail, app icon style,
geometric shape, no gradients, no texture, crisp edges,
centered, square format, looks good at 24px""",

    'inventory': """Flat icon, simple backpack or chest silhouette, single color green,
solid dark purple background, minimal detail, app icon style,
geometric shape, no gradients, no texture, crisp edges,
centered, square format, looks good at 24px""",
}

FAVICON_PROMPT = """Simple icon design, red Mars planet with subtle blue atmosphere halo,
small green vegetation patches visible on surface suggesting terraforming,
single planet centered, glowing orange rim from sun behind,
game icon style, clean vector appearance, dark space background,
no text, minimalist, suitable for favicon"""


def generate_icon(flux, name, prompt):
    """Generate a single icon and upload to GCS"""
    print(f"\n{'='*50}")
    print(f"Generating {name} icon...")

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
    blob_name = f"ui/{name}_icon_{timestamp}.png"

    gcs_url = upload_blob_from_url(replicate_url, blob_name, 'image/png')

    print(f"GCS URL: {gcs_url}")
    return gcs_url


def main():
    print("Generating Pilgrims Nav Icons")
    print("=" * 50)

    flux = FluxGenerator()
    results = {}

    # Generate nav icons
    for name, prompt in NAV_ICONS.items():
        url = generate_icon(flux, name, prompt)
        results[name] = url
        time.sleep(2)  # Rate limiting

    # Generate favicon
    print(f"\n{'='*50}")
    print("Generating favicon...")
    favicon_url = generate_icon(flux, 'favicon', FAVICON_PROMPT)
    results['favicon'] = favicon_url

    # Print summary
    print("\n" + "=" * 50)
    print("GENERATION COMPLETE")
    print("=" * 50)
    print("\nAdd these URLs to config.py or use directly:\n")

    for name, url in results.items():
        const_name = f"{name.upper()}_ICON_URL"
        print(f'{const_name} = "{url}"')

    print("\n\nFor base.html nav icons, replace emoji spans with:")
    print("""
<img src="{{ nav_icons.base }}" class="nav-icon-img" alt="Base">
<img src="{{ nav_icons.crew }}" class="nav-icon-img" alt="Crew">
<img src="{{ nav_icons.depot }}" class="nav-icon-img" alt="Depot">
<img src="{{ nav_icons.expeditions }}" class="nav-icon-img" alt="Expeditions">
<img src="{{ nav_icons.inventory }}" class="nav-icon-img" alt="Inventory">
""")


if __name__ == "__main__":
    main()
