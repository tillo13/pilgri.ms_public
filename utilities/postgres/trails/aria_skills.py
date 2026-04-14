"""ARIA skill XP tracking + daily resonance bonus."""

import logging

from utilities.postgres.core import db_cursor
from utilities.postgres.trails.segments import (
    ensure_trail_segments_table,
    add_km_to_trail,
    get_trail_level_from_count,
)

logger = logging.getLogger(__name__)


def get_aria_skills(user_id: int) -> dict:
    """Get ARIA skills for a user, creating default record if needed"""
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO pilgrim.aria_skills (user_id)
                VALUES (%s)
                ON CONFLICT (user_id) DO NOTHING
            """, (user_id,))

            cur.execute("""
                SELECT * FROM pilgrim.aria_skills WHERE user_id = %s
            """, (user_id,))
            row = cur.fetchone()
            return dict(row) if row else {
                'resonance_xp': 0, 'resonance_level': 1,
                'crystal_sensing_xp': 0, 'crystal_sensing_level': 1,
                'lore_memory_xp': 0, 'lore_memory_level': 1
            }
    except Exception as e:
        logger.error(f"Failed to get ARIA skills: {e}")
        return {
            'resonance_xp': 0, 'resonance_level': 1,
            'crystal_sensing_xp': 0, 'crystal_sensing_level': 1,
            'lore_memory_xp': 0, 'lore_memory_level': 1
        }


def add_aria_skill_xp(user_id: int, skill: str, xp_amount: int) -> dict:
    """
    Add XP to an ARIA skill. Levels up automatically.
    Skill can be: 'resonance', 'crystal_sensing', 'lore_memory'
    """
    if skill not in ('resonance', 'crystal_sensing', 'lore_memory'):
        raise ValueError(f"Invalid ARIA skill: {skill}")

    xp_col = f"{skill}_xp"
    level_col = f"{skill}_level"

    try:
        with db_cursor(commit=True) as cur:
            # Ensure record exists
            cur.execute("""
                INSERT INTO pilgrim.aria_skills (user_id)
                VALUES (%s)
                ON CONFLICT (user_id) DO NOTHING
            """, (user_id,))

            # Add XP
            cur.execute(f"""
                UPDATE pilgrim.aria_skills
                SET {xp_col} = {xp_col} + %s, updated_at = NOW()
                WHERE user_id = %s
                RETURNING {xp_col}, {level_col}
            """, (xp_amount, user_id))
            row = cur.fetchone()

            # Check for level up (100 XP per level)
            new_xp = row[xp_col]
            current_level = row[level_col]
            new_level = max(1, min(100, 1 + new_xp // 100))

            if new_level > current_level:
                cur.execute(f"""
                    UPDATE pilgrim.aria_skills SET {level_col} = %s WHERE user_id = %s
                """, (new_level, user_id))
                return {'xp': new_xp, 'level': new_level, 'leveled_up': True}

            return {'xp': new_xp, 'level': current_level, 'leveled_up': False}
    except Exception as e:
        logger.error(f"Failed to add ARIA skill XP: {e}")
        return {'xp': 0, 'level': 1, 'leveled_up': False}


def use_aria_resonance(user_id: int, destination_name: str) -> dict:
    """Use ARIA's daily resonance ability to boost a trail by +2"""
    from datetime import datetime
    try:
        # Avoid circular import — crew.ensure_crew_missions_schema ensures mission columns on users
        from utilities.postgres.trails.crew import ensure_crew_missions_schema
        ensure_crew_missions_schema()
        now = datetime.utcnow()

        with db_cursor(commit=True) as cur:
            # Check cooldown
            cur.execute("""
                SELECT aria_last_resonance FROM pilgrim.users WHERE id = %s
            """, (user_id,))
            row = cur.fetchone()
            if row and row['aria_last_resonance']:
                seconds_since = (now - row['aria_last_resonance']).total_seconds()
                if seconds_since < 86400:  # 24 hours
                    hours_remaining = (86400 - seconds_since) / 3600
                    return {'success': False, 'error': f'ARIA resonance on cooldown ({hours_remaining:.1f}h remaining)'}

            # Update cooldown
            cur.execute("""
                UPDATE pilgrim.users SET aria_last_resonance = %s WHERE id = %s
            """, (now, user_id))

            # Increment trail by 2 (ARIA bonus) — always applies to HOME segment
            ensure_trail_segments_table()
            cur.execute("""
                INSERT INTO pilgrim.trail_segments (user_id, from_landmark, destination_name, trip_count, trail_level, last_used_at)
                VALUES (%s, 'HOME', %s, 2, 'marked', NOW())
                ON CONFLICT (user_id, from_landmark, destination_name)
                DO UPDATE SET trip_count = pilgrim.trail_segments.trip_count + 2,
                              last_used_at = NOW()
                RETURNING trip_count
            """, (user_id, destination_name))
            row = cur.fetchone()
            new_count = row['trip_count']
            new_level = get_trail_level_from_count(new_count)
            cur.execute("""
                UPDATE pilgrim.trail_segments SET trail_level = %s
                WHERE user_id = %s AND from_landmark = 'HOME' AND destination_name = %s
            """, (new_level, user_id, destination_name))

            # Also add km (resonance gives ~1 base session worth of trail progress)
            from config_shop import BASE_TRAIL_RATE_KMH
            resonance_km = BASE_TRAIL_RATE_KMH * (15 / 60)  # Base rate × 15min session
            # Get total_distance_km for the trail segment
            cur.execute("""
                SELECT total_distance_km FROM pilgrim.trail_segments
                WHERE user_id = %s AND from_landmark = 'HOME' AND destination_name = %s
            """, (user_id, destination_name))
            seg = cur.fetchone()
            seg_dist = float(seg['total_distance_km']) if seg and seg['total_distance_km'] else None

        # Add km outside the main transaction (same pattern as complete_crew_mission)
        if seg_dist:
            add_km_to_trail(user_id, destination_name, resonance_km, 'aria', seg_dist, 'HOME')

        with db_cursor(commit=True) as cur:
            # Log the resonance
            cur.execute("""
                INSERT INTO pilgrim.crew_missions (user_id, crew_member, mission_type, destination_name, started_at, completed_at, trip_count_added)
                VALUES (%s, 'aria', 'resonance', %s, %s, %s, 2)
            """, (user_id, destination_name, now, now))
            from utilities.postgres.activity import log_activity
            log_activity(user_id, 'trail', 'trail_resonance', f"ARIA Resonance: {destination_name}",
                         detail=f"+{resonance_km:.2f}km · Trail Lv{new_level} · {new_count} trips", source_table='crew_missions')

        return {
            'success': True,
            'destination': destination_name,
            'trip_count_added': 2,
            'km_added': round(resonance_km, 4),
            'trail': {'destination_name': destination_name, 'trip_count': new_count, 'trail_level': new_level}
        }
    except Exception as e:
        logger.error(f"Failed to use ARIA resonance: {e}")
        return {'success': False, 'error': str(e)}
