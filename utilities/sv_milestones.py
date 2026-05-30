"""
SV Economy: Collection Milestones (Dr. Bo's Research Program)

Per SV Economy brainstorm — Luke approved "hybrid" option:
Track total items analyzed (sharded). Award one-time SV at thresholds.
Milestones are permanent achievements, awarded once per threshold.
"""

import logging
from utilities.postgres.core import db_cursor

logger = logging.getLogger(__name__)

# Thresholds: total_items_analyzed -> SV reward (one-time, per brainstorm sign-off)
COLLECTION_MILESTONES = [
    (10, 250, "Novice Collector"),
    (25, 500, "Curious Analyst"),
    (50, 1000, "Field Researcher"),
    (100, 2000, "Specimen Expert"),
    (250, 5000, "Master Cataloger"),
    (500, 10000, "Mars Naturalist"),
]


def ensure_milestone_table():
    """Create milestone tracking table if it doesn't exist."""
    with db_cursor(commit=True) as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pilgrim.sv_milestones (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES pilgrim.users(id),
                threshold INTEGER NOT NULL,
                sv_awarded INTEGER NOT NULL,
                milestone_name TEXT NOT NULL,
                awarded_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(user_id, threshold)
            )
        """)


def check_and_award_milestones(user_id: int) -> list:
    """
    Check if user has crossed any new collection milestones.
    Called after each extraction/sharding operation.

    Returns list of newly awarded milestones (may be empty).
    """
    from utilities.postgres.users import add_passive_sv

    ensure_milestone_table()

    with db_cursor() as cur:
        # Count total items this user has analyzed (sharded)
        cur.execute("""
            SELECT COUNT(*) as total FROM pilgrim.expedition_discoveries ed
            JOIN pilgrim.expeditions e ON ed.expedition_id = e.id
            WHERE e.user_id = %s AND ed.analyzed = true
        """, (user_id,))
        total_analyzed = cur.fetchone()['total']

        # Get milestones already awarded
        cur.execute("""
            SELECT threshold FROM pilgrim.sv_milestones WHERE user_id = %s
        """, (user_id,))
        awarded = {row['threshold'] for row in cur.fetchall()}

    # Check each threshold
    newly_awarded = []
    for threshold, sv_reward, name in COLLECTION_MILESTONES:
        if total_analyzed >= threshold and threshold not in awarded:
            # Award it
            add_passive_sv(user_id, sv_reward)
            with db_cursor(commit=True) as cur:
                cur.execute("""
                    INSERT INTO pilgrim.sv_milestones (user_id, threshold, sv_awarded, milestone_name)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (user_id, threshold) DO NOTHING
                """, (user_id, threshold, sv_reward, name))
            newly_awarded.append({
                'threshold': threshold,
                'sv_reward': sv_reward,
                'name': name,
                'total_analyzed': total_analyzed
            })
            logger.info(f"🏆 Milestone: user {user_id} reached {name} ({threshold} items) — +{sv_reward} SV")

    return newly_awarded


def get_user_milestones(user_id: int) -> dict:
    """Get milestone status for display — which are earned, which are next."""
    ensure_milestone_table()

    with db_cursor() as cur:
        cur.execute("""
            SELECT COUNT(*) as total FROM pilgrim.expedition_discoveries ed
            JOIN pilgrim.expeditions e ON ed.expedition_id = e.id
            WHERE e.user_id = %s AND ed.analyzed = true
        """, (user_id,))
        total_analyzed = cur.fetchone()['total']

        cur.execute("""
            SELECT threshold, sv_awarded, milestone_name, awarded_at
            FROM pilgrim.sv_milestones WHERE user_id = %s ORDER BY threshold
        """, (user_id,))
        earned = cur.fetchall()

    earned_thresholds = {r['threshold'] for r in earned}
    next_milestone = None
    for threshold, sv_reward, name in COLLECTION_MILESTONES:
        # Consider earned if in DB OR if total_analyzed exceeds threshold
        if threshold not in earned_thresholds and total_analyzed < threshold:
            next_milestone = {
                'threshold': threshold,
                'sv_reward': sv_reward,
                'name': name,
                'items_remaining': threshold - total_analyzed
            }
            break

    return {
        'total_analyzed': total_analyzed,
        'earned': earned,
        'next': next_milestone,
        'all_milestones': [
            {'threshold': t, 'sv_reward': sv, 'name': n,
             'earned': t in earned_thresholds or total_analyzed >= t}
            for t, sv, n in COLLECTION_MILESTONES
        ]
    }


# ============================================================================
# CODEX MILESTONES (bug #1160) — a SEPARATE axis from the analyzed-based
# COLLECTION_MILESTONES above. The codex counts DISTINCT discovery items the
# captain has ever CLAIMED ("found"), per category, and rewards 100% completion.
# FOUND != ANALYZED: finding (claiming) fills the codex; sharding never removes
# it. Rewards below are TUNABLE — adjust freely (mirrored in math_registry.json).
# Source of truth for rewards: utilities/sv_milestones.py (these constants).
# ============================================================================
CODEX_CATEGORY_REWARD_SV = {
    'mineral': 1500, 'data': 1500, 'artifact': 2000,
    'biological': 2000, 'equipment': 1500,
}
CODEX_TOTAL_REWARD_SV = 10000  # all active items collected
CODEX_CATEGORY_TITLES = {
    'mineral': 'Mineral Cataloger', 'data': 'Data Archivist', 'artifact': 'Relic Keeper',
    'biological': 'Xenobiologist', 'equipment': 'Quartermaster',
}
CODEX_TOTAL_TITLE = 'Curator of Mars'


_CODEX_TABLE_ENSURED = False


def ensure_codex_milestone_table():
    """Codex milestone awards — keyed by milestone_key (e.g. 'category_biological',
    'total_all') so one row can represent a category OR the full-codex completion.
    Run-once per process (db-speed: don't CREATE on every hot-path call)."""
    global _CODEX_TABLE_ENSURED
    if _CODEX_TABLE_ENSURED:
        return
    with db_cursor(commit=True) as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pilgrim.codex_milestones (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES pilgrim.users(id),
                milestone_key TEXT NOT NULL,
                sv_awarded INTEGER NOT NULL,
                milestone_name TEXT NOT NULL,
                awarded_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(user_id, milestone_key)
            )
        """)
    _CODEX_TABLE_ENSURED = True


def get_earned_codex_milestones(user_id: int) -> list:
    """Just the awarded codex milestone rows (1 query, NO join) — for the /colony
    page reveal + display, so the page doesn't re-run the per-category JOIN that
    get_user_discovery_codex already does (db-speed-first)."""
    ensure_codex_milestone_table()
    with db_cursor() as cur:
        cur.execute("""
            SELECT milestone_key, sv_awarded, milestone_name
            FROM pilgrim.codex_milestones WHERE user_id = %s ORDER BY awarded_at
        """, (user_id,))
        return cur.fetchall()


def _codex_found_by_category(cur, user_id: int):
    """(found_by_type, total_by_type) — FOUND = distinct CLAIMED discovery_item_id,
    analyzed state ignored. Per-category totals are QUERIED (never hardcoded) so
    adding/retiring items can't make a category impossible to complete. One query."""
    cur.execute("""
        SELECT di.item_type,
               COUNT(*) FILTER (WHERE c.discovery_item_id IS NOT NULL) AS found,
               COUNT(*) AS total
        FROM pilgrim.discovery_items di
        LEFT JOIN (
            SELECT DISTINCT ed.discovery_item_id
            FROM pilgrim.expedition_discoveries ed
            JOIN pilgrim.expeditions e ON ed.expedition_id = e.id
            WHERE e.user_id = %s AND ed.claimed_by_user = true
        ) c ON c.discovery_item_id = di.id
        WHERE di.active = true
        GROUP BY di.item_type
    """, (user_id,))
    found, total = {}, {}
    for r in cur.fetchall():
        found[r['item_type']] = r['found']
        total[r['item_type']] = r['total']
    return found, total


def check_and_award_codex_milestones(user_id: int) -> list:
    """Award one-time SV for per-category 100% completion + full-codex completion.
    FOUND-based (claimed); separate table/axis from check_and_award_milestones.
    Called on every claim — cheap (2 queries, no loop-with-cursor). Returns the
    list of newly awarded milestones (may be empty)."""
    from utilities.postgres.users import add_passive_sv
    ensure_codex_milestone_table()

    with db_cursor() as cur:
        found, total = _codex_found_by_category(cur, user_id)
        cur.execute("SELECT milestone_key FROM pilgrim.codex_milestones WHERE user_id = %s", (user_id,))
        awarded = {r['milestone_key'] for r in cur.fetchall()}

    newly = []

    def _grant(key, sv, name):
        # Atomic: INSERT first, credit SV only if WE actually wrote the row. Ties the SV
        # grant to winning the UNIQUE(user_id, milestone_key) race so two concurrent
        # category-completing claims can't double-credit (the row dedupes; the SV would
        # not otherwise). DB is the single source of truth for "already awarded".
        with db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO pilgrim.codex_milestones (user_id, milestone_key, sv_awarded, milestone_name)
                VALUES (%s, %s, %s, %s) ON CONFLICT (user_id, milestone_key) DO NOTHING
            """, (user_id, key, sv, name))
            inserted = cur.rowcount > 0
        if not inserted:
            return  # already awarded by a racing claim/process — do NOT credit SV again
        add_passive_sv(user_id, sv)
        newly.append({'milestone_key': key, 'sv_reward': sv, 'name': name})
        logger.info(f"🏆 Codex milestone: user {user_id} → {name} (+{sv} SV)")

    for cat, tot in total.items():
        key = f"category_{cat}"
        if tot > 0 and found.get(cat, 0) >= tot and key not in awarded:
            _grant(key, CODEX_CATEGORY_REWARD_SV.get(cat, 1500),
                   CODEX_CATEGORY_TITLES.get(cat, f"{cat.title()} Complete"))

    grand_total = sum(total.values())
    grand_found = sum(found.get(c, 0) for c in total)
    if grand_total > 0 and grand_found >= grand_total and 'total_all' not in awarded:
        _grant('total_all', CODEX_TOTAL_REWARD_SV, CODEX_TOTAL_TITLE)

    return newly


def get_codex_milestones(user_id: int) -> dict:
    """Codex completion state + awarded milestone keys — feeds the /colony codex
    display, the fire-once reveal (earned_keys vs localStorage), PilgrimBot + ARIA."""
    ensure_codex_milestone_table()
    with db_cursor() as cur:
        found, total = _codex_found_by_category(cur, user_id)
        cur.execute("""
            SELECT milestone_key, sv_awarded, milestone_name, awarded_at
            FROM pilgrim.codex_milestones WHERE user_id = %s
        """, (user_id,))
        earned = cur.fetchall()
    return {
        'found_by_category': found,
        'total_by_category': total,
        'total_found': sum(found.get(c, 0) for c in total),
        'total_items': sum(total.values()),
        'earned_keys': [r['milestone_key'] for r in earned],
        'earned': earned,
        'category_rewards': CODEX_CATEGORY_REWARD_SV,
        'total_reward': CODEX_TOTAL_REWARD_SV,
    }
