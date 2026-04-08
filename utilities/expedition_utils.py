"""
Expedition System - Mars Surface Exploration with GEOGRAPHIC FILTERING
All expedition business logic consolidated here - app.py routes are thin pass-throughs
FIXED: Discovery persistence after expedition completion
"""

import logging
import random
import math
from typing import Dict, Any, List, Tuple
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# ============================================================================
# PRICING CONSTANTS
# ============================================================================

BASE_FUEL_PER_KM = 1.0
LIFE_SUPPORT_PER_DAY = 50.0
BASE_SPEED_KM_PER_HOUR = 3.5  # Base rover/walking speed on Mars (was 2.0, bumped per Luke #1116)
EVA_HOURS_PER_DAY = 8.0

# Trail system: trip count thresholds → level, and level → speed multiplier
TRAIL_LEVEL_THRESHOLDS = [
    (1, 'marked'),       # 1 completed trip
    (3, 'cached'),       # 3 completed trips
    (7, 'established'),  # 7 completed trips
    (15, 'highway'),     # 15 completed trips
]

TRAIL_SPEED_MULTIPLIERS = {
    'none': 1.0,
    'marked': 1.25,
    'cached': 1.5,
    'established': 2.0,
    'highway': 3.0,
}

def get_trail_level_from_count(trip_count: int) -> str:
    """Convert trip count to trail level name"""
    level = 'none'
    for threshold, name in TRAIL_LEVEL_THRESHOLDS:
        if trip_count >= threshold:
            level = name
    return level


def calculate_trail_speed_mult_km(km_built: float, total_distance_km: float) -> float:
    """
    Calculate trail speed multiplier using the new km-based proportional system.

    Formula: trail_speed_mult = 1.0 + (km_built / total_distance_km) * 0.5
    - 0% built = 1.0x (no bonus)
    - 50% built = 1.25x
    - 100% built = 1.5x (max bonus)

    This replaces the old threshold-based system (none/marked/cached/established/highway)
    with continuous, proportional progress.
    """
    if not total_distance_km or total_distance_km <= 0:
        return 1.0

    ratio = min(1.0, (km_built or 0) / total_distance_km)
    return 1.0 + ratio * 0.5


def get_trail_speed_mult_for_destination(user_id: int, destination_name: str, distance_km: float = None) -> dict:
    """
    Get trail speed multiplier for a destination, using km-based system if available.

    Returns dict with:
    - speed_mult: The speed multiplier to use
    - km_built: How much trail has been built (if using new system)
    - total_distance_km: Total trail distance (if using new system)
    - percent_complete: Percentage of trail built
    - using_km_system: True if using new km-based system
    """
    from utilities.postgres_utils import get_user_trail

    trail_data = get_user_trail(user_id, destination_name)

    # Check if we have km-based data
    km_built = trail_data.get('km_built') or 0
    total_distance = trail_data.get('total_distance_km')

    # If no total_distance set but we have distance_km param, use that
    if not total_distance and distance_km:
        total_distance = distance_km

    if total_distance and total_distance > 0:
        # Use new km-based system
        speed_mult = calculate_trail_speed_mult_km(km_built, total_distance)
        percent = round((km_built / total_distance) * 100, 1)
        return {
            'speed_mult': round(speed_mult, 3),
            'km_built': km_built,
            'total_distance_km': total_distance,
            'percent_complete': percent,
            'using_km_system': True,
            'trail_level': trail_data.get('trail_level', 'none'),  # Legacy, for display
            'captain_km': trail_data.get('captain_km', 0),
            'scientist_km': trail_data.get('scientist_km', 0),
            'aria_km': trail_data.get('aria_km', 0)
        }
    else:
        # Fall back to old threshold system
        trail_level = trail_data.get('trail_level', 'none')
        speed_mult = TRAIL_SPEED_MULTIPLIERS.get(trail_level, 1.0)
        return {
            'speed_mult': speed_mult,
            'km_built': 0,
            'total_distance_km': distance_km or 0,
            'percent_complete': 0,
            'using_km_system': False,
            'trail_level': trail_level,
            'captain_km': 0,
            'scientist_km': 0,
            'aria_km': 0
        }


def calculate_segmented_travel_time(
    user_id: int,
    destination_distance_km: float,
    destination_name: str,
    base_speed_mult: float,
    base_coords: dict = None
) -> dict:
    """
    Calculate travel time using trail segment compounding.

    Long journeys benefit from intermediate trails:
    - If there's a highway trail at 50km and destination is 500km,
      the first 50km uses highway speed (3x), remaining 450km uses destination trail.

    Returns dict with:
    - total_hours: Total travel time
    - segments: List of {distance, trail_level, speed_mult, hours}
    - effective_trail_mult: Weighted average trail multiplier for display
    """
    from utilities.postgres_utils import get_user_trails, get_user_trail, db_cursor

    # Get all user trails with distances
    try:
        with db_cursor() as cur:
            # Get base coords if not provided
            if not base_coords:
                cur.execute("""
                    SELECT home_mars_lat, home_mars_lon FROM pilgrim.users WHERE id = %s
                """, (user_id,))
                user = cur.fetchone()
                if user and user['home_mars_lat']:
                    base_coords = {'latitude': float(user['home_mars_lat']), 'longitude': float(user['home_mars_lon'])}

            if not base_coords:
                # Can't calculate segments without base coords, use simple method
                trail_info = get_trail_speed_mult_for_destination(user_id, destination_name, destination_distance_km)
                trail_mult = trail_info['speed_mult']
                hours = destination_distance_km / (BASE_SPEED_KM_PER_HOUR * base_speed_mult * trail_mult)
                return {
                    'total_hours': hours,
                    'segments': [{'distance': destination_distance_km, 'trail_level': trail_info.get('trail_level', 'none'), 'speed_mult': trail_mult, 'hours': hours}],
                    'effective_trail_mult': trail_mult,
                    'trail_info': trail_info  # Include km-based progress info
                }

            # Get all trails with their landmark distances
            cur.execute("""
                SELECT t.destination_name, t.trip_count, t.trail_level,
                       m.latitude, m.longitude,
                       (6371 * SQRT(POW(RADIANS(m.latitude - %s), 2) +
                        POW(RADIANS(m.longitude - %s) * COS(RADIANS(m.latitude)), 2))) as distance_km
                FROM pilgrim.trail_segments t
                JOIN pilgrim.mars_mappings m ON m.name = t.destination_name
                WHERE t.user_id = %s AND t.trip_count > 0
                ORDER BY distance_km ASC
            """, (base_coords['latitude'], base_coords['longitude'], user_id))
            trails_with_distance = cur.fetchall() or []

    except Exception as e:
        logger.error(f"Error calculating segmented travel: {e}")
        # Fallback to simple calculation using km-based system
        trail_info = get_trail_speed_mult_for_destination(user_id, destination_name, destination_distance_km)
        trail_mult = trail_info['speed_mult']
        hours = destination_distance_km / (BASE_SPEED_KM_PER_HOUR * base_speed_mult * trail_mult)
        return {
            'total_hours': hours,
            'segments': [{'distance': destination_distance_km, 'trail_level': trail_info.get('trail_level', 'none'), 'speed_mult': trail_mult, 'hours': hours}],
            'effective_trail_mult': trail_mult,
            'trail_info': trail_info
        }

    # Filter to trails that are CLOSER than destination (on the way)
    intermediate_trails = [t for t in trails_with_distance if float(t['distance_km']) < destination_distance_km]

    # Get destination trail using km-based system
    dest_trail_info = get_trail_speed_mult_for_destination(user_id, destination_name, destination_distance_km)
    dest_trail_mult = dest_trail_info['speed_mult']

    if not intermediate_trails:
        # No intermediate trails, use destination trail for whole journey
        hours = destination_distance_km / (BASE_SPEED_KM_PER_HOUR * base_speed_mult * dest_trail_mult)
        return {
            'total_hours': hours,
            'segments': [{'distance': destination_distance_km, 'trail_level': dest_trail_info.get('trail_level', 'none'), 'speed_mult': dest_trail_mult, 'hours': hours}],
            'effective_trail_mult': dest_trail_mult,
            'trail_info': dest_trail_info
        }

    # Build segments from intermediate trails
    # Strategy: use the BEST trail available for each distance segment
    segments = []
    current_distance = 0
    total_hours = 0

    # Sort by distance and find best trail at each point
    for trail in intermediate_trails:
        trail_dist = float(trail['distance_km'])
        trail_mult = TRAIL_SPEED_MULTIPLIERS.get(trail['trail_level'], 1.0)

        # Segment from current position to this trail's distance
        segment_distance = trail_dist - current_distance
        if segment_distance > 0:
            # Use the best trail we've seen so far for this segment
            best_mult = max(trail_mult, segments[-1]['speed_mult'] if segments else 1.0)
            segment_hours = segment_distance / (BASE_SPEED_KM_PER_HOUR * base_speed_mult * best_mult)
            segments.append({
                'distance': segment_distance,
                'trail_level': trail['trail_level'],
                'speed_mult': best_mult,
                'hours': segment_hours,
                'landmark': trail['destination_name']
            })
            total_hours += segment_hours
            current_distance = trail_dist

    # Final segment from last trail to destination
    final_distance = destination_distance_km - current_distance
    if final_distance > 0:
        final_hours = final_distance / (BASE_SPEED_KM_PER_HOUR * base_speed_mult * dest_trail_mult)
        segments.append({
            'distance': final_distance,
            'trail_level': dest_trail_info.get('trail_level', 'none'),
            'speed_mult': dest_trail_mult,
            'hours': final_hours,
            'landmark': destination_name
        })
        total_hours += final_hours

    # Calculate effective (weighted average) trail multiplier for display
    if total_hours > 0:
        weighted_mult = sum(s['speed_mult'] * s['hours'] for s in segments) / total_hours
    else:
        weighted_mult = dest_trail_mult

    return {
        'total_hours': total_hours,
        'segments': segments,
        'effective_trail_mult': round(weighted_mult, 2)
    }

# Backwards compat alias
WALKING_SPEED_KM_PER_HOUR = BASE_SPEED_KM_PER_HOUR


# ============================================================================
# TRAVEL SPEED CALCULATION (DRY - single source of truth)
# ============================================================================

