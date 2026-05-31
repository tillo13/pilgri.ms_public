"""Expedition and discovery item database operations."""

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

from utilities.postgres.core import db_cursor, _fetchone, _fetchall, _get_one, _get_many, _update, _count, ensure_table_columns

logger = logging.getLogger(__name__)


# ============================================================================
# EXPEDITIONS
# ============================================================================

_SIGNAL_CLAIM_COLUMNS_ENSURED = False
_LANDMARK_ID_ENSURED = False


def ensure_landmark_discovery_id():
    """Idempotently give pilgrim.landmark_discoveries a surrogate `id`.

    The table's natural key is (user_id, landmark_name) — it never had an `id`
    column. When Bug #21 added `RETURNING id, (xmax = 0) AS is_new` to
    record_landmark_discovery (for the first-discovery Exploration +1.0 event,
    deduped via the integer source_id in captain_stat_events), every INSERT
    started raising 'column "id" does not exist' — so since then NO new landmark
    was recorded AND the Exploration event never fired. Adding the SERIAL column
    (backfills existing rows) makes RETURNING id valid and the dedup work.
    """
    global _LANDMARK_ID_ENSURED
    if _LANDMARK_ID_ENSURED:
        return
    try:
        # Existence-checked: no lock-grabbing ALTER once `id` exists (same cold-start
        # timeout class as the expeditions columns above).
        ensure_table_columns('pilgrim', 'landmark_discoveries', {'id': 'SERIAL'})
        _LANDMARK_ID_ENSURED = True
    except Exception as e:
        logger.error(f"Failed to ensure landmark_discoveries.id: {e}")

def ensure_signal_claim_columns():
    """Idempotently add Phase 2.3b columns to pilgrim.expeditions.

    Called lazily before any read/write that depends on these columns.
    Safe to call repeatedly — module-level guard avoids redundant queries.
    """
    global _SIGNAL_CLAIM_COLUMNS_ENSURED
    if _SIGNAL_CLAIM_COLUMNS_ENSURED:
        return
    try:
        # Existence-checked (see ensure_table_columns): no ALTER / no ACCESS EXCLUSIVE
        # lock on the hot expeditions table once these columns exist — which was
        # causing 'canceling statement due to statement timeout' noise on cold starts.
        ensure_table_columns('pilgrim', 'expeditions', {
            'expedition_type': "TEXT NOT NULL DEFAULT 'standard'",
            'signal_site_id': "INTEGER",
            'cinematic_shown_at': "TIMESTAMP",
            'cinematic_payload': "JSONB",
        })
        _SIGNAL_CLAIM_COLUMNS_ENSURED = True
    except Exception as e:
        logger.error(f"Failed to ensure signal_claim columns: {e}")


def create_expedition(user_id: int, commander_asset_id: int, destination_name: str, destination_type: str,
                      destination_lat: float, destination_lon: float, distance_km: float, fuel_cost_eth: float,
                      travel_time_seconds: int, commander_stats: dict, vehicle_type: str = 'rover',
                      cargo_capacity: int = 5, expedition_type: str = 'standard',
                      signal_site_id: Optional[int] = None) -> Optional[int]:
    """Create expedition record with round-trip timing.

    Vehicles must travel to destination AND return - discoveries only available after return.
    - arrives_at = when vehicle reaches destination
    - return_arrives_at = when vehicle returns to base with cargo
    - expedition_type: 'standard' or 'signal_claim' (Phase 2.3b — dedicated claim trip, no-fail)
    - signal_site_id: pilgrim.origin_sites.id when expedition_type='signal_claim'
    """
    ensure_signal_claim_columns()
    try:
        with db_cursor(commit=True) as cur:
            # UTC: match how SQL NOW() stores departed_at on the same row.
            # Naive datetime.now() returned local-time on App Engine instances
            # that ran with a non-UTC TZ, producing arrives_at < departed_at
            # by the offset (~5-7h). 56 historical rows patched 2026-04-30.
            now = datetime.utcnow()
            arrives_at = now + timedelta(seconds=travel_time_seconds)
            return_arrives_at = arrives_at + timedelta(seconds=travel_time_seconds)  # Same time back

            cur.execute("""
                INSERT INTO pilgrim.expeditions
                (user_id, commander_asset_id, destination_name, destination_type, destination_lat, destination_lon,
                 distance_km, fuel_cost_eth, arrives_at, return_arrives_at, vehicle_type, cargo_capacity,
                 commander_exploration, commander_leadership, commander_strategy, commander_logistics, commander_charisma,
                 expedition_type, signal_site_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
            """, (user_id, commander_asset_id, destination_name, destination_type, destination_lat, destination_lon,
                  distance_km, fuel_cost_eth, arrives_at, return_arrives_at, vehicle_type, cargo_capacity,
                  commander_stats.get('exploration', 50), commander_stats.get('leadership', 50),
                  commander_stats.get('strategy', 50), commander_stats.get('logistics', 50),
                  commander_stats.get('charisma', 50), expedition_type, signal_site_id))
            result = cur.fetchone()
            expedition_id = result['id'] if result else None
            logger.info(f"✅ Created expedition {expedition_id} to {destination_name} (return at {return_arrives_at}, type={expedition_type})")
            from utilities.postgres.activity import log_activity
            log_activity(user_id, 'expedition', 'expedition_launch', f"Expedition to {destination_name}",
                         amount=float(fuel_cost_eth) * 10000000 if fuel_cost_eth else 0,
                         detail=vehicle_type, source_table='expeditions', source_id=expedition_id,
                         metadata={'distance_km': distance_km, 'vehicle_type': vehicle_type, 'destination': destination_name,
                                   'expedition_type': expedition_type, 'signal_site_id': signal_site_id})
            return expedition_id
    except Exception as e:
        logger.error(f"❌ Failed to create expedition: {e}")
        return None


