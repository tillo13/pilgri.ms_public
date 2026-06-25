"""Mars coordinates, landmarks, fog-of-war, and frontier line database operations."""

import math
import random
import logging
from typing import Dict, Any, Optional, List

from utilities.postgres.core import db_cursor, _fetchone, _fetchall, request_memo
from utilities.mars_math import calculate_mars_distance

logger = logging.getLogger(__name__)


# ============================================================================
# FULL MARS MAPPINGS CACHE (per-request)
# mars_mappings is ~2000 rows of static reference data. Fetching once per
# request and filtering in Python is dramatically cheaper than the repeated
# bounding-box queries fog-of-war + frontier-line code used to issue.
# ============================================================================

def get_all_mars_mappings() -> List[Dict]:
    """Fetch every mars_mappings row. Memoized per-request."""
    def _load():
        try:
            with db_cursor() as cur:
                cur.execute("""
                    SELECT name, type, latitude, longitude, diameter_km, origin, quad_name, link
                    FROM pilgrim.mars_mappings
                """)
                rows = _fetchall(cur)
            for r in rows:
                r['latitude'] = float(r['latitude'])
                r['longitude'] = float(r['longitude'])
            return rows
        except Exception as e:
            logger.warning(f"Could not load mars_mappings: {e}")
            return []
    return request_memo(('get_all_mars_mappings',), _load)


def get_mars_mappings_by_name() -> Dict[str, Dict]:
    """Dict of name -> mars_mappings row. Memoized per-request."""
    return request_memo(
        ('get_mars_mappings_by_name',),
        lambda: {r['name']: r for r in get_all_mars_mappings()},
    )


# ============================================================================
# MARS COORDINATES
# ============================================================================

def get_random_mars_coordinates():
    """Generate random Mars coordinates with safe buffer zones"""
    return {
        'latitude': round(random.uniform(-65.0, 65.0), 6),
        'longitude': round(random.uniform(10.0, 350.0), 6)
    }


def get_nearest_mars_landmarks(latitude, longitude, limit=5):
    """Find nearest Mars landmarks to coordinates"""
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT name, type, latitude, longitude, diameter_km, origin, quad_name, link
                FROM pilgrim.mars_mappings
                ORDER BY SQRT(POW(RADIANS(latitude - %s), 2) + POW(RADIANS(longitude - %s) * COS(RADIANS(latitude)), 2))
                LIMIT %s
            """, (latitude, longitude, limit))
            landmarks = _fetchall(cur)
            for lm in landmarks:
                lm['distance_km'] = round(calculate_mars_distance(latitude, longitude, lm['latitude'], lm['longitude']), 2)
                # Use DRY helper for travel estimate (assumes base rover 1.25x, avg logistics 50)
                from utilities.expeditions.terrain import estimate_travel_days
                lm['travel_days'] = estimate_travel_days(lm['distance_km'], vehicle_speed_mult=1.25, logistics=50)
            return landmarks
    except Exception as e:
        logger.error(f"❌ Failed to get landmarks: {e}")
        return []


def get_or_set_user_mars_home(user_id):
    return request_memo(('get_or_set_user_mars_home', user_id), lambda: _get_or_set_user_mars_home_uncached(user_id))


def _get_or_set_user_mars_home_uncached(user_id):
    """Get user's Mars home coordinates, or set if not assigned"""
    newly_set = False
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("SELECT home_mars_lat, home_mars_lon, home_mars_set_at FROM pilgrim.users WHERE id = %s", (user_id,))
            result = cur.fetchone()
            if not result or result['home_mars_lat'] is None:
                coords = get_random_mars_coordinates()
                cur.execute("UPDATE pilgrim.users SET home_mars_lat = %s, home_mars_lon = %s, home_mars_set_at = NOW() WHERE id = %s",
                            (coords['latitude'], coords['longitude'], user_id))
                logger.info(f"Set Mars home for user {user_id}: {coords}")
                newly_set = True
            else:
                coords = {'latitude': float(result['home_mars_lat']), 'longitude': float(result['home_mars_lon']), 'set_at': result['home_mars_set_at']}

        # v3 (#1414): when a captain's base is first set, immediately compute their 4 antipode chains.
        if newly_set:
            try:
                from utilities.postgres.trails.chains import compute_user_trail_chains, persist_user_trail_chains
                persist_user_trail_chains(user_id, compute_user_trail_chains(user_id))
            except Exception as e:
                logger.warning(f"Failed to compute trail chains during onboarding for user {user_id}: {e}")
        return coords
    except Exception as e:
        logger.error(f"❌ Failed to get/set Mars home: {e}")
        return get_random_mars_coordinates()


