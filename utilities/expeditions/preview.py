"""
Expedition pre-launch previews: cost modal, route modal, shard estimate.

Pure orchestration — reads captain/scientist/fleet state and runs the cost
engine in preview mode. No DB writes, no blockchain calls. Uses cached gas
pricing so preview is near-instant.
"""

import logging

from utilities.expeditions.config import (
    BASE_SPEED_KM_PER_HOUR,
    EVA_HOURS_PER_DAY,
    TERRAIN_MODIFIERS,
)
from utilities.expeditions.cost import calculate_expedition_cost
from utilities.expeditions.travel import calculate_segmented_travel_time
from utilities.postgres.trails import TRAIL_SPEED_MULTIPLIERS

logger = logging.getLogger(__name__)


def get_expedition_cost_preview(
    user_id: int,
    distance_km: float,
    destination_type: str
) -> dict:
    """
    Calculate full expedition cost preview including gas and atmospheric fees.

    SPEED OPTIMIZATION: Uses cached gas pricing instead of blockchain calls.
    Preview calculations use DB-cached balance (synced hourly by cron).
    Actual launch still uses live blockchain for transaction execution.
    """
    from utilities.postgres.wallets import get_user_primary_sepolia_wallet
    from utilities.postgres.map import get_or_set_user_mars_home
    from utilities.postgres.expeditions import get_user_completed_expeditions_count
    from utilities.depot_utils import (
        eth_to_display,
        generate_commander_stats,
        calculate_cached_transaction_cost
    )

    if not distance_km:
        return {'success': False, 'error': 'Missing distance'}

    wallet = get_user_primary_sepolia_wallet(user_id)
    if not wallet:
        return {'success': False, 'error': 'No wallet found'}

    base_coords = get_or_set_user_mars_home(user_id)

    commander_stats = generate_commander_stats()
    expeditions_completed = get_user_completed_expeditions_count(user_id)

    # Get user's upgrade effects for cost calculation
    upgrade_effects = None
    try:
        from utilities.upgrades_utils import get_user_upgrade_effects
        upgrade_effects = get_user_upgrade_effects(user_id)
    except ImportError:
        pass

    expedition_pricing = calculate_expedition_cost(
        distance_km=distance_km,
        destination_type=destination_type,
        commander_stats=commander_stats,
        user_expeditions_completed=expeditions_completed,
        base_coords=base_coords,
        upgrade_effects=upgrade_effects
    )

    base_expedition_cost_eth = expedition_pricing['base_expedition_cost'] / 10000000

    # SPEED: Use DB-cached balance instead of blockchain call
    current_balance_eth = float(wallet.get('current_balance_eth', 0) or 0)

    # SPEED: Use cached gas pricing (no blockchain call needed for preview)
    cached_pricing = calculate_cached_transaction_cost(
        base_expedition_cost_eth,
        user_balance_eth=current_balance_eth,
        message_length=250
    )

    gas_cost_eth = cached_pricing['gas_cost_eth']
    atmospheric_fee_eth = cached_pricing['atmospheric_fee_eth']
    atmospheric_fee_multiplier = cached_pricing['conditions']['fee_multiplier']
    total_cost_eth = cached_pricing['total_cost_eth']

    is_first_mission = expeditions_completed == 0
    first_mission_cap_applied = False

    # Apply first mission cap in PREVIEW (not just at launch)
    if is_first_mission and current_balance_eth > 0:
        max_first_mission_cost_eth = current_balance_eth * 0.5

        if total_cost_eth > max_first_mission_cost_eth:
            logger.info(f"🎁 PREVIEW: First mission cap applied - original {total_cost_eth * 10000000:.1f}, capping to {max_first_mission_cost_eth * 10000000:.1f}")

            remaining_for_base = max_first_mission_cost_eth - gas_cost_eth

            if remaining_for_base > 0:
                base_expedition_cost_eth = remaining_for_base / (1 + (atmospheric_fee_multiplier - 1.0))
                atmospheric_fee_eth = base_expedition_cost_eth * (atmospheric_fee_multiplier - 1.0)
                total_cost_eth = base_expedition_cost_eth + atmospheric_fee_eth + gas_cost_eth
                first_mission_cap_applied = True
            else:
                logger.warning(f"⚠️ User balance too low for first mission cap ({current_balance_eth} ETH)")
                return {
                    'success': False,
                    'error': f'Insufficient balance. Need at least {eth_to_display(gas_cost_eth * 2)} shards to cover operations.'
                }

    can_afford = current_balance_eth >= total_cost_eth

    return {
        'success': True,
        'expedition_pricing': expedition_pricing,
        'total_pricing': {
            'base_cost_eth': base_expedition_cost_eth,
            'base_cost_display': base_expedition_cost_eth * 10000000,
            'atmospheric_fee_eth': atmospheric_fee_eth,
            'atmospheric_fee_display': atmospheric_fee_eth * 10000000,
            'gas_cost_eth': gas_cost_eth,
            'gas_cost_display': gas_cost_eth * 10000000,
            'total_cost_eth': total_cost_eth,
            'total_cost_display': total_cost_eth * 10000000,
            'conditions': cached_pricing['conditions'],
            'can_afford': can_afford,
            'current_balance_eth': current_balance_eth,
            'current_balance_display': current_balance_eth * 10000000,
            'shortfall_eth': max(0, total_cost_eth - current_balance_eth),
            'shortfall_display': max(0, (total_cost_eth - current_balance_eth) * 10000000),
            'first_mission_cap_applied': first_mission_cap_applied,
            'is_first_mission': is_first_mission
        },
        'commander_stats': commander_stats,
        'expeditions_completed': expeditions_completed
    }


