"""
Generic Upgrade System for Pilgrims
====================================
Handles leveling up any upgradeable entity: vehicles, storage, future items.
Similar to Clash of Clans - one system for all upgrade paths.

Usage:
    from utilities.upgrades_utils import (
        get_user_upgrade_level,
        get_upgrade_stats,
        perform_upgrade,
        get_upgrade_catalog_for_user
    )

    # Check user's rover level
    level = get_user_upgrade_level(user_id, 'vehicles', 'rover')

    # Get stats for that level
    stats = get_upgrade_stats('vehicles', 'rover', level)

    # Upgrade to next level
    result = perform_upgrade(user_id, 'vehicles', 'rover')
"""

import json
import logging
from typing import Dict, Any, Optional, List
from config import UPGRADE_CATALOG, get_upgrade_item_config as _get_upgrade_item_config, get_upgrade_level_stats as _get_upgrade_level_stats
from config_infrastructure import INFRASTRUCTURE_CATALOG
from utilities.postgres_utils import db_cursor, get_user_infrastructure

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


# ============================================================================
# DATABASE TABLE MANAGEMENT
# ============================================================================

_upgrades_table_ensured = False

def ensure_upgrades_table() -> bool:
    """Ensure the player_upgrades table exists with build timer columns.
    Only runs once per process to avoid deadlocks under concurrent load."""
    global _upgrades_table_ensured
    if _upgrades_table_ensured:
        return True
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS pilgrim.player_upgrades (
                    user_id INTEGER REFERENCES pilgrim.users(id),
                    category VARCHAR(50) NOT NULL,
                    item_key VARCHAR(50) NOT NULL,
                    level INTEGER DEFAULT 1,
                    upgraded_at TIMESTAMP DEFAULT NOW(),
                    tx_hash VARCHAR(255),
                    tx_pending BOOLEAN DEFAULT FALSE,
                    PRIMARY KEY (user_id, category, item_key)
                )
            """)
            # Create index for faster lookups
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_player_upgrades_user
                ON pilgrim.player_upgrades(user_id)
            """)
            # Add ready_at column for build timers (if not exists)
            cur.execute("""
                ALTER TABLE pilgrim.player_upgrades
                ADD COLUMN IF NOT EXISTS ready_at TIMESTAMP
            """)
            # Add pending_level column (level being upgraded to)
            cur.execute("""
                ALTER TABLE pilgrim.player_upgrades
                ADD COLUMN IF NOT EXISTS pending_level INTEGER
            """)
            _upgrades_table_ensured = True
            return True
    except Exception as e:
        logger.error(f"Failed to ensure upgrades table: {e}")
        return False


# ============================================================================
# READ OPERATIONS
# ============================================================================

def get_user_upgrade_level(user_id: int, category: str, item_key: str) -> int:
    """
    Get user's current USABLE level for an upgradeable item.
    If an upgrade is in progress (pending_level set, ready_at in future), returns the old level.
    If build is complete (ready_at passed), auto-completes and returns new level.
    Returns the default_level from config if not in DB (e.g., rover starts at 1).
    Returns 0 for items that must be unlocked (e.g., drone).

    For infrastructure: returns level based on building existence + upgrade record.
    """
    from datetime import datetime, timezone

    # Special handling for infrastructure - uses building existence as base
    if category == 'infrastructure':
        return get_infrastructure_level(user_id, item_key)

    try:
        ensure_upgrades_table()

        # Check DB for level and build status
        with db_cursor() as cur:
            cur.execute("""
                SELECT level, pending_level, ready_at FROM pilgrim.player_upgrades
                WHERE user_id = %s AND category = %s AND item_key = %s
            """, (user_id, category, item_key))
            row = cur.fetchone()
            if row:
                level = row['level']
                pending_level = row['pending_level']
                ready_at = row['ready_at']

                # If there's a pending upgrade, check if it's ready
                if pending_level and ready_at:
                    now = datetime.now(timezone.utc)
                    ready_at_aware = ready_at.replace(tzinfo=timezone.utc) if ready_at.tzinfo is None else ready_at
                    if now >= ready_at_aware:
                        # Build complete - auto-apply the upgrade
                        _complete_pending_upgrade(user_id, category, item_key, pending_level)
                        return pending_level
                    else:
                        # Still building - return the OLD level (usable level)
                        return level

                return level

        # No DB record - return default level from config
        item_config = get_item_config(category, item_key)
        if item_config:
            return item_config.get('default_level', 0)
        return 0

    except Exception as e:
        logger.error(f"Failed to get upgrade level: {e}")
        return 0


