"""Expedition JSON formatters — Decimal/date → plain types for API responses."""

from utilities.postgres.expeditions import (
    get_user_expedition_history,
    get_expedition_by_id,
    get_expedition_discovery_items,
)


def get_expedition_history_payload(user_id: int, limit: int = 50, offset: int = 0) -> dict:
    """Full payload for /api/expeditions/history — fetch + format."""
    limit = min(limit, 100)
    result = get_user_expedition_history(user_id, limit=limit, offset=offset)
    multi_visits = result.get('multi_visits', {})

    formatted = []
    for exp in result['expeditions']:
        duration_hours = float(exp['duration_seconds'] or 0) / 3600
        formatted.append({
            'id': exp['id'],
            'destination': exp['destination_name'],
            'type': exp['destination_type'],
            'distance_km': float(exp['distance_km'] or 0),
            'lat': float(exp['destination_lat'] or 0),
            'lon': float(exp['destination_lon'] or 0),
            'departed_at': (exp['departed_at'].isoformat() + 'Z') if exp['departed_at'] else None,
            'completed_at': (exp['completed_at'].isoformat() + 'Z') if exp['completed_at'] else None,
            'duration_hours': round(duration_hours, 1),
            'cost': round(float(exp['sepolia_cost'] or 0) * 10000000, 1),
            'sepolia_earned': round(float(exp['sepolia_earned'] or 0) * 10000000, 1),
            'discovery_count': exp['discovery_count'] or 0,
            'claimed_count': exp['claimed_count'] or 0,
            'total_extracted': round(float(exp['total_extracted'] or 0), 1),
            'link': exp['destination_link'],
            'common': exp.get('common_count', 0) or 0,
            'uncommon': exp.get('uncommon_count', 0) or 0,
            'rare': exp.get('rare_count', 0) or 0,
            'legendary': exp.get('legendary_count', 0) or 0,
            'scientific_value': int(exp.get('total_scientific_value', 0) or 0),
            'visit_count': multi_visits.get(exp['destination_name'], 1),
        })

    return {
        'success': True,
        'expeditions': formatted,
        'total_count': result['total_count'],
        'limit': result['limit'],
        'offset': result['offset'],
        'multi_visits': multi_visits,
    }


def get_expedition_items_payload(user_id: int, expedition_id: int) -> tuple[dict, int]:
    """Full payload for /api/expeditions/<id>/items — fetch + format.

    Returns (payload, status_code).
    """
    expedition = get_expedition_by_id(expedition_id)
    if not expedition or expedition['user_id'] != user_id:
        return {'success': False, 'error': 'Expedition not found'}, 404

    discoveries = get_expedition_discovery_items(expedition_id)
    formatted = []
    for d in discoveries:
        quantity = d['quantity'] or 1
        scientific_value = int(d.get('base_scientific_value') or 0) * quantity
        formatted.append({
            'id': d['id'],
            'item_name': d['item_name'],
            'rarity': d['rarity'],
            'description': d['description'],
            'item_type': d['item_type'],
            'image_url': d['image_url'],
            'found_at_km': float(d['found_at_km'] or 0),
            'nearby_feature': d['nearby_feature'],
            'base_value': float(d['base_value'] or 0),
            'enhanced_value': float(d['enhanced_value'] or 0),
            'quantity': quantity,
            'claimed': d['claimed_by_user'] or False,
            'analyzed': d['analyzed'] or False,
            'scientific_value': scientific_value,
        })

    return {
        'success': True,
        'expedition_id': expedition_id,
        'destination': expedition['destination_name'],
        'discoveries': formatted,
    }, 200
