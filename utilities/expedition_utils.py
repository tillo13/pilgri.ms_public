"""
Expedition System — thin re-export shim.

The real code lives in utilities/expeditions/ (config, terrain, travel, cost,
preview, lifecycle, page_data, trails) and utilities/discovery_utils.py.
This module stays only so existing `from utilities.expedition_utils import X`
callers keep working.

Do not add new logic here — put it in the appropriate utilities/expeditions/
sibling, then (if needed) add the symbol to the re-exports below.
"""

# noqa: F401 throughout — re-exports intentionally shadow direct imports.

from utilities.expeditions.config import (  # noqa: F401
    BASE_FUEL_PER_KM,
    LIFE_SUPPORT_PER_DAY,
    BASE_SPEED_KM_PER_HOUR,
    EVA_HOURS_PER_DAY,
    BASE_COST_PER_KM,
    TERRAIN_MODIFIERS,
    MISSION_ARTIFACT_MAX_DISTANCE_KM,
    GENERIC_SAMPLE_MAX_DISTANCE_KM,
)

# Backwards compat alias (old callers expect WALKING_SPEED_KM_PER_HOUR)
WALKING_SPEED_KM_PER_HOUR = BASE_SPEED_KM_PER_HOUR

from utilities.mars_math import haversine_distance, MARS_RADIUS_KM  # noqa: F401

from utilities.db_trails import (  # noqa: F401
    TRAIL_LEVEL_THRESHOLDS,
    TRAIL_SPEED_MULTIPLIERS,
    get_trail_level_from_count,
    calculate_trail_speed_mult_km,
    get_trail_speed_mult_for_destination,
)

from utilities.expeditions.terrain import (  # noqa: F401
    calculate_speed_multiplier,
    calculate_travel_time,
    estimate_travel_days,
    get_terrain_info,
    is_item_geographically_valid,
)

from utilities.expeditions.travel import calculate_segmented_travel_time  # noqa: F401

from utilities.expeditions.cost import (  # noqa: F401
    calculate_expedition_cost,
    generate_expedition_narrative,
    sort_landmarks_by_cost,
)

from utilities.expeditions.preview import (  # noqa: F401
    get_expedition_cost_preview,
    get_expedition_preview,
    estimate_expedition_return,
    get_expedition_cost_preview_formatted,
)

from utilities.expeditions.lifecycle import (  # noqa: F401
    launch_expedition,
    recall_expedition,
    complete_expedition_if_ready,
    get_expedition_discovery_progress,
    claim_all_discoveries,
    get_discovery_progress_formatted,
    start_expedition_from_request,
    check_signal_events,
)

from utilities.expeditions.page_data import get_expeditions_page_data  # noqa: F401

from utilities.expeditions.trails import (  # noqa: F401
    handle_trail_build_request,
    get_trail_consumables_data,
)

from utilities.discovery_utils import (  # noqa: F401
    get_progressive_weights,
    calculate_discovery_checkpoints,
    interpolate_route_coordinates,
    matches_terrain_feature,
    roll_for_item_spawn,
    get_distance_value_multiplier,
    calculate_enhanced_item_value,
    generate_expedition_discoveries,
    analyze_discovery,
    shard_all_discoveries,
    calculate_expedition_discovery,
)
