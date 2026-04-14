"""
Shard Network / Signal System Utilities
Handles the ARG mechanics: Origin Sites, Echo Sites, and the /signal page.

The Shard Network is the distributed memory system that connects all ARIAs.
Sepolia shards are ancient crystalline data storage - each shard a fragment of memory.
Origin Sites (14) are real Mars landing locations - legendary tier.
Echo Sites (unlimited) spawn dynamically from exploration - rare/uncommon tier.
"""

import logging
import random
import math
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

from utilities.postgres_utils import db_cursor

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

ECHO_SPAWN_CHANCE = 0.02  # 2% base chance per expedition
ECHO_PITY_TIMER = 50  # Guaranteed spawn after this many expeditions without one
ECHO_MAX_RANKED_CLAIMS = 10  # First 10 finders get ranked
ECHO_SITE_EXPIRY_DAYS = 7  # Echo sites expire after 7 days
ORIGIN_DETECTION_RADIUS_KM = 42  # Default km radius to claim normal origin sites (42 = Easter egg)
ORIGIN_LOST_SIGNAL_RADIUS_KM = 200  # Km radius for lost signal sites (need decoder first)

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

def check_origin_site_proximity(lat: float, lon: float) -> Optional[Dict]:
    """Check if coordinates are near any unclaimed Origin Site"""
    sites = get_all_origin_sites()

    for site in sites:
        if site['is_claimed']:
            continue

        distance = haversine_distance(lat, lon, site['latitude'], site['longitude'])
        if distance <= ORIGIN_DETECTION_RADIUS_KM:
            site['distance_km'] = distance
            return site

    return None

def claim_origin_site(
    site_id: int,
    user_id: int,
    commander_name: str,
    wallet_address: str = None,
    expedition_id: int = None,
    tx_hash: str = None
) -> Dict:
    """
    Claim an Origin Site as the First Founder.

    The founder display format is: "CommanderName ◆ 0xWALL"
    where 0xWALL is the first 4 chars of the wallet after 0x.
    """
    # Input validation
    if not site_id or not isinstance(site_id, int):
        return {'success': False, 'error': f'Invalid site_id: {site_id}'}
    if not user_id or not isinstance(user_id, int):
        return {'success': False, 'error': f'Invalid user_id: {user_id}'}
    if not commander_name or not isinstance(commander_name, str):
        return {'success': False, 'error': f'Invalid commander_name: {commander_name}'}

    try:
        logger.info(f"[CLAIM] Starting claim for site_id={site_id}, user_id={user_id}, commander={commander_name}")

        # Extract wallet prefix (e.g., "0x570a" from "0x570a1b2c3d...")
        wallet_prefix = None
        if wallet_address and wallet_address.startswith('0x') and len(wallet_address) >= 6:
            wallet_prefix = wallet_address[:6]  # "0x" + first 4 hex chars
        logger.info(f"[CLAIM] Wallet prefix: {wallet_prefix}, expedition_id: {expedition_id}")

        with db_cursor(commit=True) as cur:
            # Check if already claimed
            logger.info("[CLAIM] Step 1: Checking if already claimed...")
            cur.execute(
                "SELECT founder_user_id FROM pilgrim.origin_sites WHERE id = %s",
                (site_id,)
            )
            row = cur.fetchone()
            logger.info(f"[CLAIM] Existing founder check result: {row}")
            if row and row['founder_user_id']:
                return {'success': False, 'error': 'Origin Site already claimed'}

            # Get current sol (game day count)
            logger.info("[CLAIM] Step 2: Getting current sol...")
            cur.execute("SELECT EXTRACT(EPOCH FROM NOW())::INTEGER / 86400 as sol")
            sol_row = cur.fetchone()
            logger.info(f"[CLAIM] Sol row: {sol_row}")
            sol = sol_row['sol']
            logger.info(f"[CLAIM] Sol value: {sol}")

            # Claim the site
            logger.info("[CLAIM] Step 3: Updating origin_sites with claim...")
            cur.execute("""
                UPDATE pilgrim.origin_sites
                SET founder_user_id = %s,
                    founder_commander_name = %s,
                    founder_sol = %s,
                    founder_tx_hash = %s,
                    founder_wallet_prefix = %s,
                    founder_claimed_at = NOW(),
                    updated_at = NOW()
                WHERE id = %s AND founder_user_id IS NULL
                RETURNING site_code, mission_name, memory_text
            """, (user_id, commander_name, sol, tx_hash, wallet_prefix, site_id))

            result = cur.fetchone()
            logger.info(f"[CLAIM] UPDATE result: {result}")
            if not result:
                logger.warning(f"Claim failed for site {site_id} - RETURNING returned nothing")
                return {'success': False, 'error': 'Failed to claim - may already be claimed'}

            # Extract using dict keys (RealDictRow)
            site_code = result['site_code']
            mission_name = result['mission_name']
            memory_text = result['memory_text']
            logger.info(f"[CLAIM] Claimed: {site_code} / {mission_name}")

            # Record in site_claims
            logger.info("[CLAIM] Step 4: Inserting into site_claims...")
            cur.execute("""
                INSERT INTO pilgrim.site_claims
                (site_type, origin_site_id, user_id, commander_name, claim_rank,
                 claim_tier, expedition_id, tx_hash, sol_number)
                VALUES ('origin', %s, %s, %s, 1, 'legendary', %s, %s, %s)
            """, (site_id, user_id, commander_name, expedition_id, tx_hash, sol))
            logger.info("[CLAIM] site_claims INSERT complete")
            from utilities.db_activity import log_activity
            log_activity(user_id, 'claim', 'claim_origin', f"Claimed Origin: {site_code}",
                         detail=mission_name, tx_hash=tx_hash or '', source_table='site_claims')

            # Build founder display string
            founder_display = commander_name
            if wallet_prefix:
                founder_display = f"{commander_name} ◆ {wallet_prefix}"

            logger.info(f"🏆 ORIGIN FOUNDER: {founder_display} claimed {site_code}")

            return {
                'success': True,
                'site_code': site_code,
                'mission_name': mission_name,
                'memory_text': memory_text,
                'founder_name': commander_name,
                'founder_display': founder_display,
                'founder_wallet_prefix': wallet_prefix,
                'sol': sol,
                'tier': 'legendary'
            }

    except Exception as e:
        logger.error(f"Failed to claim origin site: {e}")
        logger.error(f"Exception type: {type(e).__name__}")
        import traceback
        logger.error(traceback.format_exc())
        return {'success': False, 'error': str(e)}


