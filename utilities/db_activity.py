"""utilities.db_activity — thin re-export shim.

Code moved to utilities/postgres/activity.py. This shim keeps existing
`from utilities.db_activity import Y` callers working. Do not add new logic.
"""
# noqa: F401 throughout — re-exports intentionally shadow direct imports.
from utilities.postgres.activity import (  # noqa: F401
    ensure_activity_table,
    log_activity,
    get_activity,
)
