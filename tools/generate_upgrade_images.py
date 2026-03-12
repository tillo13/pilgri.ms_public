#!/usr/bin/env python3
"""
Upgrade System Image Generation Script
Generates images for all upgradeable items (vehicles, storage, etc.) at each level.

Uses Flux Kontext for progressive upgrades - each level modifies the previous one
to maintain consistent style and visual continuity.

Usage:
    python tools/generate_upgrade_images.py
    python tools/generate_upgrade_images.py --category vehicles
    python tools/generate_upgrade_images.py --category vehicles --item rover
    python tools/generate_upgrade_images.py --dry-run
    python tools/generate_upgrade_images.py --progressive  # Use Kontext for Lv2+
"""

import sys
import os
import logging
import time
import argparse

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utilities.flux_utils import FluxGenerator
from utilities.google_cloud_storage_utils import upload_blob_from_url
from config import UPGRADE_CATALOG

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# EXISTING STYLE REFERENCE IMAGES
# Use these to maintain consistent art style across new items
# ============================================================================

STYLE_REFERENCE_IMAGES = {
    'vehicles': {
        # Rover already has level 1 - use it to build levels 2-4
        'rover': 'https://storage.googleapis.com/galactica-pilgrim-assets/shop_items/rover_basic_1767505567.png',
        # Drone will use rover as style reference for level 1
        'drone': 'https://storage.googleapis.com/galactica-pilgrim-assets/shop_items/rover_basic_1767505567.png',
    },
    'storage': {
        # Bunker will use ore refinery as style reference (existing infrastructure)
        'bunker': 'https://storage.googleapis.com/galactica-pilgrim-assets/shop_items/ore_processing_refinery_1767631607.png',
    },
}

# ============================================================================
# KONTEXT PROMPTS FOR CREATING NEW ITEMS FROM STYLE REFERENCE
# These create a NEW item type while maintaining the reference image's art style
# ============================================================================

STYLE_TRANSFER_PROMPTS = {
    'vehicles': {
        'drone': "Transform this into a Mars quadcopter drone. Replace the rover with a small 4-rotor drone hovering above red Martian terrain. Simple grey plastic body, single downward camera, dust swirling below. Keep the exact same cartoon art style with bold black outlines, same color palette, same stylized proportions as the original image.",
    },
    'storage': {
        'bunker': "Transform this into a Mars underground storage bunker entrance. Replace the building with a bunker hatch on red Martian surface. Simple metal hatch door, basic ventilation pipe, partially buried in Martian soil, utilitarian grey metal. Keep the exact same cartoon art style with bold black outlines, same color palette, same stylized proportions as the original image.",
    },
}

# ============================================================================
# BASE PROMPTS (Level 1 - generate from scratch) - FALLBACK ONLY
# Only used if no style reference exists
# ============================================================================

BASE_PROMPTS = {
    'vehicles': {
        'rover': "Cartoon video game Mars rover with bold outlines: compact 4-wheeled rover, simple solar panel on top, single camera mast, grey and white color scheme, on red Martian terrain with rocks, stylized proportions, video game asset style, clean design",
        'drone': "Cartoon video game Mars drone with bold outlines: small quadcopter drone, 4 rotors, single downward camera, lightweight grey plastic body, hovering over red Martian terrain, dust below, stylized proportions, video game asset style",
    },
    'storage': {
        'bunker': "Cartoon video game Mars storage bunker with bold outlines: small underground bunker hatch on surface, simple metal door, basic ventilation pipe, partially buried in red Martian soil, utilitarian grey metal, stylized proportions, video game asset style",
    },
}

# ============================================================================
# KONTEXT UPGRADE PROMPTS (applied to previous level's image)
# These describe the CHANGES from one level to the next
# CRITICAL: Preserve exact art style - bold cartoon outlines, Mars game aesthetic
# ============================================================================