def get_pending_signal_cinematic(user_id: int) -> Optional[Dict]:
    """Return the oldest completed signal_claim expedition awaiting its cinematic.

    Returns the row with cinematic_payload populated and cinematic_shown_at NULL,
    ordered by completed_at ASC so multiple pending claims play in arrival order.
    """
    ensure_signal_claim_columns()
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT id, user_id, signal_site_id, destination_name, destination_type,
                       cinematic_payload, completed_at
                FROM pilgrim.expeditions
                WHERE user_id = %s
                  AND expedition_type = 'signal_claim'
                  AND status = 'complete'
                  AND cinematic_shown_at IS NULL
                  AND cinematic_payload IS NOT NULL
                ORDER BY completed_at ASC NULLS LAST
                LIMIT 1
            """, (user_id,))
            return cur.fetchone()
    except Exception as e:
        logger.error(f"Failed to get pending signal cinematic: {e}")
        return None


def mark_signal_cinematic_shown(expedition_id: int, user_id: int) -> bool:
    """One-shot: mark cinematic as shown so before_request stops redirecting."""
    ensure_signal_claim_columns()
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE pilgrim.expeditions
                SET cinematic_shown_at = NOW()
                WHERE id = %s AND user_id = %s AND cinematic_shown_at IS NULL
            """, (expedition_id, user_id))
            return cur.rowcount > 0
    except Exception as e:
        logger.error(f"Failed to mark cinematic shown: {e}")
        return False


def write_signal_cinematic_payload(expedition_id: int, payload: Dict) -> bool:
    """Persist the claim/visit result so the cinematic page can render it."""
    ensure_signal_claim_columns()
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE pilgrim.expeditions
                SET cinematic_payload = %s::jsonb
                WHERE id = %s
            """, (json.dumps(payload, default=str), expedition_id))
            return cur.rowcount > 0
    except Exception as e:
        logger.error(f"Failed to write cinematic payload: {e}")
        return False

def get_user_active_expeditions(user_id: int) -> List[Dict]:
    """Get active expeditions for user with destination link from mars_mappings.

    Returns expeditions that are:
    1. Currently traveling (status = 'traveling')
    2. OR completed but have unclaimed discoveries (so user can still claim)

    This ensures the expedition banner stays visible until all discoveries are claimed.
    """
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT e.*, mm.link as destination_link,
                       COALESCE(unclaimed.count, 0) as unclaimed_count,
                       COALESCE(total_disc.count, 0) as total_discovery_count
                FROM pilgrim.expeditions e
                LEFT JOIN pilgrim.mars_mappings mm ON LOWER(e.destination_name) = LOWER(mm.name)
                LEFT JOIN (
                    SELECT expedition_id, COUNT(*) as count
                    FROM pilgrim.expedition_discoveries
                    WHERE claimed_by_user = false
                    GROUP BY expedition_id
                ) unclaimed ON unclaimed.expedition_id = e.id
                LEFT JOIN (
                    SELECT expedition_id, COUNT(*) as count
                    FROM pilgrim.expedition_discoveries
                    GROUP BY expedition_id
                ) total_disc ON total_disc.expedition_id = e.id
                WHERE e.user_id = %s
                  AND (e.status IN ('traveling', 'recalled')
                       OR (e.status = 'complete' AND COALESCE(unclaimed.count, 0) > 0))
                ORDER BY e.departed_at DESC
            """, (user_id,))
            return _fetchall(cur)
    except Exception as e:
        logger.error(f"❌ Failed to get active expeditions: {e}")
        return []

def get_expedition_by_id(expedition_id: int) -> Optional[Dict]:
    """Get expedition by ID"""
    return _get_one('expeditions', 'id = %s', (expedition_id,), 'expedition')

def update_expedition_complete(expedition_id: int, discovery_type: str, sepolia_earned: float, discovery_message: str) -> bool:
    """Mark expedition as complete"""
    return _update('expeditions', 'status = %s, completed_at = NOW(), discovery_type = %s, sepolia_earned = %s, discovery_message = %s',
                   'id = %s', ('complete', discovery_type, sepolia_earned, discovery_message, expedition_id), 'expedition')

def get_user_completed_expeditions_count(user_id):
    """Get count of completed expeditions"""
    return _count('expeditions', "user_id = %s AND status = 'complete'", (user_id,), 'expedition count')

