"""
Infrastructure utilities - Solar arrays, battery storage, and shard generation
FIXED: Removed "ready to activate" bug, auto-activates when build completes
FIXED: Immediate reward now uses send_sepolia_reward() correctly
ADDED: Battery storage enables 50% generation during Mars nights (real sol timing)
ADDED: Dust storm system - solar arrays become dust-covered after 7 days of accumulation
       Users must claim and clean panels to resume generation.
       Maintenance Drone shop item prevents dust accumulation.
"""
import math
import logging
from datetime import datetime, timedelta

# Mars sol duration in Earth hours (24h 37m 22s)
MARS_SOL_HOURS = 24.6228

# ============================================================================
# DUST STORM / ACCUMULATION CAP SETTINGS
# Matches idle discoveries 7-day cap for consistency
# ============================================================================
ACCUMULATION_CAP_HOURS = 24 * 7  # 7 days = 168 hours max accumulation
DUST_STORM_MESSAGE = "A Martian dust storm has coated your solar arrays. Claim your accumulated shards and clean the panels to resume generation."

def calculate_daylight_fraction(hours_elapsed: float, longitude: float) -> tuple[float, float]:
    """
    Calculate what fraction of elapsed time was during Mars daylight vs night.
    Uses simplified model: Mars has ~12.3 hour days and ~12.3 hour nights.
    Longitude determines current time of day on Mars.

    Returns: (day_fraction, night_fraction) that sum to 1.0
    """
    # Mars rotates 360° per sol, so longitude determines local solar time
    # We use current UTC time + longitude offset to determine Mars local time

    # Current Mars time at this longitude (simplified model)
    # One full Mars rotation = MARS_SOL_HOURS Earth hours
    # 360° of longitude = one full rotation
    hours_since_epoch = (datetime.utcnow() - datetime(2000, 1, 1)).total_seconds() / 3600

    # Mars local solar time (0-24.6 range, where 12.3 is solar noon)
    mars_local_time = (hours_since_epoch / MARS_SOL_HOURS * 24 + longitude / 15) % MARS_SOL_HOURS

    # Day is roughly 6:00 to 18:00 Mars local time (simplified)
    # This gives ~12.3 hours of day, ~12.3 hours of night
    day_start = MARS_SOL_HOURS * 0.25  # ~6:09 Mars time
    day_end = MARS_SOL_HOURS * 0.75    # ~18:28 Mars time

    # For accumulated time, we estimate based on how many full sols elapsed
    full_sols = hours_elapsed / MARS_SOL_HOURS

    if full_sols >= 1.0:
        # For longer periods, Mars day/night averages out to 50/50
        return 0.5, 0.5
    else:
        # For shorter periods, check if we're currently in day or night
        if day_start <= mars_local_time <= day_end:
            # Currently daytime - bias toward day
            day_fraction = 0.6 + (0.4 * (1.0 - full_sols))  # More day time for short periods during day
        else:
            # Currently nighttime - bias toward night
            day_fraction = 0.4 * (1.0 - full_sols)  # Less day time for short periods during night

        return day_fraction, 1.0 - day_fraction
from config_infrastructure import INFRASTRUCTURE_CATALOG
from utilities.postgres_utils import (
    create_infrastructure, get_user_infrastructure, update_infrastructure_status,
    get_infrastructure_by_id, get_user_primary_sepolia_wallet, create_depot_transaction,
    get_db_connection, update_sepolia_wallet_balance, get_or_set_user_mars_home
)
from utilities.sepolia_utils import MarsAsteroidMiner, sanitize_tx_error

logger = logging.getLogger(__name__)


def _get_mars_environment_multiplier(latitude: float) -> float:
    """Get Mars environment multiplier for solar shard generation.

    Combines two real Mars factors:
    - Dust opacity: blocks sunlight reaching Sepolia shards (0.20-0.98x)
    - Temperature: heat activates shard energy release per lore (0.90-1.10x)

    Uses current conditions at claim time. Scientifically accurate:
    dust storms peak at Ls 180-330, temps vary by season/time/latitude.
    """
    factors = _get_mars_environment_factors(latitude)
    return round(factors['dust'] * factors['temperature'], 3)


def _get_mars_environment_factors(latitude: float) -> dict:
    """Get individual Mars environment factors for UI breakdown.

    Returns dict with dust, temperature, latitude factors and combined multiplier.
    """
    from utilities.mars_environment_utils import get_mars_environment
    env = get_mars_environment(base_lat=latitude)
    dust_factor = env['dust']['solar_efficiency'] / 100.0  # 0.20 to 0.98
    temp = env['temperature']['current']  # -110 to -10 typical
    temp_factor = 1.0 + (temp + 60) / 500.0  # 0.90 at -110°C, 1.10 at -10°C
    lat_factor = math.cos(math.radians(abs(latitude)))  # 0.0 to 1.0
    return {
        'dust': round(dust_factor, 3),
        'temperature': round(temp_factor, 3),
        'latitude': round(lat_factor, 3),
        'dust_condition': env['dust']['condition'],
        'temp_celsius': env['temperature']['current'],
        'combined': round(dust_factor * temp_factor, 3),
    }


def calculate_generation_rate(structure_type, latitude, longitude, level: int = 1):
    """Calculate resource generation rate based on structure type, location, and level.

    For solar_array: Base rate varies by latitude (equator = best), then scaled by level
    For other buildings: Use catalog-defined rate for the given level
    """
    definition = INFRASTRUCTURE_CATALOG.get(structure_type, {})
    level_data = definition.get('levels', {}).get(level, {})
    catalog_rate = float(level_data.get('generation_rate', 0.0))

    if structure_type == 'solar_array':
        # Solar array base rate varies by latitude, then scales with level
        lat_radians = math.radians(abs(latitude))
        latitude_factor = math.cos(lat_radians)
        base_rate = 10.0 * latitude_factor
        # Level 1 catalog rate is 10.0, so we scale proportionally
        level_mult = catalog_rate / 10.0 if catalog_rate > 0 else 1.0
        return round(base_rate * level_mult, 2)

    return catalog_rate


def get_build_requirements(structure_type, user_id):
    """Check if user meets requirements to build this structure.

    Checks both:
    1. Basic requirements (building TYPE exists) - from 'requirements' list
    2. Level requirements (building at LEVEL X) - from 'unlock_requirements' dict
    """
    from utilities.upgrades_utils import get_infrastructure_level

    definition = INFRASTRUCTURE_CATALOG.get(structure_type)
    if not definition:
        return False, ['Invalid structure type']

    user_buildings = get_user_infrastructure(user_id)
    user_types = [b['structure_type'] for b in user_buildings if b.get('status') == 'active']
    missing = []

    # Check basic requirements (building must exist)
    requirements = definition.get('requirements', [])
    for req in requirements:
        if req not in user_types:
            missing.append(req)

    # Check unlock_requirements (building must be at specific level)
    unlock_requirements = definition.get('unlock_requirements', {})
    for req_building, req_level in unlock_requirements.items():
        if req_building not in user_types:
            # Building doesn't exist at all
            missing.append(f"{req_building} (need Lv{req_level})")
        else:
            # Building exists, check level
            current_level = get_infrastructure_level(user_id, req_building)
            if current_level < req_level:
                catalog = INFRASTRUCTURE_CATALOG.get(req_building, {})
                building_name = catalog.get('name', req_building)
                missing.append(f"{building_name} Lv{req_level} (have Lv{current_level})")

    return len(missing) == 0, missing


