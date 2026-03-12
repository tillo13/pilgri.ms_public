#!/usr/bin/env python3
"""
Test Upgrade Image Generation Approaches
=========================================

Tests different approaches to generating upgrade images:
A. Kontext - Image-to-image edit (Flux Kontext Pro)
B. Nano Banana - Google's premium image generation with reference
C. Llama Vision - Vision model describes → Flux generates
D. Direct Flux - Text-to-image only (no input image)

Test Case: Rover Lv4 → Lv5 "Regolith Runner"
Goal: More Mars-like (less Earth metal, more rock/regolith)

Usage:
    python tools/test_upgrade_image_generation.py --approach all
    python tools/test_upgrade_image_generation.py --approach kontext
    python tools/test_upgrade_image_generation.py --approach nano-banana
    python tools/test_upgrade_image_generation.py --approach llama-vision
    python tools/test_upgrade_image_generation.py --approach direct
"""

import sys
import os
import time
import json
import logging
import argparse

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utilities.flux_utils import FluxGenerator
from utilities.google_cloud_storage_utils import upload_blob_from_url
from config import FLUX_MODEL

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# TEST CONFIGURATION
# ============================================================================

# Source image: Rover Level 4
SOURCE_IMAGE_URL = "https://storage.googleapis.com/galactica-pilgrim-assets/upgrades/vehicles_rover_lv4_1767750981.png"

# Target: Level 5 "Regolith Runner"
TARGET_NAME = "Regolith Runner"
TARGET_LEVEL = 5

# Kontext prompt (image-to-image edit)
KONTEXT_PROMPT = """Upgrade this rover to Level 5: replace metal panels with compressed Martian regolith slabs, add more red-brown rock textures, include subtle blue-purple Sepolia crystal nodes in crevices, make it look more weathered and geological. Keep the same cartoon video game style with bold outlines."""

# Direct Flux prompt (text-to-image)
DIRECT_FLUX_PROMPT = """Cartoon video game item with bold outlines and stylized proportions: Level 5 Mars rover called Regolith Runner, built from compressed Martian regolith and clay-fired components with basalt supports, asymmetrical design with mismatched stone wheels of different sizes carved from compressed Martian rock, weathered red-brown rocky surfaces, body made of irregularly stacked sedimentary rock slabs fitted together imperfectly, one side bulkier than the other, subtle blue-purple Sepolia crystal nodes embedded in crevices, looks cobbled together from foreign alien terrain materials not meant for machinery, isolated on red Martian terrain, vibrant colors with reds and oranges reflecting Mars atmosphere, video game asset style"""

# Results directory
RESULTS_DIR = "/private/tmp/claude-501/-Users-at-Desktop-code-other-galactica/f61ff3d7-924e-489e-841e-40fb48c06e18/scratchpad"

# ============================================================================
# APPROACH A: KONTEXT (Image-to-Image)
# ============================================================================

def test_kontext(flux):
    """Test Flux Kontext Pro for image-to-image editing"""
    logger.info("\n" + "=" * 60)
    logger.info("APPROACH A: KONTEXT (Image-to-Image Edit)")
    logger.info("=" * 60)

    start_time = time.time()

    try:
        result_url = flux.kontext_edit(
            image_url=SOURCE_IMAGE_URL,
            edit_prompt=KONTEXT_PROMPT,
            output_format="png"
        )

        elapsed = time.time() - start_time

        # Save to GCS for permanent storage
        timestamp = int(time.time())
        blob_name = f"test_generation/kontext_rover_lv5_{timestamp}.png"
        gcs_url = upload_blob_from_url(result_url, blob_name, 'image/png')

        logger.info(f"✅ Kontext Success!")
        logger.info(f"   Time: {elapsed:.1f}s")
        logger.info(f"   Replicate URL: {result_url}")
        logger.info(f"   GCS URL: {gcs_url}")

        return {
            'approach': 'kontext',
            'success': True,
            'time_seconds': round(elapsed, 1),
            'replicate_url': result_url,
            'gcs_url': gcs_url,
            'estimated_cost': 0.05
        }

    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"❌ Kontext Failed: {e}")
        return {
            'approach': 'kontext',
            'success': False,
            'time_seconds': round(elapsed, 1),
            'error': str(e)
        }

# ============================================================================
# APPROACH B: NANO BANANA PRO (Google's Premium Model)
# ============================================================================

# Nano Banana prompt for upgrade
NANO_BANANA_PROMPT = """Level 5 Mars rover called Regolith Runner in cartoon video game style with bold outlines:
Built from compressed Martian regolith and clay-fired components with basalt supports.
Asymmetrical design with mismatched stone wheels of different sizes.
Weathered red-brown rocky surfaces with subtle blue-purple Sepolia crystal nodes in crevices.
Body made of irregularly stacked sedimentary rock slabs fitted together imperfectly.
Looks cobbled together from alien terrain materials, isolated on red Martian terrain.
Vibrant colors with reds and oranges reflecting Mars atmosphere, video game asset style."""

