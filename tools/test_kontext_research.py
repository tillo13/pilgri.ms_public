#!/usr/bin/env python3
"""Quick Research Lab progression test - Lv1→Lv10"""

import sys
import os
import time
import logging

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utilities.flux_utils import FluxGenerator
from utilities.google_cloud_storage_utils import upload_blob_from_url

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

LEVEL_1_IMAGE = "https://storage.googleapis.com/galactica-pilgrim-assets/shop_items/research_lab_1767506665.png"

LEVEL_NAMES = {
    1: 'Field Lab', 2: 'Analysis Module', 3: 'Mobile Research Lab', 4: 'Specimen Chamber',
    5: 'Research Center', 6: 'Deep Analysis Array', 7: 'Martian Institute', 8: 'Xenolab Complex',
    9: 'Advanced Research Hub', 10: 'Mars Science Academy',
}

MATERIAL_PROGRESSION = {
    2: "Add dust weathering, more equipment visible, slightly expanded",
    3: "Mobile base visible, more scientific instruments, rugged field setup",
    4: "Add specimen containment pods, glowing analysis screens, more complex",
    5: "Larger structure, multiple lab modules connected, serious research facility",
    6: "Add crystalline sensor arrays, deep scanning equipment, Mars rock integration",
    7: "Grand institute building, Martian architecture, regolith walls beginning",
    8: "Alien-looking lab, blue-purple Sepolia crystals powering equipment",
    9: "Heavy crystal integration, looks partially grown from Mars terrain, advanced tech",
    10: "Massive Martian academy, Sepolia crystal core, ancient wisdom meets science",
}

def run_test():
    flux = FluxGenerator()
    current_image = LEVEL_1_IMAGE
    results = []

    for level in range(2, 11):
        logger.info(f"\n{'='*50}\nGENERATING LEVEL {level}: {LEVEL_NAMES[level]}\n{'='*50}")

        prompt = f"""Upgrade this research lab to Level {level} "{LEVEL_NAMES[level]}": {MATERIAL_PROGRESSION[level]}.
Keep the same cartoon video game style with bold outlines.
Maintain overall building shape but show material and complexity evolution.
Isolated on red Martian terrain, vibrant colors."""

        start = time.time()
        result_url = flux.kontext_edit(current_image, prompt, "png")
        elapsed = time.time() - start

        timestamp = int(time.time())
        blob_name = f"test_generation/kontext_research_lv{level}_{timestamp}.png"
        gcs_url = upload_blob_from_url(result_url, blob_name, 'image/png')

        logger.info(f"✅ Level {level}: {elapsed:.1f}s → {gcs_url}")
        results.append({'level': level, 'url': gcs_url})
        current_image = gcs_url
        time.sleep(2)

    # Print all URLs for Chrome
    logger.info("\n\nALL RESEARCH LAB URLS:")
    logger.info(f"Lv1: {LEVEL_1_IMAGE}")
    for r in results:
        logger.info(f"Lv{r['level']}: {r['url']}")

if __name__ == "__main__":
    run_test()
