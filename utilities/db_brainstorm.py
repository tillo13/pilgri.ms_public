"""utilities.db_brainstorm — thin re-export shim.

Code moved to utilities/postgres/brainstorm.py. This shim keeps existing
`from utilities.db_brainstorm import X` callers working. Do not add new logic.
"""
# noqa: F401 throughout — re-exports intentionally shadow direct imports.
from utilities.postgres.brainstorm import (  # noqa: F401
    ensure_brainstorm_comments_table,
    get_comments_for_page,
    add_comment,
)
