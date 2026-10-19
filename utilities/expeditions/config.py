"""
utilities.expeditions.config — data-only tuning values for the expedition subsystem.

All constants, tables, and magic numbers live here. Sibling modules
(terrain, cost, travel, core) import from this file. Do not put logic here.
"""

# ============================================================================
# TRAVEL SPEED
# ============================================================================

BASE_SPEED_KM_PER_HOUR = 3.5  # Base rover/walking speed on Mars (bumped per Luke #1116)
EVA_HOURS_PER_DAY = 8.0


# ============================================================================
# FUEL / LIFE SUPPORT
# ============================================================================

BASE_FUEL_PER_KM = 1.0
LIFE_SUPPORT_PER_DAY = 50.0
BASE_COST_PER_KM = 2.5  # tuned for ~300-500 shards for medium expeditions


# ============================================================================
# TERRAIN MODIFIERS
# Mars is brutal. Terrain affects BOTH speed and cost.
#   speed_mult: <1.0 = slower, >1.0 = faster
#   cost_mult:  <1.0 = cheaper, >1.0 = more expensive
# ============================================================================

TERRAIN_MODIFIERS = {
    'Planitia': {
        'speed_mult': 1.2, 'cost_mult': 0.7,
        'reason': 'Flat plains - optimal conditions for wheeled vehicles'
    },
    'Vallis': {
        'speed_mult': 0.7, 'cost_mult': 1.3,
        'reason': 'Valley floor - scattered debris and rockslides'
    },
    'Crater': {
        'speed_mult': 0.6, 'cost_mult': 1.5,
        'reason': 'Crater rim - unstable edges, steep grades'
    },
    'Fossae': {
        'speed_mult': 0.6, 'cost_mult': 1.4,
        'reason': 'Trough system - multiple difficult crossings'
    },
    'Patera': {
        'speed_mult': 0.5, 'cost_mult': 1.6,
        'reason': 'Volcanic caldera - sharp basalt, uneven lava flows'
    },
    'Chasma': {
        'speed_mult': 0.4, 'cost_mult': 2.0,
        'reason': 'Deep canyon - extreme descent/ascent, limited routes'
    },
    'Mons': {
        'speed_mult': 0.3, 'cost_mult': 2.5,
        'reason': 'Mountain - extreme elevation gain, motor strain'
    },
    'Rupes': {
        'speed_mult': 0.2, 'cost_mult': 3.0,
        'reason': 'Cliff escarpment - requires extensive rerouting'
    },
    'default': {
        'speed_mult': 1.0, 'cost_mult': 1.0,
        'reason': 'Standard Martian terrain'
    }
}


# ============================================================================
# GEOGRAPHIC FILTERING
# ============================================================================

MISSION_ARTIFACT_MAX_DISTANCE_KM = 100
GENERIC_SAMPLE_MAX_DISTANCE_KM = 9999