def get_user_visited_locations_count(user_id):
    """Get count of unique locations visited by user"""
    try:
        with db_cursor(dict_cursor=False) as cur:
            cur.execute("SELECT COUNT(DISTINCT destination_name) FROM pilgrim.expeditions WHERE user_id = %s AND status = 'complete'", (user_id,))
            return cur.fetchone()[0]
    except Exception as e:
        logger.error(f"❌ Failed to get visited locations count: {e}")
        return 0


def calculate_expedition_sv(distance_km: float) -> int:
    """Calculate SV earned from expedition distance. Single source of truth."""
    d = float(distance_km)
    if d <= 200:
        sv = 100 + int(d * 0.5)
    elif d <= 500:
        sv = 200 + int((d - 200) * 1.0)
    elif d <= 1500:
        sv = 500 + int((d - 500) * 0.5)
    else:
        sv = 1000 + int((d - 1500) * 0.4)
    return max(100, min(sv, 2000))


def get_last_completed_buggy_expedition(user_id: int) -> Optional[Dict]:
    """Get most recent completed buggy expedition with aggregated discovery stats.
    Used for the 'Last Buggy Expedition' cinematic card on Base HQ."""
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT e.id, e.destination_name, e.destination_type, e.distance_km,
                       e.departed_at, e.completed_at, e.sepolia_earned, e.vehicle_type,
                       e.cargo_capacity, e.discovery_count,
                       COUNT(ed.id) as total_discoveries,
                       SUM(CASE WHEN di.rarity = 'common' THEN 1 ELSE 0 END) as common_count,
                       SUM(CASE WHEN di.rarity = 'uncommon' THEN 1 ELSE 0 END) as uncommon_count,
                       SUM(CASE WHEN di.rarity = 'rare' THEN 1 ELSE 0 END) as rare_count,
                       SUM(CASE WHEN di.rarity = 'legendary' THEN 1 ELSE 0 END) as legendary_count,
                       COALESCE(SUM(ed.enhanced_value * ed.quantity), 0) as total_value,
                       COALESCE(SUM(di.base_scientific_value * ed.quantity), 0) as total_sv_from_items
                FROM pilgrim.expeditions e
                LEFT JOIN pilgrim.expedition_discoveries ed ON ed.expedition_id = e.id
                LEFT JOIN pilgrim.discovery_items di ON ed.discovery_item_id = di.id
                WHERE e.user_id = %s AND e.status = 'complete' AND e.vehicle_type = 'buggy'
                GROUP BY e.id
                ORDER BY e.completed_at DESC
                LIMIT 1
            """, (user_id,))
            row = cur.fetchone()
            if not row:
                return None
            result = dict(row)
            result['sv_earned'] = calculate_expedition_sv(float(result['distance_km']))
            return result
    except Exception as e:
        logger.error(f"❌ Failed to get last buggy expedition: {e}")
        return None


def get_user_expedition_history(user_id: int, limit: int = 50, offset: int = 0) -> Dict:
    """
    Get expedition history with discoveries for user.
    Returns completed expeditions with discovery counts, rarity breakdown, and scientific value.
    """
    try:
        with db_cursor() as cur:
            # Get completed expeditions with aggregated discovery data including rarity counts
            cur.execute("""
                SELECT
                    e.id,
                    e.destination_name,
                    e.destination_type,
                    e.destination_lat,
                    e.destination_lon,
                    e.distance_km,
                    e.departed_at,
                    e.completed_at,
                    e.fuel_cost_eth as sepolia_cost,
                    e.sepolia_earned,
                    mm.link as destination_link,
                    COUNT(ed.id) as discovery_count,
                    COUNT(CASE WHEN ed.claimed_by_user THEN 1 END) as claimed_count,
                    SUM(CASE WHEN ed.claimed_by_user THEN ed.enhanced_value * ed.quantity ELSE 0 END) as total_extracted,
                    EXTRACT(EPOCH FROM (e.completed_at - e.departed_at)) as duration_seconds,
                    -- Rarity breakdown
                    COUNT(CASE WHEN di.rarity = 'common' THEN 1 END) as common_count,
                    COUNT(CASE WHEN di.rarity = 'uncommon' THEN 1 END) as uncommon_count,
                    COUNT(CASE WHEN di.rarity = 'rare' THEN 1 END) as rare_count,
                    COUNT(CASE WHEN di.rarity = 'legendary' THEN 1 END) as legendary_count,
                    -- Scientific value total
                    COALESCE(SUM(di.base_scientific_value * ed.quantity), 0) as total_scientific_value
                FROM pilgrim.expeditions e
                LEFT JOIN pilgrim.expedition_discoveries ed ON ed.expedition_id = e.id
                LEFT JOIN pilgrim.discovery_items di ON ed.discovery_item_id = di.id
                LEFT JOIN pilgrim.mars_mappings mm ON LOWER(e.destination_name) = LOWER(mm.name)
                WHERE e.user_id = %s AND e.status = 'complete'
                GROUP BY e.id, mm.link
                ORDER BY e.completed_at DESC
                LIMIT %s OFFSET %s
            """, (user_id, limit, offset))
            expeditions = _fetchall(cur)

            # Get total count for pagination
            cur.execute("""
                SELECT COUNT(*) as total FROM pilgrim.expeditions
                WHERE user_id = %s AND status = 'complete'
            """, (user_id,))
            total_count = cur.fetchone()['total']

            # Get visit counts per location for grouping
            cur.execute("""
                SELECT destination_name, COUNT(*) as visit_count
                FROM pilgrim.expeditions
                WHERE user_id = %s AND status = 'complete'
                GROUP BY destination_name
                HAVING COUNT(*) > 1
            """, (user_id,))
            multi_visits = {row['destination_name']: row['visit_count'] for row in cur.fetchall()}

            return {
                'expeditions': expeditions,
                'total_count': total_count,
                'limit': limit,
                'offset': offset,
                'multi_visits': multi_visits  # Locations visited more than once
            }
    except Exception as e:
        logger.error(f"❌ Failed to get expedition history: {e}")
        return {'expeditions': [], 'total_count': 0, 'limit': limit, 'offset': offset, 'multi_visits': {}}


def get_expedition_discovery_items(expedition_id: int) -> List[Dict]:
    """Get all discovery items for a specific expedition with item details."""
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT
                    ed.id,
                    ed.found_at_km,
                    ed.nearby_feature,
                    ed.base_value,
                    ed.enhanced_value,
                    ed.quantity,
                    ed.claimed_by_user,
                    ed.analyzed,
                    di.item_name,
                    di.rarity,
                    di.description,
                    di.item_type,
                    di.image_url,
                    di.base_scientific_value
                FROM pilgrim.expedition_discoveries ed
                JOIN pilgrim.discovery_items di ON ed.discovery_item_id = di.id
                WHERE ed.expedition_id = %s
                ORDER BY ed.found_at_km ASC
            """, (expedition_id,))
            return _fetchall(cur)
    except Exception as e:
        logger.error(f"❌ Failed to get expedition discoveries: {e}")
        return []


