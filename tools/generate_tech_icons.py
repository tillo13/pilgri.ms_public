#!/usr/bin/env python3
"""
Generate tech tree icons for all 20 research technologies + 4 branch icons.
Style: Mars-material aesthetic - items carved from red rock/clay with Sepolia crystal accents.
NO metal, NO glass, NO Earth technology. Primitive, geological, Martian.
"""
import sys
import os
import time
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utilities.flux_utils import FluxGenerator
from utilities.google_cloud_storage_utils import upload_blob_from_url
from config import FLUX_MODEL

# Mars-material aesthetic: red rock, clay, carved stone, Sepolia crystal accents.
# Items look like they were MADE ON MARS from local materials. Primitive but functional.
TECH_PROMPTS = {
    # Exploration branch - carved rock survey tools
    'wind_analysis': "Cartoon video game item with bold outlines and stylized proportions: simple wind vane carved from rough red Martian rock with a tiny glowing purple crystal tip, primitive stone weathervane on a short rock pedestal, geological and handmade looking, isolated on red Martian terrain with rocky landscape, vibrant colors with reds and oranges reflecting Mars atmosphere, video game asset style",
    'terrain_mapping': "Cartoon video game item with bold outlines and stylized proportions: flat red Mars stone slab tablet with carved topographic contour lines etched into the surface, simple primitive map carved in rock, small purple crystal marker dot, isolated on red Martian terrain with rocky landscape, vibrant colors with reds and oranges reflecting Mars atmosphere, video game asset style",
    'storm_prediction': "Cartoon video game item with bold outlines and stylized proportions: rounded red Mars rock weather stone with carved spiral dust patterns on its surface, small purple crystal embedded in center glowing faintly, primitive carved storm indicator, isolated on red Martian terrain with rocky landscape, vibrant colors with reds and oranges reflecting Mars atmosphere, video game asset style",
    'advanced_sensors': "Cartoon video game item with bold outlines and stylized proportions: tall pointed red rock obelisk spire with a glowing purple Sepolia crystal at the tip, carved Mars stone pillar with rough texture, primitive sensor tower, isolated on red Martian terrain with rocky landscape, vibrant colors with reds and oranges reflecting Mars atmosphere, video game asset style",
    'deep_scanning': "Cartoon video game item with bold outlines and stylized proportions: Y-shaped red Mars rock dowsing rod with deep purple crystals embedded at both tips glowing brightly, primitive forked stone tool, geological and ancient looking, isolated on red Martian terrain with rocky landscape, vibrant colors with reds and oranges and purple crystal glow, video game asset style",

    # Vehicles branch - rock/clay vehicle parts
    'material_science': "Cartoon video game item with bold outlines and stylized proportions: cross-section chunk of layered Mars rock showing distinct red and orange geological strata layers, rough hewn sample of Martian geology, small crystal vein visible in one layer, isolated on red Martian terrain with rocky landscape, vibrant colors with reds and oranges reflecting Mars atmosphere, video game asset style",
    'suspension_engineering': "Cartoon video game item with bold outlines and stylized proportions: curved arch of flexible red Mars clay shaped like a spring or suspension bridge, simple bent rock arch showing natural flex, primitive shock absorber carved from stone, isolated on red Martian terrain with rocky landscape, vibrant colors with reds and oranges reflecting Mars atmosphere, video game asset style",
    'chassis_reinforcement': "Cartoon video game item with bold outlines and stylized proportions: thick squared slab of hardened dark red Mars rock armor plate, dense heavy stone shield piece with rough carved edges, primitive protective plate, isolated on red Martian terrain with rocky landscape, vibrant colors with reds and oranges reflecting Mars atmosphere, video game asset style",
    'nav_computation': "Cartoon video game item with bold outlines and stylized proportions: flat circular red Mars stone disc with carved directional compass rose arrows etched into surface, primitive navigation stone with small crystal at center, isolated on red Martian terrain with rocky landscape, vibrant colors with reds and oranges reflecting Mars atmosphere, video game asset style",
    'all_terrain_mastery': "Cartoon video game item with bold outlines and stylized proportions: carved red Mars rock wheel shape with crystal-veined treads and rough stone hub, primitive stone tire with purple crystal fragments embedded in the rim, isolated on red Martian terrain with rocky landscape, vibrant colors with reds and oranges reflecting Mars atmosphere, video game asset style",

    # Power branch - rock energy devices
    'solar_optimization': "Cartoon video game item with bold outlines and stylized proportions: flat angled red Mars rock disc shaped like a sundial tilted toward light, thin crystal veins running across its surface catching sunlight with faint glow, primitive solar collector carved from stone, isolated on red Martian terrain with rocky landscape, vibrant colors with reds and oranges reflecting Mars atmosphere, video game asset style",
    'battery_chemistry': "Cartoon video game item with bold outlines and stylized proportions: hollowed carved red Mars rock vessel pot with glowing orange-purple crystal energy visible inside, primitive stone battery container with carved lid, warm glow emanating from within, isolated on red Martian terrain with rocky landscape, vibrant colors with reds and oranges reflecting Mars atmosphere, video game asset style",
    'thermal_tap': "Cartoon video game item with bold outlines and stylized proportions: red Mars rock chimney spire with orange heat shimmer glow rising from the top, carved stone thermal vent tap, warm colors radiating upward, primitive geothermal device, isolated on red Martian terrain with rocky landscape, vibrant colors with reds and oranges reflecting Mars atmosphere, video game asset style",
    'power_grid': "Cartoon video game item with bold outlines and stylized proportions: three small connected red Mars rock pillars with glowing purple crystal veins linking them together like power lines, primitive stone power network, crystal conduits between monoliths, isolated on red Martian terrain with rocky landscape, vibrant colors with reds and oranges reflecting Mars atmosphere, video game asset style",
    'fusion_basics': "Cartoon video game item with bold outlines and stylized proportions: rounded red Mars rock sphere cracked open revealing bright glowing crystal core inside, primitive stone fusion reactor, intense purple-white crystal energy visible through cracks, isolated on red Martian terrain with rocky landscape, vibrant colors with reds oranges and bright crystal glow, video game asset style",

    # Extraction branch - rock mining/collection tools
    'shard_resonance': "Cartoon video game item with bold outlines and stylized proportions: forked red Mars rock tuning fork shape with small purple Sepolia crystals vibrating at both tips, primitive resonance tool carved from stone, faint vibration waves visible, isolated on red Martian terrain with rocky landscape, vibrant colors with reds and oranges reflecting Mars atmosphere, video game asset style",
    'specimen_preservation': "Cartoon video game item with bold outlines and stylized proportions: carved hollowed red Mars rock jar vessel with a crystal-sealed lid on top, primitive specimen container made of stone with purple crystal stopper, isolated on red Martian terrain with rocky landscape, vibrant colors with reds and oranges reflecting Mars atmosphere, video game asset style",
    'crystal_attunement': "Cartoon video game item with bold outlines and stylized proportions: cluster of purple-orange Sepolia crystals growing naturally from a red Mars rock base, crystal formation with warm glow, geological crystal deposit specimen, isolated on red Martian terrain with rocky landscape, vibrant colors with reds oranges and purple crystal glow, video game asset style",
    'xenobiology_mastery': "Cartoon video game item with bold outlines and stylized proportions: red Mars rock mortar and pestle with tiny crushed crystal specimens inside the bowl, primitive laboratory grinding tool carved from stone, small crystal fragments visible, isolated on red Martian terrain with rocky landscape, vibrant colors with reds and oranges reflecting Mars atmosphere, video game asset style",
    'ancient_protocols': "Cartoon video game item with bold outlines and stylized proportions: weathered ancient red Mars rock tablet with glowing purple crystal rune symbols carved into surface, primitive stone inscription slab with mysterious glowing markings, isolated on red Martian terrain with rocky landscape, vibrant colors with reds oranges and purple crystal rune glow, video game asset style",
}