def start_construction(user_id, structure_type, latitude, longitude):
    """Begin building infrastructure - charge user if needed, set ready_at time"""
    catalog_def = INFRASTRUCTURE_CATALOG.get(structure_type)
    if not catalog_def:
        return {'success': False, 'error': 'Invalid structure type'}

    # Extract level 1 data and flatten into a definition dict for backward compatibility
    level_1 = catalog_def.get('levels', {}).get(1, {})
    definition = {
        'name': catalog_def.get('name', structure_type),
        'description': catalog_def.get('description', ''),
        'icon': catalog_def.get('icon', ''),
        'generates_resource': catalog_def.get('generates_resource'),
        'cost_sepolia': level_1.get('cost', 0) / 10_000_000,  # Convert display to ETH units
        'build_time_seconds': level_1.get('build_time_days', 0) * 86400,
    }

    can_build, missing = get_build_requirements(structure_type, user_id)
    if not can_build:
        return {'success': False, 'error': f'Missing prerequisites: {", ".join(missing)}'}

    generation_rate = calculate_generation_rate(structure_type, latitude, longitude)
    # Apply build speed bonuses (Logistics stat, future tech/infra effects)
    from utilities.upgrades_utils import get_user_upgrade_effects
    build_mult = get_user_upgrade_effects(user_id).get('build_time_mult', 1.0)
    adjusted_seconds = max(60, definition['build_time_seconds'] * build_mult)  # Floor: 1 min
    ready_at = datetime.now() + timedelta(seconds=adjusted_seconds)

    # Initialize new_balance - will be set properly in payment block if cost > 0
    new_balance = None

    # Handle payment if cost > 0
    if definition['cost_sepolia'] > 0:
        wallet = get_user_primary_sepolia_wallet(user_id)
        if not wallet:
            return {'success': False, 'error': 'No wallet found'}
        
        # ✅ FIX: Convert Decimal to float for comparison and math
        current_balance = float(wallet.get('current_balance_eth', 0))
        cost_eth = float(definition['cost_sepolia'])

        if current_balance < cost_eth:
            return {
                'success': False,
                'error': f"Insufficient shards. Need {cost_eth * 10000000:.0f}, have {current_balance * 10000000:.0f}"
            }
        
        # Immediate DB balance deduction
        cost_display = cost_eth * 10000000
        new_balance = current_balance - cost_eth
        update_sepolia_wallet_balance(wallet['wallet_address'], new_balance)

        logger.info(f"💰 INFRASTRUCTURE PURCHASE: {definition['name']}")
        logger.info(f"   Cost: {cost_display:.1f} Sepolia ({cost_eth} ETH)")
        logger.info(f"   Build Time: {definition['build_time_seconds'] / 86400:.1f} days")
        logger.info(f"   Balance: {current_balance * 10000000:.1f} → {new_balance * 10000000:.1f} Sepolia")

        # Background blockchain tx + transaction logging
        from utilities.depot_utils import background_blockchain_tx
        background_blockchain_tx(
            wallet_address=wallet['wallet_address'],
            wallet_private_key=wallet['wallet_private_key'],
            amount_eth=cost_eth,
            reason=f"Building {definition['name']}",
            user_id=user_id, purchase_type='infrastructure_purchase',
            item_details={
                'structure_type': structure_type,
                'structure_name': definition['name'],
                'build_time_days': definition['build_time_seconds'] / 86400
            }
        )
    
    # Create infrastructure
    construction_id = create_infrastructure(
        user_id=user_id, structure_type=structure_type, structure_name=definition['name'],
        latitude=latitude, longitude=longitude, cost_sepolia=definition['cost_sepolia'],
        build_duration=definition['build_time_seconds'], generates_resource=definition.get('generates_resource'),
        generation_rate=generation_rate, ready_at=ready_at
    )
    
    if not construction_id:
        return {'success': False, 'error': 'Database error'}
    
    # ✅ Queue reward for free generators (runs async, doesn't block user)
    reward_result = None
    if definition['cost_sepolia'] == 0 and definition.get('generates_resource') == 'sepolia':
        # Queue the reward to be sent in the background - don't block the user
        # The reward will be credited when they next check their balance
        import threading

        def send_reward_async():
            try:
                wallet = get_user_primary_sepolia_wallet(user_id)
                if not wallet:
                    logger.warning(f"No wallet for user {user_id}, skipping infrastructure reward")
                    return

                miner = MarsAsteroidMiner()
                if not miner.connect():
                    logger.error(f"Failed to connect to Sepolia for infrastructure reward")
                    return

                coords = get_or_set_user_mars_home(user_id)
                lat = abs(coords['latitude'])
                efficiency = (1.0 - (lat / 90.0) * 0.4) * 100

                # Welcome bonus: 750 shards lets new players buy battery (10) + ice drill (500) with 240 left
                # This fixes the cold start problem where players grind for days with only 10/hr solar income
                initial_reward_eth = 0.000075  # 750 Sepolia display

                message = (
                    f"{definition['name']} deployed at {coords['latitude']:.2f}°N, {coords['longitude']:.2f}°E. "
                    f"Latitude efficiency: {efficiency:.1f}%. Solar constant: 590 W/m². "
                    f"First shard harvest complete. System now generating {generation_rate:.1f} Sepolia/hour. "
                )

                # Use FAST method - broadcast immediately
                result = miner.send_sepolia_reward_fast(
                    wallet['wallet_address'],
                    initial_reward_eth,
                    message,
                    context="infrastructure_completion"
                )

                if result['success']:
                    create_depot_transaction(
                        user_id=user_id,
                        wallet_address=wallet['wallet_address'],
                        purchase_type='infrastructure_completion',
                        amount_eth=initial_reward_eth,
                        tx_hash=result['tx_hash'],
                        etherscan_url=result['etherscan_url'],
                        item_details={
                            'construction_id': construction_id,
                            'structure_type': structure_type
                        }
                    )
                    logger.info(f"⚡ Infrastructure reward broadcast for user {user_id}: {initial_reward_eth * 10000000:.1f} Sepolia")
            except Exception as e:
                logger.error(f"Failed to send async infrastructure reward: {e}")

        # Start the reward in a background thread
        thread = threading.Thread(target=send_reward_async)
        thread.start()

        # Tell the user the reward is coming (optimistic response)
        reward_result = {
            'success': True,
            'amount': 750.0,  # 0.000075 ETH = 750 Sepolia display (welcome bonus)
            'pending': True,
            'message': 'Welcome bonus processing'
        }
    
    # Format time display
    days = definition['build_time_seconds'] / 86400
    hours = definition['build_time_seconds'] / 3600
    time_display = f"{days:.1f} days" if days >= 1 else f"{hours:.1f} hours" if hours >= 1 else f"{definition['build_time_seconds']} seconds"

    # For paid structures: use already-calculated new_balance (no re-query)
    # For free structures: get current balance from wallet
    if new_balance is None:
        wallet = get_user_primary_sepolia_wallet(user_id)
        new_balance = float(wallet.get('current_balance_eth', 0)) if wallet else 0
    new_balance_display = new_balance * 10000000

    return {
        'success': True,
        'construction_id': construction_id,
        'ready_at': ready_at.isoformat(),
        'time_display': time_display,
        'cost_paid': definition['cost_sepolia'] * 10000000 if definition['cost_sepolia'] > 0 else 0,
        'new_balance': new_balance_display,  # For immediate UI update - uses calculated value
        'reward_sent': reward_result is not None,
        'reward': reward_result
    }

