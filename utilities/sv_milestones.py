"""
SV Economy: Collection Milestones (Dr. Bo's Research Program)

Per SV Economy brainstorm — Luke approved "hybrid" option:
Track total items analyzed (sharded). Award one-time SV at thresholds.
Milestones are permanent achievements, awarded once per threshold.
"""

import logging
from utilities.postgres_utils import db_cursor

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
    from utilities.db_users import add_passive_sv

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
