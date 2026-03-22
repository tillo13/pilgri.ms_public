"""
Shop Utilities - Equipment purchases, upgrade effects, and shopping list
Handles all shop-related business logic for the Pilgrims game
"""
import logging
from typing import Dict, List, Optional, Any
from config import SHOP_CATALOG, SHOP_CATEGORIES, get_shop_item
from utilities.postgres_utils import (
    get_user_upgrades,
    get_user_upgrade_count,
    add_user_upgrade,
    get_user_primary_sepolia_wallet,
    update_sepolia_wallet_balance,
    create_depot_transaction
)
from utilities.depot_utils import eth_to_display, display_to_eth
from utilities.sepolia_utils import MarsAsteroidMiner, sanitize_tx_error

logger = logging.getLogger(__name__)

# ============================================================================
# UPGRADE AVAILABILITY
# ============================================================================

def get_user_owned_items(user_id: int) -> Dict[str, int]:
    """Get dict of item_id -> quantity for all items user owns"""
    upgrades = get_user_upgrades(user_id)
    return {u['item_id']: u['quantity'] for u in upgrades}


def get_scanner_trail_bonus(user_id: int) -> dict:
    """
    Get trail building bonus from owned scanners.
    Takes BEST scanner owned (not stacking) - higher tier = better bonus.
    """
    from config import TRAIL_SCANNER_BONUSES, SHOP_CATALOG

    owned = get_user_owned_items(user_id)

    # Find best scanner owned (highest bonus wins)
    best_bonus = 0.0
    best_scanner = None

    for scanner_id, bonus in TRAIL_SCANNER_BONUSES.items():
        if owned.get(scanner_id, 0) > 0 and bonus > best_bonus:
            best_bonus = bonus
            best_scanner = scanner_id

    scanner_name = None
    if best_scanner:
        item = SHOP_CATALOG.get(best_scanner, {})
        scanner_name = item.get('name', best_scanner)

    return {
        'bonus': best_bonus,
        'bonus_percent': int(best_bonus * 100),
        'multiplier': 1.0 + best_bonus,
        'scanner_id': best_scanner,
        'scanner_name': scanner_name
    }


def check_requirements_met(item_id: str, owned_items: Dict[str, int]) -> tuple:
    """
    Check if user meets requirements to purchase an item
    Returns (can_buy: bool, missing_requirements: list)
    """
    item = get_shop_item(item_id)
    if not item:
        return False, ['Item not found']

    requirements = item.get('requirements', [])
    missing = []

    for req_id in requirements:
        if owned_items.get(req_id, 0) < 1:
            req_item = get_shop_item(req_id)
            req_name = req_item['name'] if req_item else req_id
            missing.append(req_name)

    return len(missing) == 0, missing

def check_max_owned(item_id: str, owned_items: Dict[str, int]) -> tuple:
    """
    Check if user has reached max ownership for an item
    Returns (can_buy_more: bool, current_owned: int, max_allowed: int)
    """
    item = get_shop_item(item_id)
    if not item:
        return False, 0, 0

    max_owned = item.get('max_owned', 1)
    current_owned = owned_items.get(item_id, 0)

    return current_owned < max_owned, current_owned, max_owned

def get_item_availability(item_id: str, user_id: int, user_balance: float) -> Dict:
    """
    Get full availability status for an item
    Returns dict with can_afford, requirements_met, can_buy_more, etc.
    """
    item = get_shop_item(item_id)
    if not item:
        return {'exists': False}

    owned_items = get_user_owned_items(user_id)
    cost = item['cost_display']

    can_afford = user_balance >= cost
    reqs_met, missing_reqs = check_requirements_met(item_id, owned_items)
    can_buy_more, current_owned, max_owned = check_max_owned(item_id, owned_items)

    can_purchase = can_afford and reqs_met and can_buy_more
    shortfall = max(0, cost - user_balance)

    return {
        'exists': True,
        'item': item,
        'cost': cost,
        'can_afford': can_afford,
        'shortfall': shortfall,
        'requirements_met': reqs_met,
        'missing_requirements': missing_reqs,
        'can_buy_more': can_buy_more,
        'current_owned': current_owned,
        'max_owned': max_owned,
        'can_purchase': can_purchase,
        'reason': _get_unavailable_reason(can_afford, reqs_met, can_buy_more, missing_reqs, current_owned, max_owned)
    }

