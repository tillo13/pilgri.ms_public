"""utilities.db_assets — thin re-export shim.

Code moved to utilities/postgres/assets.py. This shim keeps existing
`from utilities.db_assets import Y` callers working. Do not add new logic.
"""
# noqa: F401 throughout — re-exports intentionally shadow direct imports.
from utilities.postgres.assets import (  # noqa: F401
    create_replicate_asset,
    get_user_replicate_assets,
    get_user_commander_images,
    get_asset_edit_chain,
    claim_anonymous_assets,
    update_asset_stats,
    delete_asset,
    get_primary_commander,
    get_user_commander,
    set_primary_commander,
    update_commander_name,
    get_commander_stats,
)
