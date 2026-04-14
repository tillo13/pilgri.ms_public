"""utilities.db_wallets — thin re-export shim.

Code moved to utilities/postgres/wallets.py. This shim keeps existing
`from utilities.db_wallets import Y` callers working. Do not add new logic.
"""
# noqa: F401 throughout — re-exports intentionally shadow direct imports.
from utilities.postgres.wallets import (  # noqa: F401
    create_sepolia_wallet_for_user,
    get_user_sepolia_wallets,
    get_user_primary_sepolia_wallet,
    update_sepolia_wallet_balance,
    sync_all_wallet_balances,
    claim_anonymous_wallet,
    get_wallet_by_address,
    get_random_unclaimed_cache,
)