def _complete_pending_upgrade(user_id: int, category: str, item_key: str, new_level: int):
    """Internal: Auto-complete a pending upgrade when build timer expires."""
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE pilgrim.player_upgrades
                SET level = %s, pending_level = NULL, ready_at = NULL
                WHERE user_id = %s AND category = %s AND item_key = %s
            """, (new_level, user_id, category, item_key))
        logger.info(f"✅ Auto-completed upgrade: {user_id} {category}/{item_key} -> Lv{new_level}")
    except Exception as e:
        logger.error(f"Failed to complete pending upgrade: {e}")


def get_all_upgrade_build_statuses(user_id: int, category: str) -> Dict[str, Optional[Dict]]:
    """Bulk-fetch build statuses for ALL items in a category in ONE query.
    Returns {item_key: status_dict_or_None}."""
    from datetime import datetime, timezone
    try:
        ensure_upgrades_table()
        with db_cursor() as cur:
            cur.execute("""
                SELECT item_key, level, pending_level, ready_at FROM pilgrim.player_upgrades
                WHERE user_id = %s AND category = %s
            """, (user_id, category))
            rows = cur.fetchall()
    except Exception as e:
        logger.error(f"Failed to bulk-fetch build statuses: {e}")
        return {}

    now = datetime.now(timezone.utc)
    results = {}
    for row in rows:
        key = row['item_key']
        pending_level = row['pending_level']
        ready_at = row['ready_at']

        if not pending_level or not ready_at:
            results[key] = {'is_building': False, 'current_level': row['level']}
            continue

        ready_at_aware = ready_at.replace(tzinfo=timezone.utc) if ready_at.tzinfo is None else ready_at
        seconds_remaining = max(0, (ready_at_aware - now).total_seconds())

        if seconds_remaining <= 0:
            _complete_pending_upgrade(user_id, category, key, pending_level)
            results[key] = {'is_building': False, 'current_level': pending_level}
        else:
            results[key] = {
                'is_building': True,
                'pending_level': pending_level,
                'ready_at': ready_at_aware.isoformat(),
                'seconds_remaining': int(seconds_remaining),
                'current_level': row['level']
            }
    return results


def get_upgrade_build_status(user_id: int, category: str, item_key: str) -> Optional[Dict]:
    """
    Get the build status for an upgrade.
    Returns None if no upgrade in progress, or:
    {
        'is_building': True/False,
        'pending_level': 3,
        'ready_at': datetime,
        'seconds_remaining': 12345,
        'current_level': 2
    }
    """
    from datetime import datetime, timezone
    try:
        ensure_upgrades_table()
        with db_cursor() as cur:
            cur.execute("""
                SELECT level, pending_level, ready_at FROM pilgrim.player_upgrades
                WHERE user_id = %s AND category = %s AND item_key = %s
            """, (user_id, category, item_key))
            row = cur.fetchone()
            if not row:
                return None

            pending_level = row['pending_level']
            ready_at = row['ready_at']

            if not pending_level or not ready_at:
                return {'is_building': False, 'current_level': row['level']}

            now = datetime.now(timezone.utc)
            ready_at_aware = ready_at.replace(tzinfo=timezone.utc) if ready_at.tzinfo is None else ready_at
            seconds_remaining = max(0, (ready_at_aware - now).total_seconds())

            if seconds_remaining <= 0:
                # Build is done but not yet auto-completed
                _complete_pending_upgrade(user_id, category, item_key, pending_level)
                return {'is_building': False, 'current_level': pending_level}

            return {
                'is_building': True,
                'pending_level': pending_level,
                'ready_at': ready_at_aware.isoformat(),
                'seconds_remaining': int(seconds_remaining),
                'current_level': row['level']
            }
    except Exception as e:
        logger.error(f"Failed to get upgrade build status: {e}")
        return None


BASE_CONCURRENT_UPGRADE_CAP = 3  # Default max concurrent upgrades


def count_concurrent_upgrades(user_id: int) -> int:
    """Count how many builds are in progress (equipment upgrades + infrastructure construction)."""
    from datetime import datetime, timezone
    ensure_upgrades_table()
    with db_cursor() as cur:
        # Equipment upgrades (player_upgrades with pending_level)
        cur.execute("""
            SELECT COUNT(*) as cnt FROM pilgrim.player_upgrades
            WHERE user_id = %s AND pending_level IS NOT NULL AND ready_at > NOW()
        """, (user_id,))
        row = cur.fetchone()
        equipment_count = row['cnt'] if row else 0
        # Infrastructure builds (colony_infrastructure with status='building')
        cur.execute("""
            SELECT COUNT(*) as cnt FROM pilgrim.colony_infrastructure
            WHERE user_id = %s AND status = 'building' AND ready_at > NOW()
        """, (user_id,))
        row = cur.fetchone()
        infra_count = row['cnt'] if row else 0
        return equipment_count + infra_count


def get_user_upgrade_cap(user_id: int) -> int:
    """
    Get user's max concurrent upgrade cap.
    Base cap is 3. Habitat Module Level 5+ adds +1 slot.
    """
    cap = BASE_CONCURRENT_UPGRADE_CAP
    # Check for habitat module level 5+
    habitat_level = get_infrastructure_level(user_id, 'habitat_module')
    if habitat_level >= 5:
        cap += 1  # +1 slot at level 5
    return cap


def get_active_builds(user_id: int) -> list:
    """
    Get list of active builds with name, category, target level, and seconds remaining.
    Returns list sorted by ready_at (soonest first).
    """
    from datetime import datetime, timezone
    ensure_upgrades_table()
    builds = []
    with db_cursor() as cur:
        cur.execute("""
            SELECT category, item_key, level, pending_level, ready_at
            FROM pilgrim.player_upgrades
            WHERE user_id = %s AND pending_level IS NOT NULL AND ready_at > NOW()
            ORDER BY ready_at ASC
        """, (user_id,))
        now = datetime.now(timezone.utc)
        for row in cur.fetchall():
            # Get item name from catalog
            item_config = UPGRADE_CATALOG.get(row['category'], {}).get(row['item_key'], {})
            level_config = item_config.get('levels', {}).get(row['pending_level'], {})
            item_name = level_config.get('name', item_config.get('name', row['item_key'].replace('_', ' ').title()))

            ready_at = row['ready_at']
            if ready_at.tzinfo is None:
                ready_at = ready_at.replace(tzinfo=timezone.utc)
            seconds_remaining = max(0, int((ready_at - now).total_seconds()))

            builds.append({
                'name': item_name,
                'category': row['category'],
                'item_key': row['item_key'],
                'current_level': row['level'],
                'target_level': row['pending_level'],
                'seconds_remaining': seconds_remaining,
                'ready_at': ready_at.isoformat()
            })
    return builds


def get_all_user_upgrades(user_id: int) -> Dict[str, Dict[str, int]]:
    """
    Get all upgrades for a user as nested dict: {category: {item_key: level}}
    Includes default levels for items not yet in DB.
    """
    try:
        ensure_upgrades_table()

        # Migrate old shop purchases to player_upgrades (once per session)
        from utilities.legacy_migration import ensure_legacy_migrated
        ensure_legacy_migrated(user_id)

        # Start with defaults from catalog
        result = {}
        for category, items in UPGRADE_CATALOG.items():
            result[category] = {}
            for item_key, item_config in items.items():
                result[category][item_key] = item_config.get('default_level', 0)

        # Override with actual DB values
        with db_cursor() as cur:
            cur.execute("""
                SELECT category, item_key, level FROM pilgrim.player_upgrades
                WHERE user_id = %s
            """, (user_id,))
            for row in cur.fetchall():
                cat = row['category']
                key = row['item_key']
                if cat not in result:
                    result[cat] = {}
                result[cat][key] = row['level']

        return result

    except Exception as e:
        logger.error(f"Failed to get all upgrades: {e}")
        return {}


def get_upgrade_stats(category: str, item_key: str, level: int) -> Optional[Dict]:
    """Get stats for an item at a given level - handles both upgrades and infrastructure"""
    return get_level_stats(category, item_key, level)


def get_next_upgrade_cost(category: str, item_key: str, current_level: int) -> Optional[int]:
    """Get cost to upgrade from current_level to next level. Returns None if max."""
    next_stats = get_upgrade_stats(category, item_key, current_level + 1)
    if not next_stats:
        return None  # Already at max level
    return next_stats.get('cost', 0)


# ============================================================================
# WRITE OPERATIONS
# ============================================================================

def perform_upgrade(user_id: int, category: str, item_key: str) -> Dict[str, Any]:
    """
    Upgrade an item to the next level.
    Handles both unlock (0→1) and upgrade (1→2, etc.)
    Uses build_time_days from config - upgrade isn't usable until timer completes.

    Returns:
        {
            'success': True/False,
            'error': 'message' (if failed),
            'category': 'vehicles',
            'item_key': 'rover',
            'old_level': 1,
            'new_level': 2,
            'cost': 5000,
            'stats': {...},  # New level stats
            'ready_at': '2026-02-05T12:00:00Z',  # When upgrade completes
            'build_time_days': 2
        }
    """
    from datetime import datetime, timezone, timedelta
    from utilities.depot_utils import get_fast_balance_and_wallet_info, display_to_eth

    try:
        ensure_upgrades_table()

        # DOUBLE-CLICK PROTECTION: Check if upgrade already in progress
        build_status = get_upgrade_build_status(user_id, category, item_key)
        if build_status and build_status.get('is_building'):
            return {
                'success': False,
                'error': 'Upgrade already in progress. Please wait for it to complete.',
                'is_building': True,
                'ready_at': build_status.get('ready_at'),
                'seconds_remaining': build_status.get('seconds_remaining')
            }

        # CONCURRENT UPGRADE CAP: Check if user has too many upgrades in progress
        current_building = count_concurrent_upgrades(user_id)
        max_cap = get_user_upgrade_cap(user_id)
        if current_building >= max_cap:
            return {
                'success': False,
                'error': f'Maximum concurrent upgrades reached ({current_building}/{max_cap}). Wait for one to complete or upgrade your Habitat Module.',
                'cap_reached': True,
                'current_building': current_building,
                'max_cap': max_cap
            }

        # Get current level
        current_level = get_user_upgrade_level(user_id, category, item_key)
        next_level = current_level + 1

        # Get item config (handles both upgrades and infrastructure)
        item_config = get_item_config(category, item_key)
        if not item_config:
            return {'success': False, 'error': f'Unknown item: {category}/{item_key}'}

        # Infrastructure-specific: building must exist before it can be upgraded
        if category == 'infrastructure':
            if current_level == 0:
                return {'success': False, 'error': f'You must build {item_config["name"]} first before upgrading it.'}

        # Check max level
        max_level = item_config.get('max_level', 1)
        if current_level >= max_level:
            return {'success': False, 'error': 'Already at max level'}

        # Get next level stats (includes cost)
        next_stats = get_upgrade_stats(category, item_key, next_level)
        if not next_stats:
            return {'success': False, 'error': 'No upgrade available'}

        cost_display = next_stats.get('cost', 0)
        build_time_days = next_stats.get('build_time_days', 0)

        # Check balance (FAST: uses DB cache, not blockchain)
        total_balance, wallet_info, primary_wallet = get_fast_balance_and_wallet_info(user_id)
        if total_balance < cost_display:
            return {
                'success': False,
                'error': f'Insufficient shards. Need {cost_display:.0f}, have {total_balance:.0f}',
                'cost': cost_display,
                'balance': total_balance
            }

        # Deduct cost immediately, blockchain tx fires in background
        tx_hash = None
        if cost_display > 0 and primary_wallet:
            cost_eth = display_to_eth(cost_display)

            # Immediate DB balance deduction
            from utilities.postgres_utils import update_sepolia_wallet_balance
            new_balance_eth = float(primary_wallet.get('current_balance_eth', 0)) - cost_eth
            update_sepolia_wallet_balance(primary_wallet.get('wallet_address'), new_balance_eth)

            # Background blockchain tx + transaction logging
            from utilities.depot_utils import background_blockchain_tx
            background_blockchain_tx(
                wallet_address=primary_wallet.get('wallet_address'),
                wallet_private_key=primary_wallet.get('wallet_private_key'),
                amount_eth=cost_eth,
                reason=f"Upgrade: {item_config['name']} to {next_stats.get('name', f'Lv{next_level}')}",
                user_id=user_id, purchase_type='upgrade_purchase',
                item_details={
                    'category': category, 'item_key': item_key,
                    'item_name': item_config['name'],
                    'from_level': current_level, 'to_level': next_level,
                    'level_name': next_stats.get('name', f'Level {next_level}'),
                    'cost_shards': cost_display
                }
            )

        # Calculate ready_at based on build time (apply build speed bonuses)
        ready_at = None
        if build_time_days > 0:
            effects = get_user_upgrade_effects(user_id)
            build_mult = effects.get('build_time_mult', 1.0)
            adjusted_days = max(0.01, build_time_days * build_mult)  # Floor: ~15 min
            ready_at = datetime.now(timezone.utc) + timedelta(days=adjusted_days)

        # Update database with build timer
        with db_cursor(commit=True) as cur:
            if build_time_days > 0:
                # Start build timer - set pending_level and ready_at, keep current level
                cur.execute("""
                    INSERT INTO pilgrim.player_upgrades
                    (user_id, category, item_key, level, pending_level, ready_at, upgraded_at, tx_hash)
                    VALUES (%s, %s, %s, %s, %s, %s, NOW(), %s)
                    ON CONFLICT (user_id, category, item_key)
                    DO UPDATE SET pending_level = %s, ready_at = %s, upgraded_at = NOW(), tx_hash = %s
                """, (
                    user_id, category, item_key, current_level, next_level, ready_at, tx_hash,
                    next_level, ready_at, tx_hash
                ))
                logger.info(f"⏱️ User {user_id} started upgrade {category}/{item_key} to Lv{next_level} (ready in {build_time_days} days)")
                from utilities.db_activity import log_activity
                log_activity(user_id, 'upgrade', 'upgrade_started',
                             f"Upgrading: {item_key.replace('_', ' ').title()} Lv{next_level}",
                             amount=cost_display, detail=f"{category} · {build_time_days}d build",
                             tx_hash=tx_hash or '', source_table='player_upgrades',
                             metadata={'category': category, 'item_key': item_key, 'from_level': current_level, 'to_level': next_level})
            else:
                # Instant upgrade (build_time_days = 0)
                cur.execute("""
                    INSERT INTO pilgrim.player_upgrades
                    (user_id, category, item_key, level, pending_level, ready_at, upgraded_at, tx_hash)
                    VALUES (%s, %s, %s, %s, NULL, NULL, NOW(), %s)
                    ON CONFLICT (user_id, category, item_key)
                    DO UPDATE SET level = %s, pending_level = NULL, ready_at = NULL, upgraded_at = NOW(), tx_hash = %s
                """, (user_id, category, item_key, next_level, tx_hash, next_level, tx_hash))
                logger.info(f"✅ User {user_id} instantly upgraded {category}/{item_key} to Lv{next_level}")
                from utilities.db_activity import log_activity
                log_activity(user_id, 'upgrade', 'upgrade_complete',
                             f"Upgraded: {item_key.replace('_', ' ').title()} Lv{next_level}",
                             amount=cost_display, detail=category, tx_hash=tx_hash or '',
                             source_table='player_upgrades',
                             metadata={'category': category, 'item_key': item_key, 'from_level': current_level, 'to_level': next_level})

        # First-Reveal: Check if image needs generation (for build timer, do this in background)
        is_first_reveal = False
        try:
            if category == 'infrastructure':
                from utilities.upgrade_image_utils import maybe_generate_infrastructure_image
                image_result = maybe_generate_infrastructure_image(item_key, next_level, user_id)
            else:
                from utilities.upgrade_image_utils import maybe_generate_upgrade_image
                image_result = maybe_generate_upgrade_image(category, item_key, next_level, user_id)
            is_first_reveal = image_result.get('is_first_reveal', False)
            if is_first_reveal:
                logger.info(f"First Reveal! User {user_id} discovered {category}/{item_key} level {next_level}")
        except Exception as img_err:
            logger.warning(f"Image generation check failed (non-blocking): {img_err}")

        return {
            'success': True,
            'category': category,
            'item_key': item_key,
            'old_level': current_level,
            'new_level': next_level,
            'cost': cost_display,
            'stats': next_stats,
            'item_name': item_config['name'],
            'level_name': next_stats.get('name', f'Level {next_level}'),
            'is_first_reveal': is_first_reveal,
            'build_time_days': build_time_days,
            'ready_at': ready_at.isoformat() if ready_at else None,
            'is_building': build_time_days > 0
        }

    except Exception as e:
        logger.error(f"Failed to perform upgrade: {e}")
        return {'success': False, 'error': str(e)}


# ============================================================================
# CATALOG FOR UI
# ============================================================================

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
                current_stats = get_upgrade_stats(category, item_key, current_level) or {}
                next_stats = get_upgrade_stats(category, item_key, current_level + 1)

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


def get_vehicle_for_expedition(user_id: int, vehicle_type: str = 'rover') -> Dict[str, Any]:
    """
    Get vehicle stats for expedition calculations.
    Returns stats dict with cargo, speed_mult, discovery bonuses.
    """
    level = get_user_upgrade_level(user_id, 'vehicles', vehicle_type)
    if level == 0:
        return None  # Vehicle not unlocked

    stats = get_upgrade_stats('vehicles', vehicle_type, level)
    if not stats:
        return None

    return {
        'vehicle_type': vehicle_type,
        'level': level,
        'name': stats.get('name', f'{vehicle_type} Lv{level}'),
        'cargo': stats.get('cargo', 5),
        'speed_mult': stats.get('expedition_speed_mult', stats.get('speed_mult', 1.0)),
        'max_range_km': stats.get('max_range_km', 9999),
        'discovery_bonus': stats.get('discovery_bonus', 0),
        'rare_bonus': stats.get('rare_bonus', 0),
        'legendary_bonus': stats.get('legendary_bonus', 0),
        'image_url': stats.get('image_url'),
    }


def get_user_owned_vehicles(user_id: int) -> List[Dict[str, Any]]:
    """
    Get list of all vehicles owned by user (level >= 1).
    Used for expedition slot calculation - each vehicle = 1 expedition slot.
    """
    vehicles = []
    for vehicle_type in ['rover', 'drone', 'buggy']:
        vehicle = get_vehicle_for_expedition(user_id, vehicle_type)
        if vehicle:
            vehicles.append(vehicle)
    return vehicles


def count_user_vehicles(user_id: int) -> int:
    """
    Count total vehicles owned by user.
    Expedition slots = number of vehicles owned.
    """
    return len(get_user_owned_vehicles(user_id))


# ============================================================================
# UPGRADE EFFECTS - Calculate cumulative bonuses from all upgrades
# ============================================================================

def get_user_upgrade_effects(user_id: int) -> Dict[str, Any]:
    """
    Calculate all cumulative effects from user's upgrades AND infrastructure.
    Reads from player_upgrades table + UPGRADE_CATALOG.

    Returns a dict of effect_name -> total_value

    Example output:
    {
        'expedition_speed_mult': 2.0,  # From rover level
        'cargo_slots': 8,              # From rover
        'discovery_chance_bonus': 0.35,  # From scanner
        'rare_chance_bonus': 0.10,
        'life_support_cost_mult': 0.85,
        'fuel_cost_mult': 0.8,  # From water_extractor infrastructure
        ...
    }
    """
    # Initialize with defaults (unified from both upgrade and shop systems)
    effects = {
        # Vehicle/expedition effects
        'expedition_speed_mult': 1.0,
        'cargo_slots': 0,
        'fuel_cost_mult': 1.0,
        'max_range_km': 0,

        # Discovery effects
        'discovery_chance_bonus': 0.0,
        'rare_chance_bonus': 0.0,
        'legendary_chance_bonus': 0.0,
        'discovery_value_mult': 1.0,
        'bio_discovery_value_mult': 1.0,

        # Expedition cost effects
        'life_support_cost_mult': 1.0,

        # Passive income effects
        'passive_income_mult': 1.0,
        'passive_income_base': 0,

        # Captain stat bonuses
        'stat_exploration_bonus': 0,
        'stat_leadership_bonus': 0,
        'stat_strategy_bonus': 0,
        'stat_logistics_bonus': 0,
        'stat_charisma_bonus': 0,

        # Build speed (lower = faster, like cost mults)
        'build_time_mult': 1.0,

        # Boolean flags
        'dust_storm_immune': False,

        # Storage capacity (discovery limit) - default 300, Storage Bunker adds more
        'storage_capacity': 300,
    }

    # Get all user upgrades from new unified system
    user_upgrades = get_all_user_upgrades(user_id)

    # Apply upgrade effects from UPGRADE_CATALOG
    for category, items in user_upgrades.items():
        for item_key, level in items.items():
            if level == 0:
                continue  # Not unlocked

            stats = get_upgrade_stats(category, item_key, level)
            if not stats:
                continue

            # Apply each stat from the level config
            for key, value in stats.items():
                if key in ['name', 'cost', 'image_url', 'build_time_days']:
                    continue  # Skip non-effect fields

                # Map capacity (from Storage Bunker) to storage_capacity
                if key == 'capacity':
                    effects['storage_capacity'] = max(effects.get('storage_capacity', 300), value)
                    continue

                if key not in effects:
                    effects[key] = value
                    continue

                current = effects[key]

                # Multiplicative effects - take the best value
                if key.endswith('_mult'):
                    if 'cost' in key:
                        # Cost mults: lower is better
                        effects[key] = min(current, value)
                    else:
                        # Other mults: higher is better
                        effects[key] = max(current, value)

                # Additive - stack
                elif key.endswith('_bonus') or key.endswith('_base') or key in ['cargo', 'cargo_slots', 'max_range_km']:
                    effects[key] = current + value

                # Boolean flags - OR together
                elif isinstance(value, bool):
                    effects[key] = current or value

    # Map 'cargo' to 'cargo_slots' for backward compat
    if 'cargo' in effects and effects['cargo'] > 0:
        effects['cargo_slots'] = effects.get('cargo_slots', 0) + effects['cargo']

    # Apply infrastructure effects
    try:
        from utilities.infrastructure_utils import get_user_infrastructure_effects
        infra_effects = get_user_infrastructure_effects(user_id)

        for key, value in infra_effects.items():
            if key not in effects:
                effects[key] = value
                continue

            current = effects[key]

            if key.endswith('_mult'):
                if 'cost' in key:
                    effects[key] = current * value  # Stack cost reductions
                else:
                    effects[key] = max(current, value)
            elif key.endswith('_bonus'):
                effects[key] = current + value
            elif isinstance(value, bool):
                effects[key] = current or value

    except ImportError:
        pass

    # Apply tech tree effects (research bonuses)
    try:
        from utilities.tech_utils import get_tech_effects
        tech_effects = get_tech_effects(user_id)

        for key, value in tech_effects.items():
            if key not in effects:
                effects[key] = value
                continue

            current = effects[key]
            if key.endswith('_mult'):
                if 'cost' in key:
                    effects[key] = current * value
                else:
                    effects[key] = current * value
            elif key.endswith('_bonus') or key.endswith('_base') or key in ['cargo_slots']:
                effects[key] = current + value
            elif isinstance(value, bool):
                effects[key] = current or value
    except ImportError:
        pass

    # Captain Logistics stat → build speed bonus
    try:
        from utilities.postgres_utils import get_commander_stats
        stats = get_commander_stats(user_id)
        if stats:
            logistics = stats.get('logistics', 0) or 0
            # Logistics 0 = no bonus, 50 = 10% faster, 100 = 20% faster
            logistics_build_mult = max(0.5, 1.0 - logistics / 500.0)
            effects['build_time_mult'] = effects.get('build_time_mult', 1.0) * logistics_build_mult
    except Exception:
        pass

    return effects
