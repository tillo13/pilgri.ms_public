"""Build completions summary — catalog-enriched detail for recently-finished
upgrades and infrastructure builds.

Used by:
- Depot page landing modal (bug #1397)
- While-You-Were-Away briefing (bug #1397)

Returns structured data (name, old_level → new_level, cost, new bonuses,
Lv Y image AND Lv X image) so the frontend can render rich before/after cards.

Bug #1397 ReOpen v3 (2026-04-29): replace the localStorage-based modal
suppression with a server-side `pilgrim.users.depot_completions_seen_at`
timestamp. localStorage was unreliable across sessions/devices and could be
silently corrupted into a singleton dismiss key that suppressed every future
modal (Luke's "shows ~25% of the time"). Server-side is deterministic.
"""

import logging
from datetime import datetime, timezone

from utilities.postgres.core import db_cursor

logger = logging.getLogger(__name__)

_SEEN_COLUMN_ENSURED = False


def ensure_completions_seen_column() -> bool:
    """Idempotent migration: pilgrim.users.depot_completions_seen_at TIMESTAMP."""
    global _SEEN_COLUMN_ENSURED
    if _SEEN_COLUMN_ENSURED:
        return True
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'pilgrim' AND table_name = 'users'
                          AND column_name = 'depot_completions_seen_at'
                    ) THEN
                        ALTER TABLE pilgrim.users ADD COLUMN depot_completions_seen_at TIMESTAMP NULL;
                    END IF;
                END $$;
            """)
        _SEEN_COLUMN_ENSURED = True
        return True
    except Exception as e:
        logger.error(f"ensure_completions_seen_column failed: {e}")
        return False


def mark_completions_seen(user_id: int) -> bool:
    """Stamp depot_completions_seen_at = NOW() so the modal won't re-fire."""
    ensure_completions_seen_column()
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE pilgrim.users
                SET depot_completions_seen_at = NOW(), updated_at = NOW()
                WHERE id = %s
            """, (user_id,))
        return True
    except Exception as e:
        logger.error(f"mark_completions_seen failed for user {user_id}: {e}")
        return False


def _get_completions_seen_at(user_id: int):
    """Returns the user's last-seen timestamp (UTC-aware) or None."""
    ensure_completions_seen_column()
    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT depot_completions_seen_at FROM pilgrim.users WHERE id = %s",
                (user_id,),
            )
            row = cur.fetchone()
        seen = (row or {}).get('depot_completions_seen_at') if row else None
        if seen and seen.tzinfo is None:
            seen = seen.replace(tzinfo=timezone.utc)
        return seen
    except Exception as e:
        logger.warning(f"_get_completions_seen_at failed user={user_id}: {e}")
        return None


_EFFECT_KEYS_SKIP = {
    'name', 'cost', 'build_time_days', 'effect_description', 'description',
    # metadata/gates — never player-facing stat diffs (leaked "Level Requires:
    # {'habitat_module': 3}" into the build-complete modal, found via #1472)
    'level_requires', 'level_unlocks', 'robot_unlocked',
}

# Bug #1463: any image/media/url field must never render as a stat diff. A
# denylist of specific keys (image_url) let the buggy-only longhaul_image_url
# leak its raw URL into the build-complete modal. Skip the whole class so the
# next *_image_url / *_url / icon / thumbnail / video field can't regress it.
_MEDIA_KEY_MARKERS = ('image', 'url', 'icon', 'thumb', 'video')


def _is_media_key(k: str) -> bool:
    kl = k.lower()
    return any(m in kl for m in _MEDIA_KEY_MARKERS)

_EFFECT_LABELS = {
    'cargo': 'Cargo',
    'expedition_speed_mult': 'Speed',
    'max_range_km': 'Range',
    'fuel_cost_mult': 'Fuel Cost',
    'generation_rate': 'Generation',
    'max_concurrent': 'Concurrent',
    'trail_km_per_hour': 'Trail km/hr',
    'discovery_value_mult': 'Discovery Value',
    'bio_discovery_value_mult': 'Bio Discovery Value',
    'build_time_mult': 'Build Speed',
    'research_speed_mult': 'Research Speed',
    'robot_build_speed_mult': 'Narog Assembly Speed',  # #1472: was bare-titling to "Robot Build Speed Mult"
    'sv_storage_cap': 'SV Storage',
    'storage_cap': 'Storage Cap',
}


