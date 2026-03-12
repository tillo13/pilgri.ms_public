#!/usr/bin/env python3
"""
Generate activity tab category icons for Colony page.
Usage: python tools/generate_activity_icons.py
"""

import sys
import os
import time
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utilities.flux_utils import FluxGenerator
from utilities.google_cloud_storage_utils import upload_blob_from_url
from config import FLUX_MODEL

ACTIVITY_ICONS = {
    'activity_purchase': """Flat icon, simple stack of coins or crystal shards silhouette, single color amber-gold,
solid dark purple background, minimal detail, app icon style,
geometric shape, no gradients, no texture, crisp edges,
centered, square format, looks good at 24px""",

    'activity_infrastructure': """Flat icon, simple Mars dome building or tower silhouette, single color purple-violet,
solid dark purple background, minimal detail, app icon style,
geometric shape, no gradients, no texture, crisp edges,
centered, square format, looks good at 24px""",

    'activity_expedition': """Flat icon, simple rocket ship launching silhouette, single color cyan-blue,
solid dark purple background, minimal detail, app icon style,
geometric shape, no gradients, no texture, crisp edges,
centered, square format, looks good at 24px""",

    'activity_upgrade': """Flat icon, simple upward arrow with gear cog silhouette, single color green,
solid dark purple background, minimal detail, app icon style,
geometric shape, no gradients, no texture, crisp edges,
centered, square format, looks good at 24px""",

    'activity_discovery': """Flat icon, simple glowing crystal gem silhouette, single color orange,
solid dark purple background, minimal detail, app icon style,
geometric shape, no gradients, no texture, crisp edges,
centered, square format, looks good at 24px""",

    'activity_landmark': """Flat icon, simple planet or globe with pin marker silhouette, single color teal,
solid dark purple background, minimal detail, app icon style,
geometric shape, no gradients, no texture, crisp edges,
centered, square format, looks good at 24px""",

    'activity_claim': """Flat icon, simple flag planted in ground silhouette, single color indigo-blue,
solid dark purple background, minimal detail, app icon style,
geometric shape, no gradients, no texture, crisp edges,
centered, square format, looks good at 24px""",

    'activity_research': """Flat icon, simple laboratory beaker with bubbles silhouette, single color pink-magenta,
solid dark purple background, minimal detail, app icon style,
geometric shape, no gradients, no texture, crisp edges,
centered, square format, looks good at 24px""",
}


def generate_icon(flux, name, prompt):
    """Generate a single icon and upload to GCS"""
    print(f"\n{'='*50}")
    print(f"Generating {name} icon...")

    replicate_url = flux.client.run(
        FLUX_MODEL,
        input={'prompt': prompt, 'aspect_ratio': '1:1'}
    )

    if isinstance(replicate_url, list):
        replicate_url = replicate_url[0]
    else:
        replicate_url = str(replicate_url)

    print(f"Replicate URL: {replicate_url}")

    # Upload to GCS
    timestamp = int(time.time())
    blob_name = f"ui/icons/{name}_{timestamp}.png"
    gcs_url = upload_blob_from_url(replicate_url, blob_name, 'image/png')
    print(f"GCS URL: {gcs_url}")
    return gcs_url


def main():
    print("Generating Activity Tab Icons")
    print("=" * 50)

    flux = FluxGenerator()
    results = {}

    for name, prompt in ACTIVITY_ICONS.items():
        url = generate_icon(flux, name, prompt)
        results[name] = url
        time.sleep(2)

    # Save results
    output_path = '/tmp/activity_icons_results.json'
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)

    print("\n" + "=" * 50)
    print("GENERATION COMPLETE")
    print("=" * 50)
    print(f"\nResults saved to {output_path}")
    print("\nURLs:")
    for name, url in results.items():
        print(f'  {name}: {url}')


if __name__ == '__main__':
    main()