def _get_unavailable_reason(can_afford, reqs_met, can_buy_more, missing_reqs, current, max_owned):
    """Get human-readable reason why item can't be purchased"""
    if not can_buy_more:
        return f"Already own maximum ({current}/{max_owned})"
    if not reqs_met:
        return f"Requires: {', '.join(missing_reqs)}"
    if not can_afford:
        return "Insufficient Shards"
    return None

# ============================================================================
# SHOP CATALOG FOR UI
# ============================================================================

def get_shop_catalog_for_user(user_id: int, user_balance: float) -> Dict:
    """
    Get full shop catalog organized by category with availability info
    Perfect for rendering the shop UI. Includes build status for owned items.
    """
    from config import get_build_time_seconds

    # Get all upgrades with status info
    all_upgrades = get_user_upgrades(user_id)
    owned_items = {u['item_id']: u['quantity'] for u in all_upgrades}
    status_map = {u['item_id']: u for u in all_upgrades}

    categories = {}
    for cat_id, cat_info in sorted(SHOP_CATEGORIES.items(), key=lambda x: x[1]['order']):
        categories[cat_id] = {
            'name': cat_info['name'],
            'icon': cat_info['icon'],
            'items': []
        }

    for item_id, item in SHOP_CATALOG.items():
        category = item['category']

        cost = item['cost_display']
        can_afford = user_balance >= cost
        reqs_met, missing_reqs = check_requirements_met(item_id, owned_items)
        can_buy_more, current_owned, max_owned = check_max_owned(item_id, owned_items)

        # Get build status if owned
        upgrade_info = status_map.get(item_id, {})
        status = upgrade_info.get('status', 'active') if current_owned > 0 else None
        ready_at = upgrade_info.get('ready_at')
        seconds_remaining = 0
        if status == 'building' and ready_at:
            from datetime import datetime
            now = datetime.now()
            if ready_at > now:
                seconds_remaining = int((ready_at - now).total_seconds())

        item_data = {
            'id': item_id,
            'name': item['name'],
            'icon': item['icon'],
            'cost': cost,
            'description': item['description'],
            'effects': item['effects'],
            'requirements': item.get('requirements', []),
            'image_url': item.get('image_url'),
            'can_afford': can_afford,
            'shortfall': max(0, cost - user_balance),
            'requirements_met': reqs_met,
            'missing_requirements': missing_reqs,
            'can_buy_more': can_buy_more,
            'current_owned': current_owned,
            'max_owned': max_owned,
            'can_purchase': can_afford and reqs_met and can_buy_more,
            'owned': current_owned > 0,
            'status': status,
            'ready_at': ready_at.isoformat() if ready_at else None,
            'seconds_remaining': seconds_remaining,
            'build_time_seconds': get_build_time_seconds(cost)
        }

        if category in categories:
            categories[category]['items'].append(item_data)

    # Sort items within each category by cost
    for cat in categories.values():
        cat['items'].sort(key=lambda x: x['cost'])

    return categories

# ============================================================================
# SHOPPING LIST (for emails and "what can I buy" UI)
# ============================================================================

def get_shopping_list(user_id: int, user_balance: float) -> Dict:
    """
    Generate a "shopping list" showing what user can afford vs saving toward
    Great for engagement emails!

    Returns:
        {
            'ready_now': [...items user can buy right now...],
            'almost_there': [...items within 20% of affording...],
            'saving_toward': [...next tier of items to work toward...]
        }
    """
    owned_items = get_user_owned_items(user_id)

    ready_now = []
    almost_there = []
    saving_toward = []

    for item_id, item in SHOP_CATALOG.items():
        cost = item['cost_display']
        reqs_met, missing_reqs = check_requirements_met(item_id, owned_items)
        can_buy_more, current_owned, max_owned = check_max_owned(item_id, owned_items)

        # Skip items user already maxed out
        if not can_buy_more:
            continue

        # Skip items with unmet requirements (unless requirement is also affordable)
        if not reqs_met:
            # Check if this is a "next step" item where req is affordable
            all_reqs_affordable = all(
                SHOP_CATALOG.get(r, {}).get('cost_display', float('inf')) <= user_balance
                for r in item.get('requirements', [])
            )
            if not all_reqs_affordable:
                continue

        shortfall = max(0, cost - user_balance)
        percent_affordable = (user_balance / cost * 100) if cost > 0 else 100

        item_info = {
            'id': item_id,
            'name': item['name'],
            'icon': item['icon'],
            'cost': cost,
            'shortfall': shortfall,
            'percent_affordable': round(percent_affordable, 1),
            'description': item['description'],
            'requirements_met': reqs_met,
            'missing_requirements': missing_reqs
        }

        if user_balance >= cost and reqs_met:
            ready_now.append(item_info)
        elif percent_affordable >= 80:  # Within 20% of affording
            almost_there.append(item_info)
        elif percent_affordable >= 30:  # At least 30% there
            saving_toward.append(item_info)

    # Sort each list by cost
    ready_now.sort(key=lambda x: x['cost'])
    almost_there.sort(key=lambda x: x['shortfall'])  # Closest first
    saving_toward.sort(key=lambda x: x['cost'])

    return {
        'ready_now': ready_now[:5],  # Top 5 affordable
        'almost_there': almost_there[:3],  # Top 3 almost affordable
        'saving_toward': saving_toward[:3],  # Top 3 goals
        'balance': user_balance,
        'total_available': len(ready_now)
    }

