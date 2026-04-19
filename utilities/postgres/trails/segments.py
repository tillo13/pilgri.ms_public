"""Trail segments: CRUD + km-based progress + nearest origin + drone + spawn-next."""

import logging
from typing import Optional

from utilities.postgres.core import db_cursor
from utilities.postgres.trails.config import TRAIL_LEVEL_THRESHOLDS, TRAIL_SPEED_MULTIPLIERS

logger = logging.getLogger(__name__)

_trail_schema_ensured = False


def get_trail_level_from_count(trip_count: int) -> str:
    """Convert trip count to trail level name."""
    level = 'none'
    for threshold, name in TRAIL_LEVEL_THRESHOLDS:
        if trip_count >= threshold:
            level = name
    return level


def calculate_trail_speed_mult_km(km_built: float, total_distance_km: float) -> float:
    """
    Trail speed multiplier via km-based proportional progress.
    Formula: 1.0 + (km_built / total_distance_km) * 0.5
    (0% = 1.0x, 50% = 1.25x, 100% = 1.5x)
    """
    if not total_distance_km or total_distance_km <= 0:
        return 1.0
    ratio = min(1.0, (km_built or 0) / total_distance_km)
    return 1.0 + ratio * 0.5


def get_trail_speed_mult_for_destination(user_id: int, destination_name: str, distance_km: float = None) -> dict:
    """
    Trail speed multiplier for a destination, preferring km-based system when
    total_distance_km is known; falls back to the legacy threshold system.
    """
    trail_data = get_user_trail(user_id, destination_name)

    km_built = trail_data.get('km_built') or 0
    total_distance = trail_data.get('total_distance_km')
    if not total_distance and distance_km:
        total_distance = distance_km

    if total_distance and total_distance > 0:
        speed_mult = calculate_trail_speed_mult_km(km_built, total_distance)
        percent = round((km_built / total_distance) * 100, 1)
        return {
            'speed_mult': round(speed_mult, 3),
            'km_built': km_built,
            'total_distance_km': total_distance,
            'percent_complete': percent,
            'using_km_system': True,
            'trail_level': trail_data.get('trail_level', 'none'),
            'captain_km': trail_data.get('captain_km', 0),
            'scientist_km': trail_data.get('scientist_km', 0),
            'aria_km': trail_data.get('aria_km', 0),
        }

    trail_level = trail_data.get('trail_level', 'none')
    return {
        'speed_mult': TRAIL_SPEED_MULTIPLIERS.get(trail_level, 1.0),
        'km_built': 0,
        'total_distance_km': distance_km or 0,
        'percent_complete': 0,
        'using_km_system': False,
        'trail_level': trail_level,
        'captain_km': 0,
        'scientist_km': 0,
        'aria_km': 0,
    }


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

    # Migration: add drone_km column for Automation Drone passive trail building
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("ALTER TABLE pilgrim.trail_segments ADD COLUMN IF NOT EXISTS drone_km DOUBLE PRECISION DEFAULT 0")
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

        # SV Economy Pillar 5: Award 5 SV per km of trail built
        if km_amount > 0:
            try:
                from utilities.postgres.users import add_passive_sv
                trail_sv = int(km_amount * 2)
                if trail_sv > 0:
                    add_passive_sv(user_id, trail_sv)
                    logger.info(f"🛤️ Trail SV: user {user_id} earned {trail_sv} SV from {km_amount:.1f} km built on {destination_name}")
            except Exception as e:
                logger.error(f"Failed to award trail SV: {e}")

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


