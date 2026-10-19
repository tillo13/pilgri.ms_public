"""Bug #21 — Captain stats progression event log + cached value updater.

Luke locked V2 multipliers 2026-05-07 20:59 ("V2 is fine") and the 5-point
sign-off 2026-05-09 (Ok for EVA suit code / deprecate XP / Charisma placeholder
/ replicate_assets architecture / retro script). This module is the foundation:
every captain-stat change becomes an event row, and the cached integer column
`pilgrim.replicate_assets.commander_<stat>` is recomputed from the event sum
on every award.

Model:
    captain_stat_events(user_id, stat_name, delta, source_kind, source_table,
                       source_id) with UNIQUE on the last four — so the same
                       crew_mission / expedition / landmark / bond / etc can
                       NEVER be credited twice.

    source_kind values:
      'baseline'      — initial value at character creation OR retro snapshot
      'retro_credit'  — one-shot retroactive growth (Luke-approved V2 numbers)
      'sol_tick'      — daily passive Leadership growth per active captain
      'crew_mission'  — +0.05 Leadership per completed crew mission
      'expedition'    — +0.2 Strategy per completed expedition + km contribution
      'legendary'     — +1.0 Strategy per legendary discovery on an expedition
      'km'            — +0.001 Exploration per km traveled (per expedition)
      'landmark'      — +1.0 Exploration per first-time landmark
      'trail_segment' — +0.05 Logistics per completed trail segment
      'upgrade'       — +1.0 Logistics per upgrade level-up
      'aria_bond'     — +2.0 Charisma per formed bond

    Current displayed stat = min(WORLD_1_CAP, ROUND(SUM(events.delta))).
    The integer commander_<stat> column is the cached version of that compute.

Race-condition handling between retro and live triggers:
    Retro and triggers use DIFFERENT source_kinds, so the dedupe UNIQUE
    constraint can't catch a double-credit on its own. The cutoff timestamp
    GO_LIVE_AT is written by the retro script at start, read at module import.
    Retro counts only activity with completed_at < GO_LIVE_AT; triggers only
    award for rows with completed_at >= GO_LIVE_AT. No overlap possible.
"""

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta, timezone

from utilities.postgres.core import db_cursor

logger = logging.getLogger(__name__)

STAT_NAMES = ['leadership', 'strategy', 'exploration', 'logistics', 'charisma']
WORLD_1_CAP = 75  # Luke 2026-04-12 §2: "Max cap is maybe it's 75 of World 1, 90 on World 2, and then 105 on World 3"

# V2 multipliers — Luke 2026-05-07 20:59 "V2 is fine".
# DO NOT modify without an explicit Luke directive on bug #21 / brainstorm captain-stats §2.
# Smoke-test pins this constant.
V2_MULTIPLIERS = {
    'leadership':  {'sol_tick': 0.1,   'crew_mission': 0.05},
    'strategy':    {'expedition': 0.2, 'legendary':    1.0},
    'exploration': {'km':        0.001, 'landmark':    1.0},
    'logistics':   {'trail_segment': 0.05, 'upgrade':  1.0},
    # Luke #198 / 2026-05-09 #3 "Ok to leave Charisma as is" → placeholder, bonds only.
    'charisma':    {'aria_bond': 2.0},
}

# Mapping from source_kind back to which stat it credits.
SOURCE_KIND_TO_STAT = {
    'sol_tick':      'leadership',
    'crew_mission':  'leadership',
    'expedition':    'strategy',
    'legendary':     'strategy',
    'km':            'exploration',
    'landmark':      'exploration',
    'trail_segment': 'logistics',
    'upgrade':       'logistics',
    'aria_bond':     'charisma',
}

_schema_ensured = False
_go_live_at: Optional[datetime] = None