# ============================================================================
# PURCHASE PROCESSING
# ============================================================================

def purchase_shop_item(user_id: int, item_id: str) -> Dict:
    """
    Process a shop item purchase
    - Validates availability
    - Executes blockchain transaction
    - Records purchase in database
    - Returns result
    """
    item = get_shop_item(item_id)
    if not item:
        return {'success': False, 'error': 'Item not found'}

    # =========================================================================
    # DEPRECATION CHECK: SHOP_CATALOG is deprecated, all items blocked
    # New purchases should use UPGRADE_CATALOG via /api/upgrade endpoint
    # This check ensures no new shop purchases while keeping existing data intact
    # =========================================================================
    return {
        'success': False,
        'error': 'Shop items have been retired. Please use the Upgrades tab for equipment improvements.',
        'deprecated': True,
        'redirect': '/depot?tab=upgrades'
    }

    # Legacy code below - kept for reference but unreachable
    # Get wallet and balance
    wallet = get_user_primary_sepolia_wallet(user_id)
    if not wallet:
        return {'success': False, 'error': 'No wallet found'}

    miner = MarsAsteroidMiner()
    if not miner.connect():
        return {'success': False, 'error': 'Network unavailable'}

    balance_eth = miner.get_live_wallet_balance(
        wallet['wallet_address'],
        fallback_balance=wallet.get('current_balance_eth', 0)
    )
    user_balance = eth_to_display(balance_eth)

    # Check availability
    availability = get_item_availability(item_id, user_id, user_balance)
    if not availability['can_purchase']:
        return {'success': False, 'error': availability['reason']}

    cost_display = item['cost_display']
    cost_eth = display_to_eth(cost_display)

    # Execute transaction
    try:
        tx_result = miner.return_to_hub(
            from_address=wallet['wallet_address'],
            from_private_key=wallet['wallet_private_key'],
            amount_eth=cost_eth,
            reason=f"Purchase: {item['name']}"
        )

        if not tx_result['success']:
            return {'success': False, 'error': sanitize_tx_error(tx_result.get('error', ''))}

        # Update wallet balance
        new_balance_eth = balance_eth - cost_eth
        update_sepolia_wallet_balance(wallet['wallet_address'], new_balance_eth)

        # Record upgrade ownership
        add_user_upgrade(user_id, item_id, tx_result['tx_hash'])

        # Record transaction
        create_depot_transaction(
            user_id=user_id,
            wallet_address=wallet['wallet_address'],
            purchase_type='shop_upgrade',
            amount_eth=cost_eth,
            tx_hash=tx_result['tx_hash'],
            etherscan_url=tx_result['etherscan_url'],
            item_details={
                'item_id': item_id,
                'item_name': item['name'],
                'category': item['category']
            }
        )

        # Get build time for response
        from config import get_build_time_seconds
        build_seconds = get_build_time_seconds(cost_display)

        # Update activity timestamp for ARIA photo generation
        from utilities.postgres_utils import update_user_activity
        update_user_activity(user_id)

        logger.info(f"Shop purchase: {item['name']} by user {user_id} for {cost_display} Shards, build time {build_seconds}s")

        return {
            'success': True,
            'item': item,
            'new_balance': eth_to_display(new_balance_eth),
            'tx_hash': tx_result['tx_hash'],
            'etherscan_url': tx_result['etherscan_url'],
            'build_time_seconds': build_seconds,
            'status': 'building'
        }

    except Exception as e:
        logger.error(f"Shop purchase failed: {e}")
        return {'success': False, 'error': str(e)}

