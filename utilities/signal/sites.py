"""Origin Sites + Echo Sites + signal page data."""

import logging
import random
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

from utilities.postgres.core import db_cursor
from utilities.mars_math import haversine_distance, offset_coordinates, point_to_path_distance

from utilities.signal.config import (
    ECHO_SPAWN_CHANCE,
    ECHO_PITY_TIMER,
    ECHO_SITE_EXPIRY_DAYS,
    ORIGIN_DETECTION_RADIUS_KM,
    ORIGIN_LOST_SIGNAL_RADIUS_KM,
)

logger = logging.getLogger(__name__)


# ============================================================================
# ORIGIN SITES
# ============================================================================

def get_all_origin_sites() -> List[Dict]:
    """Get all Origin Sites with their status"""
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT id, site_code, mission_name, latitude, longitude,
                       mission_year, mission_country, mission_status, memory_text,
                       founder_user_id, founder_commander_name, founder_sol,
                       founder_tx_hash, founder_claimed_at, is_active,
                       is_lost_signal, unlock_code, unlock_radius_km, founder_wallet_prefix,
                       legendary_item_name, legendary_item_description, legendary_item_image_url
                FROM pilgrim.origin_sites
                ORDER BY mission_year, site_code
            """)
            sites = []
            for row in cur.fetchall():
                # Use unlock_radius_km if set, otherwise default based on lost signal status
                is_lost = row['is_lost_signal'] or False
                radius = row['unlock_radius_km'] or (ORIGIN_LOST_SIGNAL_RADIUS_KM if is_lost else ORIGIN_DETECTION_RADIUS_KM)

                sites.append({
                    'id': row['id'],
                    'site_code': row['site_code'],
                    'mission_name': row['mission_name'],
                    'latitude': float(row['latitude']),
                    'longitude': float(row['longitude']),
                    'mission_year': row['mission_year'],
                    'mission_country': row['mission_country'],
                    'mission_status': row['mission_status'],
                    'memory_text': row['memory_text'],
                    'founder_user_id': row['founder_user_id'],
                    'founder_commander_name': row['founder_commander_name'],
                    'founder_sol': row['founder_sol'],
                    'founder_tx_hash': row['founder_tx_hash'],
                    'founder_claimed_at': row['founder_claimed_at'],
                    'founder_wallet_prefix': row['founder_wallet_prefix'],
                    'is_active': row['is_active'],
                    'is_claimed': row['founder_user_id'] is not None,
                    'is_lost_signal': is_lost,
                    'unlock_code': row['unlock_code'],
                    'unlock_radius_km': radius,
                    'legendary_item_name': row['legendary_item_name'],
                    'legendary_item_description': row['legendary_item_description'],
                    'legendary_item_image_url': row['legendary_item_image_url']
                })
            return sites
    except Exception as e:
        logger.error(f"Failed to get origin sites: {e}")
        return []

def get_origin_site_by_code(site_code: str) -> Optional[Dict]:
    """Get a specific Origin Site by its code"""
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT id, site_code, mission_name, latitude, longitude,
                       mission_year, mission_country, mission_status, memory_text,
                       founder_user_id, founder_commander_name, founder_sol,
                       founder_tx_hash, founder_claimed_at,
                       is_lost_signal, unlock_code, unlock_radius_km, founder_wallet_prefix
                FROM pilgrim.origin_sites
                WHERE site_code = %s
            """, (site_code,))
            row = cur.fetchone()
            if row:
                is_lost = row['is_lost_signal'] or False
                radius = row['unlock_radius_km'] or (ORIGIN_LOST_SIGNAL_RADIUS_KM if is_lost else ORIGIN_DETECTION_RADIUS_KM)

                return {
                    'id': row['id'],
                    'site_code': row['site_code'],
                    'mission_name': row['mission_name'],
                    'latitude': float(row['latitude']),
                    'longitude': float(row['longitude']),
                    'mission_year': row['mission_year'],
                    'mission_country': row['mission_country'],
                    'mission_status': row['mission_status'],
                    'memory_text': row['memory_text'],
                    'founder_user_id': row['founder_user_id'],
                    'founder_commander_name': row['founder_commander_name'],
                    'founder_sol': row['founder_sol'],
                    'founder_tx_hash': row['founder_tx_hash'],
                    'founder_claimed_at': row['founder_claimed_at'],
                    'founder_wallet_prefix': row['founder_wallet_prefix'],
                    'is_lost_signal': is_lost,
                    'unlock_code': row['unlock_code'],
                    'unlock_radius_km': radius,
                    'is_claimed': row['founder_user_id'] is not None
                }
            return None
    except Exception as e:
        logger.error(f"Failed to get origin site {site_code}: {e}")
        return None

