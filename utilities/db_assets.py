"""Replicate asset and captain management database operations."""

import logging
from typing import Dict, Any, Optional, List

from utilities.postgres_utils import db_cursor, _fetchone, _fetchall, _get_one

logger = logging.getLogger(__name__)


# ============================================================================
# REPLICATE ASSETS
# ============================================================================

def create_replicate_asset(user_id: int = None, asset_type: str = 'character_image', replicate_url: str = None,
                           gcs_url: str = None, gcs_blob_name: str = None, prompt_used: str = None,
                           edit_number: int = None, is_original: bool = False, parent_asset_id: int = None,
                           replicate_model: str = None, content_type: str = 'image/png',
                           commander_name: str = None, commander_stats: dict = None) -> Optional[int]:
    """Create a replicate asset record.

    For character_image assets: automatically sets is_primary_character=true if user has no other primary.
    This ensures every user always has a captain.
    """
    try:
        with db_cursor(commit=True) as cur:
            user_id = user_id or 5
            stats = commander_stats if (asset_type == 'character_image' and is_original and commander_stats) else {}

            is_primary = False
            if asset_type in ('character_image', 'edited_image'):
                cur.execute("""
                    SELECT COUNT(*) as cnt FROM pilgrim.replicate_assets
                    WHERE user_id = %s AND asset_type IN ('character_image', 'edited_image')
                    AND is_primary_character = true AND is_deleted = false
                """, (user_id,))
                has_primary = cur.fetchone()['cnt'] > 0
                is_primary = not has_primary

            cur.execute("""
                INSERT INTO pilgrim.replicate_assets
                (user_id, asset_type, replicate_url, gcs_url, gcs_blob_name, content_type, prompt_used, edit_number,
                 is_original, parent_asset_id, replicate_model, uploaded_to_gcs_at, replicate_expires_at, commander_name,
                 commander_leadership, commander_strategy, commander_exploration, commander_logistics, commander_charisma,
                 is_primary_character)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW() + INTERVAL '24 hours', %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (user_id, asset_type, replicate_url, gcs_url, gcs_blob_name, content_type, prompt_used, edit_number,
                  is_original, parent_asset_id, replicate_model, commander_name,
                  stats.get('leadership'), stats.get('strategy'), stats.get('exploration'),
                  stats.get('logistics'), stats.get('charisma'), is_primary))
            asset_id = cur.fetchone()['id']
            primary_msg = " (set as PRIMARY)" if is_primary else ""
            logger.info(f"✅ Created asset ID {asset_id} ({asset_type}){primary_msg}")
            from utilities.db_activity import log_activity
            log_activity(user_id, 'media', asset_type or 'captain_portrait',
                         f"{'Captain Portrait' if asset_type == 'character_image' else asset_type.replace('_', ' ').title()}",
                         image_url=gcs_url or '', source_table='replicate_assets', source_id=asset_id)
            return asset_id
    except Exception as e:
        logger.error(f"❌ Failed to create asset: {e}")
        return None


def get_user_replicate_assets(user_id: int, asset_type: str = None, limit: int = 50) -> List[Dict]:
    """Get replicate assets for a user"""
    try:
        with db_cursor() as cur:
            if asset_type:
                cur.execute("""
                    SELECT id, user_id, asset_type, gcs_url, created_at, commander_name, is_primary_character
                    FROM pilgrim.replicate_assets WHERE user_id = %s AND asset_type = %s AND is_deleted = FALSE
                    ORDER BY created_at DESC LIMIT %s
                """, (user_id, asset_type, limit))
            else:
                cur.execute("""
                    SELECT id, user_id, asset_type, gcs_url, created_at, commander_name, is_primary_character
                    FROM pilgrim.replicate_assets WHERE user_id = %s AND is_deleted = FALSE
                    ORDER BY created_at DESC LIMIT %s
                """, (user_id, limit))
            return _fetchall(cur)
    except Exception as e:
        logger.error(f"❌ Failed to get assets: {e}")
        return []


def get_user_commander_images(user_id: int, limit: int = 50) -> dict:
    """Get both character_image and edited_image for a captain in ONE query.

    PERFORMANCE: Replaces the common pattern of making two separate queries.
    Returns dict with 'character_images', 'edited_images', and 'all_images' (sorted by created_at desc).
    """
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT id, user_id, asset_type, gcs_url, created_at, commander_name, is_primary_character
                FROM pilgrim.replicate_assets
                WHERE user_id = %s
                  AND asset_type IN ('character_image', 'edited_image')
                  AND is_deleted = FALSE
                ORDER BY created_at DESC LIMIT %s
            """, (user_id, limit * 2))
            all_assets = _fetchall(cur)

            character_images = [a for a in all_assets if a['asset_type'] == 'character_image'][:limit]
            edited_images = [a for a in all_assets if a['asset_type'] == 'edited_image'][:limit]
            all_images = all_assets[:limit]

            return {
                'character_images': character_images,
                'edited_images': edited_images,
                'all_images': all_images
            }
    except Exception as e:
        logger.error(f"❌ Failed to get captain images: {e}")
        return {'character_images': [], 'edited_images': [], 'all_images': []}


