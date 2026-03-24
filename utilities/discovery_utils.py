"""Discovery spawning, analysis, and extraction utilities."""

import logging
import random
import math
from datetime import timedelta
from typing import Dict, Any, Optional, List, Tuple

logger = logging.getLogger(__name__)


# ============================================================================
# PROGRESSIVE DISCOVERY ITEM SPAWNING SYSTEM (WITH GEOGRAPHIC FILTERING)
# ============================================================================

def get_progressive_weights(expedition_number: int, distance_km: float, exploration: int,
                           equipment_effects: dict = None, strategy: int = 50) -> dict:
    """Calculate rarity weights based on expedition number, distance, exploration, and equipment bonuses.

    Equipment effects applied:
    - discovery_chance_bonus: Increases overall spawn weights
    - rare_chance_bonus: Increases rare rarity weight
    - legendary_chance_bonus: Increases legendary rarity weight

    Captain stats applied:
    - exploration: Boosts rare/legendary weights (existing)
    - strategy: Boosts rare weight by up to 50% (strategy/200)
    """
    equipment_effects = equipment_effects or {}

    if expedition_number <= 3:
        base_weights = {
            'common': 50,
            'uncommon': 25,
            'rare': 15,
            'legendary': 0
        }
    elif expedition_number <= 9:
        base_weights = {
            'common': 75,
            'uncommon': 20,
            'rare': 5,
            'legendary': 0
        }
    elif expedition_number <= 19:
        base_weights = {
            'common': 60,
            'uncommon': 25,
            'rare': 12,
            'legendary': 0
        }
    else:
        base_weights = {
            'common': 60,
            'uncommon': 25,
            'rare': 12,
            'legendary': 0.5
        }

    if distance_km < 100:
        distance_mult = {
            'common': 1.5,
            'uncommon': 1.0,
            'rare': 0.5,
            'legendary': 0.0
        }
    elif distance_km < 300:
        distance_mult = {
            'common': 1.0,
            'uncommon': 1.0,
            'rare': 1.0,
            'legendary': 0.0
        }
    elif distance_km < 600:
        distance_mult = {
            'common': 0.75,
            'uncommon': 1.0,
            'rare': 1.5,
            'legendary': 0.5
        }
    elif distance_km < 1000:
        distance_mult = {
            'common': 0.5,
            'uncommon': 1.0,
            'rare': 2.0,
            'legendary': 1.5
        }
    elif distance_km < 2000:
        distance_mult = {
            'common': 0.4,
            'uncommon': 1.0,
            'rare': 2.5,
            'legendary': 2.5
        }
    else:
        distance_mult = {
            'common': 0.3,
            'uncommon': 0.8,
            'rare': 3.0,
            'legendary': 4.0
        }

    final_weights = {}
    for rarity, base_weight in base_weights.items():
        weight = base_weight * distance_mult[rarity]

        if rarity == 'legendary':
            exploration_factor = 1.0 + (exploration / 90.0) ** 2
            weight *= exploration_factor
        elif rarity == 'rare':
            exploration_factor = 1.0 + (exploration / 90.0)
            weight *= exploration_factor
            # Strategy boosts rare find chance: 0-100 -> 0-50% bonus
            strategy_bonus = strategy / 200.0
            weight *= (1.0 + strategy_bonus)

        final_weights[rarity] = max(0, weight)

    # Apply equipment bonuses from scanners, drones, etc.
    discovery_bonus = equipment_effects.get('discovery_chance_bonus', 0)
    rare_bonus = equipment_effects.get('rare_chance_bonus', 0)
    legendary_bonus = equipment_effects.get('legendary_chance_bonus', 0)

    if discovery_bonus > 0:
        # Boost uncommon and rare proportionally (discovery bonus improves finding better items)
        final_weights['uncommon'] *= (1 + discovery_bonus)
        final_weights['rare'] *= (1 + discovery_bonus * 0.5)

    if rare_bonus > 0:
        final_weights['rare'] *= (1 + rare_bonus)

    if legendary_bonus > 0:
        final_weights['legendary'] *= (1 + legendary_bonus)

    return final_weights

