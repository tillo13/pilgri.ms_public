#!/usr/bin/env python3
"""
Test Kontext Full Progression: Rover Lv1 → Lv10
================================================

Tests whether subtle Kontext edits compound across 10 levels
into meaningful visual progression toward Mars materials.

Each level passes its result as input to the next level.
"""

import sys
import os
import time
import json
import logging

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utilities.replicate_utils import FluxGenerator
from utilities.google_cloud_storage_utils import upload_blob_from_url

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Level 1 starting image
LEVEL_1_IMAGE = "https://storage.googleapis.com/galactica-pilgrim-assets/shop_items/rover_basic_1767505567.png"

# Rover level names from config
LEVEL_NAMES = {
    1: 'Scout Rover',
    2: 'Explorer Rover',
    3: 'Expedition Rover',
    4: 'Terrain Crawler',
    5: 'Regolith Runner',
    6: 'Basalt Hauler',
    7: 'Stone Serpent',
    8: 'Dust Devil',
    9: 'Mars Leviathan',
    10: 'Titan Transport',
}

# Mars material progression per the brainstorm doc
MATERIAL_PROGRESSION = {
    # Lv1-2: Earth imports (dusty metal/polymer)
    2: "Add dust weathering and minor wear marks, slightly more rugged",
    # Lv3-4: Hybrid (Earth frame + regolith patches)
    3: "Add patches of Martian regolith on the body, some clay-colored repairs",
    4: "Replace some metal panels with compressed regolith slabs, add rocky textures",
    # Lv5-6: Mostly Mars (compressed regolith, basalt)
    5: "Body now mostly compressed Martian regolith and clay, wheels showing stone texture",
    6: "Basalt supports visible, body made of stacked sedimentary rock slabs, more geological",
    # Lv7-8: Full Mars (carved volcanic rock, crystal-laced)
    7: "Carved from volcanic Martian rock, asymmetrical design, subtle blue-purple crystal nodes appearing",
    8: "More blue-purple Sepolia crystals embedded in crevices, weathered ancient appearance",
    # Lv9-10: Ancient Mars (grown from terrain, Sepolia core)
    9: "Looks almost grown from the terrain, heavy Sepolia crystal integration, geological wonder",
    10: "Massive ancient Mars construction, Sepolia crystal core visible, looks alive with geological power",
}


def generate_kontext_prompt(from_level, to_level):
    """Generate the Kontext edit prompt for a level upgrade."""
    to_name = LEVEL_NAMES.get(to_level, f'Level {to_level}')
    material_change = MATERIAL_PROGRESSION.get(to_level, "Make it look more advanced")

    return f"""Upgrade this rover to Level {to_level} "{to_name}": {material_change}.
Keep the same cartoon video game style with bold outlines.
Maintain overall shape and proportions but show the material evolution.
Isolated on red Martian terrain, vibrant colors with reds and oranges."""


def run_progression_test(flux, start_level=1, end_level=10):
    """Run the full Kontext progression test."""
    results = []
    current_image_url = LEVEL_1_IMAGE

    logger.info(f"Starting progression test: Lv{start_level} → Lv{end_level}")
    logger.info(f"Starting image: {current_image_url}")

    for level in range(start_level + 1, end_level + 1):
        logger.info(f"\n{'='*60}")
        logger.info(f"GENERATING LEVEL {level}: {LEVEL_NAMES.get(level, 'Unknown')}")
        logger.info(f"{'='*60}")

        prompt = generate_kontext_prompt(level - 1, level)
        logger.info(f"Prompt: {prompt[:100]}...")

        start_time = time.time()

        try:
            result_url = flux.kontext_edit(
                image_url=current_image_url,
                edit_prompt=prompt,
                output_format="png"
            )

            elapsed = time.time() - start_time

            # Save to GCS
            timestamp = int(time.time())
            blob_name = f"test_generation/kontext_progression_rover_lv{level}_{timestamp}.png"
            gcs_url = upload_blob_from_url(result_url, blob_name, 'image/png')

            logger.info(f"✅ Level {level} Success! Time: {elapsed:.1f}s")
            logger.info(f"   GCS URL: {gcs_url}")

            results.append({
                'level': level,
                'name': LEVEL_NAMES.get(level),
                'success': True,
                'time_seconds': round(elapsed, 1),
                'input_url': current_image_url,
                'output_url': gcs_url,
                'prompt': prompt,
            })

            # Use this result as input for next level
            current_image_url = gcs_url

            # Rate limiting
            time.sleep(2)

        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"❌ Level {level} Failed: {e}")
            results.append({
                'level': level,
                'name': LEVEL_NAMES.get(level),
                'success': False,
                'time_seconds': round(elapsed, 1),
                'error': str(e),
            })
            # Stop progression on failure
            break

    return results


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Test Kontext progression Lv1→Lv10')
    parser.add_argument('--start', type=int, default=1, help='Starting level (default: 1)')
    parser.add_argument('--end', type=int, default=10, help='Ending level (default: 10)')
    args = parser.parse_args()

    logger.info("=" * 80)
    logger.info("KONTEXT PROGRESSION TEST: ROVER Lv1 → Lv10")
    logger.info("=" * 80)
    logger.info("Testing if subtle changes compound across 10 levels")
    logger.info("")

    flux = FluxGenerator()
    logger.info("✅ FluxGenerator initialized")

    results = run_progression_test(flux, args.start, args.end)

    # Summary
    logger.info("\n" + "=" * 80)
    logger.info("PROGRESSION RESULTS")
    logger.info("=" * 80)

    total_time = sum(r.get('time_seconds', 0) for r in results)
    total_cost = len([r for r in results if r.get('success')]) * 0.05

    for r in results:
        status = "✅" if r.get('success') else "❌"
        logger.info(f"{status} Level {r['level']} ({r['name']}): {r.get('time_seconds', 'N/A')}s")
        if r.get('output_url'):
            logger.info(f"   → {r['output_url']}")

    logger.info(f"\nTotal time: {total_time:.1f}s")
    logger.info(f"Est. cost: ${total_cost:.2f}")

    # Save results
    results_file = "/tmp/kontext_progression_results.json"
    with open(results_file, 'w') as f:
        json.dump({
            'test': 'kontext_progression',
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'results': results,
            'total_time': total_time,
            'total_cost': total_cost,
        }, f, indent=2)

    logger.info(f"\n📄 Results saved to: {results_file}")
    logger.info("\n🔍 Download images to /tmp/ and view to see the progression!")

    # Print download commands
    logger.info("\nTo download all images:")
    for r in results:
        if r.get('output_url'):
            logger.info(f'curl -s -o /tmp/rover_lv{r["level"]}.png "{r["output_url"]}"')


if __name__ == "__main__":
    main()
