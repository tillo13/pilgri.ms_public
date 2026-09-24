#!/usr/bin/env python3
"""
Mars Location Image Generator

Generates AI images for Mars locations using Flux, on-demand.
Only generates images when requested (not all 2000+ locations at once).

Usage:
  python tools/mars_location_image_generator.py "Valles Marineris"    # Generate for one location
  python tools/mars_location_image_generator.py --batch 5             # Generate for 5 random locations without images
  python tools/mars_location_image_generator.py --list-pending        # List locations needing images
"""
import sys
import os
import argparse
import logging

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utilities.postgres.core import db_cursor
from utilities.google_cloud_storage_utils import upload_blob_from_url, BUCKET_NAME
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def get_replicate_client():
    """Get Replicate client for text-to-image generation"""
    try:
        import replicate
        from utilities.google_auth_utils import get_secret
        from config import PROJECT_ID, REPLICATE_TOKEN_ID

        token = get_secret(REPLICATE_TOKEN_ID, PROJECT_ID)
        return replicate.Client(api_token=token)
    except Exception as e:
        logger.error(f"Failed to initialize Replicate client: {e}")
        return None


# Text-to-image model (not kontext which requires input image)
TEXT_TO_IMAGE_MODEL = "black-forest-labs/flux-1.1-pro"


def generate_mars_location_prompt(location: dict) -> str:
    """
    Generate a prompt for creating a Mars landscape image based on location data.
    Uses stylized cartoon art style to match game aesthetic.

    Args:
        location: Dict with name, type, diameter_km, origin, latitude, longitude
    """
    name = location.get('name', 'Unknown')
    loc_type = location.get('type', 'terrain').lower()
    diameter = location.get('diameter_km')
    latitude = float(location.get('latitude', 0))

    # Determine terrain characteristics based on type - varied descriptions for visual interest
    import random
    terrain_desc = ""
    if 'crater' in loc_type:
        if diameter and float(diameter) > 100:
            terrain_desc = random.choice([
                "massive ancient impact basin with steep eroded walls and a weathered central peak",
                "enormous crater depression with terraced cliffs descending into dusty shadows",
                "giant impact scar with jagged rim and scattered boulders across the floor"
            ])
        elif diameter and float(diameter) > 20:
            terrain_desc = random.choice([
                "weathered impact crater with gentle sloping walls and rocky debris",
                "mid-sized crater with eroded rim and dust-filled basin",
                "ancient crater bowl with scattered rust-colored rocks"
            ])
        else:
            terrain_desc = random.choice([
                "small impact depression surrounded by ejected rubble",
                "shallow crater dimple in the dusty red plains",
                "minor impact scar with low rim and sandy floor"
            ])
    elif 'chasma' in loc_type or 'valles' in loc_type:
        terrain_desc = random.choice([
            "small winding ravine with layered sediment walls",
            "narrow martian gulch cutting through rust-red rock",
            "shallow canyon with gentle rolling walls and dusty floor",
            "modest valley with eroded cliffsides and scattered boulders",
            "twisting trench carved into ancient bedrock"
        ])
    elif 'mons' in loc_type:
        terrain_desc = random.choice([
            "towering volcanic peak with gentle shield slopes",
            "massive dormant volcano with hardened lava fields",
            "enormous mountain rising from dusty plains with caldera summit"
        ])
    elif 'planitia' in loc_type or 'planum' in loc_type:
        terrain_desc = random.choice([
            "endless flat plains stretching to the horizon with scattered pebbles",
            "vast dusty lowlands with gentle rolling dunes",
            "wide open rust-red desert floor with distant low hills"
        ])
    elif 'sulci' in loc_type or 'sulcus' in loc_type:
        terrain_desc = "parallel grooved ridges etched into the surface, strange tectonic patterns"
    elif 'fossae' in loc_type or 'fossa' in loc_type:
        terrain_desc = random.choice([
            "long narrow fault trench splitting the dusty ground",
            "collapsed rift valley with steep fractured walls"
        ])
    elif 'terra' in loc_type:
        terrain_desc = random.choice([
            "rugged ancient highlands pocked with old craters",
            "weathered high terrain with rolling rust-colored hills",
            "cratered uplands with rocky outcrops and dusty valleys"
        ])
    elif 'tholus' in loc_type:
        terrain_desc = "small rounded volcanic dome rising from flat surroundings"
    else:
        terrain_desc = random.choice([
            "rolling martian hills with rust-red soil",
            "rocky desert terrain with scattered boulders",
            "dusty red landscape with gentle undulations"
        ])

    # Adjust atmosphere based on latitude
    if abs(latitude) > 60:
        atmosphere = "polar region, white CO2 frost patches, cold thin pink sky"
    elif abs(latitude) > 30:
        atmosphere = "mid-latitude, hazy dust in thin atmosphere, salmon pink sky"
    else:
        atmosphere = "equatorial zone, warm orange-red tones, butterscotch sky"

    # Build the prompt - focus on cold, desolate, barren Mars
    prompt = f"""Stylized cartoon illustration of {name} on Mars, {terrain_desc}.
{atmosphere}.
Cold desolate barren alien world, rust-red and orange soil, dusty windswept rocks.
Frozen lifeless desert planet, no life, no green, stark and beautiful.
Vibrant cartoon art style, bold colors, sci-fi game aesthetic, dramatic lighting."""

    return prompt


