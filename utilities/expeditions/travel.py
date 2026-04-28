"""
Multi-segment travel time for expeditions.

v3 (bug #1414): Trails are now 4 deterministic cardinal chains per captain.
An expedition's destination either lies on a chain (a chain segment's
to_landmark) or it doesn't. On-chain destinations get the segment's
speed multiplier. Off-chain destinations get baseline 1.0× (no trail bonus).

The old multi-segment compounding (walking arbitrary trail_segments rows in
distance order) is gone. The chain segment IS the trail. No "highway up to
50km then road after" math — destinations are atomic v3.

Pure orchestration — no mutations.
"""

import logging

from utilities.expeditions.config import BASE_SPEED_KM_PER_HOUR
from utilities.postgres.trails.chains import get_chain_speed_mult_for_destination

logger = logging.getLogger(__name__)


def calculate_segmented_travel_time(
    user_id: int,
    destination_distance_km: float,
    destination_name: str,
    base_speed_mult: float,
    base_coords: dict = None,
) -> dict:
    """
    Travel time with v3 chain-aware speed bonus.

    If the destination is the to_landmark of one of the captain's 4 cardinal
    chain segments, applies that segment's km-ratio speed multiplier (1.0× to
    1.5×). Otherwise no trail bonus.

    Returns the same shape the rest of the codebase expects:
      total_hours, segments[], effective_trail_mult.
    """
    chain_mult = 1.0
    chain_segment_label = 'none'
    try:
        chain_mult = get_chain_speed_mult_for_destination(user_id, destination_name)
        if chain_mult > 1.0:
            chain_segment_label = 'chain'
    except Exception as e:
        logger.warning(f"chain speed lookup failed user={user_id} dest={destination_name}: {e}")

    effective_speed = BASE_SPEED_KM_PER_HOUR * base_speed_mult * chain_mult
    if effective_speed <= 0:
        effective_speed = BASE_SPEED_KM_PER_HOUR
    total_hours = destination_distance_km / effective_speed

    return {
        'total_hours': total_hours,
        'segments': [{
            'distance': destination_distance_km,
            'trail_level': chain_segment_label,
            'speed_mult': chain_mult,
            'hours': total_hours,
            'landmark': destination_name,
        }],
        'effective_trail_mult': round(chain_mult, 3),
    }
