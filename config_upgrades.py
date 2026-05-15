##############################################################################
# UPGRADE CATALOG - 11 upgrade paths x 10 levels each
# Formula: Cost(n) = round(BaseCost * 1.12^(n-1))
# Build times: 0 -> 14 days max
# Level 0 = locked/not owned, Level 1+ = owned and upgraded
##############################################################################

UPGRADE_CATALOG = {
    # =========================================================================
    # VEHICLES - Expedition transport
    # =========================================================================
    'vehicles': {
        'rover': {
            'name': 'Rover',
            'description': 'Primary expedition vehicle for surface exploration',
            'icon': '\U0001f697',
            'max_level': 10,
            'default_level': 1,
            'levels': {
                1: {
                    'name': 'Scout Rover', 'cost': 0,
                    'cargo': 10, 'expedition_speed_mult': 5.2, 'max_range_km': 300, 'fuel_cost_mult': 1.0,
                    'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/shop_items/rover_basic_1767505567.png',
                },
                2: {
                    'name': 'Explorer Rover', 'cost': 500, 'build_time_days': 1,
                    'cargo': 11, 'expedition_speed_mult': 6.3, 'max_range_km': 350, 'fuel_cost_mult': 1.0,
                    'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/test_generation/kontext_progression_rover_lv2_1770243244.png',
                },
                3: {
                    'name': 'Expedition Rover', 'cost': 560, 'build_time_days': 2,
                    'cargo': 12, 'expedition_speed_mult': 7.5, 'max_range_km': 400, 'fuel_cost_mult': 1.0,
                    'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/test_generation/kontext_progression_rover_lv3_1770243260.png',
                },
                4: {
                    'name': 'Terrain Rover', 'cost': 4128, 'build_time_days': 3,
                    'cargo': 13, 'expedition_speed_mult': 8.6, 'max_range_km': 500, 'fuel_cost_mult': 0.95,
                    'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/test_generation/kontext_progression_rover_lv4_1770243276.png',
                },
                5: {
                    'name': 'Regolith Rover', 'cost': 4623, 'build_time_days': 5,
                    'cargo': 14, 'expedition_speed_mult': 9.8, 'max_range_km': 600, 'fuel_cost_mult': 0.95,
                    'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/test_generation/kontext_progression_rover_lv5_1770243293.png',
                },
                6: {
                    'name': 'Basalt Rover', 'cost': 5178, 'build_time_days': 7,
                    'cargo': 16, 'expedition_speed_mult': 11.5, 'max_range_km': 700, 'fuel_cost_mult': 0.90,
                    'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/test_generation/kontext_progression_rover_lv6_1770243311.png',
                },
                7: {
                    'name': 'Stone Rover', 'cost': 5800, 'build_time_days': 9,
                    'cargo': 17, 'expedition_speed_mult': 12.6, 'max_range_km': 800, 'fuel_cost_mult': 0.90,
                    'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/test_generation/kontext_progression_rover_lv7_1770243327.png',
                },
                8: {
                    'name': 'Dust Rover', 'cost': 382480, 'build_time_days': 11,
                    'cargo': 19, 'expedition_speed_mult': 13.8, 'max_range_km': 950, 'fuel_cost_mult': 0.85,
                    'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/test_generation/kontext_progression_rover_lv8_1770243348.png',
                },
                9: {
                    'name': 'Leviathan Rover', 'cost': 428378, 'build_time_days': 13,
                    'cargo': 21, 'expedition_speed_mult': 15.5, 'max_range_km': 1100, 'fuel_cost_mult': 0.80,
                    'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/test_generation/kontext_progression_rover_lv9_1770243365.png',
                },
                10: {
                    'name': 'Titan Rover', 'cost': 479783, 'build_time_days': 14,
                    'cargo': 24, 'expedition_speed_mult': 17.2, 'max_range_km': 1200, 'fuel_cost_mult': 0.75,
                    'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/test_generation/kontext_progression_rover_lv10_1770243382.png',
                },
            }
        },
        'drone': {
            'name': 'Drone',
            'description': 'Fast aerial scout - low cargo, poor discoveries, but quick',
            'icon': '\U0001f6f8',
            'max_level': 10,
            'default_level': 0,
            'levels': {
                1: {
                    'name': 'Drone Mk I', 'cost': 5000, 'build_time_days': 0.042,
                    'cargo': 4, 'expedition_speed_mult': 11.0, 'max_range_km': 150, 'fuel_cost_mult': 1.10,
                    'discovery_bonus': -0.20, 'rare_bonus': -0.50, 'legendary_bonus': -1.0,
                    'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/upgrades/vehicles_drone_lv1_1767751017.png',
                },
                2: {
                    'name': 'Drone Mk II', 'cost': 5600, 'build_time_days': 3,
                    'cargo': 5, 'expedition_speed_mult': 12.1, 'max_range_km': 180, 'fuel_cost_mult': 1.05,
                    'discovery_bonus': -0.15, 'rare_bonus': -0.40, 'legendary_bonus': -1.0,
                    'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/test_generation/kontext_drone_lv2_1770243753.png',
                },
                3: {
                    'name': 'Drone Mk III', 'cost': 6272, 'build_time_days': 4,
                    'cargo': 6, 'expedition_speed_mult': 12.6, 'max_range_km': 220, 'fuel_cost_mult': 1.0,
                    'discovery_bonus': -0.10, 'rare_bonus': -0.25, 'legendary_bonus': -1.0,
                    'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/test_generation/kontext_drone_lv3_1770243770.png',
                },
                4: {
                    'name': 'Drone Mk IV', 'cost': 7025, 'build_time_days': 5,
                    'cargo': 6, 'expedition_speed_mult': 13.7, 'max_range_km': 260, 'fuel_cost_mult': 1.0,
                    'discovery_bonus': -0.05, 'rare_bonus': -0.15, 'legendary_bonus': -0.50,
                    'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/test_generation/kontext_drone_lv4_1770243786.png',
                },
                5: {
                    'name': 'Drone Mk V', 'cost': 7868, 'build_time_days': 7,
                    'cargo': 7, 'expedition_speed_mult': 14.2, 'max_range_km': 300, 'fuel_cost_mult': 0.95,
                    'discovery_bonus': 0, 'rare_bonus': -0.10, 'legendary_bonus': -0.50,
                    'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/test_generation/kontext_drone_lv5_1770243802.png',
                },
                6: {
                    'name': 'Drone Mk VI', 'cost': 8812, 'build_time_days': 8,
                    'cargo': 7, 'expedition_speed_mult': 15.2, 'max_range_km': 350, 'fuel_cost_mult': 0.95,
                    'discovery_bonus': 0, 'rare_bonus': 0, 'legendary_bonus': -0.25,
                    'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/test_generation/kontext_drone_lv6_1770243818.png',
                },
                7: {
                    'name': 'Drone Mk VII', 'cost': 9869, 'build_time_days': 10,
                    'cargo': 8, 'expedition_speed_mult': 15.8, 'max_range_km': 400, 'fuel_cost_mult': 0.90,
                    'discovery_bonus': 0.05, 'rare_bonus': 0, 'legendary_bonus': -0.10,
                    'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/test_generation/kontext_drone_lv7_1770243834.png',
                },
                8: {
                    'name': 'Drone Mk VIII', 'cost': 382480, 'build_time_days': 11,
                    'cargo': 8, 'expedition_speed_mult': 16.8, 'max_range_km': 450, 'fuel_cost_mult': 0.90,
                    'discovery_bonus': 0.05, 'rare_bonus': 0.05, 'legendary_bonus': 0,
                    'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/test_generation/kontext_drone_lv8_1770243850.png',
                },
                9: {
                    'name': 'Drone Mk IX', 'cost': 428378, 'build_time_days': 13,
                    'cargo': 9, 'expedition_speed_mult': 18.9, 'max_range_km': 500, 'fuel_cost_mult': 0.85,
                    'discovery_bonus': 0.10, 'rare_bonus': 0.05, 'legendary_bonus': 0.02,
                    'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/test_generation/kontext_drone_lv9_1770243867.png',
                },
                10: {
                    'name': 'Drone Mk X', 'cost': 479783, 'build_time_days': 14,
                    'cargo': 10, 'expedition_speed_mult': 20.5, 'max_range_km': 600, 'fuel_cost_mult': 0.85,
                    'discovery_bonus': 0.10, 'rare_bonus': 0.10, 'legendary_bonus': 0.05,
                    'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/test_generation/kontext_drone_lv10_1770243884.png',
                },
            }
        },
        'buggy': {
            'name': 'Buggy',
            'description': 'Fast and efficient - ideal for return visits and grinding',
            'icon': '\U0001faa8',
            'max_level': 10,
            'default_level': 0,
            'levels': {
                1: {
                    'name': 'Recon Buggy', 'cost': 5000, 'build_time_days': 0.042,
                    'cargo': 6, 'expedition_speed_mult': 11.7, 'max_range_km': 1500, 'fuel_cost_mult': 0.90,
                    'discovery_bonus': 0, 'rare_bonus': -0.10, 'legendary_bonus': -0.25,
                    'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/upgrades/vehicles_buggy_lv1_1768788998.png',
                    'longhaul_image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/upgrades/vehicles_buggy_lv1_1768788998.png',
                },
                2: {
                    'name': 'Desert Buggy', 'cost': 5600, 'build_time_days': 3,
                    'cargo': 7, 'expedition_speed_mult': 13.0, 'max_range_km': 1800, 'fuel_cost_mult': 0.88,
                    'discovery_bonus': 0, 'rare_bonus': -0.05, 'legendary_bonus': -0.20,
                    'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/upgrades/vehicles_buggy_lv2_1768789121.png',
                    'longhaul_image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/upgrades/vehicles_buggy_lv2_1768789121.png',
                },
                3: {
                    'name': 'Dune Buggy', 'cost': 6272, 'build_time_days': 4,
                    'cargo': 8, 'expedition_speed_mult': 13.7, 'max_range_km': 2100, 'fuel_cost_mult': 0.85,
                    'discovery_bonus': 0, 'rare_bonus': 0, 'legendary_bonus': -0.15,
                    'image_url': '',
                    'longhaul_image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/upgrades/vehicles_buggy_lv3_longhaul_1774558936.png',
                },
                4: {
                    'name': 'Canyon Buggy', 'cost': 7025, 'build_time_days': 5,
                    'cargo': 8, 'expedition_speed_mult': 15.0, 'max_range_km': 2400, 'fuel_cost_mult': 0.83,
                    'discovery_bonus': 0.02, 'rare_bonus': 0, 'legendary_bonus': -0.10,
                    'image_url': '',
                    'longhaul_image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/upgrades/vehicles_buggy_lv4_longhaul_1774558941.png',
                },
                5: {
                    'name': 'Frontier Buggy', 'cost': 7868, 'build_time_days': 7,
                    'cargo': 9, 'expedition_speed_mult': 15.6, 'max_range_km': 2700, 'fuel_cost_mult': 0.80,
                    'discovery_bonus': 0.05, 'rare_bonus': 0, 'legendary_bonus': -0.05,
                    'image_url': '',
                    'longhaul_image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/upgrades/vehicles_buggy_lv5_longhaul_1774558947.png',
                },
                6: {
                    'name': 'Valles Buggy', 'cost': 8812, 'build_time_days': 8,
                    'cargo': 9, 'expedition_speed_mult': 16.9, 'max_range_km': 3000, 'fuel_cost_mult': 0.78,
                    'discovery_bonus': 0.05, 'rare_bonus': 0.02, 'legendary_bonus': 0,
                    'image_url': '',
                    'longhaul_image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/upgrades/vehicles_buggy_lv6_longhaul_1774559035.png',
                },
                7: {
                    'name': 'Storm Buggy', 'cost': 9869, 'build_time_days': 10,
                    'cargo': 10, 'expedition_speed_mult': 17.6, 'max_range_km': 3300, 'fuel_cost_mult': 0.75,
                    'discovery_bonus': 0.08, 'rare_bonus': 0.05, 'legendary_bonus': 0,
                    'image_url': '',
                    'longhaul_image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/upgrades/vehicles_buggy_lv7_longhaul_1774559120.png',
                },
                8: {
                    'name': 'Olympus Buggy', 'cost': 382480, 'build_time_days': 11,
                    'cargo': 10, 'expedition_speed_mult': 18.9, 'max_range_km': 3600, 'fuel_cost_mult': 0.73,
                    'discovery_bonus': 0.08, 'rare_bonus': 0.05, 'legendary_bonus': 0.02,
                    'image_url': '',
                    'longhaul_image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/upgrades/vehicles_buggy_lv8_longhaul_1774559221.png',
                },
                9: {
                    'name': 'Polar Buggy', 'cost': 428378, 'build_time_days': 13,
                    'cargo': 11, 'expedition_speed_mult': 19.5, 'max_range_km': 4000, 'fuel_cost_mult': 0.70,
                    'discovery_bonus': 0.10, 'rare_bonus': 0.08, 'legendary_bonus': 0.03,
                    'image_url': '',
                    'longhaul_image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/upgrades/vehicles_buggy_lv9_longhaul_1774559350.png',
                },
                10: {
                    'name': 'Phantom Buggy', 'cost': 479783, 'build_time_days': 14,
                    'cargo': 12, 'expedition_speed_mult': 21.4, 'max_range_km': 4500, 'fuel_cost_mult': 0.68,
                    'discovery_bonus': 0.10, 'rare_bonus': 0.10, 'legendary_bonus': 0.05,
                    'image_url': '',
                    'longhaul_image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/upgrades/vehicles_buggy_lv10_longhaul_1774559470.png',
                },
            }
        },
    },

    # =========================================================================
    # EQUIPMENT - Scanners, life support, cargo
    # =========================================================================
    'equipment': {
        'scanner': {
            'name': 'Scanner',
            'description': 'Ground-penetrating radar for discovery detection',
            'icon': '\U0001f4e1',
            'max_level': 10,
            'default_level': 1,
            'levels': {
                1: {
                    'name': 'Surface Scanner', 'cost': 0,
                    'discovery_chance_bonus': 0.10, 'rare_chance_bonus': 0, 'legendary_chance_bonus': 0,
                    'vehicle_range_mult': 1.00,
                    'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/shop_items/scanner_basic_1767505603.png',
                },
                2: {
                    'name': 'Deep Core Scanner', 'cost': 300, 'build_time_days': 1,
                    'discovery_chance_bonus': 0.15, 'rare_chance_bonus': 0.03, 'legendary_chance_bonus': 0,
                    'vehicle_range_mult': 1.03,
                    'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/shop_items/scanner_deep_1767505613.png',
                },
                3: {
                    'name': 'Resonance Array', 'cost': 336, 'build_time_days': 2,
                    'discovery_chance_bonus': 0.20, 'rare_chance_bonus': 0.05, 'legendary_chance_bonus': 0,
                    'vehicle_range_mult': 1.05, 'signal_detection_enabled': True,
                    'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/shop_items/scanner_quantum_1770262697.png',
                },
                4: {
                    'name': 'Harmonic Scanner', 'cost': 4128, 'build_time_days': 3,
                    'discovery_chance_bonus': 0.25, 'rare_chance_bonus': 0.08, 'legendary_chance_bonus': 0.01,
                    'vehicle_range_mult': 1.08, 'signal_detection_enabled': True,
                    'image_url': '',
                },
                5: {
                    'name': 'Seismic Probe', 'cost': 4623, 'build_time_days': 4,
                    'discovery_chance_bonus': 0.30, 'rare_chance_bonus': 0.10, 'legendary_chance_bonus': 0.02,
                    'vehicle_range_mult': 1.12, 'signal_detection_enabled': True,
                    'image_url': '',
                },
                6: {
                    'name': 'Subsurface Imager', 'cost': 5178, 'build_time_days': 6,
                    'discovery_chance_bonus': 0.35, 'rare_chance_bonus': 0.13, 'legendary_chance_bonus': 0.03,
                    'vehicle_range_mult': 1.16, 'signal_detection_enabled': True,
                    'image_url': '',
                },
                7: {
                    'name': 'Regolith Sonar', 'cost': 5800, 'build_time_days': 8,
                    'discovery_chance_bonus': 0.40, 'rare_chance_bonus': 0.16, 'legendary_chance_bonus': 0.03,
                    'vehicle_range_mult': 1.20, 'signal_detection_enabled': True,
                    'image_url': '',
                },
                8: {
                    'name': 'Spectral Analyzer', 'cost': 382480, 'build_time_days': 10,
                    'discovery_chance_bonus': 0.45, 'rare_chance_bonus': 0.20, 'legendary_chance_bonus': 0.04,
                    'vehicle_range_mult': 1.25, 'signal_detection_enabled': True,
                    'image_url': '',
                },
                9: {
                    'name': 'Quantum Resonance Array', 'cost': 428378, 'build_time_days': 12,
                    'discovery_chance_bonus': 0.50, 'rare_chance_bonus': 0.23, 'legendary_chance_bonus': 0.04,
                    'vehicle_range_mult': 1.30, 'signal_detection_enabled': True,
                    'image_url': '',
                },
                10: {
                    'name': 'Omniscient Eye', 'cost': 479783, 'build_time_days': 14,
                    'discovery_chance_bonus': 0.55, 'rare_chance_bonus': 0.25, 'legendary_chance_bonus': 0.05,
                    'vehicle_range_mult': 1.35, 'signal_detection_enabled': True,
                    'image_url': '',
                },
            }
        },
        'life_support': {
            'name': 'Life Support',
            'description': 'Oxygen recycling to reduce expedition costs',
            'icon': '\U0001f4a8',
            'max_level': 10,
            'default_level': 0,
            'levels': {
                1: {
                    'name': 'Basic Recycler', 'cost': 600, 'build_time_days': 0.042,
                    'life_support_cost_mult': 0.90,
                    'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/shop_items/life_support_basic_1767506683.png',
                },
                2: {
                    'name': 'Enhanced Recycler', 'cost': 672, 'build_time_days': 1,
                    'life_support_cost_mult': 0.85,
                    'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/shop_items/life_support_advanced_1767506690.png',
                },
                3: {
                    'name': 'Closed-Loop Filter', 'cost': 753, 'build_time_days': 2,
                    'life_support_cost_mult': 0.80,
                    'image_url': '',
                },
                4: {
                    'name': 'Biosphere Module', 'cost': 4128, 'build_time_days': 3,
                    'life_support_cost_mult': 0.75,
                    'image_url': '',
                },
                5: {
                    'name': 'Atmospheric Processor', 'cost': 4623, 'build_time_days': 5,
                    'life_support_cost_mult': 0.70,
                    'image_url': '',
                },
                6: {
                    'name': 'Mars Air Forge', 'cost': 5178, 'build_time_days': 7,
                    'life_support_cost_mult': 0.65,
                    'image_url': '',
                },
                7: {
                    'name': 'Regolith Breather', 'cost': 5800, 'build_time_days': 9,
                    'life_support_cost_mult': 0.60,
                    'image_url': '',
                },
                8: {
                    'name': 'Deep Filter Array', 'cost': 382480, 'build_time_days': 10,
                    'life_support_cost_mult': 0.55,
                    'image_url': '',
                },
                9: {
                    'name': 'Martian Lung', 'cost': 428378, 'build_time_days': 12,
                    'life_support_cost_mult': 0.52,
                    'image_url': '',
                },
                10: {
                    'name': 'Self-Sustaining Hab', 'cost': 479783, 'build_time_days': 14,
                    'life_support_cost_mult': 0.50,
                    'image_url': '',
                },
            }
        },
        'cargo': {
            'name': 'Cargo Module',
            'description': 'Expand cargo capacity and specimen preservation',
            'icon': '\U0001f4e6',
            'max_level': 10,
            'default_level': 0,
            'levels': {
                1: {
                    'name': 'Cargo Bay I', 'cost': 750, 'build_time_days': 0.042,
                    'cargo_slots': 2, 'bio_discovery_value_mult': 1.0,
                    'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/shop_items/cargo_bay_1767505635.png',
                },
                2: {
                    'name': 'Cargo Bay II', 'cost': 840, 'build_time_days': 2,
                    'cargo_slots': 3, 'bio_discovery_value_mult': 1.05,
                    'image_url': '',
                },
                3: {
                    'name': 'Cargo Bay III', 'cost': 941, 'build_time_days': 3,
                    'cargo_slots': 4, 'bio_discovery_value_mult': 1.10,
                    'image_url': '',
                },
                4: {
                    'name': 'Cryo Storage I', 'cost': 4128, 'build_time_days': 4,
                    'cargo_slots': 5, 'bio_discovery_value_mult': 1.10,
                    'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/shop_items/cargo_refrigerated_1770262697.png',
                },
                5: {
                    'name': 'Cryo Storage II', 'cost': 4623, 'build_time_days': 6,
                    'cargo_slots': 6, 'bio_discovery_value_mult': 1.15,
                    'image_url': '',
                },
                6: {
                    'name': 'Specimen Hold', 'cost': 5178, 'build_time_days': 7,
                    'cargo_slots': 7, 'bio_discovery_value_mult': 1.15,
                    'image_url': '',
                },
                7: {
                    'name': 'Deep Specimen Hold', 'cost': 5800, 'build_time_days': 9,
                    'cargo_slots': 8, 'bio_discovery_value_mult': 1.20,
                    'image_url': '',
                },
                8: {
                    'name': 'Heavy Cargo Module', 'cost': 382480, 'build_time_days': 10,
                    'cargo_slots': 9, 'bio_discovery_value_mult': 1.20,
                    'image_url': '',
                },
                9: {
                    'name': 'Expedition Hold', 'cost': 428378, 'build_time_days': 12,
                    'cargo_slots': 10, 'bio_discovery_value_mult': 1.25,
                    'image_url': '',
                },
                10: {
                    'name': 'Mars Vault', 'cost': 479783, 'build_time_days': 14,
                    'cargo_slots': 12, 'bio_discovery_value_mult': 1.30,
                    'image_url': '',
                },
            }
        },
    },

    # =========================================================================
    # POWER - Passive Sepolia shard generation multiplier
    # =========================================================================
    'power': {
        'generator': {
            'name': 'Shard Generator',
            'description': 'Boost passive Sepolia shard generation rate',
            'icon': '\u2600\ufe0f',
            'max_level': 10,
            'default_level': 0,
            'levels': {
                1: {
                    'name': 'High-Efficiency Panels', 'cost': 1000, 'build_time_days': 0.042,
                    'passive_income_mult': 1.10,
                    'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/shop_items/shard_generator_1770262697.png',
                },
                2: {
                    'name': 'Concentrated Collector', 'cost': 1120, 'build_time_days': 2,
                    'passive_income_mult': 1.15,
                    'image_url': '',
                },
                3: {
                    'name': 'Solar Concentrator', 'cost': 1254, 'build_time_days': 3,
                    'passive_income_mult': 1.21,
                    'image_url': '',
                },
                4: {
                    'name': 'Shard Resonator', 'cost': 4128, 'build_time_days': 4,
                    'passive_income_mult': 1.28,
                    'image_url': '',
                },
                5: {
                    'name': 'Shard Excitation Core', 'cost': 4623, 'build_time_days': 6,
                    'passive_income_mult': 1.33,
                    'image_url': '',
                },
                6: {
                    'name': 'Deep Frequency Array', 'cost': 5178, 'build_time_days': 7,
                    'passive_income_mult': 1.40,
                    'image_url': '',
                },
                7: {
                    'name': 'Resonant Amplifier', 'cost': 5800, 'build_time_days': 9,
                    'passive_income_mult': 1.46,
                    'image_url': '',
                },
                8: {
                    'name': 'Harmonic Exciter', 'cost': 382480, 'build_time_days': 10,
                    'passive_income_mult': 1.54,
                    'image_url': '',
                },
                9: {
                    'name': 'Sepolia Shard Forge', 'cost': 428378, 'build_time_days': 12,
                    'passive_income_mult': 1.60,
                    'image_url': '',
                },
                10: {
                    'name': 'Shard Singularity Core', 'cost': 479783, 'build_time_days': 14,
                    'passive_income_mult': 1.70,
                    'image_url': '',
                },
            }
        },
    },

    # =========================================================================
    # RESEARCH - Discovery value multiplier
    # =========================================================================
    'research': {
        'research': {
            'name': 'Research Lab',
            'description': 'Boost scientific value from discoveries',
            'icon': '\U0001f52d',
            'max_level': 10,
            'default_level': 0,
            'levels': {
                1: {
                    'name': 'Field Lab', 'cost': 1500, 'build_time_days': 0.042,
                    'discovery_value_mult': 1.10,
                    'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/shop_items/research_lab_1767506665.png',
                },
                2: {
                    'name': 'Analysis Module', 'cost': 1680, 'build_time_days': 2,
                    'discovery_value_mult': 1.15,
                    'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/test_generation/kontext_research_lv2_1770244172.png',
                },
                3: {
                    'name': 'Mobile Research Lab', 'cost': 1882, 'build_time_days': 3,
                    'discovery_value_mult': 1.21,
                    'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/test_generation/kontext_research_lv3_1770244193.png',
                },
                4: {
                    'name': 'Specimen Chamber', 'cost': 4128, 'build_time_days': 5,
                    'discovery_value_mult': 1.28,
                    'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/test_generation/kontext_research_lv4_1770244209.png',
                },
                5: {
                    'name': 'Research Center', 'cost': 4623, 'build_time_days': 6,
                    'discovery_value_mult': 1.33,
                    'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/test_generation/kontext_research_lv5_1770244225.png',
                },
                6: {
                    'name': 'Deep Analysis Array', 'cost': 5178, 'build_time_days': 8,
                    'discovery_value_mult': 1.40,
                    'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/test_generation/kontext_research_lv6_1770244241.png',
                },
                7: {
                    'name': 'Martian Institute', 'cost': 5800, 'build_time_days': 9,
                    'discovery_value_mult': 1.46,
                    'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/test_generation/kontext_research_lv7_1770244262.png',
                },
                8: {
                    'name': 'Xenolab Complex', 'cost': 382480, 'build_time_days': 11,
                    'discovery_value_mult': 1.54,
                    'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/test_generation/kontext_research_lv8_1770244279.png',
                },
                9: {
                    'name': 'Advanced Research Hub', 'cost': 428378, 'build_time_days': 13,
                    'discovery_value_mult': 1.60,
                    'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/test_generation/kontext_research_lv9_1770244294.png',
                },
                10: {
                    'name': 'Mars Science Academy', 'cost': 479783, 'build_time_days': 14,
                    'discovery_value_mult': 1.70,
                    'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/test_generation/kontext_research_lv10_1770244310.png',
                },
            }
        },
    },

    # =========================================================================
    # GEAR - Captain stat bonuses (exploration only for now, more suits later)
    # =========================================================================
    'gear': {
        'suit': {
            'name': 'EVA Suit',
            'description': 'Protective gear for Mars exploration - boosts exploration stat and trail building speed (+5%/lv)',
            'icon': '\U0001f9d1\u200d\U0001f680',
            'max_level': 10,
            'default_level': 0,
            'levels': {
                1: {
                    'name': 'Basic EVA Suit', 'cost': 800, 'build_time_days': 0.042,
                    'stat_exploration_bonus': 1,
                    'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/shop_items/suit_exploration_1770262697.png',
                },
                2: {
                    'name': 'Enhanced EVA Suit', 'cost': 896, 'build_time_days': 2,
                    'stat_exploration_bonus': 2,
                    'image_url': '',
                },
                3: {
                    'name': 'Explorer Suit', 'cost': 1004, 'build_time_days': 3,
                    'stat_exploration_bonus': 3,
                    'image_url': '',
                },
                4: {
                    'name': 'Command Suit', 'cost': 4128, 'build_time_days': 4,
                    'stat_exploration_bonus': 4,
                    'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/shop_items/suit_command_1770262697.png',
                },
                5: {
                    'name': 'Hauler Frame', 'cost': 4623, 'build_time_days': 6,
                    'stat_exploration_bonus': 5,
                    'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/shop_items/suit_logistics_1767506726.png',
                },
                6: {
                    'name': 'Tactical Suit', 'cost': 5178, 'build_time_days': 7,
                    'stat_exploration_bonus': 6,
                    'image_url': '',
                },
                7: {
                    'name': 'Regolith Armor', 'cost': 5800, 'build_time_days': 9,
                    'stat_exploration_bonus': 7,
                    'image_url': '',
                },
                8: {
                    'name': 'Mars Exosuit', 'cost': 382480, 'build_time_days': 10,
                    'stat_exploration_bonus': 8,
                    'image_url': '',
                },
                9: {
                    'name': 'Frontier Harness', 'cost': 428378, 'build_time_days': 12,
                    'stat_exploration_bonus': 9,
                    'image_url': '',
                },
                10: {
                    'name': 'Titan Exoframe', 'cost': 479783, 'build_time_days': 14,
                    'stat_exploration_bonus': 10,
                    'image_url': '',
                },
            }
        },
    },

    # =========================================================================
    # MAINTENANCE - Dust cleaning + solar panel protection (bug #1149)
    # Passive income lives on the separate 'mining' path.
    # =========================================================================
    'maintenance': {
        'maintenance': {
            'name': 'Maintenance Drones',
            'description': 'Keeps solar panels clean and protects against dust storms',
            'icon': '\U0001f9f9',
            'max_level': 3,
            'default_level': 0,
            'levels': {
                1: {
                    'name': 'Maintenance Drone', 'cost': 2500, 'build_time_days': 0.042,
                    'dust_storm_immune': False, 'trail_km_per_hour': 0.5,
                    'build_time_mult': 0.98,
                    'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/shop_items/maintenance_drone_1770262697.png',
                },
                2: {
                    'name': 'Sweeper Drone', 'cost': 2800, 'build_time_days': 3,
                    'dust_storm_immune': False, 'trail_km_per_hour': 0.7,
                    'build_time_mult': 0.95,
                    'image_url': '',
                },
                3: {
                    'name': 'Dust Guard', 'cost': 3136, 'build_time_days': 4,
                    'dust_storm_immune': True, 'trail_km_per_hour': 1.0,
                    'build_time_mult': 0.92,
                    'image_url': '',
                },
            }
        },
    },

    # =========================================================================
    # MINING - Passive shard generation (bug #1149)
    # Separate from maintenance; does not clean panels or grant dust immunity.
    # =========================================================================
    'mining': {
        'mining': {
            'name': 'Mining Drones',
            'description': 'Autonomous shard extraction — generates passive income',
            'icon': '\u26cf\ufe0f',
            'max_level': 7,
            'default_level': 0,
            'levels': {
                1: {
                    'name': 'Mining Drone I', 'cost': 3512, 'build_time_days': 6,
                    'passive_income_base': 9, 'trail_km_per_hour': 1.5,
                    'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/shop_items/mining_drone_1767506740.png',
                },
                2: {
                    'name': 'Mining Drone II', 'cost': 3934, 'build_time_days': 7,
                    'passive_income_base': 12, 'trail_km_per_hour': 2.0,
                    'image_url': '',
                },
                3: {
                    'name': 'Extraction Swarm', 'cost': 4406, 'build_time_days': 9,
                    'passive_income_base': 15, 'trail_km_per_hour': 3.0,
                    'image_url': '',
                },
                4: {
                    'name': 'Deep Miner', 'cost': 4935, 'build_time_days': 10,
                    'passive_income_base': 18, 'trail_km_per_hour': 4.0,
                    'image_url': '',
                },
                5: {
                    'name': 'Regolith Processor', 'cost': 5527, 'build_time_days': 11,
                    'passive_income_base': 22, 'trail_km_per_hour': 5.0,
                    'image_url': '',
                },
                6: {
                    'name': 'Autonomous Excavator', 'cost': 6190, 'build_time_days': 13,
                    'passive_income_base': 26, 'trail_km_per_hour': 6.5,
                    'image_url': '',
                },
                7: {
                    'name': 'Mars Mining Matrix', 'cost': 6933, 'build_time_days': 14,
                    'passive_income_base': 30, 'trail_km_per_hour': 8.0,
                    'image_url': '',
                },
            }
        },
    },

    # =========================================================================
    # STORAGE - Discovery capacity
    # =========================================================================
    'storage': {
        'bunker': {
            'name': 'Storage Bunker',
            'description': 'Expand discovery storage capacity',
            'icon': '\U0001f3d7\ufe0f',
            'max_level': 10,
            'default_level': 0,
            'levels': {
                1: {
                    'name': 'Storage Bunker I', 'cost': 2500, 'build_time_days': 0.042,
                    'capacity': 500,
                    'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/upgrades/storage_bunker_lv1_1767751139.png',
                },
                2: {
                    'name': 'Storage Bunker II', 'cost': 2800, 'build_time_days': 2,
                    'capacity': 1000,
                    'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/upgrades/storage_bunker_lv2_1767751147.png',
                },
                3: {
                    'name': 'Storage Bunker III', 'cost': 3136, 'build_time_days': 3,
                    'capacity': 2000,
                    'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/upgrades/storage_bunker_lv3_1767751156.png',
                },
                4: {
                    'name': 'Storage Bunker IV', 'cost': 4128, 'build_time_days': 5,
                    'capacity': 4000,
                    'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/upgrades/storage_bunker_lv4_1767751164.png',
                },
                5: {
                    'name': 'Storage Bunker V', 'cost': 4623, 'build_time_days': 6,
                    'capacity': 7500,
                    'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/upgrades/storage_bunker_lv5_1767751171.png',
                },
                6: {
                    'name': 'Storage Bunker VI', 'cost': 5178, 'build_time_days': 8,
                    'capacity': 15000,
                    'image_url': '',
                },
                7: {
                    'name': 'Storage Bunker VII', 'cost': 5800, 'build_time_days': 9,
                    'capacity': 30000,
                    'image_url': '',
                },
                8: {
                    'name': 'Storage Bunker VIII', 'cost': 382480, 'build_time_days': 11,
                    'capacity': 60000,
                    'image_url': '',
                },
                9: {
                    'name': 'Storage Bunker IX', 'cost': 428378, 'build_time_days': 13,
                    'capacity': 125000,
                    'image_url': '',
                },
                10: {
                    'name': 'Storage Bunker X', 'cost': 479783, 'build_time_days': 14,
                    'capacity': 250000,
                    'image_url': '',
                },
            }
        },
    },
}


def get_upgrade_item_config(category: str, item_key: str) -> dict:
    """Get config for an upgradeable item"""
    return UPGRADE_CATALOG.get(category, {}).get(item_key)


def get_upgrade_level_stats(category: str, item_key: str, level: int) -> dict:
    """Get stats for an item at a specific level"""
    item = get_upgrade_item_config(category, item_key)
    if not item:
        return None
    return item.get('levels', {}).get(level)
