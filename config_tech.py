"""
Tech tree configuration - 4 branches × 5 techs each, with branch-wide 10-level progression.

Design:
- Each branch has 5 distinct techs (Tier 1, 2, 3)
- Players research each tech one at a time
- Once ALL 5 techs in a branch are complete → branch advances to next level
- At Level 2+, all 5 techs get new icons and names with suffix (II, III, etc.)
- Costs scale by 1.12x per branch level
- Research times increase with branch level

Total per branch at Level 1: ~59,000 SV
Total all branches at Level 1: ~236,000 SV
"""

##############################################################################
# SCIENTIST SPECIALIZATIONS
##############################################################################

SCIENTIST_BRANCHES = {
    'exploration': ['bo', 'millie', 'luke'],
    'vehicles': ['don', 'tom', 'mra'],
    'power': ['emanuel', 'debra', 'heather'],
    'extraction': ['anna', 'tanner', 'lilla', 'andy', 'clover'],
}

SCIENTIST_SECONDARY_BRANCHES = {
    'bo': 'power',
    'millie': 'vehicles',
    'luke': 'extraction',
    'don': 'power',
    'tom': 'exploration',
    'mra': 'extraction',
    'emanuel': 'vehicles',
    'debra': 'extraction',
    'heather': 'exploration',
    'anna': 'exploration',
    'tanner': 'exploration',
    'lilla': 'power',
    'andy': 'exploration',
    'clover': 'power',
}

##############################################################################
# HELPER FUNCTIONS
##############################################################################

def get_scientist_branch_bonuses(scientist_key):
    """Get research speed/cost bonuses for a scientist by branch."""
    bonuses = {}
    for branch, scientists in SCIENTIST_BRANCHES.items():
        if scientist_key in scientists:
            bonuses[branch] = {'speed_mult': 1.25, 'cost_mult': 0.80, 'label': '25% faster research, 20% cheaper'}
            break
    secondary = SCIENTIST_SECONDARY_BRANCHES.get(scientist_key)
    if secondary and secondary not in bonuses:
        bonuses[secondary] = {'speed_mult': 1.15, 'cost_mult': 1.0, 'label': '15% faster research'}
    return bonuses


def get_tech_cost_at_level(base_cost: int, branch_level: int) -> int:
    """Calculate tech cost at a given branch level. Uses 1.12x multiplier."""
    return round(base_cost * (1.12 ** (branch_level - 1)))


def get_research_time_at_level(branch_level: int) -> int:
    """Get research time in seconds based on branch level. 1.10x per level, capped at 14 days."""
    base = 86400  # 1 day
    scaled = round(base * (1.10 ** (branch_level - 1)))
    return min(scaled, 14 * 86400)


def get_tech_name_at_level(base_name: str, branch_level: int) -> str:
    """Get tech name with level suffix (II, III, etc.) at Level 2+."""
    if branch_level == 1:
        return base_name
    suffixes = {2: 'II', 3: 'III', 4: 'IV', 5: 'V', 6: 'VI', 7: 'VII', 8: 'VIII', 9: 'IX', 10: 'X'}
    return f"{base_name} {suffixes.get(branch_level, branch_level)}"


def scale_effects(effects: dict, branch_level: int) -> dict:
    """Scale tech effects based on branch level. Higher levels = stronger effects."""
    if branch_level == 1:
        return effects.copy()

    # Scale multiplier: Level 2 = 1.1x, Level 3 = 1.2x, ..., Level 10 = 1.9x
    scale = 1.0 + (branch_level - 1) * 0.1

    scaled = {}
    for key, value in effects.items():
        if isinstance(value, (int, float)):
            if key.endswith('_mult'):
                # For multipliers, scale the bonus portion
                if value > 1:
                    bonus = (value - 1) * scale
                    scaled[key] = round(1 + bonus, 2)
                elif value < 1:
                    # For cost reductions, make them stronger (lower)
                    reduction = (1 - value) * scale
                    scaled[key] = max(0.5, round(1 - reduction, 2))
                else:
                    scaled[key] = value
            elif key.endswith('_bonus') or key.endswith('_base'):
                # Additive bonuses scale directly
                scaled[key] = round(value * scale, 2)
            elif key == 'dust_storm_resistance':
                # Cap at 1.0 (100% immunity)
                scaled[key] = min(1.0, value)
            else:
                scaled[key] = value
        else:
            scaled[key] = value
    return scaled


##############################################################################
# TECH CATALOG - 4 branches × 5 techs each
# Base costs are for Level 1. Use get_tech_cost_at_level() for higher levels.
##############################################################################

