"""utilities.postgres.trails — trail segments, crew missions, ARIA skills.

Split from the old utilities/db_trails.py (1304 LOC) into focused sub-modules.
This package re-exports the full public API.
"""
# noqa: F401 throughout — re-exports intentionally shadow direct imports.
from utilities.postgres.trails.config import (  # noqa: F401
    TRAIL_LEVEL_THRESHOLDS,
    TRAIL_SPEED_MULTIPLIERS,
)
from utilities.postgres.trails.segments import (  # noqa: F401
    get_trail_level_from_count,
    calculate_trail_speed_mult_km,
    get_trail_speed_mult_for_destination,
    ensure_trail_segments_table,
    get_user_trail,
    increment_user_trail,
    get_user_trails,
    add_km_to_trail,
    get_trail_progress,
    find_nearest_trail_origin,
    spawn_next_trail,
    heal_orphan_trail_tips,
    cron_drone_trail_build,
)
from utilities.postgres.trails.chains import (  # noqa: F401
    ensure_user_trail_chains_table,
    compute_user_trail_chains,
    persist_user_trail_chains,
    get_active_chain_segments,
    get_user_active_direction,
    set_user_active_direction,
    add_km_to_active_chain,
    get_chain_speed_mult_for_destination,
    get_all_user_chains,
)
from utilities.postgres.trails.aria_skills import (  # noqa: F401
    get_aria_skills,
    add_aria_skill_xp,
    use_aria_resonance,
)
from utilities.postgres.trails.crew import (  # noqa: F401
    ensure_crew_missions_schema,
    get_crew_mission_status,
    get_crew_mission_status_with_stats,
    get_crew_nearby_payload,
    start_crew_mission,
    complete_crew_mission,
    get_trail_consumable_discoveries,
    consume_discovery_for_trail,
    get_nearby_trails_for_missions,
    get_visited_sites_for_trails,
    _format_trail_sites,
)
