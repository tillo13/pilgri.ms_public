#!/usr/bin/env python3
"""
Infrastructure Items Image Generation Script
Generates images for infrastructure items using Flux with the same visual style as shop items

Usage:
    python tools/populate_infrastructure_images.py
    python tools/populate_infrastructure_images.py --item solar_array
    python tools/populate_infrastructure_images.py --dry-run
"""

import sys
import os
import logging
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utilities.flux_utils import FluxGenerator
from utilities.google_cloud_storage_utils import upload_blob_from_url
from config import INFRASTRUCTURE_CATALOG

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# INFRASTRUCTURE ITEM FLUX PROMPTS
# Match the shop items style: cartoon video game item with Mars atmosphere
# ============================================================================

INFRASTRUCTURE_PROMPTS = {
    # TIER 1
    'solar_array': "Cartoon video game item with bold outlines and stylized proportions: large solar photovoltaic array with multiple dark blue panels arranged in a grid, metal support structure and mounting poles, sun glinting off panels, Mars dust on base, isolated on red Martian terrain with rocky landscape, vibrant colors with reds and oranges reflecting Mars atmosphere, video game asset style",

    # TIER 2
    'battery_storage': "Cartoon video game item with bold outlines and stylized proportions: industrial lithium-ion battery bank with multiple large battery cells stacked together, power cables and connectors, LED status indicators glowing green, heavy metal housing, warning labels visible, on red Martian terrain background, vibrant Mars color palette with reds and oranges, stylized video game art",

    'water_extractor': "Cartoon video game item with bold outlines and stylized proportions: massive ice mining drill rig with rotating drill bit, water collection tanks, pipes and hoses, steam venting from extraction process, industrial machinery on rocky red Martian terrain, vibrant colors with blues for water and reds for Mars, video game asset style",

    'habitat_module': "Cartoon video game item with bold outlines and stylized proportions: pressurized dome habitat module with rounded white walls, circular windows glowing with interior light, airlock entrance, life support vents on roof, connected walkways, on red Martian terrain with rocks, vibrant warm interior glow contrasting with red Mars landscape, video game asset style",

    # TIER 3
    'xenobiology_lab': "Cartoon video game item with bold outlines and stylized proportions: futuristic xenobiology research laboratory with glass specimen containers showing alien microorganisms, DNA helix hologram display, microscopes and scientific equipment, glowing biosafety containment units with green specimens inside, scientist workstations, on red Martian terrain, vibrant bioluminescent greens and scientific blues contrasting with red landscape, video game asset style",

    'greenhouse': "Cartoon video game item with bold outlines and stylized proportions: geodesic dome greenhouse with transparent panels showing lush green plants inside, hydroponic growing beds visible, LED grow lights, condensation on glass, on red Martian terrain, vibrant green plants contrasting with red Mars landscape, video game asset style",

    'comms_array': "Cartoon video game item with bold outlines and stylized proportions: massive deep space communications array with large satellite dish pointing at sky, antenna towers, blinking lights, radar equipment, control station at base, on red Martian terrain with stars visible in sky, vibrant colors, video game asset style",

    'refinery': "Cartoon video game item with bold outlines and stylized proportions: industrial ore processing refinery with conveyor belts, crushing machinery, smelting furnaces with orange glow, smokestacks, storage silos, heavy industrial complex on red Martian terrain, vibrant industrial oranges and metallic grays, video game asset style",

    # TIER 4
    'nuclear_plant': "Cartoon video game item with bold outlines and stylized proportions: nuclear fission reactor with distinctive cooling towers emitting steam, containment building with hazard symbols, control center, heavy security fencing, glowing blue reactor core visible through windows, on red Martian terrain, vibrant nuclear blue glow contrasting with red landscape, video game asset style",

    'launch_pad': "Cartoon video game item with bold outlines and stylized proportions: rocket launch complex with tall gantry tower, launch pad with flame deflector, fuel tanks and pipes, mission control building, a sleek rocket on the pad ready for launch, on red Martian terrain with dramatic sky, vibrant colors with metallic silvers and rocket flames, video game asset style",

    'research_station': "Cartoon video game item with bold outlines and stylized proportions: advanced research station with multiple connected lab modules, large observatory dome, robotic arms, holographic displays visible through windows, satellite dishes, scientific equipment everywhere, on red Martian terrain, vibrant purple and blue science glow, video game asset style",

    # TIER 5
    'fusion_reactor': "Cartoon video game item with bold outlines and stylized proportions: massive fusion power plant with glowing plasma containment ring, magnetic coils, enormous cooling systems, energy conduits pulsing with power, futuristic architecture, blindingly bright fusion core, on red Martian terrain, vibrant electric blue and white energy glow dominating the scene, video game asset style",

    'space_elevator': "Cartoon video game item with bold outlines and stylized proportions: towering space elevator base station with cable stretching into the stars, cargo pods ascending, massive support structure, futuristic terminal building, landing pads for orbital shuttles, most impressive structure on Mars, on red Martian terrain reaching into starry black sky, vibrant colors with the cable glowing, video game asset style",
}

