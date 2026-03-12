"""
═══════════════════════════════════════════════════════════════════════════════
⚠️  DEPRECATED - DO NOT USE FOR NEW FEATURES  ⚠️
═══════════════════════════════════════════════════════════════════════════════

This file contains LEGACY shop items kept ONLY for backward compatibility with
existing player purchases stored in the `user_upgrades` database table.

ALL NEW PURCHASES should use:
  - UPGRADE_CATALOG (config_upgrades.py) — 11 upgrade paths × 10 levels
  - TECH_CATALOG (config_tech.py) — 4 tech branches × 10 levels
  - INFRASTRUCTURE_CATALOG (config_infrastructure.py) — 13 buildings × 10 levels

The shop_utils.py purchase endpoint will REJECT new purchases of these items.
Existing owned items continue to function via get_user_upgrade_effects().

Deprecated: February 2026
═══════════════════════════════════════════════════════════════════════════════
"""

##############################################################################
# SHOP CATALOG - LEGACY DATA ONLY (deprecated)
# Kept for: Displaying existing purchases, backward-compatible effect calculations
# NOT for: New purchases (blocked in shop_utils.py)
##############################################################################

SHOP_CATALOG = {
    # =========================================================================
    # ROVERS - Affect expedition speed and cargo capacity
    # Each tier is 10% faster than previous (compound): 1.0 → 1.1 → 1.21 → 1.33 → 1.46
    # Cargo slots: +1 per tier, Fuel savings: 5% per tier from tier 3
    # =========================================================================
    'rover_basic': {
        'id': 'rover_basic',
        'name': 'Scout Rover',
        'icon': '🛵',
        'category': 'rover',
        'cost_display': 500,
        'description': 'Basic surface transportation. +10% expedition speed.',
        'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/shop_items/rover_basic_1767505567.png',
        'effects': {
            'expedition_speed_mult': 1.10,
        },
        'requirements': [],
        'max_owned': 1,
    },
    'rover_enhanced': {
        'id': 'rover_enhanced',
        'name': 'Explorer Rover',
        'icon': '🚗',
        'category': 'rover',
        'cost_display': 2500,
        'description': 'Enhanced mobility system. +21% total speed, +1 cargo slot.',
        'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/shop_items/rover_enhanced_1767505576.png',
        'effects': {
            'expedition_speed_mult': 1.21,
            'cargo_slots': 1,
        },
        'requirements': ['rover_basic'],
        'max_owned': 1,
    },
    'rover_advanced': {
        'id': 'rover_advanced',
        'name': 'Expedition Crawler',
        'icon': '🚙',
        'category': 'rover',
        'cost_display': 10000,
        'description': 'Heavy-duty exploration vehicle. +33% total speed, +2 cargo slots, -5% fuel cost.',
        'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/shop_items/rover_advanced_1767505586.png',
        'effects': {
            'expedition_speed_mult': 1.33,
            'cargo_slots': 2,
            'fuel_cost_mult': 0.95,
        },
        'requirements': ['rover_enhanced'],
        'max_owned': 1,
    },
    'rover_elite': {
        'id': 'rover_elite',
        'name': 'Titan Transport',
        'icon': '🚛',
        'category': 'rover',
        'cost_display': 50000,
        'description': 'Heavy transport platform. +46% total speed, +3 cargo slots, -10% fuel cost.',
        'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/shop_items/rover_elite_1767505595.png',
        'effects': {
            'expedition_speed_mult': 1.46,
            'cargo_slots': 3,
            'fuel_cost_mult': 0.90,
        },
        'requirements': ['rover_advanced'],
        'max_owned': 1,
    },

    # =========================================================================
    # SCANNERS - Affect discovery rates and rarity chances
    # Discovery chance: +10% each tier (additive), Rare: +5% each, Legendary: +2% top tier
    # =========================================================================
    'scanner_basic': {
        'id': 'scanner_basic',
        'name': 'Surface Scanner',
        'icon': '📡',
        'category': 'equipment',
        'cost_display': 300,
        'description': 'Basic ground-penetrating radar. +10% discovery chance.',
        'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/shop_items/scanner_basic_1767505603.png',
        'effects': {
            'discovery_chance_bonus': 0.10,
        },
        'requirements': [],
        'max_owned': 1,
    },
    'scanner_deep': {
        'id': 'scanner_deep',
        'name': 'Deep Core Scanner',
        'icon': '🔬',
        'category': 'equipment',
        'cost_display': 1500,
        'description': 'Subsurface analysis system. +10% discovery, +5% rare find chance.',
        'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/shop_items/scanner_deep_1767505613.png',
        'effects': {
            'discovery_chance_bonus': 0.10,
            'rare_chance_bonus': 0.05,
        },
        'requirements': ['scanner_basic'],
        'max_owned': 1,
    },
    'scanner_quantum': {
        'id': 'scanner_quantum',
        'name': 'Quantum Resonance Array',
        'icon': '⚛️',
        'category': 'equipment',
        'cost_display': 8000,
        'description': 'Advanced detection system. +10% discovery, +5% rare, +2% legendary chance.',
        'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/shop_items/scanner_quantum_1767505622.png',
        'effects': {
            'discovery_chance_bonus': 0.10,
            'rare_chance_bonus': 0.05,
            'legendary_chance_bonus': 0.02,
        },
        'requirements': ['scanner_deep'],
        'max_owned': 1,
    },

    # =========================================================================
    # CARGO MODULES - Increase what you can bring back
    # =========================================================================
    'cargo_bay': {
        'id': 'cargo_bay',
        'name': 'Cargo Bay Extension',
        'icon': '📦',
        'category': 'equipment',
        'cost_display': 750,
        'description': 'Additional storage capacity. +2 cargo slots.',
        'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/shop_items/cargo_bay_1767505635.png',
        'effects': {
            'cargo_slots': 2,
        },
        'requirements': [],
        'max_owned': 3,  # Can buy up to 3
    },
    'cargo_refrigerated': {
        'id': 'cargo_refrigerated',
        'name': 'Cryo Storage Unit',
        'icon': '❄️',
        'category': 'equipment',
        'cost_display': 2000,
        'description': 'Preserves organic samples. +20% value for biological discoveries.',
        'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/shop_items/cargo_refrigerated_1767505644.png',
        'effects': {
            'bio_discovery_value_mult': 1.20,
            'cargo_slots': 1,
        },
        'requirements': ['cargo_bay'],
        'max_owned': 1,
    },

    # =========================================================================
    # SHARD GENERATION - Improve passive shard generation
    # Each tier is 10% better than previous (compound): 1.0 → 1.1 → 1.21 → 1.33 → 1.46
    # =========================================================================
    'solar_tier2': {
        'id': 'solar_tier2',
        'name': 'High-Efficiency Panels',
        'icon': '☀️',
        'category': 'power',
        'cost_display': 1000,
        'description': 'Upgraded solar collection. +10% passive Sepolia generation.',
        'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/shop_items/solar_tier2_1767505653.png',
        'effects': {
            'passive_income_mult': 1.10,
        },
        'requirements': [],
        'max_owned': 1,
    },
    'solar_tier3': {
        'id': 'solar_tier3',
        'name': 'Concentrated Solar Array',
        'icon': '🌟',
        'category': 'power',
        'cost_display': 5000,
        'description': 'Mirror-focused collectors. +21% total passive Sepolia shard generation.',
        'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/shop_items/solar_tier3_1767505668.png',
        'effects': {
            'passive_income_mult': 1.21,
        },
        'requirements': ['solar_tier2'],
        'max_owned': 1,
    },
    'nuclear_rtg': {
        'id': 'nuclear_rtg',
        'name': 'Shard Excitation Core',
        'icon': '☢️',
        'category': 'power',
        'cost_display': 15000,
        'description': 'Deep-frequency Sepolia shard activator. +33% total passive Sepolia shard generation.',
        'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/shop_items/nuclear_rtg_1767505677.png',
        'effects': {
            'passive_income_mult': 1.33,
        },
        'requirements': ['solar_tier3'],
        'max_owned': 1,
    },
    'fusion_reactor': {
        'id': 'fusion_reactor',
        'name': 'Resonant Shard Amplifier',
        'icon': '⚡',
        'category': 'power',
        'cost_display': 100000,
        'description': 'Experimental Sepolia shard resonance amplification. +46% total passive Sepolia shard generation.',
        'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/shop_items/fusion_reactor_1767506657.png',
        'effects': {
            'passive_income_mult': 1.46,
        },
        'requirements': ['nuclear_rtg'],
        'max_owned': 1,
    },

    # =========================================================================
    # RESEARCH - Boost discovery values
    # Each tier is 10% better than previous (compound): 1.0 → 1.1 → 1.21
    # =========================================================================
    'research_lab': {
        'id': 'research_lab',
        'name': 'Mobile Research Lab',
        'icon': '🔭',
        'category': 'research',
        'cost_display': 3000,
        'description': 'On-site analysis capability. +10% scientific value from discoveries.',
        'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/shop_items/research_lab_1767506665.png',
        'effects': {
            'discovery_value_mult': 1.10,
        },
        'requirements': [],
        'max_owned': 1,
    },
    'research_advanced': {
        'id': 'research_advanced',
        'name': 'Advanced Research Center',
        'icon': '🧪',
        'category': 'research',
        'cost_display': 25000,
        'description': 'Advanced analysis facilities. +21% total scientific value from discoveries.',
        'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/shop_items/research_advanced_1767506674.png',
        'effects': {
            'discovery_value_mult': 1.21,
        },
        'requirements': ['research_lab', 'fusion_reactor'],
        'max_owned': 1,
    },

    # =========================================================================
    # LIFE SUPPORT - Reduce expedition costs
    # LEGACY: These items duplicate the life_support upgrade path in config_upgrades.py
    # Kept for backwards compatibility with existing purchases.
    # New players should use the upgrade system instead.
    # =========================================================================
    'life_support_basic': {
        'id': 'life_support_basic',
        'name': 'Enhanced Life Support',
        'icon': '💨',
        'category': 'equipment',
        'cost_display': 600,
        'description': 'Efficient oxygen recycling. -10% expedition life support costs.',
        'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/shop_items/life_support_basic_1767506683.png',
        'effects': {
            'life_support_cost_mult': 0.90,
        },
        'requirements': [],
        'max_owned': 1,
    },
    'life_support_advanced': {
        'id': 'life_support_advanced',
        'name': 'Closed-Loop Biosphere',
        'icon': '🌿',
        'category': 'equipment',
        'cost_display': 4000,
        'description': 'Self-sustaining life support. -19% total life support costs.',
        'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/shop_items/life_support_advanced_1767506690.png',
        'effects': {
            'life_support_cost_mult': 0.81,
        },
        'requirements': ['life_support_basic'],
        'max_owned': 1,
    },

    # =========================================================================
    # CAPTAIN GEAR - Boost captain stats
    # =========================================================================
    'suit_exploration': {
        'id': 'suit_exploration',
        'name': 'Explorer EVA Suit',
        'icon': '🧑‍🚀',
        'category': 'gear',
        'cost_display': 800,
        'description': 'Optimized for surface exploration. +10 to Exploration stat.',
        'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/shop_items/suit_exploration_1767506706.png',
        'effects': {
            'stat_exploration_bonus': 10,
        },
        'requirements': [],
        'max_owned': 1,
    },
    'suit_command': {
        'id': 'suit_command',
        'name': 'Command Exosuit',
        'icon': '🎖️',
        'category': 'gear',
        'cost_display': 2500,
        'description': 'Leadership-enhanced suit. +10 to Leadership and Strategy.',
        'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/shop_items/suit_command_1767506719.png',
        'effects': {
            'stat_leadership_bonus': 10,
            'stat_strategy_bonus': 10,
        },
        'requirements': [],
        'max_owned': 1,
    },
    'suit_logistics': {
        'id': 'suit_logistics',
        'name': 'Hauler Power Frame',
        'icon': '🦾',
        'category': 'gear',
        'cost_display': 1200,
        'description': 'Heavy-lift exoskeleton. +15 to Logistics stat.',
        'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/shop_items/suit_logistics_1767506726.png',
        'effects': {
            'stat_logistics_bonus': 15,
        },
        'requirements': [],
        'max_owned': 1,
    },

    # =========================================================================
    # AUTOMATION - Passive bonuses
    # Discovery chance: +10% max, Income base: flat bonus (not percentage)
    # =========================================================================
    'mining_drone': {
        'id': 'mining_drone',
        'name': 'Mining Automation',
        'icon': '⛏️',
        'category': 'automation',
        'cost_display': 20000,
        'description': 'Automated extraction drones. +10 Sepolia per hour base income.',
        'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/shop_items/mining_drone_1767506740.png',
        'effects': {
            'passive_income_base': 10,  # 10 Sepolia per hour - flat, not percentage
        },
        'requirements': [],
        'max_owned': 1,
    },
    'maintenance_drone': {
        'id': 'maintenance_drone',
        'name': 'Maintenance Drone',
        'icon': '🧹',
        'category': 'automation',
        'cost_display': 2500,
        'description': 'Autonomous cleaning drone keeps solar arrays free of Martian dust. Prevents dust storm shutdowns and keeps panels operating at peak efficiency.',
        'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/shop_items/maintenance_drone_1768094423.png',
        'effects': {
            'dust_storm_immune': True,  # Panels never get dust-covered
        },
        'requirements': [],
        'max_owned': 1,
    },
}

