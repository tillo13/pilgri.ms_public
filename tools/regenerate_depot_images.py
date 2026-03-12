#!/usr/bin/env python3
"""
Regenerate Depot Images - PILGRIMS Style Guide Compliant
=========================================================

Regenerates depot images that violate the PILGRIMS style guide:
- Must be cartoon video game items with bold outlines
- Built from MARTIAN MATERIALS (rocky, clay-like, geological)
- Subtle Sepolia crystal accents (blue-purple)
- NO metal, NO glass, NO Earth technology
- Level 1 items should be SMALL - they grow as they level up

Usage:
    python tools/regenerate_depot_images.py --list          # Show items to regenerate
    python tools/regenerate_depot_images.py --item solar_array  # Regenerate one item
    python tools/regenerate_depot_images.py --all           # Regenerate all (expensive!)
    python tools/regenerate_depot_images.py --dry-run       # Show prompts without generating
"""

import sys
import os
import argparse
import time

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# =============================================================================
# PILGRIMS STYLE PROMPT TEMPLATE
# =============================================================================

BASE_PROMPT = """Cartoon video game item with bold outlines and stylized proportions: {description}, isolated on red Martian terrain, vibrant colors with reds and oranges reflecting Mars atmosphere, video game asset style"""

# =============================================================================
# ITEMS TO REGENERATE - Each with proper PILGRIMS-style description
# =============================================================================

