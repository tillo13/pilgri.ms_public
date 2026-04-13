#!/usr/bin/env python3
"""Generate 5 robot stage component images via Flux text-to-image.

Each image matches the approved Mars-rock robot avatar style:
asymmetrical, built from Martian rock/clay/regolith, Sepolia crystal accents.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import logging
from utilities.flux_utils import FluxGenerator
from google.cloud import storage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GCS_BUCKET = "galactica-pilgrim-assets"

STAGE_PROMPTS = {
    "frame": (
        "Cartoon video game item with bold outlines and stylized proportions: "
        "A skeletal robot chassis frame built entirely from rough Martian rock and compressed regolith, "
        "asymmetrical limb bones of different thicknesses carved from red sandstone, "
        "crude joint sockets made of volcanic basalt, spine-like central column of stacked "
        "irregular stone vertebrae held together by glowing teal-purple Sepolia crystal veins, "
        "one arm socket larger than the other, hunched golem-like posture, "
        "no metal no glass no Earth technology, ancient geological appearance, "
        "isolated on red Martian terrain, vibrant reds and oranges, dark background, "
        "video game asset style"
    ),
    "plating": (
        "Cartoon video game item with bold outlines and stylized proportions: "
        "Thick armor hull plates for a robot, made entirely from layered Martian sedimentary rock slabs "
        "and iron-clay chunks, mismatched panel sizes fitted together imperfectly like a stone puzzle, "
        "cracked weathered surfaces showing ancient geological layers in deep rusty red and burnt orange, "
        "subtle small blue-purple Sepolia crystal nodes embedded in seams between plates, "
        "looks like shields carved from Mars cliff faces, no metal no glass, "
        "isolated on red Martian terrain, vibrant reds and oranges, dark background, "
        "video game asset style"
    ),
    "core": (
        "Cartoon video game item with bold outlines and stylized proportions: "
        "A glowing crystalline power reactor core for a Mars-built robot, "
        "rough geode-like outer shell of cracked Martian rock split open to reveal "
        "brilliant teal-purple Sepolia crystal cluster inside pulsing with energy, "
        "crystal veins radiating outward through the rocky shell like roots, "
        "asymmetrical shape like a natural mineral formation not manufactured, "
        "warm orange glow mixing with cool crystal light, no metal no glass, "
        "isolated on red Martian terrain, vibrant reds and oranges, dark background, "
        "video game asset style"
    ),
    "optics": (
        "Cartoon video game item with bold outlines and stylized proportions: "
        "An optical sensor array for a Mars-built robot, cluster of mismatched crystalline lenses "
        "grown naturally from Martian quartz formations, mounted in a rough red sandstone housing, "
        "three different-sized crystal eyes arranged asymmetrically, each lens a different shape "
        "with internal teal-purple Sepolia crystal glow, stone housing weathered and cracked, "
        "looks like a natural mineral cluster repurposed as vision sensors, no metal no glass no Earth tech, "
        "isolated on red Martian terrain, vibrant reds and oranges, dark background, "
        "video game asset style"
    ),
    "finish": (
        "Cartoon video game item with bold outlines and stylized proportions: "
        "Final decorative elements for a Mars-built rock robot: a collection of ancient Martian glyphs "
        "and symbols carved into flat stone tablets, a crude antenna made from a crystallized Sepolia shard "
        "growing upward like a natural crystal spire, ceremonial paint made from crushed red and orange "
        "Martian pigments in stone bowls, small charm-like crystal pendants on woven cord, "
        "everything rough and handcrafted from geological materials, no metal no glass, "
        "isolated on red Martian terrain, vibrant reds and oranges, dark background, "
        "video game asset style"
    ),
}

STAGE_ORDER = ["frame", "plating", "core", "optics", "finish"]


def upload_to_gcs(image_url, gcs_path):
    """Download image from URL and upload to GCS."""
    resp = requests.get(image_url, timeout=60)
    resp.raise_for_status()

    client = storage.Client()
    bucket = client.bucket(GCS_BUCKET)
    blob = bucket.blob(gcs_path)
    blob.upload_from_string(resp.content, content_type="image/png")

    public_url = f"https://storage.googleapis.com/{GCS_BUCKET}/{gcs_path}"
    logger.info(f"Uploaded to {public_url}")
    return public_url


def main():
    generator = FluxGenerator()
    results = {}

    for key in STAGE_ORDER:
        prompt = STAGE_PROMPTS[key]
        logger.info(f"\n{'='*60}")
        logger.info(f"Generating stage: {key}")
        logger.info(f"{'='*60}")

        # Generate via Flux text-to-image (flux-1.1-pro)
        def _generate():
            output = generator.client.run(
                "black-forest-labs/flux-1.1-pro",
                input={"prompt": prompt, "aspect_ratio": "1:1"}
            )
            if hasattr(output, 'url'):
                return output.url
            return str(output)

        result_url = generator._retry_api_call(f"Stage {key}", _generate)
        logger.info(f"Flux returned: {result_url}")

        # Upload to GCS
        gcs_path = f"ui/icons/robot_stage_{key}.png"
        public_url = upload_to_gcs(result_url, gcs_path)
        results[key] = public_url
        logger.info(f"✓ {key}: {public_url}")

    print("\n" + "="*60)
    print("ALL 5 STAGE IMAGES GENERATED:")
    print("="*60)
    for key in STAGE_ORDER:
        print(f"  {key}: {results[key]}")

    # Print config.py snippet
    print("\n# Add to config.py UI_ICONS:")
    for key in STAGE_ORDER:
        print(f"    'robot_stage_{key}': '{results[key]}',")


if __name__ == "__main__":
    main()
