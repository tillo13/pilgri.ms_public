"""utilities.db_users — thin re-export shim.

Code moved to utilities/postgres/users.py. This shim keeps existing
`from utilities.db_users import Y` callers working. Do not add new logic.
"""
# noqa: F401 throughout — re-exports intentionally shadow direct imports.
from utilities.postgres.users import (  # noqa: F401
    ensure_scientist_column,
    ensure_passive_sv_column,
    add_passive_sv,
    get_passive_sv,
    assign_scientist_to_user,
    reassign_scientist,
    get_user_scientist,
    upsert_user,
    get_user_by_id,
    get_user_by_google_id,
    update_user_activity,
    get_user_email_info,
    hydrate_user_session,
    ensure_research_columns,
    get_user_research_data,
    add_research_points,
    spend_research_points,
    spend_research_points_for_tech,
    ensure_escalation_columns,
    get_user_escalation_counts,
    increment_reroll_count,
    increment_transmutation_count,
    calculate_reroll_cost,
    calculate_transmutation_cost,
)