def get_expedition_preview(user_id: int, distance_km: float, destination_type: str, destination_name: str = '') -> dict:
    """
    Comprehensive pre-launch preview for the expedition modal.
    Returns all data needed: vehicles, trip estimates, speed breakdown,
    captain stats, scientist info, fleet status, discovery potential.
    """
    from utilities.postgres.map import get_or_set_user_mars_home
    from utilities.postgres.expeditions import get_user_active_expeditions, get_user_completed_expeditions_count, get_user_discovered_landmarks
    from utilities.postgres.users import get_user_scientist
    from utilities.upgrades_utils import get_user_owned_vehicles
    from utilities.depot_utils import get_commander_and_stats

    if not distance_km:
        return {'success': False, 'error': 'Missing distance'}

    # Captain stats + image (with EVA Suit bonuses)
    from utilities.shop_utils import get_effective_commander_stats
    commander, base_stats = get_commander_and_stats(user_id)
    if not base_stats:
        base_stats = {'exploration': 50, 'leadership': 50, 'strategy': 50, 'logistics': 50, 'charisma': 50}
    # Apply EVA Suit stat bonuses
    commander_stats = get_effective_commander_stats(user_id, base_stats)
    captain_name = commander.get('name', 'Captain') if commander else 'Captain'
    captain_image = None
    try:
        from utilities.depot_utils import get_latest_character_image
        img_url, _ = get_latest_character_image(user_id)
        captain_image = img_url
    except Exception:
        pass

    # Scientist info with stats
    scientist = get_user_scientist(user_id)
    scientist_stats = scientist.get('stats', {}) if scientist else {}
    nav_stat = scientist_stats.get('navigation', 0)
    scientist_nav_mult = round(1.0 + (nav_stat / 150.0), 3)  # nav=50 → ×1.33
    scientist_info = {
        'name': scientist.get('name', 'None'),
        'specialty': scientist.get('specialty', ''),
        'image_url': scientist.get('image_url', ''),
        'nav_mult': scientist_nav_mult,
        'stats': scientist_stats,
    } if scientist else None

    # Fleet status
    active_expeditions = get_user_active_expeditions(user_id)
    fleet_status = []
    active_types = set()
    for exp in active_expeditions:
        if exp['status'] in ('traveling', 'recalled'):
            active_types.add(exp.get('vehicle_type', 'rover'))
            fleet_status.append({
                'vehicle_type': exp.get('vehicle_type', 'rover'),
                'destination': exp['destination_name'],
                'status': exp['status'],
                'return_arrives_at': exp['return_arrives_at'].isoformat() + 'Z' if exp.get('return_arrives_at') else None
            })

    # All owned vehicles with availability
    owned_vehicles = get_user_owned_vehicles(user_id)
    vehicles = []
    for v in owned_vehicles:
        available = v['vehicle_type'] not in active_types
        vehicles.append({**v, 'available': available})

    # Speed breakdown and trip estimate per vehicle
    base_coords = get_or_set_user_mars_home(user_id)
    expeditions_completed = get_user_completed_expeditions_count(user_id)
    logistics = commander_stats.get('logistics', 50)
    logistics_speed_bonus = 1.0 + (logistics / 100.0)

    # Bug #1310: tech research bonuses (e.g. 10.39× speed) were missing from preview's
    # per-vehicle speed display, even though launch (lifecycle.py:158) applies them.
    # Pull tech-only multiplier here so each vehicle row shows the real launch speed.
    from utilities.tech_utils import get_tech_effects
    tech_effects = get_tech_effects(user_id)
    tech_speed_mult = tech_effects.get('expedition_speed_mult', 1.0)
    tech_cargo_mult = tech_effects.get('cargo_capacity_mult', 1.0)

    # Terrain
    terrain_info = TERRAIN_MODIFIERS.get('default')
    for terrain_type, info in TERRAIN_MODIFIERS.items():
        if terrain_type.lower() in destination_type.lower():
            terrain_info = info
            break
    terrain_speed_mult = terrain_info.get('speed_mult', 1.0)
    terrain_name = terrain_info.get('reason', 'Standard terrain')

    # Trail multiplier: repeated trips to same destination build speed
    from utilities.postgres.trails import get_user_trail
    trail_data = get_user_trail(user_id, destination_name)
    trail_speed_mult = TRAIL_SPEED_MULTIPLIERS.get(trail_data['trail_level'], 1.0)

    # Range scales with fog radius (experienced players can reach further)
    discovered = get_user_discovered_landmarks(user_id)
    fog_radius = min(1000, 300 + len(discovered) * 50)
    range_mult = fog_radius / 300.0

    # Calculate estimates per vehicle (with segment compounding)
    vehicle_estimates = []
    for v in vehicles:
        vehicle_speed_mult = v['speed_mult']
        # Bug #1310: combine vehicle × tech for the actual travel-time calculation.
        # speed_mult kept raw for display; effective_speed_kmh below reflects the truth.
        speed_mult = vehicle_speed_mult * tech_speed_mult
        # Drones fly — terrain doesn't slow them
        v_terrain_mult = 1.0 if v['vehicle_type'] == 'drone' else terrain_speed_mult
        # Base speed without trail (trail is calculated per-segment)
        base_speed_for_segments = speed_mult * logistics_speed_bonus * scientist_nav_mult * v_terrain_mult

        # Use segmented travel time calculation
        segment_result = calculate_segmented_travel_time(
            user_id=user_id,
            destination_distance_km=distance_km,
            destination_name=destination_name,
            base_speed_mult=base_speed_for_segments,
            base_coords=base_coords
        )

        travel_hours = segment_result['total_hours']
        travel_days = travel_hours / EVA_HOURS_PER_DAY
        round_trip_hours = travel_hours * 2
        round_trip_days = travel_days * 2

        # Effective speed (for display)
        effective_speed = distance_km / travel_hours if travel_hours > 0 else BASE_SPEED_KM_PER_HOUR * base_speed_for_segments
        # Total speed mult (for backwards compatibility)
        total_speed = effective_speed / BASE_SPEED_KM_PER_HOUR

        # Range check: scaled by fog radius (more discoveries = further reach)
        max_range = int(v.get('max_range_km', 9999) * range_mult)
        out_of_range = distance_km > max_range
        available = v['available'] and not out_of_range
        unavailable_reason = f'Out of range ({max_range} km max)' if out_of_range else ('In use' if not v['available'] else '')

        # Engineering cargo bonus: +1 per 10 stat points (max +5 at ENG 50)
        # Bug #1310: also apply tech cargo_capacity_mult — matches lifecycle.py:225-226.
        eng_stat = scientist_stats.get('engineering', 0)
        effective_cargo = int(v['cargo'] * tech_cargo_mult) + eng_stat // 10

        vehicle_estimates.append({
            'vehicle_type': v['vehicle_type'],
            'level': v['level'],
            'name': v['name'],
            'cargo': effective_cargo,
            'available': available,
            'unavailable_reason': unavailable_reason,
            'max_range_km': max_range,
            'image_url': v.get('image_url', ''),
            'speed_mult': round(vehicle_speed_mult, 2),
            'total_speed_mult': round(total_speed, 2),
            'effective_speed_kmh': round(effective_speed, 2),
            'travel_hours': round(travel_hours, 1),
            'travel_days': round(travel_days, 1),
            'round_trip_hours': round(round_trip_hours, 1),
            'round_trip_days': round(round_trip_days, 1),
            'discovery_bonus': v.get('discovery_bonus', 0),
            'rare_bonus': v.get('rare_bonus', 0),
            # Terrain per vehicle (drones fly, ignore terrain)
            'terrain_speed_mult': round(v_terrain_mult, 2),
            'terrain_name': 'Aerial (no terrain impact)' if v['vehicle_type'] == 'drone' else terrain_name,
            # Segment compounding data
            'segments': segment_result.get('segments', []),
            'effective_trail_mult': segment_result.get('effective_trail_mult', trail_speed_mult),
        })

    # Speed breakdown (for the first available or first vehicle)
    primary_vehicle = next((v for v in vehicle_estimates if v['available']), vehicle_estimates[0] if vehicle_estimates else None)

    # Use effective trail mult from segment compounding if available
    effective_trail_mult = primary_vehicle.get('effective_trail_mult', trail_speed_mult) if primary_vehicle else trail_speed_mult
    segments = primary_vehicle.get('segments', []) if primary_vehicle else []
    has_segment_compounding = len(segments) > 1  # Multiple segments means compounding is in effect

    speed_breakdown = {
        'base_speed': BASE_SPEED_KM_PER_HOUR,
        'vehicle_mult': primary_vehicle['speed_mult'] if primary_vehicle else 1.0,
        'captain_logistics_mult': round(logistics_speed_bonus, 2),
        'scientist_nav_mult': scientist_nav_mult,
        'trail_speed_mult': round(effective_trail_mult, 2),
        'trail_level': trail_data['trail_level'],
        'trail_trip_count': trail_data['trip_count'],
        'terrain_speed_mult': 1.0 if (primary_vehicle and primary_vehicle.get('vehicle_type') == 'drone') else terrain_speed_mult,
        'terrain_name': 'Aerial (no terrain impact)' if (primary_vehicle and primary_vehicle.get('vehicle_type') == 'drone') else terrain_name,
        'total_mult': primary_vehicle['total_speed_mult'] if primary_vehicle else 1.0,
        'effective_speed_kmh': primary_vehicle['effective_speed_kmh'] if primary_vehicle else BASE_SPEED_KM_PER_HOUR,
        # Segment compounding info
        'segments': segments,
        'has_segment_compounding': has_segment_compounding,
    }

    # Storage capacity check (Storage Bunker upgrade) - counts ALL inventory, not just unclaimed
    from utilities.upgrades_utils import get_user_upgrade_effects
    from utilities.postgres.expeditions import get_total_discovery_count
    upgrade_effects = get_user_upgrade_effects(user_id)
    storage_capacity = upgrade_effects.get('storage_capacity', 300)
    current_total = get_total_discovery_count(user_id)
    storage_warning = None
    if current_total >= storage_capacity:
        storage_warning = f"Storage full ({current_total}/{storage_capacity}). Extract or shard discoveries before launching!"
    elif current_total >= storage_capacity * 0.8:
        storage_warning = f"Storage nearly full ({current_total}/{storage_capacity}). Consider extracting discoveries."

    return {
        'success': True,
        'destination': {
            'name': destination_name,
            'type': destination_type,
            'distance_km': distance_km,
        },
        'vehicles': vehicle_estimates,
        'speed_breakdown': speed_breakdown,
        'captain': {
            'name': captain_name,
            'image_url': captain_image,
            'logistics': commander_stats.get('logistics', 50),
            'logistics_mult': round(logistics_speed_bonus, 2),
            'exploration': commander_stats.get('exploration', 50),
            'strategy': commander_stats.get('strategy', 50),
            'leadership': commander_stats.get('leadership', 50),
            'charisma': commander_stats.get('charisma', 50),
        },
        'scientist': scientist_info,
        'fleet_status': fleet_status,
        'expeditions_completed': expeditions_completed,
        'max_slots': 3,
        'slots_used': len(fleet_status),
        'storage': {
            'capacity': storage_capacity,
            'used': current_total,
            'remaining': max(0, storage_capacity - current_total),
            'warning': storage_warning,
        },
    }