KONTEXT_UPGRADES = {
    'vehicles': {
        'rover': {
            # Starting from the existing rover_basic image
            2: "Make this rover bigger and more advanced. Add 2 extra wheels (6 total now). Add a second solar panel on top. Add orange racing stripes on the sides. Keep the exact same cartoon art style with bold black outlines and stylized proportions.",
            3: "Make this rover more advanced. Add a robotic sample collection arm on the right side. Mount scientific instruments on top. Add a visible cargo bay in the back section. Add metallic silver accent panels. Keep the exact same cartoon art style with bold black outlines.",
            4: "Transform this into a massive flagship rover. Change to 8 large wheels. Add a pressurized crew cabin with windows in the center. Add multiple robotic arms. Add radar dish on top. Add glowing blue accent lights on the body. Keep the exact same cartoon art style with bold black outlines.",
        },
        'drone': {
            # Level 1 needs base generation, then progressive from there
            2: "Upgrade this drone to a hexacopter. Add 2 more rotors (6 total now arranged in hexagon). Add a second camera on the front. Add cargo hook underneath. Add small LED status lights. Make the body white with orange accents. Keep the exact same cartoon art style with bold black outlines.",
            3: "Make this drone more advanced and high-tech. Add thermal camera array. Add specimen collection claw underneath. Attach cargo pod to the bottom. Change body to metallic silver with glowing blue accents. Add visible scanning beam coming from camera. Keep the exact same cartoon art style with bold black outlines.",
        },
    },
    'storage': {
        'bunker': {
            # Level 1 needs base generation, then progressive from there
            2: "Upgrade this bunker to be larger. Make the hatch bigger and reinforced. Add cargo elevator mechanism beside the door. Add 3 ventilation units on the surface. Add a small surface building structure above. Keep the exact same cartoon art style with bold black outlines.",
            3: "Make this storage facility industrial-scale. Add large cargo doors. Add a crane system for heavy items. Add multiple access hatches. Add a warehouse structure on the surface. Add orange warning lights. Add stacked supply containers nearby. Keep the exact same cartoon art style with bold black outlines.",
            4: "Transform this into a massive underground vault. Make the entrance huge with blast doors. Show part of the cavernous interior visible with robotic sorting arms. Add conveyor belts visible inside. Add multi-level structure with glowing interior lights. Keep the exact same cartoon art style with bold black outlines.",
            5: "Transform this into a colossal mega-storage facility. Add a towering surface structure. Add multiple giant cargo bay doors. Add small logistics drones flying around the facility. Add glowing blue energy shields on storage areas. Make it the most impressive building on Mars. Keep the exact same cartoon art style with bold black outlines.",
        },
    },
}

# ============================================================================
# LEGACY: Full prompts for non-progressive generation (fallback)
# ============================================================================

FULL_PROMPTS = {
    'vehicles': {
        'rover': {
            1: "Cartoon video game Mars rover with bold outlines: basic 4-wheeled rover, small and compact design, simple solar panel on top, basic wheels with treads, single camera mast, utilitarian grey and white color scheme, on red Martian terrain with rocks, stylized proportions, video game asset style",
            2: "Cartoon video game Mars rover with bold outlines: upgraded 6-wheeled rover, larger chassis, dual solar panels angled for efficiency, reinforced wheels, antenna array, orange and white NASA-style livery, enhanced suspension, on red Martian terrain, stylized proportions, video game asset style",
            3: "Cartoon video game Mars rover with bold outlines: advanced exploration rover, 6 large wheels with deep treads, robotic sample arm extended, multiple scientific instruments mounted, large cargo bay visible, sleek aerodynamic design, orange and metallic silver, on red Martian terrain with dust clouds, stylized proportions, video game asset style",
            4: "Cartoon video game Mars rover with bold outlines: elite flagship rover, massive 8-wheeled transport platform, pressurized crew cabin with windows, huge cargo capacity, multiple robotic arms, advanced radar and sensor arrays, glowing blue accents on white and orange body, imposing size, on red Martian terrain with Olympus Mons in background, premium vehicle feel, stylized proportions, video game asset style",
        },
        'drone': {
            1: "Cartoon video game Mars drone with bold outlines: small quadcopter drone, basic design with 4 rotors, single downward camera, lightweight frame, simple grey plastic body, hovering over red Martian terrain, dust swirling below, stylized proportions, video game asset style",
            2: "Cartoon video game Mars drone with bold outlines: upgraded hexacopter drone, 6 rotors for stability, dual cameras front and bottom, cargo hook attachment underneath, sleek white and orange body, LED status lights, hovering higher over Martian crater, stylized proportions, video game asset style",
            3: "Cartoon video game Mars drone with bold outlines: advanced scout drone, streamlined hexacopter design, multiple sensor arrays, thermal camera, specimen collection claw, cargo pod attached, metallic silver body with glowing blue accents, scanning beam visible, flying high over Valles Marineris canyon system, premium high-tech feel, stylized proportions, video game asset style",
        },
    },
    'storage': {
        'bunker': {
            1: "Cartoon video game Mars storage bunker with bold outlines: small underground bunker hatch visible on surface, simple metal door, basic ventilation pipe, compact design partially buried in red Martian soil, utilitarian grey metal, stylized proportions, video game asset style",
            2: "Cartoon video game Mars storage bunker with bold outlines: medium storage facility, larger reinforced hatch, cargo elevator mechanism visible, multiple ventilation units, surface building above bunker entrance, white and grey industrial design, on red Martian terrain, stylized proportions, video game asset style",
            3: "Cartoon video game Mars storage bunker with bold outlines: large storage complex, industrial-scale cargo doors, crane system for heavy items, multiple access points, surface warehouse structure, heavy fortification, orange warning lights, on red Martian terrain with supply containers stacked nearby, stylized proportions, video game asset style",
            4: "Cartoon video game Mars storage bunker with bold outlines: massive underground vault entrance, huge blast doors open revealing cavernous interior, robotic sorting systems visible inside, conveyor belts, multi-level facility with glowing interior lights, impressive industrial scale, on red Martian terrain with cargo vehicles parked outside, stylized proportions, video game asset style",
            5: "Cartoon video game Mars storage bunker with bold outlines: colossal mega-storage facility, towering surface structure with underground extensions, multiple giant cargo bays, automated logistics drones flying around, glowing blue forcefields on storage areas, the most impressive storage facility on Mars, sleek white architecture with orange accents, on red Martian terrain with the facility dominating the landscape, premium feel, stylized proportions, video game asset style",
        },
    },
}

