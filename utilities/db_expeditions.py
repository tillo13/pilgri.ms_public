"""utilities.db_expeditions — thin re-export shim.

Code moved to utilities/postgres/expeditions.py. This shim keeps existing
`from utilities.db_expeditions import Y` callers working. Do not add new logic.
"""
# noqa: F401 throughout — re-exports intentionally shadow direct imports.
from utilities.postgres.expeditions import (  # noqa: F401
    create_expedition,
    get_user_active_expeditions,
    get_expedition_by_id,
    update_expedition_complete,
    get_user_completed_expeditions_count,
    get_user_visited_locations_count,
    calculate_expedition_sv,
    get_last_completed_buggy_expedition,
    get_user_expedition_history,
    get_expedition_discovery_items,
    record_landmark_discovery,
    get_user_discovered_landmarks,
    get_discovery_items_catalog,
    create_expedition_discoveries,
    get_expedition_discoveries,
    unlock_discoveries_by_distance,
    claim_expedition_discovery,
    claim_all_pending_discoveries,
    get_recent_discoveries,
    get_total_unclaimed_discoveries_count,
    get_total_discovery_count,
    get_claimed_discoveries,
    get_sample_common_discovery,
    get_all_discovery_items,
    get_discovery_item_details,
)