def record_landmark_discovery(user_id: int, landmark_name: str, landmark_type: str, latitude: float,
                               longitude: float, distance_km: float, sepolia_earned: float, expedition_id: int):
    """Record landmark discovery.

    Returns (landmark_id, is_new) on success, (None, False) on failure.
    Bug #21 callers use is_new + landmark_id for the Exploration +1.0 event;
    revisits dedupe via the (same) landmark_id source_id in captain_stat_events.
    """
    ensure_landmark_discovery_id()
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO pilgrim.landmark_discoveries (user_id, landmark_name, landmark_type, latitude, longitude, distance_km, sepolia_earned, expedition_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, landmark_name) DO UPDATE SET discovered_at = NOW(), sepolia_earned = EXCLUDED.sepolia_earned, expedition_id = EXCLUDED.expedition_id
                RETURNING id, (xmax = 0) AS is_new
            """, (user_id, landmark_name, landmark_type, latitude, longitude, distance_km, sepolia_earned, expedition_id))
            row = cur.fetchone()
            landmark_id = row['id'] if row else None
            is_new = bool(row['is_new']) if row else False
            logger.info(f"✅ Recorded discovery of {landmark_name}")
            from utilities.postgres.activity import log_activity
            log_activity(user_id, 'landmark', 'landmark_discovery', f"Discovered: {landmark_name}",
                         amount=float(sepolia_earned) * 10000000 if sepolia_earned else 0,
                         detail=landmark_type, source_table='landmark_discoveries',
                         metadata={'distance_km': distance_km, 'landmark_type': landmark_type})
            return (landmark_id, is_new)
    except Exception as e:
        logger.error(f"❌ Failed to record discovery: {e}")
        return (None, False)

def get_user_discovered_landmarks(user_id: int) -> List[Dict]:
    """Get all landmarks user has discovered. Memoized per-request."""
    from utilities.postgres.core import request_memo
    return request_memo(
        ('get_user_discovered_landmarks', user_id),
        lambda: _get_many('landmark_discoveries', 'user_id = %s', (user_id,), 'discovered_at DESC', 'discovered landmarks'),
    )


# ============================================================================
# DISCOVERY ITEMS
# ============================================================================

def get_discovery_items_catalog() -> List[Dict]:
    """Get all active discovery items WITH MISSION DATA"""
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT id, item_name, item_type, rarity, description, weight_kg, stackable, preferred_mars_features,
                       min_distance_km, max_distance_km, base_scientific_value, base_trade_value_eth,
                       exploration_enhancement_value, image_url, attributes, mission_source, mission_lat, mission_lon
                FROM pilgrim.discovery_items WHERE active = true
            """)
            return _fetchall(cur)
    except Exception as e:
        logger.error(f"❌ Failed to get discovery items: {e}")
        return []