# Shop categories for UI organization
SHOP_CATEGORIES = {
    'rover': {'name': 'Rovers', 'icon': '🚗', 'order': 1},
    'equipment': {'name': 'Equipment', 'icon': '🛠️', 'order': 2},
    'power': {'name': 'Shard Generation', 'icon': '⚡', 'order': 3},
    'research': {'name': 'Research', 'icon': '🔬', 'order': 4},
    'gear': {'name': 'Gear', 'icon': '🧑‍🚀', 'order': 5},
    'automation': {'name': 'Automation', 'icon': '🤖', 'order': 6},
}

# =============================================================================
# TRAIL BUILDING BONUSES
# Scanner equipment gives passive bonuses, discovery items can be consumed
# =============================================================================

# Scanner equipment passive bonuses (best one wins, no stacking)
TRAIL_SCANNER_BONUSES = {
    'scanner_basic': 0.02,   # Surface Scanner: +2%
    'scanner_deep': 0.03,    # Deep Core Scanner: +3%
}

# Discovery consumables - matched by item_type + keyword in item_name
# Item is DESTROYED when used for trail building
TRAIL_CONSUMABLE_BONUSES = {
    'biological': {
        'lichen': 0.10,      # Lichen Patch, Desert Lichen, Dust Lichen, Sinuous Lichen
        'microbial': 0.15,   # Microbial Mat
        'bacterial': 0.15,   # Bacterial Crust
        'microbe': 0.15,     # Microbe Crust
        'moss': 0.10,        # Fissure Moss
        'spore': 0.08,       # Hill Spores
        'default': 0.08,     # Other biological items
    },
    'mineral': {
        'gypsum': 0.12,      # Layered Gypsum, Marsh Gypsum
        'ite': 0.08,         # Calcite, Pyrite, etc. (ends in -ite)
        'ite ite': 0.08,     # Skip - this is just to ensure 'ite' matches
        'default': 0.06,     # Other minerals
    },
}