def check_construction_status(construction_id):
    """
    Check if construction is complete
    ✅ FIXED: Auto-activates when build timer completes (no "ready to activate" limbo)
    """
    building = get_infrastructure_by_id(construction_id)
    if not building:
        return {'complete': False, 'error': 'Not found'}
    
    # Already active
    if building['status'] == 'active':
        return {
            'complete': True, 
            'already_active': True,
            'generation_rate': float(building['generation_rate']),
            'structure_type': building['structure_type']
        }
    
    # Check if build time elapsed (use UTC to match DB timestamps)
    elapsed = (datetime.utcnow() - building['build_started_at']).total_seconds()
    required = building['build_duration_seconds']
    
    if elapsed >= required:
        # ✅ AUTO-ACTIVATE: No "ready to activate" state, just go active
        update_infrastructure_status(construction_id, 'active')
        logger.info(f"✅ Auto-activated {building['structure_type']} (ID: {construction_id})")

        # 🎨 First-Reveal: Generate image for this building level
        # Currently all buildings are level 1, will expand when levels added
        try:
            from utilities.upgrade_image_utils import maybe_generate_infrastructure_image
            image_result = maybe_generate_infrastructure_image(
                structure_type=building['structure_type'],
                level=1,  # Currently all buildings are level 1
                user_id=building.get('user_id')
            )
            if image_result.get('is_first_reveal'):
                logger.info(f"🎉 First Reveal! User discovered {building['structure_type']} level 1 image")
        except Exception as e:
            logger.warning(f"Image generation failed (non-blocking): {e}")

        return {
            'complete': True,
            'generation_rate': float(building['generation_rate']),
            'structure_type': building['structure_type'],
            'is_first_reveal': image_result.get('is_first_reveal', False) if 'image_result' in dir() else False
        }
    
    # Still building
    return {
        'complete': False, 
        'progress': elapsed / required, 
        'remaining': required - elapsed
    }


def send_completion_reward(construction_id, user_id):
    """
    Send first payout when construction completes
    NOTE: This is now mostly legacy since free structures get immediate rewards in start_construction()
    """
    building = get_infrastructure_by_id(construction_id)
    if not building or not building['generates_resource'] or building['generates_resource'] != 'sepolia':
        return {'success': False, 'reason': 'Not a Sepolia generator'}
    
    wallet = get_user_primary_sepolia_wallet(user_id)
    if not wallet:
        return {'success': False, 'error': 'No wallet'}
    
    amount_eth = float(building['generation_rate']) / 10000000
    
    miner = MarsAsteroidMiner()
    if not miner.connect():
        return {'success': False, 'error': 'Network error'}
    
    coords = get_or_set_user_mars_home(user_id)
    lat = abs(coords['latitude'])
    efficiency = (1.0 - (lat / 90.0) * 0.4) * 100
    
    message = (
        f"{building['structure_name']} construction complete at {coords['latitude']:.2f}°N, {coords['longitude']:.2f}°E. "
        f"First shard harvest: {building['generation_rate']:.1f} Sepolia. "
        f"Latitude efficiency: {efficiency:.1f}%. System operational. "
    )

    # Use FAST method - broadcast immediately, don't wait for confirmation
    result = miner.send_sepolia_reward_fast(
        wallet['wallet_address'],
        amount_eth,
        message,
        context="infrastructure_completion"
    )

    if result['success']:
        create_depot_transaction(
            user_id=user_id,
            wallet_address=wallet['wallet_address'],
            purchase_type='infrastructure_completion',
            amount_eth=amount_eth,
            tx_hash=result['tx_hash'],
            etherscan_url=result['etherscan_url'],
            item_details={
                'construction_id': construction_id,
                'structure_type': building['structure_type']
            }
        )
        return {
            'success': True,
            'amount': amount_eth * 10000000,
            'tx_hash': result['tx_hash'],
            'broadcast': True
        }

    return {'success': False, 'error': 'Transaction failed'}


def user_has_maintenance_drone(user_id: int) -> bool:
    """Check if user has purchased the Maintenance Drone from shop"""
    from utilities.shop_utils import get_user_owned_items
    owned = get_user_owned_items(user_id)
    return 'maintenance_drone' in owned