TECH_CATALOG = {
    'exploration': {
        'name': 'Exploration',
        'icon': '🔭',
        'icon_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/tech_icons/branch_exploration_1769194133.png',
        'description': 'Improve expedition speed, discovery rates, and weather resistance',
        'max_branch_level': 10,
        'techs': {
            'wind_analysis': {
                'name': 'Wind Analysis',
                'tier': 1,
                'base_cost_sv': 5000,
                'description': 'Study wind patterns to optimize flight paths. +25% expedition speed.',
                'effects': {'expedition_speed_mult': 1.25},
                'requires': [],
                'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/tech_icons/wind_analysis_1769193865.png',
            },
            'terrain_mapping': {
                'name': 'Terrain Mapping',
                'tier': 1,
                'base_cost_sv': 5000,
                'description': 'Chart surface features for better routes. +10% discovery chance.',
                'effects': {'discovery_chance_bonus': 0.10},
                'requires': [],
                'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/tech_icons/terrain_mapping_1770362142.png',
            },
            'storm_prediction': {
                'name': 'Storm Prediction',
                'tier': 2,
                'base_cost_sv': 12000,
                'description': 'Forecast dust storms before they hit. Full dust storm immunity.',
                'effects': {'dust_storm_resistance': 1.0},
                'requires': ['wind_analysis'],
                'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/tech_icons/storm_prediction_1769193890.png',
            },
            'advanced_sensors': {
                'name': 'Advanced Sensors',
                'tier': 2,
                'base_cost_sv': 12000,
                'description': 'Upgraded arrays spot deposits further away. +20% discovery chance.',
                'effects': {'discovery_chance_bonus': 0.20},
                'requires': ['terrain_mapping'],
                'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/tech_icons/advanced_sensors_1769193902.png',
            },
            'deep_scanning': {
                'name': 'Deep Scanning',
                'tier': 3,
                'base_cost_sv': 25000,
                'description': 'Penetrating scans reveal rare formations. +5% legendary discovery.',
                'effects': {'legendary_chance_bonus': 0.05},
                'requires': ['storm_prediction', 'advanced_sensors'],
                'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/tech_icons/deep_scanning_1770362866.png',
            },
        },
    },
    'vehicles': {
        'name': 'Vehicles',
        'icon': '🚗',
        'icon_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/tech_icons/branch_vehicles_1769194146.png',
        'description': 'Improve rover speed, cargo capacity, and fuel efficiency',
        'max_branch_level': 10,
        'techs': {
            'material_science': {
                'name': 'Material Science',
                'tier': 1,
                'base_cost_sv': 5000,
                'description': 'Martian rock composites for stronger frames. +15% cargo capacity.',
                'effects': {'cargo_capacity_mult': 1.15},
                'requires': [],
                'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/tech_icons/material_science_1769193926.png',
            },
            'suspension_engineering': {
                'name': 'Suspension Engineering',
                'tier': 1,
                'base_cost_sv': 5000,
                'description': 'Adapt suspension for rough terrain. +10% expedition speed.',
                'effects': {'expedition_speed_mult': 1.10},
                'requires': [],
                'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/tech_icons/suspension_engineering_1769193944.png',
            },
            'chassis_reinforcement': {
                'name': 'Chassis Reinforcement',
                'tier': 2,
                'base_cost_sv': 12000,
                'description': 'Reinforce for heavier loads. +20% speed, +10% cargo.',
                'effects': {'expedition_speed_mult': 1.20, 'cargo_capacity_mult': 1.10},
                'requires': ['material_science'],
                'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/tech_icons/chassis_reinforcement_1769193957.png',
            },
            'nav_computation': {
                'name': 'Nav Computation',
                'tier': 2,
                'base_cost_sv': 12000,
                'description': 'Route optimization reduces fuel waste. -10% fuel cost.',
                'effects': {'fuel_cost_mult': 0.90},
                'requires': ['suspension_engineering'],
                'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/tech_icons/nav_computation_1769193973.png',
            },
            'all_terrain_mastery': {
                'name': 'All-Terrain Mastery',
                'tier': 3,
                'base_cost_sv': 30000,
                'description': 'Master every Martian surface. +30% speed, +20% cargo.',
                'effects': {'expedition_speed_mult': 1.30, 'cargo_capacity_mult': 1.20},
                'requires': ['chassis_reinforcement', 'nav_computation'],
                'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/tech_icons/all_terrain_mastery_1769193986.png',
            },
        },
    },
    'power': {
        'name': 'Shard Generation',
        'icon': '⚡',
        'icon_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/tech_icons/branch_power_1769194157.png',
        'description': 'Boost Sepolia shard excitation and generation',
        'max_branch_level': 10,
        'techs': {
            'solar_optimization': {
                'name': 'Solar Optimization',
                'tier': 1,
                'base_cost_sv': 5000,
                'description': 'Optimize panel angles for Mars sunlight. +20% passive income.',
                'effects': {'passive_income_mult': 1.20},
                'requires': [],
                'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/tech_icons/solar_optimization_1769193997.png',
            },
            'battery_chemistry': {
                'name': 'Battery Chemistry',
                'tier': 1,
                'base_cost_sv': 5000,
                'description': 'Better charge storage for night generation. +25% night generation.',
                'effects': {'night_generation_mult': 1.25},
                'requires': [],
                'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/tech_icons/battery_chemistry_1769195087.png',
            },
            'thermal_tap': {
                'name': 'Thermal Tap',
                'tier': 2,
                'base_cost_sv': 12000,
                'description': 'Tap thermal vents to excite shard deposits. +30% passive income.',
                'effects': {'passive_income_mult': 1.30},
                'requires': ['solar_optimization'],
                'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/tech_icons/thermal_tap_1769194021.png',
            },
            'power_grid': {
                'name': 'Power Grid',
                'tier': 2,
                'base_cost_sv': 12000,
                'description': 'Efficient distribution network. +10% all generation.',
                'effects': {'all_generation_mult': 1.10},
                'requires': ['battery_chemistry'],
                'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/tech_icons/power_grid_1769194034.png',
            },
            'fusion_basics': {
                'name': 'Fusion Basics',
                'tier': 3,
                'base_cost_sv': 35000,
                'description': 'Early fusion experiments. +50% passive income.',
                'effects': {'passive_income_mult': 1.50},
                'requires': ['thermal_tap', 'power_grid'],
                'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/tech_icons/fusion_basics_1769194045.png',
            },
        },
    },
    'extraction': {
        'name': 'Extraction',
        'icon': '💎',
        'icon_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/tech_icons/branch_extraction_1769194171.png',
        'description': 'Increase shard yields and specimen value',
        'max_branch_level': 10,
        'techs': {
            'shard_resonance': {
                'name': 'Shard Resonance',
                'tier': 1,
                'base_cost_sv': 5000,
                'description': 'Tune to Sepolia crystal frequency. +10% discovery value.',
                'effects': {'discovery_value_mult': 1.10},
                'requires': [],
                'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/tech_icons/shard_resonance_1769194058.png',
            },
            'specimen_preservation': {
                'name': 'Specimen Preservation',
                'tier': 1,
                'base_cost_sv': 5000,
                'description': 'Seal samples to prevent degradation. +20% bio value.',
                'effects': {'bio_discovery_value_mult': 1.20},
                'requires': [],
                'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/tech_icons/specimen_preservation_1769194075.png',
            },
            'crystal_attunement': {
                'name': 'Crystal Attunement',
                'tier': 2,
                'base_cost_sv': 12000,
                'description': 'Deeper tuning extracts more. +25% discovery value.',
                'effects': {'discovery_value_mult': 1.25},
                'requires': ['shard_resonance'],
                'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/tech_icons/crystal_attunement_1769194088.png',
            },
            'xenobiology_mastery': {
                'name': 'Xenobiology Mastery',
                'tier': 2,
                'base_cost_sv': 12000,
                'description': 'Advanced techniques reduce costs. -25% xenolab cost.',
                'effects': {'xenolab_cost_mult': 0.75},
                'requires': ['specimen_preservation'],
                'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/tech_icons/xenobiology_mastery_1769194107.png',
            },
            'ancient_protocols': {
                'name': 'Ancient Protocols',
                'tier': 3,
                'base_cost_sv': 50000,
                'description': 'Decode ancient crystal patterns. +40% value, +20% extraction.',
                'effects': {'discovery_value_mult': 1.40, 'extraction_bonus': 0.20},
                'requires': ['crystal_attunement', 'xenobiology_mastery'],
                'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/tech_icons/ancient_protocols_1769194120.png',
            },
        },
    },
}


