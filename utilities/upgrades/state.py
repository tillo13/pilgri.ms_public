"""User-state DB reads: what a given user owns / is building.

Anything that queries player_upgrades for a specific user lives here,
plus the one-shot schema bootstrap (ensure_upgrades_table) and the
private _complete_pending_upgrade write used by auto-completion.
"""

import logging
from typing import Dict, Optional
from config import UPGRADE_CATALOG, INFRASTRUCTURE_CATALOG
from utilities.postgres.core import db_cursor, ensure_table_columns

logger = logging.getLogger(__name__)


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
        # Existence-checked migration columns — build timers (ready_at) + in-progress
        # target (pending_level). No ACCESS EXCLUSIVE lock when already present.
        ensure_table_columns('pilgrim', 'player_upgrades', {'ready_at': 'TIMESTAMP', 'pending_level': 'INTEGER'})
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
    from utilities.postgres.core import request_memo
    return request_memo(
        ('get_user_upgrade_level', user_id, category, item_key),
        lambda: _get_user_upgrade_level_uncached(user_id, category, item_key),
    )


def _get_user_upgrade_level_uncached(user_id: int, category: str, item_key: str) -> int:
    from datetime import datetime, timezone
    from utilities.upgrades.catalog import get_infrastructure_level, get_item_config

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
                SET level = %s, pending_level = NULL, ready_at = NULL,
                    upgraded_at = NOW()
                WHERE user_id = %s AND category = %s AND item_key = %s
            """, (new_level, user_id, category, item_key))
        logger.info(f"✅ Auto-completed upgrade: {user_id} {category}/{item_key} -> Lv{new_level}")
        # Bug #21 Deploy C: +1.0 Logistics per upgrade level-up. Dedupe key is
        # (category/item_key, new_level) so each level credits at most once.
        try:
            from utilities.postgres.captain_stats import award_stat_event
            award_stat_event(
                user_id, 'logistics', 1.0,
                'upgrade', f'player_upgrades:{category}/{item_key}', int(new_level),
            )
        except Exception as _e:
            logger.error(f"Bug #21 upgrade stat-event failed user={user_id} {category}/{item_key} L{new_level}: {_e}")
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


def get_user_upgrade_cap(user_id: int, _prefetch_infra_levels=None) -> int:
    """
    Get user's max concurrent upgrade cap.
    Base cap is 3. Habitat Module Level 5+ adds +1 slot.
    Pass _prefetch_infra_levels (dict from get_all_infrastructure_levels) to skip 2 DB round-trips.
    """
    cap = BASE_CONCURRENT_UPGRADE_CAP
    if _prefetch_infra_levels is not None:
        habitat_level = _prefetch_infra_levels.get('habitat_module', 0)
    else:
        from utilities.upgrades.catalog import get_infrastructure_level
        habitat_level = get_infrastructure_level(user_id, 'habitat_module')
    if habitat_level >= 5:
        cap += 1  # +1 slot at level 5
    return cap


def resolve_item_display_name(category: str, item_key: str, level=None) -> str:
    """Display name for an upgrade/infrastructure item at a given level.

    Prefers the per-level flavor name (e.g. robotics_lab L3 = 'Calibration Pit'),
    then the base catalog name ('Narog Foundry'), then a title-cased key. Resolves
    across BOTH catalogs so infrastructure items — keyed by item_key in
    INFRASTRUCTURE_CATALOG, not nested under a category in UPGRADE_CATALOG — don't
    fall through to the raw key ("Robotics Lab"). Single source of truth shared by
    get_active_builds and build_completions. #1472.
    """
    item_config = (UPGRADE_CATALOG.get(category, {}).get(item_key)
                   or INFRASTRUCTURE_CATALOG.get(item_key, {}))
    level_config = item_config.get('levels', {}).get(level, {}) if level is not None else {}
    return (level_config.get('name')
            or item_config.get('name')
            or item_key.replace('_', ' ').title())


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
            # Name from catalog — flavor name at the target level, resolved across
            # both catalogs so infra (robotics_lab → "Narog Foundry") doesn't
            # title-case to "Robotics Lab". #1472.
            item_name = resolve_item_display_name(row['category'], row['item_key'], row['pending_level'])

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


def get_all_build_statuses(user_id: int) -> Dict[tuple, dict]:
    """Bulk-fetch build status for every player_upgrades row. Returns {(category, item_key): status_dict}.
    Eliminates N+1 get_upgrade_build_status() calls in depot catalog iteration."""
    from datetime import datetime, timezone
    out: Dict[tuple, dict] = {}
    try:
        ensure_upgrades_table()
        with db_cursor() as cur:
            cur.execute("""
                SELECT category, item_key, level, pending_level, ready_at
                FROM pilgrim.player_upgrades
                WHERE user_id = %s
            """, (user_id,))
            rows = cur.fetchall()
        now = datetime.now(timezone.utc)
        to_complete = []
        for row in rows:
            cat = row['category']; key = row['item_key']
            pending_level = row['pending_level']
            ready_at = row['ready_at']
            if not pending_level or not ready_at:
                out[(cat, key)] = {'is_building': False, 'current_level': row['level']}
                continue
            ready_at_aware = ready_at.replace(tzinfo=timezone.utc) if ready_at.tzinfo is None else ready_at
            seconds_remaining = max(0, (ready_at_aware - now).total_seconds())
            if seconds_remaining <= 0:
                to_complete.append((cat, key, pending_level))
                out[(cat, key)] = {'is_building': False, 'current_level': pending_level}
            else:
                out[(cat, key)] = {
                    'is_building': True,
                    'pending_level': pending_level,
                    'ready_at': ready_at_aware.isoformat(),
                    'seconds_remaining': int(seconds_remaining),
                    'current_level': row['level'],
                }
        for cat, key, pl in to_complete:
            _complete_pending_upgrade(user_id, cat, key, pl)
    except Exception as e:
        logger.error(f"get_all_build_statuses failed: {e}")
    return out


def get_all_user_upgrades(user_id: int) -> Dict[str, Dict[str, int]]:
    """
    Get all upgrades for a user as nested dict: {category: {item_key: level}}
    Includes default levels for items not yet in DB.
    Per-request memoized — second call in the same request is free.
    """
    from utilities.postgres.core import request_memo
    return request_memo(('get_all_user_upgrades', user_id), lambda: _get_all_user_upgrades_uncached(user_id))


def _get_all_user_upgrades_uncached(user_id: int) -> Dict[str, Dict[str, int]]:
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
    from utilities.upgrades.catalog import get_level_stats
    return get_level_stats(category, item_key, level)
