"""Trail segments, crew missions, and ARIA skill database operations."""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

from utilities.postgres_utils import db_cursor, _fetchone, _fetchall

logger = logging.getLogger(__name__)

_trail_schema_ensured = False


# ============================================================================
# TRAIL SEGMENTS: Track repeated trips to build speed bonuses
# ============================================================================

def ensure_trail_segments_table():
    """Create trail_segments table if it doesn't exist, with chain routing support."""
    global _trail_schema_ensured
    if _trail_schema_ensured:
        return
    _trail_schema_ensured = True

    with db_cursor(commit=True) as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pilgrim.trail_segments (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                from_landmark TEXT DEFAULT 'HOME',
                destination_name TEXT NOT NULL,
                trip_count INTEGER DEFAULT 0,
                trail_level TEXT DEFAULT 'none',
                last_used_at TIMESTAMP DEFAULT NOW(),
                created_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(user_id, from_landmark, destination_name)
            )
        """)

    # Migration: add from_landmark column if table existed before chain routing
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("ALTER TABLE pilgrim.trail_segments ADD COLUMN IF NOT EXISTS from_landmark TEXT DEFAULT 'HOME'")
    except Exception:
        pass

    # Migration: update unique constraint from (user_id, destination_name) to (user_id, from_landmark, destination_name)
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("ALTER TABLE pilgrim.trail_segments DROP CONSTRAINT IF EXISTS trail_segments_user_id_destination_name_key")
    except Exception:
        pass
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                DO $$ BEGIN
                    ALTER TABLE pilgrim.trail_segments
                    ADD CONSTRAINT trail_segments_chain_unique UNIQUE(user_id, from_landmark, destination_name);
                EXCEPTION WHEN duplicate_table THEN NULL;
                END $$;
            """)
    except Exception:
        pass

def get_user_trail(user_id: int, destination_name: str, from_landmark: str = 'HOME') -> dict:
    """Get trail data for a specific route segment, including km-based progress"""
    default = {
        'from_landmark': from_landmark, 'destination_name': destination_name,
        'trip_count': 0, 'trail_level': 'none',
        'total_distance_km': None, 'km_built': 0, 'captain_km': 0, 'scientist_km': 0, 'aria_km': 0
    }
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT from_landmark, destination_name, trip_count, trail_level, last_used_at,
                       total_distance_km, km_built, captain_km, scientist_km, aria_km
                FROM pilgrim.trail_segments
                WHERE user_id = %s AND from_landmark = %s AND destination_name = %s
            """, (user_id, from_landmark, destination_name))
            row = cur.fetchone()
            return dict(row) if row else default
    except Exception:
        return default

def increment_user_trail(user_id: int, destination_name: str, from_landmark: str = 'HOME') -> dict:
    """Increment trip count for a route segment and update trail level."""
    from utilities.expedition_utils import get_trail_level_from_count
    try:
        ensure_trail_segments_table()
        with db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO pilgrim.trail_segments (user_id, from_landmark, destination_name, trip_count, trail_level, last_used_at)
                VALUES (%s, %s, %s, 1, 'marked', NOW())
                ON CONFLICT (user_id, from_landmark, destination_name)
                DO UPDATE SET trip_count = pilgrim.trail_segments.trip_count + 1,
                              last_used_at = NOW()
                RETURNING trip_count
            """, (user_id, from_landmark, destination_name))
            row = cur.fetchone()
            new_count = row['trip_count']
            new_level = get_trail_level_from_count(new_count)
            cur.execute("""
                UPDATE pilgrim.trail_segments SET trail_level = %s
                WHERE user_id = %s AND from_landmark = %s AND destination_name = %s
            """, (new_level, user_id, from_landmark, destination_name))
        return {'destination_name': destination_name, 'trip_count': new_count, 'trail_level': new_level}
    except Exception as e:
        logger.error(f"Failed to increment trail: {e}")
        return {'destination_name': destination_name, 'trip_count': 0, 'trail_level': 'none'}