##############################################################################
# ADDITIONAL HELPER FUNCTIONS (for config.py compatibility)
##############################################################################

def get_tech_branch_config(branch: str) -> dict:
    """Get full branch config including techs."""
    return TECH_CATALOG.get(branch, {})


def get_tech_level_stats(branch: str, tech_key: str, branch_level: int = 1) -> dict:
    """Get tech stats at a specific branch level."""
    branch_data = TECH_CATALOG.get(branch)
    if not branch_data:
        return {}
    tech_data = branch_data.get('techs', {}).get(tech_key)
    if not tech_data:
        return {}

    return {
        'name': get_tech_name_at_level(tech_data['name'], branch_level),
        'tier': tech_data['tier'],
        'cost_sv': get_tech_cost_at_level(tech_data['base_cost_sv'], branch_level),
        'research_time_seconds': get_research_time_at_level(branch_level),
        'description': tech_data['description'],
        'effects': scale_effects(tech_data.get('effects', {}), branch_level),
        'requires': tech_data.get('requires', []),
        'image_url': tech_data.get('image_url', ''),
    }


def get_tech_research_cost(branch: str, tech_key: str, branch_level: int = 1) -> int:
    """Get research cost for a tech at a specific branch level."""
    branch_data = TECH_CATALOG.get(branch)
    if not branch_data:
        return 0
    tech_data = branch_data.get('techs', {}).get(tech_key)
    if not tech_data:
        return 0
    return get_tech_cost_at_level(tech_data['base_cost_sv'], branch_level)


##############################################################################
# MIGRATION MAPPING (old tech_key strings to new system)
##############################################################################

# Maps old numeric tech_keys to branch level equivalents
# Used when players have completed techs under the old 10-level linear system
TECH_MIGRATION_MAP = {
    # If player completed level N under old system, what branch level does that represent?
    # Old system: each "level" was a step in linear progression
    # New system: must complete all 5 techs to advance branch level
    # Conservative mapping: old completions count toward Level 1 techs
}
