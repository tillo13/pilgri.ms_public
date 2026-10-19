"""Trail system constants — level thresholds + speed multipliers."""

TRAIL_LEVEL_THRESHOLDS = [
    (1, 'marked'),       # 1 completed trip
    (3, 'cached'),       # 3 completed trips
    (7, 'established'),  # 7 completed trips
    (15, 'highway'),     # 15 completed trips
]

TRAIL_SPEED_MULTIPLIERS = {
    'none': 1.0,
    'marked': 1.25,
    'cached': 1.5,
    'established': 2.0,
    'highway': 3.0,
}