def calculate_discovery_checkpoints(distance_km: float, travel_time_seconds: int) -> List[dict]:
    """Generate checkpoints every 15 minutes (900 seconds)"""
    checkpoints = []
    checkpoint_interval_seconds = 900
    num_checkpoints = max(1, int(travel_time_seconds / checkpoint_interval_seconds))

    for i in range(num_checkpoints):
        time_at_checkpoint = (i + 1) * checkpoint_interval_seconds
        if time_at_checkpoint > travel_time_seconds:
            time_at_checkpoint = travel_time_seconds

        progress = time_at_checkpoint / travel_time_seconds
        distance_at_checkpoint = distance_km * progress

        checkpoints.append({
            'time_seconds': time_at_checkpoint,
            'distance_km': round(distance_at_checkpoint, 2)
        })

    logger.info(f"Generated {len(checkpoints)} checkpoints for {travel_time_seconds}s journey")
    return checkpoints

def interpolate_route_coordinates(start_lat: float, start_lon: float, end_lat: float,
                                 end_lon: float, progress: float) -> Tuple[float, float]:
    """Calculate coordinates at progress point (0.0 to 1.0) along route"""
    return (
        round(start_lat + (end_lat - start_lat) * progress, 6),
        round(start_lon + (end_lon - start_lon) * progress, 6)
    )

def matches_terrain_feature(mars_type: str, item_features: List[str]) -> bool:
    """Check if mars_mapping type matches item's preferred_features"""
    if not item_features:
        return True
    normalized = mars_type.lower().strip()
    return any(normalized in f.lower() or f.lower() in normalized for f in item_features)

def roll_for_item_spawn(items: List[dict], exploration_stat: int, checkpoint_progress: float,
                       expedition_seed: int, expedition_number: int, distance_km: float,
                       prefer_stackable: bool = True, equipment_effects: dict = None,
                       strategy_stat: int = 50, leadership_stat: int = 50,
                       geology_stat: int = 0, nearby_feature_type: str = '') -> dict:
    """Roll for item spawn with progressive rarity system, equipment bonuses, and crew stats"""
    if not items:
        return None

    random.seed(expedition_seed + int(checkpoint_progress * 1000))

    weight_multipliers = get_progressive_weights(expedition_number, distance_km, exploration_stat,
                                                  equipment_effects=equipment_effects,
                                                  strategy=strategy_stat)
    # Leadership boosts spawn chance: 0-100 -> 0.85 to 0.95
    spawn_chance = min(0.95, 0.85 + (leadership_stat / 1000.0))
    progress_factor = 0.7 + (checkpoint_progress * 0.3)

    weights = []
    for item in items:
        base_weight = weight_multipliers.get(item['rarity'], 0)

        if base_weight == 0:
            weights.append(0)
            continue

        if prefer_stackable and item.get('stackable', False):
            base_weight *= 1.5

        # Scientist Geology boosts terrain-matching items: 0-50 -> up to x1.5 weight
        if geology_stat > 0 and nearby_feature_type:
            if matches_terrain_feature(nearby_feature_type, item.get('preferred_mars_features', [])):
                geology_bonus = 1.0 + (geology_stat / 100.0)
                base_weight *= geology_bonus

        if item['rarity'] == 'legendary':
            weight = base_weight * progress_factor
        elif item['rarity'] == 'rare':
            weight = base_weight * (0.8 + progress_factor * 0.2)
        else:
            weight = base_weight

        weights.append(weight)

    if sum(weights) == 0:
        return None

    if random.random() < spawn_chance:
        return random.choices(items, weights=weights, k=1)[0]
    return None

def get_distance_value_multiplier(distance_km: float) -> float:
    """Items found further from base are worth more - rewards long expeditions."""
    if distance_km < 200:
        return 1.0
    elif distance_km < 500:
        return 1.25
    elif distance_km < 1000:
        return 1.5
    elif distance_km < 2000:
        return 2.0
    else:
        return 2.5

def calculate_enhanced_item_value(base_value: int, exploration_stat: int, item_enhancement: float,
                                  analysis_stat: int = 0, distance_km: float = 0) -> dict:
    """Calculate enhanced value with captain exploration + scientist analysis + distance bonuses"""
    exploration_bonus = exploration_stat / 100.0
    # Scientist Analysis: 0-50 -> up to x1.25 value multiplier
    analysis_bonus = analysis_stat / 200.0
    # Distance bonus: items from further expeditions are worth more
    distance_mult = get_distance_value_multiplier(distance_km)
    enhanced = int(base_value * (1 + exploration_bonus) * (1 + analysis_bonus) * item_enhancement * distance_mult)
    return {
        'base_value': base_value,
        'enhanced_value': enhanced,
        'exploration_bonus_pct': int(exploration_bonus * 100),
        'analysis_bonus_pct': int(analysis_bonus * 100),
        'distance_bonus_pct': int((distance_mult - 1.0) * 100),
        'item_multiplier': item_enhancement
    }