def create_expedition_discoveries(discoveries: List[Dict]) -> bool:
    """Bulk insert expedition discoveries"""
    try:
        with db_cursor(commit=True) as cur:
            for disc in discoveries:
                cur.execute("""
                    INSERT INTO pilgrim.expedition_discoveries
                    (expedition_id, discovery_item_id, found_at_km, found_at_coordinates, nearby_feature, base_value, enhanced_value, quantity)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (disc['expedition_id'], disc['discovery_item_id'], disc['found_at_km'],
                      json.dumps(disc['found_at_coordinates']), disc['nearby_feature'],
                      disc['base_value'], disc['enhanced_value'], disc['quantity']))
            # Update denormalized discovery_count on expedition
            exp_counts = {}
            for d in discoveries:
                exp_counts[d['expedition_id']] = exp_counts.get(d['expedition_id'], 0) + 1
            for exp_id, count in exp_counts.items():
                cur.execute("UPDATE pilgrim.expeditions SET discovery_count = %s WHERE id = %s", (count, exp_id))
            logger.info(f"Created {len(discoveries)} expedition discoveries")
            return True
    except Exception as e:
        logger.error(f"❌ Failed to create discoveries: {e}")
        return False

def get_expedition_discoveries(expedition_id: int, unlocked_only: bool = False) -> List[Dict]:
    """Get discoveries for expedition"""
    try:
        with db_cursor() as cur:
            query = """
                SELECT ed.*, di.item_name, di.item_type, di.rarity, di.description, di.image_url, di.weight_kg, di.stackable, di.base_scientific_value as scientific_value
                FROM pilgrim.expedition_discoveries ed
                JOIN pilgrim.discovery_items di ON ed.discovery_item_id = di.id
                WHERE ed.expedition_id = %s
            """
            if unlocked_only:
                query += " AND ed.unlocked_at IS NOT NULL"
            query += " ORDER BY ed.found_at_km"
            cur.execute(query, (expedition_id,))
            return _fetchall(cur)
    except Exception as e:
        logger.error(f"❌ Failed to get expedition discoveries: {e}")
        return []

def unlock_discoveries_by_distance(expedition_id: int, current_distance_km: float) -> int:
    """Unlock discoveries at or before current distance"""
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("UPDATE pilgrim.expedition_discoveries SET unlocked_at = NOW() WHERE expedition_id = %s AND found_at_km <= %s AND unlocked_at IS NULL",
                        (expedition_id, current_distance_km))
            return cur.rowcount
    except Exception as e:
        logger.error(f"❌ Failed to unlock discoveries: {e}")
        return 0

def _award_codex_milestones(user_id: int):
    """Bug #1160: fire the codex (found-based) milestone check after a claim. Isolated
    so a milestone failure can NEVER break the claim itself."""
    try:
        from utilities.sv_milestones import check_and_award_codex_milestones
        check_and_award_codex_milestones(user_id)
    except Exception as e:
        logger.warning(f"codex milestone check failed for {user_id} (claim still succeeded): {e}")


def claim_expedition_discovery(discovery_id: int, user_id: int) -> bool:
    """Mark discovery as claimed — only if expedition has returned (complete/recalled)"""
    from utilities.postgres.users import update_user_activity
    claimed = False
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE pilgrim.expedition_discoveries SET claimed_by_user = true, claimed_at = NOW()
                WHERE id = %s AND expedition_id IN (
                    SELECT id FROM pilgrim.expeditions WHERE user_id = %s AND status IN ('complete', 'recalled')
                ) AND claimed_by_user = false
            """, (discovery_id, user_id))
            if cur.rowcount > 0:
                update_user_activity(user_id)
                from utilities.postgres.activity import log_activity
                log_activity(user_id, 'discovery', 'discovery_claimed', f"Claimed discovery #{discovery_id}",
                             source_table='expedition_discoveries', source_id=discovery_id)
                claimed = True
    except Exception as e:
        logger.error(f"❌ Failed to claim discovery: {e}")
        return False
    # Codex check runs POST-COMMIT (outside the with block) so it sees the just-claimed
    # row — a separate pooled connection under READ COMMITTED can't see the uncommitted
    # UPDATE, which would otherwise miss the milestone on the claim that completes it.
    if claimed:
        _award_codex_milestones(user_id)  # bug #1160: a claim can complete a category
    return claimed

