"""TRAILS v3 — Antipode chain computation + storage.

Bug #1414. Each captain's base produces 4 deterministic cardinal chains (N/S/E/W)
via constrained Dijkstra over the 2,038-landmark graph. All chains terminate at
the captain's antipode landmark — the furthest reachable point on Mars from base.

Pure-function design: compute_user_trail_chains is side-effect-free.
persist_user_trail_chains writes the rows. ensure_user_trail_chains_table
runs the schema migration idempotently.
"""

from __future__ import annotations

import heapq
import logging
from typing import Dict, List, Optional, Tuple

from utilities.postgres.core import db_cursor
from utilities.mars_math import haversine_distance, bearing_deg

logger = logging.getLogger(__name__)


# Tuning constants — see #1414 plan, decisions 4 + 5 + 6.
HOP_CAP_KM = 800.0
OVERSIZE_MAX_KM = 2000.0  # tail-end safety: one oversize hop allowed
DIRECTION_BEARING_WINDOWS = {
    'N': (315.0, 45.0),     # wraps through 0/360
    'E': (45.0, 135.0),
    'S': (135.0, 225.0),
    'W': (225.0, 315.0),
}
POLAR_TRANSIT_LAT = 80.0  # N must touch lat > 80; S must touch lat < -80
EQUATORIAL_LON_BAND_DEG = 30.0  # E/W must transit (base_lon + 180) ± this band

# Per-segment progress display tiers (decision #2)
SEGMENT_TIERS = [
    (0.00, 'none'),
    (0.25, 'Path'),
    (0.50, 'Road'),
    (0.75, 'Highway'),
    (1.00, 'Superhighway'),
]

# Chain-cumulative prestige tiers (decision #3)
CHAIN_PRESTIGE_TIERS = [
    (0,     'none'),
    (1000,  'Surveying'),
    (5000,  'Marked'),
    (11000, 'Complete'),
]


_CHAINS_SCHEMA_ENSURED = False