# ============================================================================
# IMAGE GENERATION
# ============================================================================

def generate_infrastructure_image(item_id, flux):
    """Generate image for an infrastructure item and save to GCS"""

    if item_id not in INFRASTRUCTURE_PROMPTS:
        logger.warning(f"No prompt defined for item: {item_id}")
        return None, None

    item = INFRASTRUCTURE_CATALOG.get(item_id)
    item_name = item['name'] if item else item_id.replace('_', ' ').title()

    prompt = INFRASTRUCTURE_PROMPTS[item_id]

    logger.info(f"Generating image for: {item_name}")
    logger.info(f"Prompt: {prompt[:100]}...")

    # Generate image with Flux using text-to-image
    from config import FLUX_MODEL
    replicate_url = flux.client.run(
        FLUX_MODEL,
        input={'prompt': prompt}
    )

    if isinstance(replicate_url, list):
        replicate_url = replicate_url[0]
    else:
        replicate_url = str(replicate_url)

    logger.info(f"Replicate returned: {replicate_url}")

    # Upload to GCS
    timestamp = int(time.time())
    blob_name = f"infrastructure_items/{item_id}_{timestamp}.png"

    gcs_url = upload_blob_from_url(replicate_url, blob_name, 'image/png')

    if not gcs_url:
        raise Exception("Failed to upload to GCS")

    return gcs_url, blob_name

# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(description='Generate infrastructure item images')
    parser.add_argument('--item', type=str, help='Generate for specific item ID only')
    parser.add_argument('--dry-run', action='store_true', help='Show prompts without generating')
    args = parser.parse_args()

    logger.info("=" * 80)
    logger.info("INFRASTRUCTURE ITEMS IMAGE GENERATION")
    logger.info("=" * 80)

    # Determine which items to process
    if args.item:
        if args.item not in INFRASTRUCTURE_PROMPTS:
            logger.error(f"Unknown item ID: {args.item}")
            logger.info(f"Available items: {list(INFRASTRUCTURE_PROMPTS.keys())}")
            return
        items_to_process = [args.item]
    else:
        items_to_process = list(INFRASTRUCTURE_PROMPTS.keys())

    logger.info(f"Will process {len(items_to_process)} items")

    if args.dry_run:
        logger.info("\n=== DRY RUN - Showing prompts only ===\n")
        for item_id in items_to_process:
            item = INFRASTRUCTURE_CATALOG.get(item_id, {})
            logger.info(f"\n{item_id}: {item.get('name', 'Unknown')}")
            logger.info(f"  {INFRASTRUCTURE_PROMPTS[item_id]}")
        return

    # Initialize Flux
    flux = FluxGenerator()
    logger.info("✅ FluxGenerator initialized")

    # Process items
    success_count = 0
    fail_count = 0
    results = {}

    start_time = time.time()

    for i, item_id in enumerate(items_to_process, 1):
        try:
            logger.info(f"\nProcessing {i}/{len(items_to_process)}: {item_id}")

            gcs_url, blob_name = generate_infrastructure_image(item_id, flux)

            if gcs_url:
                results[item_id] = {'url': gcs_url, 'blob': blob_name}
                success_count += 1
                logger.info(f"✅ Success: {item_id}")
                logger.info(f"   URL: {gcs_url}")
            else:
                fail_count += 1
                logger.warning(f"⚠️ Skipped: {item_id}")

            # Rate limiting
            if i < len(items_to_process):
                time.sleep(2)

        except Exception as e:
            fail_count += 1
            logger.error(f"❌ Failed: {item_id} - {e}")
            time.sleep(3)
            continue

    # Summary
    total_time = time.time() - start_time
    logger.info("\n" + "=" * 80)
    logger.info("GENERATION COMPLETE")
    logger.info("=" * 80)
    logger.info(f"Success: {success_count}/{len(items_to_process)}")
    logger.info(f"Failed: {fail_count}/{len(items_to_process)}")
    logger.info(f"Total time: {total_time/60:.1f} minutes")

    if results:
        logger.info("\n=== Generated URLs ===")
        for item_id, data in results.items():
            logger.info(f"{item_id}: {data['url']}")

        # Output as JSON for easy copying to config.py
        import json
        logger.info("\n=== JSON for config.py ===")
        url_map = {k: v['url'] for k, v in results.items()}
        print(json.dumps(url_map, indent=2))

        # Also output in config.py format for easy copy-paste
        logger.info("\n=== Copy-paste for INFRASTRUCTURE_CATALOG ===")
        for item_id, data in results.items():
            print(f"        'image_url': '{data['url']}',")

if __name__ == "__main__":
    main()
