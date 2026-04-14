"""utilities.db_bugs — thin re-export shim.

Code moved to utilities/postgres/bugs.py. This shim keeps existing
`from utilities.db_bugs import Y` callers working. Do not add new logic.
"""
# noqa: F401 throughout — re-exports intentionally shadow direct imports.
from utilities.postgres.bugs import (  # noqa: F401
    _serialize_row,
    _serialize_rows,
    ensure_bug_tables,
    create_bug,
    get_bug_by_id,
    get_bug_by_name,
    get_active_bugs,
    get_completed_bugs,
    update_bug,
    complete_bug,
    reopen_bug,
    search_bugs,
    get_bug_history,
    get_bug_stats,
    upload_bug_screenshot,
    get_ideas,
    create_idea,
    add_idea_note,
    promote_idea,
    get_bug_comments,
    add_bug_comment,
    _notify_mentions,
)
