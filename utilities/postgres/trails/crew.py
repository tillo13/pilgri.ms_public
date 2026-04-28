"""Crew missions: schema, status, start/complete + trail consumables + nearby-sites."""

import logging

from utilities.postgres.core import db_cursor
from utilities.postgres.trails.segments import (
    ensure_trail_segments_table,
    add_km_to_trail,
    get_trail_progress,
)
from utilities.postgres.trails.aria_skills import add_aria_skill_xp

logger = logging.getLogger(__name__)


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
            from utilities.postgres.activity import log_activity
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


def handle_trail_complete_request(user_id: int, data: dict) -> dict:
    """Route-glue wrapper for POST /api/trail/complete.

    Validates worker_type and mission state before calling complete_crew_mission().
    """
    worker_type = (data.get('worker_type') or '').lower()
    if worker_type not in ('captain', 'scientist', 'aria'):
        return {'success': False, 'error': 'Invalid worker type'}

    status = get_crew_mission_status(user_id)
    member_status = status.get(worker_type) or {}

    if member_status.get('busy'):
        return {'success': False, 'error': f'{worker_type.title()} is still on mission'}
    if not member_status.get('complete') and not member_status.get('target'):
        return {'success': False, 'error': f'No mission to complete for {worker_type.title()}'}

    return complete_crew_mission(user_id, worker_type)


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
                add_aria_skill_xp(user_id, 'crystal_sensing', xp_gain)
                add_aria_skill_xp(user_id, 'lore_memory', xp_gain)
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

        # v3 (#1414): km goes to the captain's active chain segment, not a trail_segments row.
        chain_state = None
        if km_to_add > 0:
            from utilities.postgres.trails.chains import add_km_to_active_chain
            chain_state = add_km_to_active_chain(user_id, km_to_add, crew_member)

        return {
            'success': True,
            'crew_member': crew_member,
            'destination': destination,
            'km_added': km_to_add,
            'xp_gained': xp_gain,
            'new_xp_total': current_xp + xp_gain,
            'chain_state': chain_state,
            # back-compat for any frontend still reading 'trail'
            'trail': {
                'destination_name': chain_state['direction'] if chain_state else destination,
                'km_built': chain_state['km_built'] if chain_state else 0,
                'total_distance_km': chain_state['segment_distance_km'] if chain_state else 0,
                'completed': chain_state['completed'] if chain_state else False,
            } if chain_state else None,
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


def get_nearby_trails_for_missions(user_id: int, max_distance_km: float = 50.0) -> list:
    """DEPRECATED: Use get_visited_sites_for_trails instead"""
    return get_visited_sites_for_trails(user_id)


def get_visited_sites_for_trails(user_id: int, frontier_limit: int = 5) -> list:
    """v3 (#1414): return the 4 cardinal chains as 4 trail sites.

    Each "site" is the next unbuilt segment of one of the captain's chains
    (N/S/E/W). Plus completed segments returned for map rendering.
    """
    from utilities.postgres.trails.chains import (
        ensure_user_trail_chains_table, get_active_chain_segments, get_all_user_chains,
    )
    from utilities.postgres.map import get_mars_mappings_by_name
    ensure_user_trail_chains_table()
    try:
        with db_cursor() as cur:
            cur.execute("SELECT home_mars_lat, home_mars_lon FROM pilgrim.users WHERE id = %s", (user_id,))
            user = cur.fetchone()
            if not user or not user['home_mars_lat']:
                return []
            base_lat = float(user['home_mars_lat'])
            base_lon = float(user['home_mars_lon'])

        active = get_active_chain_segments(user_id)
        all_chains = get_all_user_chains(user_id)
        landmarks_by_name = get_mars_mappings_by_name()

        sites = []
        # 1 row per direction with the next unbuilt segment as the "trail site"
        for direction in ('N', 'E', 'S', 'W'):
            info = active.get(direction) or {}
            seg = info.get('next_unbuilt')
            if not seg:
                continue
            dest_name = seg['to_landmark']
            from_name = seg['from_landmark']
            dest_lm = landmarks_by_name.get(dest_name)
            if not dest_lm:
                continue
            dest_lat = float(dest_lm['latitude'])
            dest_lon = float(dest_lm['longitude'])
            if from_name == 'HOME':
                from_lat, from_lon = base_lat, base_lon
            else:
                from_lm = landmarks_by_name.get(from_name)
                from_lat = float(from_lm['latitude']) if from_lm else base_lat
                from_lon = float(from_lm['longitude']) if from_lm else base_lon
            seg_dist = float(seg['segment_distance_km'])
            km_built = float(seg['km_built'] or 0)
            sites.append({
                'name': dest_name,
                'type': dest_lm.get('type', 'Crater, craters'),
                'latitude': dest_lat,
                'longitude': dest_lon,
                'distance_km': round(seg_dist, 2),
                'from_landmark': from_name,
                'from_latitude': from_lat,
                'from_longitude': from_lon,
                'segment_distance_km': round(seg_dist, 2),
                'km_built': km_built,
                'is_complete': False,
                'captain_km': float(seg['captain_km'] or 0),
                'scientist_km': float(seg['scientist_km'] or 0),
                'aria_km': float(seg['aria_km'] or 0),
                'drone_km': float(seg['drone_km'] or 0),
                'robot_km': float(seg['robot_km'] or 0),
                'chain_direction': direction,
                'segment_index': seg['segment_index'],
                'chain_total_km': info.get('total_km'),
                'chain_km_built': info.get('km_built_total'),
                'chain_completed_segments': info.get('completed_segments'),
                'chain_total_segments': info.get('total_segments'),
                'chain_prestige_tier': info.get('prestige_tier'),
                'trail_level': seg.get('tier', 'none'),
            })
        # Completed segments — useful for map rendering
        for row in all_chains:
            if not row.get('completed_at'):
                continue
            dest_name = row['to_landmark']
            from_name = row['from_landmark']
            dest_lm = landmarks_by_name.get(dest_name)
            if not dest_lm:
                continue
            if from_name == 'HOME':
                from_lat, from_lon = base_lat, base_lon
            else:
                from_lm = landmarks_by_name.get(from_name)
                from_lat = float(from_lm['latitude']) if from_lm else base_lat
                from_lon = float(from_lm['longitude']) if from_lm else base_lon
            sites.append({
                'name': dest_name,
                'type': dest_lm.get('type', 'Crater, craters'),
                'latitude': float(dest_lm['latitude']),
                'longitude': float(dest_lm['longitude']),
                'distance_km': round(float(row['segment_distance_km']), 2),
                'from_landmark': from_name,
                'from_latitude': from_lat,
                'from_longitude': from_lon,
                'segment_distance_km': round(float(row['segment_distance_km']), 2),
                'km_built': float(row['km_built'] or 0),
                'is_complete': True,
                'captain_km': float(row['captain_km'] or 0),
                'scientist_km': float(row['scientist_km'] or 0),
                'aria_km': float(row['aria_km'] or 0),
                'drone_km': float(row['drone_km'] or 0),
                'robot_km': float(row['robot_km'] or 0),
                'chain_direction': row['direction'],
                'segment_index': row['segment_index'],
                'trail_level': 'Superhighway',
            })
        sites.sort(key=lambda s: (s['is_complete'], s.get('chain_direction', 'Z'), s.get('segment_index', 0)))
        return sites
    except Exception as e:
        logger.error(f"Failed to get visited sites for trails (v3): {e}")
        return []


def _format_trail_sites(trails: list, base_lat: float, base_lon: float) -> list:
    """Format trail segment rows into the site dict format expected by the API."""
    from utilities.mars_math import haversine_distance

    # Bug #1291: chain trails (from_landmark != 'HOME') previously had from_latitude/from_longitude
    # hardcoded to base coords, so the map drew them as base->dest instead of origin->dest.
    # Look up real coords for any non-HOME from_landmarks in one batch query.
    non_home_froms = sorted({t['from_landmark'] for t in trails
                             if t.get('from_landmark') and t['from_landmark'] != 'HOME'})
    from_coords_lookup = {}
    if non_home_froms:
        with db_cursor() as cur:
            cur.execute("""
                SELECT name, latitude, longitude FROM pilgrim.mars_mappings
                WHERE name = ANY(%s)
            """, (non_home_froms,))
            for r in (cur.fetchall() or []):
                from_coords_lookup[r['name']] = (float(r['latitude']), float(r['longitude']))

    results = []
    for t in trails:
        s_lat = float(t['latitude'])
        s_lon = float(t['longitude'])
        home_dist = haversine_distance(base_lat, base_lon, s_lat, s_lon)
        from_lm = t.get('from_landmark') or 'HOME'
        if from_lm != 'HOME' and from_lm in from_coords_lookup:
            from_lat, from_lon = from_coords_lookup[from_lm]
        else:
            from_lat, from_lon = base_lat, base_lon
        total_dist = float(t.get('total_distance_km') or home_dist)
        km_built = float(t.get('km_built') or 0)
        results.append({
            'name': t['destination_name'],
            'type': t.get('type', 'Crater, craters'),
            'latitude': s_lat,
            'longitude': s_lon,
            'visit_count': 0,
            'last_visited': None,
            'distance_km': round(home_dist, 2),
            'from_landmark': from_lm,
            'from_latitude': from_lat,
            'from_longitude': from_lon,
            'segment_distance_km': round(total_dist, 2),
            'km_built': km_built,
            'is_complete': total_dist > 0 and km_built >= total_dist,
            'captain_km': float(t.get('captain_km') or 0),
            'scientist_km': float(t.get('scientist_km') or 0),
            'aria_km': float(t.get('aria_km') or 0),
            'trip_count': t.get('trip_count', 0),
            'trail_level': t.get('trail_level', 'none'),
        })
    # Sort: incomplete first (by distance), then completed (by distance).
    # Keeps the picker showing buildable trails at the top.
    results.sort(key=lambda s: (s['is_complete'], s['segment_distance_km']))
    return results


def get_crew_mission_status_with_stats(user_id: int) -> dict:
    """Mission status enriched with per-crew stat multipliers — used by the
    /api/crew/mission/status endpoint."""
    from utilities.postgres.trails.aria_skills import get_aria_skills

    status = get_crew_mission_status(user_id)

    with db_cursor() as cur:
        cur.execute("""
            SELECT captain_logistics_xp, scientist_navigation_xp
            FROM pilgrim.users WHERE id = %s
        """, (user_id,))
        row = cur.fetchone()
        if row:
            logistics_xp = row.get('captain_logistics_xp') or 0
            nav_xp = row.get('scientist_navigation_xp') or 0
            status['captain']['stat_value'] = logistics_xp
            status['captain']['stat_multiplier'] = round(1.0 + (logistics_xp / 1000), 2)
            status['captain']['stat_desc'] = f"Logistics {logistics_xp} XP"
            if status.get('scientist'):
                status['scientist']['stat_value'] = nav_xp
                status['scientist']['stat_multiplier'] = round(1.0 + (nav_xp / 1500), 2)
                status['scientist']['stat_desc'] = f"Navigation {nav_xp} XP"

    aria_skills = get_aria_skills(user_id)
    resonance_level = aria_skills.get('resonance_level') or 1
    if status.get('aria'):
        status['aria']['stat_value'] = resonance_level
        status['aria']['stat_multiplier'] = round(1.0 + (resonance_level / 100), 2)
        status['aria']['stat_desc'] = f"Resonance Lv{resonance_level}"

    return status


def get_crew_nearby_payload(user_id: int) -> dict:
    """Formatted trails + home base coords for the /api/crew/mission/nearby endpoint."""
    trails = get_visited_sites_for_trails(user_id)

    base_coords = None
    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT home_mars_lat, home_mars_lon FROM pilgrim.users WHERE id = %s",
                (user_id,))
            user = cur.fetchone()
            if user and user['home_mars_lat']:
                base_coords = {
                    'latitude': float(user['home_mars_lat']),
                    'longitude': float(user['home_mars_lon']),
                }
    except Exception:
        pass

    formatted = []
    for t in trails:
        formatted.append({
            'name': t['name'],
            'type': t['type'],
            'distance_km': round(float(t.get('distance_km') or 0), 1),
            'from_landmark': t.get('from_landmark', 'HOME'),
            'from_latitude': float(t['from_latitude']) if t.get('from_latitude') else None,
            'from_longitude': float(t['from_longitude']) if t.get('from_longitude') else None,
            'segment_distance_km': round(float(t.get('segment_distance_km') or 0), 1),
            'visit_count': t.get('visit_count', 0),
            'km_built': round(float(t.get('km_built') or 0), 3),
            'captain_km': round(float(t.get('captain_km') or 0), 3),
            'scientist_km': round(float(t.get('scientist_km') or 0), 3),
            'aria_km': round(float(t.get('aria_km') or 0), 3),
            'trip_count': t.get('trip_count', 0),
            'trail_level': t.get('trail_level', 'none'),
            'latitude': float(t['latitude']) if t.get('latitude') else None,
            'longitude': float(t['longitude']) if t.get('longitude') else None,
            'is_complete': bool(t.get('is_complete', False)),
        })

    return {'success': True, 'trails': formatted, 'base_coords': base_coords}
