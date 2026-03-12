#!/usr/bin/env python3
"""
Shop Items Image Generation Script
Generates images for shop items using Flux with the same visual style as discovery items

Usage:
    python tools/populate_shop_images.py
"""

import sys
import os
import logging
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utilities.flux_utils import FluxGenerator
from utilities.google_cloud_storage_utils import upload_blob_from_url
from config import SHOP_CATALOG

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# SHOP ITEM FLUX PROMPTS
# Match the discovery items style: cartoon video game item with Mars atmosphere
# ============================================================================

SHOP_ITEM_PROMPTS = {
    # ROVERS
    'rover_basic': "Cartoon video game item with bold outlines and stylized proportions: small rugged scout rover with chunky wheels, compact frame, antenna on top, dusty red-orange Mars dust on wheels, isolated on red Martian terrain, vibrant colors with reds and oranges reflecting Mars atmosphere, video game asset style",

    'rover_enhanced': "Cartoon video game item with bold outlines and stylized proportions: medium-sized exploration rover with reinforced wheels, cargo rack on back, solar panels on roof, sleek futuristic design, on red Martian rocks, vibrant Mars color palette with reds and oranges, stylized video game art",

    'rover_advanced': "Cartoon video game item with bold outlines and stylized proportions: heavy-duty expedition crawler with tank treads, large cargo bay, scientific instruments mounted, pressurized cabin, imposing industrial design, on Mars terrain background, vibrant colors, video game asset style",

    'rover_elite': "Cartoon video game item with bold outlines and stylized proportions: massive transport platform vehicle with multiple cargo containers, command tower, industrial machinery, glowing lights, epic scale dwarfing rocks around it, isolated on red Martian landscape, vibrant reds and oranges, stylized video game art",

    # SCANNERS
    'scanner_basic': "Cartoon video game item with bold outlines and stylized proportions: handheld ground-penetrating radar device with small dish antenna, digital display screen, chunky sci-fi design, on red Martian terrain, vibrant colors with reds and oranges, video game asset style",

    'scanner_deep': "Cartoon video game item with bold outlines and stylized proportions: advanced subsurface scanner with larger sensor array, multiple antennas, holographic display, sleek metallic body, on red Martian rocks, vibrant Mars color palette, stylized video game art",

    'scanner_quantum': "Cartoon video game item with bold outlines and stylized proportions: futuristic quantum resonance array with glowing blue energy rings, crystalline sensors, floating holographic readouts, advanced alien-looking technology, on Mars terrain, vibrant colors, video game asset style",

    # CARGO
    'cargo_bay': "Cartoon video game item with bold outlines and stylized proportions: modular cargo container extension with reinforced panels, storage compartments, attachment clamps, industrial orange and gray colors, on red Martian terrain, vibrant Mars color palette, video game asset style",

    'cargo_refrigerated': "Cartoon video game item with bold outlines and stylized proportions: cryo storage unit with frost on exterior, cooling vents, blue glowing temperature display, specimen containers visible through window, on red Martian rocks, vibrant colors, stylized video game art",

    # POWER
    'solar_tier2': "Cartoon video game item with bold outlines and stylized proportions: high-efficiency solar panel array with sleek modern design, blue photovoltaic cells, adjustable mounting, sun reflections, on red Martian terrain, vibrant colors with reds and oranges, video game asset style",

    'solar_tier3': "Cartoon video game item with bold outlines and stylized proportions: concentrated solar array with large mirror dishes focusing light, central collector tower, industrial framework, gleaming metal, on Mars terrain background, vibrant Mars color palette, stylized video game art",

    'nuclear_rtg': "Cartoon video game item with bold outlines and stylized proportions: nuclear RTG generator with distinctive cooling fins, radioactive warning symbols, glowing orange heat exchanger, heavy industrial design, on red Martian rocks, vibrant colors, video game asset style",

    'fusion_reactor': "Cartoon video game item with bold outlines and stylized proportions: compact fusion reactor with glowing plasma core visible through window, magnetic containment rings, advanced technology, blue energy glow, on Mars terrain, vibrant reds and oranges background, stylized video game art",

    # RESEARCH
    'research_lab': "Cartoon video game item with bold outlines and stylized proportions: mobile research lab module with scientific instruments, specimen analysis equipment, computer displays, robotic arm, on red Martian terrain, vibrant Mars color palette, video game asset style",

    'research_advanced': "Cartoon video game item with bold outlines and stylized proportions: advanced research center with multiple lab modules, holographic displays, robotic assistants, cutting-edge technology, impressive scientific complex, on Mars terrain background, vibrant colors, stylized video game art",

    # LIFE SUPPORT
    'life_support_basic': "Cartoon video game item with bold outlines and stylized proportions: enhanced life support unit with oxygen recycler tanks, air filtration system, compact design with green status lights, on red Martian terrain, vibrant colors with reds and oranges, video game asset style",

    'life_support_advanced': "Cartoon video game item with bold outlines and stylized proportions: closed-loop biosphere module with plant growth chambers visible, water recycling system, self-sustaining ecosystem, green glow from plants inside, on Mars terrain, vibrant Mars color palette, stylized video game art",

    # GEAR
    'suit_exploration': "Cartoon video game item with bold outlines and stylized proportions: explorer EVA spacesuit on display stand, streamlined design, enhanced mobility joints, helmet with wide visor, Mars dust on boots, on red Martian terrain, vibrant colors, video game asset style",

    'suit_command': "Cartoon video game item with bold outlines and stylized proportions: command exosuit with leadership insignia, armored plating, tactical displays on arm, impressive military-style design, on red Martian rocks, vibrant Mars color palette, stylized video game art",

    'suit_logistics': "Cartoon video game item with bold outlines and stylized proportions: hauler power frame exoskeleton with heavy-lift arms, cargo attachment points, industrial yellow and gray colors, powerful servos visible, on Mars terrain, vibrant colors, video game asset style",

    # AUTOMATION
    'drone_scout': "Cartoon video game item with bold outlines and stylized proportions: swarm of small flying scout drones with spinning rotors, camera eyes, sleek aerodynamic bodies, formation flying, on red Martian terrain background, vibrant colors with reds and oranges, video game asset style",

    'mining_drone': "Cartoon video game item with bold outlines and stylized proportions: automated mining drone with drill arm, ore collection bin, caterpillar tracks, industrial design, extraction equipment, glowing operational lights, on Mars terrain, vibrant Mars color palette, stylized video game art",

    'maintenance_drone': "Cartoon video game item with bold outlines and stylized proportions: autonomous cleaning drone hovering with spinning brush attachments, dust collection canister, small propeller rotors, sleek compact design, sweeping Martian dust off solar panels, industrial orange and white colors, on red Martian terrain, vibrant colors with reds and oranges, video game asset style",

    # COMMANDER CUSTOMIZATION (depot services)
    'reroll_stats': "Cartoon video game item with bold outlines and stylized proportions: glowing crystalline dice made of purple and blue energy, magical runes floating around them, cosmic sparkles and stardust, mystical reroll effect, on red Martian terrain, vibrant colors with reds and oranges background, video game asset style",

    'modify_commander': "Cartoon video game item with bold outlines and stylized proportions: futuristic holographic wardrobe terminal with clothing silhouettes displayed, purple energy glow, sleek sci-fi design with touchscreen interface, fashion customization station, on red Martian terrain, vibrant Mars color palette, stylized video game art",

    'new_commander': "Cartoon video game item with bold outlines and stylized proportions: mysterious ancient Martian portal archway with swirling purple and orange energy vortex, crystalline frame with alien glyphs, silhouette of a human figure emerging from the portal, transformation chamber effect, on red Martian terrain, vibrant colors with reds and oranges, video game asset style",

    'video_briefing': "Cartoon video game item with bold outlines and stylized proportions: holographic film projector displaying a commander silhouette, movie reel with glowing purple energy, cinematic spotlight effect, mission briefing screen, on red Martian terrain, vibrant colors with reds and oranges, video game asset style",
}