def calculate_accumulated_income(user_id):
    """
    Calculate total accumulated Sepolia from all active generators.

    ACCUMULATION CAP (CORE MECHANIC - prevents infinite stacking):
    - ALL generators accumulate up to ACCUMULATION_CAP_HOURS (7 days) maximum
    - After 7 days, generation STOPS completely - no more shards accumulate
    - This is a HARD CAP: if you don't log in for a year, you still only get 7 days worth
    - User must claim to reset the timer and resume generation

    DUST STORM (VISUAL INDICATOR):
    - When solar arrays hit the cap, they show as "dust covered"
    - This is purely cosmetic - the cap is what actually stops generation
    - Maintenance Drone prevents the dust visual (cleaner look) but NOT the cap
    - Nuclear plants don't get dusty visually but still respect the cap

    NIGHT CYCLE:
    - Solar arrays generate 0% at night unless battery_storage is built (then 50%)
    """
    from utilities.postgres_utils import ensure_dust_covered_column, set_infrastructure_dust_covered
    ensure_dust_covered_column()  # Ensure column exists

    structures = get_user_infrastructure(user_id)
    coords = get_or_set_user_mars_home(user_id)
    total_accumulated = 0.0
    total_all_time = 0.0
    details = []
    dust_covered_structures = []  # Track which structures are dust-covered
    structures_at_cap = []  # Track structures that have hit the accumulation cap

    # ========================================================================
    # GET USER'S UPGRADE EFFECTS (passive_income_mult, passive_income_base, all_generation_mult)
    # Unified from UPGRADE_CATALOG (depot upgrades) + infrastructure + tech tree
    # ========================================================================
    try:
        from utilities.upgrades_utils import get_user_upgrade_effects
        from utilities.shop_utils import get_passive_income_source
        user_effects = get_user_upgrade_effects(user_id)
        passive_income_source = get_passive_income_source(user_id)  # Which item provides the mult
    except Exception as e:
        logger.warning(f"Could not get user upgrade effects: {e}")
        user_effects = {}
        passive_income_source = None

    # Tech passive mult extracted from user_effects (already merged by get_user_upgrade_effects)
    # No separate get_tech_effects call needed — it's already included
    tech_passive_mult = 1.0
    try:
        from utilities.tech_utils import get_tech_effects
        tech_effects = get_tech_effects(user_id)
        tech_passive_mult = tech_effects.get('passive_income_mult', 1.0)
    except Exception:
        pass

    # passive_income_mult: Combined from equipment + tech tree (both passive_income_mult sources)
    passive_income_mult = user_effects.get('passive_income_mult', 1.0)

    # passive_income_base: From Mining Drone (+10 shards/hour flat bonus)
    passive_income_base = user_effects.get('passive_income_base', 0)

    # all_generation_mult: From Fusion Shard Reactor infrastructure (doubles ALL generation)
    all_generation_mult = user_effects.get('all_generation_mult', 1.0)

    # Bulk-fetch all infrastructure levels in ONE query (fixes N+1 pattern)
    from utilities.upgrades_utils import get_all_infrastructure_levels
    all_levels = get_all_infrastructure_levels(user_id, structures=structures)

    # Check if user has battery storage for night generation
    has_battery = any(s['structure_type'] == 'battery_storage' and s['status'] == 'active' for s in structures)
    night_multiplier = 0.5 if has_battery else 0.0  # Battery enables 50% generation at night

    # Check if user has Maintenance Drone (prevents dust visual only, NOT the cap)
    has_maintenance_drone = user_has_maintenance_drone(user_id)

    for structure in structures:
        if structure['status'] != 'active' or not structure['generates_resource'] or structure['generates_resource'] != 'sepolia':
            continue

        total_all_time += float(structure.get('total_generated', 0))

        # Check if structure is already dust-covered (visual state only)
        is_dust_covered = structure.get('dust_covered', False)

        last_payout = structure.get('last_payout_at') or structure['build_completed_at'] or structure['created_at']
        hours_elapsed = (datetime.utcnow() - last_payout).total_seconds() / 3600

        # Use level-based catalog rate (supports infrastructure leveling)
        building_level = all_levels.get(structure['structure_type'], 1)
        if building_level < 1:
            building_level = 1  # Default to level 1 if no upgrade record

        db_rate = float(structure['generation_rate'])
        catalog_def = INFRASTRUCTURE_CATALOG.get(structure['structure_type'], {})
        level_data = catalog_def.get('levels', {}).get(building_level, {})
        catalog_rate = float(level_data.get('generation_rate', 0.0))

        # For solar_array, use calculate_generation_rate which factors in latitude + level
        if structure['structure_type'] == 'solar_array':
            hourly_rate = calculate_generation_rate('solar_array', coords['latitude'], coords['longitude'], building_level)
        else:
            hourly_rate = catalog_rate if catalog_rate > 0 else db_rate

        # ====================================================================
        # HARD CAP: Generation stops after ACCUMULATION_CAP_HOURS
        # This is the core fix - no matter how long you're gone, max is 7 days
        # ====================================================================
        capped_hours = min(hours_elapsed, ACCUMULATION_CAP_HOURS)
        at_cap = hours_elapsed >= ACCUMULATION_CAP_HOURS

        if at_cap:
            structures_at_cap.append(structure['structure_type'])

        # Solar arrays: affected by day/night cycle + Mars environment
        if structure['structure_type'] == 'solar_array':
            day_fraction, night_fraction = calculate_daylight_fraction(capped_hours, coords['longitude'])
            env_mult = _get_mars_environment_multiplier(coords['latitude'])
            # Maintenance Drone reduces dust penalty by 50% (keeps panels cleaner)
            if has_maintenance_drone:
                factors = _get_mars_environment_factors(coords['latitude'])
                dust = factors['dust']
                # Halve the dust penalty: dust_factor goes from 0.7 to 0.85
                improved_dust = dust + (1.0 - dust) * 0.5
                env_mult = round(improved_dust * factors['temperature'], 3)
            effective_rate = hourly_rate * (day_fraction + night_fraction * night_multiplier) * env_mult
            accumulated = effective_rate * capped_hours

            # Dust visual: show when at cap (unless have maintenance drone)
            if at_cap and not has_maintenance_drone and not is_dust_covered:
                set_infrastructure_dust_covered(user_id, structure['structure_type'], True)
                is_dust_covered = True

            if is_dust_covered:
                dust_covered_structures.append(structure['structure_type'])

            day_night_info = {
                'day_fraction': round(day_fraction, 2),
                'night_fraction': round(night_fraction, 2),
                'has_battery': has_battery,
                'effective_multiplier': round((day_fraction + night_fraction * night_multiplier) * env_mult, 2),
                'env_multiplier': round(env_mult, 2),
            }
        else:
            # Other generators (nuclear, refinery, etc.) run 24/7
            # Same cap applies - no infinite generation
            accumulated = hourly_rate * capped_hours
            day_night_info = None

        total_accumulated += accumulated

        detail = {
            'structure_type': structure['structure_type'],
            'structure_name': structure['structure_name'],
            'hourly_rate': hourly_rate,
            'hours_elapsed': hours_elapsed,
            'capped_hours': capped_hours,
            'accumulated': accumulated,
            'last_payout': last_payout,
            'dust_covered': is_dust_covered,
            'at_cap': at_cap,
            'cap_reached_hours_ago': max(0, hours_elapsed - ACCUMULATION_CAP_HOURS) if at_cap else 0
        }
        if day_night_info:
            detail['day_night'] = day_night_info
        details.append(detail)

    # ========================================================================
    # APPLY UPGRADE EFFECTS TO TOTAL
    # These were previously defined in config.py but never actually used!
    # ========================================================================

    # Track base total before bonuses (for UI display)
    base_accumulated = total_accumulated

    # 1. Apply passive_income_mult (from solar upgrades like High-Efficiency Panels)
    #    This multiplies ALL infrastructure generation
    if passive_income_mult > 1.0:
        total_accumulated *= passive_income_mult

    # 2. Apply all_generation_mult (from Fusion Shard Reactor infrastructure)
    #    This ALSO multiplies all generation (stacks with passive_income_mult)
    if all_generation_mult > 1.0:
        total_accumulated *= all_generation_mult

    # 3. Add passive_income_base (from Mining Drone - flat +10/hour)
    #    This is NOT affected by day/night (drones work 24/7)
    #    Still subject to the same accumulation cap
    if passive_income_base > 0 and details:
        # Use the average capped_hours from structures (or cap if no structures)
        avg_capped_hours = sum(d['capped_hours'] for d in details) / len(details) if details else ACCUMULATION_CAP_HOURS
        drone_income = passive_income_base * avg_capped_hours
        total_accumulated += drone_income

    # 4. Scientist shard generation bonus (analysis stat → % boost)
    #    +2% per analysis point, max +100% at 50 analysis
    #    Added per bug #1030 — Luke approved adding this mechanic
    scientist_shard_mult = 1.0
    try:
        from utilities.postgres_utils import get_user_scientist
        scientist = get_user_scientist(user_id)
        if scientist:
            analysis_stat = scientist.get('stats', {}).get('analysis', 0)
            scientist_shard_mult = 1.0 + (min(analysis_stat, 50) * 0.02)  # +2% per point, cap at +100%
            if scientist_shard_mult > 1.0:
                total_accumulated *= scientist_shard_mult
    except Exception:
        pass

    # ========================================================================
    # CALCULATE RATE BREAKDOWN FOR UI
    # This makes it easy for the frontend to show the math step-by-step
    # ========================================================================
    base_hourly_rate = sum(d['hourly_rate'] for d in details)  # Sum of infrastructure rates

    # Only use hours from structures that actually generate (ignore 0-rate structures like refinery)
    generating_details = [d for d in details if d['hourly_rate'] > 0]
    avg_hours = sum(d['capped_hours'] for d in generating_details) / len(generating_details) if generating_details else 0

    # Calculate the actual average rate this harvest period (most accurate)
    actual_avg_rate = round(total_accumulated / avg_hours, 1) if avg_hours > 0 else 0

    # Calculate day/night efficiency and environment multiplier for solar
    day_night_efficiency = 1.0  # Pure day/night cycle (without env baked in)
    mars_env_multiplier = 1.0
    mars_env_factors = None
    if details:
        solar_details = [d for d in details if d.get('day_night')]
        if solar_details:
            mars_env_multiplier = solar_details[0]['day_night'].get('env_multiplier', 1.0)
            # Separate day/night from env: effective_multiplier = day_night_only × env_mult
            # So day_night_only = effective_multiplier / env_mult
            env_m = mars_env_multiplier if mars_env_multiplier > 0 else 1.0
            avg_effective = sum(d['day_night']['effective_multiplier'] for d in solar_details) / len(solar_details)
            day_night_efficiency = round(avg_effective / env_m, 3) if env_m > 0 else avg_effective
            # Get individual env factors for UI breakdown
            mars_env_factors = _get_mars_environment_factors(coords['latitude'])

    # Effective base rate (after day/night + environment but before upgrades)
    effective_base_rate = round(base_hourly_rate * day_night_efficiency * mars_env_multiplier, 1)

    # Theoretical max rate (if 100% daytime, with all bonuses including scientist)
    theoretical_max_rate = round(((base_hourly_rate * passive_income_mult * all_generation_mult) + passive_income_base) * scientist_shard_mult, 1)

    # ========================================================================
    # BUILD GENERATORS BREAKDOWN FOR UI
    # List each generating structure with its contribution
    # ========================================================================
    generators_breakdown = []
    for d in generating_details:
        struct_type = d['structure_type']
        catalog_entry = INFRASTRUCTURE_CATALOG.get(struct_type, {})
        generators_breakdown.append({
            'structure_type': struct_type,
            'name': d['structure_name'],
            'icon': catalog_entry.get('icon', '⚡'),
            'hourly_rate': d['hourly_rate'],
            'has_day_night': d.get('day_night') is not None,  # True for solar_array
            'latitude_affected': struct_type == 'solar_array',
        })

    # ========================================================================
    # PASSIVE SCIENCE VALUE GENERATION
    # Research Station generates SV passively (scientist working at the bench)
    # Uses same accumulation cap as shards for consistency
    # ========================================================================
    sv_accumulated = 0.0
    sv_hourly_rate = 0.0
    for structure in structures:
        if structure['status'] != 'active':
            continue
        # Get level-based SV rate (using bulk-fetched levels)
        building_level = all_levels.get(structure['structure_type'], 1)
        if building_level < 1:
            building_level = 1

        catalog_def = INFRASTRUCTURE_CATALOG.get(structure['structure_type'], {})
        level_data = catalog_def.get('levels', {}).get(building_level, {})
        sv_rate = float(level_data.get('science_generation_rate', 0))
        if sv_rate <= 0:
            continue
        sv_hourly_rate += sv_rate
        last_payout = structure.get('last_payout_at') or structure['build_completed_at'] or structure['created_at']
        hours_elapsed = (datetime.utcnow() - last_payout).total_seconds() / 3600
        capped_hours = min(hours_elapsed, ACCUMULATION_CAP_HOURS)
        sv_accumulated += sv_rate * capped_hours

    # Scientist analysis stat boosts SV generation (+2% per point, max +100% at 50)
    try:
        from utilities.postgres_utils import get_user_scientist
        scientist = get_user_scientist(user_id)
        if scientist:
            analysis_stat = scientist.get('stats', {}).get('analysis', 0)
            sv_bonus = 1.0 + (analysis_stat / 50.0)
            sv_accumulated *= sv_bonus
            sv_hourly_rate *= sv_bonus
    except Exception:
        pass

    return {
        'total_accumulated': round(total_accumulated, 2),
        'base_accumulated': round(base_accumulated, 2),  # Before bonuses
        'total_all_time': round(total_all_time, 2),
        'details': details,
        'can_claim': total_accumulated > 0.1,
        'has_battery': has_battery,
        'has_maintenance_drone': has_maintenance_drone,
        'dust_covered_structures': dust_covered_structures,
        'any_dust_covered': len(dust_covered_structures) > 0,
        'structures_at_cap': structures_at_cap,
        'any_at_cap': len(structures_at_cap) > 0,
        'cap_hours': ACCUMULATION_CAP_HOURS,
        'cap_days': ACCUMULATION_CAP_HOURS / 24,
        # Bonuses breakdown
        'bonuses_applied': {
            'passive_income_mult': passive_income_mult,
            'passive_income_source': passive_income_source,  # Which item provides the mult (name, icon)
            'tech_passive_mult': tech_passive_mult,  # Tech-tree-only component (for UI visibility)
            'all_generation_mult': all_generation_mult,
            'passive_income_base': passive_income_base,
            'scientist_shard_mult': scientist_shard_mult,  # Analysis stat → shard gen boost
        },
        # Rate breakdown for UI (NEW)
        'rate_breakdown': {
            'base_hourly_rate': round(base_hourly_rate, 1),  # Raw infrastructure rate
            'day_night_efficiency': round(day_night_efficiency * 100, 0),  # Pure day/night cycle %
            'effective_base_rate': effective_base_rate,  # After day/night + environment
            'theoretical_max_rate': theoretical_max_rate,  # Max possible with all bonuses
            'actual_avg_rate': actual_avg_rate,  # What you're actually getting this period
            'mars_env_multiplier': round(mars_env_multiplier * 100, 0),  # Combined env % (dust × temp)
            'mars_env_factors': mars_env_factors,  # Individual: dust, temperature, latitude, condition
        },
        'generators_breakdown': generators_breakdown,  # List of generating structures with rates
        'latitude': coords['latitude'],
        # Science Value generation
        'sv_accumulated': round(sv_accumulated, 1),
        'sv_hourly_rate': round(sv_hourly_rate, 1),
    }