ITEMS_TO_REGENERATE = {
    # === INFRASTRUCTURE (11 items) ===
    'solar_array': {
        'category': 'infrastructure',
        'current_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/infrastructure_items/solar_array_1767508612.png',
        'description': 'small compact solar collector made of flat Martian stone slabs arranged in a circle, embedded with tiny glowing Sepolia crystals that absorb light, rough rocky texture with rust-red color, sits low to the ground like a natural rock formation, no metal no glass, primitive alien technology feel, about the size of a campfire pit',
        'issue': 'Metal/glass Earth tech solar panels'
    },
    'water_extractor': {
        'category': 'infrastructure',
        'current_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/infrastructure_items/water_extractor_1767509198.png',
        'description': 'small stone well structure carved from reddish Martian rock, crystalline filter made of natural blue-purple Sepolia crystal formations in the center, clay pipes leading into the ground, ancient weathered appearance, compact size like a waist-high fountain, no metal pipes no glass, primitive geological water gathering device',
        'issue': 'Giant industrial complex with glass tower'
    },
    'refinery': {
        'category': 'infrastructure',
        'current_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/infrastructure_items/refinery_1767509233.png',
        'description': 'small crude smelting pit carved into Martian rock, glowing orange-red heat in the center, rough stone walls stacked irregularly, small Sepolia crystals embedded in corners providing energy, looks like a primitive forge built from Mars terrain, compact fire pit size, no smokestacks no metal, ancient alien foundry aesthetic',
        'issue': 'Massive Earth industrial factory'
    },
    'habitat_module': {
        'category': 'infrastructure',
        'current_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/infrastructure_items/habitat_module_1767509208.png',
        'description': 'small rounded shelter carved from hollow Martian boulder, rough rocky exterior with natural rust-red coloring, tiny glowing window-like Sepolia crystal inlays, sturdy stone door, looks like a cozy hobbit-hole made from Mars rock, compact single-room size, no metal dome no glass windows, cave dwelling aesthetic',
        'issue': 'Needs more Martian material feel'
    },
    'greenhouse': {
        'category': 'infrastructure',
        'current_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/infrastructure_items/greenhouse_1767509216.png',
        'description': 'small stone growing chamber with crystalline roof made of translucent Sepolia crystal formations instead of glass, rough Martian rock walls, tiny green plants visible inside, primitive planter boxes carved from stone, compact garden shed size, no glass dome no metal frame, ancient crystal terrarium feel',
        'issue': 'Glass dome needs to be crystal'
    },
    'comms_array': {
        'category': 'infrastructure',
        'current_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/infrastructure_items/comms_array_1767509225.png',
        'description': 'small standing stone monolith with natural Sepolia crystal formations growing from the top, rough carved Martian rock pillar, crystals pulse with faint blue-purple glow, ancient resonance obelisk appearance, about person-height, no satellite dish no metal antenna, mystical standing stone communication device',
        'issue': 'Giant Earth satellite dish'
    },
    'xenobiology_lab': {
        'category': 'infrastructure',
        'current_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/infrastructure_items/xenobiology_lab_1767631633.png',
        'description': 'small stone examination table with carved specimen bowls, rough Martian rock workbench, a few clay jars and stone containers for samples, tiny Sepolia crystal providing light, simple primitive research station, compact desk-sized setup, no glowing screens no high-tech equipment, archaeological dig site feel',
        'issue': 'Sprawling high-tech facility'
    },
    'regolith_forge': {
        'category': 'infrastructure',
        'current_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/infrastructure_items/regolith_forge_1770244569.png',
        'description': 'small stone kiln structure built from stacked Martian rocks, glowing Sepolia crystals providing heat in the center, rough clay-like construction, primitive blast furnace carved from terrain, compact campfire size, ancient metallurgy aesthetic, no industrial machinery no smokestacks',
        'issue': 'Earth factory duplicate'
    },
    'thermal_vent_tap': {
        'category': 'infrastructure',
        'current_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/infrastructure_items/thermal_vent_tap_1770244603.png',
        'description': 'small natural hot spring surrounded by Martian rocks, steam wisps rising from crystalline pool, Sepolia crystals growing around the edges channeling heat, rough stone basin carved into ground, compact hot tub size, ancient geothermal tap aesthetic, no pipes no metal grating',
        'issue': 'Too big for level 1'
    },
    'resonance_chamber': {
        'category': 'infrastructure',
        'current_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/infrastructure_items/resonance_chamber_1770244586.png',
        'description': 'small circular stone altar with central Sepolia crystal formation, rough carved Martian rock ring around it, faint purple energy glow, ancient meditation circle aesthetic, compact shrine size about waist height, mystical archaeological relic feel, no high-tech machinery no metal',
        'issue': 'Too big for level 1'
    },
    'monolith_antenna': {
        'category': 'infrastructure',
        'current_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/infrastructure_items/monolith_antenna_1770244620.png',
        'description': 'small carved standing stone pillar with Sepolia crystal cap, rough weathered Martian rock surface with ancient markings, subtle purple glow from crystal top, primitive signal beacon aesthetic, about person-height obelisk, ancient alien marker stone feel, no building no metal structure',
        'issue': 'Too big for level 1'
    },

    # === EQUIPMENT/SUITS (5 items) ===
    'suit_exploration': {
        'category': 'equipment',
        'config_file': 'config_upgrades.py',
        'current_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/shop_items/suit_exploration_1767506706.png',
        'description': 'compact EVA suit made from layered Martian stone plates and hardened clay segments, rough rocky texture in rust-red colors, small Sepolia crystals embedded in joints for flexibility, primitive geological armor aesthetic, helmet made from carved boulder with crystal visor, no text labels no metal no sleek design',
        'issue': 'Has "MARS" text on base'
    },
    'suit_command': {
        'category': 'equipment',
        'config_file': 'config_upgrades.py',
        'current_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/shop_items/suit_command_1767506719.png',
        'description': 'bulkier command suit assembled from thick Martian rock plates, rough stone shoulder pieces, larger Sepolia crystal nodes on chest for communication, weathered geological armor appearance, carved rock helmet with crystal viewing slit, ancient warrior aesthetic, no sleek metal no glowing screens',
        'issue': 'Too sleek/metallic'
    },
    'cargo_refrigerated': {
        'category': 'equipment',
        'config_file': 'config_upgrades.py',
        'current_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/shop_items/cargo_refrigerated_1767505644.png',
        'description': 'small insulated stone container with thick Martian rock walls, Sepolia crystals embedded inside providing cooling glow, rough carved exterior with lid, primitive ice box made from alien terrain materials, compact crate size, ancient cold storage chest aesthetic, no metal no refrigeration unit',
        'issue': 'Too industrial'
    },
    'maintenance_drone': {
        'category': 'equipment',
        'config_file': 'config_upgrades.py',
        'current_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/shop_items/maintenance_drone_1768094423.png',
        'description': 'small hovering rock golem made of stacked Martian stone pieces, Sepolia crystals providing lift glow underneath, rough asymmetrical body with stone appendages, primitive floating helper creature aesthetic, about cat-sized, ancient animated rock servant feel, no propellers no metal no sleek drone design',
        'issue': 'Too high-tech drone look'
    },
    'scanner_quantum': {
        'category': 'equipment',
        'config_file': 'config_upgrades.py',
        'current_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/shop_items/scanner_quantum_1767505622.png',
        'description': 'handheld stone dowsing rod with large Sepolia crystal formation at tip, rough carved Martian rock handle, crystal pulses with detection energy, primitive divining tool aesthetic, compact wand-sized, ancient prospecting device feel, no screens no metal no high-tech scanner',
        'issue': 'Too high-tech'
    },
}

# =============================================================================
# GENERATION FUNCTIONS
# =============================================================================