# Track generated URLs for progressive mode
generated_images = {}

# ============================================================================
# IMAGE GENERATION
# ============================================================================

def generate_base_image(category, item_key, flux, dry_run=False):
    """
    Generate Level 1 base image.

    Strategy:
    1. If item already has a level 1 image (rover), use it directly
    2. If a style reference + transfer prompt exists, use Kontext to create
       a new item type in the same style
    3. Fall back to standard Flux generation
    """
    item_config = UPGRADE_CATALOG.get(category, {}).get(item_key, {})
    level_name = item_config.get('levels', {}).get(1, {}).get('name', f'{item_key} Lv1')

    # Check if this item already has a level 1 image in config
    existing_image = item_config.get('levels', {}).get(1, {}).get('image_url')
    if existing_image and item_key == 'rover':
        logger.info(f"Using EXISTING level 1 image for: {level_name}")
        logger.info(f"Existing URL: {existing_image}")
        generated_images[(category, item_key, 1)] = existing_image
        return existing_image

    # Check if we have a style reference and transfer prompt
    style_ref = STYLE_REFERENCE_IMAGES.get(category, {}).get(item_key)
    transfer_prompt = STYLE_TRANSFER_PROMPTS.get(category, {}).get(item_key)

    if style_ref and transfer_prompt:
        logger.info(f"Generating STYLE TRANSFER for: {level_name}")
        logger.info(f"Reference image: {style_ref}")
        logger.info(f"Transfer prompt: {transfer_prompt[:80]}...")

        if dry_run:
            logger.info(f"DRY RUN - would generate style transfer: {category}/{item_key}")
            return "https://example.com/dry-run-style-transfer.png"

        # Use Kontext to create new item type from style reference
        replicate_url = flux.kontext_edit(style_ref, transfer_prompt, output_format="png")
        logger.info(f"Kontext style transfer returned: {replicate_url}")

        # Upload to GCS
        timestamp = int(time.time())
        gcs_blob_name = f"upgrade_items/{category}_{item_key}_lv1_{timestamp}.png"
        gcs_url = upload_blob_from_url(replicate_url, gcs_blob_name)
        logger.info(f"Uploaded to GCS: {gcs_url}")

        generated_images[(category, item_key, 1)] = gcs_url
        return gcs_url

    # Fallback: standard Flux generation
    prompt = BASE_PROMPTS.get(category, {}).get(item_key)
    if not prompt:
        prompt = FULL_PROMPTS.get(category, {}).get(item_key, {}).get(1)

    if not prompt:
        logger.warning(f"No base prompt for: {category}/{item_key}")
        return None

    logger.info(f"Generating BASE image (fallback) for: {level_name}")
    logger.info(f"Prompt: {prompt[:80]}...")

    if dry_run:
        logger.info(f"DRY RUN - would generate base: {category}/{item_key}")
        return "https://example.com/dry-run-base.png"

    # Generate with standard Flux
    from config import FLUX_MODEL
    replicate_url = flux.client.run(FLUX_MODEL, input={'prompt': prompt})

    if isinstance(replicate_url, list):
        replicate_url = replicate_url[0]
    else:
        replicate_url = str(replicate_url)

    logger.info(f"Replicate returned: {replicate_url}")

    # Upload to GCS
    timestamp = int(time.time())
    gcs_blob_name = f"upgrade_items/{category}_{item_key}_lv1_{timestamp}.png"
    gcs_url = upload_blob_from_url(replicate_url, gcs_blob_name)
    logger.info(f"Uploaded to GCS: {gcs_url}")

    # Track for progressive upgrades
    generated_images[(category, item_key, 1)] = gcs_url

    return gcs_url


