#!/usr/bin/env python3
"""
Generate scientist versions of default leader portraits for Pilgrims.

Takes each leader in static/images/default_leaders/ and creates a scientist
version with lab coat/science gear, saving to static/images/default_scientists/

Usage: python tools/generate_scientist_portraits.py
"""

import sys
import os
import time
import base64
import re

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utilities.flux_utils import FluxGenerator
from utilities.google_cloud_storage_utils import upload_blob_from_url
from config import FLUX_MODEL

# Source and destination directories
LEADERS_DIR = "static/images/default_leaders"
SCIENTISTS_DIR = "static/images/default_scientists"

# Prompt to transform leader into scientist
SCIENTIST_PROMPT = """Same cartoon character, same face and features, but now wearing a white lab coat
over their space suit, holding a tablet or scientific instrument,
Mars research station laboratory background with screens and equipment,
professional scientist pose, same cute cartoon art style,
warm lighting from screens, scientific equipment visible"""


def extract_name_from_filename(filename):
    """Extract name from filename like 'leader1_andy.png' -> 'Andy'"""
    match = re.search(r'leader\d+_(\w+)\.png', filename)
    if match:
        return match.group(1).capitalize()
    return None


def get_leader_files():
    """Get all leader image files"""
    if not os.path.exists(LEADERS_DIR):
        print(f"Error: {LEADERS_DIR} not found")
        return []

    files = []
    for f in sorted(os.listdir(LEADERS_DIR)):
        if f.endswith('.png') and f.startswith('leader'):
            name = extract_name_from_filename(f)
            if name:
                files.append({'filename': f, 'name': name, 'path': os.path.join(LEADERS_DIR, f)})
    return files


def generate_scientist_portrait(flux, leader_info):
    """Generate a scientist version of a leader portrait"""
    name = leader_info['name']
    path = leader_info['path']

    print(f"\n{'='*50}")
    print(f"Processing: {name} ({leader_info['filename']})")

    # Read the local image file
    with open(path, 'rb') as f:
        image_data = f.read()

    # Convert to base64 data URI
    image_b64 = base64.b64encode(image_data).decode('utf-8')
    data_uri = f"data:image/png;base64,{image_b64}"

    # Generate scientist version using Flux
    print(f"  Generating scientist version...")
    output = flux.client.run(
        FLUX_MODEL,
        input={
            'input_image': data_uri,
            'prompt': SCIENTIST_PROMPT
        }
    )

    result_url = output[0] if isinstance(output, list) else str(output)
    print(f"  Replicate URL: {result_url}")

    # Upload to GCS
    timestamp = int(time.time())
    blob_name = f"scientists/scientist_{name.lower()}_{timestamp}.png"
    gcs_url = upload_blob_from_url(result_url, blob_name, 'image/png')
    print(f"  GCS URL: {gcs_url}")

    return {
        'name': name,
        'original': leader_info['filename'],
        'gcs_url': gcs_url
    }


def main():
    print("=" * 60)
    print("SCIENTIST PORTRAIT GENERATOR")
    print("=" * 60)

    # Create output directory if needed
    os.makedirs(SCIENTISTS_DIR, exist_ok=True)

    # Get all leader files
    leaders = get_leader_files()
    print(f"\nFound {len(leaders)} leader portraits:")
    for l in leaders:
        print(f"  - {l['name']} ({l['filename']})")

    if not leaders:
        print("No leaders found!")
        return

    # Initialize Flux
    print("\nInitializing Flux...")
    flux = FluxGenerator()

    # Process each leader
    results = []
    for leader in leaders:
        try:
            result = generate_scientist_portrait(flux, leader)
            results.append(result)
            time.sleep(2)  # Rate limiting
        except Exception as e:
            print(f"  ERROR: {e}")
            continue

    # Print summary
    print("\n" + "=" * 60)
    print("GENERATION COMPLETE")
    print("=" * 60)
    print(f"\nGenerated {len(results)}/{len(leaders)} scientist portraits:\n")

    print("# Add to config.py or database:")
    print("SCIENTIST_PORTRAITS = {")
    for r in results:
        print(f"    '{r['name'].lower()}': '{r['gcs_url']}',")
    print("}")

    print("\n# Scientist names for random assignment:")
    for r in results:
        print(f"#   Dr. {r['name']} - Colony Scientist")


if __name__ == "__main__":
    main()