def generate_image(item_key: str, item_data: dict, dry_run: bool = False) -> dict:
    """Generate a new image for an item using Flux."""
    from utilities.flux_utils import FluxGenerator
    from utilities.google_cloud_storage_utils import upload_blob_from_url

    prompt = BASE_PROMPT.format(description=item_data['description'])

    print(f"\n{'='*60}")
    print(f"Item: {item_key}")
    print(f"Category: {item_data['category']}")
    print(f"Issue: {item_data['issue']}")
    print(f"\nPrompt:\n{prompt[:200]}...")

    if dry_run:
        print("\n[DRY RUN - Not generating]")
        return {'success': True, 'dry_run': True}

    try:
        print("\nGenerating image via Flux...")
        generator = FluxGenerator()

        # Use Flux to generate from scratch (not Kontext edit)
        # Kontext would try to preserve the old bad style
        result_url = generator.client.run(
            "black-forest-labs/flux-1.1-pro",
            input={
                "prompt": prompt,
                "aspect_ratio": "1:1",
                "output_format": "png",
                "output_quality": 90
            }
        )

        if isinstance(result_url, list):
            result_url = result_url[0]
        result_url = str(result_url)

        print(f"Generated: {result_url}")

        # Upload to GCS
        timestamp = int(time.time())
        if item_data['category'] == 'infrastructure':
            blob_name = f"infrastructure_items/{item_key}_{timestamp}.png"
        else:
            blob_name = f"shop_items/{item_key}_{timestamp}.png"

        gcs_url = upload_blob_from_url(result_url, blob_name)
        print(f"Uploaded to GCS: {gcs_url}")

        return {
            'success': True,
            'item_key': item_key,
            'replicate_url': result_url,
            'gcs_url': gcs_url,
            'blob_name': blob_name
        }

    except Exception as e:
        print(f"ERROR: {e}")
        return {'success': False, 'error': str(e)}


def list_items():
    """List all items that need regeneration."""
    print("\n" + "="*60)
    print("ITEMS TO REGENERATE (19 total)")
    print("="*60)

    by_category = {}
    for key, data in ITEMS_TO_REGENERATE.items():
        cat = data['category']
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append((key, data))

    for cat, items in sorted(by_category.items()):
        print(f"\n{cat.upper()} ({len(items)} items):")
        for key, data in items:
            print(f"  - {key}: {data['issue']}")


def main():
    parser = argparse.ArgumentParser(description='Regenerate depot images with PILGRIMS style')
    parser.add_argument('--list', action='store_true', help='List items to regenerate')
    parser.add_argument('--item', type=str, help='Regenerate a specific item')
    parser.add_argument('--all', action='store_true', help='Regenerate all items (expensive!)')
    parser.add_argument('--dry-run', action='store_true', help='Show prompts without generating')
    parser.add_argument('--category', type=str, help='Regenerate all items in a category')

    args = parser.parse_args()

    if args.list or (not args.item and not args.all and not args.category):
        list_items()
        print("\n\nUsage:")
        print("  --item solar_array    Regenerate one item")
        print("  --category infrastructure  Regenerate all in category")
        print("  --all                 Regenerate ALL items (~$3 cost)")
        print("  --dry-run             Preview prompts without generating")
        return

    items_to_process = []

    if args.item:
        if args.item not in ITEMS_TO_REGENERATE:
            print(f"Unknown item: {args.item}")
            print(f"Available: {', '.join(ITEMS_TO_REGENERATE.keys())}")
            return
        items_to_process = [(args.item, ITEMS_TO_REGENERATE[args.item])]

    elif args.category:
        items_to_process = [
            (k, v) for k, v in ITEMS_TO_REGENERATE.items()
            if v['category'] == args.category
        ]
        if not items_to_process:
            print(f"No items in category: {args.category}")
            return

    elif args.all:
        items_to_process = list(ITEMS_TO_REGENERATE.items())
        if not args.dry_run:
            print(f"\n⚠️  About to regenerate {len(items_to_process)} images")
            print(f"   Estimated cost: ~${len(items_to_process) * 0.15:.2f}")
            confirm = input("Continue? [y/N] ")
            if confirm.lower() != 'y':
                print("Cancelled.")
                return

    # Process items
    results = []
    for item_key, item_data in items_to_process:
        result = generate_image(item_key, item_data, dry_run=args.dry_run)
        results.append((item_key, result))
        if not args.dry_run and result.get('success'):
            time.sleep(2)  # Rate limit

    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)

    success = [r for r in results if r[1].get('success')]
    failed = [r for r in results if not r[1].get('success')]

    print(f"Processed: {len(results)}")
    print(f"Success: {len(success)}")
    print(f"Failed: {len(failed)}")

    if success and not args.dry_run:
        print("\n✅ Successfully generated:")
        for key, result in success:
            print(f"  {key}: {result.get('gcs_url', 'N/A')}")

        print("\n📝 Update config files with new URLs:")
        for key, result in success:
            if result.get('gcs_url'):
                item = ITEMS_TO_REGENERATE[key]
                config_file = item.get('config_file', 'config_infrastructure.py')
                print(f"  {config_file}: {key} → {result['gcs_url']}")

    if failed:
        print("\n❌ Failed:")
        for key, result in failed:
            print(f"  {key}: {result.get('error', 'Unknown error')}")


if __name__ == '__main__':
    main()
