"""
Terrain physics + travel-time math for expeditions.

Pure logic. Constants live in utilities/expeditions/config.py.
No DB access, no blockchain, no game-state mutations.
"""

import logging
from utilities.mars_math import point_to_path_distance
from utilities.expeditions.config import (
    BASE_SPEED_KM_PER_HOUR,
    EVA_HOURS_PER_DAY,
    TERRAIN_MODIFIERS,
    MISSION_ARTIFACT_MAX_DISTANCE_KM,
)

logger = logging.getLogger(__name__)


# ============================================================================
# SPEED / TRAVEL TIME
# ============================================================================

def calculate_speed_multiplier(vehicle_speed_mult: float = 1.0, logistics: int = 50) -> float:
    """
    Total speed multiplier for expedition travel.

    Formula per PILGRIMS.md:
        Travel time = Distance ÷ (base_speed × logistics_modifier × vehicle_speed)

    - Vehicle is PRIMARY speed factor (1.25x–3.0x based on upgrade level)
    - Logistics gives SECONDARY bonus (1.0x–2.0x based on 0-100 stat)
    """
    logistics_bonus = 1.0 + (logistics / 100.0)
    return vehicle_speed_mult * logistics_bonus


def calculate_travel_time(distance_km: float, speed_multiplier: float) -> dict:
    """Travel time for an expedition given distance and speed."""
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
    """Quick estimate of travel days. Used for rough display before full pricing."""
    speed_mult = calculate_speed_multiplier(vehicle_speed_mult, logistics)
    return calculate_travel_time(distance_km, speed_mult)['travel_days']


# ============================================================================
# TERRAIN LOOKUP
# ============================================================================

def get_terrain_info(destination_type: str) -> dict:
    """
    Resolve a destination type string to its terrain modifier dict.
    Collapses the 4× repeated lookup pattern from expedition_utils.py.
    """
    if not destination_type:
        return TERRAIN_MODIFIERS['default']
    needle = destination_type.lower()
    for terrain_type, info in TERRAIN_MODIFIERS.items():
        if terrain_type == 'default':
            continue
        if terrain_type.lower() in needle:
            return info
    return TERRAIN_MODIFIERS['default']


# ============================================================================
# GEOGRAPHIC FILTERING
# ============================================================================

def is_item_geographically_valid(item: dict, start_lat: float, start_lon: float,
                                 end_lat: float, end_lon: float) -> bool:
    """Check if a discovery item can spawn on this expedition path."""
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