def get_user_trails(user_id: int) -> list:
    """Get all trails for a user (for map visualization)"""
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT from_landmark, destination_name, trip_count, trail_level, last_used_at,
                       total_distance_km, km_built, captain_km, scientist_km, aria_km
                FROM pilgrim.trail_segments
                WHERE user_id = %s AND (trip_count > 0 OR km_built > 0)
                ORDER BY km_built DESC, trip_count DESC
            """, (user_id,))
            return cur.fetchall() or []
    except Exception:
        return []


# ============================================================================
# KM-BASED TRAIL BUILDING SYSTEM
# ============================================================================

def add_km_to_trail(user_id: int, destination_name: str, km_amount: float,
                    worker_type: str, total_distance_km: float = None,
                    from_landmark: str = 'HOME') -> dict:
    """
    Add km progress to a trail segment.

    Args:
        user_id: User ID
        destination_name: Landmark name (endpoint)
        km_amount: How much km to add
        worker_type: 'captain', 'scientist', or 'aria'
        total_distance_km: Segment distance (required for new trails)
        from_landmark: Origin node for this segment (default 'HOME')
    """
    try:
        km_column = f"{worker_type}_km"
        if km_column not in ('captain_km', 'scientist_km', 'aria_km'):
            raise ValueError(f"Invalid worker_type: {worker_type}")

        with db_cursor(commit=True) as cur:
            cur.execute("""
                SELECT total_distance_km, km_built FROM pilgrim.trail_segments
                WHERE user_id = %s AND from_landmark = %s AND destination_name = %s
            """, (user_id, from_landmark, destination_name))
            existing = cur.fetchone()

            if existing:
                cur.execute(f"""
                    UPDATE pilgrim.trail_segments
                    SET km_built = COALESCE(km_built, 0) + %s,
                        {km_column} = COALESCE({km_column}, 0) + %s,
                        last_used_at = NOW(),
                        total_distance_km = COALESCE(total_distance_km, %s)
                    WHERE user_id = %s AND from_landmark = %s AND destination_name = %s
                    RETURNING *
                """, (km_amount, km_amount, total_distance_km, user_id, from_landmark, destination_name))
            else:
                if not total_distance_km:
                    raise ValueError("total_distance_km required for new trails")
                cur.execute(f"""
                    INSERT INTO pilgrim.trail_segments
                    (user_id, from_landmark, destination_name, total_distance_km, km_built, {km_column}, trip_count, trail_level)
                    VALUES (%s, %s, %s, %s, %s, %s, 0, 'none')
                    RETURNING *
                """, (user_id, from_landmark, destination_name, total_distance_km, km_amount, km_amount))

            row = cur.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"Failed to add km to trail: {e}")
        return None


def get_trail_progress(user_id: int, destination_name: str, from_landmark: str = 'HOME') -> dict:
    """Get detailed trail progress for a segment"""
    trail = get_user_trail(user_id, destination_name, from_landmark)

    km_built = trail.get('km_built') or 0
    total = trail.get('total_distance_km') or 0

    if total > 0:
        percent = round((km_built / total) * 100, 1)
        speed_mult = 1.0 + (min(1.0, km_built / total) * 0.5)
    else:
        percent = 0
        speed_mult = 1.0

    return {
        'from_landmark': from_landmark,
        'destination_name': destination_name,
        'km_built': round(km_built, 3),
        'total_distance_km': total,
        'percent_complete': percent,
        'speed_mult': round(speed_mult, 3),
        'captain_km': round(trail.get('captain_km') or 0, 3),
        'scientist_km': round(trail.get('scientist_km') or 0, 3),
        'aria_km': round(trail.get('aria_km') or 0, 3),
        'trip_count': trail.get('trip_count', 0),
        'trail_level': trail.get('trail_level', 'none')
    }


def find_nearest_trail_origin(user_id: int, destination_name: str) -> dict:
    """Find the nearest connected node in the user's trail network to build FROM.

    Connected nodes = HOME + any landmark that is a destination of an existing trail.
    Returns the closest connected node and the segment distance to the target.
    """
    from utilities.mars_math import haversine_distance
    ensure_trail_segments_table()  # Ensure from_landmark column exists
    try:
        with db_cursor() as cur:
            # Get user's base coordinates
            cur.execute("SELECT home_mars_lat, home_mars_lon FROM pilgrim.users WHERE id = %s", (user_id,))
            user = cur.fetchone()
            if not user or not user['home_mars_lat']:
                return {'from_landmark': 'HOME', 'segment_distance_km': 0}

            base_lat = float(user['home_mars_lat'])
            base_lon = float(user['home_mars_lon'])

            # Get destination coordinates
            cur.execute("SELECT latitude, longitude FROM pilgrim.mars_mappings WHERE name = %s", (destination_name,))
            dest = cur.fetchone()
            if not dest:
                return {'from_landmark': 'HOME', 'segment_distance_km': 0}

            dest_lat = float(dest['latitude'])
            dest_lon = float(dest['longitude'])

            # Start with HOME as best option
            home_dist = haversine_distance(base_lat, base_lon, dest_lat, dest_lon)
            best_from = 'HOME'
            best_dist = home_dist
            best_lat = base_lat
            best_lon = base_lon

            # Get all landmarks reachable via COMPLETED trails (connected nodes)
            # Only fully-built trails count — partial progress doesn't open new origins
            cur.execute("""
                SELECT DISTINCT t.destination_name, m.latitude, m.longitude
                FROM pilgrim.trail_segments t
                JOIN pilgrim.mars_mappings m ON m.name = t.destination_name
                WHERE t.user_id = %s AND t.km_built > 0
                  AND t.km_built >= t.total_distance_km AND t.total_distance_km > 0
                  AND t.destination_name != %s
            """, (user_id, destination_name))
            connected_nodes = cur.fetchall() or []

            for node in connected_nodes:
                node_lat = float(node['latitude'])
                node_lon = float(node['longitude'])
                dist = haversine_distance(node_lat, node_lon, dest_lat, dest_lon)
                if dist < best_dist:
                    best_from = node['destination_name']
                    best_dist = dist
                    best_lat = node_lat
                    best_lon = node_lon

            return {
                'from_landmark': best_from,
                'from_latitude': best_lat,
                'from_longitude': best_lon,
                'segment_distance_km': round(best_dist, 2),
                'home_distance_km': round(home_dist, 2),
            }
    except Exception as e:
        logger.error(f"Failed to find nearest trail origin: {e}")
        return {'from_landmark': 'HOME', 'segment_distance_km': 0}


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


# ============================================================================
# CREW MISSIONS: Quick trail-building activities for captain/scientist
# ============================================================================

def ensure_crew_missions_schema():
    """Add crew mission columns to users table and create missions log table"""
    # Add mission tracking columns to users table (each in separate transaction)
    columns_to_add = [
        ("captain_mission_ends_at", "TIMESTAMP"),
        ("captain_mission_target", "TEXT"),
        ("scientist_mission_ends_at", "TIMESTAMP"),
        ("scientist_mission_target", "TEXT"),
        ("aria_last_resonance", "TIMESTAMP"),
        ("captain_logistics_xp", "INTEGER DEFAULT 0"),
        ("scientist_navigation_xp", "INTEGER DEFAULT 0"),
        # ARIA mission tracking (same pattern as captain/scientist)
        ("aria_mission_ends_at", "TIMESTAMP"),
        ("aria_mission_target", "TEXT"),
        # Trail session data (km to add when mission completes)
        ("captain_mission_km", "FLOAT DEFAULT 0"),
        ("scientist_mission_km", "FLOAT DEFAULT 0"),
        ("aria_mission_km", "FLOAT DEFAULT 0"),
        # Chain routing: origin landmark for active trail missions
        ("captain_mission_from", "TEXT DEFAULT 'HOME'"),
        ("scientist_mission_from", "TEXT DEFAULT 'HOME'"),
        ("aria_mission_from", "TEXT DEFAULT 'HOME'"),
    ]
    for col_name, col_type in columns_to_add:
        try:
            with db_cursor(commit=True) as cur:
                cur.execute(f"""
                    ALTER TABLE pilgrim.users ADD COLUMN IF NOT EXISTS {col_name} {col_type};
                """)
        except Exception:
            pass  # Column already exists or other error

    # Create missions log table
    with db_cursor(commit=True) as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pilgrim.crew_missions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                crew_member TEXT NOT NULL,
                mission_type TEXT NOT NULL,
                destination_name TEXT NOT NULL,
                started_at TIMESTAMP DEFAULT NOW(),
                completed_at TIMESTAMP,
                trip_count_added INTEGER DEFAULT 1,
                xp_gained INTEGER DEFAULT 0,
                narrative TEXT
            )
        """)