def _fmt(v):
    if v is None:
        return '—'
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, float):
        return f"{v:g}" if v != int(v) else f"{int(v):,}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def _format_effect_diff(old_data: dict, new_data: dict) -> list:
    """Human-readable diff lines for keys that changed between two level dicts."""
    diffs = []
    keys = (set(old_data.keys()) | set(new_data.keys())) - _EFFECT_KEYS_SKIP
    for k in sorted(keys):
        if _is_media_key(k):
            continue
        ov = old_data.get(k)
        nv = new_data.get(k)
        if ov == nv:
            continue
        label = _EFFECT_LABELS.get(k, k.replace('_', ' ').title())
        if k.endswith('_mult'):
            diffs.append(f"{label}: {_fmt(ov)}× → {_fmt(nv)}×")
        else:
            diffs.append(f"{label}: {_fmt(ov)} → {_fmt(nv)}")
    return diffs


def get_recent_build_completions(user_id: int, since_dt=None, limit: int = 10,
                                 use_seen_timestamp: bool = False) -> list:
    """Recently-completed upgrades with catalog detail for display.

    Args:
        since_dt: explicit lower-bound timestamp. WYWA briefing uses this.
        use_seen_timestamp: when True, ignore since_dt and instead filter to
            anything completed AFTER pilgrim.users.depot_completions_seen_at.
            The depot landing modal uses this so completions never re-show
            once a captain has dismissed them. Bug #1397 ReOpen v3.

    Each item:
        category, item_key, item_name,
        old_level, new_level,
        cost, image_url, prev_image_url,
        effect_diff (list[str]),
        completed_at (iso),
    Newest first.
    """
    from config_upgrades import UPGRADE_CATALOG
    from config_infrastructure import INFRASTRUCTURE_CATALOG

    if since_dt is not None and since_dt.tzinfo is None:
        since_dt = since_dt.replace(tzinfo=timezone.utc)

    if use_seen_timestamp:
        # Server-side suppression: filter to completions newer than the
        # captain's last "seen" stamp. None == never seen, so show everything.
        since_dt = _get_completions_seen_at(user_id)

    try:
        with db_cursor() as cur:
            # pending_level IS NULL = build has completed (not mid-build).
            # upgraded_at is bumped to NOW() on completion (see
            # _complete_pending_upgrade), so it doubles as completed_at.
            if since_dt:
                cur.execute("""
                    SELECT category, item_key, level, upgraded_at AS completed_at
                    FROM pilgrim.player_upgrades
                    WHERE user_id = %s
                      AND pending_level IS NULL
                      AND upgraded_at IS NOT NULL
                      AND upgraded_at > %s
                    ORDER BY upgraded_at DESC
                    LIMIT %s
                """, (user_id, since_dt, limit))
            else:
                cur.execute("""
                    SELECT category, item_key, level, upgraded_at AS completed_at
                    FROM pilgrim.player_upgrades
                    WHERE user_id = %s
                      AND pending_level IS NULL
                      AND upgraded_at IS NOT NULL
                    ORDER BY upgraded_at DESC
                    LIMIT %s
                """, (user_id, limit))
            rows = [dict(r) for r in (cur.fetchall() or [])]
    except Exception as e:
        logger.error(f"get_recent_build_completions failed for user {user_id}: {e}")
        return []

    results = []
    for r in rows:
        category = r['category']
        item_key = r['item_key']
        new_level = int(r['level'] or 1)
        old_level = max(1, new_level - 1)

        if category == 'infrastructure':
            entry = INFRASTRUCTURE_CATALOG.get(item_key, {})
        else:
            entry = UPGRADE_CATALOG.get(category, {}).get(item_key, {})

        levels = entry.get('levels', {}) or {}
        old_data = levels.get(old_level) or {}
        new_data = levels.get(new_level) or {}

        from utilities.upgrades.state import resolve_item_display_name
        item_name = resolve_item_display_name(category, item_key, new_level)
        from utilities.upgrade_image_utils import get_best_available_image
        image_url = (
            get_best_available_image(category, item_key, new_level)
            or entry.get('icon')
            or ''
        )
        prev_image_url = get_best_available_image(category, item_key, old_level) or ''
        try:
            cost = int(new_data.get('cost') or 0)
        except Exception:
            cost = 0

        results.append({
            'category': category,
            'item_key': item_key,
            'item_name': item_name,
            'old_level': old_level,
            'new_level': new_level,
            'cost': cost,
            'image_url': image_url,
            'prev_image_url': prev_image_url,
            'effect_diff': _format_effect_diff(old_data, new_data),
            'completed_at': r['completed_at'].isoformat() if r.get('completed_at') else None,
        })

    return results
