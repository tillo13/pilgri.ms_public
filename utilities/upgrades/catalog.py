"""Upgrade catalog & cost lookups.

Pure config-side helpers for resolving item configs, per-level stats,
infrastructure level lookups (that read DB but are catalog-oriented),
next-upgrade cost, and the big enriched catalog for the Depot UI.
"""

import logging
from typing import Dict, Any, Optional
from config import (
    UPGRADE_CATALOG,
    get_upgrade_item_config as _get_upgrade_item_config,
    get_upgrade_level_stats as _get_upgrade_level_stats,
)
from config_infrastructure import INFRASTRUCTURE_CATALOG
from utilities.postgres.core import db_cursor
from utilities.postgres.shop import get_user_infrastructure

logger = logging.getLogger(__name__)


# ============================================================================
# UNIFIED CONFIG ACCESSORS (handles both upgrades and infrastructure)
# ============================================================================

def get_item_config(category: str, item_key: str) -> Optional[dict]:
    """Get config for any upgradeable item - checks both upgrade and infrastructure catalogs."""
    if category == 'infrastructure':
        return INFRASTRUCTURE_CATALOG.get(item_key)
    return _get_upgrade_item_config(category, item_key)


def get_level_stats(category: str, item_key: str, level: int) -> Optional[dict]:
    """Get stats for an item at a specific level - handles infrastructure too."""
    if category == 'infrastructure':
        item = INFRASTRUCTURE_CATALOG.get(item_key)
        if not item:
            return None
        return item.get('levels', {}).get(level)
    return _get_upgrade_level_stats(category, item_key, level)


def get_all_infrastructure_levels(user_id: int, structures=None) -> dict:
    """
    Bulk-fetch all infrastructure levels in ONE query. Returns {building_key: level}.
    Active buildings with no upgrade record default to level 1.
    Auto-completes any pending upgrades whose ready_at has passed.

    Pass pre-fetched structures to avoid redundant get_user_infrastructure() call.
    """
    from datetime import datetime, timezone
    from utilities.upgrades.state import _complete_pending_upgrade

    if structures is None:
        structures = get_user_infrastructure(user_id)
    active_types = {b['structure_type'] for b in structures if b.get('status') == 'active'}

    if not active_types:
        return {}

    # Single query for ALL infrastructure upgrade records
    levels = {}
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT item_key, level, pending_level, ready_at FROM pilgrim.player_upgrades
                WHERE user_id = %s AND category = 'infrastructure'
            """, (user_id,))
            rows = {r['item_key']: r for r in cur.fetchall()}
    except Exception as e:
        logger.error(f"Failed to bulk-fetch infrastructure levels: {e}")
        rows = {}

    now = datetime.now(timezone.utc)
    for building_key in active_types:
        row = rows.get(building_key)
        if not row:
            levels[building_key] = 1  # Exists but no upgrade record
            continue

        level = row['level']
        pending_level = row['pending_level']
        ready_at = row['ready_at']

        if pending_level and ready_at:
            ready_at_aware = ready_at.replace(tzinfo=timezone.utc) if ready_at.tzinfo is None else ready_at
            if now >= ready_at_aware:
                _complete_pending_upgrade(user_id, 'infrastructure', building_key, pending_level)
                levels[building_key] = pending_level
                continue

        levels[building_key] = level

    return levels


def get_infrastructure_level(user_id: int, building_key: str) -> int:
    """
    Get the current level of an infrastructure building.
    Returns 0 if building doesn't exist.
    Returns 1 if building exists but no upgrade record (base level).
    Returns actual level from player_upgrades if upgraded.

    NOTE: For bulk operations, use get_all_infrastructure_levels() instead
    to avoid N+1 queries.
    """
    from datetime import datetime, timezone
    from utilities.upgrades.state import _complete_pending_upgrade

    # First check if building exists in colony_infrastructure
    user_buildings = get_user_infrastructure(user_id)
    building_types = {b['structure_type'] for b in user_buildings if b.get('status') == 'active'}

    if building_key not in building_types:
        return 0  # Building doesn't exist

    # Building exists - check if there's an upgrade record
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT level, pending_level, ready_at FROM pilgrim.player_upgrades
                WHERE user_id = %s AND category = 'infrastructure' AND item_key = %s
            """, (user_id, building_key))
            row = cur.fetchone()

            if not row:
                return 1  # Building exists but no upgrade record = Level 1

            level = row['level']
            pending_level = row['pending_level']
            ready_at = row['ready_at']

            # Check if pending upgrade is complete
            if pending_level and ready_at:
                now = datetime.now(timezone.utc)
                ready_at_aware = ready_at.replace(tzinfo=timezone.utc) if ready_at.tzinfo is None else ready_at
                if now >= ready_at_aware:
                    _complete_pending_upgrade(user_id, 'infrastructure', building_key, pending_level)
                    return pending_level

            return level
    except Exception as e:
        logger.error(f"Failed to get infrastructure level: {e}")
        return 1  # Default to level 1 if error


def get_next_upgrade_cost(category: str, item_key: str, current_level: int) -> Optional[int]:
    """Get cost to upgrade from current_level to next level. Returns None if max."""
    next_stats = get_level_stats(category, item_key, current_level + 1)
    if not next_stats:
        return None  # Already at max level
    return next_stats.get('cost', 0)


