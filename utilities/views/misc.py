"""Miscellaneous view helpers: profile page, recent activity, discovery items."""

import logging

logger = logging.getLogger(__name__)


def build_recent_activity(user_id, limit=10):
    """
    Build combined activity list from assets and transactions.
    Consolidates repeated activity-building logic from app.py.
    """
    from utilities.postgres.shop import get_user_depot_transactions
    from utilities.postgres.assets import get_user_replicate_assets
    from utilities.depot_utils import eth_to_display

    assets = get_user_replicate_assets(user_id, limit=limit)
    transactions = get_user_depot_transactions(user_id, limit=limit)

    activity = [{'type': a['asset_type'], 'timestamp': a['created_at'], 'data': a} for a in assets]
    activity += [{
        'type': 'depot_transaction', 'timestamp': tx['created_at'],
        'data': {
            'purchase_type': tx['purchase_type'],
            'amount_display': eth_to_display(tx['amount_eth']),
            'tx_hash': tx['tx_hash'], 'item_details': tx.get('item_details')
        }
    } for tx in transactions]

    activity.sort(key=lambda x: x['timestamp'], reverse=True)
    return activity[:limit]


def get_profile_page_data(user_id, auth):
    """Get all data needed for colony/profile page - LEGACY, use get_colony_page_data instead."""
    from utilities.postgres.wallets import get_user_sepolia_wallets
    from utilities.postgres.assets import get_user_replicate_assets
    from utilities.depot_utils import get_fast_balance_and_wallet_info
    return {
        'user': auth.get_current_user(),
        'wallets': get_user_sepolia_wallets(user_id),
        'total_balance': get_fast_balance_and_wallet_info(user_id)[0],  # FAST: no blockchain
        'images': get_user_replicate_assets(user_id, asset_type='character_image', limit=50),
        'videos': get_user_replicate_assets(user_id, asset_type='character_video', limit=20)
    }


def get_formatted_discovery_items():
    """Get all discovery items formatted for API response."""
    from utilities.postgres.expeditions import get_all_discovery_items

    items = get_all_discovery_items()
    return {'items': [{
        'id': i['id'], 'item_name': i['item_name'], 'item_type': i['item_type'], 'rarity': i['rarity'],
        'description': i['description'], 'weight_kg': float(i['weight_kg'] or 0), 'stackable': i['stackable'],
        'preferred_mars_features': i['preferred_mars_features'], 'min_distance_km': float(i['min_distance_km'] or 0),
        'max_distance_km': float(i['max_distance_km']) if i['max_distance_km'] else None,
        'base_scientific_value': i['base_scientific_value'], 'base_trade_value_eth': float(i['base_trade_value_eth'] or 0),
        'exploration_enhancement_value': float(i['exploration_enhancement_value'] or 0), 'image_url': i['image_url']
    } for i in items]}