# Visitor tier definitions (no cap - 43+ become Wanderers)
VISITOR_TIERS = {
    # Rank range: (tier_name, tier_color, item_rarity)
    (2, 3): ('Early Witness', '#10b981', 'rare'),      # Green - Rare item
    (4, 10): ('Pioneer', '#3b82f6', 'uncommon'),       # Blue - Uncommon item
    (11, 42): ('Pilgrim', '#8b5cf6', 'common'),        # Purple - Common item
    (43, 99999): ('Wanderer', '#6b7280', 'common'),    # Gray - Common item (no cap)
}

# Visitor reward item definitions
VISITOR_ITEM_CONFIG = {
    'Early Witness': {
        'name_pattern': 'Witness Shard: {mission}',
        'description_pattern': "You stood where {mission} first touched Mars. {mission_year}. One of the first to make the pilgrimage after the Founder. Rank #{rank} Early Witness. Witnessed by {commander} ({wallet}).",
        'flux_prompt': "Cartoon video game item with bold outlines and stylized proportions: glowing amber crystal shard with etched ancient circuit patterns running through it, small holographic inscription floating above showing visitor name, rare artifact quality with golden edges, orange-red Mars glow emanating from within, isolated on red Martian terrain, vibrant colors with reds and oranges reflecting Mars atmosphere, video game asset style",
        'blockchain_msg': "ORIGIN_VISIT #{rank} | {mission} | {commander} | {wallet} | The answer may be 42. You are one of them.",
    },
    'Pioneer': {
        'name_pattern': 'Pioneer Fragment: {mission}',
        'description_pattern': "A pilgrim's memento from {mission}. {mission_year}. You followed in the footsteps of the Founder, carrying forward the legacy. Rank #{rank} Pioneer. Carried by {commander} ({wallet}).",
        'flux_prompt': "Cartoon video game item with bold outlines and stylized proportions: rough-hewn crystal fragment with faint geometric markings etched on surface, blue-purple Sepolia veins visible running through the interior, weathered but treasured pilgrim memento, isolated on red Martian terrain, vibrant colors with reds and oranges reflecting Mars atmosphere, video game asset style",
        'blockchain_msg': "ORIGIN_VISIT #{rank} | {mission} | {commander} | {wallet} | The answer may be 42. You are one of them.",
    },
    'Pilgrim': {
        'name_pattern': 'Pilgrim Stone: {mission}',
        'description_pattern': "You made the journey to {mission}. {mission_year}. The path was long, but you found your way. Rank #{rank} Pilgrim. {commander} ({wallet}) was here.",
        'flux_prompt': "Cartoon video game item with bold outlines and stylized proportions: small polished Mars stone with a single Sepolia crystal chip embedded in center, simple but meaningful pilgrim keepsake, red-orange Martian rock coloring, isolated on red Martian terrain, vibrant colors with reds and oranges reflecting Mars atmosphere, video game asset style",
        'blockchain_msg': "ORIGIN_VISIT #{rank} | {mission} | {commander} | {wallet} | The answer may be 42. You are one of them.",
    },
    'Wanderer': {
        'name_pattern': "Wanderer's Mark: {mission}",
        'description_pattern': "One of many who found their way to {mission}. {mission_year}. The journey matters more than the arrival. Rank #{rank} Wanderer. {commander} ({wallet}) passed through.",
        'flux_prompt': "Cartoon video game item with bold outlines and stylized proportions: worn pebble of compressed Martian dust with tiny crystal fleck embedded, humble traveler token showing signs of a long journey, dusty red-brown coloring, isolated on red Martian terrain, vibrant colors with reds and oranges reflecting Mars atmosphere, video game asset style",
        'blockchain_msg': "ORIGIN_VISIT #{rank} | {mission} | {commander} | {wallet} | A pilgrim passed through.",
    },
}

def get_visitor_tier(rank: int) -> tuple:
    """Get tier info for a visitor rank. Returns (tier_name, tier_color, item_rarity)"""
    for (min_rank, max_rank), tier_info in VISITOR_TIERS.items():
        if min_rank <= rank <= max_rank:
            return tier_info
    return ('Wanderer', '#6b7280', 'common')  # Default for overflow


