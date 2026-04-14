"""
Multi-segment travel time for expeditions.

Long journeys compound intermediate trail bonuses: if a highway trail exists
at 50km and the destination is 500km away, the first 50km uses highway speed
and the remainder uses the destination trail speed.

Pure orchestration — no mutations. Reads trails + base coords from the DB.
"""

import logging

from utilities.expeditions.config import BASE_SPEED_KM_PER_HOUR
from utilities.db_trails import (
    TRAIL_SPEED_MULTIPLIERS,
    get_trail_speed_mult_for_destination,
)

logger = logging.getLogger(__name__)


def _single_segment(distance_km, base_speed_mult, trail_info):
    """Fallback: whole journey as one segment at the destination trail speed."""
    trail_mult = trail_info['speed_mult']
    hours = distance_km / (BASE_SPEED_KM_PER_HOUR * base_speed_mult * trail_mult)
    return {
        'total_hours': hours,
        'segments': [{
            'distance': distance_km,
            'trail_level': trail_info.get('trail_level', 'none'),
            'speed_mult': trail_mult,
            'hours': hours,
        }],
        'effective_trail_mult': trail_mult,
        'trail_info': trail_info,
    }


def calculate_segmented_travel_time(
    user_id: int,
    destination_distance_km: float,
    destination_name: str,
    base_speed_mult: float,
    base_coords: dict = None,
) -> dict:
    """
    Travel time using trail-segment compounding.

    Returns dict with total_hours, segments[], effective_trail_mult (weighted avg).
    """
    from utilities.postgres_utils import db_cursor  # local: avoid top-level cycle

    try:
        with db_cursor() as cur:
            if not base_coords:
                cur.execute(
                    "SELECT home_mars_lat, home_mars_lon FROM pilgrim.users WHERE id = %s",
                    (user_id,),
                )
                user = cur.fetchone()
                if user and user['home_mars_lat']:
                    base_coords = {
                        'latitude': float(user['home_mars_lat']),
                        'longitude': float(user['home_mars_lon']),
                    }

            if not base_coords:
                # No base coords → can't segment, fall back to simple calc
                trail_info = get_trail_speed_mult_for_destination(
                    user_id, destination_name, destination_distance_km
                )
                return _single_segment(destination_distance_km, base_speed_mult, trail_info)

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
        trail_info = get_trail_speed_mult_for_destination(
            user_id, destination_name, destination_distance_km
        )
        return _single_segment(destination_distance_km, base_speed_mult, trail_info)

    intermediate_trails = [
        t for t in trails_with_distance
        if float(t['distance_km']) < destination_distance_km
    ]

    dest_trail_info = get_trail_speed_mult_for_destination(
        user_id, destination_name, destination_distance_km
    )
    dest_trail_mult = dest_trail_info['speed_mult']

    if not intermediate_trails:
        return _single_segment(destination_distance_km, base_speed_mult, dest_trail_info)

    segments = []
    current_distance = 0
    total_hours = 0

    for trail in intermediate_trails:
        trail_dist = float(trail['distance_km'])
        trail_mult = TRAIL_SPEED_MULTIPLIERS.get(trail['trail_level'], 1.0)

        segment_distance = trail_dist - current_distance
        if segment_distance > 0:
            best_mult = max(trail_mult, segments[-1]['speed_mult'] if segments else 1.0)
            segment_hours = segment_distance / (BASE_SPEED_KM_PER_HOUR * base_speed_mult * best_mult)
            segments.append({
                'distance': segment_distance,
                'trail_level': trail['trail_level'],
                'speed_mult': best_mult,
                'hours': segment_hours,
                'landmark': trail['destination_name'],
            })
            total_hours += segment_hours
            current_distance = trail_dist

    final_distance = destination_distance_km - current_distance
    if final_distance > 0:
        final_hours = final_distance / (BASE_SPEED_KM_PER_HOUR * base_speed_mult * dest_trail_mult)
        segments.append({
            'distance': final_distance,
            'trail_level': dest_trail_info.get('trail_level', 'none'),
            'speed_mult': dest_trail_mult,
            'hours': final_hours,
            'landmark': destination_name,
        })
        total_hours += final_hours

    if total_hours > 0:
        weighted_mult = sum(s['speed_mult'] * s['hours'] for s in segments) / total_hours
    else:
        weighted_mult = dest_trail_mult

    return {
        'total_hours': total_hours,
        'segments': segments,
        'effective_trail_mult': round(weighted_mult, 2),
    }
