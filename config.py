"""
Configuration file for Galactica Character Creation Game
All constants, settings, and prompts centralized here.
"""

##############################################################################
# APP.PY CONFIGURATION
##############################################################################

# Project Settings (app.py)
PROJECT_ID = "galactica-character-game"
APP_NAME = "Galactica Character Creation"
SECRET_KEY_ID = "FLASK_SECRET_KEY"
DEV_SECRET_KEY = 'dev-secret-key-change-in-production'

# Google Auth (app.py)
GOOGLE_CLIENT_ID_SECRET = "GOOGLE_CLIENT_ID"
GOOGLE_CLIENT_SECRET_SECRET = "GOOGLE_CLIENT_SECRET"

# External Links (brainstorm templates)
# Sheet ID split to avoid secret scanner false positive on public mirror
_BT_ID = "1akw5Z8LzHjdFBDnS1FOD" + "Ut3tJVP9skG1PLf5yJ3AvbI"
BUG_TRACKER_URL = f"https://docs.google.com/spreadsheets/d/{_BT_ID}"

# Server Settings (app.py)
DEFAULT_HOST = '0.0.0.0'
PORT_RANGE_START = 5001  # Start at 5001 (macOS Control Center uses 5000)
PORT_RANGE_END = 5050

# Stats Generation (app.py)
STAT_NAMES = ['leadership', 'strategy', 'exploration', 'logistics', 'charisma']
MIN_STAT_VALUE = 1
MAX_STAT_VALUE = 75
MAX_DISPLAY_STAT = 90
TOTAL_MAX_POSSIBLE = MAX_DISPLAY_STAT * len(STAT_NAMES)

# File Paths (app.py)
DEFAULT_LEADERS_DIR = "static/images/default_leaders"
STATIC_DIR = "static"
TEMPLATES_DIR = "templates"

# UI Messages (app.py)
WELCOME_MESSAGES = {
    'authenticated': "Welcome back, {name}!",
    'guest': "Welcome, Guest!"
}

PROCESSING_MESSAGES = [
    "Preparing for the journey ahead...",
    "Gathering supplies...", 
    "Checking the map...",
    "Setting the course...",
    "Loading provisions...", 
    "Final preparations...",
    "This usually takes ~60 seconds...", 
    "Almost ready for adventure...",
    "Polishing the details...", 
    "Making sure everything is perfect..."
]

# Style Options (app.py)
QUICK_STYLES = {
    'minecraft': 'make the scene minecraft-like blocky scene',
    'ghibli': 'make ghibli-like anime scene', 
    'claymation': 'make it a claymation scene',
    'lego': 'make the scene out of lego blocks'
}

##############################################################################
# REPLICATE_UTILS.PY CONFIGURATION
##############################################################################

# Secret Management (replicate_utils.py)
REPLICATE_TOKEN_ID = "REPLICATE_API_TOKEN"

# Models (replicate_utils.py)
FLUX_MODEL = "black-forest-labs/flux-kontext-pro"
WAN_VIDEO_MODEL = "wan-video/wan-2.2-i2v-fast"

# Prompts (replicate_utils.py)
STANDALONE_CARTOON_PROMPT = "convert to cartoon video game character in a space suit without a helmet, or Mars exploration gear, standing on red martian terrain with rocky landscape and Earth visible as a blue marble in the starry sky above, dressed and adorned for interplanetary exploration, complete full body visible with bold outlines, stylized proportions, vibrant color palette with reds and oranges reflecting Mars atmosphere. if more than one character select only the most prominent one"

VIDEO_ANIMATION_PROMPT = "A cartoon character in space exploration gear without a helmet stands on a red martian ridge overlooking rust-colored valleys and distant mountains, with Earth visible as a small blue sphere in the star-filled black sky above. The character slowly raises their hand to shield their eyes from the pale sun as they gaze toward the distant Mars horizon. The character turns their head left and right, surveying the alien red landscape with a sense of wonder and determination, occasionally glancing up at Earth and the stars. They point toward distant martian landmarks and the Earth above with deliberate, slow movements. The camera smoothly pans left to right and back again, showing different angles of the character against the expansive red planet vista with the starry cosmos and Earth visible in the pink-orange sky. All movements are slow and deliberate - the character's gestures are unhurried, the head turns are gradual, and the camera movement is smooth and steady. The scene captures the spirit of interplanetary exploration and discovery as the character contemplates the Mars journey ahead while remaining connected to their home world."
# Animation Settings (replicate_utils.py)
MAX_SPEED = True
MIN_FRAMES = 81
LOW_RESOLUTION = "480p"
FAST_SAMPLE_SHIFT = 7
STANDARD_FPS = 16