def claim_accumulated_income(user_id, session=None):
    """Claim all accumulated Sepolia from generators and send to wallet"""
    calc = calculate_accumulated_income(user_id)
    
    if not calc['can_claim']:
        return {
            'success': False, 
            'error': 'No income to claim (minimum: 0.1 Sepolia)', 
            'accumulated': calc['total_accumulated']
        }
    
    wallet = get_user_primary_sepolia_wallet(user_id)
    if not wallet:
        return {'success': False, 'error': 'No wallet found'}
    
    coords = get_or_set_user_mars_home(user_id)
    
    miner = MarsAsteroidMiner()
    if not miner.connect():
        return {'success': False, 'error': 'Network unavailable'}
    
    try:
        amount_eth = calc['total_accumulated'] / 10000000
        total_hours = sum(d['hours_elapsed'] for d in calc['details'])
        
        # Build harvest details
        harvest_details = []
        for detail in calc['details']:
            if detail['structure_type'] == 'solar_array':
                lat = abs(coords['latitude'])
                efficiency = (1.0 - (lat / 90.0) * 0.4) * 100
                harvest_details.append(
                    f"Solar Array at {coords['latitude']:.2f}°N {coords['longitude']:.2f}°E: "
                    f"{detail['accumulated']:.1f} Sepolia over {detail['hours_elapsed']:.1f}h. "
                    f"Efficiency: {efficiency:.1f}%. "
                )
        
        # Create harvest message
        message = (
            f"Colony shard systems generated {calc['total_accumulated']:.1f} Sepolia over {total_hours:.1f} hours. "
            f"Base: {coords['latitude']:.2f}°N, {coords['longitude']:.2f}°E. "
            f"{''.join(harvest_details)}"
            f"Resources harvested and transferred to cache. "
        )

        # Use FAST method - broadcast immediately, don't wait for confirmation
        result = miner.send_sepolia_reward_fast(
            wallet['wallet_address'],
            amount_eth,
            message,
            context="infrastructure_income"
        )

        if not result['success']:
            return {'success': False, 'error': 'Transaction failed'}

        # Log transaction
        create_depot_transaction(
            user_id=user_id,
            wallet_address=wallet['wallet_address'],
            purchase_type='infrastructure_income',
            amount_eth=amount_eth,
            tx_hash=result['tx_hash'],
            etherscan_url=result['etherscan_url'],
            item_details={
                'hours_accumulated': total_hours,
                'structures': [d['structure_type'] for d in calc['details']],
                'base_coordinates': {
                    'latitude': coords['latitude'],
                    'longitude': coords['longitude']
                },
                'solar_efficiency_percent': (1.0 - (abs(coords['latitude']) / 90.0) * 0.4) * 100,
                'structure_details': calc['details']
            }
        )
        
        # Update last_payout_at for all structures AND clear dust
        conn = get_db_connection()
        cur = conn.cursor()
        for structure in calc['details']:
            # Reset last_payout_at, add to total_generated, AND clear dust_covered
            cur.execute("""
                UPDATE pilgrim.colony_infrastructure
                SET last_payout_at = NOW(),
                    total_generated = total_generated + %s,
                    dust_covered = FALSE,
                    dust_covered_at = NULL,
                    updated_at = NOW()
                WHERE user_id = %s AND structure_type = %s AND status = 'active'
            """, (structure['accumulated'], user_id, structure['structure_type']))
        conn.commit()
        cur.close()
        conn.close()

        # Log dust clearing if any were covered
        dust_cleared = calc.get('any_dust_covered', False)
        if dust_cleared:
            logger.info(f"✨ Dust cleared from solar arrays for user {user_id}")

        logger.info(f"✅ User {user_id} harvested {calc['total_accumulated']} Sepolia from {coords['latitude']:.2f}°N, {coords['longitude']:.2f}°E")

        # Calculate new balance: session cache + claimed amount (NO blockchain re-query)
        if session is not None:
            from utilities.depot_utils import update_session_balance
            old_balance = session.get('_bal', 0)
            new_balance = old_balance + calc['total_accumulated']
            update_session_balance(session, new_balance)
        else:
            # No session - use DB cached balance as fallback
            from utilities.depot_utils import get__bal
            old_balance = get__bal(user_id)
            new_balance = old_balance + calc['total_accumulated']

        # Update activity timestamp for ARIA photo generation
        from utilities.postgres_utils import update_user_activity
        update_user_activity(user_id)

        return {
            'success': True,
            'amount_claimed': calc['total_accumulated'],
            'new_balance': new_balance,  # For immediate UI update - calculated, not re-queried
            'tx_hash': result['tx_hash'],
            'etherscan_url': result['etherscan_url'],
            'details': calc['details'],
            'base_coordinates': coords,
            'dust_cleared': dust_cleared,
            'panels_cleaned': len(calc.get('dust_covered_structures', []))
        }

    except Exception as e:
        logger.error(f"Failed to claim income for user {user_id}: {e}")
        return {'success': False, 'error': str(e)}