def generate_expedition_discoveries(expedition_id: int, expedition_data: dict,
                                   available_items: List[dict], nearby_features: List[dict],
                                   travel_time_seconds: int = None, user_expedition_count: int = 1,
                                   cargo_capacity: int = None) -> List[dict]:
    """
    Generate discoveries with GEOGRAPHIC FILTERING and CARGO LIMITS.
    Mission artifacts ONLY spawn if mission landing site is on expedition path.

    cargo_capacity: Max discoveries the vehicle can carry back. If None, uses default of 5.
                   Excess discoveries are left behind (vehicle takes the most valuable).
    """
    # Lazy import: is_item_geographically_valid stays in expedition_utils
    from utilities.expedition_utils import is_item_geographically_valid

    discoveries = []

    if travel_time_seconds is None:
        travel_time_seconds = int((expedition_data['distance_km'] / 2.0) * 3600)

    checkpoints = calculate_discovery_checkpoints(expedition_data['distance_km'], travel_time_seconds)
    exploration = expedition_data['commander_stats'].get('exploration', 50)
    strategy = expedition_data['commander_stats'].get('strategy', 50)
    leadership = expedition_data['commander_stats'].get('leadership', 50)
    scientist_stats = expedition_data.get('scientist_stats', {})
    analysis = scientist_stats.get('analysis', 0)
    geology = scientist_stats.get('geology', 0)
    distance_km = expedition_data['distance_km']

    start_lat = expedition_data['base_lat']
    start_lon = expedition_data['base_lon']
    end_lat = expedition_data['destination_lat']
    end_lon = expedition_data['destination_lon']

    geographically_valid_items = [
        item for item in available_items
        if is_item_geographically_valid(item, start_lat, start_lon, end_lat, end_lon)
    ]

    filtered_count = len(available_items) - len(geographically_valid_items)
    if filtered_count > 0:
        logger.info(f"Filtered {filtered_count} mission artifacts not on path (keeping {len(geographically_valid_items)} valid items)")

    if checkpoints:
        first_checkpoint = checkpoints[0]

        common_stackables = [
            item for item in geographically_valid_items
            if item['rarity'] == 'common'
            and item.get('stackable', False)
            and item['min_distance_km'] <= distance_km
        ]

        if not common_stackables:
            common_stackables = [
                item for item in geographically_valid_items
                if item['rarity'] == 'common'
                and item['min_distance_km'] <= distance_km
            ]

        if common_stackables:
            first_item = random.choice(common_stackables)

            progress = first_checkpoint['distance_km'] / distance_km if distance_km > 0 else 0
            lat, lon = interpolate_route_coordinates(
                expedition_data['base_lat'], expedition_data['base_lon'],
                expedition_data['destination_lat'], expedition_data['destination_lon'], progress)

            nearest_feature = min(nearby_features,
                                key=lambda f: math.sqrt((float(f['latitude'])-lat)**2 + (float(f['longitude'])-lon)**2))

            enhanced = calculate_enhanced_item_value(
                first_item['base_scientific_value'], exploration, first_item['exploration_enhancement_value'],
                analysis_stat=analysis, distance_km=distance_km)

            discoveries.append({
                'expedition_id': expedition_id,
                'discovery_item_id': first_item['id'],
                'found_at_km': 0.0,
                'found_at_coordinates': {'lat': expedition_data['base_lat'], 'lon': expedition_data['base_lon']},
                'nearby_feature': nearest_feature['name'],
                'base_value': enhanced['base_value'],
                'enhanced_value': enhanced['enhanced_value'],
                'quantity': 1,
                'weight_kg': first_item.get('weight_kg', 1.0)  # Digital data = 0kg
            })

    legendary_found = False
    rare_items_found = set()  # Track rare item IDs to prevent duplicates
    for checkpoint in checkpoints[1:]:
        progress = checkpoint['distance_km'] / distance_km if distance_km > 0 else 0
        lat, lon = interpolate_route_coordinates(
            expedition_data['base_lat'], expedition_data['base_lon'],
            expedition_data['destination_lat'], expedition_data['destination_lon'], progress)

        nearest_feature = min(nearby_features,
                            key=lambda f: math.sqrt((float(f['latitude'])-lat)**2 + (float(f['longitude'])-lon)**2))

        # Filter items: use CHECKPOINT distance (not total expedition distance) for min/max range
        # This ensures long expeditions can still find items near base camp
        checkpoint_km = checkpoint['distance_km']
        matching_items = [item for item in geographically_valid_items
                         if matches_terrain_feature(nearest_feature['type'], item['preferred_mars_features'])
                         and item['min_distance_km'] <= checkpoint_km
                         and (item['max_distance_km'] is None or checkpoint_km <= item['max_distance_km'])
                         and not (legendary_found and item['rarity'] == 'legendary')
                         and not (item['rarity'] == 'rare' and item['id'] in rare_items_found)]

        item = roll_for_item_spawn(
            matching_items,
            exploration,
            progress,
            expedition_id,
            user_expedition_count,
            distance_km,
            prefer_stackable=True,
            equipment_effects=expedition_data.get('equipment_effects'),
            strategy_stat=strategy,
            leadership_stat=leadership,
            geology_stat=geology,
            nearby_feature_type=nearest_feature.get('type', '')
        )

        if item:
            if item['rarity'] == 'legendary':
                legendary_found = True
            elif item['rarity'] == 'rare':
                rare_items_found.add(item['id'])  # Prevent same rare item spawning twice
            enhanced = calculate_enhanced_item_value(
                item['base_scientific_value'], exploration, item['exploration_enhancement_value'],
                analysis_stat=analysis, distance_km=distance_km)

            discoveries.append({
                'expedition_id': expedition_id,
                'discovery_item_id': item['id'],
                'found_at_km': checkpoint['distance_km'],
                'found_at_coordinates': {'lat': lat, 'lon': lon},
                'nearby_feature': nearest_feature['name'],
                'base_value': enhanced['base_value'],
                'enhanced_value': enhanced['enhanced_value'],
                'quantity': 1,
                'weight_kg': item.get('weight_kg', 1.0)  # Digital data = 0kg
            })

    # Apply cargo capacity limit - vehicle can only carry so much weight
    # Digital data (weight_kg=0) doesn't count against cargo!
    if cargo_capacity is None:
        cargo_capacity = 5  # Default Scout Rover capacity

    # Distance cargo bonus: longer expeditions = more cargo slots
    # +1 per 500km beyond 500km, max +4 bonus slots
    if distance_km > 500:
        distance_cargo_bonus = min(4, int((distance_km - 500) / 500) + 1)
        cargo_capacity += distance_cargo_bonus
        logger.info(f"Distance cargo bonus: +{distance_cargo_bonus} slots (total {cargo_capacity}) for {distance_km}km expedition")

    # Enforce cargo capacity: total discoveries (all types) capped by vehicle capacity
    # Sort by value (highest first) so we keep the best finds
    if len(discoveries) > cargo_capacity:
        discoveries.sort(key=lambda d: d['enhanced_value'], reverse=True)
        left_behind = discoveries[cargo_capacity:]
        discoveries = discoveries[:cargo_capacity]
        left_behind_value = sum(d['enhanced_value'] for d in left_behind)
        logger.info(f"Cargo limit: Vehicle capacity {cargo_capacity}, found {cargo_capacity + len(left_behind)} items, left behind {len(left_behind)} items worth {left_behind_value} shards")

    logger.info(f"Generated {len(discoveries)} discoveries for expedition {expedition_id} (Mission #{user_expedition_count}, {distance_km}km, cargo: {cargo_capacity})")
    return discoveries