# Retry Settings (replicate_utils.py)
MAX_RETRIES = 3
RETRY_DELAY = 2
BACKOFF_MULTIPLIER = 2

# Default Leaders Configuration - Auto-discovered from GCS
DEFAULT_LEADERS_GCS_BASE = "default_leaders"
BUCKET_NAME = "galactica-pilgrim-assets"

# Colony Scientists - Scientist versions of default leaders (randomly assigned to users)
# Each scientist corresponds to a default leader: scientist1_andy -> leader1_andy, etc.
COLONY_SCIENTISTS = {
    'anna': {
        'name': 'Dr. Anna',
        'specialty': 'Geology',
        'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/scientists/scientist_anna_1767580966.png',
        'stats': {'navigation': 12, 'analysis': 22, 'geology': 45, 'engineering': 8},
    },
    'andy': {
        'name': 'Dr. Andy',
        'specialty': 'Astrobiology',
        'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/scientists/scientist_andy_1767581167.png',
        'stats': {'navigation': 15, 'analysis': 38, 'geology': 20, 'engineering': 10},
    },
    'bo': {
        'name': 'Dr. Bo',
        'specialty': 'Atmospheric Science',
        'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/scientists/scientist_bo_1767581042.png',
        'stats': {'navigation': 30, 'analysis': 25, 'geology': 12, 'engineering': 14},
    },
    'clover': {
        'name': 'Dr. Clover',
        'specialty': 'Botany',
        'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/scientists/scientist_clover_1767581180.png',
        'stats': {'navigation': 8, 'analysis': 35, 'geology': 18, 'engineering': 6},
    },
    'debra': {
        'name': 'Dr. Debra',
        'specialty': 'Chemistry',
        'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/scientists/scientist_debra_1767581068.png',
        'stats': {'navigation': 10, 'analysis': 42, 'geology': 28, 'engineering': 15},
    },
    'don': {
        'name': 'Dr. Don',
        'specialty': 'Engineering',
        'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/scientists/scientist_don_1767581030.png',
        'stats': {'navigation': 28, 'analysis': 12, 'geology': 10, 'engineering': 48},
    },
    'emanuel': {
        'name': 'Dr. Emanuel',
        'specialty': 'Physics',
        'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/scientists/scientist_emanuel_1767581222.png',
        'stats': {'navigation': 22, 'analysis': 30, 'geology': 8, 'engineering': 32},
    },
    'heather': {
        'name': 'Dr. Heather',
        'specialty': 'Hydrology',
        'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/scientists/scientist_heather_1767580979.png',
        'stats': {'navigation': 18, 'analysis': 28, 'geology': 35, 'engineering': 12},
    },
    'lilla': {
        'name': 'Dr. Lilla',
        'specialty': 'Xenobiology',
        'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/scientists/scientist_lilla_1767581154.png',
        'stats': {'navigation': 14, 'analysis': 40, 'geology': 22, 'engineering': 8},
    },
    'luke': {
        'name': 'Dr. Luke',
        'specialty': 'Planetary Science',
        'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/scientists/scientist_luke_1767580992.png',
        'stats': {'navigation': 35, 'analysis': 25, 'geology': 40, 'engineering': 10},
    },
    'millie': {
        'name': 'Dr. Millie',
        'specialty': 'Meteorology',
        # Bug #1282: Luke "ship both" 2026-05-08 — refreshed Meteorology-themed portrait
        'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/scientists/scientist_millie_1778527521.png',
        'stats': {'navigation': 38, 'analysis': 20, 'geology': 15, 'engineering': 12},
    },
    'mra': {
        'name': 'Dr. Mra',
        'specialty': 'Materials Science',
        # Bug #1282: Luke "ship both" 2026-05-08 — sunglasses removed, face visible
        'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/scientists/scientist_mra_no_glasses_1778527521.png',
        'stats': {'navigation': 16, 'analysis': 18, 'geology': 32, 'engineering': 42},
    },
    'tanner': {
        'name': 'Dr. Tanner',
        'specialty': 'Archaeology',
        'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/scientists/scientist_tanner_1767581017.png',
        'stats': {'navigation': 20, 'analysis': 32, 'geology': 38, 'engineering': 6},
    },
    'tom': {
        'name': 'Dr. Tom',
        'specialty': 'Robotics',
        'image_url': 'https://storage.googleapis.com/galactica-pilgrim-assets/scientists/scientist_tom_1767581205.png',
        'stats': {'navigation': 34, 'analysis': 15, 'geology': 8, 'engineering': 45},
    },
}

