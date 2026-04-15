"""Back-compat shim — real code lives in utilities/upgrades/. R14 split (2026-04-15).

The original 1116-LOC module was split into the `utilities/upgrades/` package
(catalog + state + flow + effects + vehicles). This shim preserves every public
name that older callers import from `utilities.upgrades_utils`. Prefer importing
from the new modules directly in new code.
"""

# --- Catalog / cost lookups ---
from utilities.upgrades.catalog import (
    get_item_config,
    get_level_stats,
    get_all_infrastructure_levels,
    get_infrastructure_level,
    get_next_upgrade_cost,
    get_upgrade_catalog_for_user,
)

# --- Per-user state (DB reads) ---
from utilities.upgrades.state import (
    ensure_upgrades_table,
    _upgrades_table_ensured,
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

# --- Purchase / upgrade write path ---
from utilities.upgrades.flow import (
    handle_upgrade_request,
    perform_upgrade,
)

# --- Aggregate effects ---
from utilities.upgrades.effects import get_user_upgrade_effects

# --- Vehicle helpers ---
from utilities.upgrades.vehicles import (
    get_vehicle_for_expedition,
    get_user_owned_vehicles,
    count_user_vehicles,
)

__all__ = [
    # catalog
    'get_item_config', 'get_level_stats',
    'get_all_infrastructure_levels', 'get_infrastructure_level',
    'get_next_upgrade_cost', 'get_upgrade_catalog_for_user',
    # state
    'ensure_upgrades_table', 'get_user_upgrade_level',
    '_complete_pending_upgrade', 'get_all_upgrade_build_statuses',
    'get_upgrade_build_status', 'count_concurrent_upgrades',
    'get_user_upgrade_cap', 'get_active_builds',
    'get_all_user_upgrades', 'get_upgrade_stats',
    'BASE_CONCURRENT_UPGRADE_CAP',
    # flow
    'handle_upgrade_request', 'perform_upgrade',
    # effects
    'get_user_upgrade_effects',
    # vehicles
    'get_vehicle_for_expedition', 'get_user_owned_vehicles', 'count_user_vehicles',
]
