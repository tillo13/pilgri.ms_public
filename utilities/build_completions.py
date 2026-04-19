"""Build completions summary — catalog-enriched detail for recently-finished
upgrades and infrastructure builds.

Used by:
- Depot page landing modal (bug #1397)
- While-You-Were-Away briefing (bug #1397)

Returns structured data (name, old_level → new_level, cost, new bonuses,
Lv Y image) so the frontend can render rich cards instead of bare names.
"""

import logging
from datetime import datetime, timezone

from utilities.postgres.core import db_cursor

logger = logging.getLogger(__name__)


_EFFECT_KEYS_SKIP = {
    'name', 'cost', 'image_url', 'build_time_days', 'effect_description',
    'description', 'icon',
}

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


def get_recent_build_completions(user_id: int, since_dt=None, limit: int = 10) -> list:
    """Recently-completed upgrades with catalog detail for display.

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

    now = datetime.now(timezone.utc)
    if since_dt is not None and since_dt.tzinfo is None:
        since_dt = since_dt.replace(tzinfo=timezone.utc)

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

        item_name = (
            new_data.get('name')
            or entry.get('name')
            or item_key.replace('_', ' ').title()
        )
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