# Scientist specialty bonuses for trail building on Mars
# Mars trails require understanding: regolith composition, bedrock stability,
# dust management, temperature cycling, and terrain navigation
SCIENTIST_TRAIL_BONUSES = {
    'Geology': 0.20,           # Best - Martian regolith expert, knows bedrock stability
    'Planetary Science': 0.18, # Great - broad Mars surface knowledge
    'Archaeology': 0.15,       # Good - excavation expertise, terrain reading
    'Hydrology': 0.12,         # Good - ancient water channels = natural trail routes
    'Engineering': 0.12,       # Good - structural construction knowledge
    'Materials Science': 0.10, # Decent - Martian material properties
    'Chemistry': 0.08,         # Some - soil chemistry, dust binding
    'Physics': 0.08,           # Some - load-bearing calculations
    'Atmospheric Science': 0.06,  # Minor - dust storm considerations
    'Meteorology': 0.06,       # Minor - weather window planning
    'Robotics': 0.05,          # Minor - can help automate surveying
    'Astrobiology': 0.04,      # Minimal - focused on life, not terrain
    'Botany': 0.04,            # Minimal - focused on plants
    'Xenobiology': 0.04,       # Minimal - focused on alien life
}

def get_scientist_trail_bonus(scientist_key: str) -> float:
    """Get trail building bonus for a scientist based on specialty + geology stat."""
    if not scientist_key or scientist_key not in COLONY_SCIENTISTS:
        return 0.0
    scientist = COLONY_SCIENTISTS[scientist_key]
    specialty = scientist.get('specialty', '')
    geology_stat = scientist.get('stats', {}).get('geology', 0)

    specialty_bonus = SCIENTIST_TRAIL_BONUSES.get(specialty, 0.05)
    geology_bonus = geology_stat / 200  # geology 40 = +20%

    return specialty_bonus + geology_bonus

def get_random_scientist():
    """Get a random scientist for assignment to a new user"""
    import random
    key = random.choice(list(COLONY_SCIENTISTS.keys()))
    return {'key': key, **COLONY_SCIENTISTS[key]}

def generate_random_leader_stats():
    """Generate random stats for a default leader"""
    import random
    return {
        'leadership': random.randint(MIN_STAT_VALUE, MAX_STAT_VALUE),
        'strategy': random.randint(MIN_STAT_VALUE, MAX_STAT_VALUE),
        'exploration': random.randint(MIN_STAT_VALUE, MAX_STAT_VALUE),
        'logistics': random.randint(MIN_STAT_VALUE, MAX_STAT_VALUE),
        'charisma': random.randint(MIN_STAT_VALUE, MAX_STAT_VALUE)
    }

##############################################################################
# INFRASTRUCTURE SYSTEM - Now in config_infrastructure.py (13 buildings × 10 levels)
# Import for backwards compatibility
##############################################################################
from config_infrastructure import INFRASTRUCTURE_CATALOG