def get_crew_mission_status(user_id: int) -> dict:
    """Get current mission status for captain, scientist, and ARIA"""
    try:
        ensure_crew_missions_schema()
        with db_cursor() as cur:
            cur.execute("""
                SELECT captain_mission_ends_at, captain_mission_target, captain_mission_km, captain_mission_from,
                       scientist_mission_ends_at, scientist_mission_target, scientist_mission_km, scientist_mission_from,
                       aria_mission_ends_at, aria_mission_target, aria_mission_km, aria_mission_from,
                       aria_last_resonance,
                       captain_logistics_xp, scientist_navigation_xp
                FROM pilgrim.users WHERE id = %s
            """, (user_id,))
            row = cur.fetchone()
            if not row:
                return {'captain': None, 'scientist': None, 'aria': None}

            from datetime import datetime
            now = datetime.utcnow()

            # Captain status
            cap_ends = row.get('captain_mission_ends_at')
            cap_busy = cap_ends and cap_ends > now
            cap_complete = cap_ends and cap_ends <= now and row.get('captain_mission_target')

            # Scientist status
            sci_ends = row.get('scientist_mission_ends_at')
            sci_busy = sci_ends and sci_ends > now
            sci_complete = sci_ends and sci_ends <= now and row.get('scientist_mission_target')

            # ARIA status
            aria_ends = row.get('aria_mission_ends_at')
            aria_busy = aria_ends and aria_ends > now
            aria_complete = aria_ends and aria_ends <= now and row.get('aria_mission_target')

            return {
                'captain': {
                    'busy': cap_busy,
                    'complete': cap_complete,
                    'ends_at': cap_ends.isoformat() if cap_ends else None,
                    'target': row.get('captain_mission_target'),
                    'from_landmark': row.get('captain_mission_from') or 'HOME',
                    'km_pending': row.get('captain_mission_km') or 0,
                    'xp': row.get('captain_logistics_xp') or 0,
                },
                'scientist': {
                    'busy': sci_busy,
                    'complete': sci_complete,
                    'ends_at': sci_ends.isoformat() if sci_ends else None,
                    'target': row.get('scientist_mission_target'),
                    'from_landmark': row.get('scientist_mission_from') or 'HOME',
                    'km_pending': row.get('scientist_mission_km') or 0,
                    'xp': row.get('scientist_navigation_xp') or 0,
                },
                'aria': {
                    'busy': aria_busy,
                    'complete': aria_complete,
                    'ends_at': aria_ends.isoformat() if aria_ends else None,
                    'target': row.get('aria_mission_target'),
                    'from_landmark': row.get('aria_mission_from') or 'HOME',
                    'km_pending': row.get('aria_mission_km') or 0,
                },
                # Legacy cooldown (kept for compatibility)
                'aria_cooldown': {
                    'available': not aria_busy and not aria_complete,
                    'last_used': row.get('aria_last_resonance').isoformat() if row.get('aria_last_resonance') else None,
                }
            }
    except Exception as e:
        logger.error(f"Failed to get crew mission status: {e}")
        return {'captain': None, 'scientist': None, 'aria': None}