# ============================================================================
# FOG-OF-WAR: RADIUS-BASED QUERIES
# The fog-of-war is a circle around home base. We query ALL landmarks within
# this radius (not limited by count) to ensure all directions are covered.
# ============================================================================

def get_mars_landmarks_within_radius(center_lat: float, center_lon: float, radius_km: float) -> List[Dict]:
    """Get all landmarks within a radius of a center point.

    This is the core fog-of-war query - returns ALL landmarks in the circle,
    not limited by count. This ensures all directions get coverage.
    """
    try:
        radius_deg = radius_km / 59
        lat_min, lat_max = center_lat - radius_deg, center_lat + radius_deg
        lon_min, lon_max = center_lon - radius_deg, center_lon + radius_deg

        results = []
        for row in get_all_mars_mappings():
            lat, lon = row['latitude'], row['longitude']
            if not (lat_min <= lat <= lat_max and lon_min <= lon <= lon_max):
                continue
            dist = calculate_mars_distance(center_lat, center_lon, lat, lon)
            if dist <= radius_km:
                out = dict(row)
                out['distance_km'] = round(dist, 2)
                results.append(out)
        results.sort(key=lambda r: r['distance_km'])
        return results
    except Exception as e:
        logger.warning(f"Could not get landmarks within radius: {e}")
        return []


# ============================================================================
# FRONTIER LINE LOGIC
# ============================================================================

def _lon_delta(from_lon: float, to_lon: float) -> float:
    """Signed shortest longitude delta in (-180, 180]. Positive = `to` is EAST of
    `from`, negative = WEST. Mars longitude is cyclic [0,360); a flat `lon1 < lon2`
    compare breaks at the 0/360 meridian — bug #1485, where a captain who explored
    to lon≈0 saw ZERO 'further west' frontier dots because the entire western
    hemisphere sat one wrap (lon≈350-360) away and the flat filter never reached it.
    """
    return ((to_lon - from_lon + 180) % 360) - 180


def _get_direction_from_angle(angle_degrees: float) -> str:
    """Convert angle (0=N, 90=E, -90=W, 180=S) to 8-direction string."""
    if -22.5 <= angle_degrees < 22.5:
        return 'N'
    elif 22.5 <= angle_degrees < 67.5:
        return 'NE'
    elif 67.5 <= angle_degrees < 112.5:
        return 'E'
    elif 112.5 <= angle_degrees < 157.5:
        return 'SE'
    elif angle_degrees >= 157.5 or angle_degrees < -157.5:
        return 'S'
    elif -157.5 <= angle_degrees < -112.5:
        return 'SW'
    elif -112.5 <= angle_degrees < -67.5:
        return 'W'
    else:  # -67.5 <= angle < -22.5
        return 'NW'


