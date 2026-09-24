#!/usr/bin/env python3
"""Quick Exploration Tech Branch progression test - Lv1→Lv10"""

import sys
import os
import time
import logging

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utilities.replicate_utils import FluxGenerator
from utilities.google_cloud_storage_utils import upload_blob_from_url

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Level 1 starting image - Wind Analysis I
LEVEL_1_IMAGE = "https://storage.googleapis.com/galactica-pilgrim-assets/tech_icons/wind_analysis_1769193865.png"

LEVEL_NAMES = {
    1: 'Wind Analysis I', 2: 'Terrain Mapping', 3: 'Storm Watch', 4: 'Advanced Sensors',
    5: 'Storm Prediction', 6: 'Subsurface Mapping', 7: 'Deep Scanning', 8: 'Resonance Detection',
    9: 'Storm Mastery', 10: 'Exploration Mastery',
}

MATERIAL_PROGRESSION = {
    2: "Add dust weathering and minor wear marks, slightly more equipment visible",
    3: "Add atmospheric sensors, rugged field equipment with Martian dust accumulation",
    4: "More sensor arrays, clay-colored regolith components beginning to appear",
    5: "Replace some metal panels with compressed regolith, rocky textures appearing",
    6: "Subsurface scanning equipment carved from Martian rock, geological textures dominant",
    7: "Basalt structures visible, small blue-purple Sepolia crystals beginning to appear",
    8: "Heavy Sepolia crystal integration, crystals embedded throughout, ancient tech feel",
    9: "Fully integrated with Mars terrain, crystals pulsing with energy throughout",
    10: "Grown from Martian geology itself, massive Sepolia crystal core, looks ancient and powerful",
}

def run_test():
    flux = FluxGenerator()
    current_image = LEVEL_1_IMAGE
    results = []

    for level in range(2, 11):
        logger.info(f"\n{'='*50}\nGENERATING LEVEL {level}: {LEVEL_NAMES[level]}\n{'='*50}")

        prompt = f"""Upgrade this exploration research equipment: {MATERIAL_PROGRESSION[level]}.
Keep the same cartoon video game style with bold outlines.
Maintain research equipment style but show material evolution.
Isolated on red Martian terrain, vibrant colors."""

        start = time.time()
        result_url = flux.kontext_edit(current_image, prompt, "png")
        elapsed = time.time() - start

        timestamp = int(time.time())
        blob_name = f"tech_icons/exploration_lv{level}_{timestamp}.png"
        gcs_url = upload_blob_from_url(result_url, blob_name, 'image/png')

        logger.info(f"✅ Level {level}: {elapsed:.1f}s → {gcs_url}")
        results.append({'level': level, 'name': LEVEL_NAMES[level], 'url': gcs_url})
        current_image = gcs_url
        time.sleep(2)

    # Print all URLs
    logger.info("\n\nALL EXPLORATION TECH URLS:")
    logger.info(f"Lv1: {LEVEL_1_IMAGE}")
    for r in results:
        logger.info(f"Lv{r['level']}: {r['url']}")

if __name__ == "__main__":
    run_test()