def start_crew_mission(user_id: int, crew_member: str, destination_name: str,
                       duration_minutes: int, km_to_add: float = 0,
                       from_landmark: str = 'HOME') -> dict:
    """Start a trail building mission for captain, scientist, or ARIA.

    Args:
        user_id: The user
        crew_member: 'captain', 'scientist', or 'aria'
        destination_name: Where they're building trail to
        duration_minutes: How long the session is (3, 5, 10, or 15)
        km_to_add: Pre-calculated km that will be added when mission completes
        from_landmark: Origin node for this trail segment
    """
    from datetime import datetime, timedelta
    try:
        ensure_crew_missions_schema()
        now = datetime.utcnow()
        ends_at = now + timedelta(minutes=duration_minutes)

        with db_cursor(commit=True) as cur:
            if crew_member == 'captain':
                cur.execute("""
                    UPDATE pilgrim.users
                    SET captain_mission_ends_at = %s, captain_mission_target = %s,
                        captain_mission_km = %s, captain_mission_from = %s
                    WHERE id = %s
                """, (ends_at, destination_name, km_to_add, from_landmark, user_id))
            elif crew_member == 'scientist':
                cur.execute("""
                    UPDATE pilgrim.users
                    SET scientist_mission_ends_at = %s, scientist_mission_target = %s,
                        scientist_mission_km = %s, scientist_mission_from = %s
                    WHERE id = %s
                """, (ends_at, destination_name, km_to_add, from_landmark, user_id))
            elif crew_member == 'aria':
                cur.execute("""
                    UPDATE pilgrim.users
                    SET aria_mission_ends_at = %s, aria_mission_target = %s,
                        aria_mission_km = %s, aria_mission_from = %s
                    WHERE id = %s
                """, (ends_at, destination_name, km_to_add, from_landmark, user_id))
            else:
                return {'success': False, 'error': 'Invalid crew member'}

            # Log the mission start
            cur.execute("""
                INSERT INTO pilgrim.crew_missions (user_id, crew_member, mission_type, destination_name, started_at)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
            """, (user_id, crew_member, 'trail_building', destination_name, now))
            from utilities.db_activity import log_activity
            log_activity(user_id, 'trail', 'trail_mission_start', f"Trail Mission: {destination_name}",
                         detail=f"{crew_member} · {km_to_add:.1f} km", source_table='crew_missions',
                         metadata={'crew_member': crew_member, 'km_to_add': km_to_add, 'duration_minutes': duration_minutes})

        return {
            'success': True,
            'crew_member': crew_member,
            'from_landmark': from_landmark,
            'destination': destination_name,
            'ends_at': ends_at.isoformat(),
            'duration_minutes': duration_minutes,
            'km_to_add': km_to_add
        }
    except Exception as e:
        logger.error(f"Failed to start crew mission: {e}")
        return {'success': False, 'error': str(e)}


