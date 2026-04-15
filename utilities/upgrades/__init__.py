"""utilities.upgrades — R14 split of utilities/upgrades_utils.py (2026-04-15).

Sub-modules:
    catalog    — config lookup, level stats, enriched Depot catalog
    state      — per-user DB reads (player_upgrades), schema bootstrap
    flow       — purchase / perform_upgrade write path
    effects    — cumulative bonuses from upgrades + infra + tech + captain
    vehicles   — vehicle-specific helpers for expedition slots
"""

from utilities.upgrades.catalog import (
    get_item_config,
    get_level_stats,
    get_all_infrastructure_levels,
    get_infrastructure_level,
    get_next_upgrade_cost,
    get_upgrade_catalog_for_user,
)
from utilities.upgrades.state import (
    ensure_upgrades_table,
    get_user_upgrade_level,
    _complete_pending_upgrade,
    get_all_upgrade_build_statuses,
    get_upgrade_build_status,
    count_concurrent_upgrades,
    get_user_upgrade_cap,
    get_active_builds,
    get_all_user_upgrades,
    get_upgrade_stats,
    BASE_CONCURRENT_UPGRADE_CAP,
)
from utilities.upgrades.flow import (
    handle_upgrade_request,
    perform_upgrade,
)
from utilities.upgrades.effects import get_user_upgrade_effects
from utilities.upgrades.vehicles import (
    get_vehicle_for_expedition,
    get_user_owned_vehicles,
    count_user_vehicles,
)

__all__ = [
    # catalog
    'get_item_config',
    'get_level_stats',
    'get_all_infrastructure_levels',
    'get_infrastructure_level',
    'get_next_upgrade_cost',
    'get_upgrade_catalog_for_user',
    # state
    'ensure_upgrades_table',
    'get_user_upgrade_level',
    '_complete_pending_upgrade',
    'get_all_upgrade_build_statuses',
    'get_upgrade_build_status',
    'count_concurrent_upgrades',
    'get_user_upgrade_cap',
    'get_active_builds',
    'get_all_user_upgrades',
    'get_upgrade_stats',
    'BASE_CONCURRENT_UPGRADE_CAP',
    # flow
    'handle_upgrade_request',
    'perform_upgrade',
    # effects
    'get_user_upgrade_effects',
    # vehicles
    'get_vehicle_for_expedition',
    'get_user_owned_vehicles',
    'count_user_vehicles',
]