def claim_all_pending_discoveries(user_id: int, expedition_id: int = None) -> Dict:
    """Claim ALL unclaimed discoveries for a user at once (optionally for specific expedition).
    Used by email actions and expedition claim_all endpoint.
    """
    from utilities.postgres.users import update_user_activity
    try:
        with db_cursor(commit=True) as cur:
            # Build WHERE clause — only allow claiming from returned expeditions
            if expedition_id:
                where_clause = "e.user_id = %s AND e.id = %s AND e.status IN ('complete', 'recalled') AND ed.claimed_by_user = false AND ed.unlocked_at IS NOT NULL"
                params = (user_id, expedition_id)
            else:
                where_clause = "e.user_id = %s AND e.status IN ('complete', 'recalled') AND ed.claimed_by_user = false AND ed.unlocked_at IS NOT NULL"
                params = (user_id,)

            # First get the count and total value
            cur.execute(f"""
                SELECT COUNT(*) as count, COALESCE(SUM(ed.enhanced_value * ed.quantity), 0) as total_value
                FROM pilgrim.expedition_discoveries ed
                JOIN pilgrim.expeditions e ON ed.expedition_id = e.id
                WHERE {where_clause}
            """, params)
            stats = cur.fetchone()

            # Now claim them all in one UPDATE
            cur.execute(f"""
                UPDATE pilgrim.expedition_discoveries ed
                SET claimed_by_user = true, claimed_at = NOW()
                FROM pilgrim.expeditions e
                WHERE ed.expedition_id = e.id
                  AND {where_clause}
            """, params)

            claimed = stats['count'] if stats else 0
            value = float(stats['total_value']) if stats else 0
            logger.info(f"✅ Batch claimed {claimed} discoveries (value: {value}) for user {user_id}" +
                       (f" expedition {expedition_id}" if expedition_id else ""))

            if claimed > 0:
                update_user_activity(user_id)
    except Exception as e:
        logger.error(f"❌ Failed to claim all discoveries: {e}")
        return {'claimed_count': 0, 'total_value': 0}
    # POST-COMMIT (see claim_expedition_discovery): the batch UPDATE is committed when
    # the with-block exits, so the codex check now sees the just-claimed rows.
    if claimed > 0:
        _award_codex_milestones(user_id)  # bug #1160: batch claim can complete a category
    return {'claimed_count': claimed, 'total_value': value}

def get_user_discovery_codex(user_id: int) -> Dict:
    """Lifetime collection codex (bug #1160): every active discovery item + whether
    this captain has EVER claimed it. FOUND = distinct claimed discovery_item_id,
    regardless of analyzed/sharded state (sharding sets analyzed=true but keeps the
    row), so the codex is permanent + retroactive. ONE LEFT JOIN — keeps /colony
    inside its db-call budget. Grouped by item_type for the category-tabbed grid.
    """
    CATEGORY_ORDER = ['mineral', 'data', 'artifact', 'biological', 'equipment']
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT di.id, di.item_name, di.item_type, di.rarity, di.image_url,
                       (c.discovery_item_id IS NOT NULL) AS collected
                FROM pilgrim.discovery_items di
                LEFT JOIN (
                    SELECT DISTINCT ed.discovery_item_id
                    FROM pilgrim.expedition_discoveries ed
                    JOIN pilgrim.expeditions e ON ed.expedition_id = e.id
                    WHERE e.user_id = %s AND ed.claimed_by_user = true
                ) c ON c.discovery_item_id = di.id
                WHERE di.active = true
                ORDER BY di.item_type, di.rarity, di.item_name
            """, (user_id,))
            rows = cur.fetchall()
        categories = {}
        total_collected = 0
        for r in rows:
            cat = categories.setdefault(r['item_type'], {'items': [], 'collected': 0, 'total': 0})
            found = bool(r['collected'])
            cat['items'].append({
                'id': r['id'], 'item_name': r['item_name'], 'rarity': r['rarity'],
                'image_url': r['image_url'], 'collected': found,
            })
            cat['total'] += 1
            if found:
                cat['collected'] += 1
                total_collected += 1
        # Stable display order; any unknown type lands after the known ones.
        ordered = {k: categories[k] for k in CATEGORY_ORDER if k in categories}
        for k in categories:
            ordered.setdefault(k, categories[k])
        return {'categories': ordered, 'total_collected': total_collected, 'total_items': len(rows)}
    except Exception as e:
        logger.error(f"get_user_discovery_codex failed for {user_id}: {e}")
        return {'categories': {}, 'total_collected': 0, 'total_items': 0}


def get_recent_discoveries_payload(user_id: int) -> Dict:
    """Build the API response for GET /api/expeditions/recent_discoveries."""
    try:
        discoveries = get_recent_discoveries(user_id, limit=3)
        total_unclaimed = get_total_unclaimed_discoveries_count(user_id)
        return {
            'success': True,
            'discoveries': discoveries,
            'count': len(discoveries),
            'total_unclaimed': total_unclaimed,
        }
    except Exception as e:
        import logging as _logging
        _logging.getLogger(__name__).error(f"Failed to get recent discoveries: {e}")
        return {'success': False, 'error': str(e)}


def get_recent_discoveries(user_id: int, limit: int = 5) -> List[Dict]:
    """Get recent unlocked but unclaimed discoveries"""
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT ed.id, ed.expedition_id, ed.found_at_km, ed.found_at_coordinates, ed.nearby_feature,
                       ed.base_value, ed.enhanced_value, ed.quantity, ed.unlocked_at, ed.claimed_by_user, ed.claimed_at,
                       di.item_name, di.item_type, di.rarity, di.description, di.image_url, di.weight_kg,
                       e.destination_name, e.destination_type
                FROM pilgrim.expedition_discoveries ed
                JOIN pilgrim.discovery_items di ON ed.discovery_item_id = di.id
                JOIN pilgrim.expeditions e ON ed.expedition_id = e.id
                WHERE e.user_id = %s AND ed.unlocked_at IS NOT NULL AND ed.claimed_by_user = false
                    AND e.status = 'complete'
                ORDER BY ed.unlocked_at DESC LIMIT %s
            """, (user_id, limit))
            return _fetchall(cur)
    except Exception as e:
        logger.error(f"❌ Failed to get recent discoveries: {e}")
        return []