def complete_crew_mission(user_id: int, crew_member: str) -> dict:
    """Complete a trail building mission and award XP + km built"""
    from datetime import datetime
    try:
        ensure_crew_missions_schema()
        now = datetime.utcnow()
        from_landmark = 'HOME'

        with db_cursor(commit=True) as cur:
            # Get current mission info based on crew member
            if crew_member == 'captain':
                cur.execute("""
                    SELECT captain_mission_ends_at, captain_mission_target, captain_mission_km,
                           captain_logistics_xp, captain_mission_from
                    FROM pilgrim.users WHERE id = %s
                """, (user_id,))
                row = cur.fetchone()
                if not row or not row.get('captain_mission_target'):
                    return {'success': False, 'error': 'No active captain mission'}
                if row.get('captain_mission_ends_at') and row['captain_mission_ends_at'] > now:
                    return {'success': False, 'error': 'Mission not yet complete'}

                destination = row['captain_mission_target']
                km_to_add = row.get('captain_mission_km') or 0
                from_landmark = row.get('captain_mission_from') or 'HOME'
                current_xp = row.get('captain_logistics_xp') or 0
                xp_gain = 5

                cur.execute("""
                    UPDATE pilgrim.users
                    SET captain_mission_ends_at = NULL, captain_mission_target = NULL,
                        captain_mission_km = 0, captain_mission_from = 'HOME',
                        captain_logistics_xp = %s
                    WHERE id = %s
                """, (current_xp + xp_gain, user_id))

            elif crew_member == 'scientist':
                cur.execute("""
                    SELECT scientist_mission_ends_at, scientist_mission_target, scientist_mission_km,
                           scientist_navigation_xp, scientist_mission_from
                    FROM pilgrim.users WHERE id = %s
                """, (user_id,))
                row = cur.fetchone()
                if not row or not row.get('scientist_mission_target'):
                    return {'success': False, 'error': 'No active scientist mission'}
                if row.get('scientist_mission_ends_at') and row['scientist_mission_ends_at'] > now:
                    return {'success': False, 'error': 'Mission not yet complete'}

                destination = row['scientist_mission_target']
                km_to_add = row.get('scientist_mission_km') or 0
                from_landmark = row.get('scientist_mission_from') or 'HOME'
                current_xp = row.get('scientist_navigation_xp') or 0
                xp_gain = 5

                cur.execute("""
                    UPDATE pilgrim.users
                    SET scientist_mission_ends_at = NULL, scientist_mission_target = NULL,
                        scientist_mission_km = 0, scientist_mission_from = 'HOME',
                        scientist_navigation_xp = %s
                    WHERE id = %s
                """, (current_xp + xp_gain, user_id))

            elif crew_member == 'aria':
                cur.execute("""
                    SELECT aria_mission_ends_at, aria_mission_target, aria_mission_km, aria_mission_from
                    FROM pilgrim.users WHERE id = %s
                """, (user_id,))
                row = cur.fetchone()
                if not row or not row.get('aria_mission_target'):
                    return {'success': False, 'error': 'No active ARIA mission'}
                if row.get('aria_mission_ends_at') and row['aria_mission_ends_at'] > now:
                    return {'success': False, 'error': 'Mission not yet complete'}

                destination = row['aria_mission_target']
                km_to_add = row.get('aria_mission_km') or 0
                from_landmark = row.get('aria_mission_from') or 'HOME'
                current_xp = 0
                xp_gain = 5

                cur.execute("""
                    UPDATE pilgrim.users
                    SET aria_mission_ends_at = NULL, aria_mission_target = NULL,
                        aria_mission_km = 0, aria_mission_from = 'HOME'
                    WHERE id = %s
                """, (user_id,))

                add_aria_skill_xp(user_id, 'resonance', xp_gain)
            else:
                return {'success': False, 'error': 'Invalid crew member'}

            # Update mission log
            cur.execute("""
                UPDATE pilgrim.crew_missions
                SET completed_at = %s, xp_gained = %s
                WHERE id = (
                    SELECT id FROM pilgrim.crew_missions
                    WHERE user_id = %s AND crew_member = %s AND completed_at IS NULL
                    ORDER BY started_at DESC LIMIT 1
                )
            """, (now, xp_gain, user_id, crew_member))

        # Add km to trail segment (outside the transaction to avoid issues)
        trail_result = None
        if km_to_add > 0:
            from utilities.mars_math import haversine_distance
            with db_cursor() as cur:
                # Get destination coords
                cur.execute("SELECT latitude, longitude FROM pilgrim.mars_mappings WHERE name = %s", (destination,))
                dest_coords = cur.fetchone()

                if from_landmark == 'HOME':
                    # Distance from base to destination
                    cur.execute("SELECT home_mars_lat, home_mars_lon FROM pilgrim.users WHERE id = %s", (user_id,))
                    user = cur.fetchone()
                    if user and dest_coords:
                        distance_km = haversine_distance(
                            float(user['home_mars_lat']), float(user['home_mars_lon']),
                            float(dest_coords['latitude']), float(dest_coords['longitude']))
                    else:
                        distance_km = 100
                else:
                    # Distance from origin landmark to destination
                    cur.execute("SELECT latitude, longitude FROM pilgrim.mars_mappings WHERE name = %s", (from_landmark,))
                    from_coords = cur.fetchone()
                    if from_coords and dest_coords:
                        distance_km = haversine_distance(
                            float(from_coords['latitude']), float(from_coords['longitude']),
                            float(dest_coords['latitude']), float(dest_coords['longitude']))
                    else:
                        distance_km = 100

            trail_result = add_km_to_trail(user_id, destination, km_to_add, crew_member, distance_km, from_landmark)
            if trail_result:
                trail_result = get_trail_progress(user_id, destination, from_landmark)

                # Check if trail just completed — spawn next dot
                if (trail_result.get('km_built', 0) >= trail_result.get('total_distance_km', 0)
                        and trail_result.get('total_distance_km', 0) > 0):
                    next_trail = spawn_next_trail(user_id, destination)
                    if next_trail:
                        trail_result['completed'] = True
                        trail_result['next_trail'] = next_trail.get('destination_name')

        return {
            'success': True,
            'crew_member': crew_member,
            'from_landmark': from_landmark,
            'destination': destination,
            'km_added': km_to_add,
            'xp_gained': xp_gain,
            'new_xp_total': current_xp + xp_gain,
            'trail': trail_result
        }
    except Exception as e:
        logger.error(f"Failed to complete crew mission: {e}")
        return {'success': False, 'error': str(e)}


