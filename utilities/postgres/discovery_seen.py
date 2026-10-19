"""#1508: per-item "seen" state for the Collection page new-discovery signal.

Server-side per-(user, discovery_item) acknowledgement — NOT localStorage
(#1397 ReOpen v3 ripped localStorage out: unreliable across devices, can corrupt
into a singleton dismiss key). A collected discovery_item_id with NO row here is
"NEW" → highlighted card until the captain clicks it (Part 2). The one-time
backfill modal (Part 1) fires when this table is EMPTY for the user, then bulk-
inserts every currently-collected id so it never re-fires.

Part 3 (haul-popup "first-ever find") is INDEPENDENT of this table — see
build_expedition_haul's is_first_ever (lifetime claimed-distinct), since the haul
shows before anything is claimed.
"""

import logging
from utilities.postgres.core import db_cursor
from utilities.ensure_once import ensure_once

logger = logging.getLogger(__name__)


@ensure_once
def ensure_seen_table() -> bool:
    """Idempotent: pilgrim.player_seen_discoveries. Guarded @ensure_once so the
    DDL fires at most once per process (shared Cloud SQL — db-speed-first rule)."""
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS pilgrim.player_seen_discoveries (
                    user_id           INTEGER NOT NULL,
                    discovery_item_id INTEGER NOT NULL,
                    seen_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (user_id, discovery_item_id)
                );
            """)
        return True
    except Exception as e:
        logger.error(f"ensure_seen_table failed: {e}")
        return False


def get_seen_ids(user_id: int) -> set:
    """Set of discovery_item_ids this captain has already acknowledged."""
    ensure_seen_table()
    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT discovery_item_id FROM pilgrim.player_seen_discoveries WHERE user_id = %s",
                (user_id,))
            return {r['discovery_item_id'] for r in cur.fetchall()}
    except Exception as e:
        logger.error(f"get_seen_ids failed for {user_id}: {e}")
        return set()


def has_any_seen(user_id: int) -> bool:
    """True once the captain has ANY seen row — i.e. the one-time backfill modal
    has already fired. Drives Part 1's fire-exactly-once condition."""
    ensure_seen_table()
    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT 1 FROM pilgrim.player_seen_discoveries WHERE user_id = %s LIMIT 1",
                (user_id,))
            return cur.fetchone() is not None
    except Exception as e:
        logger.error(f"has_any_seen failed for {user_id}: {e}")
        return True  # fail safe: never spam the modal on a transient error


def mark_seen(user_id: int, discovery_item_id: int) -> bool:
    """Acknowledge ONE discovery item (Part 2: captain clicked the card)."""
    ensure_seen_table()
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO pilgrim.player_seen_discoveries (user_id, discovery_item_id)
                VALUES (%s, %s)
                ON CONFLICT (user_id, discovery_item_id) DO NOTHING
            """, (user_id, discovery_item_id))
        return True
    except Exception as e:
        logger.error(f"mark_seen failed for {user_id}/{discovery_item_id}: {e}")
        return False


def mark_all_collected_seen(user_id: int) -> int:
    """Bulk-acknowledge every currently-collected item (Part 1: backfill modal
    dismissed). Inserts one row per distinct claimed discovery_item_id so the
    modal never re-fires and no legacy item carries a NEW badge. Returns count."""
    ensure_seen_table()
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO pilgrim.player_seen_discoveries (user_id, discovery_item_id)
                SELECT %s, DISTINCT_ids.discovery_item_id FROM (
                    SELECT DISTINCT ed.discovery_item_id
                    FROM pilgrim.expedition_discoveries ed
                    JOIN pilgrim.expeditions e ON ed.expedition_id = e.id
                    WHERE e.user_id = %s AND ed.claimed_by_user = true
                ) DISTINCT_ids
                ON CONFLICT (user_id, discovery_item_id) DO NOTHING
            """, (user_id, user_id))
            return cur.rowcount or 0
    except Exception as e:
        logger.error(f"mark_all_collected_seen failed for {user_id}: {e}")
        return 0