def calculate_speed_multiplier(vehicle_speed_mult: float = 1.0, logistics: int = 50) -> float:
    """
    Calculate total speed multiplier for expedition travel.

    Formula per PILGRIMS.md:
        Travel time = Distance ÷ (base_speed × logistics_modifier × vehicle_speed)

    Args:
        vehicle_speed_mult: From vehicle upgrade (rover 1.25-3.0x, drone 1.5-1.6x, buggy 1.75-2.0x)
        logistics: Commander's logistics stat (0-100)

    Returns:
        Total speed multiplier to apply to BASE_SPEED_KM_PER_HOUR

    Design:
        - Vehicle is PRIMARY speed factor (1.25x to 3.0x based on upgrade level)
        - Logistics provides SECONDARY bonus (1.0x to 1.5x based on 0-100 stat)
        - Total range: ~1.25x (worst) to ~4.5x (best rover + max logistics)
    """
    # Logistics bonus: 0 logistics = 1.0x, 50 = 1.5x, 100 = 2.0x
    logistics_bonus = 1.0 + (logistics / 100.0)

    return vehicle_speed_mult * logistics_bonus


def calculate_travel_time(distance_km: float, speed_multiplier: float) -> dict:
    """
    Calculate travel time for an expedition given distance and speed.

    Args:
        distance_km: Distance to destination
        speed_multiplier: From calculate_speed_multiplier()

    Returns:
        dict with travel_hours, travel_days, effective_speed_kmh
    """
    effective_speed = BASE_SPEED_KM_PER_HOUR * speed_multiplier
    travel_hours = distance_km / effective_speed
    travel_days = travel_hours / EVA_HOURS_PER_DAY

    return {
        'travel_hours': round(travel_hours, 1),
        'travel_days': round(travel_days, 1),
        'effective_speed_kmh': round(effective_speed, 1),
        'speed_multiplier': round(speed_multiplier, 2)
    }


def estimate_travel_days(distance_km: float, vehicle_speed_mult: float = 1.25, logistics: int = 50) -> float:
    """
    Quick estimate of travel days for a destination.
    Used for rough display before full pricing is calculated.
    """
    speed_mult = calculate_speed_multiplier(vehicle_speed_mult, logistics)
    travel = calculate_travel_time(distance_km, speed_mult)
    return travel['travel_days']

# Terrain affects BOTH speed and cost - Mars is brutal!
# speed_mult: <1.0 = slower, >1.0 = faster
# cost_mult: <1.0 = cheaper, >1.0 = more expensive
TERRAIN_MODIFIERS = {
    'Planitia': {
        'speed_mult': 1.2, 'cost_mult': 0.7,
        'reason': 'Flat plains - optimal conditions for wheeled vehicles'
    },
    'Vallis': {
        'speed_mult': 0.7, 'cost_mult': 1.3,
        'reason': 'Valley floor - scattered debris and rockslides'
    },
    'Crater': {
        'speed_mult': 0.6, 'cost_mult': 1.5,
        'reason': 'Crater rim - unstable edges, steep grades'
    },
    'Fossae': {
        'speed_mult': 0.6, 'cost_mult': 1.4,
        'reason': 'Trough system - multiple difficult crossings'
    },
    'Patera': {
        'speed_mult': 0.5, 'cost_mult': 1.6,
        'reason': 'Volcanic caldera - sharp basalt, uneven lava flows'
    },
    'Chasma': {
        'speed_mult': 0.4, 'cost_mult': 2.0,
        'reason': 'Deep canyon - extreme descent/ascent, limited routes'
    },
    'Mons': {
        'speed_mult': 0.3, 'cost_mult': 2.5,
        'reason': 'Mountain - extreme elevation gain, motor strain'
    },
    'Rupes': {
        'speed_mult': 0.2, 'cost_mult': 3.0,
        'reason': 'Cliff escarpment - requires extensive rerouting'
    },
    'default': {
        'speed_mult': 1.0, 'cost_mult': 1.0,
        'reason': 'Standard Martian terrain'
    }
}

# ============================================================================
# GEOGRAPHIC FILTERING CONSTANTS
# ============================================================================

from utilities.mars_math import haversine_distance, point_to_path_distance, MARS_RADIUS_KM  # noqa: E402

MISSION_ARTIFACT_MAX_DISTANCE_KM = 100
GENERIC_SAMPLE_MAX_DISTANCE_KM = 9999

def is_item_geographically_valid(item: dict, start_lat: float, start_lon: float,
                                end_lat: float, end_lon: float) -> bool:
    """Check if discovery item can spawn on this expedition path"""
    mission_source = item.get('mission_source')
    
    if not mission_source:
        return True
    
    mission_lat = item.get('mission_lat')
    mission_lon = item.get('mission_lon')
    
    if mission_lat is None or mission_lon is None:
        logger.warning(f"Mission artifact {item['item_name']} missing landing coords")
        return False
    
    distance_to_path = point_to_path_distance(
        mission_lat, mission_lon,
        start_lat, start_lon,
        end_lat, end_lon
    )
    
    is_valid = distance_to_path <= MISSION_ARTIFACT_MAX_DISTANCE_KM
    
    if not is_valid:
        logger.debug(f"Filtered {item['item_name']} ({mission_source}): {distance_to_path:.1f}km from path")
    
    return is_valid

# ============================================================================
# EXPEDITION COST CALCULATION (Vehicle-based, no life support)
# ============================================================================

# Cost rate per km (tuned for ~300-500 shards for medium expeditions)
BASE_COST_PER_KM = 2.5

def calculate_expedition_cost(
    distance_km: float,
    destination_type: str,
    commander_stats: dict,
    user_expeditions_completed: int = 0,
    base_coords: dict = None,
    upgrade_effects: dict = None,
    is_return_visit: bool = False,
    scientist_nav_mult: float = 1.0,
    trail_speed_mult: float = 1.0,
    vehicle_type: str = None
) -> dict:
    """
    Calculate expedition cost and travel time.

    New streamlined formula (vehicles, no life support):
    - Base cost from distance
    - Terrain affects both speed AND cost (Mars is brutal!)
    - Vehicle efficiency reduces cost
    - Logistics skill reduces cost
    - Experience reduces cost
    - Return visits get -30% cost, -50% travel time (mapped route)
    """
    if upgrade_effects is None:
        upgrade_effects = {}

    # Get vehicle stats
    vehicle_speed_mult = upgrade_effects.get('expedition_speed_mult', 1.25)
    vehicle_cost_mult = upgrade_effects.get('fuel_cost_mult', 1.0)

    # Get terrain modifiers (now has both speed_mult and cost_mult)
    terrain_info = TERRAIN_MODIFIERS.get('default')
    for terrain_type, info in TERRAIN_MODIFIERS.items():
        if terrain_type.lower() in destination_type.lower():
            terrain_info = info
            break

    terrain_speed_mult = terrain_info.get('speed_mult', 1.0)
    terrain_cost_mult = terrain_info.get('cost_mult', 1.0)
    terrain_reason = terrain_info['reason']

    # Drones fly — terrain doesn't slow them (but still affects cost for landing/takeoff)
    if vehicle_type == 'drone':
        terrain_speed_mult = 1.0
        terrain_reason = 'Aerial (no terrain impact)'

    # Distance tier (for narrative)
    if distance_km < 50:
        distance_tier = "Short Range"
        distance_desc = "Local reconnaissance"
    elif distance_km < 200:
        distance_tier = "Medium Range"
        distance_desc = "Extended surface mission"
    elif distance_km < 500:
        distance_tier = "Long Range"
        distance_desc = "Major expedition"
    else:
        distance_tier = "Epic Expedition"
        distance_desc = "Unprecedented journey"

    # Commander stats
    logistics = commander_stats.get('logistics', 50)
    strategy = commander_stats.get('strategy', 50)

    # === TRAVEL TIME CALCULATION ===
    # Speed stack: vehicle × captain_logistics × scientist × trail × terrain
    logistics_speed_bonus = 1.0 + (logistics / 100.0)  # 1.0 to 2.0x
    total_speed_mult = vehicle_speed_mult * logistics_speed_bonus * scientist_nav_mult * trail_speed_mult * terrain_speed_mult

    effective_speed = BASE_SPEED_KM_PER_HOUR * total_speed_mult
    travel_hours = distance_km / effective_speed
    travel_days = travel_hours / EVA_HOURS_PER_DAY

    # Return visit: 50% faster (mapped route)
    if is_return_visit:
        travel_days = travel_days * 0.5
        travel_hours = travel_hours * 0.5

    # === COST CALCULATION ===
    # Base cost from distance
    base_cost = distance_km * BASE_COST_PER_KM

    # Terrain multiplier (0.7x to 3.0x)
    after_terrain = base_cost * terrain_cost_mult
    terrain_cost_added = after_terrain - base_cost

    # Vehicle efficiency (0.75x to 1.1x)
    after_vehicle = after_terrain * vehicle_cost_mult
    vehicle_savings = after_terrain - after_vehicle

    # Logistics efficiency: 0-100 skill → 0-30% reduction
    logistics_efficiency = 1.0 - (logistics / 333.0)
    logistics_efficiency = max(0.7, logistics_efficiency)  # Cap at 30% reduction
    after_logistics = after_vehicle * logistics_efficiency
    logistics_savings = after_vehicle - after_logistics
    logistics_savings_pct = (1.0 - logistics_efficiency) * 100

    # Strategy reduces terrain penalty (0-25% of terrain cost back)
    strategy_efficiency = min(0.25, strategy / 400.0)
    strategy_refund = terrain_cost_added * strategy_efficiency
    after_strategy = after_logistics - strategy_refund
    strategy_savings_pct = strategy_efficiency * 100

    # Charisma efficiency: 0-100 skill → 0-20% cost reduction
    charisma = commander_stats.get('charisma', 50)
    charisma_efficiency = 1.0 - (charisma / 500.0)
    charisma_efficiency = max(0.8, charisma_efficiency)  # Cap at 20% reduction
    after_charisma = after_strategy * charisma_efficiency
    charisma_savings = after_strategy - after_charisma
    charisma_savings_pct = (1.0 - charisma_efficiency) * 100

    # Experience discount: 2% per 1 expedition, max 50% at 25 expeditions
    experience_discount = min(0.5, user_expeditions_completed * 0.02)
    experience_mult = 1.0 - experience_discount
    after_experience = after_charisma * experience_mult
    experience_savings = after_charisma - after_experience
    experience_discount_pct = experience_discount * 100

    # Life support efficiency from upgrades (life_support upgrade path)
    # Default 1.0 means no savings, lower = cheaper (e.g., 0.5 = 50% off)
    life_support_mult = upgrade_effects.get('life_support_cost_mult', 1.0)
    after_life_support = after_experience * life_support_mult
    life_support_savings = after_experience - after_life_support
    life_support_discount_pct = (1.0 - life_support_mult) * 100

    # Return visit: 30% cheaper (known hazards)
    if is_return_visit:
        final_cost = after_life_support * 0.7
        return_savings = after_life_support * 0.3
    else:
        final_cost = after_life_support
        return_savings = 0

    # Generate narrative
    narrative = generate_expedition_narrative(
        distance_km=distance_km,
        travel_days=travel_days,
        distance_tier=distance_tier,
        distance_desc=distance_desc,
        terrain_reason=terrain_reason,
        commander_stats=commander_stats,
        user_expeditions_completed=user_expeditions_completed,
        logistics_savings_pct=logistics_savings_pct,
        strategy_savings_pct=strategy_savings_pct,
        total_speed_mult=total_speed_mult,
        is_return_visit=is_return_visit
    )

    return {
        # Cost breakdown
        'base_cost': round(base_cost, 1),
        'terrain_cost': round(terrain_cost_added, 1),
        'terrain_multiplier': terrain_cost_mult,
        'terrain_speed_mult': terrain_speed_mult,
        'terrain_reason': terrain_reason,
        'vehicle_savings': round(vehicle_savings, 1),
        'vehicle_cost_mult': vehicle_cost_mult,
        'logistics_savings': round(logistics_savings, 1),
        'logistics_efficiency_pct': round(logistics_savings_pct, 1),
        'strategy_savings': round(strategy_refund, 1),
        'strategy_savings_pct': round(strategy_savings_pct, 1),
        'charisma_savings': round(charisma_savings, 1),
        'charisma_savings_pct': round(charisma_savings_pct, 1),
        'experience_savings': round(experience_savings, 1),
        'experience_discount_pct': round(experience_discount_pct, 1),
        'life_support_savings': round(life_support_savings, 1),
        'life_support_discount_pct': round(life_support_discount_pct, 1),
        'life_support_mult': life_support_mult,
        'return_savings': round(return_savings, 1),
        'is_return_visit': is_return_visit,
        'base_expedition_cost': round(final_cost, 1),

        # Travel info (one-way for reference, round-trip for display)
        'travel_days': round(travel_days, 1),
        'travel_hours': round(travel_hours, 1),
        'round_trip_days': round(travel_days * 2, 1),
        'round_trip_hours': round(travel_hours * 2, 1),
        'effective_speed_kmh': round(effective_speed, 1),
        'logistics_speed_multiplier': round(total_speed_mult, 2),
        'vehicle_speed_mult': vehicle_speed_mult,

        # Distance tier
        'distance_tier': distance_tier,
        'distance_desc': distance_desc,

        # Commander stats used
        'logistics_skill': logistics,
        'strategy_skill': strategy,
        'expeditions_completed': user_expeditions_completed,

        # Narrative
        'narrative': narrative,

        # For backwards compat (old keys some code may use)
        'base_fuel_cost': round(base_cost, 1),
        'rover_speed_bonus': vehicle_speed_mult,
    }