def get_upgrade_catalog_for_user(user_id: int) -> Dict[str, Any]:
    """
    Get the full upgrade catalog enriched with user's current levels and affordability.
    Used by Depot to show all upgradeable items.

    Returns nested structure:
    {
        'vehicles': {
            'rover': {
                'name': 'Rover',
                'icon': '🚗',
                'current_level': 2,
                'max_level': 4,
                'current_stats': {...},
                'next_level_stats': {...},
                'upgrade_cost': 15000,
                'can_afford': True,
                'is_max_level': False,
                'is_locked': False,
            },
            ...
        },
        ...
    }
    """
    from utilities.depot_utils import get_fast_balance_and_wallet_info
    from utilities.upgrades.state import (
        get_all_user_upgrades,
        get_upgrade_build_status,
    )

    try:
        user_upgrades = get_all_user_upgrades(user_id)
        balance, _, _ = get_fast_balance_and_wallet_info(user_id)  # FAST: no blockchain

        result = {}

        for category, items in UPGRADE_CATALOG.items():
            result[category] = {}

            for item_key, item_config in items.items():
                # Get build status first (may auto-complete if ready)
                build_status = get_upgrade_build_status(user_id, category, item_key)
                is_building = build_status.get('is_building', False) if build_status else False

                current_level = user_upgrades.get(category, {}).get(item_key, 0)
                current_stats = get_level_stats(category, item_key, current_level) or {}
                next_stats = get_level_stats(category, item_key, current_level + 1)

                upgrade_cost = next_stats.get('cost') if next_stats else None
                is_locked = current_level == 0
                is_max = current_level >= item_config.get('max_level', 1)

                # Image resolution: DB generated → config → walk back to nearest level with image
                from utilities.upgrade_image_utils import get_best_available_image
                display_level = (current_level + 1) if is_locked else current_level
                display_image = get_best_available_image(category, item_key, display_level) if display_level > 0 else ''

                # Include all level data (used by rich upgrade modal)
                # Pass all stats through (excluding image_url to keep JSON lean)
                all_levels = {}
                for lv, lv_stats in item_config.get('levels', {}).items():
                    level_entry = {k: v for k, v in lv_stats.items() if k != 'image_url'}
                    level_entry.setdefault('name', f'Lv{lv}')
                    level_entry.setdefault('cost', 0)
                    level_entry.setdefault('build_time_days', 0)
                    all_levels[int(lv)] = level_entry

                # Determine action text based on state
                if is_building:
                    action_text = 'Upgrading...'
                elif is_max:
                    action_text = 'Max Level'
                elif is_locked:
                    action_text = 'Unlock'
                else:
                    action_text = 'Upgrade'

                result[category][item_key] = {
                    'name': item_config['name'],
                    'description': item_config.get('description', ''),
                    'icon': item_config.get('icon', ''),
                    'current_level': current_level,
                    'max_level': item_config.get('max_level', 1),
                    'current_stats': current_stats,
                    'current_level_name': current_stats.get('name', 'Locked') if current_stats else 'Locked',
                    'next_level_stats': next_stats,
                    'next_level_name': next_stats.get('name') if next_stats else None,
                    'upgrade_cost': upgrade_cost,
                    'can_afford': upgrade_cost is not None and balance >= upgrade_cost,
                    'is_max_level': is_max,
                    'is_locked': is_locked,
                    'is_building': is_building,
                    'build_status': build_status,
                    'action_text': action_text,
                    'image_url': display_image,
                    'all_levels': all_levels,
                }

        # ========================================================================
        # INFRASTRUCTURE - Add buildings that user already owns for upgrade
        # ========================================================================
        result['infrastructure'] = {}
        user_buildings = get_user_infrastructure(user_id)
        owned_types = {b['structure_type'] for b in user_buildings if b.get('status') == 'active'}

        for item_key, item_config in INFRASTRUCTURE_CATALOG.items():
            # Only show buildings the user has already built
            if item_key not in owned_types:
                continue

            build_status = get_upgrade_build_status(user_id, 'infrastructure', item_key)
            is_building = build_status.get('is_building', False) if build_status else False

            current_level = get_infrastructure_level(user_id, item_key)
            current_stats = get_level_stats('infrastructure', item_key, current_level) or {}
            next_stats = get_level_stats('infrastructure', item_key, current_level + 1)

            upgrade_cost = next_stats.get('cost') if next_stats else None
            max_level = item_config.get('max_level', 10)
            is_max = current_level >= max_level

            # Image resolution: DB generated → config → walk back to nearest level with image
            from utilities.upgrade_image_utils import get_best_available_image
            display_image = get_best_available_image('infrastructure', item_key, current_level)

            # All levels data for modal - pass all stats through
            all_levels = {}
            for lv, lv_stats in item_config.get('levels', {}).items():
                level_entry = {k: v for k, v in lv_stats.items() if k != 'image_url'}
                level_entry.setdefault('name', f'Lv{lv}')
                level_entry.setdefault('cost', 0)
                level_entry.setdefault('build_time_days', 0)
                all_levels[int(lv)] = level_entry

            if is_building:
                action_text = 'Upgrading...'
            elif is_max:
                action_text = 'Max Level'
            else:
                action_text = 'Upgrade'

            result['infrastructure'][item_key] = {
                'name': item_config['name'],
                'description': item_config.get('description', ''),
                'icon': item_config.get('icon', ''),
                'current_level': current_level,
                'max_level': max_level,
                'current_stats': current_stats,
                'current_level_name': current_stats.get('name', f'Lv{current_level}'),
                'next_level_stats': next_stats,
                'next_level_name': next_stats.get('name') if next_stats else None,
                'upgrade_cost': upgrade_cost,
                'can_afford': upgrade_cost is not None and balance >= upgrade_cost,
                'is_max_level': is_max,
                'is_locked': False,  # Building exists, so not locked
                'is_building': is_building,
                'build_status': build_status,
                'action_text': action_text,
                'image_url': display_image,
                'all_levels': all_levels,
            }

        return result

    except Exception as e:
        logger.error(f"Failed to get upgrade catalog: {e}")
        return {}