# ============================================================================
# UPGRADE EFFECTS - Calculate cumulative bonuses from all owned upgrades
# ============================================================================

def get_passive_income_source(user_id: int) -> Dict:
    """
    Find which item is providing the highest passive_income_mult bonus.
    Returns dict with item name, icon, and multiplier value.
    Only counts active (completed) builds.
    """
    from utilities.postgres_utils import get_user_upgrades
    owned_items = get_user_upgrades(user_id, active_only=True)

    best_item = None
    best_mult = 1.0

    for upgrade in owned_items:
        item_id = upgrade['item_id']
        item = get_shop_item(item_id)
        if not item:
            continue

        mult = item.get('effects', {}).get('passive_income_mult', 1.0)
        if mult > best_mult:
            best_mult = mult
            best_item = {
                'id': item_id,
                'name': item['name'],
                'icon': item.get('icon', '⚡'),
                'mult': mult
            }

    return best_item


def get_user_upgrade_effects(user_id: int) -> Dict:
    """
    DEPRECATED: Use utilities.upgrades_utils.get_user_upgrade_effects() instead.

    This is a thin wrapper for backward compatibility. The unified version in
    upgrades_utils.py reads from UPGRADE_CATALOG (10-level paths) + infrastructure + tech tree.
    """
    from utilities.upgrades_utils import get_user_upgrade_effects as unified_get_effects
    return unified_get_effects(user_id)

def get_suit_stat_bonuses(user_id: int) -> Dict:
    """
    Get EVA Suit stat bonus PERCENTAGES for UI display.
    Returns dict of stat_name -> percentage (e.g., {'exploration': 30, 'leadership': 25, ...})
    These are percentages that multiply base stats.
    """
    effects = get_user_upgrade_effects(user_id)
    return {
        'exploration': effects.get('stat_exploration_bonus', 0),
        'leadership': effects.get('stat_leadership_bonus', 0),
        'strategy': effects.get('stat_strategy_bonus', 0),
        'logistics': effects.get('stat_logistics_bonus', 0),
        'charisma': effects.get('stat_charisma_bonus', 0),
    }


def get_effective_commander_stats(user_id: int, base_stats: Dict) -> Dict:
    """
    Apply EVA Suit bonuses as PERCENTAGES to commander stats.
    A captain with 60 exploration and +10% bonus gets 60 * 1.10 = 66.
    Returns modified stats dict with bonus breakdown.
    """
    suit_pct = get_suit_stat_bonuses(user_id)

    def apply_pct(base, pct):
        """Apply percentage bonus, return (effective, bonus_points)"""
        bonus = round(base * pct / 100)
        return base + bonus, bonus

    result = {}
    for stat in ['leadership', 'strategy', 'exploration', 'logistics', 'charisma']:
        base = base_stats.get(stat, 50)
        pct = suit_pct.get(stat, 0)
        effective, bonus_pts = apply_pct(base, pct)
        result[stat] = effective
        result[f'{stat}_suit_bonus'] = bonus_pts  # For UI display
        result[f'{stat}_suit_pct'] = pct  # Percentage for UI

    return result

# ============================================================================
# EMAIL HELPERS
# ============================================================================

def format_shopping_list_for_email(user_id: int, user_balance: float) -> str:
    """
    Format shopping list as plain text for email
    """
    shopping = get_shopping_list(user_id, user_balance)

    lines = []
    lines.append(f"Your balance: {user_balance:.1f} Shards\n")

    if shopping['ready_now']:
        lines.append("Ready to purchase:")
        for item in shopping['ready_now']:
            lines.append(f"  {item['icon']} {item['name']} - {item['cost']:.0f} Shards")
        lines.append("")

    if shopping['almost_there']:
        lines.append("Almost there:")
        for item in shopping['almost_there']:
            lines.append(f"  {item['icon']} {item['name']} - need {item['shortfall']:.0f} more ({item['percent_affordable']:.0f}% saved)")
        lines.append("")

    if shopping['saving_toward']:
        lines.append("Saving toward:")
        for item in shopping['saving_toward']:
            lines.append(f"  {item['icon']} {item['name']} - {item['cost']:.0f} Shards ({item['percent_affordable']:.0f}% saved)")

    return "\n".join(lines)


# ============================================================================
# USER EQUIPMENT DATA (for Cache/Inventory page)
# ============================================================================