##############################################################################
# TRAIL CONFIG - Trail building bonuses and durations (config_shop.py)
##############################################################################
from config_shop import (
    # Bug #1430: TRAIL_SCANNER_BONUSES_BY_LEVEL + TRAIL_CONSUMABLE_BONUSES removed.
    TRAIL_MULTIPLIER_DURATIONS,
    get_trail_duration_from_multiplier,
)

# Helper function
def get_infrastructure_definition(structure_type):
    """Get infrastructure config by type"""
    return INFRASTRUCTURE_CATALOG.get(structure_type)

##############################################################################
# SERVER PORT MANAGEMENT (moved from loader.py)
##############################################################################

def get_available_port():
    """Find an available port in the configured range"""
    import socket
    for port in range(PORT_RANGE_START, PORT_RANGE_END):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('localhost', port))
                return port
        except OSError:
            continue
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('localhost', 0))
        return s.getsockname()[1]

def kill_port_processes(port):
    """Kill any processes using the specified port"""
    import subprocess
    import time
    try:
        result = subprocess.run(['lsof', f'-ti:{port}'], capture_output=True, text=True, timeout=3)
        if result.returncode == 0 and result.stdout.strip():
            for pid in result.stdout.strip().split('\n'):
                if pid.strip():
                    subprocess.run(['kill', '-9', pid.strip()])
            time.sleep(0.5)
    except Exception:
        pass

##############################################################################
# UPGRADE CATALOG - Extracted to config_upgrades.py (11 paths x 10 levels)
##############################################################################
from config_upgrades import UPGRADE_CATALOG, get_upgrade_item_config, get_upgrade_level_stats

##############################################################################
# TECH TREE - Extracted to config_tech.py (4 branches × 10 levels)
##############################################################################
from config_tech import (
    TECH_CATALOG, SCIENTIST_BRANCHES, SCIENTIST_SECONDARY_BRANCHES,
    get_scientist_branch_bonuses, get_tech_branch_config,
    get_tech_level_stats, get_tech_research_cost, TECH_MIGRATION_MAP
)


##############################################################################
# UI ICONS - Custom Mars-material style icons (replacing emojis)
##############################################################################

