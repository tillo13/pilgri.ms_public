"""Shim — real code in utilities/views/. Kept for caller compat."""
from utilities.views.arrival import get_command_page_data, _get_all_scientists_with_bonuses
from utilities.views.dashboard import get_dashboard_page_data, get_fleet_status
from utilities.views.while_you_were_away import get_while_you_were_away_summary
from utilities.views.colony import get_colony_page_data
from utilities.views.depot import get_depot_page_data, get_claimed_discoveries_data
from utilities.views.misc import get_profile_page_data, build_recent_activity, get_formatted_discovery_items

__all__ = [
    'get_command_page_data', '_get_all_scientists_with_bonuses',
    'get_dashboard_page_data', 'get_fleet_status',
    'get_while_you_were_away_summary',
    'get_colony_page_data',
    'get_depot_page_data', 'get_claimed_discoveries_data',
    'get_profile_page_data', 'build_recent_activity', 'get_formatted_discovery_items',
]