# Trip duration based on TOTAL multiplier (crew stat × scanner × consumable)
# All bonuses stack multiplicatively: stat_mult × scanner_mult × consumable_mult
# No bonus = 15 min (slowest), high combined = 3 min (fastest)
#
# Example combos:
# - Fresh crew (1.0x) + no scanner + no consumable = 1.0x → 15 min
# - Experienced crew (1.5x) + scanner (1.03x) + top consumable (1.15x) = 1.78x → 3 min
TRAIL_MULTIPLIER_DURATIONS = {
    1.50: 3,    # 1.50x+ total → 3 min (experienced crew + good bonuses)
    1.30: 5,    # 1.30-1.49x → 5 min
    1.15: 8,    # 1.15-1.29x → 8 min (decent bonuses)
    1.05: 12,   # 1.05-1.14x → 12 min (scanner only or low stat)
    1.00: 15,   # 1.0x → 15 min (no bonuses at all)
}


def get_trail_duration_from_multiplier(total_multiplier: float) -> int:
    """Get trip duration in minutes based on TOTAL multiplier (stat × scanner × consumable)."""
    for tier_mult, duration in sorted(TRAIL_MULTIPLIER_DURATIONS.items(), reverse=True):
        if total_multiplier >= tier_mult:
            return duration
    return 15  # Default to longest trip


def get_shop_item(item_id):
    """Get shop item config by ID"""
    return SHOP_CATALOG.get(item_id)


def get_build_time_seconds(cost_display: float) -> int:
    """
    Calculate build time based on item cost.
    Mars-realistic times: days to months, NOT minutes/hours.
    """
    if cost_display < 500:
        return 3 * 86400      # 3 days
    elif cost_display < 1000:
        return 5 * 86400      # 5 days
    elif cost_display < 2000:
        return 7 * 86400      # 1 week
    elif cost_display < 3000:
        return 14 * 86400     # 2 weeks
    elif cost_display < 5000:
        return 21 * 86400     # 3 weeks
    elif cost_display < 10000:
        return 30 * 86400     # 1 month
    elif cost_display < 20000:
        return 45 * 86400     # 45 days
    elif cost_display < 30000:
        return 60 * 86400     # 2 months
    elif cost_display < 50000:
        return 90 * 86400     # 3 months
    else:
        return 120 * 86400    # 4 months


def get_shop_items_by_category(category):
    """Get all shop items in a category"""
    return {k: v for k, v in SHOP_CATALOG.items() if v['category'] == category}