def generate_location_image(location_name: str, client=None) -> dict:
    """
    Generate an image for a specific Mars location using text-to-image.

    Args:
        location_name: Name of the Mars location
        client: Optional Replicate client instance

    Returns:
        Dict with success, image_url, message
    """
    # Get location data from database
    with db_cursor() as cur:
        cur.execute("""
            SELECT id, name, type, latitude, longitude, diameter_km, origin, image_url
            FROM pilgrim.mars_mappings
            WHERE LOWER(name) = LOWER(%s)
            LIMIT 1
        """, (location_name,))
        location = cur.fetchone()

    if not location:
        return {'success': False, 'error': f"Location '{location_name}' not found"}

    if location.get('image_url'):
        return {
            'success': True,
            'image_url': location['image_url'],
            'message': 'Image already exists',
            'cached': True
        }

    # Initialize Replicate client if not provided
    if not client:
        client = get_replicate_client()
        if not client:
            return {'success': False, 'error': 'Replicate client not available'}

    # Generate prompt and image
    prompt = generate_mars_location_prompt(dict(location))
    logger.info(f"Generating image for '{location['name']}' ({location['type']})")
    logger.info(f"Prompt: {prompt[:100]}...")

    try:
        # Generate image using Flux text-to-image
        output = client.run(
            TEXT_TO_IMAGE_MODEL,
            input={
                "prompt": prompt,
                "aspect_ratio": "16:9",
                "output_format": "png",
                "safety_tolerance": 2
            }
        )

        # Handle different output formats
        if isinstance(output, list):
            replicate_url = str(output[0])
        else:
            replicate_url = str(output)

        if not replicate_url:
            return {'success': False, 'error': 'Flux generation failed - no URL returned'}

        # Save to GCS
        location_id = location['id']
        timestamp = int(datetime.now().timestamp())
        blob_name = f"mars_locations/{location_id}_{timestamp}.png"

        gcs_url = upload_blob_from_url(replicate_url, blob_name, 'image/png')

        if not gcs_url:
            return {'success': False, 'error': 'Failed to save to GCS'}

        # Update database with image URL
        with db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE pilgrim.mars_mappings
                SET image_url = %s, image_generated_at = NOW()
                WHERE id = %s
            """, (gcs_url, location_id))

        logger.info(f"Successfully generated image for '{location['name']}': {gcs_url}")

        return {
            'success': True,
            'image_url': gcs_url,
            'location_id': location_id,
            'location_name': location['name'],
            'cached': False
        }

    except Exception as e:
        logger.error(f"Error generating image for '{location_name}': {e}")
        return {'success': False, 'error': str(e)}


def generate_batch_images(count: int = 5, client=None) -> list:
    """
    Generate images for multiple locations that don't have images yet.
    Prioritizes interesting location types.

    Args:
        count: Number of images to generate
        client: Optional Replicate client instance

    Returns:
        List of result dicts
    """
    # Get locations without images, prioritizing interesting types
    with db_cursor() as cur:
        cur.execute("""
            SELECT name, type, diameter_km
            FROM pilgrim.mars_mappings
            WHERE image_url IS NULL
            ORDER BY
                CASE
                    WHEN type ILIKE '%%chasma%%' THEN 1
                    WHEN type ILIKE '%%mons%%' THEN 2
                    WHEN type ILIKE '%%crater%%' AND COALESCE(diameter_km, 0) > 50 THEN 3
                    WHEN type ILIKE '%%valles%%' THEN 4
                    ELSE 5
                END,
                RANDOM()
            LIMIT %s
        """, (count,))
        locations = cur.fetchall()

    if not locations:
        logger.info("All locations already have images!")
        return []

    # Initialize Replicate client once for batch
    if not client:
        client = get_replicate_client()
        if not client:
            return [{'success': False, 'error': 'Replicate client not available'}]

    results = []
    for loc in locations:
        result = generate_location_image(loc['name'], client)
        results.append(result)

        # Small delay between generations to be nice to Replicate
        if result.get('success') and not result.get('cached'):
            import time
            time.sleep(2)

    return results


def list_pending_locations(limit: int = 20):
    """List locations that need images"""
    with db_cursor() as cur:
        cur.execute("""
            SELECT name, type, diameter_km, origin
            FROM pilgrim.mars_mappings
            WHERE image_url IS NULL
            ORDER BY
                CASE
                    WHEN type ILIKE '%chasma%' THEN 1
                    WHEN type ILIKE '%mons%' THEN 2
                    WHEN type ILIKE '%crater%' AND COALESCE(diameter_km, 0) > 50 THEN 3
                    ELSE 4
                END,
                diameter_km DESC NULLS LAST
            LIMIT %s
        """, (limit,))
        locations = cur.fetchall()

    print(f"\n{'='*60}")
    print(f"Mars Locations Needing Images (showing {len(locations)} of many)")
    print(f"{'='*60}")

    for loc in locations:
        diameter = f"{float(loc['diameter_km']):.1f} km" if loc.get('diameter_km') else "?"
        print(f"  {loc['name']:30} | {loc['type']:20} | {diameter}")

    # Count total pending
    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) as cnt FROM pilgrim.mars_mappings WHERE image_url IS NULL")
        total = cur.fetchone()['cnt']

    print(f"\nTotal locations without images: {total}")


def get_or_generate_location_image(location_name: str) -> str:
    """
    Get image URL for a location, generating if needed.
    This is the main function to call from other code.

    Args:
        location_name: Name of the Mars location

    Returns:
        Image URL or None
    """
    result = generate_location_image(location_name)
    return result.get('image_url') if result.get('success') else None


def main():
    parser = argparse.ArgumentParser(description='Generate Mars location images')
    parser.add_argument('location', nargs='?', help='Location name to generate image for')
    parser.add_argument('--batch', type=int, metavar='N', help='Generate N random images')
    parser.add_argument('--list-pending', action='store_true', help='List locations needing images')
    args = parser.parse_args()

    if args.list_pending:
        list_pending_locations()
    elif args.batch:
        results = generate_batch_images(args.batch)
        success = sum(1 for r in results if r.get('success'))
        print(f"\nGenerated {success}/{len(results)} images successfully")
        for r in results:
            if r.get('success'):
                print(f"  {r.get('location_name', 'Unknown')}: {r.get('image_url', '')[:60]}...")
            else:
                print(f"  FAILED: {r.get('error', 'Unknown error')}")
    elif args.location:
        result = generate_location_image(args.location)
        if result.get('success'):
            cached = " (cached)" if result.get('cached') else ""
            print(f"Image for '{args.location}'{cached}: {result['image_url']}")
        else:
            print(f"Error: {result.get('error')}")
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