def test_nano_banana(flux):
    """Test Google Nano Banana Pro for premium image generation"""
    logger.info("\n" + "=" * 60)
    logger.info("APPROACH B: NANO BANANA PRO (Google Premium)")
    logger.info("=" * 60)

    start_time = time.time()

    try:
        # Use Nano Banana with reference image
        result_url = flux.nano_banana_edit(
            prompt=NANO_BANANA_PROMPT,
            image_urls=[SOURCE_IMAGE_URL],
            resolution="2K",
            aspect_ratio="1:1",
            output_format="png"
        )

        elapsed = time.time() - start_time

        # Save to GCS
        timestamp = int(time.time())
        blob_name = f"test_generation/nanobanana_rover_lv5_{timestamp}.png"
        gcs_url = upload_blob_from_url(result_url, blob_name, 'image/png')

        logger.info(f"✅ Nano Banana Success!")
        logger.info(f"   Time: {elapsed:.1f}s")
        logger.info(f"   Replicate URL: {result_url}")
        logger.info(f"   GCS URL: {gcs_url}")

        return {
            'approach': 'nano-banana',
            'success': True,
            'time_seconds': round(elapsed, 1),
            'replicate_url': result_url,
            'gcs_url': gcs_url,
            'estimated_cost': 0.20  # Premium model $0.15-0.30
        }

    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"❌ Nano Banana Failed: {e}")
        import traceback
        traceback.print_exc()
        return {
            'approach': 'nano-banana',
            'success': False,
            'time_seconds': round(elapsed, 1),
            'error': str(e)
        }

# ============================================================================
# APPROACH C: LLAMA VISION (Vision Model → Flux)
# ============================================================================

def test_llama_vision(flux):
    """Test Llama Vision to describe image → Flux generates"""
    logger.info("\n" + "=" * 60)
    logger.info("APPROACH C: LLAMA VISION (Vision → Flux)")
    logger.info("=" * 60)

    start_time = time.time()

    try:
        # Step 1: Use Llama Vision to describe the image
        logger.info("Step 1: Llama Vision analyzing source image...")

        llama_output = flux.client.run(
            "meta/llama-3.2-90b-vision-instruct",
            input={
                "image": SOURCE_IMAGE_URL,
                "prompt": """Describe this Mars rover image in detail for an image generation prompt. Focus on:
1. Overall shape, proportions, and style (cartoon/realistic)
2. Wheel design, count, and positioning
3. Body materials and textures
4. Color palette (specific colors)
5. Distinctive features (antennas, sensors, cargo)

Be very specific and concise - this will be used to generate an upgraded version."""
            }
        )

        # Handle different output formats (streaming)
        if hasattr(llama_output, '__iter__') and not isinstance(llama_output, str):
            source_description = ''.join(llama_output)
        else:
            source_description = str(llama_output)

        logger.info(f"   Llama description: {source_description[:200]}...")

        # Step 2: Create upgrade prompt from description
        logger.info("Step 2: Creating upgrade prompt...")

        generated_prompt = f"""Cartoon video game item with bold outlines and stylized proportions: Level 5 Mars rover called Regolith Runner, evolved from the base design with these characteristics preserved: {source_description[:300]}.

UPGRADED with Martian materials: body now made of compressed Martian regolith slabs and clay-fired components with basalt supports, wheels carved from compressed Martian stone of different sizes, asymmetrical and imperfect construction, weathered red-brown rocky surfaces, subtle blue-purple Sepolia crystal nodes embedded in crevices, looks cobbled together from alien terrain materials, isolated on red Martian terrain, vibrant colors with reds and oranges reflecting Mars atmosphere, video game asset style"""

        # Step 3: Generate with Flux
        logger.info("Step 3: Generating with Flux...")

        replicate_url = flux.client.run(
            FLUX_MODEL,
            input={'prompt': generated_prompt}
        )

        if isinstance(replicate_url, list):
            replicate_url = replicate_url[0]
        else:
            replicate_url = str(replicate_url)

        elapsed = time.time() - start_time

        # Save to GCS
        timestamp = int(time.time())
        blob_name = f"test_generation/llamavision_rover_lv5_{timestamp}.png"
        gcs_url = upload_blob_from_url(replicate_url, blob_name, 'image/png')

        logger.info(f"✅ Llama Vision Success!")
        logger.info(f"   Time: {elapsed:.1f}s")
        logger.info(f"   Replicate URL: {replicate_url}")
        logger.info(f"   GCS URL: {gcs_url}")

        return {
            'approach': 'llama-vision',
            'success': True,
            'time_seconds': round(elapsed, 1),
            'source_description': source_description,
            'generated_prompt': generated_prompt[:500],
            'replicate_url': replicate_url,
            'gcs_url': gcs_url,
            'estimated_cost': 0.03  # Llama cheap + Flux
        }

    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"❌ Llama Vision Failed: {e}")
        import traceback
        traceback.print_exc()
        return {
            'approach': 'llama-vision',
            'success': False,
            'time_seconds': round(elapsed, 1),
            'error': str(e)
        }

# ============================================================================
# APPROACH D: DIRECT FLUX (Text-to-Image Only)
# ============================================================================

