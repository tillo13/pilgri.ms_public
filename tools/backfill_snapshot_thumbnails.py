#!/usr/bin/env python3
"""
Backfill thumbnails for existing ARIA snapshots that don't have them.

Usage:
    python tools/backfill_snapshot_thumbnails.py
    python tools/backfill_snapshot_thumbnails.py --dry-run
    python tools/backfill_snapshot_thumbnails.py --limit 5
"""

import sys
import os
import json
import logging

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utilities.postgres_utils import db_cursor
from utilities.google_cloud_storage_utils import create_thumbnail, BUCKET_NAME, GCP_PROJECT_ID
from google.cloud import storage
import requests

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_snapshots_without_thumbnails(limit=None):
    """Get ARIA snapshots that don't have thumbnails."""
    with db_cursor() as cur:
        query = """
            SELECT id, gcs_url, metadata
            FROM pilgrim.generated_images
            WHERE category = 'aria_snapshot' AND is_active = true
            ORDER BY created_at DESC
        """
        if limit:
            query += f" LIMIT {limit}"
        cur.execute(query)

        snapshots = []
        for row in cur.fetchall():
            metadata = row.get('metadata') or {}
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except:
                    metadata = {}

            # Skip if already has thumbnail
            if metadata.get('thumbnail_url'):
                continue

            snapshots.append({
                'id': row['id'],
                'gcs_url': row['gcs_url'],
                'metadata': metadata
            })

        return snapshots


def generate_thumbnail_for_snapshot(snapshot, dry_run=False):
    """Generate and upload thumbnail for a single snapshot."""
    snapshot_id = snapshot['id']
    gcs_url = snapshot['gcs_url']
    metadata = snapshot['metadata']

    logger.info(f"Processing snapshot {snapshot_id}: {gcs_url[:60]}...")

    if dry_run:
        logger.info("  DRY RUN - would generate thumbnail")
        return None

    try:
        # Download the image
        response = requests.get(gcs_url, timeout=60)
        response.raise_for_status()
        image_data = response.content

        file_size_kb = len(image_data) / 1024
        logger.info(f"  Downloaded {file_size_kb:.1f} KB")

        # Create thumbnail
        thumbnail_data = create_thumbnail(image_data, max_width=400)

        if not thumbnail_data:
            logger.warning(f"  No thumbnail generated (image may be small already)")
            return None

        thumb_size_kb = len(thumbnail_data) / 1024
        logger.info(f"  Created thumbnail: {thumb_size_kb:.1f} KB")

        # Generate thumbnail URL from original URL
        # e.g., .../snapshot_123.png -> .../snapshot_123_thumb.jpg
        thumb_blob_name = gcs_url.replace(f'https://storage.googleapis.com/{BUCKET_NAME}/', '')
        thumb_blob_name = thumb_blob_name.replace('.png', '_thumb.jpg')

        # Upload thumbnail
        storage_client = storage.Client(project=GCP_PROJECT_ID)
        bucket = storage_client.bucket(BUCKET_NAME)
        thumb_blob = bucket.blob(thumb_blob_name)
        thumb_blob.upload_from_string(thumbnail_data, content_type='image/jpeg', timeout=60)

        thumbnail_url = f"https://storage.googleapis.com/{BUCKET_NAME}/{thumb_blob_name}"
        logger.info(f"  Uploaded: {thumbnail_url}")

        # Update metadata in database
        metadata['thumbnail_url'] = thumbnail_url
        with db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE pilgrim.generated_images
                SET metadata = %s
                WHERE id = %s
            """, (json.dumps(metadata), snapshot_id))

        logger.info(f"  ✓ Updated database")
        return thumbnail_url

    except Exception as e:
        logger.error(f"  ✗ Error: {e}")
        return None


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Backfill thumbnails for ARIA snapshots')
    parser.add_argument('--dry-run', '-d', action='store_true', help='Show what would be done')
    parser.add_argument('--limit', '-l', type=int, help='Limit number of snapshots to process')
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("ARIA SNAPSHOT THUMBNAIL BACKFILL")
    logger.info(f"Dry run: {args.dry_run}")
    logger.info("=" * 60)

    snapshots = get_snapshots_without_thumbnails(limit=args.limit)
    logger.info(f"Found {len(snapshots)} snapshots without thumbnails")

    if not snapshots:
        logger.info("Nothing to do!")
        return

    success = 0
    failed = 0

    for snap in snapshots:
        result = generate_thumbnail_for_snapshot(snap, dry_run=args.dry_run)
        if result:
            success += 1
        else:
            failed += 1

    logger.info("=" * 60)
    logger.info(f"COMPLETE: {success} succeeded, {failed} failed/skipped")
    logger.info("=" * 60)


if __name__ == '__main__':
    main()
