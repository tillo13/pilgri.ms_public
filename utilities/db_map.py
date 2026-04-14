"""utilities.db_map — thin re-export shim.

Code moved to utilities/postgres/map.py. This shim keeps existing
`from utilities.db_map import Y` callers working. Do not add new logic.
"""
# noqa: F401 throughout — re-exports intentionally shadow direct imports.
from utilities.postgres.map import (  # noqa: F401
    get_random_mars_coordinates,
    get_nearest_mars_landmarks,
    get_or_set_user_mars_home,
    get_mars_landmarks_within_radius,
    _get_direction_from_angle,
    get_user_furthest_expeditions_by_direction,
    get_frontier_landmarks_beyond_point,
    get_all_frontier_landmarks,
    get_available_landmarks_by_discovery,
)