def get_trail_consumable_discoveries(user_id: int) -> list:
    """
    Get claimed discoveries that can be consumed for trail building bonuses.
    Returns ONLY common/uncommon biological and mineral items - NOT rare/legendary.
    Rare artifacts and legendary finds are too valuable to grind up for road fill!
    """
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT ed.id, ed.quantity, di.item_name, di.item_type,
                       di.rarity, di.image_url
                FROM pilgrim.expedition_discoveries ed
                JOIN pilgrim.discovery_items di ON ed.discovery_item_id = di.id
                JOIN pilgrim.expeditions e ON ed.expedition_id = e.id
                WHERE e.user_id = %s
                  AND ed.claimed_by_user = true
                  AND (ed.analyzed = false OR ed.analyzed IS NULL)
                  AND di.item_type IN ('biological', 'mineral')
                  AND di.rarity IN ('common', 'uncommon')
                ORDER BY di.item_type, di.item_name
            """, (user_id,))
            return [dict(row) for row in cur.fetchall()]
    except Exception as e:
        logger.error(f"Failed to get trail consumables: {e}")
        return []


def consume_discovery_for_trail(user_id: int, discovery_id: int) -> dict:
    """
    Consume a discovery item for trail building bonus.
    Marks the item as analyzed (destroyed) and returns the bonus to apply.
    Only common/uncommon biological/mineral items can be consumed.
    """
    from config import TRAIL_CONSUMABLE_BONUSES

    try:
        # Verify ownership, item type, and rarity restrictions
        with db_cursor() as cur:
            cur.execute("""
                SELECT ed.id, di.item_name, di.item_type, di.rarity
                FROM pilgrim.expedition_discoveries ed
                JOIN pilgrim.discovery_items di ON ed.discovery_item_id = di.id
                JOIN pilgrim.expeditions e ON ed.expedition_id = e.id
                WHERE ed.id = %s AND e.user_id = %s
                  AND ed.claimed_by_user = true
                  AND (ed.analyzed = false OR ed.analyzed IS NULL)
                  AND di.item_type IN ('biological', 'mineral')
                  AND di.rarity IN ('common', 'uncommon')
            """, (discovery_id, user_id))
            row = cur.fetchone()

        if not row:
            return {'success': False, 'error': 'Item not found, already used, or not consumable'}

        # Calculate bonus based on item type and name keywords
        item_type = row['item_type']
        item_name = row['item_name'].lower()
        type_bonuses = TRAIL_CONSUMABLE_BONUSES.get(item_type, {})
        bonus = type_bonuses.get('default', 0.05)

        # Check for specific keyword matches (higher bonuses)
        for keyword, val in type_bonuses.items():
            if keyword != 'default' and keyword in item_name:
                bonus = val
                break

        # Consume one unit: decrement quantity if > 1, otherwise mark fully analyzed
        with db_cursor(commit=True) as cur:
            cur.execute("SELECT quantity FROM pilgrim.expedition_discoveries WHERE id = %s", (discovery_id,))
            qty_row = cur.fetchone()
            current_qty = qty_row['quantity'] if qty_row else 1

            if current_qty > 1:
                cur.execute("""
                    UPDATE pilgrim.expedition_discoveries
                    SET quantity = quantity - 1
                    WHERE id = %s
                """, (discovery_id,))
            else:
                cur.execute("""
                    UPDATE pilgrim.expedition_discoveries
                    SET analyzed = true, analyzed_at = NOW()
                    WHERE id = %s
                """, (discovery_id,))

        logger.info(f"User {user_id} consumed {row['item_name']} for trail building (+{int(bonus*100)}%)")

        return {
            'success': True,
            'item_name': row['item_name'],
            'item_type': item_type,
            'bonus': bonus,
            'bonus_percent': int(bonus * 100)
        }
    except Exception as e:
        logger.error(f"Failed to consume discovery for trail: {e}")
        return {'success': False, 'error': str(e)}


def use_aria_resonance(user_id: int, destination_name: str) -> dict:
    """Use ARIA's daily resonance ability to boost a trail by +2"""
    from datetime import datetime
    from utilities.expedition_utils import get_trail_level_from_count
    try:
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

            # Log the resonance
            cur.execute("""
                INSERT INTO pilgrim.crew_missions (user_id, crew_member, mission_type, destination_name, started_at, completed_at, trip_count_added)
                VALUES (%s, 'aria', 'resonance', %s, %s, %s, 2)
            """, (user_id, destination_name, now, now))
            from utilities.db_activity import log_activity
            log_activity(user_id, 'trail', 'trail_resonance', f"ARIA Resonance: {destination_name}",
                         detail=f"Trail Lv{new_level} · {new_count} trips", source_table='crew_missions')

        return {
            'success': True,
            'destination': destination_name,
            'trip_count_added': 2,
            'trail': {'destination_name': destination_name, 'trip_count': new_count, 'trail_level': new_level}
        }
    except Exception as e:
        logger.error(f"Failed to use ARIA resonance: {e}")
        return {'success': False, 'error': str(e)}


