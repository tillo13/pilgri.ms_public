"""
Infrastructure upgrade catalog - 13 buildings × 10 levels each
Formula: Cost(n) = round(BaseCost × 1.12^(n-1))
Build times: Scale from instant to 14 days max
Level 0 = not built, Level 1+ = built and upgraded
"""

##############################################################################
# INFRASTRUCTURE CATALOG - 13 building paths × 10 levels each
##############################################################################

INFRASTRUCTURE_CATALOG = {
    # =========================================================================
    # POWER SYSTEMS
    # =========================================================================
    'solar_array': {
        'name': 'Solar Array',
        'description': 'Excites Sepolia shard deposits using Mars sunlight',
        'icon': '\U0001f506',  # 🔆
        'category': 'power',
        'generates_resource': 'sepolia',  # CRITICAL: This structure generates Sepolia!
        'max_level': 10,
        'default_level': 1,  # Players start with this
        'levels': {
            1: {
                'name': 'Basic Solar Panels', 'cost': 0,
                'generation_rate': 10.0, 'build_time_days': 0,
                'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/infrastructure_items/solar_array_1770262697.png',
            },
            2: {
                'name': 'Expanded Array', 'cost': 500, 'build_time_days': 1,
                'generation_rate': 12.0,
                'image_url': '',
            },
            3: {
                'name': 'High-Efficiency Panels', 'cost': 560, 'build_time_days': 2,
                'generation_rate': 15.0,
                'image_url': '',
            },
            4: {
                'name': 'Concentrated Collector', 'cost': 4128, 'build_time_days': 3,
                'generation_rate': 18.0,
                'image_url': '',
            },
            5: {
                'name': 'Mirror Array', 'cost': 4623, 'build_time_days': 5,
                'generation_rate': 22.0,
                'image_url': '',
            },
            6: {
                'name': 'Regolith Solar Farm', 'cost': 5178, 'build_time_days': 7,
                'generation_rate': 27.0,
                'image_url': '',
            },
            7: {
                'name': 'Crystal-Laced Collectors', 'cost': 5800, 'build_time_days': 9,
                'generation_rate': 33.0,
                'image_url': '',
            },
            8: {
                'name': 'Resonant Solar Grid', 'cost': 54640, 'build_time_days': 11,
                'generation_rate': 40.0,
                'image_url': '',
            },
            9: {
                'name': 'Sepolia Excitation Array', 'cost': 61197, 'build_time_days': 13,
                'generation_rate': 50.0,
                'image_url': '',
            },
            10: {
                'name': 'Monolithic Power Station', 'cost': 68540, 'build_time_days': 14,
                'generation_rate': 65.0,
                'image_url': '',
            },
        }
    },

    'battery_storage': {
        'name': 'Battery Storage',
        'description': 'Stores charged Sepolia shards for Mars nights',
        'icon': '\U0001f50b',  # 🔋
        'category': 'power',
        'max_level': 10,
        'default_level': 0,
        'requirements': ['solar_array'],
        'unlock_requirements': {'solar_array': 2},  # Unlocks when solar hits Lv2
        'levels': {
            1: {
                'name': 'Basic Battery Bank', 'cost': 100, 'build_time_days': 0.042,
                'night_generation': 0.30,  # 30% of solar at night
                'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/infrastructure_items/battery_storage_1767508622.png',
            },
            2: {
                'name': 'Expanded Storage', 'cost': 112, 'build_time_days': 1,
                'night_generation': 0.35,
                'image_url': '',
            },
            3: {
                'name': 'High-Capacity Cells', 'cost': 125, 'build_time_days': 2,
                'night_generation': 0.40,
                'image_url': '',
            },
            4: {
                'name': 'Deep Cycle Bank', 'cost': 4128, 'build_time_days': 3,
                'night_generation': 0.45,
                'image_url': '',
            },
            5: {
                'name': 'Regolith Capacitors', 'cost': 4623, 'build_time_days': 5,
                'night_generation': 0.50,
                'image_url': '',
            },
            6: {
                'name': 'Crystal Cell Array', 'cost': 5178, 'build_time_days': 7,
                'night_generation': 0.55,
                'image_url': '',
            },
            7: {
                'name': 'Resonant Storage', 'cost': 5800, 'build_time_days': 9,
                'night_generation': 0.60,
                'image_url': '',
            },
            8: {
                'name': 'Sepolia Battery Core', 'cost': 54640, 'build_time_days': 11,
                'night_generation': 0.70,
                'image_url': '',
            },
            9: {
                'name': 'Deep Resonance Bank', 'cost': 61197, 'build_time_days': 13,
                'night_generation': 0.80,
                'image_url': '',
            },
            10: {
                'name': 'Perpetual Power Core', 'cost': 68540, 'build_time_days': 14,
                'night_generation': 0.90,  # 90% at night
                'image_url': '',
            },
        }
    },

    # =========================================================================
    # EXTRACTION SYSTEMS
    # =========================================================================
    'water_extractor': {
        'name': 'Water Extractor',
        'description': 'Extracts water ice for fuel synthesis',
        'icon': '\U0001f4a7',  # 💧
        'category': 'extraction',
        'max_level': 10,
        'default_level': 0,
        'requirements': ['solar_array'],
        'unlock_requirements': {'solar_array': 2},  # Unlocks when solar hits Lv2
        'levels': {
            1: {
                'name': 'Basic Ice Drill', 'cost': 500, 'build_time_days': 0.042,
                'fuel_cost_reduction': 0.10,  # -10% fuel costs
                'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/infrastructure_items/water_extractor_1770262697.png',
            },
            2: {
                'name': 'Improved Drill', 'cost': 560, 'build_time_days': 2,
                'fuel_cost_reduction': 0.13,
                'image_url': '',
            },
            3: {
                'name': 'Deep Ice Tap', 'cost': 627, 'build_time_days': 3,
                'fuel_cost_reduction': 0.16,
                'image_url': '',
            },
            4: {
                'name': 'Permafrost Extractor', 'cost': 4128, 'build_time_days': 4,
                'fuel_cost_reduction': 0.20,
                'image_url': '',
            },
            5: {
                'name': 'Aquifer Tap', 'cost': 4623, 'build_time_days': 6,
                'fuel_cost_reduction': 0.24,
                'image_url': '',
            },
            6: {
                'name': 'Subsurface Mining Rig', 'cost': 5178, 'build_time_days': 8,
                'fuel_cost_reduction': 0.28,
                'image_url': '',
            },
            7: {
                'name': 'Crystal-Aided Extractor', 'cost': 5800, 'build_time_days': 10,
                'fuel_cost_reduction': 0.32,
                'image_url': '',
            },
            8: {
                'name': 'Deep Core Drill', 'cost': 54640, 'build_time_days': 11,
                'fuel_cost_reduction': 0.36,
                'image_url': '',
            },
            9: {
                'name': 'Resonant Water Mine', 'cost': 61197, 'build_time_days': 13,
                'fuel_cost_reduction': 0.40,
                'image_url': '',
            },
            10: {
                'name': 'Hydro Core Complex', 'cost': 68540, 'build_time_days': 14,
                'fuel_cost_reduction': 0.45,  # -45% fuel costs
                'image_url': '',
            },
        }
    },

    'refinery': {
        'name': 'Ore Refinery',
        'description': 'Processes Martian regolith into Sepolia shards',
        'icon': '\u2699\ufe0f',  # ⚙️
        'category': 'extraction',
        'max_level': 10,
        'default_level': 0,
        'requirements': ['water_extractor', 'solar_array'],
        'unlock_requirements': {'water_extractor': 3, 'solar_array': 3},  # Unlocks at Lv3 each
        'levels': {
            1: {
                'name': 'Basic Refinery', 'cost': 5000, 'build_time_days': 0.042,
                'generation_rate': 25.0,
                'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/infrastructure_items/refinery_1770262697.png',
            },
            2: {
                'name': 'Improved Refinery', 'cost': 5600, 'build_time_days': 4,
                'generation_rate': 30.0,
                'image_url': '',
            },
            3: {
                'name': 'High-Throughput Refinery', 'cost': 6272, 'build_time_days': 5,
                'generation_rate': 36.0,
                'image_url': '',
            },
            4: {
                'name': 'Crystal-Enhanced Refinery', 'cost': 7025, 'build_time_days': 6,
                'generation_rate': 43.0,
                'image_url': '',
            },
            5: {
                'name': 'Advanced Refinery', 'cost': 7868, 'build_time_days': 7,
                'generation_rate': 52.0,
                'image_url': '',
            },
            6: {
                'name': 'Deep Processing Plant', 'cost': 8812, 'build_time_days': 9,
                'generation_rate': 62.0,
                'image_url': '',
            },
            7: {
                'name': 'Crystal-Enhanced Refinery', 'cost': 9869, 'build_time_days': 10,
                'generation_rate': 75.0,
                'image_url': '',
            },
            8: {
                'name': 'Sepolia Extraction Core', 'cost': 54640, 'build_time_days': 11,
                'generation_rate': 90.0,
                'image_url': '',
            },
            9: {
                'name': 'Resonant Processing Hub', 'cost': 61197, 'build_time_days': 13,
                'generation_rate': 110.0,
                'image_url': '',
            },
            10: {
                'name': 'Monolithic Refinery', 'cost': 68540, 'build_time_days': 14,
                'generation_rate': 135.0,
                'image_url': '',
            },
        }
    },

    # =========================================================================
    # HABITAT SYSTEMS
    # =========================================================================
    'habitat_module': {
        'name': 'Habitat Module',
        'description': 'Pressurized living quarters for crew',
        'icon': '\U0001f3e0',  # 🏠
        'category': 'habitat',
        'max_level': 10,
        'default_level': 0,
        'requirements': ['solar_array'],
        'unlock_requirements': {'solar_array': 2},  # Unlocks when solar hits Lv2
        'levels': {
            1: {
                'name': 'Basic Hab Pod', 'cost': 1000, 'build_time_days': 0.042,
                'expedition_capacity': 1,
                'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/infrastructure_items/habitat_module_1770262697.png',
            },
            2: {
                'name': 'Expanded Quarters', 'cost': 1120, 'build_time_days': 2,
                'expedition_capacity': 2,
                'image_url': '',
            },
            3: {
                'name': 'Crew Dormitory', 'cost': 1254, 'build_time_days': 3,
                'expedition_capacity': 2,
                'image_url': '',
            },
            4: {
                'name': 'Colony Hub', 'cost': 4128, 'build_time_days': 4,
                'expedition_capacity': 3,
                'image_url': '',
            },
            5: {
                'name': 'Regolith Bunker', 'cost': 4623, 'build_time_days': 6,
                'expedition_capacity': 3,
                'image_url': '',
            },
            6: {
                'name': 'Underground Complex', 'cost': 5178, 'build_time_days': 8,
                'expedition_capacity': 4,
                'image_url': '',
            },
            7: {
                'name': 'Crystal-Laced Habitat', 'cost': 5800, 'build_time_days': 10,
                'expedition_capacity': 4,
                'image_url': '',
            },
            8: {
                'name': 'Resonant Living Core', 'cost': 54640, 'build_time_days': 11,
                'expedition_capacity': 5,
                'image_url': '',
            },
            9: {
                'name': 'Deep Mars Settlement', 'cost': 61197, 'build_time_days': 13,
                'expedition_capacity': 5,
                'image_url': '',
            },
            10: {
                'name': 'Monolithic Colony', 'cost': 68540, 'build_time_days': 14,
                'expedition_capacity': 6,
                'image_url': '',
            },
        }
    },

    'greenhouse': {
        'name': 'Greenhouse',
        'description': 'Grow food on Mars to reduce expedition costs',
        'icon': '\U0001f331',  # 🌱
        'category': 'life_support',
        'max_level': 10,
        'default_level': 0,
        'requirements': ['water_extractor', 'habitat_module'],
        'unlock_requirements': {'water_extractor': 3, 'habitat_module': 2},
        'levels': {
            1: {
                'name': 'Basic Hydroponics', 'cost': 2000, 'build_time_days': 0.042,
                'life_support_reduction': 0.10,
                'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/infrastructure_items/greenhouse_1770262697.png',
            },
            2: {
                'name': 'Expanded Garden', 'cost': 2240, 'build_time_days': 3,
                'life_support_reduction': 0.13,
                'image_url': '',
            },
            3: {
                'name': 'Aeroponics Bay', 'cost': 2509, 'build_time_days': 4,
                'life_support_reduction': 0.16,
                'image_url': '',
            },
            4: {
                'name': 'Crop Biodome', 'cost': 4128, 'build_time_days': 5,
                'life_support_reduction': 0.20, 'science_generation_rate': 1.0,
                'image_url': '',
            },
            5: {
                'name': 'Regolith Farm', 'cost': 4623, 'build_time_days': 7,
                'life_support_reduction': 0.24, 'science_generation_rate': 1.5,
                'image_url': '',
            },
            6: {
                'name': 'Crystal-Lit Gardens', 'cost': 5178, 'build_time_days': 8,
                'life_support_reduction': 0.28, 'science_generation_rate': 2.0,
                'image_url': '',
            },
            7: {
                'name': 'Underground Farm Complex', 'cost': 5800, 'build_time_days': 10,
                'life_support_reduction': 0.32, 'science_generation_rate': 2.5,
                'image_url': '',
            },
            8: {
                'name': 'Biosphere Module', 'cost': 54640, 'build_time_days': 11,
                'life_support_reduction': 0.36, 'science_generation_rate': 3.0,
                'image_url': '',
            },
            9: {
                'name': 'Self-Sustaining Ecosystem', 'cost': 61197, 'build_time_days': 13,
                'life_support_reduction': 0.40, 'science_generation_rate': 3.5,
                'image_url': '',
            },
            10: {
                'name': 'Mars Eden', 'cost': 68540, 'build_time_days': 14,
                'life_support_reduction': 0.45, 'science_generation_rate': 4.0,
                'image_url': '',
            },
        }
    },

    # =========================================================================
    # RESEARCH SYSTEMS
    # =========================================================================
    'research_station': {
        'name': 'Research Station',
        'description': 'Scientist workspace that generates Science Value',
        'icon': '\U0001f52c',  # 🔬
        'category': 'research',
        'max_level': 10,
        'default_level': 1,  # Players start with basic
        'levels': {
            # SV rates boosted ~6x per SV Economy brainstorm (was 1-14, now 5-90)
            1: {
                'name': 'Workbench', 'cost': 0, 'build_time_days': 0,
                'science_generation_rate': 5.0, 'discovery_value_mult': 1.0,
                'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/infrastructure_items/research_station_1769191168.png',
            },
            2: {
                'name': 'Basic Lab', 'cost': 300, 'build_time_days': 1,
                'science_generation_rate': 8.0, 'discovery_value_mult': 1.05,
                'image_url': '',
            },
            3: {
                'name': 'Analysis Station', 'cost': 336, 'build_time_days': 2,
                'science_generation_rate': 12.0, 'discovery_value_mult': 1.10,
                'image_url': '',
            },
            4: {
                'name': 'Research Center', 'cost': 4128, 'build_time_days': 3,
                'science_generation_rate': 18.0, 'discovery_value_mult': 1.15,
                'image_url': '',
            },
            5: {
                'name': 'Science Complex', 'cost': 4623, 'build_time_days': 5,
                'science_generation_rate': 25.0, 'discovery_value_mult': 1.21,
                'image_url': '',
            },
            6: {
                'name': 'Crystal Analysis Lab', 'cost': 5178, 'build_time_days': 7,
                'science_generation_rate': 35.0, 'discovery_value_mult': 1.28,
                'image_url': '',
            },
            7: {
                'name': 'Deep Research Facility', 'cost': 5800, 'build_time_days': 9,
                'science_generation_rate': 45.0, 'discovery_value_mult': 1.33,
                'image_url': '',
            },
            8: {
                'name': 'Sepolia Studies Institute', 'cost': 54640, 'build_time_days': 11,
                'science_generation_rate': 58.0, 'discovery_value_mult': 1.40,
                'image_url': '',
            },
            9: {
                'name': 'Mars Science Academy', 'cost': 61197, 'build_time_days': 13,
                'science_generation_rate': 72.0, 'discovery_value_mult': 1.46,
                'image_url': '',
            },
            10: {
                'name': 'Ancient Studies Monolith', 'cost': 68540, 'build_time_days': 14,
                'science_generation_rate': 90.0, 'discovery_value_mult': 1.54,
                'image_url': '',
            },
        }
    },

    'xenobiology_lab': {
        'name': 'Xenobiology Lab',
        'description': 'Study Martian specimens — boosts bio value, discovery chance, and SV generation',
        'icon': '\U0001f9ec',  # 🧬
        'category': 'research',
        'max_level': 10,
        'default_level': 0,
        'requirements': ['habitat_module'],
        'unlock_requirements': {'habitat_module': 3, 'research_station': 2},
        'levels': {
            1: {
                'name': 'Basic Xeno Lab', 'cost': 2000, 'build_time_days': 0.042,
                'research_enabled': True, 'bio_value_mult': 1.10, 'discovery_chance_bonus': 0.02,
                'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/infrastructure_items/xenobiology_lab_1770262697.png',
            },
            2: {
                'name': 'Specimen Analysis Bay', 'cost': 2240, 'build_time_days': 3,
                'research_enabled': True, 'bio_value_mult': 1.15, 'discovery_chance_bonus': 0.03, 'science_generation_rate': 1.0,
                'image_url': '',
            },
            3: {
                'name': 'Microbe Culture Lab', 'cost': 2509, 'build_time_days': 4,
                'research_enabled': True, 'bio_value_mult': 1.21, 'discovery_chance_bonus': 0.04, 'science_generation_rate': 2.0,
                'image_url': '',
            },
            4: {
                'name': 'Life Detection Array', 'cost': 4128, 'build_time_days': 5,
                'research_enabled': True, 'bio_value_mult': 1.28, 'discovery_chance_bonus': 0.05, 'science_generation_rate': 3.0,
                'image_url': '',
            },
            5: {
                'name': 'Advanced Xeno Studies', 'cost': 4623, 'build_time_days': 7,
                'research_enabled': True, 'bio_value_mult': 1.35, 'discovery_chance_bonus': 0.06, 'science_generation_rate': 5.0, 'rare_chance_bonus': 0.02,
                'image_url': '',
            },
            6: {
                'name': 'Crystal Bio-Resonance Lab', 'cost': 5178, 'build_time_days': 8,
                'research_enabled': True, 'bio_value_mult': 1.42, 'discovery_chance_bonus': 0.07, 'science_generation_rate': 7.0, 'rare_chance_bonus': 0.03,
                'image_url': '',
            },
            7: {
                'name': 'Deep Life Sciences', 'cost': 5800, 'build_time_days': 10,
                'research_enabled': True, 'bio_value_mult': 1.50, 'discovery_chance_bonus': 0.08, 'science_generation_rate': 9.0, 'rare_chance_bonus': 0.04,
                'image_url': '',
            },
            8: {
                'name': 'Ancient Biology Institute', 'cost': 54640, 'build_time_days': 11,
                'research_enabled': True, 'bio_value_mult': 1.58, 'discovery_chance_bonus': 0.09, 'science_generation_rate': 12.0, 'rare_chance_bonus': 0.05,
                'image_url': '',
            },
            9: {
                'name': 'Sepolia Life Studies', 'cost': 61197, 'build_time_days': 13,
                'research_enabled': True, 'bio_value_mult': 1.65, 'discovery_chance_bonus': 0.10, 'science_generation_rate': 15.0, 'rare_chance_bonus': 0.06,
                'image_url': '',
            },
            10: {
                'name': 'Xeno Genesis Complex', 'cost': 68540, 'build_time_days': 14,
                'research_enabled': True, 'bio_value_mult': 1.75, 'discovery_chance_bonus': 0.12, 'science_generation_rate': 20.0, 'rare_chance_bonus': 0.08,
                'image_url': '',
            },
        }
    },

    'comms_array': {
        'name': 'Communications Array',
        'description': 'Deep space antenna for discovery detection',
        'icon': '\U0001f4e1',  # 📡
        'category': 'research',
        'max_level': 10,
        'default_level': 0,
        'requirements': ['solar_array', 'battery_storage'],
        'unlock_requirements': {'solar_array': 3, 'battery_storage': 2},
        'levels': {
            1: {
                'name': 'Basic Antenna', 'cost': 3000, 'build_time_days': 0.042,
                'discovery_bonus': 0.05,
                'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/infrastructure_items/comms_array_1770262697.png',
            },
            2: {
                'name': 'High-Gain Array', 'cost': 3360, 'build_time_days': 3,
                'discovery_bonus': 0.07,
                'image_url': '',
            },
            3: {
                'name': 'Deep Space Relay', 'cost': 3763, 'build_time_days': 4,
                'discovery_bonus': 0.09,
                'image_url': '',
            },
            4: {
                'name': 'Signal Processing Hub', 'cost': 4215, 'build_time_days': 5,
                'discovery_bonus': 0.11,
                'image_url': '',
            },
            5: {
                'name': 'Resonance Antenna', 'cost': 4721, 'build_time_days': 7,
                'discovery_bonus': 0.13,
                'image_url': '',
            },
            6: {
                'name': 'Crystal-Tuned Array', 'cost': 5287, 'build_time_days': 8,
                'discovery_bonus': 0.15,
                'image_url': '',
            },
            7: {
                'name': 'Deep Signal Detector', 'cost': 5922, 'build_time_days': 10,
                'discovery_bonus': 0.18,
                'image_url': '',
            },
            8: {
                'name': 'Sepolia Resonance Relay', 'cost': 54640, 'build_time_days': 11,
                'discovery_bonus': 0.20,
                'image_url': '',
            },
            9: {
                'name': 'Ancient Signal Array', 'cost': 61197, 'build_time_days': 13,
                'discovery_bonus': 0.23,
                'image_url': '',
            },
            10: {
                'name': 'Deep Space Beacon', 'cost': 68540, 'build_time_days': 14,
                'discovery_bonus': 0.25,
                'image_url': '',
            },
        }
    },

    # =========================================================================
    # TIER 4-7 ADVANCED BUILDINGS (unlock via prerequisite levels)
    # Buildings show but are locked until unlock_requirements are met
    # =========================================================================
    'regolith_forge': {
        'name': 'Regolith Forge',
        'description': 'Processes raw Martian regolith into refined materials',
        'icon': '\u2692\ufe0f',  # ⚒️
        'category': 'extraction',
        'generates_resource': 'sepolia',
        'max_level': 10,
        'default_level': 0,
        'requirements': ['refinery'],
        'unlock_requirements': {'refinery': 7},  # Unlocks when refinery hits Lv7
        'levels': {
            1: {
                'name': 'Basic Forge', 'cost': 20000, 'build_time_days': 0.042,
                'generation_rate': 50.0, 'science_generation_rate': 3.0,
                'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/infrastructure_items/regolith_forge_1770262697.png',
            },
            2: {
                'name': 'Improved Forge', 'cost': 22400, 'build_time_days': 7,
                'generation_rate': 60.0, 'science_generation_rate': 3.5,
                'image_url': '',
            },
            3: {
                'name': 'High-Output Forge', 'cost': 25088, 'build_time_days': 8,
                'generation_rate': 72.0, 'science_generation_rate': 4.0,
                'image_url': '',
            },
            4: {
                'name': 'Industrial Forge', 'cost': 28099, 'build_time_days': 9,
                'generation_rate': 86.0, 'science_generation_rate': 4.5,
                'image_url': '',
            },
            5: {
                'name': 'Crystal-Heated Forge', 'cost': 31471, 'build_time_days': 10,
                'generation_rate': 103.0, 'science_generation_rate': 5.0,
                'image_url': '',
                'stat_exploration_bonus': 1,
                'stat_leadership_bonus': 1,
                'stat_strategy_bonus': 1,
                'stat_logistics_bonus': 1,
                'stat_charisma_bonus': 1,
            },
            6: {
                'name': 'Deep Core Forge', 'cost': 35247, 'build_time_days': 11,
                'generation_rate': 124.0, 'science_generation_rate': 5.5,
                'image_url': '',
                'stat_exploration_bonus': 2,
                'stat_leadership_bonus': 2,
                'stat_strategy_bonus': 2,
                'stat_logistics_bonus': 2,
                'stat_charisma_bonus': 2,
            },
            7: {
                'name': 'Resonant Forge', 'cost': 39477, 'build_time_days': 12,
                'generation_rate': 149.0, 'science_generation_rate': 6.0,
                'image_url': '',
                'stat_exploration_bonus': 3,
                'stat_leadership_bonus': 3,
                'stat_strategy_bonus': 3,
                'stat_logistics_bonus': 3,
                'stat_charisma_bonus': 3,
            },
            8: {
                'name': 'Sepolia Forge Complex', 'cost': 54640, 'build_time_days': 13,
                'generation_rate': 178.0, 'science_generation_rate': 7.0,
                'image_url': '',
                'stat_exploration_bonus': 4,
                'stat_leadership_bonus': 4,
                'stat_strategy_bonus': 4,
                'stat_logistics_bonus': 4,
                'stat_charisma_bonus': 4,
            },
            9: {
                'name': 'Ancient Forge', 'cost': 61197, 'build_time_days': 14,
                'generation_rate': 214.0, 'science_generation_rate': 8.0,
                'image_url': '',
                'stat_exploration_bonus': 5,
                'stat_leadership_bonus': 5,
                'stat_strategy_bonus': 5,
                'stat_logistics_bonus': 5,
                'stat_charisma_bonus': 5,
            },
            10: {
                'name': 'Monolithic Forge', 'cost': 68540, 'build_time_days': 14,
                'generation_rate': 257.0, 'science_generation_rate': 9.0,
                'image_url': '',
                'stat_exploration_bonus': 6,
                'stat_leadership_bonus': 6,
                'stat_strategy_bonus': 6,
                'stat_logistics_bonus': 6,
                'stat_charisma_bonus': 6,
            },
        }
    },

    'resonance_chamber': {
        'name': 'Sepolia Resonance Chamber',
        'description': 'Amplifies Sepolia shard resonance frequencies',
        'icon': '\U0001f4a0',  # 💠
        'category': 'power',
        'generates_resource': 'sepolia',
        'max_level': 10,
        'default_level': 0,
        'requirements': ['regolith_forge'],
        'unlock_requirements': {'regolith_forge': 5},  # Unlocks when forge hits Lv5
        'levels': {
            1: {
                'name': 'Basic Chamber', 'cost': 80000, 'build_time_days': 0.042,
                'generation_rate': 100.0, 'science_generation_rate': 5.0,
                'all_generation_mult': 1.15,
                'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/infrastructure_items/resonance_chamber_1770262697.png',
            },
            2: {
                'name': 'Tuned Chamber', 'cost': 89600, 'build_time_days': 9,
                'generation_rate': 115.0, 'science_generation_rate': 5.5,
                'all_generation_mult': 1.18,
                'image_url': '',
            },
            3: {
                'name': 'Harmonic Chamber', 'cost': 100352, 'build_time_days': 10,
                'generation_rate': 132.0, 'science_generation_rate': 6.0,
                'all_generation_mult': 1.21,
                'image_url': '',
            },
            4: {
                'name': 'Crystal Resonator', 'cost': 112394, 'build_time_days': 11,
                'generation_rate': 152.0, 'science_generation_rate': 6.5,
                'all_generation_mult': 1.25,
                'image_url': '',
            },
            5: {
                'name': 'Deep Resonance Array', 'cost': 125882, 'build_time_days': 12,
                'generation_rate': 175.0, 'science_generation_rate': 7.0,
                'all_generation_mult': 1.28,
                'image_url': '',
                'stat_exploration_bonus': 1,
                'stat_leadership_bonus': 1,
                'stat_strategy_bonus': 1,
                'stat_logistics_bonus': 1,
                'stat_charisma_bonus': 1,
            },
            6: {
                'name': 'Sepolia Amplifier', 'cost': 140988, 'build_time_days': 12,
                'generation_rate': 201.0, 'science_generation_rate': 7.5,
                'all_generation_mult': 1.32,
                'image_url': '',
                'stat_exploration_bonus': 2,
                'stat_leadership_bonus': 2,
                'stat_strategy_bonus': 2,
                'stat_logistics_bonus': 2,
                'stat_charisma_bonus': 2,
            },
            7: {
                'name': 'Quantum Chamber', 'cost': 157906, 'build_time_days': 13,
                'generation_rate': 231.0, 'science_generation_rate': 8.0,
                'all_generation_mult': 1.36,
                'image_url': '',
                'stat_exploration_bonus': 3,
                'stat_leadership_bonus': 3,
                'stat_strategy_bonus': 3,
                'stat_logistics_bonus': 3,
                'stat_charisma_bonus': 3,
            },
            8: {
                'name': 'Ancient Resonance Core', 'cost': 176855, 'build_time_days': 13,
                'generation_rate': 266.0, 'science_generation_rate': 9.0,
                'all_generation_mult': 1.40,
                'image_url': '',
                'stat_exploration_bonus': 4,
                'stat_leadership_bonus': 4,
                'stat_strategy_bonus': 4,
                'stat_logistics_bonus': 4,
                'stat_charisma_bonus': 4,
            },
            9: {
                'name': 'Planetary Harmonics', 'cost': 198078, 'build_time_days': 14,
                'generation_rate': 306.0, 'science_generation_rate': 10.0,
                'all_generation_mult': 1.45,
                'image_url': '',
                'stat_exploration_bonus': 5,
                'stat_leadership_bonus': 5,
                'stat_strategy_bonus': 5,
                'stat_logistics_bonus': 5,
                'stat_charisma_bonus': 5,
            },
            10: {
                'name': 'Monolithic Resonance', 'cost': 221847, 'build_time_days': 14,
                'generation_rate': 352.0, 'science_generation_rate': 11.0,
                'all_generation_mult': 1.50,
                'image_url': '',
                'stat_exploration_bonus': 6,
                'stat_leadership_bonus': 6,
                'stat_strategy_bonus': 6,
                'stat_logistics_bonus': 6,
                'stat_charisma_bonus': 6,
            },
        }
    },

    'thermal_vent_tap': {
        'name': 'Thermal Vent Tap',
        'description': 'Taps deep thermal vents for constant Sepolia shard excitation',
        'icon': '\U0001f30b',  # 🌋
        'category': 'extraction',
        'generates_resource': 'sepolia',
        'max_level': 10,
        'default_level': 0,
        'requirements': ['resonance_chamber'],
        'unlock_requirements': {'resonance_chamber': 5},  # Unlocks when chamber hits Lv5
        'levels': {
            1: {
                'name': 'Basic Vent Tap', 'cost': 250000, 'build_time_days': 0.042,
                'generation_rate': 200.0, 'science_generation_rate': 8.0,
                'dust_storm_immune': True,
                'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/infrastructure_items/thermal_vent_tap_1770262697.png',
            },
            2: {
                'name': 'Improved Tap', 'cost': 280000, 'build_time_days': 11,
                'generation_rate': 230.0, 'science_generation_rate': 9.0,
                'dust_storm_immune': True,
                'image_url': '',
            },
            3: {
                'name': 'Deep Vent Bore', 'cost': 313600, 'build_time_days': 11,
                'generation_rate': 265.0, 'science_generation_rate': 10.0,
                'dust_storm_immune': True,
                'image_url': '',
            },
            4: {
                'name': 'Thermal Extractor', 'cost': 351232, 'build_time_days': 12,
                'generation_rate': 305.0, 'science_generation_rate': 11.0,
                'dust_storm_immune': True,
                'image_url': '',
            },
            5: {
                'name': 'Crystal-Cooled Tap', 'cost': 393380, 'build_time_days': 12,
                'generation_rate': 350.0, 'science_generation_rate': 12.0,
                'dust_storm_immune': True,
                'image_url': '',
                'stat_exploration_bonus': 1,
                'stat_leadership_bonus': 1,
                'stat_strategy_bonus': 1,
                'stat_logistics_bonus': 1,
                'stat_charisma_bonus': 1,
            },
            6: {
                'name': 'Geothermal Complex', 'cost': 440586, 'build_time_days': 13,
                'generation_rate': 403.0, 'science_generation_rate': 13.0,
                'dust_storm_immune': True,
                'image_url': '',
                'stat_exploration_bonus': 2,
                'stat_leadership_bonus': 2,
                'stat_strategy_bonus': 2,
                'stat_logistics_bonus': 2,
                'stat_charisma_bonus': 2,
            },
            7: {
                'name': 'Deep Core Tap', 'cost': 493456, 'build_time_days': 13,
                'generation_rate': 463.0, 'science_generation_rate': 14.0,
                'dust_storm_immune': True,
                'image_url': '',
                'stat_exploration_bonus': 3,
                'stat_leadership_bonus': 3,
                'stat_strategy_bonus': 3,
                'stat_logistics_bonus': 3,
                'stat_charisma_bonus': 3,
            },
            8: {
                'name': 'Mantle Extraction', 'cost': 552671, 'build_time_days': 14,
                'generation_rate': 533.0, 'science_generation_rate': 16.0,
                'dust_storm_immune': True,
                'image_url': '',
                'stat_exploration_bonus': 4,
                'stat_leadership_bonus': 4,
                'stat_strategy_bonus': 4,
                'stat_logistics_bonus': 4,
                'stat_charisma_bonus': 4,
            },
            9: {
                'name': 'Planetary Heat Engine', 'cost': 618991, 'build_time_days': 14,
                'generation_rate': 612.0, 'science_generation_rate': 18.0,
                'dust_storm_immune': True,
                'image_url': '',
                'stat_exploration_bonus': 5,
                'stat_leadership_bonus': 5,
                'stat_strategy_bonus': 5,
                'stat_logistics_bonus': 5,
                'stat_charisma_bonus': 5,
            },
            10: {
                'name': 'Monolithic Vent Complex', 'cost': 693270, 'build_time_days': 14,
                'generation_rate': 704.0, 'science_generation_rate': 20.0,
                'dust_storm_immune': True,
                'image_url': '',
                'stat_exploration_bonus': 6,
                'stat_leadership_bonus': 6,
                'stat_strategy_bonus': 6,
                'stat_logistics_bonus': 6,
                'stat_charisma_bonus': 6,
            },
        }
    },

    'monolith_antenna': {
        'name': 'Monolith Antenna',
        'description': 'Ancient resonance array that detects deep Sepolia shard formations',
        'icon': '\U0001f5fc',  # 🗼
        'category': 'research',
        'max_level': 10,
        'default_level': 0,
        'requirements': ['thermal_vent_tap'],
        'unlock_requirements': {'thermal_vent_tap': 5},  # Unlocks when vent tap hits Lv5
        'levels': {
            1: {
                'name': 'Basic Monolith', 'cost': 750000, 'build_time_days': 0.042,
                'generation_rate': 500.0, 'science_generation_rate': 12.0,
                'legendary_discovery_chance': 0.05,
                'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/infrastructure_items/monolith_antenna_1770262697.png',
            },
            2: {
                'name': 'Tuned Monolith', 'cost': 840000, 'build_time_days': 12,
                'generation_rate': 560.0, 'science_generation_rate': 13.0,
                'legendary_discovery_chance': 0.06,
                'image_url': '',
            },
            3: {
                'name': 'Resonant Spire', 'cost': 940800, 'build_time_days': 13,
                'generation_rate': 627.0, 'science_generation_rate': 15.0,
                'legendary_discovery_chance': 0.07,
                'image_url': '',
            },
            4: {
                'name': 'Crystal Monolith', 'cost': 1053696, 'build_time_days': 13,
                'generation_rate': 702.0, 'science_generation_rate': 17.0,
                'legendary_discovery_chance': 0.08,
                'image_url': '',
            },
            5: {
                'name': 'Deep Signal Tower', 'cost': 1180139, 'build_time_days': 13,
                'generation_rate': 787.0, 'science_generation_rate': 19.0,
                'legendary_discovery_chance': 0.09,
                'image_url': '',
                'stat_exploration_bonus': 1,
                'stat_leadership_bonus': 1,
                'stat_strategy_bonus': 1,
                'stat_logistics_bonus': 1,
                'stat_charisma_bonus': 1,
            },
            6: {
                'name': 'Ancient Spire', 'cost': 1321756, 'build_time_days': 14,
                'generation_rate': 881.0, 'science_generation_rate': 21.0,
                'legendary_discovery_chance': 0.10,
                'image_url': '',
                'stat_exploration_bonus': 2,
                'stat_leadership_bonus': 2,
                'stat_strategy_bonus': 2,
                'stat_logistics_bonus': 2,
                'stat_charisma_bonus': 2,
            },
            7: {
                'name': 'Sepolia Beacon', 'cost': 1480367, 'build_time_days': 14,
                'generation_rate': 987.0, 'science_generation_rate': 24.0,
                'legendary_discovery_chance': 0.11,
                'image_url': '',
                'stat_exploration_bonus': 3,
                'stat_leadership_bonus': 3,
                'stat_strategy_bonus': 3,
                'stat_logistics_bonus': 3,
                'stat_charisma_bonus': 3,
            },
            8: {
                'name': 'Planetary Resonator', 'cost': 1658011, 'build_time_days': 14,
                'generation_rate': 1105.0, 'science_generation_rate': 27.0,
                'legendary_discovery_chance': 0.12,
                'image_url': '',
                'stat_exploration_bonus': 4,
                'stat_leadership_bonus': 4,
                'stat_strategy_bonus': 4,
                'stat_logistics_bonus': 4,
                'stat_charisma_bonus': 4,
            },
            9: {
                'name': 'Ancient Signal Core', 'cost': 1856972, 'build_time_days': 14,
                'generation_rate': 1238.0, 'science_generation_rate': 30.0,
                'legendary_discovery_chance': 0.14,
                'image_url': '',
                'stat_exploration_bonus': 5,
                'stat_leadership_bonus': 5,
                'stat_strategy_bonus': 5,
                'stat_logistics_bonus': 5,
                'stat_charisma_bonus': 5,
            },
            10: {
                'name': 'Cosmic Monolith', 'cost': 2079809, 'build_time_days': 14,
                'generation_rate': 1386.0, 'science_generation_rate': 35.0,
                'legendary_discovery_chance': 0.15,
                'image_url': '',
                'stat_exploration_bonus': 6,
                'stat_leadership_bonus': 6,
                'stat_strategy_bonus': 6,
                'stat_logistics_bonus': 6,
                'stat_charisma_bonus': 6,
            },
        }
    },

    # =========================================================================
    # ROBOTICS — workshop that turns recovered Martian salvage into a robot
    # See utilities/db_robot.py + plan decision #14 (Sepolia ARG breadcrumbs).
    # Each level shortens robot stage assembly time via robot_build_speed_mult.
    # =========================================================================
    'robotics_lab': {
        'name': 'Narog Foundry',
        'description': 'Workshop where recovered Martian salvage is forged into an autonomous robot. Each Foundry level raises every Narog stat linearly from 5/100 to 100/100.',
        'icon': '\U0001f916',  # 🤖
        'category': 'research',
        'max_level': 10,
        'default_level': 0,
        'requirements': ['research_station', 'regolith_forge'],
        'unlock_requirements': {'research_station': 3, 'regolith_forge': 3},
        # Per-level upgrade prereqs (Bug #1436, Luke 2026-05-06).
        # Foundry L3 also unlocks the Narog's Logistics stat slot;
        # L6 unlocks Research; L9 unlocks Expeditions. See robot.py
        # STAT_UNLOCK_FOUNDRY_LEVEL.
        'levels': {
            1: {
                'name': 'Salvage Workbench', 'cost': 150000, 'build_time_days': 7,
                'robot_unlocked': True, 'robot_build_speed_mult': 1.00,
                'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/infrastructure_items/robotics_lab_1775872908.png',
            },
            2: {
                'name': 'Assembly Bay', 'cost': 168000, 'build_time_days': 8,
                'robot_unlocked': True, 'robot_build_speed_mult': 1.10,
                'image_url': '',
            },
            3: {
                'name': 'Calibration Pit', 'cost': 188160, 'build_time_days': 9,
                'robot_unlocked': True, 'robot_build_speed_mult': 1.20,
                'level_requires': {'habitat_module': 3},  # #1436 Luke
                'image_url': '',
            },
            4: {
                'name': 'Manipulator Forge', 'cost': 210739, 'build_time_days': 10,
                'robot_unlocked': True, 'robot_build_speed_mult': 1.30,
                'image_url': '',
            },
            5: {
                'name': 'Servo Atelier', 'cost': 236028, 'build_time_days': 11,
                'robot_unlocked': True, 'robot_build_speed_mult': 1.40,
                'image_url': '',
            },
            6: {
                'name': 'Crystal-Servo Lab', 'cost': 264352, 'build_time_days': 12,
                'robot_unlocked': True, 'robot_build_speed_mult': 1.50,
                'level_requires': {'research_station': 6, 'greenhouse': 6},  # #1436 Luke
                'image_url': '',
            },
            7: {
                'name': 'Resonant Assembly', 'cost': 296074, 'build_time_days': 13,
                'robot_unlocked': True, 'robot_build_speed_mult': 1.65,
                'image_url': '',
            },
            8: {
                'name': 'Cognition Chamber', 'cost': 331603, 'build_time_days': 13,
                'robot_unlocked': True, 'robot_build_speed_mult': 1.80,
                'image_url': '',
            },
            9: {
                'name': 'Autonomy Reactor', 'cost': 371396, 'build_time_days': 14,
                'robot_unlocked': True, 'robot_build_speed_mult': 1.90,
                'level_requires': {'habitat_module': 9, 'greenhouse': 9, 'research_station': 9},  # #1436 Luke
                'image_url': '',
            },
            10: {
                'name': 'Sentient Forge', 'cost': 415963, 'build_time_days': 14,
                'robot_unlocked': True, 'robot_build_speed_mult': 2.00,
                'image_url': '',
            },
        }
    },
}


def get_infrastructure_item_config(building_key: str) -> dict:
    """Get config for an infrastructure building"""
    return INFRASTRUCTURE_CATALOG.get(building_key)


def get_infrastructure_level_stats(building_key: str, level: int) -> dict:
    """Get stats for a building at a specific level"""
    item = get_infrastructure_item_config(building_key)
    if not item:
        return None
    return item.get('levels', {}).get(level)


def get_infrastructure_upgrade_cost(building_key: str, target_level: int) -> int:
    """Get the cost to upgrade to a specific level"""
    stats = get_infrastructure_level_stats(building_key, target_level)
    return stats.get('cost', 0) if stats else 0


def get_infrastructure_build_time(building_key: str, target_level: int) -> int:
    """Get build time in seconds for a specific level"""
    stats = get_infrastructure_level_stats(building_key, target_level)
    if not stats:
        return 0
    days = stats.get('build_time_days', 0)
    return days * 86400  # Convert to seconds
