"""Cumulative upgrade effects aggregator.

Merges player_upgrades + infrastructure effects + tech tree + captain
logistics into one flat effects dict used by expedition / build math.
"""

import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


def get_user_upgrade_effects(user_id: int) -> Dict[str, Any]:
    """
    Calculate all cumulative effects from user's upgrades AND infrastructure.
    Reads from player_upgrades table + UPGRADE_CATALOG.

    Returns a dict of effect_name -> total_value

    Example output:
    {
        'expedition_speed_mult': 2.0,  # From rover level
        'cargo_slots': 8,              # From rover
        'discovery_chance_bonus': 0.35,  # From scanner
        'rare_chance_bonus': 0.10,
        'life_support_cost_mult': 0.85,
        'fuel_cost_mult': 0.8,  # From water_extractor infrastructure
        ...
    }
    """
    from utilities.upgrades.state import get_all_user_upgrades, get_upgrade_stats

    # Initialize with defaults (unified from both upgrade and shop systems)
    effects = {
        # Vehicle/expedition effects
        'expedition_speed_mult': 1.0,
        'cargo_slots': 0,
        'fuel_cost_mult': 1.0,
        'max_range_km': 0,
        'vehicle_range_mult': 1.0,
        'signal_detection_enabled': False,

        # Discovery effects
        'discovery_chance_bonus': 0.0,
        'rare_chance_bonus': 0.0,
        'legendary_chance_bonus': 0.0,
        'discovery_value_mult': 1.0,
        'bio_discovery_value_mult': 1.0,

        # Expedition cost effects
        'life_support_cost_mult': 1.0,

        # Passive income effects
        'passive_income_mult': 1.0,
        'passive_income_base': 0,

        # Captain stat bonuses
        'stat_exploration_bonus': 0,
        'stat_leadership_bonus': 0,
        'stat_strategy_bonus': 0,
        'stat_logistics_bonus': 0,
        'stat_charisma_bonus': 0,

        # Build speed (lower = faster, like cost mults)
        'build_time_mult': 1.0,

        # Boolean flags
        'dust_storm_immune': False,

        # Storage capacity (discovery limit) - default 300, Storage Bunker adds more
        'storage_capacity': 300,
    }

    # Get all user upgrades from new unified system
    user_upgrades = get_all_user_upgrades(user_id)

    # Apply upgrade effects from UPGRADE_CATALOG
    for category, items in user_upgrades.items():
        for item_key, level in items.items():
            if level == 0:
                continue  # Not unlocked

            stats = get_upgrade_stats(category, item_key, level)
            if not stats:
                continue

            # Apply each stat from the level config
            for key, value in stats.items():
                if key in ['name', 'cost', 'image_url', 'build_time_days']:
                    continue  # Skip non-effect fields

                # Map capacity (from Storage Bunker) to storage_capacity
                if key == 'capacity':
                    effects['storage_capacity'] = max(effects.get('storage_capacity', 300), value)
                    continue

                if key not in effects:
                    effects[key] = value
                    continue

                current = effects[key]

                # Multiplicative effects - take the best value
                if key.endswith('_mult'):
                    if 'cost' in key:
                        # Cost mults: lower is better
                        effects[key] = min(current, value)
                    else:
                        # Other mults: higher is better
                        effects[key] = max(current, value)

                # Additive - stack
                elif key.endswith('_bonus') or key.endswith('_base') or key in ['cargo', 'cargo_slots', 'max_range_km']:
                    effects[key] = current + value

                # Boolean flags - OR together
                elif isinstance(value, bool):
                    effects[key] = current or value

    # Map 'cargo' to 'cargo_slots' for backward compat
    if 'cargo' in effects and effects['cargo'] > 0:
        effects['cargo_slots'] = effects.get('cargo_slots', 0) + effects['cargo']

    # Apply infrastructure effects
    try:
        from utilities.infrastructure_utils import get_user_infrastructure_effects
        infra_effects = get_user_infrastructure_effects(user_id)

        for key, value in infra_effects.items():
            if key not in effects:
                effects[key] = value
                continue

            current = effects[key]

            if key.endswith('_mult'):
                if 'cost' in key:
                    effects[key] = current * value  # Stack cost reductions
                else:
                    effects[key] = max(current, value)
            elif key.endswith('_bonus'):
                effects[key] = current + value
            elif isinstance(value, bool):
                effects[key] = current or value

    except ImportError:
        pass

    # Apply tech tree effects (research bonuses)
    try:
        from utilities.tech_utils import get_tech_effects
        tech_effects = get_tech_effects(user_id)

        for key, value in tech_effects.items():
            if key not in effects:
                effects[key] = value
                continue

            current = effects[key]
            if key.endswith('_mult'):
                if 'cost' in key:
                    effects[key] = current * value
                else:
                    effects[key] = current * value
            elif key.endswith('_bonus') or key.endswith('_base') or key in ['cargo_slots']:
                effects[key] = current + value
            elif isinstance(value, bool):
                effects[key] = current or value
    except ImportError:
        pass

    # Captain Logistics stat → build speed bonus
    try:
        from utilities.postgres.assets import get_commander_stats
        stats = get_commander_stats(user_id)
        if stats:
            logistics = stats.get('logistics', 0) or 0
            # Logistics 0 = no bonus, 50 = 10% faster, 100 = 20% faster
            logistics_build_mult = max(0.5, 1.0 - logistics / 500.0)
            effects['build_time_mult'] = effects.get('build_time_mult', 1.0) * logistics_build_mult
    except Exception:
        pass

    return effects