def get_asset_edit_chain(asset_id: int) -> List[Dict]:
    """Get full edit chain for an asset"""
    try:
        with db_cursor() as cur:
            cur.execute("""
                WITH RECURSIVE asset_chain AS (
                    SELECT * FROM pilgrim.replicate_assets WHERE id = %s
                    UNION SELECT ra.* FROM pilgrim.replicate_assets ra
                    INNER JOIN asset_chain ac ON ra.id = ac.parent_asset_id
                ) SELECT * FROM asset_chain WHERE is_original = TRUE
            """, (asset_id,))
            root = cur.fetchone()
            if not root:
                return []
            cur.execute("""
                WITH RECURSIVE asset_chain AS (
                    SELECT *, 0 as depth FROM pilgrim.replicate_assets WHERE id = %s
                    UNION SELECT ra.*, ac.depth + 1 FROM pilgrim.replicate_assets ra
                    INNER JOIN asset_chain ac ON ra.parent_asset_id = ac.id
                ) SELECT * FROM asset_chain ORDER BY depth, created_at
            """, (root['id'],))
            return _fetchall(cur)
    except Exception as e:
        logger.error(f"❌ Failed to get edit chain: {e}")
        return []


def claim_anonymous_assets(new_user_id: int, session_asset_ids: list = None) -> bool:
    """Transfer anonymous assets to newly registered user and set captain as primary"""
    try:
        with db_cursor(commit=True) as cur:
            if session_asset_ids and len(session_asset_ids) > 0:
                cur.execute("UPDATE pilgrim.replicate_assets SET user_id = %s, updated_at = NOW() WHERE id = ANY(%s) AND user_id = 5",
                            (new_user_id, session_asset_ids))
            else:
                cur.execute("UPDATE pilgrim.replicate_assets SET user_id = %s, updated_at = NOW() WHERE user_id = 5 AND created_at > NOW() - INTERVAL '10 minutes'",
                            (new_user_id,))
            claimed_count = cur.rowcount
            if claimed_count > 0:
                cur.execute("""
                    UPDATE pilgrim.replicate_assets
                    SET is_primary_character = true
                    WHERE user_id = %s
                      AND asset_type = 'character_image'
                      AND is_deleted = false
                      AND id = (
                          SELECT id FROM pilgrim.replicate_assets
                          WHERE user_id = %s AND asset_type = 'character_image' AND is_deleted = false
                          ORDER BY created_at DESC LIMIT 1
                      )
                """, (new_user_id, new_user_id))
                logger.info(f"Claimed {claimed_count} asset(s) for user {new_user_id}, set primary captain")
                return True
            return False
    except Exception as e:
        logger.error(f"❌ Failed to claim assets: {e}")
        return False


