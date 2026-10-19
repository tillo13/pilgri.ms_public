"""Origin site claim/visit handlers + lost-signal + puzzle decoders."""

import logging
from typing import Dict, Any, List, Optional

from utilities.postgres.core import db_cursor
from utilities.mars_math import haversine_distance, point_to_path_distance

from utilities.signal.config import (
    VISITOR_ITEM_CONFIG,
    get_visitor_tier,
)
from utilities.signal.sites import (
    get_all_origin_sites,
)
from utilities.signal.rewards import (
    generate_legendary_item_for_origin,
    generate_visitor_reward_image,
)

logger = logging.getLogger(__name__)


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
            from utilities.postgres.activity import log_activity
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
            from utilities.postgres.activity import log_activity
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

        # Phase 2 closest-approach: fetch Base coords once so we can evaluate the
        # FULL expedition path (Base → Destination), not just the destination.
        from utilities.postgres.map import get_or_set_user_mars_home
        base_coords = get_or_set_user_mars_home(user_id)
        base_lat = float(base_coords['latitude'])
        base_lon = float(base_coords['longitude'])

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

            # Find closest expedition path to this site (Phase 2: full path, not endpoint)
            min_distance = float('inf')
            closest_exp = None

            for exp in expeditions:
                dist = point_to_path_distance(
                    site['latitude'], site['longitude'],
                    base_lat, base_lon,
                    float(exp['latitude']), float(exp['longitude'])
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
        from utilities.postgres.activity import log_activity
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
    from utilities.postgres.assets import get_user_commander

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
        from utilities.postgres.activity import log_activity
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