def check_origin_site_proximity(base_lat: float, base_lon: float,
                                  dest_lat: float, dest_lon: float) -> Optional[Dict]:
    """Check if an expedition path (base → destination) passes near any unclaimed Origin Site.

    Phase 2 closest-approach: evaluates the full great-circle path, not just the
    destination endpoint. Returns the CLOSEST unclaimed site whose path distance
    is within its own per-site unlock_radius_km, or None if no site is in range.
    """
    sites = get_all_origin_sites()
    closest = None
    closest_distance = float('inf')

    for site in sites:
        if site['is_claimed']:
            continue

        distance = point_to_path_distance(
            site['latitude'], site['longitude'],
            base_lat, base_lon,
            dest_lat, dest_lon
        )
        if distance <= site['unlock_radius_km'] and distance < closest_distance:
            closest_distance = distance
            closest = dict(site)
            closest['distance_km'] = distance

    return closest


# ============================================================================
# ECHO SITES
# ============================================================================

def get_active_echo_sites() -> List[Dict]:
    """Get all active Echo Sites"""
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT id, site_code, latitude, longitude, nearby_landmark,
                       spawned_at, memory_text, total_claims, max_ranked_claims,
                       is_depleted
                FROM pilgrim.echo_sites
                WHERE is_active = TRUE
                AND (expires_at IS NULL OR expires_at > NOW())
                ORDER BY spawned_at DESC
            """)
            sites = []
            for row in cur.fetchall():
                sites.append({
                    'id': row['id'],
                    'site_code': row['site_code'],
                    'latitude': float(row['latitude']),
                    'longitude': float(row['longitude']),
                    'nearby_landmark': row['nearby_landmark'],
                    'spawned_at': row['spawned_at'],
                    'memory_text': row['memory_text'],
                    'total_claims': row['total_claims'],
                    'max_ranked_claims': row['max_ranked_claims'],
                    'is_depleted': row['is_depleted'],
                    'slots_remaining': max(0, row['max_ranked_claims'] - row['total_claims'])
                })
            return sites
    except Exception as e:
        logger.error(f"Failed to get echo sites: {e}")
        return []

def get_recent_echo_claims(limit: int = 10) -> List[Dict]:
    """Get recent Echo Site claims for the /signal page"""
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT sc.commander_name, sc.claim_rank, sc.claim_tier,
                       sc.claimed_at, sc.sol_number,
                       es.site_code, es.memory_text
                FROM pilgrim.site_claims sc
                JOIN pilgrim.echo_sites es ON sc.echo_site_id = es.id
                WHERE sc.site_type = 'echo'
                ORDER BY sc.claimed_at DESC
                LIMIT %s
            """, (limit,))
            claims = []
            for row in cur.fetchall():
                claims.append({
                    'commander_name': row['commander_name'],
                    'claim_rank': row['claim_rank'],
                    'claim_tier': row['claim_tier'],
                    'claimed_at': row['claimed_at'],
                    'sol_number': row['sol_number'],
                    'site_code': row['site_code'],
                    'memory_text': row['memory_text']
                })
            return claims
    except Exception as e:
        logger.error(f"Failed to get recent echo claims: {e}")
        return []

def get_origin_site_visitors(site_id: int) -> Dict:
    """Get visitors for a single Origin Site — prefer _bulk_get_origin_visitors() for multiple sites"""
    result = _bulk_get_origin_visitors([site_id])
    return result.get(site_id, {'founder': None, 'early_witnesses': [], 'pioneers': [], 'pilgrims_count': 0, 'total_visitors': 0})


