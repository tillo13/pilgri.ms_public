"""DB queries for ARIA snapshot context — read-only user/colony data."""

import json
import logging

from utilities.postgres.core import db_cursor

logger = logging.getLogger(__name__)


def get_user_by_email(email):
    """Partial-match user lookup by email."""
    with db_cursor() as cur:
        cur.execute("SELECT * FROM pilgrim.users WHERE email ILIKE %s", (f"%{email}%",))
        return cur.fetchone()


def get_user_captain(user_id):
    """User's primary captain image + stats."""
    with db_cursor() as cur:
        cur.execute("""
            SELECT gcs_url, commander_name,
                   commander_leadership, commander_strategy, commander_exploration,
                   commander_logistics, commander_charisma
            FROM pilgrim.replicate_assets
            WHERE user_id = %s
              AND asset_type IN ('character_image', 'edited_image')
              AND is_primary_character = true
              AND is_deleted = false
            LIMIT 1
        """, (user_id,))
        return cur.fetchone()


def get_recent_discoveries(user_id, limit=5):
    """Recent discoveries with expedition + item details."""
    with db_cursor() as cur:
        cur.execute("""
            SELECT di.item_name as name, di.rarity, di.item_type, di.description,
                   di.image_url as gcs_url,
                   e.destination_name, e.distance_km, ed.enhanced_value
            FROM pilgrim.expedition_discoveries ed
            JOIN pilgrim.expeditions e ON ed.expedition_id = e.id
            JOIN pilgrim.discovery_items di ON ed.discovery_item_id = di.id
            WHERE e.user_id = %s
            ORDER BY ed.created_at DESC
            LIMIT %s
        """, (user_id, limit))
        return cur.fetchall()


def get_recent_expeditions(user_id, limit=3):
    """Recent completed expeditions."""
    with db_cursor() as cur:
        cur.execute("""
            SELECT destination_name, destination_type, distance_km, completed_at,
                   (SELECT COUNT(*) FROM pilgrim.expedition_discoveries WHERE expedition_id = e.id) as discovery_count
            FROM pilgrim.expeditions e
            WHERE user_id = %s AND status = 'complete'
            ORDER BY completed_at DESC
            LIMIT %s
        """, (user_id, limit))
        return cur.fetchall()


def get_user_rover_image(user_id):
    """Currently unused — rover images aren't stored per-user yet. Returns None."""
    return None


def get_user_infrastructure(user_id):
    """Active colony infrastructure."""
    with db_cursor() as cur:
        cur.execute("""
            SELECT structure_type, generation_rate, total_generated, build_completed_at
            FROM pilgrim.colony_infrastructure
            WHERE user_id = %s AND status = 'active'
        """, (user_id,))
        return cur.fetchall()


def get_active_expeditions(user_id):
    """Currently in-progress expeditions."""
    with db_cursor() as cur:
        cur.execute("""
            SELECT destination_name, destination_type, distance_km, departed_at
            FROM pilgrim.expeditions
            WHERE user_id = %s AND status = 'in_progress'
            ORDER BY departed_at DESC
        """, (user_id,))
        return cur.fetchall()


def get_recent_purchases(user_id, limit=5):
    """Recent depot purchases with parsed item_details JSON."""
    with db_cursor() as cur:
        cur.execute("""
            SELECT purchase_type, item_details, created_at
            FROM pilgrim.depot_transactions
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT %s
        """, (user_id, limit))
        results = []
        for row in cur.fetchall():
            item_details = row.get('item_details') or {}
            if isinstance(item_details, str):
                try:
                    item_details = json.loads(item_details)
                except Exception:
                    item_details = {}
            results.append({
                'type': row.get('purchase_type'),
                'name': item_details.get('name') or item_details.get('item_key') or row.get('purchase_type'),
                'details': item_details,
            })
        return results


def get_user_upgrades(user_id):
    """Upgrade levels keyed as 'category_item'."""
    with db_cursor() as cur:
        cur.execute("""
            SELECT category, item_key, level
            FROM pilgrim.player_upgrades
            WHERE user_id = %s
        """, (user_id,))
        return {f"{row['category']}_{row['item_key']}": row['level'] for row in cur.fetchall()}


def get_expedition_stats(user_id):
    """Total expedition + discovery counts."""
    with db_cursor() as cur:
        cur.execute("""
            SELECT
                (SELECT COUNT(*) FROM pilgrim.expeditions WHERE user_id = %s) as total_expeditions,
                (SELECT COUNT(*) FROM pilgrim.expedition_discoveries ed
                 JOIN pilgrim.expeditions e ON ed.expedition_id = e.id
                 WHERE e.user_id = %s) as total_discoveries
        """, (user_id, user_id))
        return cur.fetchone()


def get_user_balance(user_id):
    """Estimated shard balance for prompt flavor (0 on failure — non-critical)."""
    try:
        from utilities.depot_utils import get_live_balance_and_wallet_info, eth_to_display
        total_balance, _, _ = get_live_balance_and_wallet_info(user_id)
        return eth_to_display(total_balance) if total_balance else 0
    except Exception:
        return 0


def get_recent_events(user_id, limit=5):
    """Notable events in the last 24h for prompt context."""
    events = []
    with db_cursor() as cur:
        cur.execute("""
            SELECT destination_name, completed_at
            FROM pilgrim.expeditions
            WHERE user_id = %s AND status = 'complete'
              AND completed_at > NOW() - INTERVAL '24 hours'
            ORDER BY completed_at DESC
            LIMIT %s
        """, (user_id, limit))
        for row in cur.fetchall():
            events.append(f"Expedition to {row['destination_name']} completed")

        cur.execute("""
            SELECT di.item_name, di.rarity, ed.created_at
            FROM pilgrim.expedition_discoveries ed
            JOIN pilgrim.discovery_items di ON ed.discovery_item_id = di.id
            JOIN pilgrim.expeditions e ON ed.expedition_id = e.id
            WHERE e.user_id = %s
              AND ed.created_at > NOW() - INTERVAL '24 hours'
            ORDER BY ed.created_at DESC
            LIMIT %s
        """, (user_id, limit))
        for row in cur.fetchall():
            events.append(f"Discovered {row['rarity']} {row['item_name']}")

    return events[:limit]


def get_active_users_for_snapshots(active_hours=48):
    """Users with a captain image AND activity in the last `active_hours`.

    48h window ensures evening players still get next-morning snapshots
    (cron runs 6AM PST). Saves ~$0.60/user/day vs. generating for everyone.
    """
    with db_cursor() as cur:
        cur.execute("""
            SELECT DISTINCT u.id, u.email
            FROM pilgrim.users u
            JOIN pilgrim.replicate_assets ra ON u.id = ra.user_id
            WHERE ra.asset_type IN ('character_image', 'edited_image')
              AND ra.is_primary_character = true
              AND ra.is_deleted = false
              AND ra.gcs_url IS NOT NULL
              AND u.last_meaningful_activity_at > NOW() - INTERVAL '%s hours'
            ORDER BY u.id
        """, (active_hours,))
        return cur.fetchall()