def spawn_next_trail(user_id: int, completed_destination: str) -> Optional[dict]:
    """When a trail is completed, chain a new segment from the completed point
    to the closest unbuilt landmark that is strictly farther from base.

    Design (Luke bugs #450, #483, #484, #1291, #1399):
    - from_landmark = completed_destination (NOT 'HOME') — the new segment
      chains off the completed point. Render shows Base→P1→P2, not Base→P2.
    - Candidates must be farther from HOME than completed_destination — no
      backtracking toward base; chains always extend outward.
    - Exclude any landmark already present in trail_segments for this user.
    - Pick the closest candidate to completed_destination (shortest hop).
    - On candidate conflict (ON CONFLICT DO NOTHING returns no row), fall
      through to the next candidate instead of leaving an orphan tip.
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

            cur.execute(
                "SELECT latitude, longitude FROM pilgrim.mars_mappings WHERE name = %s",
                (completed_destination,),
            )
            completed = cur.fetchone()
            if not completed:
                return None
            comp_lat = float(completed['latitude'])
            comp_lon = float(completed['longitude'])
            comp_home_dist = haversine_distance(base_lat, base_lon, comp_lat, comp_lon)

            cur.execute(
                "SELECT destination_name FROM pilgrim.trail_segments WHERE user_id = %s",
                (user_id,),
            )
            existing = {r['destination_name'] for r in (cur.fetchall() or [])}

            cur.execute("SELECT name, type, latitude, longitude FROM pilgrim.mars_mappings")
            all_landmarks = cur.fetchall()

        candidates = []
        for lm in all_landmarks:
            if lm['name'] in existing or lm['name'] == completed_destination:
                continue
            lm_lat = float(lm['latitude'])
            lm_lon = float(lm['longitude'])
            home_dist = haversine_distance(base_lat, base_lon, lm_lat, lm_lon)
            if home_dist <= comp_home_dist:
                continue
            hop_dist = haversine_distance(comp_lat, comp_lon, lm_lat, lm_lon)
            candidates.append({**dict(lm), 'hop_distance': hop_dist})
        candidates.sort(key=lambda x: x['hop_distance'])

        if not candidates:
            logger.info(f"spawn_next_trail: no farther-from-base candidates past {completed_destination} for user {user_id}")
            return None

        for next_lm in candidates:
            with db_cursor(commit=True) as cur:
                cur.execute("""
                    INSERT INTO pilgrim.trail_segments
                    (user_id, from_landmark, destination_name, total_distance_km,
                     km_built, captain_km, scientist_km, aria_km, trip_count, trail_level)
                    VALUES (%s, %s, %s, %s, 0, 0, 0, 0, 0, 'none')
                    ON CONFLICT (user_id, from_landmark, destination_name) DO NOTHING
                    RETURNING *
                """, (user_id, completed_destination, next_lm['name'], round(next_lm['hop_distance'], 6)))
                row = cur.fetchone()
            if row:
                logger.info(f"Spawned chain trail for user {user_id}: {completed_destination} -> {next_lm['name']} ({next_lm['hop_distance']:.1f} km hop)")
                return dict(row)

        logger.info(f"spawn_next_trail: all candidates conflicted past {completed_destination} for user {user_id}")
        return None
    except Exception as e:
        logger.error(f"Failed to spawn next trail: {e}")
        return None


def heal_orphan_trail_tips(user_id: int) -> int:
    """For every completed trail destination that has no descendant chain row,
    spawn the next-hop chain. Fixes orphans left behind by older code paths
    (bug #1399: Kasabi completed but no Point 2).

    Returns count of chains spawned.
    """
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT DISTINCT destination_name
                FROM pilgrim.trail_segments
                WHERE user_id = %s
                  AND total_distance_km IS NOT NULL
                  AND total_distance_km > 0
                  AND km_built >= total_distance_km
                  AND destination_name NOT IN (
                      SELECT from_landmark FROM pilgrim.trail_segments
                      WHERE user_id = %s AND from_landmark != 'HOME'
                  )
            """, (user_id, user_id))
            orphan_tips = [r['destination_name'] for r in (cur.fetchall() or [])]

        spawned = 0
        for tip in orphan_tips:
            if spawn_next_trail(user_id, tip):
                spawned += 1
        if spawned:
            logger.info(f"heal_orphan_trail_tips: spawned {spawned} chain(s) for user {user_id}")
        return spawned
    except Exception as e:
        logger.error(f"heal_orphan_trail_tips failed for user {user_id}: {e}")
        return 0


# ============================================================================
# AUTOMATION DRONE — Passive Trail Building (cron job, runs every 30 min)
# ============================================================================

def cron_drone_trail_build():
    """Passive trail building for users with Automation Drone upgrades.

    Called by /api/cron/drone_trail_build every 30 minutes.
    Adds km based on drone level's trail_km_per_hour config.
    Builds on the trail closest to completion (most km_built / total_distance_km).
    """
    from config_upgrades import UPGRADE_CATALOG
    from utilities.upgrades_utils import get_user_upgrade_level

    ensure_trail_segments_table()
    results = []

    try:
        with db_cursor() as cur:
            # Get all users who have active trail segments
            cur.execute("SELECT DISTINCT user_id FROM pilgrim.trail_segments WHERE km_built < total_distance_km AND total_distance_km > 0")
            users = cur.fetchall()

        for u in users:
            user_id = u['user_id']
            # bug #1149: Maintenance + Mining drones both contribute trail_km/hr. Sum both paths.
            km_per_hour = 0.0
            for (cat, key) in (('maintenance', 'maintenance'), ('mining', 'mining')):
                lv = get_user_upgrade_level(user_id, cat, key)
                if lv < 1:
                    continue
                cfg = UPGRADE_CATALOG.get(cat, {}).get(key, {}).get('levels', {}).get(lv, {})
                km_per_hour += cfg.get('trail_km_per_hour', 0) or 0
            if km_per_hour <= 0:
                continue

            # 30 min cron interval = 0.5 hours
            km_to_add = km_per_hour * 0.5

            # Find the trail closest to completion (highest % built)
            with db_cursor() as cur:
                cur.execute("""
                    SELECT destination_name, from_landmark, km_built, total_distance_km
                    FROM pilgrim.trail_segments
                    WHERE user_id = %s AND total_distance_km > 0 AND km_built < total_distance_km
                    ORDER BY (km_built / total_distance_km) DESC
                    LIMIT 1
                """, (user_id,))
                trail = cur.fetchone()

            if not trail:
                continue

            dest = trail['destination_name']
            from_lm = trail['from_landmark']
            total_dist = float(trail['total_distance_km'])

            # Cap km_to_add so we don't overshoot
            remaining = total_dist - float(trail['km_built'])
            actual_km = min(km_to_add, remaining)

            # Add km as 'drone' worker type
            with db_cursor(commit=True) as cur:
                cur.execute("""
                    UPDATE pilgrim.trail_segments
                    SET km_built = COALESCE(km_built, 0) + %s,
                        drone_km = COALESCE(drone_km, 0) + %s,
                        last_used_at = NOW()
                    WHERE user_id = %s AND from_landmark = %s AND destination_name = %s
                """, (actual_km, actual_km, user_id, from_lm, dest))

            # Award SV (2 SV/km, same as manual)
            if actual_km > 0:
                try:
                    from utilities.postgres.users import add_passive_sv
                    trail_sv = int(actual_km * 2)
                    if trail_sv > 0:
                        add_passive_sv(user_id, trail_sv)
                except Exception:
                    pass

            # Check if trail just completed — spawn next
            new_built = float(trail['km_built']) + actual_km
            if new_built >= total_dist:
                spawn_next_trail(user_id, dest)

            results.append(f"user {user_id}: +{actual_km:.2f}km to {dest} (drone Lv{drone_level})")

    except Exception as e:
        logger.error(f"Drone trail cron error: {e}")
        results.append(f"ERROR: {e}")

    return results
