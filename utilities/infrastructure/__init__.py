"""Infrastructure package - split from utilities/infrastructure_utils.py (R10a)."""
from utilities.infrastructure.environment import (
    MARS_SOL_HOURS,
    ACCUMULATION_CAP_HOURS,
    DUST_STORM_MESSAGE,
    calculate_daylight_fraction,
    _get_mars_environment_multiplier,
    _get_mars_environment_factors,
    calculate_generation_rate,
)
from utilities.infrastructure.construction import (
    _check_build_requirements_fast,
    get_build_requirements,
    start_construction,
    check_construction_status,
    send_completion_reward,
)
from utilities.infrastructure.income import (
    user_has_maintenance_drone,
    calculate_accumulated_income,
    claim_accumulated_income,
    record_science_value,
)
from utilities.infrastructure.effects import get_user_infrastructure_effects
from utilities.infrastructure.views import (
    get_infrastructure_page_data,
    handle_infrastructure_build,
    handle_infrastructure_status,
    handle_accumulated_income,
)

__all__ = [
    'MARS_SOL_HOURS', 'ACCUMULATION_CAP_HOURS', 'DUST_STORM_MESSAGE',
    'calculate_daylight_fraction',
    '_get_mars_environment_multiplier', '_get_mars_environment_factors',
    'calculate_generation_rate',
    '_check_build_requirements_fast', 'get_build_requirements',
    'start_construction', 'check_construction_status', 'send_completion_reward',
    'user_has_maintenance_drone', 'calculate_accumulated_income',
    'claim_accumulated_income', 'record_science_value',
    'get_user_infrastructure_effects',
    'get_infrastructure_page_data', 'handle_infrastructure_build',
    'handle_infrastructure_status', 'handle_accumulated_income',
]