def generate_expedition_narrative(
    distance_km: float,
    travel_days: float,
    distance_tier: str,
    distance_desc: str,
    terrain_reason: str,
    commander_stats: dict,
    user_expeditions_completed: int,
    logistics_savings_pct: float,
    strategy_savings_pct: float,
    total_speed_mult: float,
    is_return_visit: bool = False
) -> str:
    """Generate narrative explanation of expedition"""

    parts = []

    # Time description
    if travel_days < 1:
        time_desc = f"{travel_days * EVA_HOURS_PER_DAY:.1f} hours"
    else:
        time_desc = f"{travel_days:.1f} days"

    # Return visit prefix
    if is_return_visit:
        parts.append(f"Return expedition to mapped territory.")

    parts.append(f"{distance_tier}: {distance_desc} spanning {distance_km:.0f} km.")
    parts.append(f"Estimated travel: {time_desc} round-trip at {total_speed_mult:.1f}× speed.")
    parts.append(terrain_reason + ".")

    # Commander effects
    effects = []
    if logistics_savings_pct > 5:
        effects.append(f"Logistics ({commander_stats['logistics']}): -{logistics_savings_pct:.0f}% cost")
    if strategy_savings_pct > 5:
        effects.append(f"Strategy ({commander_stats['strategy']}): terrain penalty reduced")
    if user_expeditions_completed >= 5:
        effects.append(f"Experience: -{min(50, user_expeditions_completed * 2)}% veteran discount")
    if is_return_visit:
        effects.append("Return visit: -30% cost, -50% travel time")

    if effects:
        parts.append("Bonuses: " + ", ".join(effects) + ".")
    
    if user_expeditions_completed >= 15:
        parts.append(f"Veteran expedition protocols active ({user_expeditions_completed} missions completed).")
    elif user_expeditions_completed >= 5:
        parts.append(f"Experience from {user_expeditions_completed} prior missions improves planning efficiency.")
    
    return " ".join(parts)

def sort_landmarks_by_cost(landmarks: List[Dict], commander_stats: dict,
                           user_expeditions_completed: int, base_coords: dict,
                           user_id: int = None) -> List[Dict]:
    """Calculate cost for each landmark and sort cheapest-first"""
    safe_stats = {
        'leadership': commander_stats.get('leadership') or 50,
        'strategy': commander_stats.get('strategy') or 50,
        'exploration': commander_stats.get('exploration') or 50,
        'logistics': commander_stats.get('logistics') or 50,
        'charisma': commander_stats.get('charisma') or 50
    }

    # Get upgrade effects if user_id provided
    upgrade_effects = None
    if user_id:
        try:
            from utilities.upgrades_utils import get_user_upgrade_effects
            upgrade_effects = get_user_upgrade_effects(user_id)
        except ImportError:
            pass

    enriched_landmarks = []

    for landmark in landmarks:
        # Check if this is a return visit (visited before)
        is_return = landmark.get('visit_count', 0) > 0

        pricing = calculate_expedition_cost(
            distance_km=landmark['distance_km'],
            destination_type=landmark['type'],
            commander_stats=safe_stats,
            user_expeditions_completed=user_expeditions_completed,
            base_coords=base_coords,
            upgrade_effects=upgrade_effects,
            is_return_visit=is_return
        )

        landmark['calculated_cost'] = pricing['base_expedition_cost']
        landmark['travel_hours_actual'] = pricing['travel_hours']
        landmark['travel_days'] = pricing['travel_days']
        landmark['speed_multiplier'] = pricing['logistics_speed_multiplier']
        landmark['is_return_visit'] = is_return
        landmark['expedition_pricing'] = pricing  # Full pricing for UI

        enriched_landmarks.append(landmark)

    enriched_landmarks.sort(key=lambda x: x['calculated_cost'])

    return enriched_landmarks

