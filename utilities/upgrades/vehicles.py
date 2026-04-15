"""Vehicle-specific helpers.

Thin wrappers over get_user_upgrade_level / get_upgrade_stats that
shape data for expedition slot math.
"""

import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


def get_vehicle_for_expedition(user_id: int, vehicle_type: str = 'rover') -> Dict[str, Any]:
    """
    Get vehicle stats for expedition calculations.
    Returns stats dict with cargo, speed_mult, discovery bonuses.
    """
    from utilities.upgrades.state import get_user_upgrade_level, get_upgrade_stats

    level = get_user_upgrade_level(user_id, 'vehicles', vehicle_type)
    if level == 0:
        return None  # Vehicle not unlocked

    stats = get_upgrade_stats('vehicles', vehicle_type, level)
    if not stats:
        return None

    return {
        'vehicle_type': vehicle_type,
        'level': level,
        'name': stats.get('name', f'{vehicle_type} Lv{level}'),
        'cargo': stats.get('cargo', 5),
        'speed_mult': stats.get('expedition_speed_mult', stats.get('speed_mult', 1.0)),
        'max_range_km': stats.get('max_range_km', 9999),
        'discovery_bonus': stats.get('discovery_bonus', 0),
        'rare_bonus': stats.get('rare_bonus', 0),
        'legendary_bonus': stats.get('legendary_bonus', 0),
        'image_url': stats.get('image_url'),
    }


def get_user_owned_vehicles(user_id: int) -> List[Dict[str, Any]]:
    """
    Get list of all vehicles owned by user (level >= 1).
    Used for expedition slot calculation - each vehicle = 1 expedition slot.
    """
    vehicles = []
    for vehicle_type in ['rover', 'drone', 'buggy']:
        vehicle = get_vehicle_for_expedition(user_id, vehicle_type)
        if vehicle:
            vehicles.append(vehicle)
    return vehicles


def count_user_vehicles(user_id: int) -> int:
    """
    Count total vehicles owned by user.
    Expedition slots = number of vehicles owned.
    """
    return len(get_user_owned_vehicles(user_id))
