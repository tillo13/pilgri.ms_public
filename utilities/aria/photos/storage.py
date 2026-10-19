"""Persistence for generated ARIA snapshots."""

import json
import logging

from utilities.postgres.core import db_cursor

logger = logging.getLogger(__name__)


def save_generated_image(user_id, category, subcategory, gcs_url, gcs_blob_name=None,
                         source_image_url=None, prompt_used=None, caption=None,
                         item_key=None, level=None, metadata=None, thumbnail_url=None):
    """Insert a generated image row into pilgrim.generated_images. Returns new id."""
    if metadata is None:
        metadata = {}
    if thumbnail_url:
        metadata['thumbnail_url'] = thumbnail_url

    with db_cursor(commit=True) as cur:
        cur.execute("""
            INSERT INTO pilgrim.generated_images
            (user_id, category, subcategory, item_key, level, gcs_url, gcs_blob_name,
             source_image_url, prompt_used, caption, metadata)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            user_id, category, subcategory, item_key, level, gcs_url, gcs_blob_name,
            source_image_url, prompt_used, caption,
            json.dumps(metadata) if metadata else None,
        ))
        result = cur.fetchone()
        logger.info(f"Saved generated image to DB (id: {result['id']})")
        return result['id']


def get_user_snapshots(user_id, limit=20):
    """Most recent ARIA snapshots for a user."""
    with db_cursor() as cur:
        cur.execute("""
            SELECT id, subcategory, gcs_url, caption, metadata, created_at
            FROM pilgrim.generated_images
            WHERE user_id = %s AND category = 'aria_snapshot' AND is_active = true
            ORDER BY created_at DESC
            LIMIT %s
        """, (user_id, limit))
        return cur.fetchall()
