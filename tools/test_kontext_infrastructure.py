#!/usr/bin/env python3
"""Quick Infrastructure progression test - Refinery → Monolith Antenna (Tier 3→7)"""

import sys
import os
import time
import logging

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utilities.flux_utils import FluxGenerator
from utilities.google_cloud_storage_utils import upload_blob_from_url

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Tier 3 Refinery as starting point
TIER_3_IMAGE = "https://storage.googleapis.com/galactica-pilgrim-assets/infrastructure_items/refinery_1767509233.png"

TIER_INFO = {
    4: {
        'key': 'regolith_forge',
        'name': 'Regolith Forge',
        'description': 'Processes raw Martian regolith into refined materials',
        'prompt': "Upgrade this refinery building to a Regolith Forge: add large processing chambers carved from Martian rock, industrial heat vents glowing orange, compressed regolith walls with rocky textures, small blue-purple Sepolia crystal nodes appearing in crevices",
    },
    5: {
        'key': 'resonance_chamber',
        'name': 'Sepolia Resonance Chamber',
        'description': 'Amplifies Sepolia shard resonance frequencies',
        'prompt': "Transform this into a Sepolia Resonance Chamber: crystalline dome structure built from geological formations, heavy blue-purple Sepolia crystal integration throughout, resonating energy visible, walls made of stacked Martian sedimentary rock, mysterious ancient technology feel",
    },
    6: {
        'key': 'thermal_vent_tap',
        'name': 'Thermal Vent Tap',
        'description': 'Taps deep thermal vents for constant energy',
        'prompt': "Evolve this into a Thermal Vent Tap: structure built directly into volcanic Martian rock, steam vents and geothermal pipes emerging from ground, deep orange magma glow from below, heavy basalt construction, Sepolia crystals energized by geothermal heat",
    },
    7: {
        'key': 'monolith_antenna',
        'name': 'Monolith Antenna',
        'description': 'Ancient resonance array for deep shard detection',
        'prompt': "Transform into a Monolith Antenna: massive ancient Mars construction that looks grown from the terrain itself, huge Sepolia crystal core as the central antenna, geological wonder that appears almost alive, asymmetrical towering structure of volcanic rock and crystal formations, looks like it has been here for millennia",
    },
}

def run_test():
    flux = FluxGenerator()
    current_image = TIER_3_IMAGE
    results = []

    for tier in range(4, 8):
        info = TIER_INFO[tier]
        logger.info(f"\n{'='*50}\nGENERATING TIER {tier}: {info['name']}\n{'='*50}")

        prompt = f"""{info['prompt']}.
Keep the same cartoon video game style with bold outlines.
Maintain building proportions but show Mars material evolution.
Isolated on red Martian terrain, vibrant colors."""

        start = time.time()
        result_url = flux.kontext_edit(current_image, prompt, "png")
        elapsed = time.time() - start

        timestamp = int(time.time())
        blob_name = f"infrastructure_items/{info['key']}_{timestamp}.png"
        gcs_url = upload_blob_from_url(result_url, blob_name, 'image/png')

        logger.info(f"✅ Tier {tier}: {elapsed:.1f}s → {gcs_url}")
        results.append({'tier': tier, 'key': info['key'], 'name': info['name'], 'url': gcs_url})
        current_image = gcs_url
        time.sleep(2)

    # Print all URLs
    logger.info("\n\nALL INFRASTRUCTURE URLS:")
    logger.info(f"Tier 3 (Refinery): {TIER_3_IMAGE}")
    for r in results:
        logger.info(f"Tier {r['tier']} ({r['name']}): {r['url']}")

    # Print config update snippet
    logger.info("\n\nCONFIG UPDATE SNIPPET:")
    for r in results:
        logger.info(f"'{r['key']}': 'image_url': '{r['url']}',")

if __name__ == "__main__":
    run_test()