def _bulk_get_origin_visitors(site_ids: List[int]) -> Dict[int, Dict]:
    """Bulk-fetch visitors for multiple Origin Sites in ONE query. Returns {site_id: visitors_dict}."""
    empty = lambda: {'founder': None, 'early_witnesses': [], 'pioneers': [], 'pilgrims_count': 0, 'total_visitors': 0}
    if not site_ids:
        return {}
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT origin_site_id, commander_name, claim_rank, claim_tier, claimed_at, sol_number
                FROM pilgrim.site_claims
                WHERE site_type = 'origin' AND origin_site_id = ANY(%s)
                ORDER BY origin_site_id, claim_rank ASC
            """, (site_ids,))

            results = {sid: empty() for sid in site_ids}
            for row in cur.fetchall():
                sid = row['origin_site_id']
                rank = row['claim_rank']
                visitor = {
                    'name': row['commander_name'],
                    'rank': rank,
                    'tier': row['claim_tier'],
                    'sol': row['sol_number']
                }
                visitors = results[sid]
                visitors['total_visitors'] += 1

                if rank == 1:
                    visitors['founder'] = visitor
                elif rank <= 3:
                    visitors['early_witnesses'].append(visitor)
                elif rank <= 10:
                    visitors['pioneers'].append(visitor)
                elif rank <= 42:
                    visitors['pilgrims_count'] += 1

            return results
    except Exception as e:
        logger.error(f"Failed to bulk get origin site visitors: {e}")
        return {sid: empty() for sid in site_ids}


def get_expeditions_since_last_echo(user_id: int) -> int:
    """Count expeditions since user's last echo site spawn"""
    try:
        with db_cursor() as cur:
            # Get when this user last spawned an echo site
            cur.execute("""
                SELECT spawned_at FROM pilgrim.echo_sites
                WHERE spawned_by_user_id = %s
                ORDER BY spawned_at DESC
                LIMIT 1
            """, (user_id,))
            row = cur.fetchone()

            if row:
                last_spawn = row['spawned_at']
                # Count expeditions since then
                cur.execute("""
                    SELECT COUNT(*) as cnt FROM pilgrim.expeditions
                    WHERE user_id = %s AND status = 'complete' AND completed_at > %s
                """, (user_id, last_spawn))
            else:
                # Count all completed expeditions (never spawned before)
                cur.execute("""
                    SELECT COUNT(*) as cnt FROM pilgrim.expeditions
                    WHERE user_id = %s AND status = 'complete'
                """, (user_id,))

            result = cur.fetchone()
            return result['cnt'] if result else 0
    except Exception as e:
        logger.error(f"Failed to count expeditions since last echo: {e}")
        return 0


