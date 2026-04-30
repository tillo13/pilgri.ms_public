"""Expedition haul celebration modal — full discovery data for completed/recalled expeditions."""

import logging
from utilities.postgres.core import db_cursor

logger = logging.getLogger(__name__)


def build_expedition_haul(user_id: int, expedition_id: int) -> dict:
    """Return full haul payload for the celebration modal, or an error dict.

    Side effects: unlocks distance-gated discoveries on completed/recalled expeditions,
    and stamps notified_at on completed expeditions so they stop showing as "new return".
    """
    from utilities.postgres.expeditions import (
        get_expedition_by_id,
        get_expedition_discoveries,
        unlock_discoveries_by_distance,
        calculate_expedition_sv,
    )
    from utilities.depot_utils import eth_to_display

    expedition = get_expedition_by_id(expedition_id)
    if not expedition or expedition['user_id'] != user_id:
        return {'success': False, 'error': 'Unauthorized'}

    destination_image = None
    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT image_url FROM pilgrim.mars_mappings WHERE name = %s LIMIT 1",
                (expedition['destination_name'],))
            row = cur.fetchone()
            if row:
                destination_image = row.get('image_url')
    except Exception as e:
        logger.warning(f"Could not fetch destination image: {e}")

    # Unlock discoveries for any expedition whose return_arrives_at has passed,
    # not just ones already flipped to status='complete'. The dashboard fleet
    # card surfaces the "RETURNED!" UI based on now >= return_arrives_at, so
    # the modal must align — otherwise captains see "0 discoveries" on a
    # vehicle they can clearly see has returned.
    from datetime import datetime as _dt
    now_utc = _dt.utcnow()
    return_arrives_at = expedition.get('return_arrives_at') or expedition.get('arrives_at')
    has_arrived = bool(return_arrives_at and now_utc >= return_arrives_at)
    if expedition['status'] in ('complete', 'recalled') or has_arrived:
        unlock_discoveries_by_distance(expedition_id, float(expedition['distance_km']))

    discoveries = get_expedition_discoveries(expedition_id, unlocked_only=True)

    # Travel time — clamp to 0 so corrupted timestamps (arrives_at < departed_at
    # from a TZ-skewed launch path) never render as "-318 minutes". Prefer the
    # actual completed_at delta when available; otherwise use the planned
    # round-trip arrives_at.
    travel_hours = 0.0
    if expedition.get('departed_at') and expedition.get('completed_at'):
        travel_hours = max(0.0, (expedition['completed_at'] - expedition['departed_at']).total_seconds() / 3600)
    elif expedition.get('departed_at') and expedition.get('arrives_at'):
        travel_hours = max(0.0, (expedition['arrives_at'] - expedition['departed_at']).total_seconds() / 3600)

    formatted = [{
        'id': d.get('id'), 'item_name': d.get('item_name'), 'rarity': d.get('rarity', 'common'),
        'image_url': d.get('image_url'), 'description': d.get('description'),
        'enhanced_value': float(d.get('enhanced_value') or d.get('scientific_value') or 0),
        'claimed': d.get('claimed_by_user', False), 'item_type': d.get('item_type')
    } for d in discoveries]

    shards_display = eth_to_display(float(expedition.get('sepolia_earned') or 0))
    distance = float(expedition['distance_km'])
    sv_earned = calculate_expedition_sv(distance)

    if expedition['status'] == 'complete' and not expedition.get('notified_at'):
        try:
            with db_cursor(commit=True) as cur:
                cur.execute(
                    "UPDATE pilgrim.expeditions SET notified_at = NOW() WHERE id = %s",
                    (expedition_id,))
        except Exception:
            pass

    return {
        'success': True,
        'expedition': {
            'id': expedition_id, 'destination': expedition['destination_name'],
            'destination_type': expedition.get('destination_type'), 'destination_image': destination_image,
            'distance_km': distance, 'vehicle_type': expedition.get('vehicle_type', 'rover'),
            'shards_earned': shards_display, 'sv_earned': sv_earned,
            'travel_hours': round(travel_hours, 1), 'status': expedition['status']
        },
        'discoveries': formatted,
        'unclaimed_count': sum(1 for d in formatted if not d['claimed'])
    }