def update_asset_stats(asset_id: int, commander_stats: dict) -> bool:
    """Update captain stats on an asset"""
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE pilgrim.replicate_assets
                SET commander_leadership = %s, commander_strategy = %s, commander_exploration = %s,
                    commander_logistics = %s, commander_charisma = %s, updated_at = NOW()
                WHERE id = %s
            """, (commander_stats.get('leadership'), commander_stats.get('strategy'), commander_stats.get('exploration'),
                  commander_stats.get('logistics'), commander_stats.get('charisma'), asset_id))
            return True
    except Exception as e:
        logger.error(f"❌ Failed to update asset stats: {e}")
        return False


def delete_asset(asset_id: int, user_id: int) -> bool:
    """Soft-delete an asset"""
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("UPDATE pilgrim.replicate_assets SET is_deleted = true, deleted_at = NOW() WHERE id = %s AND user_id = %s RETURNING asset_type",
                        (asset_id, user_id))
            if cur.fetchone():
                logger.info(f"✅ Deleted asset {asset_id}")
                return True
            return False
    except Exception as e:
        logger.error(f"❌ Failed to delete asset: {e}")
        return False


# ============================================================================
# CAPTAIN MANAGEMENT
# ============================================================================

def get_primary_commander(user_id: int) -> Optional[Dict]:
    """Get user's primary (active) captain"""
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT id, user_id, asset_type, gcs_url, created_at, commander_name,
                       commander_leadership, commander_strategy, commander_exploration,
                       commander_logistics, commander_charisma, is_primary_character
                FROM pilgrim.replicate_assets
                WHERE user_id = %s AND asset_type IN ('character_image', 'edited_image')
                      AND is_primary_character = true AND is_deleted = false LIMIT 1
            """, (user_id,))
            return _fetchone(cur)
    except Exception as e:
        logger.error(f"❌ Failed to get primary captain: {e}")
        return None


def get_user_commander(user_id: int) -> Optional[Dict]:
    """Get user's captain with name field (alias for ARIA context).

    Returns dict with 'name' key for compatibility with ARIA chat context.
    """
    commander = get_primary_commander(user_id)
    if commander and commander.get('commander_name'):
        return {'name': commander['commander_name'], **commander}
    return None


def set_primary_commander(user_id: int, asset_id: int) -> bool:
    """Set a specific captain as primary"""
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                SELECT asset_type, parent_asset_id, commander_leadership, commander_strategy,
                       commander_exploration, commander_logistics, commander_charisma
                FROM pilgrim.replicate_assets WHERE id = %s AND user_id = %s AND is_deleted = false
            """, (asset_id, user_id))
            asset = cur.fetchone()
            if not asset or asset['asset_type'] not in ['character_image', 'edited_image']:
                return False
            if asset['asset_type'] == 'edited_image' and asset['commander_leadership'] is None and asset['parent_asset_id']:
                cur.execute("""
                    SELECT commander_leadership, commander_strategy, commander_exploration, commander_logistics, commander_charisma
                    FROM pilgrim.replicate_assets WHERE id = %s
                """, (asset['parent_asset_id'],))
                parent = cur.fetchone()
                if parent and parent['commander_leadership'] is not None:
                    cur.execute("""
                        UPDATE pilgrim.replicate_assets
                        SET commander_leadership = %s, commander_strategy = %s, commander_exploration = %s,
                            commander_logistics = %s, commander_charisma = %s, updated_at = NOW()
                        WHERE id = %s
                    """, (parent['commander_leadership'], parent['commander_strategy'], parent['commander_exploration'],
                          parent['commander_logistics'], parent['commander_charisma'], asset_id))
            cur.execute("UPDATE pilgrim.replicate_assets SET is_primary_character = false WHERE user_id = %s AND is_primary_character = true AND asset_type IN ('character_image', 'edited_image')", (user_id,))
            cur.execute("UPDATE pilgrim.replicate_assets SET is_primary_character = true, updated_at = NOW() WHERE id = %s AND user_id = %s", (asset_id, user_id))
            logger.info(f"✅ Set asset {asset_id} as primary for user {user_id}")
            return True
    except Exception as e:
        logger.error(f"❌ Failed to set primary captain: {e}")
        return False


def update_commander_name(user_id: int, new_name: str) -> bool:
    """Update the captain name for a user (in both users table and replicate_assets)."""
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE pilgrim.users SET captain_name = %s WHERE id = %s
            """, (new_name, user_id))
            cur.execute("""
                UPDATE pilgrim.replicate_assets
                SET commander_name = %s, updated_at = NOW()
                WHERE user_id = %s
                  AND asset_type IN ('character_image', 'edited_image')
                  AND is_deleted = false
            """, (new_name, user_id))
            updated_count = cur.rowcount
            logger.info(f"✅ Updated captain name to '{new_name}' for user {user_id} ({updated_count} assets)")
            return True
    except Exception as e:
        logger.error(f"❌ Failed to update captain name: {e}")
        return False


def get_commander_stats(user_id: int) -> Optional[Dict]:
    """Get captain stats from most recent character_image WITH stats"""
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT commander_leadership, commander_strategy, commander_exploration, commander_logistics, commander_charisma
                FROM pilgrim.replicate_assets
                WHERE user_id = %s AND asset_type = 'character_image' AND is_deleted = FALSE
                ORDER BY (commander_leadership IS NOT NULL) DESC, created_at DESC LIMIT 1
            """, (user_id,))
            result = cur.fetchone()
            if result and result['commander_leadership'] is not None:
                return {'leadership': result['commander_leadership'], 'strategy': result['commander_strategy'],
                        'exploration': result['commander_exploration'], 'logistics': result['commander_logistics'],
                        'charisma': result['commander_charisma']}
            return None
    except Exception as e:
        logger.error(f"❌ Failed to get captain stats: {e}")
        return None