def get_user_furthest_expeditions_by_direction(user_id: int, home_lat: float, home_lon: float) -> Dict[str, Dict]:
    """Get the furthest completed expedition in each of 8 directions.

    Returns dict like: {'N': {'name': 'Kalpin', 'lat': 8.93, 'lon': 141.27, 'dist': 792}, ...}
    Directions with no expeditions will have None as value.
    """
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT DISTINCT destination_name, destination_lat, destination_lon
                FROM pilgrim.expeditions
                WHERE user_id = %s AND status = 'complete'
                  AND COALESCE(discovery_type, '') != 'recalled'
            """, (user_id,))
            expeditions = _fetchall(cur)
    except Exception as e:
        logger.warning(f"Could not get expeditions for frontier: {e}")
        return {d: None for d in ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']}

    # Group by direction, track furthest
    directions = {d: None for d in ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']}

    for exp in expeditions:
        lat = float(exp['destination_lat'])
        lon = float(exp['destination_lon'])
        lat_diff = lat - home_lat
        lon_diff = _lon_delta(home_lon, lon)  # wrap-aware (#1485) — flat diff misreads meridian crossers
        dist = calculate_mars_distance(home_lat, home_lon, lat, lon)

        # Calculate direction
        angle = math.degrees(math.atan2(lon_diff, lat_diff))
        direction = _get_direction_from_angle(angle)

        # Update if this is furthest in this direction
        if directions[direction] is None or dist > directions[direction]['dist']:
            directions[direction] = {
                'name': exp['destination_name'],
                'lat': lat,
                'lon': lon,
                'dist': dist
            }

    return directions


def get_frontier_landmarks_beyond_point(
    direction: str,
    furthest_lat: float,
    furthest_lon: float,
    home_lat: float,
    home_lon: float,
    limit: int = 3,
    exclude_names: set = None
) -> List[Dict]:
    """Get landmarks beyond a point in a specific direction.

    These are the 'frontier dots' that extend exploration beyond the fog-of-war.

    GUARANTEE: Always returns up to `limit` landmarks regardless of distance.
    No hard distance cap — searches as far as needed so players always have a
    "next step" in any direction (CLAUDE.md requirement, bugs #74 #207 #433 #1267).

    DISCOVERED-AWARE (#1519): `exclude_names` (the player's already-discovered
    landmark names) is filtered out BEFORE the candidate cap and band-pick. This
    is the structural fix for the recurring "no new dots in direction X" saga
    (#74 #88 #172 #207 #433 #1267 #1485): previously the nearest-150 candidate
    pool included discovered landmarks, so a heavily-explored octant could fill
    all 150 + every distance band with already-visited dots and surface ZERO new
    ones — which the display layer then dropped, starving the direction. Excluding
    discovered up front guarantees the band-pick only ever yields UNDISCOVERED
    dots, so it's impossible to starve a direction while undiscovered landmarks
    remain in it — no constant-tuning required.

    STEPPING STONES: Uses adaptive band sizing — 500km bands near home, scaling
    down to 200km bands at extreme distances — to prevent clustering.
    """
    exclude_names = exclude_names or set()
    # Build SQL conditions based on direction
    conditions = []
    if 'N' in direction:
        conditions.append(f'latitude > {furthest_lat}')
    if 'S' in direction:
        conditions.append(f'latitude < {furthest_lat}')
    if 'E' in direction:
        conditions.append(f'longitude > {furthest_lon}')
    if 'W' in direction:
        conditions.append(f'longitude < {furthest_lon}')

    if not conditions:
        return []

    try:
        # Python-filter from the cached mars_mappings pool (memoized per-request).
        def _matches(r):
            lat, lon = r['latitude'], r['longitude']
            # #1519: drop already-discovered landmarks up front so the [:150] cap
            # and per-band pick below only ever consider UNDISCOVERED candidates.
            if r['name'] in exclude_names: return False
            if 'N' in direction and not lat > furthest_lat: return False
            if 'S' in direction and not lat < furthest_lat: return False
            # Wrap-aware E/W (#1485): "further east/west" follows the shortest arc
            # around the sphere, so reaching lon≈0 no longer dead-ends the W/NW/SW dots.
            if 'E' in direction and not _lon_delta(furthest_lon, lon) > 0: return False
            if 'W' in direction and not _lon_delta(furthest_lon, lon) < 0: return False
            return True

        candidates = []
        for r in get_all_mars_mappings():
            if not _matches(r):
                continue
            dist = calculate_mars_distance(home_lat, home_lon, r['latitude'], r['longitude'])
            out = dict(r)
            out['distance_km'] = dist
            candidates.append(out)
        candidates.sort(key=lambda r: r['distance_km'])
        all_landmarks = candidates[:150]

        if not all_landmarks:
            return []

        if True:  # preserve original indent block

            # STEPPING STONE SELECTION: Pick one landmark per distance band.
            # Adaptive band size: 500km for nearby, shrinks for distant exploration.
            result = []
            covered_bands = set()

            for lm in all_landmarks:
                dist = float(lm['distance_km'])

                # Adaptive band size: 500km up to 2000km, 300km up to 4000km, 200km beyond
                if dist < 2000:
                    band_size = 500
                elif dist < 4000:
                    band_size = 300
                else:
                    band_size = 200
                band = int(dist / band_size)

                # Take first landmark in each band (ensures stepping stones)
                if band not in covered_bands:
                    covered_bands.add(band)
                    lm['is_frontier'] = True
                    lm['frontier_direction'] = direction
                    lm['distance_km'] = round(dist, 2)
                    result.append(lm)

                    if len(result) >= limit:
                        break

            return result
    except Exception as e:
        logger.warning(f"Could not get frontier landmarks for {direction}: {e}")
        return []


def get_all_frontier_landmarks(user_id: int, home_lat: float, home_lon: float,
                               dots_per_direction: int = 5, exclude_names: set = None) -> List[Dict]:
    """Get frontier landmarks in all 8 directions.

    For each direction, finds the user's furthest expedition and returns
    stepping-stone landmarks beyond that point. This ensures players always have
    a 'next step' in any direction they want to explore, with no big gaps.

    `exclude_names` (#1519): the player's discovered landmark names, threaded into
    every directional pick so frontier dots are guaranteed UNDISCOVERED. See
    get_frontier_landmarks_beyond_point for the full rationale.

    STEPPING STONES: Instead of just closest 3, we get one landmark per 500km band.
    This prevents situations where all visible dots cluster at similar distances.
    """
    exclude_names = exclude_names or set()
    # Get furthest point in each direction
    furthest_by_direction = get_user_furthest_expeditions_by_direction(user_id, home_lat, home_lon)

    all_frontier = []
    seen_names = set()

    for direction in ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']:
        furthest = furthest_by_direction.get(direction)

        if furthest:
            # Get landmarks beyond the furthest explored point
            frontier_dots = get_frontier_landmarks_beyond_point(
                direction,
                furthest['lat'],
                furthest['lon'],
                home_lat,
                home_lon,
                limit=dots_per_direction,
                exclude_names=exclude_names
            )
            # #1485: sparse/edge directions (poleward, or after exploring to a meridian)
            # can still come up short. Top up with frontier dots measured from HOME so
            # EVERY direction always offers a next step (CLAUDE.md frontier guarantee).
            if len(frontier_dots) < dots_per_direction:
                have = {d['name'] for d in frontier_dots}
                for lm in get_frontier_landmarks_beyond_point(
                        direction, home_lat, home_lon, home_lat, home_lon,
                        limit=dots_per_direction, exclude_names=exclude_names):
                    if lm['name'] in have:
                        continue
                    frontier_dots.append(lm)
                    have.add(lm['name'])
                    if len(frontier_dots) >= dots_per_direction:
                        break
        else:
            # No expeditions in this direction - get frontier from home
            frontier_dots = get_frontier_landmarks_beyond_point(
                direction,
                home_lat,
                home_lon,
                home_lat,
                home_lon,
                limit=dots_per_direction,
                exclude_names=exclude_names
            )

        # Add unique landmarks
        for lm in frontier_dots:
            if lm['name'] not in seen_names:
                seen_names.add(lm['name'])
                all_frontier.append(lm)

    return all_frontier


def get_available_landmarks_by_discovery(user_id: int, base_coords: dict, limit: int = 20) -> List[Dict]:
    """Get landmarks based on fog-of-war expansion from visited locations.

    GRADUAL EXPANSION: Shows landmarks in expanding rings around base and discoveries.
    - Base radius: 300km + 50km per discovery (caps at 1000km)
    - Each discovery also reveals its nearest 3 unexplored neighbors
    - Total undiscovered landmarks capped to prevent overwhelming UI
    """
    from utilities.postgres.expeditions import get_user_discovered_landmarks
    discovered = get_user_discovered_landmarks(user_id)
    discovered_names = {d['landmark_name'] for d in discovered}
    num_discoveries = len(discovered)

    base_lat = base_coords['latitude']
    base_lon = base_coords['longitude']

    # Infrastructure bonus (Launch Pad can increase range)
    range_mult = 1.0
    try:
        from utilities.infrastructure_utils import get_user_infrastructure_effects
        effects = get_user_infrastructure_effects(user_id)
        range_mult = effects.get('expedition_range_mult', 1.0)
    except Exception:
        pass

    # GRADUAL radius expansion: 300km base + 50km per discovery, cap at 1000km
    base_radius = 300 + (num_discoveries * 50)
    expansion_radius = int(min(1000, base_radius) * range_mult)

    all_candidates = {}  # name -> landmark (dedupe)

    # FOG-OF-WAR: Get ALL landmarks within the fog radius
    # This uses radius-based query to ensure all directions get coverage
    fog_landmarks = get_mars_landmarks_within_radius(base_lat, base_lon, expansion_radius)
    for lm in fog_landmarks:
        lm['distance_km'] = round(float(lm['distance_km']), 2)
        all_candidates[lm['name']] = lm

    # Mark discovered status for candidates
    all_landmarks = list(all_candidates.values())
    for lm in all_landmarks:
        lm['is_discovered'] = lm['name'] in discovered_names
        if lm['is_discovered']:
            disc = next((d for d in discovered if d['landmark_name'] == lm['name']), None)
            if disc:
                lm['last_visit'] = disc['discovered_at']
                lm['last_yield'] = disc['sepolia_earned']
                lm['visit_count'] = disc.get('visit_count', 1)

    # BUG FIX: Always include ALL discovered landmarks, even if outside fog-of-war.
    # Use the per-request cached mars_mappings lookup to avoid per-miss DB queries.
    mappings_by_name = get_mars_mappings_by_name()
    for disc in discovered:
        name = disc['landmark_name']
        if name in all_candidates:
            continue
        source = mappings_by_name.get(name)
        if not source:
            continue
        row = dict(source)
        row['distance_km'] = round(calculate_mars_distance(
            base_lat, base_lon, row['latitude'], row['longitude']
        ), 2)
        row['is_discovered'] = True
        row['last_visit'] = disc['discovered_at']
        row['last_yield'] = disc['sepolia_earned']
        row['visit_count'] = disc.get('visit_count', 1)
        all_landmarks.append(row)
        all_candidates[name] = row

    # === LAYER 2: FRONTIER LINES (additive to fog-of-war) ===
    # Players should ALWAYS see 1-3 dots in each of 8 directions beyond their furthest point
    # This creates exploration chains and ensures there's always a "next step" in any direction
    try:
        frontier_landmarks = get_all_frontier_landmarks(user_id, base_lat, base_lon, dots_per_direction=5,
                                                        exclude_names=discovered_names)
        for lm in frontier_landmarks:
            if lm['name'] not in all_candidates:
                lm['is_discovered'] = lm['name'] in discovered_names
                all_candidates[lm['name']] = lm
                all_landmarks.append(lm)
    except Exception as e:
        logger.warning(f"Could not fetch frontier landmarks: {e}")

    # Split into categories
    discovered_list = sorted([l for l in all_landmarks if l.get('is_discovered')],
                            key=lambda x: x['distance_km'])
    # Frontier landmarks ALWAYS shown (they're the "next step" in each direction)
    frontier_list = sorted([l for l in all_landmarks if l.get('is_frontier') and not l.get('is_discovered')],
                          key=lambda x: x['distance_km'])
    # Regular fog-of-war undiscovered (non-frontier)
    fog_undiscovered = sorted([l for l in all_landmarks if not l.get('is_discovered') and not l.get('is_frontier')],
                             key=lambda x: x['distance_km'])

    # Combine all: discovered + fog undiscovered + frontier
    # No artificial cap - show everything within fog radius + frontier dots
    result = discovered_list + fog_undiscovered + frontier_list

    result.sort(key=lambda x: x['distance_km'])
    return result