def get_total_unclaimed_discoveries_count(user_id: int) -> int:
    """Get total count of unclaimed discoveries across all expeditions"""
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) as count
                FROM pilgrim.expedition_discoveries ed
                JOIN pilgrim.expeditions e ON ed.expedition_id = e.id
                WHERE e.user_id = %s AND ed.unlocked_at IS NOT NULL AND ed.claimed_by_user = false
            """, (user_id,))
            result = cur.fetchone()
            return result['count'] if result else 0
    except Exception as e:
        logger.error(f"❌ Failed to get unclaimed count: {e}")
        return 0


def get_total_discovery_count(user_id: int) -> int:
    """Get total count of ALL discoveries in inventory (claimed + unclaimed, not analyzed/sharded).
    This is what Storage Bunker capacity checks against."""
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) as count
                FROM pilgrim.expedition_discoveries ed
                JOIN pilgrim.expeditions e ON ed.expedition_id = e.id
                WHERE e.user_id = %s
                  AND ed.unlocked_at IS NOT NULL
                  AND (ed.analyzed = false OR ed.analyzed IS NULL)
            """, (user_id,))
            result = cur.fetchone()
            return result['count'] if result else 0
    except Exception as e:
        logger.error(f"❌ Failed to get total discovery count: {e}")
        return 0

def get_claimed_discoveries(user_id: int) -> List[Dict]:
    """Get ALL claimed discoveries for user's inventory - STACKED by item (excludes analyzed)

    Also includes legendary items from Origin Site claims.
    """
    try:
        discoveries = []
        with db_cursor() as cur:
            # Regular expedition discoveries
            cur.execute("""
                SELECT di.id as discovery_item_id, di.item_name, di.item_type, di.rarity, di.description,
                       di.image_url, di.weight_kg, di.stackable, di.base_scientific_value,
                       SUM(ed.quantity) as quantity,
                       (SUM(ed.enhanced_value * ed.quantity)::numeric / NULLIF(SUM(ed.quantity), 0)) as enhanced_value,
                       MAX(ed.claimed_at) as claimed_at,
                       MAX(e.destination_name) as destination_name, MAX(ed.found_at_km) as found_at_km
                FROM pilgrim.expedition_discoveries ed
                JOIN pilgrim.discovery_items di ON ed.discovery_item_id = di.id
                JOIN pilgrim.expeditions e ON ed.expedition_id = e.id
                WHERE e.user_id = %s AND ed.claimed_by_user = true AND (ed.analyzed = false OR ed.analyzed IS NULL)
                GROUP BY di.id, di.item_name, di.item_type, di.rarity, di.description, di.image_url, di.weight_kg, di.stackable, di.base_scientific_value
            """, (user_id,))
            discoveries.extend(_fetchall(cur))

            # Origin Site legendary items (from site_claims)
            cur.execute("""
                SELECT
                    -os.id as discovery_item_id,
                    os.legendary_item_name as item_name,
                    'origin fragment' as item_type,
                    'legendary' as rarity,
                    os.legendary_item_description as description,
                    os.legendary_item_image_url as image_url,
                    0.0::numeric as weight_kg,
                    false as stackable,
                    1::bigint as quantity,
                    99999::numeric as enhanced_value,
                    sc.claimed_at as claimed_at,
                    os.mission_name as destination_name,
                    0.0::numeric as found_at_km,
                    os.site_code as site_code,
                    os.founder_commander_name as founder_name,
                    os.founder_wallet_prefix as founder_wallet
                FROM pilgrim.site_claims sc
                JOIN pilgrim.origin_sites os ON sc.origin_site_id = os.id
                WHERE sc.user_id = %s AND sc.site_type = 'origin'
                AND os.legendary_item_name IS NOT NULL
            """, (user_id,))
            origin_items = _fetchall(cur)
            discoveries.extend(origin_items)

        # Sort: legendary first, then by rarity
        rarity_order = {'legendary': 1, 'rare': 2, 'uncommon': 3, 'common': 4}
        discoveries.sort(key=lambda d: (rarity_order.get(d['rarity'], 5), d['item_name']))

        return discoveries
    except Exception as e:
        logger.error(f"❌ Failed to get claimed discoveries: {e}")
        return []

def get_sample_common_discovery() -> Optional[Dict]:
    """Get random common discovery item for preview WITH MISSION DATA"""
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT id, item_name, item_type, rarity, description, weight_kg, stackable, preferred_mars_features,
                       min_distance_km, max_distance_km, base_scientific_value, base_trade_value_eth,
                       exploration_enhancement_value, image_url, mission_source, mission_lat, mission_lon
                FROM pilgrim.discovery_items WHERE rarity = 'common' AND active = true ORDER BY RANDOM() LIMIT 1
            """)
            return _fetchone(cur)
    except Exception as e:
        logger.error(f"❌ Failed to get sample item: {e}")
        return None

def get_all_discovery_items() -> List[Dict]:
    """Get all discovery items for catalog viewer WITH MISSION DATA"""
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT id, item_name, item_type, rarity, description, weight_kg, stackable, preferred_mars_features,
                       min_distance_km, max_distance_km, base_scientific_value, base_trade_value_eth,
                       exploration_enhancement_value, image_url, mission_source, mission_lat, mission_lon
                FROM pilgrim.discovery_items ORDER BY rarity DESC, item_name
            """)
            return _fetchall(cur)
    except Exception as e:
        logger.error(f"❌ Failed to get all items: {e}")
        return []

