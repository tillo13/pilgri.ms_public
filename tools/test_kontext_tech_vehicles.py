#!/usr/bin/env python3
"""Quick Vehicles Tech Branch progression test - Lv1→Lv10"""

import sys
import os
import time
import logging

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utilities.replicate_utils import FluxGenerator
from utilities.google_cloud_storage_utils import upload_blob_from_url

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

LEVEL_1_IMAGE = "https://storage.googleapis.com/galactica-pilgrim-assets/tech_icons/material_science_1769193926.png"

# Clean prompts - no numbers, no specific names
MATERIAL_PROGRESSION = {
    2: "Add dust weathering, slightly more mechanical components visible",
    3: "More complex machinery, rugged field equipment with red dust accumulation",
    4: "Reinforced frame, clay-colored rocky components beginning to appear",
    5: "Replace some metal with compressed rocky slabs, terrain textures appearing",
    6: "More geological materials, basalt-like structures visible in the design",
    7: "Small blue-purple crystals beginning to appear in crevices and joints",
    8: "Heavy crystal integration, crystals powering equipment, ancient tech feel",
    9: "Fully integrated with rocky terrain, crystals pulsing with energy throughout",
    10: "Grown from geology itself, massive crystal core, looks ancient and powerful",
}

def run_test():
    flux = FluxGenerator()
    current_image = LEVEL_1_IMAGE
    results = []

    for level in range(2, 11):
        logger.info(f"\n{'='*50}\nGENERATING LEVEL {level}\n{'='*50}")

        prompt = f"""Upgrade this vehicle research equipment: {MATERIAL_PROGRESSION[level]}.
Keep the same cartoon video game style with bold outlines.
Maintain mechanical equipment style but show material evolution.
Isolated on red terrain, vibrant colors."""

        start = time.time()
        result_url = flux.kontext_edit(current_image, prompt, "png")
        elapsed = time.time() - start

        timestamp = int(time.time())
        blob_name = f"tech_icons/vehicles_lv{level}_{timestamp}.png"
        gcs_url = upload_blob_from_url(result_url, blob_name, 'image/png')

        logger.info(f"✅ Level {level}: {elapsed:.1f}s → {gcs_url}")
        results.append({'level': level, 'url': gcs_url})
        current_image = gcs_url
        time.sleep(2)

    logger.info("\n\nALL VEHICLES TECH URLS:")
    logger.info(f"Lv1: {LEVEL_1_IMAGE}")
    for r in results:
        logger.info(f"Lv{r['level']}: {r['url']}")

if __name__ == "__main__":
    run_test()