# ============================================================================
# NEW: EXPEDITION COST PREVIEW (from app.py)
# ============================================================================

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
    from utilities.postgres_utils import (
        get_user_primary_sepolia_wallet,
        get_or_set_user_mars_home,
        get_user_completed_expeditions_count
    )
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
    from utilities.postgres_utils import (
        get_or_set_user_mars_home,
        get_user_active_expeditions,
        get_user_completed_expeditions_count,
        get_user_scientist,
        get_user_discovered_landmarks
    )
    from utilities.upgrades_utils import get_vehicle_for_expedition, get_user_owned_vehicles
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

    # Terrain
    terrain_info = TERRAIN_MODIFIERS.get('default')
    for terrain_type, info in TERRAIN_MODIFIERS.items():
        if terrain_type.lower() in destination_type.lower():
            terrain_info = info
            break
    terrain_speed_mult = terrain_info.get('speed_mult', 1.0)
    terrain_name = terrain_info.get('reason', 'Standard terrain')

    # Trail multiplier: repeated trips to same destination build speed
    from utilities.postgres_utils import get_user_trail
    trail_data = get_user_trail(user_id, destination_name)
    trail_speed_mult = TRAIL_SPEED_MULTIPLIERS.get(trail_data['trail_level'], 1.0)

    # Range scales with fog radius (experienced players can reach further)
    discovered = get_user_discovered_landmarks(user_id)
    fog_radius = min(1000, 300 + len(discovered) * 50)
    range_mult = fog_radius / 300.0

    # Calculate estimates per vehicle (with segment compounding)
    vehicle_estimates = []
    for v in vehicles:
        speed_mult = v['speed_mult']
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
        eng_stat = scientist_stats.get('engineering', 0)
        effective_cargo = v['cargo'] + eng_stat // 10

        vehicle_estimates.append({
            'vehicle_type': v['vehicle_type'],
            'level': v['level'],
            'name': v['name'],
            'cargo': effective_cargo,
            'available': available,
            'unavailable_reason': unavailable_reason,
            'max_range_km': max_range,
            'image_url': v.get('image_url', ''),
            'speed_mult': round(speed_mult, 2),
            'total_speed_mult': round(total_speed, 2),
            'effective_speed_kmh': round(effective_speed, 2),
            'travel_hours': round(travel_hours, 1),
            'travel_days': round(travel_days, 1),
            'round_trip_hours': round(round_trip_hours, 1),
            'round_trip_days': round(round_trip_days, 1),
            'discovery_bonus': v.get('discovery_bonus', 0),
            'rare_bonus': v.get('rare_bonus', 0),
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
    from utilities.db_expeditions import get_total_discovery_count
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

# ============================================================================
# NEW: EXPEDITION LAUNCH (from app.py)
# ============================================================================

def launch_expedition(
    user_id: int,
    destination_name: str,
    destination_type: str,
    destination_lat: float,
    destination_lon: float,
    distance_km: float,
    vehicle_type: str = 'rover'
) -> dict:
    """
    Launch expedition - handles all business logic:
    - Cost calculation with first mission cap
    - Blockchain transaction
    - DB updates
    - Discovery generation
    """
    from utilities.postgres_utils import (
        get_user_primary_sepolia_wallet,
        get_or_set_user_mars_home,
        get_user_replicate_assets,
        get_user_completed_expeditions_count,
        update_sepolia_wallet_balance,
        create_depot_transaction,
        create_expedition,
        get_nearest_mars_landmarks,
        get_discovery_items_catalog,
        create_expedition_discoveries,
        get_user_active_expeditions,
        get_user_scientist,
        get_user_discovered_landmarks
    )
    from utilities.sepolia_utils import MarsAsteroidMiner
    from utilities.depot_utils import generate_commander_stats

    if not all([destination_name, distance_km]):
        return {'success': False, 'error': 'Missing destination data'}

    # Validate vehicle type
    if vehicle_type not in ('rover', 'drone', 'buggy'):
        vehicle_type = 'rover'

    # Check vehicle is owned and get vehicle-specific stats
    from utilities.upgrades_utils import get_vehicle_for_expedition
    vehicle_data = get_vehicle_for_expedition(user_id, vehicle_type)
    if not vehicle_data:
        return {'success': False, 'error': f'{vehicle_type.capitalize()} not unlocked'}

    # Range scales with fog radius (more discoveries = further reach)
    discovered = get_user_discovered_landmarks(user_id)
    fog_radius = min(1000, 300 + len(discovered) * 50)
    range_mult = fog_radius / 300.0
    max_range = int(vehicle_data.get('max_range_km', 9999) * range_mult)
    if distance_km > max_range:
        return {'success': False, 'error': f'{vehicle_type.capitalize()} max range is {max_range} km. Destination is {distance_km:.0f} km away.'}

    # Speed stack for cost calculation
    from utilities.depot_utils import get_commander_and_stats
    commander_check, cmd_stats = get_commander_and_stats(user_id)
    if not cmd_stats:
        cmd_stats = {'exploration': 50, 'leadership': 50, 'strategy': 50, 'logistics': 50, 'charisma': 50}
    logistics_bonus = 1.0 + (cmd_stats.get('logistics', 50) / 100.0)
    scientist = get_user_scientist(user_id)
    sci_stats = scientist.get('stats', {}) if scientist else {}
    sci_nav_mult = 1.0 + (sci_stats.get('navigation', 0) / 150.0)
    # Drones fly — terrain doesn't slow them
    terrain_mult = 1.0
    if vehicle_type != 'drone':
        for terrain_type, info in TERRAIN_MODIFIERS.items():
            if terrain_type.lower() in destination_type.lower():
                terrain_mult = info.get('speed_mult', 1.0)
                break
    # Trail speed bonus for this route
    from utilities.postgres_utils import get_user_trail
    trail_data = get_user_trail(user_id, destination_name)
    launch_trail_mult = TRAIL_SPEED_MULTIPLIERS.get(trail_data['trail_level'], 1.0)

    # Check expedition capacity - 1 per vehicle type, capped by habitat module
    active_expeditions = get_user_active_expeditions(user_id)

    # Get expedition cap from habitat module (default 3 if no habitat built)
    from utilities.infrastructure_utils import get_user_infrastructure_effects
    infra_effects = get_user_infrastructure_effects(user_id)
    expedition_cap = infra_effects.get('expedition_capacity', 3)

    # Per-type constraint: only 1 of each vehicle type active at a time
    active_of_type = [e for e in active_expeditions if e.get('vehicle_type') == vehicle_type and e['status'] in ('traveling', 'recalled')]
    if active_of_type:
        dest = active_of_type[0]['destination_name']
        return {'success': False, 'error': f'Your {vehicle_type} is already on expedition to {dest}. Recall it first or wait for return.'}

    # Total cap: limited by habitat module capacity
    traveling = [e for e in active_expeditions if e['status'] in ('traveling', 'recalled')]
    if len(traveling) >= expedition_cap:
        return {'success': False, 'error': f'All {expedition_cap} expedition slots in use. Upgrade your Habitat Module for more slots.'}

    # Check for unclaimed discoveries blocking slots
    completed_with_unclaimed = [e for e in active_expeditions if e['status'] == 'complete' and e.get('unclaimed_count', 0) > 0]
    if completed_with_unclaimed and len(traveling) + len(completed_with_unclaimed) >= expedition_cap:
        destinations = ', '.join([e['destination_name'] for e in completed_with_unclaimed])
        return {'success': False, 'error': f'Claim your discoveries from {destinations} before starting a new expedition'}

    wallet = get_user_primary_sepolia_wallet(user_id)
    if not wallet:
        return {'success': False, 'error': 'No wallet found'}

    base_coords = get_or_set_user_mars_home(user_id)

    # Single query for both character_image and edited_image
    from utilities.postgres_utils import get_user_commander_images
    all_images = get_user_commander_images(user_id, limit=1)['all_images']

    if not all_images:
        return {'success': False, 'error': 'No commander found'}

    commander = all_images[0]

    # Use REAL commander stats (not random!) + EVA Suit bonuses
    from utilities.postgres_utils import get_commander_stats
    from utilities.shop_utils import get_effective_commander_stats
    base_commander_stats = get_commander_stats(user_id)
    if not base_commander_stats:
        base_commander_stats = generate_commander_stats()
    # Apply EVA Suit stat bonuses
    commander_stats = get_effective_commander_stats(user_id, base_commander_stats)

    expeditions_completed = get_user_completed_expeditions_count(user_id)
    user_expedition_count = expeditions_completed + 1

    # Get user's upgrade effects for cost calculation
    from utilities.upgrades_utils import get_user_upgrade_effects
    upgrade_effects = get_user_upgrade_effects(user_id)

    # Override speed with vehicle-specific speed (not max across all vehicles)
    upgrade_effects['expedition_speed_mult'] = vehicle_data['speed_mult']

    expedition_pricing = calculate_expedition_cost(
        distance_km=distance_km,
        destination_type=destination_type,
        commander_stats=commander_stats,
        user_expeditions_completed=expeditions_completed,
        base_coords=base_coords,
        upgrade_effects=upgrade_effects,
        scientist_nav_mult=sci_nav_mult,
        trail_speed_mult=launch_trail_mult
    )

    base_expedition_cost_eth = expedition_pricing['base_expedition_cost'] / 10000000

    # Bug #1290: preview uses calculate_cached_transaction_cost (DEFAULT_FEE_MULTIPLIER=1.0,
    # no blockchain call), but launch previously used miner.calculate_total_transaction_cost
    # (live Sepolia gas lookup). When Sepolia gas ticked up between preview and launch,
    # the fee_multiplier rose above 1.0 and total cost jumped ~47 shards — enough to push
    # players who could barely afford the preview cost into "Insufficient funds".
    # Fix: use the same cached pricing at launch so preview == launch cost, always.
    from utilities.depot_utils import calculate_cached_transaction_cost
    current_balance_eth = float(wallet.get('current_balance_eth', 0) or 0)
    total_pricing = calculate_cached_transaction_cost(
        base_expedition_cost_eth,
        user_balance_eth=current_balance_eth,
        message_length=250
    )
    total_pricing['success'] = True  # cached version always succeeds

    is_first_mission = expeditions_completed == 0
    user_balance_eth = total_pricing['current_balance_eth']

    if is_first_mission and user_balance_eth > 0:
        max_first_mission_cost_eth = user_balance_eth * 0.5

        if total_pricing['total_cost_eth'] > max_first_mission_cost_eth:
            remaining_for_base = max_first_mission_cost_eth - total_pricing['gas_cost_eth']

            if remaining_for_base > 0:
                max_base_cost_eth = remaining_for_base / (1 + (total_pricing['conditions']['fee_multiplier'] - 1.0))
                total_pricing = calculate_cached_transaction_cost(
                    max_base_cost_eth,
                    user_balance_eth=current_balance_eth,
                    message_length=250
                )
                total_pricing['success'] = True
                base_expedition_cost_eth = max_base_cost_eth
                logger.info(f"🎁 First mission cap applied: {total_pricing['total_cost_display']} (was {expedition_pricing['base_expedition_cost']})")
            else:
                logger.warning(f"⚠️ User balance too low for first mission cap ({user_balance_eth} ETH)")

    if not total_pricing['can_afford']:
        return {
            'success': False,
            'error': 'Insufficient Sepolia for expedition',
            'expedition_pricing': expedition_pricing,
            'total_pricing': total_pricing
        }
    
    travel_time_seconds = int(expedition_pricing['travel_hours'] * 3600)

    # --- Optimistic: create expedition + discoveries immediately ---
    try:
        # Use vehicle-specific cargo capacity + scientist engineering bonus
        cargo_capacity = vehicle_data.get('cargo', 5)
        engineering_stat = sci_stats.get('engineering', 0)
        cargo_capacity += engineering_stat // 10  # +1 per 10 engineering (max +5 at 50)

        # Optimistically deduct balance
        new_balance = total_pricing['current_balance_eth'] - total_pricing['total_cost_eth']
        update_sepolia_wallet_balance(wallet['wallet_address'], new_balance)

        expedition_id = create_expedition(
            user_id=user_id,
            commander_asset_id=commander['id'],
            destination_name=destination_name,
            destination_type=destination_type,
            destination_lat=destination_lat,
            destination_lon=destination_lon,
            distance_km=distance_km,
            fuel_cost_eth=total_pricing['total_cost_eth'],
            travel_time_seconds=travel_time_seconds,
            commander_stats=commander_stats,
            vehicle_type=vehicle_type,
            cargo_capacity=cargo_capacity
        )

        try:
            from utilities.discovery_utils import generate_expedition_discoveries
            from utilities.db_expeditions import get_total_discovery_count

            # Storage capacity check - counts ALL inventory (claimed + unclaimed, not analyzed)
            storage_capacity = upgrade_effects.get('storage_capacity', 300)
            current_total = get_total_discovery_count(user_id)
            remaining_capacity = max(0, storage_capacity - current_total)

            if remaining_capacity == 0:
                logger.warning(f"⚠️ Storage full: {current_total}/{storage_capacity} discoveries. Limiting to minimum cargo.")
                cargo_capacity = min(cargo_capacity, 3)  # Still get SOME finds
            elif remaining_capacity < cargo_capacity:
                logger.info(f"📦 Storage nearly full: {current_total}/{storage_capacity}. Limiting cargo to {remaining_capacity}.")
                cargo_capacity = max(3, remaining_capacity)  # Never below 3

            all_items = get_discovery_items_catalog()
            nearby_features = get_nearest_mars_landmarks(
                base_coords['latitude'], base_coords['longitude'], limit=20
            )

            discoveries = generate_expedition_discoveries(
                expedition_id=expedition_id,
                expedition_data={
                    'distance_km': distance_km,
                    'commander_stats': commander_stats,
                    'scientist_stats': sci_stats,
                    'base_lat': base_coords['latitude'],
                    'base_lon': base_coords['longitude'],
                    'destination_lat': destination_lat,
                    'destination_lon': destination_lon,
                    'equipment_effects': upgrade_effects or {}
                },
                available_items=all_items,
                nearby_features=nearby_features,
                travel_time_seconds=travel_time_seconds,
                user_expedition_count=user_expedition_count,
                cargo_capacity=cargo_capacity
            )

            create_expedition_discoveries(discoveries)
            logger.info(f"✅ Created {len(discoveries)} discoveries for expedition {expedition_id}")
        except Exception as e:
            logger.error(f"Failed to generate discoveries: {e}")

        # Update activity timestamp for ARIA photo generation
        from utilities.postgres_utils import update_user_activity
        update_user_activity(user_id)

        # --- Background thread: blockchain tx + depot transaction ---
        import threading
        def do_blockchain_tx():
            try:
                miner = MarsAsteroidMiner()
                if not miner.connect():
                    logger.error(f"❌ Blockchain connect failed for expedition {expedition_id}")
                    return
                tx_result = miner.return_to_hub_with_reconciliation(
                    from_address=wallet['wallet_address'],
                    from_private_key=wallet['wallet_private_key'],
                    estimated_total_eth=total_pricing['total_cost_eth'],
                    base_cost_eth=base_expedition_cost_eth,
                    reason=destination_name
                )
                if tx_result['success']:
                    create_depot_transaction(
                        user_id=user_id,
                        wallet_address=wallet['wallet_address'],
                        purchase_type='expedition_launch',
                        amount_eth=total_pricing['total_cost_eth'],
                        tx_hash=tx_result['tx_hash'],
                        etherscan_url=tx_result['etherscan_url'],
                        item_details={
                            'destination': destination_name,
                            'distance_km': distance_km,
                            'reconciliation_message': tx_result.get('reconciliation_message'),
                            'atmospheric_difference': tx_result.get('atmospheric_difference_display'),
                            'actual_ops_cost': tx_result.get('actual_gas_cost_display'),
                            'first_mission_cap_applied': is_first_mission
                        }
                    )
                    logger.info(f"✅ Blockchain tx confirmed for expedition {expedition_id}: {tx_result['tx_hash']}")
                else:
                    logger.error(f"❌ Blockchain tx failed for expedition {expedition_id}: {tx_result}")
            except Exception as e:
                logger.error(f"❌ Background blockchain tx error for expedition {expedition_id}: {e}")

        thread = threading.Thread(target=do_blockchain_tx)
        thread.start()

        # --- Return immediately ---
        from utilities.depot_utils import eth_to_display
        new_balance_display = eth_to_display(new_balance)

        now = datetime.now()
        arrives_at = now + timedelta(seconds=travel_time_seconds)
        return_arrives_at = arrives_at + timedelta(seconds=travel_time_seconds)

        return {
            'success': True,
            'expedition_id': expedition_id,
            'new_balance': new_balance_display,
            'pending': True,
            'travel_time_seconds': travel_time_seconds,
            'arrives_at': arrives_at.isoformat() + 'Z',
            'return_arrives_at': return_arrives_at.isoformat() + 'Z',
            'total_round_trip_seconds': travel_time_seconds * 2,
            'vehicle_type': vehicle_type,
            'cargo_capacity': cargo_capacity,
            'first_mission_discount': is_first_mission
        }

    except Exception as e:
        logger.error(f"Expedition launch failed: {e}")
        return {'success': False, 'error': str(e)}

# ============================================================================
# EXPEDITION RECALL
# ============================================================================

def recall_expedition(user_id: int, expedition_id: int) -> dict:
    """
    Recall a vehicle mid-expedition. Vehicle turns around and heads back.
    Return speed uses full speed stack (vehicle × logistics × scientist × trail × terrain).
    No discoveries generated for recalled expeditions.
    """
    from utilities.postgres_utils import get_expedition_by_id, db_cursor, get_user_scientist
    from utilities.upgrades_utils import get_vehicle_for_expedition

    expedition = get_expedition_by_id(expedition_id)
    if not expedition:
        return {'success': False, 'error': 'Expedition not found'}

    if expedition['user_id'] != user_id:
        return {'success': False, 'error': 'Unauthorized'}

    if expedition['status'] != 'traveling':
        return {'success': False, 'error': 'Can only recall active expeditions'}

    now = datetime.now()
    arrives_at = expedition['arrives_at']
    departed_at = expedition['departed_at']

    # Can only recall during outbound leg
    if now >= arrives_at:
        return {'success': False, 'error': 'Vehicle already at destination or returning'}

    # Calculate how far the vehicle has traveled
    total_outbound_seconds = (arrives_at - departed_at).total_seconds()
    elapsed_seconds = (now - departed_at).total_seconds()
    progress = min(max(elapsed_seconds / total_outbound_seconds, 0.0), 1.0)
    distance_covered_km = float(expedition['distance_km']) * progress  # Convert Decimal to float

    # Calculate return speed using speed stack
    vehicle_type = expedition.get('vehicle_type', 'rover')
    vehicle_data = get_vehicle_for_expedition(user_id, vehicle_type)
    vehicle_speed_mult = vehicle_data['speed_mult'] if vehicle_data else 1.25

    # Captain logistics bonus
    logistics = expedition.get('commander_logistics', 50)
    logistics_speed_bonus = 1.0 + (logistics / 100.0)

    # Scientist navigation bonus
    scientist = get_user_scientist(user_id)
    sci_stats = scientist.get('stats', {}) if scientist else {}
    scientist_nav_mult = 1.0 + (sci_stats.get('navigation', 0) / 150.0)

    # Trail speed bonus for this route
    from utilities.postgres_utils import get_user_trail
    trail_data = get_user_trail(user_id, expedition['destination_name'])
    trail_speed_mult = TRAIL_SPEED_MULTIPLIERS.get(trail_data['trail_level'], 1.0)

    # Terrain speed modifier (drones fly — terrain doesn't slow them)
    dest_type = expedition.get('destination_type', '')
    terrain_speed_mult = 1.0
    if expedition.get('vehicle_type') != 'drone':
        for terrain_type, info in TERRAIN_MODIFIERS.items():
            if terrain_type.lower() in dest_type.lower():
                terrain_speed_mult = info.get('speed_mult', 1.0)
                break

    total_speed_mult = vehicle_speed_mult * logistics_speed_bonus * scientist_nav_mult * trail_speed_mult * terrain_speed_mult
    effective_speed = BASE_SPEED_KM_PER_HOUR * total_speed_mult
    return_hours = distance_covered_km / effective_speed if effective_speed > 0 else distance_covered_km / BASE_SPEED_KM_PER_HOUR
    return_seconds = return_hours * 3600

    new_return_arrives_at = now + timedelta(seconds=return_seconds)

    # Update expedition: status='recalled', timestamps adjusted
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE pilgrim.expeditions
                SET status = 'recalled', arrives_at = %s, return_arrives_at = %s
                WHERE id = %s AND user_id = %s
            """, (now, new_return_arrives_at, expedition_id, user_id))

            # Delete pre-generated discoveries (vehicle didn't reach destination)
            cur.execute("""
                DELETE FROM pilgrim.expedition_discoveries WHERE expedition_id = %s
            """, (expedition_id,))

        logger.info(f"🔄 Recalled expedition {expedition_id}: {progress*100:.0f}% complete, "
                    f"{distance_covered_km:.1f}km covered, returning in {return_seconds:.0f}s")

        return {
            'success': True,
            'message': f'{vehicle_type.capitalize()} recalled from {expedition["destination_name"]}',
            'distance_covered_km': round(distance_covered_km, 1),
            'progress_percent': round(progress * 100, 1),
            'return_seconds': int(return_seconds),
            'return_arrives_at': new_return_arrives_at.isoformat() + 'Z',
            'speed_mult': round(total_speed_mult, 2)
        }
    except Exception as e:
        logger.error(f"Failed to recall expedition {expedition_id}: {e}")
        return {'success': False, 'error': 'Database error during recall'}

# ============================================================================
# NEW: EXPEDITION COMPLETION (from app.py)
# ============================================================================

def complete_expedition_if_ready(expedition_id: int, user_id: int) -> dict:
    """
    Check if expedition is complete and process rewards if ready
    Returns status with completion data if finished
    """
    from utilities.postgres_utils import (
        get_expedition_by_id,
        get_user_primary_sepolia_wallet,
        update_sepolia_wallet_balance,
        create_depot_transaction,
        update_expedition_complete,
        record_landmark_discovery
    )
    from utilities.sepolia_utils import MarsAsteroidMiner
    from utilities.depot_utils import eth_to_display
    
    expedition = get_expedition_by_id(expedition_id)
    if not expedition:
        return {'success': False, 'error': 'Expedition not found'}
    
    if expedition['user_id'] != user_id:
        return {'success': False, 'error': 'Unauthorized'}
    
    if expedition['status'] == 'complete':
        return {
            'success': True,
            'complete': True,
            'discovery_type': expedition['discovery_type'],
            'sepolia_earned': eth_to_display(expedition['sepolia_earned']),
            'discovery_message': expedition['discovery_message']
        }
    
    now = datetime.now()  # Use local time to match how arrives_at was stored
    arrives_at = expedition['arrives_at']
    return_arrives_at = expedition.get('return_arrives_at') or arrives_at  # Fallback for old expeditions

    # Determine expedition phase
    if now < arrives_at:
        # Outbound: traveling to destination
        remaining = (arrives_at - now).total_seconds()
        return {
            'success': True,
            'complete': False,
            'phase': 'outbound',
            'remaining_seconds': remaining,
            'arrives_at': arrives_at.isoformat() + 'Z',
            'return_arrives_at': return_arrives_at.isoformat() + 'Z' if return_arrives_at else None
        }
    elif now < return_arrives_at:
        # At destination or returning: can view discoveries but can't extract yet
        phase = 'recalled' if expedition['status'] == 'recalled' else 'returning'
        remaining = (return_arrives_at - now).total_seconds()
        return {
            'success': True,
            'complete': False,
            'phase': phase,
            'remaining_seconds': remaining,
            'arrives_at': arrives_at.isoformat() + 'Z',
            'return_arrives_at': return_arrives_at.isoformat() + 'Z'
        }

    # Recalled expeditions: no discoveries, just free the vehicle
    if expedition['status'] == 'recalled':
        update_expedition_complete(
            expedition_id, 'recalled', 0.0,
            f'Vehicle recalled from {expedition["destination_name"]} - no discoveries'
        )
        return {
            'success': True,
            'complete': True,
            'discovery_type': 'recalled',
            'sepolia_earned': 0,
            'discovery_message': f'Vehicle recalled from {expedition["destination_name"]}'
        }

    discovery = calculate_expedition_discovery(expedition)

    wallet = get_user_primary_sepolia_wallet(user_id)
    if wallet:
        miner = MarsAsteroidMiner()
        if miner.connect():
            try:
                # Use FAST method - broadcast immediately, don't wait for confirmation
                reward_result = miner.send_sepolia_reward_fast(
                    wallet['wallet_address'],
                    discovery['sepolia_earned'],
                    discovery['message'],
                    context="expedition_discovery"
                )

                if reward_result['success']:
                    create_depot_transaction(
                        user_id=user_id,
                        wallet_address=wallet['wallet_address'],
                        purchase_type='expedition_discovery',
                        amount_eth=discovery['sepolia_earned'],
                        tx_hash=reward_result['tx_hash'],
                        etherscan_url=reward_result['etherscan_url'],
                        item_details={
                            'destination': expedition['destination_name'],
                            'expedition_id': expedition_id,
                            'discovery_type': discovery['discovery_type'],
                            'discovery_quality': discovery['discovery_quality'],
                            'breakdown': discovery['breakdown']
                        }
                    )
                    # Persist new balance to DB so it survives session expiry (same fix as #1144)
                    update_sepolia_wallet_balance(
                        wallet['wallet_address'],
                        wallet.get('current_balance_eth', 0) + discovery['sepolia_earned']
                    )
            except Exception as e:
                logger.error(f"Failed to send expedition reward: {e}")
    
    update_expedition_complete(
        expedition_id,
        discovery['discovery_type'],
        discovery['sepolia_earned'],
        discovery['message']
    )

    record_landmark_discovery(
        user_id=user_id,
        landmark_name=expedition['destination_name'],
        landmark_type=expedition['destination_type'],
        latitude=expedition['destination_lat'],
        longitude=expedition['destination_lon'],
        distance_km=expedition['distance_km'],
        sepolia_earned=discovery['sepolia_earned'],
        expedition_id=expedition_id
    )

    # ========================================================================
    # TRAIL NETWORK: Increment trail for completed route
    # ========================================================================
    try:
        from utilities.postgres_utils import increment_user_trail
        trail_result = increment_user_trail(user_id, expedition['destination_name'])
        logger.info(f"🛤️ Trail updated: {expedition['destination_name']} → {trail_result['trail_level']} ({trail_result['trip_count']} trips)")
    except Exception as e:
        logger.error(f"Failed to update trail: {e}")

    # ========================================================================
    # SV ECONOMY: Award Science Value on expedition completion
    # Per brainstorm: 100-200 short, 200-500 medium, 500-1000 long, 1000-2000 epic
    # Formula: base SV scales with distance, Dr. Bo analyzes field data on return
    # ========================================================================
    try:
        from utilities.postgres_utils import add_passive_sv
        distance = float(expedition.get('distance_km', 0))
        if distance <= 200:
            expedition_sv = 100 + int(distance * 0.5)  # 100-200 SV
        elif distance <= 500:
            expedition_sv = 200 + int((distance - 200) * 1.0)  # 200-500 SV
        elif distance <= 1500:
            expedition_sv = 500 + int((distance - 500) * 0.5)  # 500-1000 SV
        else:
            expedition_sv = 1000 + int((distance - 1500) * 0.4)  # 1000-2000+ SV
        expedition_sv = max(100, min(expedition_sv, 2000))  # Clamp to 100-2000
        add_passive_sv(user_id, expedition_sv)
        logger.info(f"🔬 Expedition SV: user {user_id} earned {expedition_sv} SV from {distance:.0f} km expedition to {expedition['destination_name']}")
    except Exception as e:
        logger.error(f"Failed to award expedition SV: {e}")

    # ========================================================================
    # SHARD NETWORK: Check for Origin Site proximity and roll for Echo Site
    # ========================================================================
    signal_events = check_signal_events(
        user_id=user_id,
        expedition_id=expedition_id,
        lat=expedition['destination_lat'],
        lon=expedition['destination_lon'],
        landmark_name=expedition['destination_name']
    )

    # ========================================================================
    # ARIA BONDS: Check if another player has visited this landmark
    # ========================================================================
    aria_fragment = None
    try:
        from utilities.aria_bond_utils import check_for_aria_bond
        aria_fragment = check_for_aria_bond(user_id, expedition['destination_name'])
        if aria_fragment:
            logger.info(f"⚡ ARIA fragment created for user {user_id} at {expedition['destination_name']}")
    except Exception as e:
        logger.error(f"ARIA bond check failed: {e}")

    return {
        'success': True,
        'complete': True,
        'discovery_type': discovery['discovery_type'],
        'sepolia_earned': eth_to_display(discovery['sepolia_earned']),
        'discovery_message': discovery['message'],
        'signal_events': signal_events,  # Origin/Echo site discoveries
        'aria_fragment': aria_fragment  # Entangled crystal fragment if found
    }

# ============================================================================
# FIXED: EXPEDITION DISCOVERY PROGRESS - PROPERLY HANDLES COMPLETED EXPEDITIONS
# ============================================================================

def get_expedition_discovery_progress(expedition_id: int, user_id: int) -> dict:
    """
    Get expedition discoveries with current progress unlocking
    FIXED: Ensures discoveries persist after expedition completion and shows claim status
    """
    from utilities.postgres_utils import (
        get_expedition_by_id,
        get_expedition_discoveries,
        unlock_discoveries_by_distance
    )
    
    expedition = get_expedition_by_id(expedition_id)
    if not expedition or expedition['user_id'] != user_id:
        return {'success': False, 'error': 'Unauthorized'}
    
    # For completed expeditions, unlock ALL discoveries and show full distance
    if expedition['status'] == 'complete':
        current_distance = float(expedition['distance_km'])
        # Ensure all discoveries are unlocked for completed expeditions
        unlock_discoveries_by_distance(expedition_id, current_distance)
        logger.info(f"✅ Completed expedition {expedition_id}: unlocked all discoveries at {current_distance} km")
    else:
        elapsed = (datetime.now() - expedition['departed_at']).total_seconds()  # Use local time to match stored timestamps
        total_time = (expedition['arrives_at'] - expedition['departed_at']).total_seconds()
        progress = min(1.0, elapsed / total_time)
        current_distance = float(expedition['distance_km']) * progress
        unlock_discoveries_by_distance(expedition_id, current_distance)
        logger.debug(f"⏳ Active expedition {expedition_id}: {progress:.1%} complete, {current_distance:.1f}/{expedition['distance_km']} km")
    
    all_discoveries = get_expedition_discoveries(expedition_id, unlocked_only=False)
    unlocked = [d for d in all_discoveries if d['unlocked_at']]
    locked = [d for d in all_discoveries if not d['unlocked_at']]
    
    # For completed expeditions, include claim status and make sure discoveries persist
    unclaimed_count = 0
    if expedition['status'] == 'complete':
        for discovery in unlocked:
            discovery['can_claim'] = not discovery.get('claimed_by_user', False)
            if discovery['can_claim']:
                unclaimed_count += 1
        
        logger.info(f"🏆 Completed expedition {expedition_id}: {len(unlocked)} unlocked discoveries, {unclaimed_count} unclaimed")
    
    return {
        'success': True,
        'expedition_status': expedition['status'],
        'expedition_complete': expedition['status'] == 'complete',
        'current_distance_km': round(current_distance, 2),
        'total_distance_km': float(expedition['distance_km']),
        'unlocked_count': len(unlocked),
        'total_count': len(all_discoveries),
        'unlocked_discoveries': unlocked,
        'locked_discoveries': locked,
        'unclaimed_count': unclaimed_count,
        'has_claimable_discoveries': unclaimed_count > 0,
        'fuel_cost_display': round(float(expedition.get('fuel_cost_eth', 0) or 0) * 10000000, 1),
        'destination_name': expedition.get('destination_name', 'Unknown')
    }

# ============================================================================
# EXPEDITION DISCOVERY CALCULATION
# ============================================================================

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


def calculate_expedition_discovery(expedition: dict) -> dict:
    """Calculate what the commander discovered at destination"""
    
    base_reward = float(expedition['fuel_cost_eth']) * 2
    distance_km = float(expedition['distance_km'])
    exploration = expedition.get('commander_exploration', 50)
    exploration_bonus = (exploration / 90.0) * 0.6
    strategy = expedition.get('commander_strategy', 50)
    strategy_factor = 0.5 + (strategy / 90.0) * 0.5
    leadership = expedition.get('commander_leadership', 50)
    leadership_bonus = (leadership / 90.0) * 0.2
    
    charisma = expedition.get('commander_charisma', 50)
    charisma_bonus = (charisma / 90.0) * 0.3
    
    distance_bonus = min(distance_km / 400.0, 4.0)
    
    location_multipliers = {
        'Crater': 1.3, 'Volcano': 1.1, 'Mons': 1.6, 'Planitia': 1.0,
        'Vallis': 1.2, 'Canyon': 0.9, 'Chasma': 1.4, 'Patera': 1.2, 'default': 1.0
    }
    
    location_mult = 1.0
    dest_type = expedition.get('destination_type', '')
    for loc_type, mult in location_multipliers.items():
        if loc_type.lower() in dest_type.lower():
            location_mult = mult
            break
    
    variance = 0.5 * strategy_factor
    luck = random.uniform(1.0 - variance, 1.0 + variance)
    
    total_reward = (
        base_reward * 
        (1 + exploration_bonus) * 
        (1 + leadership_bonus) *
        (1 + charisma_bonus) *
        distance_bonus * 
        location_mult * 
        luck
    )
    
    if exploration > 70 and luck > 1.2:
        discovery_type = 'exceptional_find'
        quality = "exceptional"
        quality_desc = "Your commander's expertise led to an extraordinary discovery"
    elif exploration < 40 or luck < 0.8:
        discovery_type = 'modest_deposit'
        quality = "modest"
        quality_desc = "A standard deposit was located"
    else:
        discovery_type = 'solid_discovery'
        quality = "valuable"
        quality_desc = "Your team located a promising cache"
    
    message = (
        f"{quality_desc} at {expedition['destination_name']}. "
        f"Distance bonus: {distance_bonus:.1f}×. "
        f"Commander Exploration ({exploration}) yielded {exploration_bonus*100:.0f}% additional resources. "
    )
    
    if charisma > 40:
        message += f"Charisma ({charisma}) improved extraction by {charisma_bonus*100:.0f}%. "
    
    if strategy > 60:
        message += f"Strategic planning minimized hazards. "
    if leadership > 60:
        message += f"Strong leadership maintained team morale. "
    
    message += f"Total yield: {total_reward * 10000000:.1f} Sepolia from {expedition['destination_type']}."
    
    return {
        'sepolia_earned': total_reward,
        'discovery_type': discovery_type,
        'discovery_quality': quality,
        'message': message,
        'breakdown': {
            'base_reward': base_reward,
            'exploration_bonus': exploration_bonus,
            'leadership_bonus': leadership_bonus,
            'charisma_bonus': charisma_bonus,
            'charisma_stat': charisma,
            'distance_bonus': distance_bonus,
            'location_mult': location_mult,
            'luck_factor': luck
        }
    }

# ============================================================================
# PAGE DATA CONSOLIDATION
# ============================================================================

def get_expeditions_page_data(user_id: int) -> dict:
    """
    Get all data needed for the colony/expeditions page.
    Consolidates ~55 lines of logic from app.py.

    Returns:
        dict with all template variables for expeditions.html
    """
    import json
    from datetime import datetime
    from utilities.postgres_utils import (
        get_or_set_user_mars_home, get_user_active_expeditions,
        get_user_discovered_landmarks, get_available_landmarks_by_discovery,
        get_user_completed_expeditions_count
    )
    from utilities.depot_utils import get_fast_balance_and_wallet_info, get_commander_and_stats, generate_commander_stats

    total_balance, _, _ = get_fast_balance_and_wallet_info(user_id)  # FAST: no blockchain
    _, commander_stats = get_commander_and_stats(user_id)
    if not commander_stats:
        commander_stats = generate_commander_stats()

    home_coords = get_or_set_user_mars_home(user_id)
    landmarks = get_available_landmarks_by_discovery(user_id, home_coords, limit=30)
    active_expeditions = get_user_active_expeditions(user_id)
    discovered_landmarks = get_user_discovered_landmarks(user_id)

    # Auto-complete any arrived expeditions on page load
    # This ensures users see the correct state immediately
    # IMPORTANT: Only process expeditions that are still 'traveling', not already 'complete'
    just_completed_expedition = None
    now = datetime.now()  # Use local time to match stored timestamps
    for expedition in active_expeditions[:]:  # Copy list to allow modification
        # Auto-complete traveling/recalled expeditions that have returned
        # Already-complete expeditions with unclaimed items should stay visible
        if expedition['status'] in ('traveling', 'recalled') and expedition.get('return_arrives_at') and now >= expedition['return_arrives_at']:
            # Expedition has arrived - auto-complete it
            result = complete_expedition_if_ready(expedition['id'], user_id)
            if result.get('complete'):
                just_completed_expedition = {
                    'destination': expedition['destination_name'],
                    'discovery_message': result.get('discovery_message', ''),
                    'sepolia_earned': result.get('sepolia_earned', 0)
                }
                # Update expedition status in our local list (don't remove - it still has unclaimed items)
                expedition['status'] = 'complete'
                # Refresh balance after completion (fast - from session/DB cache)
                total_balance, _, _ = get_fast_balance_and_wallet_info(user_id)
    expeditions_completed = get_user_completed_expeditions_count(user_id)

    landmarks = sort_landmarks_by_cost(landmarks, commander_stats, expeditions_completed, home_coords, user_id=user_id)

    # Fetch all user trails for map visualization
    from utilities.postgres_utils import get_user_trails
    all_trails = get_user_trails(user_id)
    trails_by_name = {t['destination_name']: t for t in all_trails}

    js_landmarks = []
    for i, landmark in enumerate(landmarks):
        trail = trails_by_name.get(landmark['name'], {})
        js_landmarks.append({
            'index': i,
            'name': str(landmark['name']),
            'type': str(landmark['type']),
            'latitude': float(landmark['latitude']),
            'longitude': float(landmark['longitude']),
            'distance_km': float(landmark['distance_km']),
            'travel_days': float(landmark.get('travel_days', 0)),
            'sepolia_cost': round(landmark.get('calculated_cost', 0), 1),
            'diameter_km': float(landmark['diameter_km']) if landmark.get('diameter_km') else 0,
            'quad_name': str(landmark['quad_name']),
            'link': str(landmark['link']),
            'is_discovered': landmark.get('is_discovered', False),
            'last_visit': landmark.get('last_visit').isoformat() if landmark.get('last_visit') else None,
            'last_yield': float(landmark.get('last_yield', 0)) * 10000000 if landmark.get('last_yield') else 0,
            'trail_level': trail.get('trail_level', 'none'),
            'trail_trip_count': trail.get('trip_count', 0)
        })

    # Get infrastructure effects for UI display
    try:
        from utilities.infrastructure_utils import get_user_infrastructure_effects
        infra_effects = get_user_infrastructure_effects(user_id)
    except Exception:
        infra_effects = {}

    expedition_bonuses = {
        'expedition_range_mult': infra_effects.get('expedition_range_mult', 1.0),
        'legendary_chance_bonus': infra_effects.get('legendary_chance_bonus', 0.0),
        'discovery_chance_bonus': infra_effects.get('discovery_chance_bonus', 0.0),
    }

    # Calculate max concurrent expeditions - vehicle-based (max 3)
    try:
        from utilities.upgrades_utils import count_user_vehicles, get_user_owned_vehicles, get_upgrade_stats
        vehicle_count = count_user_vehicles(user_id)
        owned_vehicles = get_user_owned_vehicles(user_id)
    except Exception:
        vehicle_count = 1
        owned_vehicles = [{'vehicle_type': 'rover', 'name': 'Scout Rover', 'cargo': 5}]

    # Discovery-based range multiplier (same formula used in estimate_expedition)
    discovery_count = len(discovered_landmarks) if discovered_landmarks else 0
    fog_radius = min(1000, 300 + discovery_count * 50)
    range_mult = fog_radius / 300.0

    # Determine which vehicle types are currently on active expeditions
    active_vehicle_types = {e.get('vehicle_type', 'rover') for e in active_expeditions
                            if e.get('status') in ('traveling', 'recalled')}

    # Enrich vehicles with range breakdown data + availability
    for v in owned_vehicles:
        vtype = v.get('vehicle_type', 'rover')
        base_range = v.get('max_range_km', 9999)
        lv1_stats = get_upgrade_stats('vehicles', vtype, 1) or {}
        v['base_range_km'] = lv1_stats.get('max_range_km', base_range)
        v['base_speed'] = lv1_stats.get('expedition_speed_mult', v.get('speed_mult', 1.0))
        v['effective_range_km'] = int(base_range * range_mult)
        v['available'] = vtype not in active_vehicle_types

    # Expedition slots: vehicle count capped by habitat capacity (default 3 if no habitat)
    expedition_cap = infra_effects.get('expedition_capacity', 3)
    max_concurrent_expeditions = min(vehicle_count, expedition_cap)

    # ARIA bonds for Signal tab display
    signal_bonds = []
    try:
        from utilities.aria_bond_utils import get_bonds_for_display
        signal_bonds = get_bonds_for_display(user_id)
    except Exception:
        pass

    return {
        'drop_coords': home_coords,
        'landmarks': landmarks,
        'active_expeditions': active_expeditions,
        'discovered_landmarks': discovered_landmarks,
        'landmarks_json': json.dumps(js_landmarks),
        'base_lat': float(home_coords['latitude']),
        'base_lon': float(home_coords['longitude']),
        'total_balance': total_balance,
        'just_completed_expedition': just_completed_expedition,  # For ARIA to announce
        'expedition_bonuses': expedition_bonuses,  # Infrastructure bonuses for UI
        'max_concurrent_expeditions': max_concurrent_expeditions,  # Based on vehicles owned
        'owned_vehicles': owned_vehicles,  # List of user's vehicles for slot display
        'vehicle_count': vehicle_count,  # Total vehicles owned
        'expedition_count': expeditions_completed,  # Total completed expeditions for History tab
        'discovery_count': discovery_count,  # For range breakdown display
        'range_mult': round(range_mult, 2),  # Discovery-based range multiplier
        'signal_bonds': signal_bonds,  # ARIA bonds for Signal tab
    }

def claim_all_discoveries(user_id, expedition_id=None):
    """Claim all unlocked discoveries for user (optionally for specific expedition).
    Uses batch SQL update for efficiency - handles 1000s of discoveries in one query.
    """
    from utilities.postgres_utils import claim_all_pending_discoveries, get_expedition_by_id

    # Verify expedition ownership and completion if specified
    if expedition_id:
        expedition = get_expedition_by_id(expedition_id)
        if not expedition or expedition['user_id'] != user_id:
            return {'success': False, 'error': 'Unauthorized'}
        if expedition['status'] not in ('complete', 'recalled'):
            return {'success': False, 'error': 'Expedition still in progress'}

    # Use batch claim (single SQL UPDATE instead of loop)
    result = claim_all_pending_discoveries(user_id, expedition_id)

    if result['claimed_count'] == 0:
        return {'success': False, 'error': 'No discoveries to claim'}

    return {
        'success': True,
        'claimed_count': result['claimed_count'],
        'total_value': result['total_value'],
        'message': f"Claimed {result['claimed_count']} discoveries"
    }

def get_discovery_progress_formatted(expedition_id, user_id):
    """Get expedition discovery progress with frontend formatting."""
    import json as json_module

    result = get_expedition_discovery_progress(expedition_id, user_id)
    if not result.get('success'):
        return result

    for discovery in result.get('unlocked_discoveries', []):
        discovery['can_claim'] = not discovery.get('claimed_by_user', False)
        discovery['claimed_by_user'] = discovery.get('claimed_by_user', False)
        if isinstance(discovery.get('found_at_coordinates'), str):
            try:
                discovery['found_at_coordinates'] = json_module.loads(discovery['found_at_coordinates'])
            except:
                discovery['found_at_coordinates'] = {'lat': 0, 'lon': 0}

    return result


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


def start_expedition_from_request(user_id, data, session=None):
    """Start expedition from request data."""
    result = launch_expedition(
        user_id=user_id,
        destination_name=data.get('destination_name'),
        destination_type=data.get('destination_type'),
        destination_lat=data.get('latitude'),
        destination_lon=data.get('longitude'),
        distance_km=data.get('distance_km'),
        vehicle_type=data.get('vehicle_type', 'rover')
    )

    # Invalidate cached balance since we spent Sepolia
    if result.get('success') and session is not None:
        from utilities.depot_utils import invalidate_balance_cache
        invalidate_balance_cache(session)

    return result

# ============================================================================
# SHARD NETWORK: Signal Events (Origin Sites & Echo Sites)
# ============================================================================

def check_signal_events(
    user_id: int,
    expedition_id: int,
    lat: float,
    lon: float,
    landmark_name: str = None
) -> Dict[str, Any]:
    """
    Check for Shard Network events after expedition completion:
    1. Check proximity to unclaimed Origin Sites (14 real Mars landing locations)
    2. Roll for Echo Site spawn (2% base + pity timer)

    Returns dict with any discovered/spawned sites.
    """
    from utilities.signal_utils import (
        check_origin_site_proximity,
        maybe_spawn_echo_site
    )

    events = {
        'origin_site_nearby': None,
        'echo_site_spawned': None
    }

    try:
        # 1. Check for Origin Site proximity (within 50km of real Mars landing sites)
        origin_site = check_origin_site_proximity(lat, lon)
        if origin_site:
            events['origin_site_nearby'] = {
                'id': origin_site['id'],
                'site_code': origin_site['site_code'],
                'mission_name': origin_site['mission_name'],
                'distance_km': origin_site.get('distance_km', 0),
                'memory_preview': origin_site['memory_text'][:100] + '...' if len(origin_site['memory_text']) > 100 else origin_site['memory_text']
            }
            logger.info(f"🎯 Origin Site {origin_site['site_code']} detected near expedition to {landmark_name}!")

        # 2. Roll for Echo Site spawn (2% base + pity timer up to guaranteed)
        echo_site = maybe_spawn_echo_site(
            user_id=user_id,
            expedition_lat=lat,
            expedition_lon=lon,
            expedition_id=expedition_id,
            nearby_landmark=landmark_name
        )
        if echo_site:
            events['echo_site_spawned'] = {
                'id': echo_site['id'],
                'site_code': echo_site['site_code'],
                'latitude': echo_site['latitude'],
                'longitude': echo_site['longitude'],
                'memory_preview': echo_site['memory_text'][:100] + '...' if len(echo_site['memory_text']) > 100 else echo_site['memory_text']
            }
            logger.info(f"✨ Echo Site {echo_site['site_code']} spawned near {landmark_name}!")

    except Exception as e:
        logger.error(f"Error checking signal events: {e}")

    return events


# ============================================================================
# TRAIL BUILDING (extracted from app.py - candidate for separate trail_utils.py)
# ============================================================================

def handle_trail_build_request(user_id, data):
    """Handle a trail build request. Returns result dict for jsonify."""
    from utilities.postgres_utils import (
        get_crew_mission_status, start_crew_mission, db_cursor, consume_discovery_for_trail
    )
    from utilities.shop_utils import get_scanner_trail_bonus
    from config import get_trail_duration_from_multiplier, get_scientist_trail_bonus, COLONY_SCIENTISTS

    destination = data.get('destination_name', '')
    worker_type = data.get('worker_type', '').lower()

    if not destination:
        return {'success': False, 'error': 'No destination specified'}
    if worker_type not in ('captain', 'scientist', 'aria'):
        return {'success': False, 'error': 'Invalid worker type'}

    # Check if crew member is already busy
    status = get_crew_mission_status(user_id)
    member_status = status.get(worker_type) or {}
    if member_status.get('busy'):
        return {'success': False, 'error': f'{worker_type.title()} is already on a mission'}
    if member_status.get('complete'):
        return {'success': False, 'error': f'{worker_type.title()} has a mission to claim first'}

    # Validate destination is an active trail target (or visited expedition site)
    with db_cursor() as cur:
        # Check active trail segments first
        cur.execute("""
            SELECT ts.destination_name, mm.latitude, mm.longitude, u.home_mars_lat, u.home_mars_lon
            FROM pilgrim.trail_segments ts
            JOIN pilgrim.mars_mappings mm ON mm.name = ts.destination_name
            JOIN pilgrim.users u ON u.id = ts.user_id
            WHERE ts.user_id = %s AND ts.destination_name = %s
            LIMIT 1
        """, (user_id, destination))
        row = cur.fetchone()
        if not row:
            # Fallback: check visited expedition sites
            cur.execute("""
                SELECT DISTINCT e.destination_name, mm.latitude, mm.longitude, u.home_mars_lat, u.home_mars_lon
                FROM pilgrim.expeditions e
                JOIN pilgrim.mars_mappings mm ON mm.name = e.destination_name
                JOIN pilgrim.users u ON u.id = e.user_id
                WHERE e.user_id = %s AND e.destination_name = %s AND e.status = 'complete'
                LIMIT 1
            """, (user_id, destination))
            row = cur.fetchone()
            if not row:
                return {'success': False, 'error': 'Destination not available for trail building'}

    # Calculate km based on crew stats, scanner, and consumable
    # Stats are the PRIMARY driver (1x-6x). See config_shop.BASE_TRAIL_RATE_KMH.
    from config_shop import calculate_trail_km
    stat_multiplier = 1.0
    stat_bonus_desc = ""

    with db_cursor() as cur:
        if worker_type == 'captain':
            # Captain: commander_logistics stat (0-90) is primary, XP is secondary
            cur.execute("SELECT captain_logistics_xp FROM pilgrim.users WHERE id = %s", (user_id,))
            r = cur.fetchone()
            logistics_xp = r.get('captain_logistics_xp') or 0 if r else 0
            # Get the actual character stat (commander_logistics) from replicate_assets
            cur.execute("""
                SELECT commander_logistics FROM pilgrim.replicate_assets
                WHERE user_id = %s AND asset_type = 'character_image' AND is_deleted = FALSE
                ORDER BY created_at DESC LIMIT 1
            """, (user_id,))
            asset = cur.fetchone()
            commander_logistics = float(asset.get('commander_logistics') or 0) if asset else 0
            stat_multiplier = 1.0 + (commander_logistics / 30) + (logistics_xp / 2000)
            stat_bonus_desc = f"Logistics {int(commander_logistics)} + {logistics_xp} XP ({stat_multiplier:.1f}x)"

        elif worker_type == 'scientist':
            cur.execute("SELECT scientist_navigation_xp, scientist_key FROM pilgrim.users WHERE id = %s", (user_id,))
            r = cur.fetchone()
            nav_xp = r.get('scientist_navigation_xp') or 0 if r else 0
            nav_multiplier = 1.0 + (nav_xp / 1500)
            scientist_key = r.get('scientist_key') if r else None
            specialty_geology_bonus = get_scientist_trail_bonus(scientist_key) if scientist_key else 0
            stat_multiplier = nav_multiplier * (1.0 + specialty_geology_bonus)
            scientist_name = COLONY_SCIENTISTS.get(scientist_key, {}).get('specialty', 'Science') if scientist_key else 'Science'
            stat_bonus_desc = f"Nav {nav_xp} XP + {scientist_name} ({stat_multiplier:.1f}x)"

        elif worker_type == 'aria':
            # ARIA: resonance is primary multiplier, lore_memory adds efficiency
            cur.execute("SELECT resonance_level, lore_memory_level FROM pilgrim.aria_skills WHERE user_id = %s", (user_id,))
            r = cur.fetchone()
            resonance_level = r.get('resonance_level') or 1 if r else 1
            lore_memory_level = r.get('lore_memory_level') or 1 if r else 1
            stat_multiplier = 1.0 + (resonance_level / 20) + (lore_memory_level / 200)
            stat_bonus_desc = f"Resonance Lv{resonance_level} + Lore Lv{lore_memory_level} ({stat_multiplier:.1f}x)"

    scanner_bonus = get_scanner_trail_bonus(user_id)
    scanner_multiplier = scanner_bonus['multiplier']

    # EVA Suit bonus: +5% trail speed per suit level (Lv10 = +50%)
    from utilities.upgrades_utils import get_user_upgrade_level
    suit_level = get_user_upgrade_level(user_id, 'gear', 'suit')
    suit_multiplier = 1.0 + (suit_level * 0.05)

    # Consumable bonus (optional)
    consumable_multiplier = 1.0
    consumable_used = None
    consumable_id = data.get('consumable_id')
    if consumable_id:
        consume_result = consume_discovery_for_trail(user_id, int(consumable_id))
        if consume_result.get('success'):
            consumable_multiplier = 1.0 + consume_result['bonus']
            consumable_used = consume_result

    total_multiplier = stat_multiplier * scanner_multiplier * suit_multiplier * consumable_multiplier
    trail_calc = calculate_trail_km(total_multiplier)
    duration_minutes = trail_calc['duration_minutes']
    km_to_add = trail_calc['km_to_add']

    # Chain routing: find nearest connected node to build from
    from utilities.db_trails import find_nearest_trail_origin
    origin = find_nearest_trail_origin(user_id, destination)
    from_landmark = origin.get('from_landmark', 'HOME')

    result = start_crew_mission(user_id, worker_type, destination, duration_minutes, km_to_add, from_landmark)

    if result.get('success'):
        result['km_to_add'] = round(km_to_add, 4)
        result['from_landmark'] = from_landmark
        result['segment_distance_km'] = origin.get('segment_distance_km', 0)
        result['stat_multiplier'] = round(stat_multiplier, 2)
        result['stat_bonus'] = stat_bonus_desc
        result['scanner_multiplier'] = round(scanner_multiplier, 2)
        result['scanner_bonus'] = scanner_bonus
        result['suit_multiplier'] = round(suit_multiplier, 2)
        result['suit_level'] = suit_level
        result['consumable_multiplier'] = round(consumable_multiplier, 2)
        result['consumable_used'] = consumable_used
        result['total_multiplier'] = round(total_multiplier, 2)
        if from_landmark == 'HOME':
            result['message'] = f'{worker_type.title()} heading to {destination} for {duration_minutes} min session'
        else:
            result['message'] = f'{worker_type.title()} building {from_landmark} → {destination} for {duration_minutes} min session'

    return result


def get_trail_consumables_data(user_id):
    """Get available consumables and scanner bonus for trail building."""
    from utilities.postgres_utils import get_trail_consumable_discoveries
    from utilities.shop_utils import get_scanner_trail_bonus
    from config import TRAIL_CONSUMABLE_BONUSES

    scanner = get_scanner_trail_bonus(user_id)
    discoveries = get_trail_consumable_discoveries(user_id)

    for d in discoveries:
        item_type = d.get('item_type', '')
        item_name = (d.get('item_name') or '').lower()
        type_bonuses = TRAIL_CONSUMABLE_BONUSES.get(item_type, {})
        bonus = type_bonuses.get('default', 0.05)
        for kw, val in type_bonuses.items():
            if kw != 'default' and kw in item_name:
                bonus = val
                break
        d['trail_bonus'] = bonus
        d['trail_bonus_percent'] = int(bonus * 100)

    # Group consumables by name+bonus, keep oldest ID for FIFO
    grouped = {}
    for d in sorted(discoveries, key=lambda x: x.get('claimed_at', '')):
        key = f"{d['item_name']}|{d['trail_bonus_percent']}"
        if key not in grouped:
            grouped[key] = {
                'id': d['id'],
                'item_name': d['item_name'],
                'trail_bonus_percent': d['trail_bonus_percent'],
                'count': 1
            }
        else:
            grouped[key]['count'] += 1

    return {'success': True, 'scanner': scanner, 'consumables': list(grouped.values())}


# ============================================================================
# RE-EXPORTS: Functions moved to discovery_utils.py
# Existing `from utilities.expedition_utils import X` statements keep working.
# ============================================================================

from utilities.discovery_utils import (  # noqa: F401
    get_progressive_weights, calculate_discovery_checkpoints,
    interpolate_route_coordinates, matches_terrain_feature,
    roll_for_item_spawn, get_distance_value_multiplier,
    calculate_enhanced_item_value, generate_expedition_discoveries,
    analyze_discovery, shard_all_discoveries,
)