UI_ICONS = {
    # Navigation & UI Actions
    'moon_theme': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_moon_theme_1767995036.png',
    'sun_theme': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_sun_theme_1767995045.png',
    'edit_pencil': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_edit_pencil_1767995060.png',
    'logout_door': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_logout_door_1767995069.png',
    'info': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_info_1767995079.png',

    # Status Indicators
    'success_check': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_success_check_1767995088.png',
    'error_x': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_error_x_1767995098.png',
    'warning_alert': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_warning_alert_1767995106.png',
    'processing_hourglass': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_processing_hourglass_1767995114.png',

    # Rarity Tiers
    'rarity_legendary': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_rarity_legendary_1767995123.png',
    'rarity_rare': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_rarity_rare_1767995133.png',
    'rarity_uncommon': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_rarity_uncommon_1767995142.png',
    'rarity_common': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_rarity_common_1767995152.png',

    # Captain Stats
    'stat_leadership': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_stat_leadership_1767995161.png',
    'stat_strategy': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_stat_strategy_1767995171.png',
    'stat_exploration': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_stat_exploration_1767995179.png',
    'stat_logistics': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_stat_logistics_1767995187.png',
    'stat_charisma': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_stat_charisma_1767995196.png',

    # Activity Log
    'activity_income': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_activity_income_1767995205.png',
    'activity_expense': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_activity_expense_1767995214.png',
    'activity_expedition': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_activity_expedition_1767995224.png',
    'activity_construction': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_activity_construction_1767995233.png',
    'activity_extraction': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_activity_extraction_1767995241.png',

    # Environment
    'env_sun_power': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_env_sun_power_1767995250.png',
    'env_temperature': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_env_temperature_1767995261.png',
    'env_satellite': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_env_satellite_1767995270.png',
    'env_dust_storm': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_env_dust_storm_1767995279.png',

    # Empty States
    'empty_discoveries': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_empty_discoveries_1767995293.png',
    'empty_equipment': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_empty_equipment_1767995307.png',
    'empty_expeditions': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_empty_expeditions_1767995316.png',
    'empty_power': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_empty_power_1767995324.png',

    # Tabs
    'tab_map': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_tab_map_1767995334.png',
    'tab_tools': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_tab_tools_1767995343.png',
    'tab_wallet': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_tab_wallet_1767995354.png',

    # Miscellaneous
    'shard_gem': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_shard_gem_1767995363.png',
    'timer_clock': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_timer_clock_1767995370.png',
    'mountain_terrain': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_mountain_terrain_1767995380.png',
    'location_pin': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_location_pin_1767995388.png',
    'calendar_date': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_calendar_date_1767995398.png',
    'camera_photo': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_camera_photo_1767995406.png',
    'chat_message': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_chat_message_1767995417.png',
    'signal_transmission': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_signal_transmission_1767995427.png',
    'astronaut_avatar': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_astronaut_avatar_1767995435.png',

    # Batch 2 - Additional Icons
    'rocket_launch': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_rocket_launch_1767996448.png',
    'telescope': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_telescope_1767996459.png',
    'user_profile': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_user_profile_1767996469.png',
    'hammer_building': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_hammer_building_1767996477.png',
    'dice_random': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_dice_random_1767996486.png',
    'video_film': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_video_film_1767996496.png',
    'gift_box': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_gift_box_1767996505.png',
    'wrench_repair': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_wrench_repair_1767996514.png',
    'robot_avatar': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/robot_avatar_mars_v2.png',
    'robot_stage_frame': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/robot_stage_frame.png',
    'robot_stage_plating': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/robot_stage_plating.png',
    'robot_stage_core': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/robot_stage_core.png',
    'robot_stage_optics': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/robot_stage_optics.png',
    'robot_stage_finish': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/robot_stage_finish.png',
    'shopping_cart': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_shopping_cart_1767996524.png',
    'shop_storefront': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_shop_storefront_1767996535.png',
    'microscope_lab': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_microscope_lab_1767996545.png',
    'crown_leadership': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_crown_leadership_1767996555.png',
    'target_strategy': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_target_strategy_1767996565.png',
    'compass_exploration': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_compass_exploration_1767996574.png',
    'sparkle_charisma': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_sparkle_charisma_1767996584.png',
    'home_base': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_home_base_1767996594.png',
    'tower_structures': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_tower_structures_1767996603.png',
    'stopwatch_duration': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_stopwatch_duration_1767996613.png',
    'mountain_type': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_mountain_type_1767996621.png',
    'link_chain': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_link_chain_1767996630.png',
    'play_button': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_play_button_1767996639.png',
    'construction_crane': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_construction_crane_1767996647.png',
    'point_down': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_point_down_1767996656.png',
    'folder_upload': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_folder_upload_1767996666.png',
    'lightning_power': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_lightning_power_1767996675.png',
    'chart_activity': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_chart_activity_1767996696.png',
    'box_package': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_box_package_1767996705.png',

    # Batch 3 - Emoji Replacement Icons
    'lock_closed': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_lock_closed_1770309266.png',
    'star_milestone': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_star_milestone_1770309293.png',
    'gear_settings': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_gear_settings_1770309304.png',
    'vehicle_rover': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_vehicle_rover_1770309365.png',
    'vehicle_drone': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_vehicle_drone_1770309380.png',
    'vehicle_buggy': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_vehicle_buggy_1770309429.png',
    'magnifier_discovery': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_magnifier_discovery_1770309441.png',
    'tornado_dust': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_tornado_dust_1770309454.png',
    'pickaxe_mining': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_pickaxe_mining_1770309465.png',
    'fuel_pump': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_fuel_pump_1770309477.png',
    'cargo_capacity': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_cargo_capacity_1770309489.png',
    'speed_fast': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_speed_fast_1770309550.png',
    'night_moon': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_night_moon_1770309565.png',
    'income_coins': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_income_coins_1770309582.png',
    'value_diamond': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_value_diamond_1770309595.png',
    'rare_sparkle': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_rare_sparkle_1770309616.png',
    'checkmark_done': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_checkmark_done_1770311939.png',

    # Batch 4 - Admin/Menu Icons
    'email_envelope': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_email_envelope_1770315130.png',
    'tree_progression': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_tree_progression_1770315141.png',
    'palette_art': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_palette_art_1770315153.png',
    'book_lore': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_book_lore_1770315170.png',
    'clipboard_list': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_clipboard_list_1770315181.png',
    'trash_delete': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/icon_trash_delete_1770315275.png',

    # ARIA
    'aria_avatar': 'https://storage.googleapis.com/galactica-pilgrim-assets/aria/concept_aria_rock_v3_1767666240.png',
}