def get_nearby_trails_for_missions(user_id: int, max_distance_km: float = 50.0) -> list:
    """DEPRECATED: Use get_visited_sites_for_trails instead"""
    return get_visited_sites_for_trails(user_id)


def get_visited_sites_for_trails(user_id: int, frontier_limit: int = 5) -> list:
    """Get exactly 4 active trail destinations for trail construction.

    Always returns up to 4 trails — the user's active trail_segments from HOME.
    If fewer than 4 exist in DB, fills remaining slots with the closest unstarted
    landmarks from mars_mappings (auto-creating trail_segments for them).

    When a trail is completed (km_built >= total_distance_km), it chains to the
    next closest landmark in that direction via spawn_next_trail().
    """
    from utilities.mars_math import haversine_distance
    ensure_trail_segments_table()
    try:
        with db_cursor() as cur:
            cur.execute("SELECT home_mars_lat, home_mars_lon FROM pilgrim.users WHERE id = %s", (user_id,))
            user = cur.fetchone()
            if not user or not user['home_mars_lat']:
                return []

            base_lat = float(user['home_mars_lat'])
            base_lon = float(user['home_mars_lon'])

            # Get user's active trail segments (all from HOME for now)
            cur.execute("""
                SELECT ts.from_landmark, ts.destination_name, ts.km_built, ts.captain_km,
                       ts.scientist_km, ts.aria_km, ts.trip_count, ts.trail_level,
                       ts.total_distance_km, m.type, m.latitude, m.longitude
                FROM pilgrim.trail_segments ts
                JOIN pilgrim.mars_mappings m ON m.name = ts.destination_name
                WHERE ts.user_id = %s
                  AND (ts.km_built < ts.total_distance_km OR ts.total_distance_km IS NULL)
                ORDER BY ts.total_distance_km ASC NULLS LAST
            """, (user_id,))
            active_trails = [dict(r) for r in (cur.fetchall() or [])]

        # If we have 4+ active trails, return them
        if len(active_trails) >= 4:
            return _format_trail_sites(active_trails[:4], base_lat, base_lon)

        # Fill remaining slots with closest unstarted landmarks
        active_dests = {t['destination_name'] for t in active_trails}
        # Also exclude completed trail destinations
        with db_cursor() as cur:
            cur.execute("""
                SELECT destination_name FROM pilgrim.trail_segments
                WHERE user_id = %s AND km_built >= total_distance_km AND total_distance_km > 0
            """, (user_id,))
            completed_dests = {r['destination_name'] for r in (cur.fetchall() or [])}

            cur.execute("SELECT name, type, latitude, longitude FROM pilgrim.mars_mappings")
            all_landmarks = cur.fetchall()

        exclude = active_dests | completed_dests
        candidates = []
        for lm in all_landmarks:
            if lm['name'] in exclude:
                continue
            d = haversine_distance(base_lat, base_lon, float(lm['latitude']), float(lm['longitude']))
            candidates.append({**dict(lm), 'distance': d})
        candidates.sort(key=lambda x: x['distance'])

        # Auto-create trail segments for the fill slots
        needed = 4 - len(active_trails)
        for c in candidates[:needed]:
            with db_cursor(commit=True) as cur:
                cur.execute("""
                    INSERT INTO pilgrim.trail_segments
                    (user_id, from_landmark, destination_name, total_distance_km,
                     km_built, captain_km, scientist_km, aria_km, trip_count, trail_level)
                    VALUES (%s, 'HOME', %s, %s, 0, 0, 0, 0, 0, 'none')
                    ON CONFLICT (user_id, from_landmark, destination_name) DO NOTHING
                """, (user_id, c['name'], round(c['distance'], 6)))
            active_trails.append({
                'from_landmark': 'HOME', 'destination_name': c['name'],
                'km_built': 0, 'captain_km': 0, 'scientist_km': 0, 'aria_km': 0,
                'trip_count': 0, 'trail_level': 'none',
                'total_distance_km': round(c['distance'], 6),
                'type': c['type'], 'latitude': c['latitude'], 'longitude': c['longitude'],
            })

        return _format_trail_sites(active_trails[:4], base_lat, base_lon)
    except Exception as e:
        logger.error(f"Failed to get visited sites for trails: {e}")
        return []