# Branch tab icons - simple recognizable shapes at small size
BRANCH_ICON_PROMPTS = {
    'branch_exploration': "Cartoon video game item with bold outlines and stylized proportions: simple carved red Mars rock spyglass telescope shape, primitive stone viewing tool with small crystal lens, compact and iconic, isolated on red Martian terrain, vibrant colors with reds and oranges reflecting Mars atmosphere, video game asset style, centered composition",
    'branch_vehicles': "Cartoon video game item with bold outlines and stylized proportions: simple carved red Mars rock wheel with crystal-veined spokes, primitive round stone tire shape, compact and iconic, isolated on red Martian terrain, vibrant colors with reds and oranges reflecting Mars atmosphere, video game asset style, centered composition",
    'branch_power': "Cartoon video game item with bold outlines and stylized proportions: simple red Mars rock carved into lightning bolt shape with purple crystal vein running through it, primitive power symbol in stone, compact and iconic, isolated on red Martian terrain, vibrant colors with reds and oranges reflecting Mars atmosphere, video game asset style, centered composition",
    'branch_extraction': "Cartoon video game item with bold outlines and stylized proportions: simple red Mars rock pickaxe with purple crystal cutting edge tip, primitive mining tool carved from stone, compact and iconic, isolated on red Martian terrain, vibrant colors with reds and oranges reflecting Mars atmosphere, video game asset style, centered composition",
}

RESULTS_FILE = '/tmp/tech_icons_results.json'


def generate_icon(flux, key, prompt):
    """Generate a single icon and upload to GCS."""
    print(f"\n{'='*50}")
    print(f"Generating: {key}")

    try:
        replicate_url = flux.client.run(
            FLUX_MODEL,
            input={'prompt': prompt}
        )

        if isinstance(replicate_url, list):
            replicate_url = replicate_url[0]
        else:
            replicate_url = str(replicate_url)

        timestamp = int(time.time())
        blob_name = f"tech_icons/{key}_{timestamp}.png"
        gcs_url = upload_blob_from_url(replicate_url, blob_name, 'image/png')
        print(f"  Done: {gcs_url}")
        return gcs_url
    except Exception as e:
        print(f"  ERROR: {e}")
        return None


def main():
    print("Generating Tech Tree Icons (v3 - Mars-material aesthetic)")
    print("=" * 50)

    flux = FluxGenerator()
    results = {}

    # Generate all tech icons
    for key, prompt in TECH_PROMPTS.items():
        url = generate_icon(flux, key, prompt)
        if url:
            results[key] = url
        time.sleep(2)

    # Generate branch icons
    for key, prompt in BRANCH_ICON_PROMPTS.items():
        url = generate_icon(flux, key, prompt)
        if url:
            results[key] = url
        time.sleep(2)

    # Save results
    with open(RESULTS_FILE, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"\n{'='*50}")
    print(f"COMPLETE: {len(results)}/24 icons generated")
    print(f"Results saved to: {RESULTS_FILE}")


if __name__ == "__main__":
    main()