def estimate_expedition_return(fuel_cost_display: float, distance_km: float, destination_type: str, commander_stats: dict) -> dict:
    """Pre-launch estimate of shard return range (display units). Same formula as calculate_expedition_discovery minus luck."""
    fuel_cost_eth = fuel_cost_display / 10000000
    base_reward = fuel_cost_eth * 2
    exploration = commander_stats.get('exploration', 50)
    leadership = commander_stats.get('leadership', 50)
    charisma = commander_stats.get('charisma', 50)

    exploration_bonus = (exploration / 90.0) * 0.6
    leadership_bonus = (leadership / 90.0) * 0.2
    charisma_bonus = (charisma / 90.0) * 0.3
    distance_bonus = min(distance_km / 400.0, 4.0)

    location_multipliers = {
        'Crater': 1.3, 'Volcano': 1.1, 'Mons': 1.6, 'Planitia': 1.0,
        'Vallis': 1.2, 'Canyon': 0.9, 'Chasma': 1.4, 'Patera': 1.2,
    }
    location_mult = 1.0
    for loc_type, mult in location_multipliers.items():
        if loc_type.lower() in destination_type.lower():
            location_mult = mult
            break

    base_return = base_reward * (1 + exploration_bonus) * (1 + leadership_bonus) * (1 + charisma_bonus) * distance_bonus * location_mult
    # Luck varies ±40% — show conservative range
    return {
        'low': round(base_return * 0.6 * 10000000, 1),
        'high': round(base_return * 1.4 * 10000000, 1),
    }


def get_expedition_cost_preview_formatted(user_id, distance_km, destination_type):
    """Get expedition cost preview with UI formatting."""
    result = get_expedition_cost_preview(
        user_id=user_id,
        distance_km=distance_km,
        destination_type=destination_type
    )
    if not result['success']:
        return result

    # Estimated shard return range (for map popup)
    est = estimate_expedition_return(
        result['total_pricing']['total_cost_display'],
        float(distance_km),
        destination_type,
        result['commander_stats']
    )

    return {
        'success': True,
        'expedition_pricing': result['expedition_pricing'],
        'total_pricing': result['total_pricing'],
        'commander_stats': result['commander_stats'],
        'expeditions_completed': result['expeditions_completed'],
        'estimated_return': est,
        'note': 'Preview pricing - actual costs calculated at launch with live network conditions'
    }