# ============================================================================
# ANALYZE & EXTRACT DISCOVERIES
# ============================================================================
EXTRACTION_SV_BONUS_RATE = 0.50  # 50% of shard payout awarded as bonus SV (was 15%, bumped per Luke's sign-off)

def analyze_discovery(user_id: int, discovery_item_id: int, session=None, extract_all: bool = True) -> Dict[str, Any]:
    """
    Analyze a discovery to extract embedded Sepolia shards.
    Your Colony Scientist breaks down the specimen, extracting ancient Martian crystals.

    - If extract_all=True: Consumes ALL claimed instances of this discovery item
    - If extract_all=False: Consumes only ONE instance (oldest first)
    - Sends shards to captain's wallet based on enhanced_value
    - Records transaction for history

    Returns: { success, shards_received, quantity_analyzed, tx_hash, error }
    """
    from utilities.postgres_utils import (
        get_user_primary_sepolia_wallet, create_depot_transaction, db_cursor, get_user_scientist
    )
    from utilities.sepolia_utils import MarsAsteroidMiner, sanitize_tx_error
    from utilities.depot_utils import display_to_eth, invalidate_balance_cache

    # Get user's wallet
    wallet = get_user_primary_sepolia_wallet(user_id)
    if not wallet:
        return {'success': False, 'error': 'No wallet found'}

    # Get claimed discoveries of this item type for user (ordered by oldest first for extract_one)
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT ed.id, ed.enhanced_value, ed.quantity, di.item_name, di.rarity, di.description, di.item_type,
                       di.base_scientific_value
                FROM pilgrim.expedition_discoveries ed
                JOIN pilgrim.expeditions e ON ed.expedition_id = e.id
                JOIN pilgrim.discovery_items di ON ed.discovery_item_id = di.id
                WHERE e.user_id = %s AND ed.discovery_item_id = %s AND ed.claimed_by_user = true AND ed.analyzed = false
                ORDER BY ed.claimed_at ASC
            """, (user_id, discovery_item_id))
            all_discoveries = cur.fetchall()

            if not all_discoveries:
                return {'success': False, 'error': 'No discoveries to analyze'}

            item_name = all_discoveries[0]['item_name']
            rarity = all_discoveries[0]['rarity']
            item_type = all_discoveries[0]['item_type']

            # If extract_all=False, only process the first (oldest) discovery row
            if extract_all:
                discoveries = all_discoveries
            else:
                # Take just the first row (which may have quantity > 1)
                first = all_discoveries[0]
                if first['quantity'] > 1:
                    # Only extract 1 from this stack - we'll need to decrement quantity instead of marking analyzed
                    discoveries = [{'id': first['id'], 'enhanced_value': first['enhanced_value'], 'quantity': 1, 'partial': True, 'original_qty': first['quantity']}]
                else:
                    discoveries = [first]

            # Calculate totals for selected discoveries
            base_value = sum(d['enhanced_value'] * d['quantity'] for d in discoveries)
            total_quantity = sum(d['quantity'] for d in discoveries)

    except Exception as e:
        logger.error(f"Failed to get discoveries for analysis: {e}")
        return {'success': False, 'error': 'Database error'}

    # Rarity determines extraction behavior
    # Scientific value is worth MORE than shard extraction (encourages keeping discoveries)
    # Legendary: BLOCKED - scientist refuses (cryptic hints about Depot)
    # Rare: 1x multiplier (full value, but warned about "whispers")
    # Uncommon: 0.75x multiplier
    # Common: 0.5x multiplier
    PAYOUT_MULTIPLIERS = {'common': 0.5, 'uncommon': 0.75, 'rare': 1, 'legendary': 0}
    multiplier = PAYOUT_MULTIPLIERS.get(rarity, 0.5)

    if rarity == 'legendary':
        return {
            'success': False,
            'error': 'The scientist cannot proceed. Something in the Depot calls to this artifact.',
            'blocked': True,
            'rarity': rarity
        }

    # ========================================================================
    # GET USER'S EQUIPMENT EFFECTS (discovery_value_mult, bio_discovery_value_mult)
    # This was previously defined in config.py but never applied!
    # Items: Mobile Research Lab (+25%), Advanced Research Center (+75%),
    #        Advanced Research Station infrastructure (+50%)
    #        Cryo Storage Unit (+20% for biological discoveries)
    # ========================================================================
    try:
        from utilities.upgrades_utils import get_user_upgrade_effects
        user_effects = get_user_upgrade_effects(user_id)
        discovery_value_mult = user_effects.get('discovery_value_mult', 1.0)
        bio_discovery_value_mult = user_effects.get('bio_discovery_value_mult', 1.0)
    except Exception as e:
        logger.warning(f"Could not get user upgrade effects for discovery analysis: {e}")
        discovery_value_mult = 1.0
        bio_discovery_value_mult = 1.0

    # Apply rarity multiplier to payout
    total_value = base_value * multiplier

    # Apply discovery_value_mult from research equipment
    if discovery_value_mult > 1.0:
        total_value *= discovery_value_mult

    # Apply bio_discovery_value_mult for biological discoveries (Cryo Storage Unit)
    if item_type == 'biological' and bio_discovery_value_mult > 1.0:
        total_value *= bio_discovery_value_mult

    # STEP 1: Mark discoveries as analyzed IMMEDIATELY (UI updates fast)
    try:
        with db_cursor(commit=True) as cur:
            for d in discoveries:
                if d.get('partial'):
                    # Partial extraction: decrement quantity by 1
                    cur.execute("""
                        UPDATE pilgrim.expedition_discoveries
                        SET quantity = quantity - 1
                        WHERE id = %s
                    """, (d['id'],))
                else:
                    # Full extraction: mark as analyzed
                    cur.execute("""
                        UPDATE pilgrim.expedition_discoveries
                        SET analyzed = true, analyzed_at = NOW()
                        WHERE id = %s
                    """, (d['id'],))
    except Exception as e:
        logger.error(f"Failed to mark discoveries as analyzed: {e}")
        return {'success': False, 'error': 'Database error'}

    # STEP 1b: Award bonus SV (extraction gives BOTH shards + SV)
    sv_bonus = math.floor(total_value * EXTRACTION_SV_BONUS_RATE)
    if sv_bonus > 0:
        from utilities.db_users import add_passive_sv
        add_passive_sv(user_id, sv_bonus)
        logger.info(f"User {user_id} earned {sv_bonus} bonus SV from extraction")

    # STEP 1c: Check collection milestones (Dr. Bo's research program)
    milestones_earned = []
    try:
        from utilities.sv_milestones import check_and_award_milestones
        milestones_earned = check_and_award_milestones(user_id)
    except Exception as e:
        logger.error(f"Milestone check failed: {e}")

    # STEP 2: Connect to Sepolia
    miner = MarsAsteroidMiner()
    if not miner.connect():
        return {'success': False, 'error': 'Network unavailable'}

    # Get scientist for flavor text
    scientist = get_user_scientist(user_id)
    scientist_name = scientist.get('name', 'Colony Scientist') if scientist else 'Colony Scientist'

    # Convert display value to ETH for transaction
    amount_eth = display_to_eth(total_value)

    # Create analysis message
    message = (
        f"{scientist_name} extracted {total_value:.0f} shards from {total_quantity}x {item_name} ({rarity}). "
        f"Specimen consumed."
    )

    # STEP 3: Send shards using FAST method (broadcasts immediately, doesn't wait)
    result = miner.send_sepolia_reward_fast(
        wallet['wallet_address'],
        amount_eth,
        message,
        context="discovery_analysis"
    )

    if not result['success']:
        return {'success': False, 'error': sanitize_tx_error(result.get('error', ''))}

    # Record transaction (tx_hash is valid even before confirmation)
    create_depot_transaction(
        user_id=user_id,
        wallet_address=wallet['wallet_address'],
        purchase_type='discovery_analysis',
        amount_eth=amount_eth,
        tx_hash=result['tx_hash'],
        etherscan_url=result['etherscan_url'],
        item_details={
            'discovery_item_id': discovery_item_id,
            'item_name': item_name,
            'rarity': rarity,
            'quantity_analyzed': total_quantity,
            'shards_extracted': total_value
        }
    )

    logger.info(f"User {user_id} analyzed {total_quantity}x {item_name} -> {total_value:.0f} shards (tx broadcast)")

    # Calculate combined bonus for UI display
    combined_mult = discovery_value_mult
    if item_type == 'biological' and bio_discovery_value_mult > 1.0:
        combined_mult *= bio_discovery_value_mult

    # Calculate new balance: session cache + received (NO blockchain re-query)
    if session is not None:
        from utilities.depot_utils import update_session_balance
        old_balance = session.get('_bal', 0)
        new_balance = old_balance + total_value
        update_session_balance(session, new_balance)
    else:
        from utilities.depot_utils import get__bal
        old_balance = get__bal(user_id)
        new_balance = old_balance + total_value

    return {
        'success': True,
        'shards_received': total_value,
        'new_balance': new_balance,  # For immediate UI update
        'quantity_analyzed': total_quantity,
        'item_name': item_name,
        'rarity': rarity,
        'item_type': item_type,
        'tx_hash': result['tx_hash'],
        'etherscan_url': result['etherscan_url'],
        'broadcast': True,  # Indicates shards are pending confirmation
        # Bonus info for UI display
        'discovery_value_mult': combined_mult,
        'bonus_applied': combined_mult > 1.0,
        'bio_bonus_applied': item_type == 'biological' and bio_discovery_value_mult > 1.0,
        'sv_awarded': sv_bonus
    }


def shard_all_discoveries(user_id: int, session=None) -> Dict[str, Any]:
    """
    Bulk extract all common and uncommon discoveries (Shard It All).
    Skips legendary and rare items - those require individual extraction.

    Returns: { success, shards_received, quantity_analyzed, items_processed, tx_hash, error }
    """
    from utilities.postgres_utils import (
        get_user_primary_sepolia_wallet, create_depot_transaction, db_cursor, get_user_scientist
    )
    from utilities.sepolia_utils import MarsAsteroidMiner, sanitize_tx_error
    from utilities.depot_utils import display_to_eth, invalidate_balance_cache

    # Get user's wallet
    wallet = get_user_primary_sepolia_wallet(user_id)
    if not wallet:
        return {'success': False, 'error': 'No wallet found'}

    # Get all common and uncommon discoveries for user
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT ed.id, ed.enhanced_value, ed.quantity, di.item_name, di.rarity, di.item_type,
                       di.base_scientific_value
                FROM pilgrim.expedition_discoveries ed
                JOIN pilgrim.expeditions e ON ed.expedition_id = e.id
                JOIN pilgrim.discovery_items di ON ed.discovery_item_id = di.id
                WHERE e.user_id = %s AND ed.claimed_by_user = true AND ed.analyzed = false
                  AND di.rarity IN ('common', 'uncommon')
                ORDER BY ed.claimed_at ASC
            """, (user_id,))
            discoveries = cur.fetchall()

            if not discoveries:
                return {'success': False, 'error': 'No common or uncommon discoveries to extract'}

    except Exception as e:
        logger.error(f"Failed to get discoveries for bulk sharding: {e}")
        return {'success': False, 'error': 'Database error'}

    # ========================================================================
    # GET USER'S EQUIPMENT EFFECTS (discovery_value_mult, bio_discovery_value_mult)
    # Items: Mobile Research Lab (+25%), Advanced Research Center (+75%),
    #        Advanced Research Station infrastructure (+50%)
    #        Cryo Storage Unit (+20% for biological discoveries)
    # ========================================================================
    try:
        from utilities.upgrades_utils import get_user_upgrade_effects
        user_effects = get_user_upgrade_effects(user_id)
        discovery_value_mult = user_effects.get('discovery_value_mult', 1.0)
        bio_discovery_value_mult = user_effects.get('bio_discovery_value_mult', 1.0)
    except Exception as e:
        logger.warning(f"Could not get user upgrade effects for bulk sharding: {e}")
        discovery_value_mult = 1.0
        bio_discovery_value_mult = 1.0

    # Calculate totals with rarity multipliers and bio bonus
    PAYOUT_MULTIPLIERS = {'common': 0.5, 'uncommon': 0.75}
    total_value = 0
    total_quantity = 0
    items_by_rarity = {'common': 0, 'uncommon': 0}
    bio_bonus_count = 0

    for d in discoveries:
        qty = d['quantity']
        rarity = d['rarity']
        item_type = d['item_type']
        rarity_mult = PAYOUT_MULTIPLIERS.get(rarity, 0.5)

        # Base value with rarity multiplier
        item_value = d['enhanced_value'] * qty * rarity_mult

        # Apply discovery_value_mult from research equipment
        if discovery_value_mult > 1.0:
            item_value *= discovery_value_mult

        # Apply bio_discovery_value_mult for biological discoveries (Cryo Storage Unit)
        if item_type == 'biological' and bio_discovery_value_mult > 1.0:
            item_value *= bio_discovery_value_mult
            bio_bonus_count += qty

        total_value += item_value
        total_quantity += qty
        items_by_rarity[rarity] = items_by_rarity.get(rarity, 0) + qty

    discovery_ids = [d['id'] for d in discoveries]

    # STEP 1: Mark discoveries as analyzed IMMEDIATELY (UI updates fast)
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE pilgrim.expedition_discoveries
                SET analyzed = true, analyzed_at = NOW()
                WHERE id = ANY(%s)
            """, (discovery_ids,))
    except Exception as e:
        logger.error(f"Failed to mark discoveries as analyzed: {e}")
        return {'success': False, 'error': 'Database error'}

    # STEP 1b: Award bonus SV (extraction gives BOTH shards + SV)
    sv_bonus = math.floor(total_value * EXTRACTION_SV_BONUS_RATE)
    if sv_bonus > 0:
        from utilities.db_users import add_passive_sv
        add_passive_sv(user_id, sv_bonus)
        logger.info(f"User {user_id} earned {sv_bonus} bonus SV from bulk extraction")

    # STEP 1c: Check collection milestones (Dr. Bo's research program)
    try:
        from utilities.sv_milestones import check_and_award_milestones
        check_and_award_milestones(user_id)
    except Exception as e:
        logger.error(f"Milestone check failed: {e}")

    # STEP 2: Connect to Sepolia
    miner = MarsAsteroidMiner()
    if not miner.connect():
        return {'success': False, 'error': 'Network unavailable'}

    # Get scientist for message
    scientist = get_user_scientist(user_id)
    scientist_name = scientist.get('name', 'Colony Scientist') if scientist else 'Colony Scientist'

    # Convert display value to ETH for transaction
    amount_eth = display_to_eth(total_value)

    # Create bulk analysis message
    message = (
        f"{scientist_name} bulk-extracted {total_value:.0f} shards from "
        f"{items_by_rarity.get('common', 0)} common + {items_by_rarity.get('uncommon', 0)} uncommon specimens. "
        f"Total: {total_quantity} items processed."
    )

    # STEP 3: Send shards using FAST method (broadcasts immediately, doesn't wait for confirmation)
    result = miner.send_sepolia_reward_fast(
        wallet['wallet_address'],
        amount_eth,
        message,
        context="discovery_analysis"
    )

    if not result['success']:
        return {'success': False, 'error': sanitize_tx_error(result.get('error', ''))}

    # Record transaction (even though not confirmed yet - tx_hash is valid)
    create_depot_transaction(
        user_id=user_id,
        wallet_address=wallet['wallet_address'],
        purchase_type='discovery_analysis',
        amount_eth=amount_eth,
        tx_hash=result['tx_hash'],
        etherscan_url=result['etherscan_url'],
        item_details={
            'bulk_extraction': True,
            'items_processed': len(discoveries),
            'quantity_analyzed': total_quantity,
            'shards_extracted': total_value,
            'by_rarity': items_by_rarity
        }
    )

    logger.info(f"User {user_id} bulk-sharded {total_quantity} items -> {total_value:.0f} shards (tx broadcast)")

    # Calculate combined bonus for UI display
    combined_mult = discovery_value_mult
    if bio_discovery_value_mult > 1.0:
        combined_mult *= bio_discovery_value_mult

    # Calculate new balance: session cache + received (NO blockchain re-query)
    if session is not None:
        from utilities.depot_utils import update_session_balance
        old_balance = session.get('_bal', 0)
        new_balance = old_balance + total_value
        update_session_balance(session, new_balance)
    else:
        from utilities.depot_utils import get__bal
        old_balance = get__bal(user_id)
        new_balance = old_balance + total_value

    return {
        'success': True,
        'shards_received': total_value,
        'new_balance': new_balance,  # For immediate UI update
        'quantity_analyzed': total_quantity,
        'items_processed': len(discoveries),
        'by_rarity': items_by_rarity,
        'tx_hash': result['tx_hash'],
        'etherscan_url': result['etherscan_url'],
        'broadcast': True,  # Indicates shards are pending confirmation
        # Bonus info for UI display
        'discovery_value_mult': combined_mult,
        'bonus_applied': combined_mult > 1.0,
        'bio_bonus_applied': bio_bonus_count > 0,
        'bio_bonus_count': bio_bonus_count,
        'sv_awarded': sv_bonus
    }
