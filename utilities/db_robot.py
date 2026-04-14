"""utilities.db_robot — thin re-export shim.

Code moved to utilities/postgres/robot.py. This shim keeps existing
`from utilities.db_robot import Y` callers working. Do not add new logic.
"""
# noqa: F401 throughout — re-exports intentionally shadow direct imports.
from utilities.postgres.robot import (  # noqa: F401
    ROBOT_STAGES,
    STAGE_DURATION_SECONDS,
    PLACEHOLDER_STAGE_IMAGE,
    STAGE_PLACEHOLDER_IMAGES,
    DEFAULT_DIAL,
    DIAL_KEYS,
    ensure_robot_tables,
    get_robot,
    get_stage_log,
    pick_stage_sources,
    start_robot_build,
    log_stage,
    set_robot_name,
    set_robot_dial,
    mark_cinematic_played,
    save_name_suggestions,
    _stub_advance_one_stage,
    tick_robot_build,
    get_robot_page_data,
)