def record_science_value(user_id):
    """Record (claim) accumulated Science Value from Research Station. Separate from shard harvest."""
    calc = calculate_accumulated_income(user_id)
    sv_amount = calc.get('sv_accumulated', 0)

    if sv_amount < 1:
        return {'success': False, 'error': 'Not enough SV to record (minimum: 1)'}

    from utilities.postgres_utils import add_passive_sv, get_db_connection
    add_passive_sv(user_id, sv_amount)

    # Reset last_payout_at on ALL SV-generating buildings so SV doesn't re-accumulate
    # (research_station + xenobiology_lab + any future SV generators)
    sv_building_types = [stype for stype, cat in INFRASTRUCTURE_CATALOG.items()
                         if any(lv.get('science_generation_rate', 0) > 0
                                for lv in cat.get('levels', {}).values())]
    if sv_building_types:
        from utilities.postgres_utils import db_cursor as _db_cursor
        with _db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE pilgrim.colony_infrastructure
                SET last_payout_at = NOW(), updated_at = NOW()
                WHERE user_id = %s AND structure_type = ANY(%s) AND status = 'active'
            """, (user_id, sv_building_types))

    logger.info(f"🔬 User {user_id} recorded {sv_amount:.1f} SV")

    from utilities.tech_utils import _get_available_sv
    return {
        'success': True,
        'sv_recorded': round(sv_amount, 1),
        'sv_available': _get_available_sv(user_id),
    }


def get_infrastructure_page_data(user_id: int) -> dict:
    """
    Get all data needed for the colony/infrastructure page.
    Consolidates ~30 lines of logic from app.py.

    Returns:
        dict with all template variables for infrastructure.html
    """
    from datetime import datetime

    coords = get_or_set_user_mars_home(user_id)
    existing_raw = get_user_infrastructure(user_id)

    # Enrich buildings with catalog data, separate active vs building
    from utilities.upgrades_utils import get_infrastructure_level, get_upgrade_build_status
    existing = []  # Only active (completed) buildings for "Your Colony"
    building_infrastructure = []  # Still building - goes in "Under Construction"

    for building in existing_raw:
        enriched = dict(building)
        catalog_def = INFRASTRUCTURE_CATALOG.get(building['structure_type'], {})
        # Get current level for this building
        current_level = get_infrastructure_level(user_id, building['structure_type'])
        if current_level < 1:
            current_level = 1
        level_data = catalog_def.get('levels', {}).get(current_level, {})

        enriched['image_url'] = level_data.get('image_url', '')
        enriched['description'] = catalog_def.get('description', '')
        enriched['effect'] = catalog_def.get('effect')
        enriched['effect_value'] = catalog_def.get('effect_value')
        enriched['generates_resource'] = catalog_def.get('generates_resource')
        enriched['tier'] = catalog_def.get('tier', 1)
        enriched['cost_display'] = int(level_data.get('cost', 0))  # Already in display units
        enriched['category'] = catalog_def.get('category', 'general')
        enriched['total_generated'] = float(building.get('total_generated', 0) or 0)

        # Level information
        enriched['level'] = current_level
        enriched['max_level'] = catalog_def.get('max_level', 10)
        enriched['level_name'] = level_data.get('name', f'Level {current_level}')

        # Check for in-progress upgrade
        upgrade_status = get_upgrade_build_status(user_id, 'infrastructure', building['structure_type'])
        enriched['is_upgrading'] = upgrade_status.get('is_building', False) if upgrade_status else False
        enriched['upgrade_status'] = upgrade_status

        # Next level info for upgrade button
        if current_level < catalog_def.get('max_level', 10):
            next_level_data = catalog_def.get('levels', {}).get(current_level + 1, {})
            enriched['next_level_cost'] = int(next_level_data.get('cost', 0))
            enriched['next_level_name'] = next_level_data.get('name', f'Level {current_level + 1}')
            enriched['next_build_time_days'] = next_level_data.get('build_time_days', 0)
        else:
            enriched['next_level_cost'] = None
            enriched['is_max_level'] = True

        # Use level-based catalog rate
        # For solar_array, calculate based on latitude + level; for others, use catalog value
        if building['structure_type'] == 'solar_array':
            enriched['generation_rate'] = calculate_generation_rate('solar_array', coords['latitude'], coords['longitude'], current_level)
        else:
            enriched['generation_rate'] = float(level_data.get('generation_rate', 0.0))

        if building['status'] == 'active':
            existing.append(enriched)
        elif building['status'] == 'building':
            building_infrastructure.append(enriched)

    # Include both active AND building for type checking (don't allow duplicate builds)
    existing_types = {b['structure_type']: b for b in existing_raw}

    available_structures = []
    for structure_type, definition in INFRASTRUCTURE_CATALOG.items():
        if structure_type in existing_types:
            continue
        # NOTE: No longer hiding advanced buildings - they show but are locked until prereqs met

        can_build, missing = get_build_requirements(structure_type, user_id)
        rate = calculate_generation_rate(structure_type, coords['latitude'], coords['longitude'])

        # Flatten level 1 data into definition for template compatibility
        level_1 = definition.get('levels', {}).get(1, {})
        enriched_definition = {
            **definition,
            'cost_sepolia': level_1.get('cost', 0) / 10_000_000,  # Convert to Sepolia units
            'build_time_seconds': level_1.get('build_time_days', 0) * 86400,
            'image_url': level_1.get('image_url', ''),
            'generation_rate': level_1.get('generation_rate', 0),
        }

        available_structures.append({
            'type': structure_type,
            'definition': enriched_definition,
            'can_build': can_build,
            'missing_requirements': missing,
            'generation_rate': rate
        })

    return {
        'coords': coords,
        'structures': available_structures,
        'existing': existing,
        'building_infrastructure': building_infrastructure,
        'now': datetime.now()
    }


def handle_infrastructure_build(user_id, structure_type, session):
    """
    Handle infrastructure build request - check prereqs, start construction, update session.
    Consolidates route logic from app.py.
    """
    import time
    from utilities.depot_utils import update_session_balance

    if not structure_type:
        return {'success': False, 'error': 'Missing structure_type'}

    existing = get_user_infrastructure(user_id, structure_type)
    if existing and len(existing) > 0:
        return {'success': False, 'error': 'Structure already built', 'already_exists': True}

    active_construction = session.get('active_construction')
    if active_construction and active_construction.get('type') == structure_type:
        return {'success': False, 'error': 'Construction already in progress', 'in_progress': True}

    coords = get_or_set_user_mars_home(user_id)
    result = start_construction(user_id, structure_type, coords['latitude'], coords['longitude'])

    if result['success']:
        session['active_construction'] = {
            'id': result['construction_id'],
            'type': structure_type,
            'started_at': time.time()
        }
        session['construction_reward_sent'] = False
        # Update session cache with calculated balance - NO re-query
        update_session_balance(session, result['new_balance'])
        session.modified = True
        # Update activity timestamp for ARIA photo generation
        from utilities.postgres_utils import update_user_activity
        update_user_activity(user_id)

    return result


def handle_infrastructure_status(session):
    """
    Check construction status and send reward if complete.
    Consolidates route logic from app.py.
    """
    construction = session.get('active_construction')
    if not construction:
        return {'complete': False, 'error': 'No active construction'}

    status = check_construction_status(construction['id'])

    if status.get('complete') and not session.get('construction_reward_sent'):
        user_id = session.get('user_id')
        reward = send_completion_reward(construction['id'], user_id)

        if reward.get('success'):
            session['construction_reward_sent'] = True
            session.modified = True
            status['reward'] = reward
        else:
            status['reward'] = {'success': False, 'error': reward.get('error')}

    return status


def handle_accumulated_income(user_id):
    """
    Get accumulated income with total_all_time calculated.
    Consolidates route logic from app.py.
    """
    result = calculate_accumulated_income(user_id)
    structures = get_user_infrastructure(user_id)
    total_all_time = sum(float(s.get('total_generated', 0)) for s in structures)
    result['total_all_time'] = total_all_time
    return result


def get_user_infrastructure_effects(user_id: int) -> dict:
    """
    Calculate all effects from user's active infrastructure at their current levels.
    Uses level-based effects from INFRASTRUCTURE_CATALOG.

    Returns dict of effect_name -> value that can be merged with upgrade_effects:
    {
        'discovery_chance_bonus': 0.15,  # From comms_array level
        'discovery_value_mult': 1.5,     # From research_station level
        ...
    }

    NOTE: Expedition slots = min(vehicles owned, habitat expedition_capacity).
    Habitat module Lv1-3=1-2 slots, Lv4-5=3, Lv6-7=4, Lv8-9=5, Lv10=6.
    Default 3 slots if no habitat module built.
    """
    from utilities.upgrades_utils import get_all_infrastructure_levels

    structures = get_user_infrastructure(user_id)
    active_types = {s['structure_type'] for s in structures if s['status'] == 'active'}

    # Bulk-fetch all levels in ONE query (fixes N+1 pattern)
    all_levels = get_all_infrastructure_levels(user_id, structures=structures)

    effects = {}

    # Effect aggregation helper - same rules as upgrades_utils
    def apply_effect(key, value):
        if key not in effects:
            effects[key] = value
            return
        current = effects[key]
        if key.endswith('_mult'):
            if 'cost' in key:
                effects[key] = min(current, value)  # Lower is better for costs
            else:
                effects[key] = max(current, value)  # Higher is better for bonuses
        elif key.endswith('_bonus') or key.endswith('_base') or key.endswith('_rate'):
            effects[key] = current + value  # Additive
        elif isinstance(value, bool):
            effects[key] = current or value  # OR for booleans
        else:
            effects[key] = value  # Default: overwrite

    # Process each active building's level-based effects
    for building_type in active_types:
        level = all_levels.get(building_type, 1)
        if level < 1:
            continue

        catalog = INFRASTRUCTURE_CATALOG.get(building_type, {})
        level_data = catalog.get('levels', {}).get(level, {})

        # Apply all effect-type stats from level data
        for key, value in level_data.items():
            # Skip non-effect fields
            if key in ['name', 'cost', 'build_time_days', 'image_url', 'generation_rate', 'science_generation_rate']:
                continue

            # Map specific infrastructure effects to standard effect names
            if key == 'fuel_cost_reduction':
                apply_effect('fuel_cost_mult', 1.0 - value)  # -10% -> 0.90 mult
            elif key == 'life_support_reduction':
                apply_effect('life_support_cost_mult', 1.0 - value)
            elif key == 'night_generation':
                apply_effect('night_generation_mult', value)
            elif key == 'discovery_bonus':
                apply_effect('discovery_chance_bonus', value)
            elif key == 'discovery_value_mult':
                apply_effect('discovery_value_mult', value)
            elif key == 'bio_value_mult':
                apply_effect('bio_discovery_value_mult', value)
            elif key == 'all_generation_mult':
                apply_effect('all_generation_mult', value)
            elif key == 'dust_storm_immune':
                apply_effect('dust_storm_immune', value)
            elif key == 'legendary_discovery_chance':
                apply_effect('legendary_chance_bonus', value)
            elif key == 'expedition_capacity':
                # expedition_capacity is the TOTAL max slots (not additive), take highest
                apply_effect('expedition_capacity', value)
            elif key == 'research_enabled':
                apply_effect('research_enabled', value)

    # Calculate total Sepolia generation rate from all active generators
    total_sepolia_rate = 0.0
    for structure in structures:
        if structure['status'] == 'active' and structure.get('generates_resource') == 'sepolia':
            total_sepolia_rate += float(structure.get('generation_rate', 0))

    if total_sepolia_rate > 0:
        effects['sepolia_generation_rate'] = total_sepolia_rate

    return effects


# ============================================================================
# XENOBIOLOGY LAB - RESEARCH SYSTEM
# ============================================================================

def _get_experiment_cost(total_experiments: int) -> int:
    """Calculate experiment cost based on total experiments run (escalating)"""
    if total_experiments < 5:
        return 5000 + (total_experiments * 200)
    elif total_experiments < 10:
        return 6000 + ((total_experiments - 5) * 300)
    elif total_experiments < 20:
        return 7500 + ((total_experiments - 10) * 500)
    return 12500 + ((total_experiments - 20) * 1000)

def _get_experiment_max_roll(total_experiments: int) -> int:
    """Get max roll range based on experiments run (decreases over time)"""
    if total_experiments < 5:
        return 6
    elif total_experiments < 10:
        return 5
    elif total_experiments < 20:
        return 4
    elif total_experiments < 35:
        return 3
    elif total_experiments < 50:
        return 2
    return 1

def get_xenobiology_status(user_id: int) -> dict:
    """Get research status for Xenobiology Lab modal"""
    from utilities.postgres_utils import get_user_research_data, get_user_infrastructure, get_commander_stats
    from utilities.depot_utils import get_fast_balance_and_wallet_info
    from config import MAX_DISPLAY_STAT

    infrastructure = get_user_infrastructure(user_id, 'xenobiology_lab')
    has_lab = any(i['status'] == 'active' for i in infrastructure) if infrastructure else False
    if not has_lab:
        return {'success': False, 'error': 'Xenobiology Lab not built'}

    research_data = get_user_research_data(user_id)
    commander_stats = get_commander_stats(user_id)
    balance, _, _ = get_fast_balance_and_wallet_info(user_id)

    total_experiments = research_data.get('total_experiments_run', 0)
    experiment_cost = _get_experiment_cost(total_experiments)
    max_roll = _get_experiment_max_roll(total_experiments)

    stat_bonuses = research_data.get('stat_bonuses', {})
    effective_stats = {}
    for stat in ['leadership', 'strategy', 'exploration', 'logistics', 'charisma']:
        base = commander_stats.get(stat, 0) if commander_stats else 0
        bonus = stat_bonuses.get(stat, 0)
        effective_stats[stat] = {
            'base': base, 'bonus': bonus,
            'total': min(base + bonus, MAX_DISPLAY_STAT + 10),
            'can_upgrade': bonus < 10 and base + bonus < MAX_DISPLAY_STAT + 10
        }

    return {
        'success': True,
        'research_points': research_data.get('research_points', 0),
        'total_experiments': total_experiments,
        'experiment_cost': experiment_cost,
        'max_roll': max_roll,
        'current_balance': balance,
        'can_afford': balance >= experiment_cost,
        'effective_stats': effective_stats
    }

def run_xenobiology_experiment(user_id: int, session) -> dict:
    """Run an experiment to gain research points"""
    import random
    from utilities.postgres_utils import get_user_research_data, add_research_points, get_user_infrastructure
    from utilities.depot_utils import get_fast_balance_and_wallet_info, invalidate_balance_cache
    from utilities.sepolia_utils import MarsAsteroidMiner
    from utilities.depot_utils import display_to_eth

    infrastructure = get_user_infrastructure(user_id, 'xenobiology_lab')
    has_lab = any(i['status'] == 'active' for i in infrastructure) if infrastructure else False
    if not has_lab:
        return {'success': False, 'error': 'Xenobiology Lab not built'}

    research_data = get_user_research_data(user_id)
    total_experiments = research_data.get('total_experiments_run', 0)
    experiment_cost = _get_experiment_cost(total_experiments)
    max_roll = _get_experiment_max_roll(total_experiments)

    balance, _, primary_wallet = get_fast_balance_and_wallet_info(user_id)
    if balance < experiment_cost:
        return {'success': False, 'error': f'Need {experiment_cost} shards, have {balance:.1f}'}
    if not primary_wallet:
        return {'success': False, 'error': 'No wallet found'}

    points_gained = random.randint(1, max_roll)

    miner = MarsAsteroidMiner()
    tx_result = miner.log_transaction(
        private_key=primary_wallet['wallet_private_key'],
        amount_eth=display_to_eth(experiment_cost),
        message=f"XENO_EXP:{points_gained}pts"
    )
    if not tx_result.get('success'):
        return {'success': False, 'error': 'Transaction failed'}

    add_research_points(user_id, points_gained)
    invalidate_balance_cache(session)

    return {
        'success': True,
        'points_gained': points_gained,
        'max_roll': max_roll,
        'new_total_points': research_data.get('research_points', 0) + points_gained,
        'experiments_run': total_experiments + 1,
        'tx_hash': tx_result.get('tx_hash')
    }

def upgrade_xenobiology_stat(user_id: int, stat_name: str) -> dict:
    """Spend research points to upgrade a stat"""
    from utilities.postgres_utils import get_user_research_data, spend_research_points, get_commander_stats
    from config import MAX_DISPLAY_STAT

    if stat_name not in ['leadership', 'strategy', 'exploration', 'logistics', 'charisma']:
        return {'success': False, 'error': 'Invalid stat'}

    research_data = get_user_research_data(user_id)
    commander_stats = get_commander_stats(user_id)
    stat_bonuses = research_data.get('stat_bonuses', {})

    current_bonus = stat_bonuses.get(stat_name, 0)
    base_stat = commander_stats.get(stat_name, 0) if commander_stats else 0

    if current_bonus >= 10:
        return {'success': False, 'error': 'Stat bonus already at maximum (+10)'}
    if base_stat + current_bonus >= MAX_DISPLAY_STAT + 10:
        return {'success': False, 'error': 'Stat already at absolute maximum (100)'}

    if research_data.get('research_points', 0) < 1:
        return {'success': False, 'error': 'Need 1 research point'}

    result = spend_research_points(user_id, stat_name, 1)
    if not result:
        return {'success': False, 'error': 'Failed to upgrade stat'}

    new_bonus = result['stat_bonuses'].get(stat_name, 0)
    return {
        'success': True,
        'stat': stat_name,
        'new_bonus': new_bonus,
        'new_total': base_stat + new_bonus,
        'remaining_points': result['research_points']
    }