def generate_progressive_upgrade(category, item_key, level, previous_url, flux, dry_run=False):
    """Generate upgraded image using Kontext on previous level's image"""
    upgrade_prompt = KONTEXT_UPGRADES.get(category, {}).get(item_key, {}).get(level)

    if not upgrade_prompt:
        logger.warning(f"No Kontext prompt for: {category}/{item_key} level {level}")
        return None

    item_config = UPGRADE_CATALOG.get(category, {}).get(item_key, {})
    level_name = item_config.get('levels', {}).get(level, {}).get('name', f'{item_key} Lv{level}')

    logger.info(f"Generating PROGRESSIVE upgrade for: {level_name}")
    logger.info(f"Source image: {previous_url}")
    logger.info(f"Upgrade prompt: {upgrade_prompt[:80]}...")

    if dry_run:
        logger.info(f"DRY RUN - would upgrade: {category}/{item_key} to level {level}")
        return f"https://example.com/dry-run-lv{level}.png"

    # Use Kontext to modify previous image
    replicate_url = flux.kontext_edit(previous_url, upgrade_prompt, output_format="png")

    logger.info(f"Kontext returned: {replicate_url}")

    # Upload to GCS
    timestamp = int(time.time())
    gcs_blob_name = f"upgrade_items/{category}_{item_key}_lv{level}_{timestamp}.png"
    gcs_url = upload_blob_from_url(replicate_url, gcs_blob_name)
    logger.info(f"Uploaded to GCS: {gcs_url}")

    # Track for next level
    generated_images[(category, item_key, level)] = gcs_url

    return gcs_url


def generate_full_prompt_image(category, item_key, level, flux, dry_run=False):
    """Generate image using full prompt (non-progressive fallback)"""
    prompt = FULL_PROMPTS.get(category, {}).get(item_key, {}).get(level)

    if not prompt:
        logger.warning(f"No full prompt for: {category}/{item_key} level {level}")
        return None

    item_config = UPGRADE_CATALOG.get(category, {}).get(item_key, {})
    level_name = item_config.get('levels', {}).get(level, {}).get('name', f'{item_key} Lv{level}')

    logger.info(f"Generating FULL image for: {level_name}")
    logger.info(f"Prompt: {prompt[:80]}...")

    if dry_run:
        logger.info(f"DRY RUN - would generate: {category}/{item_key}/level_{level}")
        return None

    from config import FLUX_MODEL
    replicate_url = flux.client.run(FLUX_MODEL, input={'prompt': prompt})

    if isinstance(replicate_url, list):
        replicate_url = replicate_url[0]
    else:
        replicate_url = str(replicate_url)

    logger.info(f"Replicate returned: {replicate_url}")

    timestamp = int(time.time())
    gcs_blob_name = f"upgrade_items/{category}_{item_key}_lv{level}_{timestamp}.png"
    gcs_url = upload_blob_from_url(replicate_url, gcs_blob_name)
    logger.info(f"Uploaded to GCS: {gcs_url}")

    return gcs_url