def _format_trail_sites(trails: list, base_lat: float, base_lon: float) -> list:
    """Format trail segment rows into the site dict format expected by the API."""
    from utilities.mars_math import haversine_distance
    results = []
    for t in trails:
        s_lat = float(t['latitude'])
        s_lon = float(t['longitude'])
        home_dist = haversine_distance(base_lat, base_lon, s_lat, s_lon)
        results.append({
            'name': t['destination_name'],
            'type': t.get('type', 'Crater, craters'),
            'latitude': s_lat,
            'longitude': s_lon,
            'visit_count': 0,
            'last_visited': None,
            'distance_km': round(home_dist, 2),
            'from_landmark': t.get('from_landmark', 'HOME'),
            'from_latitude': base_lat,
            'from_longitude': base_lon,
            'segment_distance_km': round(float(t.get('total_distance_km') or home_dist), 2),
            'km_built': float(t.get('km_built') or 0),
            'captain_km': float(t.get('captain_km') or 0),
            'scientist_km': float(t.get('scientist_km') or 0),
            'aria_km': float(t.get('aria_km') or 0),
            'trip_count': t.get('trip_count', 0),
            'trail_level': t.get('trail_level', 'none'),
        })
    results.sort(key=lambda s: s['segment_distance_km'])
    return results


def spawn_next_trail(user_id: int, completed_destination: str) -> Optional[dict]:
    """When a trail is completed, find the next closest landmark in that direction
    and create a new trail segment. Maintains exactly 4 active trails.

    The new trail starts from HOME (not from the completed destination) to keep
    the system simple — distances are always HOME-based.
    """
    from utilities.mars_math import haversine_distance
    try:
        with db_cursor() as cur:
            cur.execute("SELECT home_mars_lat, home_mars_lon FROM pilgrim.users WHERE id = %s", (user_id,))
            user = cur.fetchone()
            if not user or not user['home_mars_lat']:
                return None
            base_lat = float(user['home_mars_lat'])
            base_lon = float(user['home_mars_lon'])

            # Get all destinations already in trail_segments (active + completed)
            cur.execute("SELECT destination_name FROM pilgrim.trail_segments WHERE user_id = %s", (user_id,))
            existing = {r['destination_name'] for r in (cur.fetchall() or [])}

            # Find closest landmark not already a trail destination
            cur.execute("SELECT name, type, latitude, longitude FROM pilgrim.mars_mappings")
            all_landmarks = cur.fetchall()

        candidates = []
        for lm in all_landmarks:
            if lm['name'] in existing:
                continue
            d = haversine_distance(base_lat, base_lon, float(lm['latitude']), float(lm['longitude']))
            candidates.append({**dict(lm), 'distance': d})
        candidates.sort(key=lambda x: x['distance'])

        if not candidates:
            return None

        next_lm = candidates[0]
        with db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO pilgrim.trail_segments
                (user_id, from_landmark, destination_name, total_distance_km,
                 km_built, captain_km, scientist_km, aria_km, trip_count, trail_level)
                VALUES (%s, 'HOME', %s, %s, 0, 0, 0, 0, 0, 'none')
                ON CONFLICT (user_id, from_landmark, destination_name) DO NOTHING
                RETURNING *
            """, (user_id, next_lm['name'], round(next_lm['distance'], 6)))
            row = cur.fetchone()

        logger.info(f"Spawned next trail for user {user_id}: {completed_destination} -> {next_lm['name']} ({next_lm['distance']:.1f} km)")
        return dict(row) if row else None
    except Exception as e:
        logger.error(f"Failed to spawn next trail: {e}")
        return None