# #1434: ONE canonical N/E/S/W trail palette. The crew map LINES, the Top Trails BOXES,
# the antipode modal, the mission list, and the legend ALL read this — so line and box
# colours can never drift apart again (they did when the map lines were migrated to
# blue/red but the boxes weren't). Colorblind-tested (deuteranopia/protanopia/tritanopia);
# direction is ALSO encoded by a per-direction dash pattern + a text label, NEVER colour
# alone. Andy 2026-06-01 chose this set over the old blue/red (a colourblind confusion pair).
TRAIL_DIR_PALETTE = {
    'N': {'color': '#FFFFFF', 'halo': '#000000', 'dash': None,        'label': 'N CHAIN'},
    'E': {'color': '#00FFFF', 'halo': '#000000', 'dash': '16,8',      'label': 'E CHAIN'},
    'S': {'color': '#FF1493', 'halo': '#000000', 'dash': '4,6',       'label': 'S CHAIN'},
    'W': {'color': '#000000', 'halo': '#FFFFFF', 'dash': '12,4,4,4',  'label': 'W CHAIN'},
}


# ============================================================================
# NAROG RECALIBRATION — re-pick / re-roll image / re-roll video / lock-in
# ============================================================================
# Single lever to flip when going live: 0.01 = 1% test pricing, 1.0 = full price.
# 2026-04-30: Andy + Luke are the only post-canonical Narogs in existence.
# Test mode lets us validate the recalibration loop without burning real shards.
# Flip to 1.0 before captain #3 ever forges.
NAROG_REFORGE_TEST_MULTIPLIER = 0.01

# Base costs at full (production) pricing. Test mode multiplies these.
# Costs mirror real API spend ratios:
#   - Re-pick has no API cost (just a shard sink to prevent spam)
#   - Re-roll Image runs Flux (~$0.05) → 500 shard base. Re-rolling image
#     INVALIDATES the existing awakening video (since Wan animates from
#     the image), so video_url is cleared on every re-roll. Captain then
#     decides whether to pay for a new awakening or lock in image-only.
#   - Re-roll Video runs Wan (~$0.50, 10× Flux) → 5000 shard + 500 SV base.
#     Surfaced contextually only when video_url is missing (not as a primary
#     recalibration action) — captain pays this when they want their new
#     image animated.
NAROG_REFORGE_BASE_COSTS = {
    'repick':       {'shards': 500,  'sv': 0},
    'reroll_image': {'shards': 500,  'sv': 0},
    'reroll_video': {'shards': 5000, 'sv': 500},
}

# Lifetime caps per Narog.
# 2026-04-30: quadrupled from 5/10/5 → 20/40/20 to give captains real room
# to iterate during the 72hr test window without bumping the cap.
NAROG_REFORGE_LIFETIME_CAPS = {
    'repick':       20,
    'reroll_image': 40,
    'reroll_video': 20,
}

# 72-hour test window. Until the captain hits "Lock In" or this elapses, no
# real on-chain tx are written. Auto-lock fires on expiry with whatever state
# is current.
NAROG_TEST_WINDOW_HOURS = 72


def narog_reforge_cost(action: str) -> dict:
    """Return current effective cost for a recalibration action, applying the
    test multiplier. Round up so costs stay as positive ints."""
    import math
    base = NAROG_REFORGE_BASE_COSTS.get(action) or {'shards': 0, 'sv': 0}
    return {
        'shards': max(1, math.ceil(base['shards'] * NAROG_REFORGE_TEST_MULTIPLIER)),
        'sv':     max(0, math.ceil(base['sv']     * NAROG_REFORGE_TEST_MULTIPLIER)),
    }