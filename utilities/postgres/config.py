"""
utilities.postgres.config — data-only tuning constants for the DB domain.

All module-level constants from former db_*.py files live here. Sibling modules
(users, assets, shop, robot, etc.) import what they need. Never put logic here.

Trail-specific constants live in utilities/postgres/trails/config.py — too
tightly coupled to trail_segments / crew_missions / aria_skills to be general.
"""

# ============================================================================
# ROBOT (5-stage build pipeline + dial)
# ============================================================================

# Five canonical build stages. Order matters: visual_stage 1..5.
ROBOT_STAGES = [
    {'idx': 1, 'key': 'frame',   'label': 'Skeletal Frame',     'part': 'load-bearing chassis'},
    {'idx': 2, 'key': 'plating', 'label': 'Hull Plating',       'part': 'pressure-rated panels'},
    {'idx': 3, 'key': 'core',    'label': 'Power Core',         'part': 'crystalline reactor'},
    {'idx': 4, 'key': 'optics',  'label': 'Optical Array',      'part': 'lens cluster'},
    {'idx': 5, 'key': 'finish',  'label': 'Finishing Touches',  'part': 'paint, glyphs, signal antenna'},
]

# Image-gen backend for Narog stages.
#   'kontext' = Flux Kontext Pro (single-seed edit, current default)
#   'flux2'   = Flux 2 Pro (up to 8 reference images, multi-ref editing)
# Flip this to 'flux2' to test the multi-ref chain (cairn + silhouette +
# captain's item) without touching any other code.
NAROG_IMAGE_MODEL = 'flux2'

# STUB timing — 60s/stage so QA can see the full build cycle in 5 minutes.
# Will be replaced with real-clock days scaled by robotics_lab.robot_build_speed_mult.
STAGE_DURATION_SECONDS = 60

# Placeholder image used until robot_visuals.py generates real Kontext-chained art.
PLACEHOLDER_STAGE_IMAGE = (
    "https://storage.googleapis.com/galactica-pilgrim-assets/"
    "ui/robot_placeholder_stage.png"
)

# Per-stage placeholder images (Mars-rock style, generated via Flux)
STAGE_PLACEHOLDER_IMAGES = {
    'frame':   'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/robot_stage_frame.png',
    'plating': 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/robot_stage_plating.png',
    'core':    'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/robot_stage_core.png',
    'optics':  'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/robot_stage_optics.png',
    'finish':  'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/robot_stage_finish.png',
}

# Default dial split (must sum to 100). Captains can rebalance in 5% increments.
DEFAULT_DIAL = {
    'mining': 25,
    'exploration': 25,
    'science': 25,
    'combat': 25,
}
DIAL_KEYS = ['mining', 'exploration', 'science', 'combat']
