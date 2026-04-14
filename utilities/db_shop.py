"""utilities.db_shop — thin re-export shim.

Code moved to utilities/postgres/shop.py. This shim keeps existing
`from utilities.db_shop import Y` callers working. Do not add new logic.
"""
# noqa: F401 throughout — re-exports intentionally shadow direct imports.
from utilities.postgres.shop import (  # noqa: F401
    ensure_dust_covered_column,
    set_infrastructure_dust_covered,
    create_depot_transaction,
    get_user_depot_transactions,
    _format_depot_activity,
    get_unified_activity,
    create_infrastructure,
    get_user_infrastructure,
    get_infrastructure_by_id,
    update_infrastructure_status,
    get_user_upgrades,
    get_user_upgrade,
    add_user_upgrade,
    get_user_upgrade_count,
    complete_ready_builds,
    get_building_upgrades,
    ensure_action_tokens_table,
    is_action_token_used,
    mark_action_token_used,
    get_next_mars_message,
)