def test_direct_flux(flux):
    """Test Direct Flux text-to-image (no input image)"""
    logger.info("\n" + "=" * 60)
    logger.info("APPROACH D: DIRECT FLUX (Text-to-Image)")
    logger.info("=" * 60)

    start_time = time.time()

    try:
        logger.info(f"Prompt: {DIRECT_FLUX_PROMPT[:100]}...")

        replicate_url = flux.client.run(
            FLUX_MODEL,
            input={'prompt': DIRECT_FLUX_PROMPT}
        )

        if isinstance(replicate_url, list):
            replicate_url = replicate_url[0]
        else:
            replicate_url = str(replicate_url)

        elapsed = time.time() - start_time

        # Save to GCS
        timestamp = int(time.time())
        blob_name = f"test_generation/direct_rover_lv5_{timestamp}.png"
        gcs_url = upload_blob_from_url(replicate_url, blob_name, 'image/png')

        logger.info(f"✅ Direct Flux Success!")
        logger.info(f"   Time: {elapsed:.1f}s")
        logger.info(f"   Replicate URL: {replicate_url}")
        logger.info(f"   GCS URL: {gcs_url}")

        return {
            'approach': 'direct',
            'success': True,
            'time_seconds': round(elapsed, 1),
            'prompt': DIRECT_FLUX_PROMPT,
            'replicate_url': replicate_url,
            'gcs_url': gcs_url,
            'estimated_cost': 0.05
        }

    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"❌ Direct Flux Failed: {e}")
        return {
            'approach': 'direct',
            'success': False,
            'time_seconds': round(elapsed, 1),
            'error': str(e)
        }

# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description='Test upgrade image generation approaches')
    parser.add_argument('--approach', type=str, default='all',
                       choices=['all', 'kontext', 'nano-banana', 'llama-vision', 'direct'],
                       help='Which approach to test')
    args = parser.parse_args()

    logger.info("=" * 80)
    logger.info("UPGRADE IMAGE GENERATION TEST")
    logger.info("=" * 80)
    logger.info(f"Source: Rover Lv4 → Target: Lv5 Regolith Runner")
    logger.info(f"Source URL: {SOURCE_IMAGE_URL}")
    logger.info(f"Approach: {args.approach}")

    # Initialize Flux
    flux = FluxGenerator()
    logger.info("✅ FluxGenerator initialized")

    results = []

    # Run selected tests
    if args.approach in ['all', 'kontext']:
        results.append(test_kontext(flux))
        time.sleep(2)  # Rate limiting

    if args.approach in ['all', 'nano-banana']:
        results.append(test_nano_banana(flux))
        time.sleep(2)

    if args.approach in ['all', 'llama-vision']:
        results.append(test_llama_vision(flux))
        time.sleep(2)

    if args.approach in ['all', 'direct']:
        results.append(test_direct_flux(flux))

    # Summary
    logger.info("\n" + "=" * 80)
    logger.info("TEST RESULTS SUMMARY")
    logger.info("=" * 80)

    for r in results:
        status = "✅" if r.get('success') else "❌"
        logger.info(f"\n{status} {r['approach'].upper()}")
        logger.info(f"   Time: {r.get('time_seconds', 'N/A')}s")
        logger.info(f"   Est. Cost: ${r.get('estimated_cost', 'N/A')}")
        if r.get('gcs_url'):
            logger.info(f"   GCS URL: {r['gcs_url']}")
        if r.get('error'):
            logger.info(f"   Error: {r['error']}")

    # Save results to scratchpad
    os.makedirs(RESULTS_DIR, exist_ok=True)
    results_file = os.path.join(RESULTS_DIR, 'image_gen_test_results.json')
    with open(results_file, 'w') as f:
        json.dump({
            'source_image': SOURCE_IMAGE_URL,
            'target': f"Lv{TARGET_LEVEL} {TARGET_NAME}",
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'results': results
        }, f, indent=2)

    logger.info(f"\n📄 Results saved to: {results_file}")

    # Print comparison table
    logger.info("\n" + "=" * 80)
    logger.info("COMPARISON TABLE")
    logger.info("=" * 80)
    logger.info(f"{'Approach':<12} {'Success':<8} {'Time':<8} {'Cost':<8} {'GCS URL'}")
    logger.info("-" * 80)

    for r in results:
        success = "Yes" if r.get('success') else "No"
        time_s = f"{r.get('time_seconds', 'N/A')}s"
        cost = f"${r.get('estimated_cost', 'N/A')}"
        url = r.get('gcs_url', 'N/A')[:50] + "..." if r.get('gcs_url') else 'N/A'
        logger.info(f"{r['approach']:<12} {success:<8} {time_s:<8} {cost:<8} {url}")

    logger.info("\n🔍 View images in browser to compare visual quality!")
    logger.info("   Success criteria:")
    logger.info("   1. Does it look like an upgrade? More Mars-like?")
    logger.info("   2. Does it match the existing cartoon aesthetic?")
    logger.info("   3. Cost-effectiveness")
    logger.info("   4. Speed")

if __name__ == "__main__":
    main()
