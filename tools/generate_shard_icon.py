#!/usr/bin/env python3
"""
Generate a Sepolia Shard icon for the nav bar
Usage: python tools/generate_shard_icon.py
"""

import sys
import os
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utilities.replicate_utils import FluxGenerator
from utilities.google_cloud_storage_utils import upload_blob_from_url
from config import FLUX_MODEL

SHARD_ICON_PROMPT = """Simple icon design, single glowing purple crystal shard with orange energy inside,
faceted gemstone shape, magical glow effect, transparent background style,
centered composition, clean vector-like appearance, game UI icon style,
vibrant purple and orange colors, no text, minimalist"""

def main():
    print("Generating Sepolia Shard icon...")

    flux = FluxGenerator()

    replicate_url = flux.client.run(
        FLUX_MODEL,
        input={'prompt': SHARD_ICON_PROMPT}
    )

    if isinstance(replicate_url, list):
        replicate_url = replicate_url[0]
    else:
        replicate_url = str(replicate_url)

    print(f"Replicate URL: {replicate_url}")

    # Upload to GCS
    timestamp = int(time.time())
    blob_name = f"ui/shard_icon_{timestamp}.png"

    gcs_url = upload_blob_from_url(replicate_url, blob_name, 'image/png')

    print(f"\n✅ Shard icon generated!")
    print(f"GCS URL: {gcs_url}")
    print(f"\nAdd to base.html or config.py:")
    print(f'SHARD_ICON_URL = "{gcs_url}"')

if __name__ == "__main__":
    main()
