"""
Shop Utilities — equipment effects, trail bonuses, commander stats.
Old SHOP_CATALOG removed March 2026. All purchases use UPGRADE_CATALOG now.
"""
import logging
from typing import Dict

logger = logging.getLogger(__name__)


# ============================================================================
# TRAIL BUILDING - Scanner bonus from upgrade level
# ============================================================================

def get_scanner_trail_bonus(user_id: int) -> dict:
    """
    Get trail building bonus from scanner upgrade level.
    Higher scanner level = better trail building speed bonus.
    """
    from config_shop import TRAIL_SCANNER_BONUSES_BY_LEVEL
    from utilities.upgrades_utils import get_user_upgrade_level, get_upgrade_stats

    level = get_user_upgrade_level(user_id, 'equipment', 'scanner')
    bonus = TRAIL_SCANNER_BONUSES_BY_LEVEL.get(level, 0.0)
    stats = get_upgrade_stats('equipment', 'scanner', level) or {}
    scanner_name = stats.get('name', 'Scanner') if level > 0 else None

    return {
        'bonus': bonus,
        'bonus_percent': int(bonus * 100),
        'multiplier': 1.0 + bonus,
        'scanner_id': f'scanner_lv{level}' if level > 0 else None,
        'scanner_name': scanner_name,
    }


# ============================================================================
# UPGRADE EFFECTS - Wrappers delegating to upgrades_utils
# ============================================================================

def get_passive_income_source(user_id: int) -> Dict:
    """
    Find which upgrade provides passive income multiplier.
    Reads from power/generator upgrade path in UPGRADE_CATALOG.
    """
    from utilities.upgrades_utils import get_user_upgrade_level, get_upgrade_stats

    level = get_user_upgrade_level(user_id, 'power', 'generator')
    if level < 1:
        return None

    stats = get_upgrade_stats('power', 'generator', level) or {}
    mult = stats.get('passive_income_mult', 1.0)
    if mult <= 1.0:
        return None

    return {
        'id': f'power_generator_lv{level}',
        'name': stats.get('name', f'Generator Lv{level}'),
        'icon': '',
        'mult': mult,
    }


def get_user_upgrade_effects(user_id: int) -> Dict:
    """Wrapper → utilities.upgrades_utils.get_user_upgrade_effects()"""
    from utilities.upgrades_utils import get_user_upgrade_effects as unified_get_effects
    return unified_get_effects(user_id)


def get_suit_stat_bonuses(user_id: int) -> Dict:
    """
    Get EVA Suit stat bonus PERCENTAGES for UI display.
    Returns dict of stat_name -> percentage (e.g., {'exploration': 30, 'leadership': 25, ...})
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
    """
    suit_pct = get_suit_stat_bonuses(user_id)

    def apply_pct(base, pct):
        bonus = round(base * pct / 100)
        return base + bonus, bonus

    result = {}
    for stat in ['leadership', 'strategy', 'exploration', 'logistics', 'charisma']:
        base = base_stats.get(stat, 50)
        pct = suit_pct.get(stat, 0)
        effective, bonus_pts = apply_pct(base, pct)
        result[stat] = effective
        result[f'{stat}_suit_bonus'] = bonus_pts
        result[f'{stat}_suit_pct'] = pct

    return result


# ============================================================================
# USER EQUIPMENT DATA (for Cache/Inventory page)
# ============================================================================

def get_user_equipment_data(user_id: int) -> Dict:
    """
    Get user's owned equipment from UPGRADE_CATALOG for the Depot equipment tab.
    """
    try:
        from utilities.upgrades_utils import get_all_user_upgrades, get_upgrade_stats
        from config_upgrades import UPGRADE_CATALOG

        user_upgrades = get_all_user_upgrades(user_id)
        owned = []

        for category_key, items in UPGRADE_CATALOG.items():
            if category_key == 'vehicles':
                continue  # Vehicles shown separately in Assets tab
            for item_key, item_config in items.items():
                level = user_upgrades.get(category_key, {}).get(item_key, 0)
                if level == 0:
                    continue
                stats = get_upgrade_stats(category_key, item_key, level)
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

        category_order = ['equipment', 'gear', 'power', 'research', 'automation', 'storage', 'infrastructure']
        owned.sort(key=lambda x: (category_order.index(x['category']) if x['category'] in category_order else 99, x.get('cost', 0)))

        return {
            'success': True,
            'owned': owned,
            'available': [],
            'total_spent': 0,
            'total_owned': len(owned),
            'total_available': 0,
        }
    except Exception as e:
        logger.error(f"Failed to get user equipment data: {e}")
        return {'success': False, 'error': str(e)}