def ensure_user_trail_chains_table():
    """Idempotent migration: pilgrim.user_trail_chains + users.active_trail_direction."""
    global _CHAINS_SCHEMA_ENSURED
    if _CHAINS_SCHEMA_ENSURED:
        return
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS pilgrim.user_trail_chains (
                    user_id INTEGER NOT NULL,
                    direction TEXT NOT NULL,
                    segment_index INTEGER NOT NULL,
                    from_landmark TEXT NOT NULL,
                    to_landmark TEXT NOT NULL,
                    segment_distance_km DOUBLE PRECISION NOT NULL,
                    km_built DOUBLE PRECISION DEFAULT 0,
                    captain_km DOUBLE PRECISION DEFAULT 0,
                    scientist_km DOUBLE PRECISION DEFAULT 0,
                    aria_km DOUBLE PRECISION DEFAULT 0,
                    drone_km DOUBLE PRECISION DEFAULT 0,
                    robot_km DOUBLE PRECISION DEFAULT 0,
                    completed_at TIMESTAMP NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (user_id, direction, segment_index),
                    CHECK (direction IN ('N','S','E','W'))
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_user_chain ON pilgrim.user_trail_chains(user_id, direction)")
            cur.execute("ALTER TABLE pilgrim.users ADD COLUMN IF NOT EXISTS active_trail_direction TEXT NOT NULL DEFAULT 'N'")
        _CHAINS_SCHEMA_ENSURED = True
    except Exception as e:
        logger.error(f"Failed to ensure user_trail_chains schema: {e}")


# ============================================================================
# COMPUTE — pure functions
# ============================================================================

def _bearing_in_window(bearing: float, window: Tuple[float, float]) -> bool:
    """Is bearing inside the window (handles 360° wrap)."""
    lo, hi = window
    if lo <= hi:
        return lo <= bearing <= hi
    # Wraparound (e.g. N: 315 to 45)
    return bearing >= lo or bearing <= hi


def find_antipode_landmark(base_lat: float, base_lon: float, all_landmarks: List[Dict]) -> Optional[Dict]:
    """Return the landmark whose great-circle distance from base is maximum."""
    best = None
    best_d = -1.0
    for lm in all_landmarks:
        if lm.get('latitude') is None or lm.get('longitude') is None:
            continue
        d = haversine_distance(base_lat, base_lon, float(lm['latitude']), float(lm['longitude']))
        if d > best_d:
            best_d = d
            best = lm
    return best


def _path_satisfies_transit(direction: str, base_lon: float, path_landmarks: List[Dict]) -> bool:
    """Does this path satisfy the polar/equatorial transit constraint for the direction?"""
    if direction == 'N':
        return any(float(lm['latitude']) > POLAR_TRANSIT_LAT for lm in path_landmarks)
    if direction == 'S':
        return any(float(lm['latitude']) < -POLAR_TRANSIT_LAT for lm in path_landmarks)
    # E/W: must transit the opposite-meridian longitude band
    target_lon = (base_lon + 180.0) % 360.0
    if target_lon > 180.0:
        target_lon -= 360.0  # normalize to (-180, 180]
    for lm in path_landmarks:
        lm_lon = float(lm['longitude'])
        if lm_lon > 180.0:
            lm_lon -= 360.0
        # Wrap-aware distance
        diff = abs(lm_lon - target_lon)
        diff = min(diff, 360.0 - diff)
        if diff <= EQUATORIAL_LON_BAND_DEG:
            return True
    return False


def _is_transit_landmark(direction: str, base_lon: float, lm: Dict) -> bool:
    """Does this landmark satisfy the transit constraint for the given direction?"""
    lat = float(lm['latitude'])
    lon = float(lm['longitude'])
    if direction == 'N':
        return lat > POLAR_TRANSIT_LAT
    if direction == 'S':
        return lat < -POLAR_TRANSIT_LAT
    target_lon = (base_lon + 180.0) % 360.0
    if target_lon > 180.0:
        target_lon -= 360.0
    if lon > 180.0:
        lon -= 360.0
    diff = abs(lon - target_lon)
    diff = min(diff, 360.0 - diff)
    return diff <= EQUATORIAL_LON_BAND_DEG


def dijkstra_chain(
    base_lat: float,
    base_lon: float,
    antipode_landmark: Dict,
    direction: str,
    all_landmarks: List[Dict],
    hop_cap: float = HOP_CAP_KM,
) -> List[Dict]:
    """Constrained Dijkstra from base to antipode. Returns ordered hops.

    State-space search: each Dijkstra state is (landmark_name, has_transited).
    `has_transited` flips True when we land on a polar/meridian transit landmark
    for the direction. Goal state is (antipode_name, True). This bakes the
    transit constraint into the search itself rather than post-validating.

    First-hop bearing window enforced from HOME. Edge cap = hop_cap by default;
    if no path exists, retry with OVERSIZE_MAX_KM cap to allow rare long edges.
    """
    antipode_name = antipode_landmark['name']

    by_name = {lm['name']: lm for lm in all_landmarks if lm.get('latitude') is not None}
    bearing_window = DIRECTION_BEARING_WINDOWS[direction]

    def _coords(name: str) -> Tuple[float, float]:
        if name == 'HOME':
            return (base_lat, base_lon)
        lm = by_name.get(name)
        return (float(lm['latitude']), float(lm['longitude']))

    def _neighbors(from_name: str, cap: float, transited: bool = False) -> List[Tuple[Dict, float]]:
        """Eligible next-hops from `from_name` within `cap` km.

        v3 plus-sign refinement (#1414): pre-transit, every candidate landmark must
        also have its BEARING-FROM-BASE inside the cardinal window. This keeps the
        chain hugging the cardinal meridian/parallel before it wraps over the pole
        (or opposite meridian for E/W), producing a clean + shape on the map.
        Post-transit, no bearing constraint — chain routes freely to the antipode.
        """
        from_lat, from_lon = _coords(from_name)
        is_first_hop = (from_name == 'HOME')
        out = []
        for lm in all_landmarks:
            if lm.get('latitude') is None or lm.get('longitude') is None:
                continue
            if lm['name'] == from_name:
                continue
            lat = float(lm['latitude'])
            lon = float(lm['longitude'])
            d = haversine_distance(from_lat, from_lon, lat, lon)
            if d > cap:
                continue
            if is_first_hop:
                b = bearing_deg(from_lat, from_lon, lat, lon)
                if not _bearing_in_window(b, bearing_window):
                    continue
            # Plus-sign constraint: pre-transit, the candidate's bearing FROM BASE must stay
            # in the cardinal corridor. Once transit landmark visited, this drops.
            if not transited and not is_first_hop:
                bearing_from_base = bearing_deg(base_lat, base_lon, lat, lon)
                if not _bearing_in_window(bearing_from_base, bearing_window):
                    continue
            out.append((lm, d))
        return out

    def _run_dijkstra(strict_cap: float, oversize_cap: float = 0.0, max_expansions: int = 500_000) -> Optional[List[str]]:
        """State-space Dijkstra. State = (name, transited, oversize_used).

        - All hops must be ≤ `strict_cap` UNLESS we use the one allowed oversize hop.
        - Oversize hops must be ≤ `oversize_cap` (set to 0 to disable oversize).
        - Goal: reach antipode_name with transited=True.
        - `max_expansions`: safety cap; returns None if exceeded (fallback handles it).
        """
        heap = [(0.0, 0, 'HOME', False, False)]
        # parent[(name, transited, oversize_used)] = (prev tuple, edge_d)
        parent: Dict[Tuple[str, bool, bool], Tuple[Tuple[str, bool, bool], float]] = {}
        best_dist: Dict[Tuple[str, bool, bool], float] = {('HOME', False, False): 0.0}
        counter = 0
        expansions = 0
        while heap:
            expansions += 1
            if expansions > max_expansions:
                logger.warning(f"Dijkstra exceeded {max_expansions} expansions for direction={direction} — abandoning")
                return None
            cum_d, _, cur_name, cur_t, cur_o = heapq.heappop(heap)
            if cur_name == antipode_name and cur_t:
                # Reconstruct path
                path = [cur_name]
                key = (cur_name, cur_t, cur_o)
                while key in parent:
                    prev_key, _e = parent[key]
                    path.append(prev_key[0])
                    key = prev_key
                path.reverse()
                return path
            if cum_d > best_dist.get((cur_name, cur_t, cur_o), float('inf')):
                continue
            # Use oversize_cap as the neighborhood radius so we don't miss long edges,
            # but restrict actually USING those long edges to oversize-allowed transitions.
            search_cap = oversize_cap if (oversize_cap > strict_cap and not cur_o) else strict_cap
            for lm, edge_d in _neighbors(cur_name, search_cap, transited=cur_t):
                is_oversize = edge_d > strict_cap
                # Block oversize edges if budget already spent
                if is_oversize and cur_o:
                    continue
                nxt_o = cur_o or is_oversize
                nxt_t = cur_t or _is_transit_landmark(direction, base_lon, lm)
                new_cum = cum_d + edge_d
                key = (lm['name'], nxt_t, nxt_o)
                if new_cum < best_dist.get(key, float('inf')):
                    best_dist[key] = new_cum
                    counter += 1
                    parent[key] = ((cur_name, cur_t, cur_o), edge_d)
                    heapq.heappush(heap, (new_cum, counter, lm['name'], nxt_t, nxt_o))
        return None

    # First attempt: strict cap, no oversize allowed.
    path_names = _run_dijkstra(hop_cap, oversize_cap=0.0, max_expansions=200_000)
    # Fallback 1: strict cap + ONE oversize hop allowed up to OVERSIZE_MAX_KM.
    if not path_names:
        path_names = _run_dijkstra(hop_cap, oversize_cap=OVERSIZE_MAX_KM, max_expansions=300_000)
    # Fallback 2 (degenerate captains): ignore strict cap entirely, allow all hops up to OVERSIZE_MAX_KM.
    # This always finds a path if one exists at all — used for captains where the constrained search
    # explodes the state space (e.g. some equatorial bases with sparse landmark density along required transit).
    if not path_names:
        logger.warning(f"Dijkstra falling back to all-oversize mode for direction={direction} base=({base_lat:.3f},{base_lon:.3f})")
        path_names = _run_dijkstra(OVERSIZE_MAX_KM, oversize_cap=0.0, max_expansions=500_000)
    if not path_names:
        logger.warning(f"Dijkstra failed direction={direction} base=({base_lat:.3f},{base_lon:.3f}) → {antipode_name}")
        return []

    hops = []
    for i in range(1, len(path_names)):
        a, b = path_names[i-1], path_names[i]
        a_lat, a_lon = _coords(a)
        b_lat, b_lon = _coords(b)
        d = haversine_distance(a_lat, a_lon, b_lat, b_lon)
        hops.append({'from': a, 'to': b, 'distance_km': d})
    return hops


def compute_user_trail_chains(user_id: int) -> Dict[str, List[Dict]]:
    """Compute the 4 cardinal chains for this user's base. Pure — no DB write."""
    from utilities.postgres.map import get_all_mars_mappings, get_or_set_user_mars_home

    base = get_or_set_user_mars_home(user_id)
    base_lat = float(base['latitude'])
    base_lon = float(base['longitude'])

    all_landmarks = get_all_mars_mappings()
    if not all_landmarks:
        logger.error(f"No mars_mappings rows — cannot compute chains for user {user_id}")
        return {'N': [], 'S': [], 'E': [], 'W': []}

    antipode = find_antipode_landmark(base_lat, base_lon, all_landmarks)
    if not antipode:
        logger.error(f"No antipode landmark found for user {user_id}")
        return {'N': [], 'S': [], 'E': [], 'W': []}

    chains = {}
    for direction in ('N', 'S', 'E', 'W'):
        hops = dijkstra_chain(base_lat, base_lon, antipode, direction, all_landmarks)
        chains[direction] = hops
        if hops:
            total_km = sum(h['distance_km'] for h in hops)
            logger.info(f"chain user={user_id} dir={direction} hops={len(hops)} total={total_km:.1f}km → {antipode['name']}")
        else:
            logger.warning(f"chain user={user_id} dir={direction} EMPTY")
    return chains


# ============================================================================
# PERSIST — DB writes
# ============================================================================

def persist_user_trail_chains(user_id: int, chains: Dict[str, List[Dict]]) -> int:
    """INSERT chain rows for user. Idempotent — skips if user already has rows.

    Returns count of rows inserted (0 if user already had chains).
    """
    ensure_user_trail_chains_table()
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("SELECT COUNT(*) AS n FROM pilgrim.user_trail_chains WHERE user_id = %s", (user_id,))
            existing = cur.fetchone()['n']
            if existing > 0:
                logger.info(f"persist_user_trail_chains: user {user_id} already has {existing} rows — skip")
                return 0

            inserted = 0
            for direction, hops in chains.items():
                for idx, hop in enumerate(hops, start=1):
                    cur.execute("""
                        INSERT INTO pilgrim.user_trail_chains
                        (user_id, direction, segment_index, from_landmark, to_landmark, segment_distance_km)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (user_id, direction, idx, hop['from'], hop['to'], hop['distance_km']))
                    inserted += 1
            logger.info(f"persist_user_trail_chains: user {user_id} +{inserted} rows")
            return inserted
    except Exception as e:
        logger.error(f"Failed to persist chains for user {user_id}: {e}")
        return 0


# ============================================================================
# READ — used by crew page, drone cron, ARIA, expedition speed math
# ============================================================================

def _segment_tier(km_built: float, segment_distance_km: float) -> str:
    if segment_distance_km <= 0:
        return 'none'
    ratio = min(1.0, km_built / segment_distance_km)
    label = 'none'
    for thresh, name in SEGMENT_TIERS:
        if ratio >= thresh:
            label = name
    return label


def _chain_prestige_tier(km_built_total: float) -> str:
    label = 'none'
    for thresh, name in CHAIN_PRESTIGE_TIERS:
        if km_built_total >= thresh:
            label = name
    return label


def get_active_chain_segments(user_id: int) -> Dict[str, Dict]:
    """For each direction, return the next unbuilt segment + chain progress summary.

    Result keyed by direction ('N','S','E','W'). Empty dict per direction if no chain.
    """
    ensure_user_trail_chains_table()
    out = {'N': {}, 'S': {}, 'E': {}, 'W': {}}
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT direction,
                       COUNT(*) AS total_segments,
                       SUM(CASE WHEN completed_at IS NOT NULL THEN 1 ELSE 0 END) AS completed_segments,
                       SUM(km_built) AS km_built_total,
                       SUM(segment_distance_km) AS total_km
                FROM pilgrim.user_trail_chains
                WHERE user_id = %s
                GROUP BY direction
            """, (user_id,))
            agg = {r['direction']: dict(r) for r in cur.fetchall()}

            cur.execute("""
                SELECT direction, segment_index, from_landmark, to_landmark, segment_distance_km,
                       km_built, captain_km, scientist_km, aria_km, drone_km, robot_km, completed_at
                FROM pilgrim.user_trail_chains
                WHERE user_id = %s AND completed_at IS NULL
                ORDER BY direction, segment_index
            """, (user_id,))
            next_unbuilt = {}
            for r in cur.fetchall():
                d = r['direction']
                if d not in next_unbuilt:
                    next_unbuilt[d] = dict(r)

        for direction in ('N', 'S', 'E', 'W'):
            agg_row = agg.get(direction)
            if not agg_row:
                continue
            km_built_total = float(agg_row['km_built_total'] or 0)
            total_km = float(agg_row['total_km'] or 0)
            segment = next_unbuilt.get(direction)
            if segment:
                segment['tier'] = _segment_tier(float(segment['km_built'] or 0), float(segment['segment_distance_km']))
            out[direction] = {
                'next_unbuilt': segment,
                'completed_segments': int(agg_row['completed_segments'] or 0),
                'total_segments': int(agg_row['total_segments'] or 0),
                'km_built_total': round(km_built_total, 1),
                'total_km': round(total_km, 1),
                'percent_complete': round((km_built_total / total_km * 100) if total_km else 0, 1),
                'prestige_tier': _chain_prestige_tier(km_built_total),
            }
    except Exception as e:
        logger.error(f"get_active_chain_segments failed for user {user_id}: {e}")
    return out


def get_user_active_direction(user_id: int) -> str:
    """Read pilgrim.users.active_trail_direction; default 'N'."""
    ensure_user_trail_chains_table()
    try:
        with db_cursor() as cur:
            cur.execute("SELECT active_trail_direction FROM pilgrim.users WHERE id = %s", (user_id,))
            row = cur.fetchone()
            d = (row or {}).get('active_trail_direction') or 'N'
            return d if d in ('N', 'S', 'E', 'W') else 'N'
    except Exception as e:
        logger.warning(f"get_user_active_direction failed for user {user_id}: {e}")
        return 'N'


def set_user_active_direction(user_id: int, direction: str) -> bool:
    """Persist captain's active chain direction. Returns True if updated."""
    if direction not in ('N', 'S', 'E', 'W'):
        return False
    ensure_user_trail_chains_table()
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("UPDATE pilgrim.users SET active_trail_direction = %s WHERE id = %s", (direction, user_id))
            return cur.rowcount > 0
    except Exception as e:
        logger.error(f"set_user_active_direction failed for user {user_id}: {e}")
        return False


def add_km_to_active_chain(user_id: int, km: float, source: str) -> Optional[Dict]:
    """Add km to the next unbuilt segment of the user's active chain.

    `source` ∈ {'captain', 'scientist', 'aria', 'drone', 'robot'} — updates that
    column for attribution. Marks segment completed_at when km_built >= segment_distance_km.

    If a segment overflows, carries the leftover km into the next segment in the chain
    (within the same direction). Returns the final segment row state (the last one
    written to), or None if no unbuilt segment exists.
    """
    if km <= 0:
        return None
    if source not in ('captain', 'scientist', 'aria', 'drone', 'robot'):
        logger.warning(f"add_km_to_active_chain: invalid source {source}")
        return None
    ensure_user_trail_chains_table()
    direction = get_user_active_direction(user_id)
    column = f"{source}_km"
    last_state = None
    remaining = km

    try:
        with db_cursor(commit=True) as cur:
            while remaining > 0:
                cur.execute(f"""
                    SELECT segment_index, segment_distance_km, km_built, {column} AS source_km
                    FROM pilgrim.user_trail_chains
                    WHERE user_id = %s AND direction = %s AND completed_at IS NULL
                    ORDER BY segment_index ASC LIMIT 1
                """, (user_id, direction))
                row = cur.fetchone()
                if not row:
                    break  # chain complete
                seg_idx = row['segment_index']
                seg_dist = float(row['segment_distance_km'])
                cur_built = float(row['km_built'] or 0)
                space = max(0.0, seg_dist - cur_built)
                add = min(space, remaining)
                new_built = cur_built + add
                completed = new_built >= seg_dist - 1e-6
                cur.execute(f"""
                    UPDATE pilgrim.user_trail_chains
                    SET km_built = %s,
                        {column} = COALESCE({column}, 0) + %s,
                        completed_at = CASE WHEN %s THEN NOW() ELSE completed_at END
                    WHERE user_id = %s AND direction = %s AND segment_index = %s
                """, (new_built, add, completed, user_id, direction, seg_idx))
                last_state = {
                    'direction': direction,
                    'segment_index': seg_idx,
                    'km_added': add,
                    'km_built': new_built,
                    'segment_distance_km': seg_dist,
                    'completed': completed,
                    'source': source,
                }
                # Bug #21 Deploy C: +0.05 Logistics when a chain segment
                # transitions to completed. Dedupe key: (user, 'trail_segment',
                # f'user_trail_chains:{direction}', segment_index) — each
                # segment in each direction credits at most once.
                if completed:
                    try:
                        from utilities.postgres.captain_stats import award_stat_event
                        ev = award_stat_event(
                            user_id, 'logistics', 0.05,
                            'trail_segment', f'user_trail_chains:{direction}', int(seg_idx),
                        )
                        if ev:
                            last_state.setdefault('stat_events', []).append(ev)
                    except Exception as _e:
                        logger.error(f"Bug #21 trail_segment stat-event failed user={user_id} {direction}#{seg_idx}: {_e}")
                remaining -= add
                if not completed:
                    break
        return last_state
    except Exception as e:
        logger.error(f"add_km_to_active_chain failed user={user_id}: {e}")
        return None


def get_chain_speed_mult_for_destination(user_id: int, destination_name: str) -> float:
    """Speed multiplier for an expedition to `destination_name`.

    If the destination is the `to_landmark` of any segment in any chain, return that
    segment's km-ratio multiplier. Otherwise off-chain → 1.0 (no trail bonus).

    This is the v3 simplification: no more multi-segment compounding across
    arbitrary trail_segments rows. The chain segment IS the trail.
    """
    ensure_user_trail_chains_table()
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT km_built, segment_distance_km
                FROM pilgrim.user_trail_chains
                WHERE user_id = %s AND to_landmark = %s
                ORDER BY km_built DESC LIMIT 1
            """, (user_id, destination_name))
            row = cur.fetchone()
            if not row:
                return 1.0
            km_built = float(row['km_built'] or 0)
            seg_dist = float(row['segment_distance_km'] or 0)
            if seg_dist <= 0:
                return 1.0
            ratio = min(1.0, km_built / seg_dist)
            return round(1.0 + ratio * 0.5, 3)
    except Exception as e:
        logger.warning(f"get_chain_speed_mult_for_destination failed user={user_id} dest={destination_name}: {e}")
        return 1.0


def get_all_user_chains(user_id: int) -> List[Dict]:
    """Return every chain row for the user (used by Chain Math modal + admin)."""
    ensure_user_trail_chains_table()
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT direction, segment_index, from_landmark, to_landmark, segment_distance_km,
                       km_built, captain_km, scientist_km, aria_km, drone_km, robot_km,
                       completed_at, created_at
                FROM pilgrim.user_trail_chains
                WHERE user_id = %s
                ORDER BY direction, segment_index
            """, (user_id,))
            return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.error(f"get_all_user_chains failed user={user_id}: {e}")
        return []