def generate_item_progressive(category, item_key, flux, dry_run=False):
    """Generate all levels for an item using progressive Kontext upgrades"""
    item_config = UPGRADE_CATALOG.get(category, {}).get(item_key, {})
    if not item_config:
        logger.error(f"Item not found: {category}/{item_key}")
        return

    levels = sorted(item_config.get('levels', {}).keys())
    results = {}

    for level in levels:
        if level == 1:
            # Generate base image
            gcs_url = generate_base_image(category, item_key, flux, dry_run)
        else:
            # Check for previous level's image
            prev_level = level - 1
            prev_url = generated_images.get((category, item_key, prev_level))

            if not prev_url:
                logger.warning(f"No previous level image for {category}/{item_key} level {prev_level}, using full prompt")
                gcs_url = generate_full_prompt_image(category, item_key, level, flux, dry_run)
            else:
                gcs_url = generate_progressive_upgrade(category, item_key, level, prev_url, flux, dry_run)

        if gcs_url:
            results[level] = gcs_url
            logger.info(f"✅ {category}/{item_key} level {level} -> {gcs_url}")

        time.sleep(2)  # Rate limiting between Replicate calls

    return results


def generate_item_full(category, item_key, flux, dry_run=False):
    """Generate all levels using full prompts (non-progressive)"""
    item_config = UPGRADE_CATALOG.get(category, {}).get(item_key, {})
    if not item_config:
        logger.error(f"Item not found: {category}/{item_key}")
        return

    levels = sorted(item_config.get('levels', {}).keys())
    results = {}

    for level in levels:
        gcs_url = generate_full_prompt_image(category, item_key, level, flux, dry_run)
        if gcs_url:
            results[level] = gcs_url
            logger.info(f"✅ {category}/{item_key} level {level} -> {gcs_url}")
        time.sleep(1)

    return results


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description='Generate images for upgrade items')
    parser.add_argument('--category', help='Generate for specific category (vehicles, storage)')
    parser.add_argument('--item', help='Generate for specific item within category')
    parser.add_argument('--level', type=int, help='Generate for specific level (non-progressive only)')
    parser.add_argument('--progressive', action='store_true', default=True,
                        help='Use Kontext for progressive upgrades (default: True)')
    parser.add_argument('--full', action='store_true',
                        help='Use full prompts instead of progressive Kontext')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be generated')
    args = parser.parse_args()

    flux = FluxGenerator()
    use_progressive = args.progressive and not args.full

    print(f"\n{'='*60}")
    print(f"Upgrade Image Generator")
    print(f"Mode: {'PROGRESSIVE (Kontext)' if use_progressive else 'FULL PROMPTS'}")
    print(f"{'='*60}\n")

    if args.category and args.item and args.level:
        # Single level - use full prompt
        gcs_url = generate_full_prompt_image(args.category, args.item, args.level, flux, args.dry_run)
        if gcs_url:
            print(f"\nGenerated: {gcs_url}")
            print(f"\nUpdate config.py:")
            print(f"UPGRADE_CATALOG['{args.category}']['{args.item}']['levels'][{args.level}]['image_url'] = '{gcs_url}'")

    elif args.category and args.item:
        # All levels for an item
        if use_progressive:
            results = generate_item_progressive(args.category, args.item, flux, args.dry_run)
        else:
            results = generate_item_full(args.category, args.item, flux, args.dry_run)

        if results:
            print(f"\n{'='*60}")
            print("Update config.py with these URLs:")
            print(f"{'='*60}")
            for level, url in results.items():
                print(f"UPGRADE_CATALOG['{args.category}']['{args.item}']['levels'][{level}]['image_url'] = '{url}'")

    elif args.category:
        # All items in a category
        items = UPGRADE_CATALOG.get(args.category, {})
        all_results = {}
        for item_key in items.keys():
            if use_progressive:
                results = generate_item_progressive(args.category, item_key, flux, args.dry_run)
            else:
                results = generate_item_full(args.category, item_key, flux, args.dry_run)
            if results:
                all_results[item_key] = results

        if all_results:
            print(f"\n{'='*60}")
            print("Update config.py with these URLs:")
            print(f"{'='*60}")
            for item_key, results in all_results.items():
                for level, url in results.items():
                    print(f"UPGRADE_CATALOG['{args.category}']['{item_key}']['levels'][{level}]['image_url'] = '{url}'")

    else:
        # Everything
        for category in UPGRADE_CATALOG.keys():
            items = UPGRADE_CATALOG.get(category, {})
            for item_key in items.keys():
                if use_progressive:
                    generate_item_progressive(category, item_key, flux, args.dry_run)
                else:
                    generate_item_full(category, item_key, flux, args.dry_run)

    print("\nDone! Update image_url fields in config.py UPGRADE_CATALOG with the generated URLs.")


if __name__ == '__main__':
    main()
