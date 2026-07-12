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


def handle_resonance_request(user_id: int, data: dict) -> dict:
    """Route-glue wrapper for POST /api/aria/resonance.

    v3 (#1414): Resonance no longer takes a destination — it adds km to the
    captain's active chain. The `destination_name` arg is accepted for backward
    compat but ignored.
    """
    return use_aria_resonance(user_id, (data.get('destination_name') or '').strip() or None)


def use_aria_resonance(user_id: int, destination_name: str = None) -> dict:
    """v3 (#1414): ARIA Resonance adds a chunk of km to the user's active chain.

    `destination_name` arg is ignored — kept for back-compat. Resonance now
    targets the next unbuilt segment of `users.active_trail_direction`.
    """
    from datetime import datetime
    try:
        from utilities.postgres.trails.crew import ensure_crew_missions_schema
        from utilities.postgres.trails.chains import (
            ensure_user_trail_chains_table, add_km_to_active_chain,
        )
        ensure_crew_missions_schema()
        ensure_user_trail_chains_table()
        now = datetime.utcnow()

        with db_cursor(commit=True) as cur:
            cur.execute("SELECT aria_last_resonance FROM pilgrim.users WHERE id = %s", (user_id,))
            row = cur.fetchone()
            if row and row['aria_last_resonance']:
                seconds_since = (now - row['aria_last_resonance']).total_seconds()
                if seconds_since < 86400:
                    hours_remaining = (86400 - seconds_since) / 3600
                    return {'success': False, 'error': f'ARIA resonance on cooldown ({hours_remaining:.1f}h remaining)'}
            cur.execute("UPDATE pilgrim.users SET aria_last_resonance = %s WHERE id = %s", (now, user_id))

        # Resonance = one full bonus crew session at ARIA's total multiplier
        # (was base rate × 15min ≈ 0.19km — invisible next to 500-800km segments).
        # Reuses the same math as dispatched trail missions so stat/suit
        # investment scales resonance identically.
        from config_shop import calculate_trail_km
        from utilities.expeditions.trails import get_worker_trail_multiplier
        mult = get_worker_trail_multiplier(user_id, 'aria')
        resonance_km = calculate_trail_km(mult['total_multiplier'])['km_to_add']

        state = add_km_to_active_chain(user_id, resonance_km, 'aria')
        if not state:
            return {'success': False, 'error': 'No active chain segment to build (chain may be complete)'}

        with db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO pilgrim.crew_missions (user_id, crew_member, mission_type, destination_name, started_at, completed_at, trip_count_added)
                VALUES (%s, 'aria', 'resonance', %s, %s, %s, 0)
            """, (user_id, state.get('direction', '?'), now, now))
            from utilities.postgres.activity import log_activity
            log_activity(user_id, 'trail', 'trail_resonance',
                         f"ARIA Resonance: {state['direction']} chain seg {state['segment_index']}",
                         detail=f"+{state['km_added']:.2f}km", source_table='crew_missions')

        return {
            'success': True,
            'direction': state['direction'],
            'segment_index': state['segment_index'],
            'km_added': round(state['km_added'], 4),
            'completed': state['completed'],
        }
    except Exception as e:
        logger.error(f"Failed to use ARIA resonance: {e}")
        return {'success': False, 'error': str(e)}