def ensure_captain_stat_events_table() -> None:
    """Create captain_stat_events + meta table on first call. Idempotent."""
    global _schema_ensured
    if _schema_ensured:
        return
    _schema_ensured = True
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS pilgrim.captain_stat_events (
                    id          SERIAL PRIMARY KEY,
                    user_id     INTEGER NOT NULL REFERENCES pilgrim.users(id),
                    stat_name   TEXT NOT NULL,
                    delta       NUMERIC(10,4) NOT NULL,
                    source_kind TEXT NOT NULL,
                    source_table TEXT NOT NULL DEFAULT '',
                    source_id   INTEGER NOT NULL DEFAULT 0,
                    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE (user_id, stat_name, source_kind, source_table, source_id)
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_cse_user_time ON pilgrim.captain_stat_events(user_id, created_at DESC)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_cse_user_stat ON pilgrim.captain_stat_events(user_id, stat_name)")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS pilgrim.captain_stats_meta (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
    except Exception as e:
        logger.error(f"Failed to ensure captain_stat_events table: {e}")


def get_go_live_at() -> Optional[datetime]:
    """Read the deploy-cutoff timestamp written by the retro script. None if
    retro has not yet run (treat triggers as no-op until retro lands)."""
    global _go_live_at
    if _go_live_at is not None:
        return _go_live_at
    ensure_captain_stat_events_table()
    try:
        with db_cursor() as cur:
            cur.execute("SELECT value FROM pilgrim.captain_stats_meta WHERE key='go_live_at'")
            r = cur.fetchone()
            if r:
                _go_live_at = datetime.fromisoformat(r['value'])
                return _go_live_at
    except Exception as e:
        logger.warning(f"get_go_live_at read failed: {e}")
    return None


def set_go_live_at(ts: datetime) -> None:
    """Called once by the retro script after it snapshots activity. Triggers
    that fire on rows with completed_at >= ts will award; retro counts only
    rows with completed_at < ts. No overlap possible.

    FIRST CALL WINS — re-running the retro script must NOT shift the cutoff,
    or live triggers in the window between two runs would silently drop events.
    """
    ensure_captain_stat_events_table()
    global _go_live_at
    with db_cursor(commit=True) as cur:
        cur.execute("""
            INSERT INTO pilgrim.captain_stats_meta (key, value)
            VALUES ('go_live_at', %s)
            ON CONFLICT (key) DO NOTHING
        """, (ts.isoformat(),))
        cur.execute("SELECT value FROM pilgrim.captain_stats_meta WHERE key='go_live_at'")
        r = cur.fetchone()
        if r:
            _go_live_at = datetime.fromisoformat(r['value'])


def _primary_asset_id(cur, user_id: int) -> Optional[int]:
    """The replicate_assets row /crew actually displays — get_primary_commander's
    selector (asset_type IN character_image+edited_image, is_primary_character=true).
    Fallback to latest character_image when no primary is flagged (early captains
    sometimes lack the primary flag — preserves the original behavior).
    """
    cur.execute("""
        SELECT id FROM pilgrim.replicate_assets
        WHERE user_id = %s
          AND asset_type IN ('character_image', 'edited_image')
          AND is_deleted = FALSE
          AND is_primary_character = TRUE
          AND commander_leadership IS NOT NULL
        LIMIT 1
    """, (user_id,))
    r = cur.fetchone()
    if r:
        return r['id']
    # Fallback: legacy captains with no primary flag
    cur.execute("""
        SELECT id FROM pilgrim.replicate_assets
        WHERE user_id = %s AND asset_type = 'character_image' AND is_deleted = FALSE
          AND commander_leadership IS NOT NULL
        ORDER BY created_at DESC LIMIT 1
    """, (user_id,))
    r = cur.fetchone()
    return r['id'] if r else None


def _recompute_and_save(cur, user_id: int, stat: str) -> int:
    """Sum events for this user+stat, cap, write to PRIMARY asset, return new int."""
    cur.execute("""
        SELECT COALESCE(SUM(delta), 0) AS total
        FROM pilgrim.captain_stat_events
        WHERE user_id = %s AND stat_name = %s
    """, (user_id, stat))
    total = float(cur.fetchone()['total'] or 0)
    new_int = max(0, min(WORLD_1_CAP, round(total)))
    asset_id = _primary_asset_id(cur, user_id)
    if asset_id is not None:
        col = f'commander_{stat}'
        cur.execute(f"UPDATE pilgrim.replicate_assets SET {col} = %s, updated_at = NOW() WHERE id = %s", (new_int, asset_id))
    return new_int


def _ensure_baselines_for_user(cur, user_id: int) -> bool:
    """Lazy baseline: if this user has zero events, write 5 baseline events
    seeded from current commander_<stat> values. Returns True if a character
    image exists (i.e. awarding is possible). Safe to call from any trigger
    path — idempotent via UNIQUE on (user, stat, 'baseline', '', 0).
    """
    cur.execute("SELECT 1 FROM pilgrim.captain_stat_events WHERE user_id = %s LIMIT 1", (user_id,))
    if cur.fetchone():
        return True  # baselines (or other events) already exist
    # Read from the PRIMARY asset — same one /crew renders and the trigger
    # writer updates. Diverging from get_primary_commander caused the Deploy B
    # mismatch where retro wrote to character_image while /crew read edited_image.
    asset_id = _primary_asset_id(cur, user_id)
    if asset_id is None:
        return False  # no character yet — caller should drop the event
    cur.execute("""
        SELECT commander_leadership, commander_strategy, commander_exploration,
               commander_logistics, commander_charisma
        FROM pilgrim.replicate_assets WHERE id = %s
    """, (asset_id,))
    r = cur.fetchone()
    if r is None or r['commander_leadership'] is None:
        return False  # no character yet — caller should drop the event
    for stat in STAT_NAMES:
        val = int(r[f'commander_{stat}'] or 0)
        cur.execute("""
            INSERT INTO pilgrim.captain_stat_events
                (user_id, stat_name, delta, source_kind, source_table, source_id)
            VALUES (%s, %s, %s, 'baseline', '', 0)
            ON CONFLICT (user_id, stat_name, source_kind, source_table, source_id)
            DO NOTHING
        """, (user_id, stat, val))
    return True


def award_stat_event(
    user_id: int,
    stat: str,
    delta: float,
    source_kind: str,
    source_table: str = '',
    source_id: int = 0,
) -> Optional[Dict[str, Any]]:
    """Insert an event + bump the cached commander_<stat>. Dedupes on
    (user_id, stat, source_kind, source_table, source_id).

    Returns {'stat', 'delta', 'old', 'new', 'capped', 'source_kind'} on success.
    Returns None if the event was already credited (idempotent — safe to retry).
    Never raises — stat-event failure must not block the game action it hooks.

    Lazy-baselines the captain on first event so the cached integer stays
    consistent with the simulation Luke approved.
    """
    if stat not in STAT_NAMES:
        logger.warning(f"award_stat_event: bad stat {stat!r}")
        return None
    if delta == 0:
        return None
    ensure_captain_stat_events_table()
    try:
        with db_cursor(commit=True) as cur:
            # Lazy baseline — first event for this captain seeds five baseline
            # rows from current commander_<stat>. After this, SUM(deltas) is a
            # complete description of the captain's stat history.
            if not _ensure_baselines_for_user(cur, user_id):
                return None  # no character — pre-character growth impossible

            asset_id = _primary_asset_id(cur, user_id)
            if asset_id is None:
                return None
            cur.execute(f"SELECT commander_{stat} AS v FROM pilgrim.replicate_assets WHERE id = %s", (asset_id,))
            r = cur.fetchone()
            old_int = int(r['v'] or 0) if r else 0

            cur.execute("""
                INSERT INTO pilgrim.captain_stat_events
                    (user_id, stat_name, delta, source_kind, source_table, source_id)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, stat_name, source_kind, source_table, source_id)
                DO NOTHING
                RETURNING id
            """, (user_id, stat, float(delta), source_kind, source_table or '', int(source_id or 0)))
            inserted = cur.fetchone()
            if not inserted:
                return None  # dedupe — already credited

            new_int = _recompute_and_save(cur, user_id, stat)

        return {
            'stat': stat,
            'delta': float(delta),
            'old': old_int,
            'new': new_int,
            'capped': new_int >= WORLD_1_CAP,
            'source_kind': source_kind,
        }
    except Exception as e:
        logger.error(f"award_stat_event failed user={user_id} stat={stat} kind={source_kind}: {e}")
        return None


def snapshot_baseline(user_id: int, current_stats: Dict[str, int]) -> None:
    """Write 5 baseline events for a captain — one per stat — using current
    commander_<stat> values. Used by the retro script for existing captains,
    and by character creation for new captains.

    Idempotent: re-running won't double-baseline because (user_id, stat,
    'baseline', '', 0) is unique.
    """
    ensure_captain_stat_events_table()
    try:
        with db_cursor(commit=True) as cur:
            for stat in STAT_NAMES:
                val = int(current_stats.get(stat, 0) or 0)
                cur.execute("""
                    INSERT INTO pilgrim.captain_stat_events
                        (user_id, stat_name, delta, source_kind, source_table, source_id)
                    VALUES (%s, %s, %s, 'baseline', '', 0)
                    ON CONFLICT (user_id, stat_name, source_kind, source_table, source_id)
                    DO NOTHING
                """, (user_id, stat, val))
    except Exception as e:
        logger.error(f"snapshot_baseline failed user={user_id}: {e}")


def get_recent_stat_events(user_id: int, hours: int = 24) -> List[Dict[str, Any]]:
    """For the ↑ indicator on /crew. Returns events created within `hours`,
    EXCLUDING baseline + retro_credit (those aren't 'recent' to the player)."""
    ensure_captain_stat_events_table()
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT stat_name, delta, source_kind, source_table, source_id, created_at
                FROM pilgrim.captain_stat_events
                WHERE user_id = %s
                  AND created_at >= %s
                  AND source_kind NOT IN ('baseline', 'retro_credit')
                ORDER BY created_at DESC
            """, (user_id, datetime.now(timezone.utc) - timedelta(hours=hours)))
            return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.warning(f"get_recent_stat_events failed user={user_id}: {e}")
        return []


def get_event_totals(user_id: int) -> Dict[str, float]:
    """Sum events per stat for one user. Useful for audit + debug pages."""
    ensure_captain_stat_events_table()
    out = {s: 0.0 for s in STAT_NAMES}
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT stat_name, COALESCE(SUM(delta), 0) AS total
                FROM pilgrim.captain_stat_events
                WHERE user_id = %s
                GROUP BY stat_name
            """, (user_id,))
            for r in cur.fetchall():
                out[r['stat_name']] = float(r['total'])
    except Exception as e:
        logger.warning(f"get_event_totals failed user={user_id}: {e}")
    return out
