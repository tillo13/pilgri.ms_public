#!/usr/bin/env python3
"""
Discovery Items Image Generation Script
Generates images for items that don't have them yet

Usage:
    python tools/populate_discovery_images.py
"""

import sys
import os
import logging
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utilities.flux_utils import FluxGenerator
from utilities.google_cloud_storage_utils import upload_blob_from_url
from utilities.postgres.core import get_db_connection

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# DATABASE OPERATIONS
# ============================================================================

def get_items_without_images():
    """Get all items that need images"""
    conn = None
    cur = None
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT id, item_name, description_for_flux
            FROM pilgrim.discovery_items
            WHERE image_url IS NULL
            ORDER BY id
        """)
        
        items = []
        for row in cur.fetchall():
            items.append({
                'id': row[0],
                'name': row[1],
                'prompt': row[2]
            })
        
        return items
        
    except Exception as e:
        logger.error(f"Database error: {e}")
        raise
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

def update_item_image(item_id, image_url, blob_name):
    """Update item with image URL and blob name"""
    conn = None
    cur = None
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            UPDATE pilgrim.discovery_items
            SET image_url = %s,
                gcs_blob_name = %s,
                updated_at = NOW()
            WHERE id = %s
        """, (image_url, blob_name, item_id))
        
        conn.commit()
        logger.info(f"✅ Updated item {item_id} with image")
        
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Failed to update item {item_id}: {e}")
        raise
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

# ============================================================================
# IMAGE GENERATION
# ============================================================================

def generate_and_save_image(item, flux):
    """Generate image for item and save to GCS"""
    
    logger.info(f"Generating image for: {item['name']}")
    logger.info(f"Base prompt: {item['prompt'][:100]}...")
    
    # Add game style wrapper to match character creation style
    styled_prompt = (
        f"{item['prompt']}, "
        "cartoon video game item style with bold outlines, stylized proportions, "
        "vibrant color palette with reds and oranges reflecting Mars atmosphere, "
        "isolated on Mars terrain background"
    )
    
    logger.info(f"Styled prompt: {styled_prompt[:150]}...")
    
    # Generate image with Flux using text-to-image
    from config import FLUX_MODEL
    replicate_url = flux.client.run(
        FLUX_MODEL,
        input={'prompt': styled_prompt}
    )
    
    if isinstance(replicate_url, list):
        replicate_url = replicate_url[0]
    else:
        replicate_url = str(replicate_url)
    
    logger.info(f"Replicate returned: {replicate_url}")
    
    # Upload to GCS
    timestamp = int(time.time())
    blob_name = f"discovery_items/{item['id']}_{timestamp}.png"
    
    gcs_url = upload_blob_from_url(replicate_url, blob_name, 'image/png')
    
    if not gcs_url:
        raise Exception("Failed to upload to GCS")
    
    return gcs_url, blob_name

# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    logger.info("=" * 80)
    logger.info("DISCOVERY ITEMS IMAGE GENERATION")
    logger.info("=" * 80)
    
    # Initialize Flux (it handles secret retrieval internally)
    flux = FluxGenerator()
    logger.info("✅ FluxGenerator initialized")
    
    # Get items without images
    items = get_items_without_images()
    logger.info(f"Found {len(items)} items without images")
    
    if not items:
        logger.info("No items to process")
        return
    
    # Process each item
    success_count = 0
    fail_count = 0
    
    import time as time_module
    start_time = time_module.time()
    generation_times = []
    
    for i, item in enumerate(items, 1):
        try:
            item_start_time = time_module.time()
            
            logger.info(f"\nProcessing {i}/{len(items)}: {item['name']}")
            
            gcs_url, blob_name = generate_and_save_image(item, flux)
            update_item_image(item['id'], gcs_url, blob_name)
            
            item_time = time_module.time() - item_start_time
            generation_times.append(item_time)
            
            success_count += 1
            
            # Calculate ETA
            items_remaining = len(items) - i
            if generation_times:
                avg_time = sum(generation_times) / len(generation_times)
                eta_seconds = avg_time * items_remaining
                eta_minutes = eta_seconds / 60
                
                logger.info(f"✅ Success: {item['name']} - took {item_time:.1f}s")
                logger.info(f"Progress: {i}/{len(items)} | Avg: {avg_time:.1f}s/item | ETA: {eta_minutes:.1f} min ({items_remaining} items left)")
            else:
                logger.info(f"✅ Success: {item['name']}")
            
            # Rate limiting
            if i < len(items):
                time.sleep(2)
                
        except Exception as e:
            fail_count += 1
            logger.error(f"❌ Failed: {item['name']} - {e}")
            time.sleep(3)
            continue
    
    # Summary
    total_time = time_module.time() - start_time
    logger.info("\n" + "=" * 80)
    logger.info("GENERATION COMPLETE")
    logger.info("=" * 80)
    logger.info(f"Success: {success_count}/{len(items)}")
    logger.info(f"Failed: {fail_count}/{len(items)}")
    logger.info(f"Total time: {total_time/60:.1f} minutes")
    if generation_times:
        logger.info(f"Average time per item: {sum(generation_times)/len(generation_times):.1f}s")

if __name__ == "__main__":
    main()