def get_user_equipment_data(user_id: int) -> Dict:
    """
    Get user's owned equipment and available upgrades for the profile/cache page.
    Returns owned items with full details, build status, and stats on what's available.
    """
    try:
        # Get all upgrades with status info
        all_upgrades = get_user_upgrades(user_id)  # Includes status, ready_at
        owned_items = {u['item_id']: u['quantity'] for u in all_upgrades}
        status_map = {u['item_id']: u for u in all_upgrades}  # Full upgrade info

        owned = []
        available = []
        total_spent = 0

        for item_id, item in SHOP_CATALOG.items():
            quantity = owned_items.get(item_id, 0)

            if quantity > 0:
                # User owns this item - include build status
                upgrade_info = status_map.get(item_id, {})
                status = upgrade_info.get('status', 'active')
                ready_at = upgrade_info.get('ready_at')

                # Calculate seconds remaining if building
                seconds_remaining = 0
                if status == 'building' and ready_at:
                    from datetime import datetime
                    now = datetime.now()
                    if ready_at > now:
                        seconds_remaining = int((ready_at - now).total_seconds())

                owned.append({
                    'id': item_id,
                    'name': item['name'],
                    'icon': item['icon'],
                    'category': item['category'],
                    'description': item['description'],
                    'cost': item['cost_display'],
                    'quantity': quantity,
                    'max_owned': item.get('max_owned', 1),
                    'effects': item.get('effects', {}),
                    'image_url': item.get('image_url'),
                    'status': status,
                    'ready_at': ready_at.isoformat() if ready_at else None,
                    'seconds_remaining': seconds_remaining
                })
                total_spent += item['cost_display'] * quantity
            else:
                # User doesn't own - check if available
                reqs_met, _ = check_requirements_met(item_id, owned_items)
                can_buy_more, _, max_owned = check_max_owned(item_id, owned_items)

                if can_buy_more:
                    available.append({
                        'id': item_id,
                        'name': item['name'],
                        'icon': item['icon'],
                        'category': item['category'],
                        'cost': item['cost_display'],
                        'requirements_met': reqs_met
                    })

        # Include upgrade catalog equipment (scanner, cargo, life_support, generator, suit)
        # These are in the NEW upgrade system, not the old SHOP_CATALOG
        try:
            from utilities.upgrades_utils import get_all_user_upgrades, get_upgrade_stats
            from config_upgrades import UPGRADE_CATALOG
            user_upgrades = get_all_user_upgrades(user_id)
            for category_key, items in UPGRADE_CATALOG.items():
                if category_key == 'vehicles':
                    continue  # Vehicles shown separately in Assets tab
                for item_key, item_config in items.items():
                    level = user_upgrades.get(category_key, {}).get(item_key, 0)
                    if level == 0:
                        continue
                    stats = get_upgrade_stats(category_key, item_key, level)
                    # Build effects dict from stats (exclude meta fields)
                    effects = {k: v for k, v in (stats or {}).items()
                               if k not in ('name', 'cost', 'image_url', 'build_time_days')}
                    owned.append({
                        'id': f'{category_key}_{item_key}',
                        'name': f"{item_config['name']} Lv{level}",
                        'icon': item_config.get('icon', ''),
                        'category': category_key,
                        'description': item_config.get('description', ''),
                        'cost': stats.get('cost', 0) if stats else 0,
                        'quantity': 1,
                        'max_owned': 1,
                        'effects': effects,
                        'image_url': stats.get('image_url') if stats else None,
                        'status': 'active',
                        'ready_at': None,
                        'seconds_remaining': 0,
                        'level': level,
                        'level_name': stats.get('name', f'Lv{level}') if stats else f'Lv{level}',
                    })
        except Exception as e:
            logger.warning(f"Failed to add upgrade catalog equipment: {e}")

        # Sort owned by category then cost
        category_order = ['rover', 'scanner', 'cargo', 'power', 'research', 'survival', 'suit', 'drone', 'equipment', 'storage']
        owned.sort(key=lambda x: (category_order.index(x['category']) if x['category'] in category_order else 99, x.get('cost', 0)))

        return {
            'success': True,
            'owned': owned,
            'available': available,
            'total_spent': total_spent,
            'total_owned': len(owned),
            'total_available': len(available)
        }
    except Exception as e:
        logger.error(f"Failed to get user equipment data: {e}")
        return {'success': False, 'error': str(e)}
