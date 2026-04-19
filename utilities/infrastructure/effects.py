"""Infrastructure effect aggregation for the user's active buildings."""
from config_infrastructure import INFRASTRUCTURE_CATALOG
from utilities.postgres.shop import get_user_infrastructure


def get_user_infrastructure_effects(user_id: int) -> dict:
    """
    Calculate all effects from user's active infrastructure at their current levels.
    Uses level-based effects from INFRASTRUCTURE_CATALOG.

    NOTE: Expedition slots = min(vehicles owned, habitat expedition_capacity).
    Habitat module Lv1-3=1-2 slots, Lv4-5=3, Lv6-7=4, Lv8-9=5, Lv10=6.
    Default 3 slots if no habitat module built.
    """
    from utilities.upgrades_utils import get_all_infrastructure_levels

    structures = get_user_infrastructure(user_id)
    active_types = {s['structure_type'] for s in structures if s['status'] == 'active'}

    all_levels = get_all_infrastructure_levels(user_id, structures=structures)

    effects = {}

    def apply_effect(key, value):
        if key not in effects:
            effects[key] = value
            return
        current = effects[key]
        if key.endswith('_mult'):
            if 'cost' in key:
                effects[key] = min(current, value)
            else:
                effects[key] = max(current, value)
        elif key.endswith('_bonus') or key.endswith('_base') or key.endswith('_rate'):
            effects[key] = current + value
        elif isinstance(value, bool):
            effects[key] = current or value
        else:
            effects[key] = value

    for building_type in active_types:
        level = all_levels.get(building_type, 1)
        if level < 1:
            continue

        catalog = INFRASTRUCTURE_CATALOG.get(building_type, {})
        level_data = catalog.get('levels', {}).get(level, {})

        for key, value in level_data.items():
            if key in ['name', 'cost', 'build_time_days', 'image_url', 'generation_rate', 'science_generation_rate']:
                continue

            if key == 'fuel_cost_reduction':
                apply_effect('fuel_cost_mult', 1.0 - value)
            elif key == 'life_support_reduction':
                apply_effect('life_support_cost_mult', 1.0 - value)
            elif key == 'night_generation':
                apply_effect('night_generation_mult', value)
            elif key == 'discovery_bonus':
                apply_effect('discovery_chance_bonus', value)
            elif key == 'discovery_value_mult':
                apply_effect('discovery_value_mult', value)
            elif key == 'bio_value_mult':
                apply_effect('bio_discovery_value_mult', value)
            elif key == 'all_generation_mult':
                apply_effect('all_generation_mult', value)
            elif key == 'dust_storm_immune':
                apply_effect('dust_storm_immune', value)
            elif key == 'legendary_discovery_chance':
                apply_effect('legendary_chance_bonus', value)
            elif key == 'expedition_capacity':
                apply_effect('expedition_capacity', value)
            elif key == 'research_enabled':
                apply_effect('research_enabled', value)
            elif key.startswith('stat_') and key.endswith('_bonus'):
                # Bug #1270 Phase 6: end-game buildings grant captain stat bonuses at L5+
                apply_effect(key, value)

    total_sepolia_rate = 0.0
    for structure in structures:
        if structure['status'] == 'active' and structure.get('generates_resource') == 'sepolia':
            total_sepolia_rate += float(structure.get('generation_rate', 0))

    if total_sepolia_rate > 0:
        effects['sepolia_generation_rate'] = total_sepolia_rate

    return effects