# ============================================================================
# IMAGE GENERATION
# ============================================================================

def generate_shop_item_image(item_id, flux):
    """Generate image for a shop item and save to GCS"""

    if item_id not in SHOP_ITEM_PROMPTS:
        logger.warning(f"No prompt defined for item: {item_id}")
        return None, None

    # Item may be in SHOP_CATALOG or a standalone service (like reroll, modify, video)
    item = SHOP_CATALOG.get(item_id)
    item_name = item['name'] if item else item_id.replace('_', ' ').title()

    prompt = SHOP_ITEM_PROMPTS[item_id]

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
    blob_name = f"shop_items/{item_id}_{timestamp}.png"

    gcs_url = upload_blob_from_url(replicate_url, blob_name, 'image/png')

    if not gcs_url:
        raise Exception("Failed to upload to GCS")

    return gcs_url, blob_name

# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(description='Generate shop item images')
    parser.add_argument('--item', type=str, help='Generate for specific item ID only')
    parser.add_argument('--dry-run', action='store_true', help='Show prompts without generating')
    args = parser.parse_args()

    logger.info("=" * 80)
    logger.info("SHOP ITEMS IMAGE GENERATION")
    logger.info("=" * 80)

    # Determine which items to process
    if args.item:
        if args.item not in SHOP_ITEM_PROMPTS:
            logger.error(f"Unknown item ID: {args.item}")
            logger.info(f"Available items: {list(SHOP_ITEM_PROMPTS.keys())}")
            return
        items_to_process = [args.item]
    else:
        items_to_process = list(SHOP_ITEM_PROMPTS.keys())

    logger.info(f"Will process {len(items_to_process)} items")

    if args.dry_run:
        logger.info("\n=== DRY RUN - Showing prompts only ===\n")
        for item_id in items_to_process:
            item = SHOP_CATALOG.get(item_id, {})
            logger.info(f"\n{item_id}: {item.get('name', 'Unknown')}")
            logger.info(f"  {SHOP_ITEM_PROMPTS[item_id]}")
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

            gcs_url, blob_name = generate_shop_item_image(item_id, flux)

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

        # Output as JSON for easy copying
        import json
        logger.info("\n=== JSON for config.py ===")
        url_map = {k: v['url'] for k, v in results.items()}
        print(json.dumps(url_map, indent=2))

if __name__ == "__main__":
    main()