def get_discovery_item_details(user_id: int, discovery_item_id: int) -> Optional[Dict]:
    """Get detailed history of a specific discovery item including all individual finds (excludes analyzed)

    Negative IDs indicate Origin Site legendary items (ID = -origin_site_id)
    """
    try:
        with db_cursor() as cur:
            # Handle Origin Site legendary items (negative IDs)
            if discovery_item_id < 0:
                origin_site_id = abs(discovery_item_id)
                cur.execute("""
                    SELECT os.id, os.legendary_item_name as item_name, 'origin fragment' as item_type,
                           'legendary' as rarity, os.legendary_item_description as description,
                           0.0 as weight_kg, false as stackable, os.legendary_item_image_url as image_url,
                           os.mission_name, os.site_code, os.founder_commander_name, os.founder_wallet_prefix,
                           sc.claimed_at
                    FROM pilgrim.origin_sites os
                    JOIN pilgrim.site_claims sc ON sc.origin_site_id = os.id
                    WHERE os.id = %s AND sc.user_id = %s AND sc.site_type = 'origin'
                """, (origin_site_id, user_id))
                origin_item = _fetchone(cur)
                if not origin_item:
                    return None
                return {
                    'item': {
                        'id': -origin_item['id'],
                        'item_name': origin_item['item_name'],
                        'item_type': origin_item['item_type'],
                        'rarity': origin_item['rarity'],
                        'description': origin_item['description'],
                        'weight_kg': 0.0,
                        'stackable': False,
                        'image_url': origin_item['image_url'],
                        'preferred_mars_features': origin_item['mission_name'],
                        'min_distance_km': 0,
                        'max_distance_km': 0,
                        'base_scientific_value': 99999,
                        'base_trade_value_eth': 0,
                        'exploration_enhancement_value': 0
                    },
                    'finds': [{
                        'id': origin_site_id,
                        'found_at_km': 0,
                        'found_at_coordinates': None,
                        'nearby_feature': origin_item['mission_name'],
                        'base_value': 99999,
                        'enhanced_value': 99999,
                        'quantity': 1,
                        'unlocked_at': origin_item['claimed_at'],
                        'claimed_at': origin_item['claimed_at'],
                        'destination_name': origin_item['mission_name'],
                        'destination_type': 'origin_site',
                        'departed_at': None,
                        'completed_at': origin_item['claimed_at']
                    }],
                    'total_quantity': 1,
                    'total_value': 99999,
                    'total_weight': 0.0,
                    'first_found': origin_item['claimed_at'],
                    'last_found': origin_item['claimed_at'],
                    'is_origin_legendary': True,
                    'site_code': origin_item['site_code'],
                    'founder_name': origin_item['founder_commander_name'],
                    'founder_wallet': origin_item['founder_wallet_prefix']
                }

            # Regular discovery items
            cur.execute("""
                SELECT ed.id, ed.found_at_km, ed.found_at_coordinates, ed.nearby_feature, ed.base_value, ed.enhanced_value,
                       ed.quantity, ed.unlocked_at, ed.claimed_at, e.destination_name, e.destination_type, e.departed_at, e.completed_at
                FROM pilgrim.expedition_discoveries ed
                JOIN pilgrim.expeditions e ON ed.expedition_id = e.id
                WHERE e.user_id = %s AND ed.discovery_item_id = %s AND ed.claimed_by_user = true AND (ed.analyzed = false OR ed.analyzed IS NULL)
                ORDER BY ed.claimed_at DESC
            """, (user_id, discovery_item_id))
            finds = _fetchall(cur)
            cur.execute("""
                SELECT id, item_name, item_type, rarity, description, weight_kg, stackable, preferred_mars_features,
                       min_distance_km, max_distance_km, base_scientific_value, base_trade_value_eth, exploration_enhancement_value, image_url
                FROM pilgrim.discovery_items WHERE id = %s
            """, (discovery_item_id,))
            item = _fetchone(cur)
            if not item:
                return None
            return {
                'item': item, 'finds': finds,
                'total_quantity': sum(f['quantity'] for f in finds),
                'total_value': sum(f['enhanced_value'] * f['quantity'] for f in finds),
                'total_weight': float(item['weight_kg']) * sum(f['quantity'] for f in finds),
                'first_found': finds[-1]['claimed_at'] if finds else None,
                'last_found': finds[0]['claimed_at'] if finds else None
            }
    except Exception as e:
        logger.error(f"❌ Failed to get discovery details: {e}")
        return None