def visit_origin_site(
    site_id: int,
    user_id: int,
    commander_name: str,
    wallet_address: str = None,
    expedition_id: int = None
) -> Dict:
    """
    Record a pilgrimage visit to an already-claimed Origin Site.

    Visitors receive tiered rewards based on their arrival rank:
    - Rank 2-3: Early Witness → Rare item + blockchain tx
    - Rank 4-10: Pioneer → Uncommon item + blockchain tx
    - Rank 11-42: Pilgrim → Common item + blockchain tx (special "42" message)
    - Rank 43+: Wanderer → Common item + blockchain tx

    All visitors get a unique Flux-generated item with their name engraved.
    Returns visitor rank, tier, and reward item info.
    """
    if not site_id or not isinstance(site_id, int):
        return {'success': False, 'error': f'Invalid site_id: {site_id}'}
    if not user_id or not isinstance(user_id, int):
        return {'success': False, 'error': f'Invalid user_id: {user_id}'}
    if not commander_name:
        return {'success': False, 'error': 'Commander name required'}

    try:
        # Extract wallet prefix for display
        wallet_prefix = None
        if wallet_address and wallet_address.startswith('0x') and len(wallet_address) >= 6:
            wallet_prefix = wallet_address[:6]

        with db_cursor(commit=True) as cur:
            # Check site exists and is claimed
            cur.execute("""
                SELECT id, site_code, mission_name, mission_year, founder_user_id, founder_commander_name
                FROM pilgrim.origin_sites WHERE id = %s
            """, (site_id,))
            site = cur.fetchone()

            if not site:
                return {'success': False, 'error': 'Origin Site not found'}
            if not site['founder_user_id']:
                return {'success': False, 'error': 'This site has not been claimed yet'}
            if site['founder_user_id'] == user_id:
                return {'success': False, 'error': 'You are the founder of this site'}

            # Check if user already visited
            cur.execute("""
                SELECT id FROM pilgrim.site_claims
                WHERE origin_site_id = %s AND user_id = %s AND site_type = 'origin'
            """, (site_id, user_id))
            if cur.fetchone():
                return {'success': False, 'error': 'You have already visited this site'}

            # Get current visitor count to determine rank (NO CAP - unlimited visitors)
            cur.execute("""
                SELECT COUNT(*) as cnt FROM pilgrim.site_claims
                WHERE origin_site_id = %s AND site_type = 'origin'
            """, (site_id,))
            current_count = cur.fetchone()['cnt']
            visitor_rank = current_count + 1  # Next rank (1 = founder, 2+ = visitors)

            # Get tier based on rank
            tier_name, tier_color, item_rarity = get_visitor_tier(visitor_rank)

            # Get current sol
            cur.execute("SELECT EXTRACT(EPOCH FROM NOW())::INTEGER / 86400 as sol")
            sol = cur.fetchone()['sol']

            # Build reward item details from tier config
            tier_config = VISITOR_ITEM_CONFIG.get(tier_name, VISITOR_ITEM_CONFIG['Wanderer'])

            item_name = tier_config['name_pattern'].format(
                mission=site['mission_name']
            )

            item_description = tier_config['description_pattern'].format(
                mission=site['mission_name'],
                mission_year=site['mission_year'] or 'Unknown year',
                rank=visitor_rank,
                commander=commander_name,
                wallet=wallet_prefix or '0x????'
            )

            blockchain_msg = tier_config['blockchain_msg'].format(
                rank=visitor_rank,
                mission=site['mission_name'],
                commander=commander_name,
                wallet=wallet_prefix or '0x????'
            )

            # Special message for rank 42 (the answer!)
            if visitor_rank == 42:
                blockchain_msg = f"ORIGIN_VISIT #42 | {site['mission_name']} | {commander_name} | {wallet_prefix or '0x????'} | You found the answer."

            # Record the visit with item details
            cur.execute("""
                INSERT INTO pilgrim.site_claims
                (site_type, origin_site_id, user_id, commander_name, claim_rank,
                 claim_tier, expedition_id, sol_number, discovery_name, blockchain_message)
                VALUES ('origin', %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (site_id, user_id, commander_name, visitor_rank, tier_name,
                  expedition_id, sol, item_name, blockchain_msg))

            claim_id = cur.fetchone()['id']

            logger.info(f"📍 ORIGIN VISITOR: {commander_name} visited {site['site_code']} as {tier_name} (rank {visitor_rank})")
            from utilities.db_activity import log_activity
            log_activity(user_id, 'claim', 'origin_visit', f"Visited Origin: {site['site_code']}",
                         detail=f"Rank #{visitor_rank} ({tier_name})", source_table='site_claims', source_id=claim_id)

            return {
                'success': True,
                'claim_id': claim_id,
                'site_id': site_id,
                'site_code': site['site_code'],
                'mission_name': site['mission_name'],
                'mission_year': site['mission_year'],
                'founder_name': site['founder_commander_name'],
                'visitor_rank': visitor_rank,
                'tier_name': tier_name,
                'tier_color': tier_color,
                'item_rarity': item_rarity,
                'item_name': item_name,
                'item_description': item_description,
                'blockchain_message': blockchain_msg,
                'flux_prompt': tier_config['flux_prompt'],
                'wallet_prefix': wallet_prefix,
                'sol': sol
            }

    except Exception as e:
        logger.error(f"Failed to record origin site visit: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {'success': False, 'error': str(e)}


def get_user_origin_site_eligibility(user_id: int) -> List[Dict]:
    """
    Check which Origin Sites a user can claim based on their expedition proximity.

    Returns list of sites with eligibility info:
    - can_claim: True if within radius and unclaimed
    - can_visit: True if within radius, claimed by someone else, and user hasn't visited
    - has_visited: True if user has already visited this site
    - closest_expedition: expedition name and distance
    - distance_km: distance from closest expedition
    """
    try:
        sites = get_all_origin_sites()

        # Get user's completed expeditions with their coordinates
        with db_cursor() as cur:
            cur.execute("""
                SELECT e.id, e.destination_name as name, e.destination_lat as latitude,
                       e.destination_lon as longitude, e.destination_name as landmark_name
                FROM pilgrim.expeditions e
                WHERE e.user_id = %s
                AND e.status = 'complete'
                AND e.destination_lat IS NOT NULL
            """, (user_id,))
            expeditions = cur.fetchall()

            # Get sites this user has already visited/claimed
            cur.execute("""
                SELECT origin_site_id FROM pilgrim.site_claims
                WHERE user_id = %s AND site_type = 'origin'
            """, (user_id,))
            visited_sites = {row['origin_site_id'] for row in cur.fetchall()}

        result = []
        for site in sites:
            has_visited = site['id'] in visited_sites

            # Generate node_id matching Signal page format
            lat_code = f"{int(abs(site['latitude']) * 10):03d}"
            lon_code = f"{int(abs(site['longitude']) * 10):03d}"
            node_id = f"NODE-{lat_code}{lon_code}"

            # Signal strength from mission_status (matches Signal page)
            ms = site.get('mission_status', '')
            if ms == 'successful':
                signal_strength = 'Strong'
            elif ms == 'crashed':
                signal_strength = 'Fragmented'
            else:
                signal_strength = 'Faint'

            site_info = {
                'id': site['id'],
                'site_code': site['site_code'],
                'mission_name': site['mission_name'],
                'node_id': node_id,
                'signal_strength': signal_strength,
                'latitude': site['latitude'],
                'longitude': site['longitude'],
                'is_claimed': site['is_claimed'],
                'is_lost_signal': site['is_lost_signal'],
                'unlock_radius_km': site['unlock_radius_km'],
                'founder_commander_name': site.get('founder_commander_name'),
                'founder_wallet_prefix': site.get('founder_wallet_prefix'),
                'founder_user_id': site.get('founder_user_id'),
                'legendary_item_name': site.get('legendary_item_name'),
                'legendary_item_description': site.get('legendary_item_description'),
                'legendary_item_image_url': site.get('legendary_item_image_url'),
                'can_claim': False,
                'can_visit': False,
                'has_visited': has_visited,
                'closest_expedition': None,
                'distance_km': None
            }

            # Find closest expedition to this site
            min_distance = float('inf')
            closest_exp = None

            for exp in expeditions:
                dist = haversine_distance(
                    float(exp['latitude']), float(exp['longitude']),
                    site['latitude'], site['longitude']
                )
                if dist < min_distance:
                    min_distance = dist
                    closest_exp = exp

            if closest_exp:
                site_info['distance_km'] = round(min_distance, 1)
                site_info['closest_expedition'] = {
                    'id': closest_exp['id'],
                    'name': closest_exp['name'],
                    'landmark': closest_exp['landmark_name']
                }

                # Check if within claiming radius
                radius = site['unlock_radius_km']
                within_radius = min_distance <= radius

                if within_radius and not site['is_claimed']:
                    site_info['can_claim'] = True
                elif within_radius and site['is_claimed'] and not has_visited:
                    # Can visit if: within range, already claimed, and user hasn't visited yet
                    # Also check user isn't the founder
                    if site.get('founder_user_id') != user_id:
                        site_info['can_visit'] = True

            result.append(site_info)

        return result

    except Exception as e:
        logger.error(f"Failed to get origin site eligibility: {e}")
        return []


def get_user_origin_site_discovery_count(user_id: int) -> Dict:
    """
    Get count of Origin Sites user has discovered (has expedition within range).
    Used for the nav dropdown to show "X/14 Origin Sites" link.

    Returns:
        {'discovered': X, 'total': 14, 'show_link': True/False}
    """
    try:
        eligibility = get_user_origin_site_eligibility(user_id)
        # Count sites where user has an expedition close enough (distance_km is set)
        discovered = sum(1 for s in eligibility if s.get('distance_km') is not None and s['distance_km'] <= s['unlock_radius_km'])
        return {
            'discovered': discovered,
            'total': 14,
            'show_link': discovered > 0
        }
    except Exception as e:
        logger.error(f"Failed to get origin site discovery count: {e}")
        return {'discovered': 0, 'total': 14, 'show_link': False}


def get_claimable_origin_sites_for_user(user_id: int) -> List[Dict]:
    """Get only the Origin Sites a user can currently claim."""
    all_sites = get_user_origin_site_eligibility(user_id)
    return [s for s in all_sites if s['can_claim']]


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
            from utilities.db_activity import log_activity
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
            from utilities.db_activity import log_activity
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

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

from utilities.mars_math import haversine_distance, offset_coordinates  # noqa: E402

def generate_blockchain_message(site_type: str, site_code: str, commander_name: str,
                                 rank: int = 1, sol: int = None) -> str:
    """Generate the blockchain message for a site claim"""
    if site_type == 'origin':
        return f"ORIGIN://{site_code}//FOUNDER:{commander_name}//SOL:{sol}"
    else:
        rank_label = "PRIME" if rank == 1 else f"RANK:{rank}"
        return f"ECHO://{site_code}//{rank_label}//FINDER:{commander_name}//SOL:{sol}"


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


# ============================================================================
# LEGENDARY ITEM GENERATION
# ============================================================================

def generate_legendary_item_for_origin(
    site_id: int,
    founder_name: str,
    founder_wallet_prefix: str
) -> Optional[Dict]:
    """
    Generate the legendary item image for an Origin Site after it's claimed.
    This uses Flux to create a unique artifact and stores it in GCS.

    Called in a background thread after claim_origin_site() succeeds.

    Args:
        site_id: The origin site ID
        founder_name: The founder's commander name
        founder_wallet_prefix: The founder's wallet prefix (e.g., "0x570a")

    Returns:
        Dict with image_url and item details, or None on failure
    """
    try:
        # Get the site's legendary item definition
        with db_cursor() as cur:
            cur.execute("""
                SELECT site_code, legendary_item_name, legendary_item_description,
                       legendary_item_flux_prompt, legendary_item_image_url
                FROM pilgrim.origin_sites
                WHERE id = %s
            """, (site_id,))
            row = cur.fetchone()

        if not row:
            logger.error(f"Origin site {site_id} not found for legendary generation")
            return None

        site_code = row['site_code']
        item_name = row['legendary_item_name']
        item_description = row['legendary_item_description']
        flux_prompt = row['legendary_item_flux_prompt']
        existing_image = row['legendary_item_image_url']

        # If already has an image, skip generation
        if existing_image:
            logger.info(f"Legendary item for {site_code} already has image, skipping")
            return {
                'site_code': site_code,
                'item_name': item_name,
                'image_url': existing_image,
                'already_exists': True
            }

        if not flux_prompt:
            logger.error(f"No Flux prompt defined for {site_code}")
            return None

        logger.info(f"Generating legendary item image for {site_code}: {item_name}")

        # Generate the image using Flux
        from utilities.flux_utils import FluxGenerator
        from utilities.google_cloud_storage_utils import upload_blob_from_url
        from config import FLUX_MODEL
        import time

        generator = FluxGenerator()

        # Build the founder inscription text
        # Format: "FOUNDED BY Andy ◆ 0x570a" engraved on the artifact
        founder_text = founder_name or "Unknown"
        if founder_wallet_prefix:
            founder_text = f"{founder_name} {founder_wallet_prefix}"

        # Append the engraving requirement to the Flux prompt
        # This ensures the text appears visibly engraved on the artifact
        engraved_prompt = f"{flux_prompt}, with clearly visible engraved golden text inscription reading 'FOUNDER: {founder_text}' carved prominently into the artifact surface, the text should be legible and stand out"

        logger.info(f"Flux prompt with engraving: {engraved_prompt[:100]}...")

        # Use the project's standard Flux model (flux-kontext-pro) with just a prompt
        # The prompt already follows the Mars-material aesthetic from CLAUDE.md
        try:
            output = generator.client.run(
                FLUX_MODEL,
                input={"prompt": engraved_prompt}
            )
        except Exception as e:
            logger.error(f"Flux generation failed for {site_code}: {e}")
            return None

        if not output:
            logger.error(f"Flux returned no output for {site_code}")
            return None

        # Get the image URL from Replicate
        if isinstance(output, list) and len(output) > 0:
            replicate_url = str(output[0])
        elif hasattr(output, 'url'):
            replicate_url = output.url
        else:
            replicate_url = str(output)

        logger.info(f"Flux generated image: {replicate_url[:60]}...")

        # Save to GCS with permanent URL
        timestamp = int(time.time())
        blob_name = f"legendary_items/{site_code.lower()}_{timestamp}.png"
        gcs_url = upload_blob_from_url(replicate_url, blob_name, content_type='image/png')

        if not gcs_url:
            logger.error(f"Failed to upload legendary item to GCS for {site_code}")
            return None

        logger.info(f"Legendary item saved to GCS: {gcs_url}")

        # Update the origin_sites record with the image URL
        # Also personalize the description with founder info
        personalized_description = item_description
        if founder_name:
            personalized_description = personalized_description.replace(
                '{founder_name}', founder_name
            )
        if founder_wallet_prefix:
            personalized_description = personalized_description.replace(
                '{founder_wallet}', founder_wallet_prefix
            )

        with db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE pilgrim.origin_sites
                SET legendary_item_image_url = %s,
                    legendary_item_description = %s,
                    updated_at = NOW()
                WHERE id = %s
            """, (gcs_url, personalized_description, site_id))

        logger.info(f"Legendary item for {site_code} complete: {item_name}")

        return {
            'site_code': site_code,
            'item_name': item_name,
            'item_description': personalized_description,
            'image_url': gcs_url,
            'already_exists': False
        }

    except Exception as e:
        logger.error(f"Failed to generate legendary item for site {site_id}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None


def get_origin_site_legendary_item(site_id: int) -> Optional[Dict]:
    """
    Get the legendary item details for an Origin Site.
    Used by the Signal page and claim modal.
    """
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT site_code, mission_name, legendary_item_name,
                       legendary_item_description, legendary_item_image_url,
                       founder_commander_name, founder_wallet_prefix
                FROM pilgrim.origin_sites
                WHERE id = %s
            """, (site_id,))
            row = cur.fetchone()

        if not row:
            return None

        return {
            'site_code': row['site_code'],
            'mission_name': row['mission_name'],
            'item_name': row['legendary_item_name'],
            'item_description': row['legendary_item_description'],
            'image_url': row['legendary_item_image_url'],
            'founder_name': row['founder_commander_name'],
            'founder_wallet_prefix': row['founder_wallet_prefix'],
            'has_image': row['legendary_item_image_url'] is not None
        }

    except Exception as e:
        logger.error(f"Failed to get legendary item for site {site_id}: {e}")
        return None


# ============================================================================
# ROUTE HANDLERS - Business logic for thin routes in app.py
# ============================================================================

def _get_commander_name_for_user(user_id: int) -> Optional[str]:
    """Get commander name - tries primary, then most recent."""
    from utilities.postgres_utils import get_primary_commander

    commander = get_primary_commander(user_id)
    if commander and commander.get('commander_name'):
        return commander['commander_name']

    # Fallback: get most recent commander with a name
    with db_cursor() as cur:
        cur.execute("""
            SELECT commander_name FROM pilgrim.replicate_assets
            WHERE user_id = %s AND asset_type = 'character_image'
            AND commander_name IS NOT NULL AND is_deleted = false
            ORDER BY created_at DESC LIMIT 1
        """, (user_id,))
        row = cur.fetchone()
        return row['commander_name'] if row else None


def handle_origin_site_claim(user_id: int, site_id: int, session) -> Dict:
    """
    Full origin site claim handler - validates, claims, fires background tasks.
    Returns result dict for JSON response.
    """
    import threading
    from utilities.postgres_utils import get_user_primary_sepolia_wallet
    from utilities.sepolia_utils import MarsAsteroidMiner

    commander_name = _get_commander_name_for_user(user_id)
    if not commander_name:
        return {'success': False, 'error': 'Commander required to claim sites'}

    # Check eligibility
    eligibility = get_user_origin_site_eligibility(user_id)
    site_eligibility = next((s for s in eligibility if s['id'] == site_id), None)

    if not site_eligibility:
        return {'success': False, 'error': 'Origin Site not found'}

    if site_eligibility['is_claimed']:
        return {'success': False, 'error': 'Origin Site already claimed by another pilgrim'}

    if not site_eligibility['can_claim']:
        distance = site_eligibility.get('distance_km')
        radius = site_eligibility.get('unlock_radius_km', 42)
        if distance:
            return {'success': False, 'error': f'Your closest expedition is {distance}km away. Must be within {radius}km to claim.'}
        return {'success': False, 'error': 'No expeditions found near this Origin Site'}

    # Get wallet and sol for message
    primary_wallet = get_user_primary_sepolia_wallet(user_id)
    wallet_address = primary_wallet['wallet_address'] if primary_wallet else None

    with db_cursor() as cur:
        cur.execute("SELECT EXTRACT(EPOCH FROM NOW())::INTEGER / 86400 as sol")
        sol = cur.fetchone()['sol']

    site_code = site_eligibility['site_code']
    origin_message = f"ORIGIN://{site_code}//FOUNDER:{commander_name}//SIG:{wallet_address or 'UNKNOWN'}//SOL:{sol}"

    expedition_id = None
    if site_eligibility.get('closest_expedition'):
        expedition_id = site_eligibility['closest_expedition'].get('id')

    logger.info(f"Claiming {site_code} for {commander_name} (user {user_id}, expedition {expedition_id})")

    # Claim in database
    result = claim_origin_site(
        site_id=site_id,
        user_id=user_id,
        commander_name=commander_name,
        wallet_address=wallet_address,
        expedition_id=expedition_id
    )

    if not result.get('success'):
        return result

    # Fire blockchain transaction in background
    if primary_wallet:
        def do_origin_blockchain_tx():
            try:
                miner = MarsAsteroidMiner()
                if not miner.connect():
                    logger.error("Origin claim blockchain tx failed: Could not connect")
                    return

                claim_fee_eth = 0.000001
                burn_address = '0x000000000000000000000000000000000000dEaD'
                gas_config = miner.gas_estimator.get_optimal_gas_price(use_dynamic=True, manual_gwei=1, speed='standard')
                transaction = miner.transaction_manager.create_transfer_transaction(
                    from_address=primary_wallet['wallet_address'],
                    to_address=burn_address,
                    amount_eth=claim_fee_eth,
                    gas_config=gas_config,
                    custom_message=origin_message,
                    context="origin_claim"
                )
                tx_hash = miner.transaction_manager.sign_and_send_transaction(
                    transaction=transaction,
                    private_key=primary_wallet['wallet_private_key'],
                    context="origin_claim"
                )
                if tx_hash:
                    with db_cursor(commit=True) as cur:
                        cur.execute("UPDATE pilgrim.origin_sites SET founder_tx_hash = %s, updated_at = NOW() WHERE id = %s", (tx_hash, site_id))
                        cur.execute("UPDATE pilgrim.site_claims SET tx_hash = %s WHERE origin_site_id = %s AND user_id = %s", (tx_hash, site_id, user_id))
                    logger.info(f"Origin claim tx recorded: {tx_hash}")
            except Exception as e:
                logger.error(f"Origin claim blockchain tx failed: {e}")

        threading.Thread(target=do_origin_blockchain_tx).start()

    # Generate legendary item in background
    wallet_prefix = result.get('founder_wallet_prefix') or (wallet_address[:6] if wallet_address else None)

    def do_legendary_item_generation():
        try:
            legendary_result = generate_legendary_item_for_origin(site_id=site_id, founder_name=commander_name, founder_wallet_prefix=wallet_prefix)
            if legendary_result:
                logger.info(f"Legendary item generated: {legendary_result.get('item_name')}")
        except Exception as e:
            logger.error(f"Legendary item generation error: {e}")

    threading.Thread(target=do_legendary_item_generation).start()

    result['legendary_item'] = {
        'name': site_eligibility.get('legendary_item_name', 'Legendary Artifact'),
        'status': 'generating',
        'message': 'Your legendary artifact is being forged...'
    }

    # Invalidate caches
    session.pop('_bal', None)
    session.pop('_org', None)
    session.modified = True

    return result


def handle_origin_site_visit(user_id: int, site_id: int, session) -> Dict:
    """
    Full origin site visit handler - validates, records visit, fires background tasks.

    Background tasks:
    1. Blockchain transaction with tiered message
    2. Flux image generation for reward item
    """
    import threading
    from utilities.postgres_utils import get_user_primary_sepolia_wallet
    from utilities.sepolia_utils import MarsAsteroidMiner

    commander_name = _get_commander_name_for_user(user_id)
    if not commander_name:
        return {'success': False, 'error': 'Commander required to visit sites'}

    eligibility = get_user_origin_site_eligibility(user_id)
    site_eligibility = next((s for s in eligibility if s['id'] == site_id), None)

    if not site_eligibility:
        return {'success': False, 'error': 'Origin Site not found'}

    if not site_eligibility['is_claimed']:
        return {'success': False, 'error': 'This site has not been claimed yet'}

    if site_eligibility['has_visited']:
        return {'success': False, 'error': 'You have already visited this site'}

    if not site_eligibility['can_visit']:
        distance = site_eligibility.get('distance_km')
        radius = site_eligibility.get('unlock_radius_km', 42)
        if distance:
            return {'success': False, 'error': f'Your closest expedition is {distance}km away. Must be within {radius}km to visit.'}
        return {'success': False, 'error': 'No expeditions found near this Origin Site'}

    # Get wallet for blockchain tx and item engraving
    primary_wallet = get_user_primary_sepolia_wallet(user_id)
    wallet_address = primary_wallet.get('wallet_address') if primary_wallet else None

    expedition_id = None
    if site_eligibility.get('closest_expedition'):
        expedition_id = site_eligibility['closest_expedition'].get('id')

    # Record the visit (now includes wallet for item personalization)
    result = visit_origin_site(
        site_id=site_id,
        user_id=user_id,
        commander_name=commander_name,
        wallet_address=wallet_address,
        expedition_id=expedition_id
    )

    if not result.get('success'):
        return result

    claim_id = result.get('claim_id')

    # Fire blockchain transaction in background
    if primary_wallet and claim_id:
        def do_visitor_blockchain_tx():
            try:
                miner = MarsAsteroidMiner()
                if not miner.connect():
                    logger.error("Origin visit blockchain tx failed: Could not connect")
                    return

                visit_fee_eth = 0.000001  # Tiny fee for permanent record
                burn_address = '0x000000000000000000000000000000000000dEaD'
                gas_config = miner.gas_estimator.get_optimal_gas_price(use_dynamic=True, manual_gwei=1, speed='standard')

                # Include the tiered blockchain message
                blockchain_msg = result.get('blockchain_message', f"ORIGIN_VISIT | {result.get('site_code')}")

                transaction = miner.transaction_manager.create_transfer_transaction(
                    from_address=primary_wallet['wallet_address'],
                    to_address=burn_address,
                    amount_eth=visit_fee_eth,
                    gas_config=gas_config,
                    data_message=blockchain_msg
                )
                tx_hash = miner.transaction_manager.sign_and_send_transaction(
                    transaction=transaction,
                    private_key=primary_wallet['wallet_private_key'],
                    context="origin_visit"
                )
                if tx_hash:
                    with db_cursor(commit=True) as cur:
                        cur.execute(
                            "UPDATE pilgrim.site_claims SET tx_hash = %s WHERE id = %s",
                            (tx_hash, claim_id)
                        )
                    logger.info(f"Origin visit tx recorded: {tx_hash}")
            except Exception as e:
                logger.error(f"Origin visit blockchain tx failed: {e}")

        threading.Thread(target=do_visitor_blockchain_tx).start()

    # Generate Flux image in background
    if claim_id:
        def do_visitor_flux_generation():
            try:
                image_result = generate_visitor_reward_image(
                    claim_id=claim_id,
                    commander_name=commander_name,
                    wallet_prefix=result.get('wallet_prefix'),
                    tier_name=result.get('tier_name'),
                    flux_prompt=result.get('flux_prompt'),
                    site_code=result.get('site_code')
                )
                if image_result:
                    logger.info(f"Visitor reward image generated for claim {claim_id}")
            except Exception as e:
                logger.error(f"Visitor reward image generation failed: {e}")

        threading.Thread(target=do_visitor_flux_generation).start()

    # Invalidate caches
    session.pop('_org', None)
    session.modified = True

    return result


def generate_visitor_reward_image(
    claim_id: int,
    commander_name: str,
    wallet_prefix: str,
    tier_name: str,
    flux_prompt: str,
    site_code: str
) -> Optional[Dict]:
    """
    Generate a unique Flux image for a visitor's reward item.
    Called in background thread after visit_origin_site() succeeds.
    """
    try:
        if not flux_prompt:
            logger.error(f"No Flux prompt for visitor reward {claim_id}")
            return None

        logger.info(f"Generating visitor reward image for {commander_name} at {site_code}")

        from utilities.flux_utils import FluxGenerator
        from utilities.google_cloud_storage_utils import upload_blob_from_url
        from config import FLUX_MODEL
        import time

        generator = FluxGenerator()

        # Add visitor name to prompt for personalization
        visitor_text = commander_name
        if wallet_prefix:
            visitor_text = f"{commander_name} {wallet_prefix}"

        engraved_prompt = f"{flux_prompt}, with small engraved text '{visitor_text}' subtly visible on the surface"

        logger.info(f"Flux prompt: {engraved_prompt[:80]}...")

        try:
            output = generator.client.run(
                FLUX_MODEL,
                input={"prompt": engraved_prompt}
            )
        except Exception as e:
            logger.error(f"Flux generation failed for visitor {claim_id}: {e}")
            return None

        if not output:
            logger.error(f"Flux returned no output for visitor {claim_id}")
            return None

        # Get the image URL from Replicate
        if isinstance(output, list) and len(output) > 0:
            replicate_url = str(output[0])
        elif hasattr(output, 'url'):
            replicate_url = output.url
        else:
            replicate_url = str(output)

        logger.info(f"Flux generated image: {replicate_url[:60]}...")

        # Save to GCS
        timestamp = int(time.time())
        tier_slug = tier_name.lower().replace(' ', '_')
        blob_name = f"origin_visitor_rewards/{site_code.lower()}_{tier_slug}_{claim_id}_{timestamp}.png"
        gcs_url = upload_blob_from_url(replicate_url, blob_name, content_type='image/png')

        if not gcs_url:
            logger.error(f"Failed to upload visitor reward to GCS for claim {claim_id}")
            return None

        logger.info(f"Visitor reward saved to GCS: {gcs_url}")

        # Update site_claims with the image URL (we'll add this column)
        # For now, store in replicate_assets as a backup
        with db_cursor(commit=True) as cur:
            # Store in replicate_assets for inventory display
            cur.execute("""
                INSERT INTO pilgrim.replicate_assets
                (user_id, asset_type, gcs_url, gcs_blob_name, prompt_used, commander_name, created_at)
                SELECT user_id, 'origin_visit_reward', %s, %s, %s, %s, NOW()
                FROM pilgrim.site_claims WHERE id = %s
                RETURNING id
            """, (gcs_url, blob_name, engraved_prompt, commander_name, claim_id))
            asset_row = cur.fetchone()
            asset_id = asset_row['id'] if asset_row else None

        return {
            'claim_id': claim_id,
            'image_url': gcs_url,
            'asset_id': asset_id
        }

    except Exception as e:
        logger.error(f"Failed to generate visitor reward image: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None


def decode_lost_signal_site(user_id: int, site_id: int, code: str) -> Dict:
    """Attempt to decode a Lost Signal site with the correct 0x code."""
    if not site_id or not code:
        return {'success': False, 'error': 'Missing site_id or code'}

    code = code.strip()
    if not code.startswith('0x'):
        return {'success': False, 'error': 'Code must start with 0x'}

    with db_cursor() as cur:
        cur.execute("""
            SELECT id, site_code, mission_name, unlock_code, is_lost_signal
            FROM pilgrim.origin_sites WHERE id = %s
        """, (site_id,))
        site = cur.fetchone()

    if not site:
        return {'success': False, 'error': 'Site not found'}

    if not site['is_lost_signal']:
        return {'success': False, 'error': 'This is not a Lost Signal site'}

    if site['unlock_code'] and code.lower() == site['unlock_code'].lower():
        with db_cursor(commit=True) as cur:
            cur.execute("UPDATE pilgrim.origin_sites SET is_lost_signal = FALSE WHERE id = %s", (site_id,))
        logger.info(f"User {user_id} decoded Lost Site {site['site_code']}!")
        return {'success': True, 'message': f"Signal decoded! {site['mission_name']} is now accessible.", 'site_code': site['site_code']}

    return {'success': False, 'error': 'Incorrect code. The signal remains fragmented.'}


def get_user_signal_claims(user_id: int) -> List[Dict]:
    """Get current user's site claims."""
    with db_cursor() as cur:
        cur.execute("""
            SELECT sc.site_type, sc.claim_rank, sc.claim_tier, sc.claimed_at,
                   COALESCE(os.site_code, es.site_code) as site_code,
                   COALESCE(os.mission_name, es.nearby_landmark) as site_name,
                   COALESCE(os.memory_text, es.memory_text) as memory_text
            FROM pilgrim.site_claims sc
            LEFT JOIN pilgrim.origin_sites os ON sc.origin_site_id = os.id
            LEFT JOIN pilgrim.echo_sites es ON sc.echo_site_id = es.id
            WHERE sc.user_id = %s
            ORDER BY sc.claimed_at DESC
        """, (user_id,))

        claims = []
        for row in cur.fetchall():
            claims.append({
                'site_type': row['site_type'],
                'claim_rank': row['claim_rank'],
                'claim_tier': row['claim_tier'],
                'claimed_at': row['claimed_at'].isoformat() if row['claimed_at'] else None,
                'site_code': row['site_code'],
                'site_name': row['site_name'],
                'memory_text': row['memory_text']
            })
        return claims


def decode_signal_puzzle(user_id: int, commander_name: str, code: str) -> Dict:
    """Attempt to decode a puzzle sequence - rewards legendary items."""
    import hashlib

    if not code:
        return {'success': False, 'error': 'No code provided'}
    if not commander_name:
        return {'success': False, 'error': 'Commander required to decode transmissions'}

    code = code.lower().strip()
    code_hash = hashlib.sha256(code.encode()).hexdigest()

    with db_cursor(commit=True) as cur:
        cur.execute("""
            SELECT id, puzzle_code, puzzle_name, reward_prompt, max_solvers, times_solved
            FROM pilgrim.signal_puzzles WHERE answer_hash = %s AND is_active = TRUE
        """, (code_hash,))
        puzzle = cur.fetchone()

        if not puzzle:
            return {'success': False, 'error': 'Sequence not recognized'}

        puzzle_id, puzzle_name = puzzle['id'], puzzle['puzzle_name']
        max_solvers, times_solved = puzzle['max_solvers'], puzzle['times_solved']

        cur.execute("SELECT id FROM pilgrim.puzzle_solvers WHERE puzzle_id = %s AND user_id = %s", (puzzle_id, user_id))
        if cur.fetchone():
            return {'success': False, 'error': 'You have already decoded this transmission'}

        if times_solved >= max_solvers:
            return {'success': False, 'error': 'This transmission has already been fully decoded by others'}

        solve_rank = times_solved + 1
        reward_name = f"First Decoder's Artifact: {puzzle_name}" if solve_rank == 1 else f"Decoder's Artifact: {puzzle_name}"

        cur.execute("""
            INSERT INTO pilgrim.puzzle_solvers (puzzle_id, user_id, commander_name, solve_rank, reward_name)
            VALUES (%s, %s, %s, %s, %s)
        """, (puzzle_id, user_id, commander_name, solve_rank, reward_name))
        from utilities.db_activity import log_activity
        log_activity(user_id, 'discovery', 'puzzle_solved', f"Decoded: {puzzle_name}",
                     detail=f"Rank #{solve_rank}", source_table='puzzle_solvers')

        cur.execute("""
            UPDATE pilgrim.signal_puzzles
            SET times_solved = times_solved + 1,
                first_solver_id = COALESCE(first_solver_id, %s),
                first_solver_name = COALESCE(first_solver_name, %s),
                first_solved_at = COALESCE(first_solved_at, NOW())
            WHERE id = %s
        """, (user_id, commander_name, puzzle_id))

        rank_suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(solve_rank, 'th')
        if solve_rank == 1:
            message = f"FIRST DECODER! You are the first to solve '{puzzle_name}'. Your name is permanently recorded."
        else:
            message = f"Transmission decoded! You are the {solve_rank}{rank_suffix} to solve '{puzzle_name}'."

        return {
            'success': True, 'message': message, 'puzzle_name': puzzle_name,
            'solve_rank': solve_rank, 'reward': {'name': reward_name, 'generating': True}
        }


def get_puzzle_solvers(limit: int = 50) -> List[Dict]:
    """Get list of puzzle solvers for display."""
    with db_cursor() as cur:
        cur.execute("""
            SELECT ps.commander_name, sp.puzzle_name, ps.solved_at, ps.solve_rank
            FROM pilgrim.puzzle_solvers ps
            JOIN pilgrim.signal_puzzles sp ON ps.puzzle_id = sp.id
            ORDER BY ps.solved_at DESC LIMIT %s
        """, (limit,))

        return [{
            'commander_name': row['commander_name'],
            'puzzle_name': row['puzzle_name'],
            'solved_at': row['solved_at'].strftime('%Y-%m-%d') if row['solved_at'] else None,
            'solve_rank': row['solve_rank']
        } for row in cur.fetchall()]


def decode_signal_tx(user_id: int, tx_hash: str) -> Dict:
    """
    Decode a Sepolia transaction hash to extract hidden signal codes.
    Players find transactions on Etherscan, decode the data field,
    and enter the tx hash to prove they found the hidden code.

    Also checks if the tx_hash is an ARIA bond fragment - if so,
    processes the bond submission instead of puzzle decoding.
    """
    import re
    import hashlib
    from utilities.sepolia_utils import MarsAsteroidMiner
    from utilities.postgres_utils import get_user_commander

    if not tx_hash:
        return {'success': False, 'error': 'No transaction provided'}

    tx_hash = tx_hash.strip()

    # ========================================================================
    # ARIA BONDS: Check if this is an entangled crystal fragment
    # ========================================================================
    try:
        from utilities.aria.bonds import process_fragment_submission
        bond_result = process_fragment_submission(tx_hash, user_id)
        if bond_result.get('is_fragment'):
            # This IS an ARIA fragment - return bond-specific response
            return bond_result
    except Exception as e:
        logger.error(f"ARIA bond check failed: {e}")

    user = get_user_commander(user_id) if user_id else None

    miner = MarsAsteroidMiner()
    tx_result = miner.fetch_and_decode_transaction(tx_hash)

    if not tx_result.get('success'):
        return {'success': False, 'error': tx_result.get('error', 'Could not retrieve transaction from the ledger')}

    decoded_data = tx_result.get('decoded_data', '')

    if tx_result.get('is_test'):
        return {'success': True, 'message': 'The decoder resonates. Connection verified.', 'decoded_message': decoded_data, 'is_test': True}

    signal_pattern = r'SIGNAL://(?:UNLOCK|CODE):([A-Za-z0-9_-]+)'
    match = re.search(signal_pattern, decoded_data)

    if not match:
        # Transaction exists but has no SIGNAL:// code — still show the decoded content
        # Check for ORIGIN:// pattern (origin site claims)
        origin_match = re.search(r'ORIGIN://(\w+)', decoded_data)
        if origin_match:
            return {
                'success': True, 'no_signal': True, 'is_origin_echo': True,
                'message': 'This transaction carries an Origin Site claim signature.',
                'decoded_message': decoded_data
            }
        return {
            'success': True, 'no_signal': True,
            'message': 'Transaction verified on the permanent record. No hidden signal detected, but the data is intact.',
            'decoded_message': decoded_data if decoded_data else '[Empty transmission]'
        }

    extracted_code = match.group(1).lower()
    code_hash = hashlib.sha256(extracted_code.encode()).hexdigest()

    with db_cursor(commit=True) as cur:
        cur.execute("""
            SELECT id, puzzle_code, puzzle_name, max_solvers, times_solved
            FROM pilgrim.signal_puzzles WHERE answer_hash = %s AND is_active = TRUE
        """, (code_hash,))
        puzzle = cur.fetchone()

        if not puzzle:
            return {'success': False, 'error': f'Code "{extracted_code}" extracted but not recognized as a valid signal', 'decoded_message': decoded_data[:200]}

        puzzle_id, puzzle_name = puzzle['id'], puzzle['puzzle_name']
        max_solvers, times_solved = puzzle['max_solvers'], puzzle['times_solved']

        if not user or not user.get('commander_name'):
            return {'success': True, 'message': f'Signal detected: "{puzzle_name}". A captain is required to claim this transmission.', 'decoded_message': decoded_data[:200], 'requires_captain': True}

        cur.execute("SELECT id FROM pilgrim.puzzle_solvers WHERE puzzle_id = %s AND user_id = %s", (puzzle_id, user_id))
        if cur.fetchone():
            return {'success': False, 'error': 'You have already decoded this transmission'}

        if times_solved >= max_solvers:
            return {'success': False, 'error': 'This transmission has already been fully decoded by others'}

        solve_rank = times_solved + 1
        cur.execute("""
            INSERT INTO pilgrim.puzzle_solvers (puzzle_id, user_id, commander_name, solve_rank, reward_name)
            VALUES (%s, %s, %s, %s, %s)
        """, (puzzle_id, user_id, user['commander_name'], solve_rank, f"TX Proof: {tx_hash[:20]}..."))
        from utilities.db_activity import log_activity
        log_activity(user_id, 'discovery', 'puzzle_solved', f"TX Decoded: {puzzle_name}",
                     detail=f"Rank #{solve_rank}", tx_hash=tx_hash or '', source_table='puzzle_solvers')

        cur.execute("""
            UPDATE pilgrim.signal_puzzles
            SET times_solved = times_solved + 1,
                first_solver_id = COALESCE(first_solver_id, %s),
                first_solver_name = COALESCE(first_solver_name, %s),
                first_solved_at = COALESCE(first_solved_at, NOW())
            WHERE id = %s
        """, (user_id, user['commander_name'], puzzle_id))

        if solve_rank == 1:
            message = f"FIRST DECODER! You found the hidden signal in the eternal ledger. '{puzzle_name}' is yours."
        else:
            message = f"Signal decoded. You are solver #{solve_rank} for '{puzzle_name}'."

        return {
            'success': True, 'message': message, 'decoded_message': decoded_data[:200],
            'extracted_code': extracted_code, 'puzzle_name': puzzle_name, 'solve_rank': solve_rank, 'tx_proof': tx_hash
        }