def maybe_spawn_echo_site(
    user_id: int,
    expedition_lat: float,
    expedition_lon: float,
    expedition_id: int = None,
    nearby_landmark: str = None
) -> Optional[Dict]:
    """
    Roll dice for Echo Site spawn with pity timer.
    - 2% base chance per expedition
    - Chance increases linearly toward guaranteed at ECHO_PITY_TIMER expeditions
    - After 50 expeditions without spawn, next one is guaranteed
    """
    # Get expeditions since last echo spawn for this user
    expeditions_since = get_expeditions_since_last_echo(user_id)

    # Calculate effective chance with pity timer
    # Base 2% + linear ramp to 100% at pity timer
    pity_bonus = min(1.0, expeditions_since / ECHO_PITY_TIMER)
    effective_chance = ECHO_SPAWN_CHANCE + (1.0 - ECHO_SPAWN_CHANCE) * pity_bonus

    # Roll the dice
    roll = random.random()
    if roll > effective_chance:
        logger.debug(f"Echo spawn miss: roll {roll:.3f} > chance {effective_chance:.3f} (pity: {expeditions_since}/{ECHO_PITY_TIMER})")
        return None

    logger.info(f"🎲 Echo Site spawn triggered for user {user_id}! (chance was {effective_chance:.1%}, pity: {expeditions_since})")

    try:
        with db_cursor(commit=True) as cur:
            # Generate unique site code
            cur.execute("SELECT COUNT(*) FROM pilgrim.echo_sites")
            count = cur.fetchone()[0]
            site_code = f"ECHO-{count + 1:03d}"

            # Offset location slightly (5-30km in random direction)
            offset_km = random.uniform(5, 30)
            angle = random.uniform(0, 360)
            new_lat, new_lon = offset_coordinates(expedition_lat, expedition_lon, offset_km, angle)

            # Get a random message
            cur.execute("""
                SELECT id, message_text FROM pilgrim.signal_messages
                ORDER BY (usage_count + 1) * RANDOM()
                LIMIT 1
            """)
            msg_row = cur.fetchone()

            if msg_row:
                message_id = msg_row[0]
                memory_text = msg_row[1]

                # Update usage count
                cur.execute("""
                    UPDATE pilgrim.signal_messages
                    SET usage_count = usage_count + 1, last_used_at = NOW()
                    WHERE id = %s
                """, (message_id,))
            else:
                message_id = None
                memory_text = "Fragment corrupted. Data unrecoverable."

            # Create the Echo Site
            expires_at = datetime.now() + timedelta(days=ECHO_SITE_EXPIRY_DAYS)

            cur.execute("""
                INSERT INTO pilgrim.echo_sites
                (site_code, latitude, longitude, nearby_landmark,
                 spawned_by_user_id, spawned_by_expedition_id,
                 message_id, memory_text, expires_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                site_code, new_lat, new_lon, nearby_landmark,
                user_id, expedition_id, message_id, memory_text, expires_at
            ))

            site_id = cur.fetchone()[0]

            logger.info(f"✨ Echo Site {site_code} spawned at {new_lat:.4f}, {new_lon:.4f}")
            from utilities.postgres.activity import log_activity
            log_activity(user_id, 'discovery', 'echo_site_spawn', f"Echo Site Spawned: {site_code}",
                         detail=nearby_landmark or '', source_table='echo_sites', source_id=site_id)

            return {
                'id': site_id,
                'site_code': site_code,
                'latitude': new_lat,
                'longitude': new_lon,
                'nearby_landmark': nearby_landmark,
                'memory_text': memory_text
            }

    except Exception as e:
        logger.error(f"Failed to spawn echo site: {e}")
        return None

def claim_echo_site(
    site_id: int,
    user_id: int,
    commander_name: str,
    expedition_id: int = None,
    tx_hash: str = None
) -> Dict:
    """Claim an Echo Site. Returns claim rank and tier."""
    try:
        with db_cursor(commit=True) as cur:
            # Get site info and current claim count
            cur.execute("""
                SELECT site_code, memory_text, total_claims, max_ranked_claims
                FROM pilgrim.echo_sites
                WHERE id = %s AND is_active = TRUE
                FOR UPDATE
            """, (site_id,))
            row = cur.fetchone()

            if not row:
                return {'success': False, 'error': 'Echo Site not found or inactive'}

            site_code, memory_text, total_claims, max_ranked = row
            new_rank = total_claims + 1

            # Check if user already claimed
            cur.execute("""
                SELECT id FROM pilgrim.site_claims
                WHERE echo_site_id = %s AND user_id = %s
            """, (site_id, user_id))
            if cur.fetchone():
                return {'success': False, 'error': 'You have already claimed this site'}

            # Determine tier based on rank
            if new_rank == 1:
                tier = 'rare'  # First finder
            elif new_rank <= 3:
                tier = 'rare'  # Early finders
            elif new_rank <= 10:
                tier = 'uncommon'  # Regular ranked finders
            else:
                tier = 'common'  # After max ranked

            # Get current sol
            cur.execute("SELECT EXTRACT(EPOCH FROM NOW())::INTEGER / 86400")
            sol = cur.fetchone()[0]

            # Record the claim
            cur.execute("""
                INSERT INTO pilgrim.site_claims
                (site_type, echo_site_id, user_id, commander_name, claim_rank,
                 claim_tier, expedition_id, tx_hash, sol_number)
                VALUES ('echo', %s, %s, %s, %s, %s, %s, %s, %s)
            """, (site_id, user_id, commander_name, new_rank, tier,
                  expedition_id, tx_hash, sol))

            # Update site claim count
            cur.execute("""
                UPDATE pilgrim.echo_sites
                SET total_claims = total_claims + 1,
                    is_depleted = (total_claims + 1 >= %s),
                    updated_at = NOW()
                WHERE id = %s
            """, (max_ranked * 5, site_id))  # Deplete after 5x max ranked

            rank_suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(new_rank, 'th')

            logger.info(f"⚡ Echo Claim: {commander_name} is {new_rank}{rank_suffix} at {site_code} ({tier})")
            from utilities.postgres.activity import log_activity
            log_activity(user_id, 'claim', 'claim_echo', f"Echo Claim: {site_code}",
                         detail=f"Rank #{new_rank} ({tier})", tx_hash=tx_hash or '', source_table='site_claims')

            return {
                'success': True,
                'site_code': site_code,
                'memory_text': memory_text,
                'claim_rank': new_rank,
                'tier': tier,
                'commander_name': commander_name,
                'sol': sol,
                'is_first_finder': new_rank == 1
            }

    except Exception as e:
        logger.error(f"Failed to claim echo site: {e}")
        return {'success': False, 'error': str(e)}

# ============================================================================
# SIGNAL PAGE DATA
# ============================================================================

def get_signal_page_data() -> Dict:
    """Get all data needed for the /signal page"""
    origin_sites = get_all_origin_sites()
    echo_sites = get_active_echo_sites()
    recent_echo_claims = get_recent_echo_claims(10)

    # Calculate stats
    total_origins = len(origin_sites)
    claimed_origins = sum(1 for s in origin_sites if s['is_claimed'])
    total_echoes = len(echo_sites)

    # Get total echo claims ever
    try:
        with db_cursor() as cur:
            cur.execute("SELECT COUNT(*) as cnt FROM pilgrim.site_claims WHERE site_type = 'echo'")
            total_echo_claims = cur.fetchone()['cnt']

            cur.execute("SELECT COUNT(DISTINCT echo_site_id) as cnt FROM pilgrim.site_claims WHERE site_type = 'echo'")
            total_echoes_discovered = cur.fetchone()['cnt']
    except:
        total_echo_claims = 0
        total_echoes_discovered = 0

    # Calculate network reconstruction percentage
    # Origins are worth more: each origin = 5%, each unique echo = 0.1%
    origin_progress = (claimed_origins / total_origins) * 70 if total_origins > 0 else 0
    echo_progress = min(30, total_echoes_discovered * 0.1)
    reconstruction_percent = origin_progress + echo_progress

    # Separate claimed and unclaimed origins for display
    claimed_origin_sites = [s for s in origin_sites if s['is_claimed']]
    unclaimed_origin_sites = [s for s in origin_sites if not s['is_claimed']]

    # Bulk-fetch ALL origin visitors in one query (not per-site)
    all_visitors = _bulk_get_origin_visitors([s['id'] for s in claimed_origin_sites])

    # Build origin memories using bulk-fetched visitors
    origin_memories = []
    for s in claimed_origin_sites:
        visitors = all_visitors.get(s['id'], {'founder': None, 'early_witnesses': [], 'pioneers': [], 'pilgrims_count': 0, 'total_visitors': 0})
        origin_memories.append({
            'site_code': s['site_code'],
            'mission_name': s['mission_name'],
            'founder_name': s['founder_commander_name'],
            'founder_wallet': s.get('founder_wallet_prefix'),
            'sol': s['founder_sol'],
            'memory_text': s['memory_text'],
            'visitors': visitors
        })

    return {
        'origin_sites': origin_sites,
        'claimed_origins': claimed_origin_sites,
        'unclaimed_origins': unclaimed_origin_sites,
        'echo_sites': echo_sites,
        'recent_echo_claims': recent_echo_claims,
        'stats': {
            'total_origins': total_origins,
            'claimed_origins': claimed_origins,
            'unclaimed_origins': total_origins - claimed_origins,
            'total_active_echoes': total_echoes,
            'total_echoes_discovered': total_echoes_discovered,
            'total_echo_claims': total_echo_claims,
            'reconstruction_percent': round(reconstruction_percent, 1)
        },
        'origin_memories': origin_memories,
        'network_complete': claimed_origins == total_origins and total_origins > 0
    }


def generate_blockchain_message(site_type: str, site_code: str, commander_name: str,
                                 rank: int = 1, sol: int = None) -> str:
    """Generate the blockchain message for a site claim"""
    if site_type == 'origin':
        return f"ORIGIN://{site_code}//FOUNDER:{commander_name}//SOL:{sol}"
    else:
        rank_label = "PRIME" if rank == 1 else f"RANK:{rank}"
        return f"ECHO://{site_code}//{rank_label}//FINDER:{commander_name}//SOL:{sol}"


def get_signal_page_render_data(user_id) -> Dict:
    """Full kwargs for rendering signal.html. Includes bonds lookup when user_id is given."""
    signal_data = get_signal_page_data()
    closest_pilgrim = get_closest_pilgrim_to_origin(origin_sites=signal_data.get('origin_sites'))

    bond_fragment_hint = None
    signal_bonds = []
    bond_bonus_state = None
    user_signal_cards = {}
    if user_id:
        try:
            from utilities.aria.bonds import get_bonds_for_display
            signal_bonds = get_bonds_for_display(user_id)
            if signal_bonds:
                bond_fragment_hint = signal_bonds[0]['bond_tx_hash']
        except Exception:
            pass

        try:
            from utilities.aria.bond_bonuses import get_bond_bonus_state_for_user
            bond_bonus_state = get_bond_bonus_state_for_user(user_id)
        except Exception as e:
            logger.warning(f"bond_bonus_state failed user={user_id}: {e}")
            bond_bonus_state = None

        try:
            user_signal_cards = _build_user_signal_cards(user_id)
        except Exception as e:
            logger.warning(f"Failed to build user signal cards for {user_id}: {e}")
            user_signal_cards = {}

    # Phase 2.3c: Puzzle fragments (collected + locked counts for /signal page)
    puzzle_fragments_data = {'collected': [], 'locked': [], 'total': 0, 'collected_count': 0}
    pending_whispers = []
    if user_id:
        try:
            from utilities.signal.puzzle_fragments import get_user_fragments
            puzzle_fragments_data = get_user_fragments(user_id)
            # Whispers that haven't been acknowledged yet — page renders an auto-popup
            from utilities.postgres.core import db_cursor
            with db_cursor() as cur:
                cur.execute("""
                    SELECT pf.id, pf.fragment_code, pf.name, pf.whisper_text, pf.rarity
                    FROM pilgrim.user_puzzle_fragments upf
                    JOIN pilgrim.puzzle_fragments pf ON pf.id = upf.fragment_id
                    WHERE upf.user_id = %s AND upf.whisper_seen_at IS NULL
                    ORDER BY upf.found_at ASC
                """, (user_id,))
                pending_whispers = [dict(r) for r in cur.fetchall()]
        except Exception as e:
            logger.warning(f"Puzzle fragments fetch failed for {user_id}: {e}")

    return {
        'closest_pilgrim': closest_pilgrim,
        'bond_fragment_hint': bond_fragment_hint,
        'signal_bonds': signal_bonds,
        'bond_bonus_state': bond_bonus_state,
        'user_signal_cards': user_signal_cards,
        'puzzle_fragments': puzzle_fragments_data,
        'pending_whispers': pending_whispers,
        **signal_data,
    }


def _build_user_signal_cards(user_id: int) -> Dict[str, Dict]:
    """
    Build per-site signal cards for a user — keyed by node_id for unclaimed,
    site_code for claimed. Each card contains YOUR closest approach, signal
    strength pips, fuzzy direction, and detection history count.
    """
    from utilities.signal.claims import get_user_origin_site_eligibility
    from utilities.postgres.map import get_or_set_user_mars_home
    from utilities.mars_math import (
        point_to_path_distance, bearing_deg, bearing_to_cardinal,
    )

    eligibility = get_user_origin_site_eligibility(user_id)
    base = get_or_set_user_mars_home(user_id)
    base_lat = float(base['latitude'])
    base_lon = float(base['longitude'])

    # Fetch user completed expeditions once for detection-history count
    with db_cursor() as cur:
        cur.execute("""
            SELECT id, destination_name, destination_lat, destination_lon, created_at
            FROM pilgrim.expeditions
            WHERE user_id = %s
            AND status = 'complete'
            AND destination_lat IS NOT NULL
            ORDER BY created_at DESC
        """, (user_id,))
        expeditions = cur.fetchall()

    cards = {}
    for site in eligibility:
        node_id = site['node_id']
        distance = site.get('distance_km')
        radius = site.get('unlock_radius_km') or 42.0

        # Signal strength: 5 pips, filled based on how close user is.
        # Fills when distance/radius <= threshold. At distance=0 → 5 pips.
        # At distance=radius → 1 pip. Beyond radius → fewer.
        pips = 0
        if distance is not None and radius > 0:
            ratio = distance / radius
            if ratio <= 0.2: pips = 5
            elif ratio <= 0.5: pips = 4
            elif ratio <= 1.0: pips = 3
            elif ratio <= 2.0: pips = 2
            elif ratio <= 5.0: pips = 1

        # Fuzzy direction from Base → site. Precision increases as you get closer.
        arrow = ''
        cardinal = ''
        try:
            bearing = bearing_deg(base_lat, base_lon, float(site['latitude']), float(site['longitude']))
            arrow, cardinal = bearing_to_cardinal(bearing)
        except Exception:
            pass

        # Detection history: count user expeditions whose path is within radius
        detection_count = 0
        for exp in expeditions:
            try:
                d = point_to_path_distance(
                    float(site['latitude']), float(site['longitude']),
                    base_lat, base_lon,
                    float(exp['destination_lat']), float(exp['destination_lon'])
                )
                if d <= radius:
                    detection_count += 1
            except Exception:
                continue

        # Fuzzy distance — round more coarsely when far away
        fuzzy_km = None
        if distance is not None:
            if distance < 50: fuzzy_km = round(distance, 1)
            elif distance < 500: fuzzy_km = round(distance / 5) * 5
            else: fuzzy_km = round(distance / 50) * 50

        card = {
            'node_id': node_id,
            'site_code': site['site_code'],
            'mission_name': site['mission_name'],
            'signal_strength': site['signal_strength'],
            'is_claimed': site['is_claimed'],
            'can_claim': site['can_claim'],
            'can_visit': site['can_visit'],
            'has_visited': site['has_visited'],
            'distance_km': distance,
            'fuzzy_km': fuzzy_km,
            'closest_expedition': site.get('closest_expedition'),
            'pips': pips,
            'pips_empty': 5 - pips,
            'arrow': arrow,
            'cardinal': cardinal,
            'detection_count': detection_count,
            'unlock_radius_km': radius,
        }
        cards[node_id] = card
        cards[site['site_code']] = card
    return cards


def get_closest_pilgrim_to_origin(origin_sites: List[Dict] = None) -> Optional[Dict]:
    """
    Find the commander who got closest to any unclaimed Origin Site.
    Accepts pre-fetched origin_sites to avoid duplicate DB call.
    """
    try:
        # Use pre-fetched sites or fetch fresh
        if origin_sites is None:
            origin_sites = get_all_origin_sites()
        unclaimed = [s for s in origin_sites if not s['is_claimed']]

        if not unclaimed:
            logger.info("All origin sites are claimed - no proximity check needed")
            return None

        # Get ALL expeditions with coordinates (any status)
        # Commander names are in replicate_assets, not users table
        with db_cursor() as cur:
            cur.execute("""
                SELECT
                    e.user_id,
                    ra.commander_name,
                    e.destination_lat,
                    e.destination_lon,
                    e.created_at
                FROM pilgrim.expeditions e
                JOIN pilgrim.replicate_assets ra ON e.user_id = ra.user_id
                    AND ra.is_primary_character = true
                    AND ra.is_deleted = false
                WHERE e.destination_lat IS NOT NULL
                AND e.destination_lon IS NOT NULL
                AND ra.commander_name IS NOT NULL
            """)
            rows = cur.fetchall()
            logger.info(f"Proximity check: found {len(rows)} expeditions with coordinates")

        if not rows:
            logger.info("No expeditions with coordinates found")
            return None

        # Find the closest approach across ALL expeditions
        closest = None
        min_distance = float('inf')

        for row in rows:
            try:
                exp_lat = float(row['destination_lat'])
                exp_lon = float(row['destination_lon'])
            except (TypeError, ValueError):
                continue

            for site in unclaimed:
                distance = haversine_distance(exp_lat, exp_lon, site['latitude'], site['longitude'])
                if distance < min_distance:
                    min_distance = distance
                    # Generate the node ID from coordinates (same logic as template)
                    lat_code = f"{int(abs(site['latitude']) * 10):03d}"
                    lon_code = f"{int(abs(site['longitude']) * 10):03d}"
                    node_id = f"NODE-{lat_code}{lon_code}"

                    closest = {
                        'user_id': row['user_id'],
                        'captain_name': row['commander_name'],
                        'distance_km': distance,
                        'node_id': node_id,
                        'site_latitude': site['latitude'],
                        'site_longitude': site['longitude']
                    }

        if closest:
            logger.info(f"Closest captain: {closest['captain_name']} at {closest['distance_km']:.1f}km from {closest['node_id']}")

        return closest

    except Exception as e:
        logger.error(f"Failed to get closest pilgrim to origin: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None
