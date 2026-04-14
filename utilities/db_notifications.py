"""utilities.db_notifications — thin re-export shim.

Code moved to utilities/postgres/notifications.py. This shim keeps existing
`from utilities.db_notifications import Y` callers working. Do not add new logic.
"""
# noqa: F401 throughout — re-exports intentionally shadow direct imports.
from utilities.postgres.notifications import (  # noqa: F401
    get_users_with_completed_expeditions,
    mark_expedition_notified,
    get_inactive_users,
    mark_user_nudged,
    get_user_fomo_data,
    save_commander_quote,
    get_commander_quotes,
    get_commander_quote_count,
)
