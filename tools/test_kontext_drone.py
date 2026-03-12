#!/usr/bin/env python3
"""Quick drone progression test - Lv1→Lv10"""

import sys
import os
import time
import logging

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utilities.flux_utils import FluxGenerator
from utilities.google_cloud_storage_utils import upload_blob_from_url

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

LEVEL_1_IMAGE = "https://storage.googleapis.com/galactica-pilgrim-assets/upgrades/vehicles_drone_lv1_1767751017.png"

LEVEL_NAMES = {
    1: 'Drone Mk I', 2: 'Drone Mk II', 3: 'Drone Mk III', 4: 'Drone Mk IV',
    5: 'Drone Mk V', 6: 'Drone Mk VI', 7: 'Drone Mk VII', 8: 'Drone Mk VIII',
    9: 'Drone Mk IX', 10: 'Drone Mk X',
}

MATERIAL_PROGRESSION = {
    2: "Add dust weathering and minor scratches, slightly more rugged",
    3: "More wear marks, dust accumulation, looking battle-tested",
    4: "Add patches of Martian clay, some regolith dust embedded in joints",
    5: "Replace some panels with compressed regolith, clay-like textures appearing",
    6: "Body becoming more geological, basalt components visible, rocky textures",
    7: "Small blue-purple Sepolia crystal nodes starting to appear in crevices",
    8: "More Sepolia crystals embedded, alien geological appearance",
    9: "Heavy crystal integration, looks partially grown from Mars terrain",
    10: "Massive Sepolia crystal core, ancient alien technology fused with Mars geology",
}

def run_test():
    flux = FluxGenerator()
    current_image = LEVEL_1_IMAGE
    results = []

    for level in range(2, 11):
        logger.info(f"\n{'='*50}\nGENERATING LEVEL {level}: {LEVEL_NAMES[level]}\n{'='*50}")

        prompt = f"""Upgrade this drone to Level {level} "{LEVEL_NAMES[level]}": {MATERIAL_PROGRESSION[level]}.
Keep the same cartoon video game style with bold outlines.
Maintain overall shape but show material evolution.
Isolated on red Martian terrain, vibrant colors."""

        start = time.time()
        result_url = flux.kontext_edit(current_image, prompt, "png")
        elapsed = time.time() - start

        timestamp = int(time.time())
        blob_name = f"test_generation/kontext_drone_lv{level}_{timestamp}.png"
        gcs_url = upload_blob_from_url(result_url, blob_name, 'image/png')

        logger.info(f"✅ Level {level}: {elapsed:.1f}s → {gcs_url}")
        results.append({'level': level, 'url': gcs_url})
        current_image = gcs_url
        time.sleep(2)

    # Print all URLs for Chrome
    logger.info("\n\nALL DRONE URLS:")
    logger.info(f"Lv1: {LEVEL_1_IMAGE}")
    for r in results:
        logger.info(f"Lv{r['level']}: {r['url']}")

if __name__ == "__main__":
    run_test()
