"""Shim for utilities.infrastructure_utils (R10a split).

The original 1494-LOC module was split into `utilities/infrastructure/` package
+ `utilities/xenobiology.py`. This shim preserves every public name that older
callers import from the old path. Prefer importing from the new modules directly
in new code.
"""

# --- Constants + env math ---
from utilities.infrastructure.environment import (
    MARS_SOL_HOURS,
    ACCUMULATION_CAP_HOURS,
    DUST_STORM_MESSAGE,
    calculate_daylight_fraction,
    _get_mars_environment_multiplier,
    _get_mars_environment_factors,
    calculate_generation_rate,
)

# --- Construction ---
from utilities.infrastructure.construction import (
    _check_build_requirements_fast,
    get_build_requirements,
    start_construction,
    check_construction_status,
    send_completion_reward,
)

# --- Income / science value ---
from utilities.infrastructure.income import (
    user_has_maintenance_drone,
    calculate_accumulated_income,
    claim_accumulated_income,
    record_science_value,
)

# --- Effects ---
from utilities.infrastructure.effects import get_user_infrastructure_effects

# --- Views / route glue ---
from utilities.infrastructure.views import (
    get_infrastructure_page_data,
    handle_infrastructure_build,
    handle_infrastructure_status,
    handle_accumulated_income,
)

# --- Xenobiology Lab ---
from utilities.xenobiology import (
    _get_experiment_cost,
    _get_experiment_max_roll,
    get_xenobiology_status,
    run_xenobiology_experiment,
    upgrade_xenobiology_stat,
)

# --- Pass-through re-exports (callers import these through this module) ---
from config_infrastructure import INFRASTRUCTURE_CATALOG
from utilities.postgres.shop import get_user_infrastructure
from utilities.postgres.map import get_or_set_user_mars_home

__all__ = [
    # env
    'MARS_SOL_HOURS', 'ACCUMULATION_CAP_HOURS', 'DUST_STORM_MESSAGE',
    'calculate_daylight_fraction',
    '_get_mars_environment_multiplier', '_get_mars_environment_factors',
    'calculate_generation_rate',
    # construction
    '_check_build_requirements_fast', 'get_build_requirements',
    'start_construction', 'check_construction_status', 'send_completion_reward',
    # income
    'user_has_maintenance_drone', 'calculate_accumulated_income',
    'claim_accumulated_income', 'record_science_value',
    # effects
    'get_user_infrastructure_effects',
    # views
    'get_infrastructure_page_data', 'handle_infrastructure_build',
    'handle_infrastructure_status', 'handle_accumulated_income',
    # xenobiology
    '_get_experiment_cost', '_get_experiment_max_roll',
    'get_xenobiology_status', 'run_xenobiology_experiment', 'upgrade_xenobiology_stat',
    # pass-through
    'INFRASTRUCTURE_CATALOG', 'get_user_infrastructure', 'get_or_set_user_mars_home',
]
