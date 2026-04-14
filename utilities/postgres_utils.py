"""
utilities.postgres_utils — thin re-export shim.

Core infrastructure now lives in utilities/postgres/core.py. Domain-specific
constants live in utilities/postgres/config.py. Domain functions still live in
utilities/db_*.py (being migrated incrementally into utilities/postgres/).

This module stays only so existing `from utilities.postgres_utils import X`
callers keep working. Do not add new logic here.
"""

# noqa: F401 throughout — re-exports intentionally shadow direct imports.

from utilities.postgres.core import (  # noqa: F401
    get_secret,
    get_db_connection,
    get_pool_health,
    get_db_connection_stats,
    db_cursor,
    _fetchone,
    _fetchall,
    _get_one,
    _get_many,
    _count,
    _update,
    json_serial,
    test_connection,
)

# ============================================================================
# RE-EXPORTS: Domain functions from db_*.py files
# All existing `from utilities.postgres_utils import X` statements keep working.
# Uses lazy __getattr__ to avoid circular imports when db_*.py files are
# imported directly (they import core functions from here).
# ============================================================================

import importlib as _importlib

_DOMAIN_EXPORTS = {
    # postgres.users - User CRUD, auth, session, research, escalation
    'ensure_scientist_column': 'postgres.users', 'ensure_passive_sv_column': 'postgres.users',
    'add_passive_sv': 'postgres.users', 'get_passive_sv': 'postgres.users',
    'assign_scientist_to_user': 'postgres.users', 'get_user_scientist': 'postgres.users',
    'upsert_user': 'postgres.users', 'get_user_by_id': 'postgres.users', 'get_user_by_google_id': 'postgres.users',
    'update_user_activity': 'postgres.users', 'get_user_email_info': 'postgres.users',
    'hydrate_user_session': 'postgres.users',
    'ensure_research_columns': 'postgres.users', 'get_user_research_data': 'postgres.users',
    'add_research_points': 'postgres.users', 'spend_research_points': 'postgres.users',
    'spend_research_points_for_tech': 'postgres.users',
    'ensure_escalation_columns': 'postgres.users', 'get_user_escalation_counts': 'postgres.users',
    'increment_reroll_count': 'postgres.users', 'increment_transmutation_count': 'postgres.users',
    'calculate_reroll_cost': 'postgres.users', 'calculate_transmutation_cost': 'postgres.users',

    # postgres.wallets - Sepolia asset operations
    'create_sepolia_wallet_for_user': 'postgres.wallets', 'get_user_sepolia_wallets': 'postgres.wallets',
    'get_user_primary_sepolia_wallet': 'postgres.wallets', 'update_sepolia_wallet_balance': 'postgres.wallets',
    'sync_all_wallet_balances': 'postgres.wallets', 'claim_anonymous_wallet': 'postgres.wallets',
    'get_wallet_by_address': 'postgres.wallets', 'get_random_unclaimed_cache': 'postgres.wallets',

    # postgres.assets - Replicate assets, captain management
    'create_replicate_asset': 'postgres.assets', 'get_user_replicate_assets': 'postgres.assets',
    'get_user_commander_images': 'postgres.assets', 'get_asset_edit_chain': 'postgres.assets',
    'claim_anonymous_assets': 'postgres.assets', 'update_asset_stats': 'postgres.assets',
    'delete_asset': 'postgres.assets', 'get_primary_commander': 'postgres.assets',
    'get_user_commander': 'postgres.assets', 'set_primary_commander': 'postgres.assets',
    'update_commander_name': 'postgres.assets', 'get_commander_stats': 'postgres.assets',

    # postgres.shop - Transactions, infrastructure, upgrades, action tokens, mars messages
    'ensure_dust_covered_column': 'postgres.shop', 'set_infrastructure_dust_covered': 'postgres.shop',
    'create_depot_transaction': 'postgres.shop', 'get_user_depot_transactions': 'postgres.shop',
    '_format_depot_activity': 'postgres.shop', 'get_unified_activity': 'postgres.shop',
    'create_infrastructure': 'postgres.shop', 'get_user_infrastructure': 'postgres.shop',
    'get_infrastructure_by_id': 'postgres.shop', 'update_infrastructure_status': 'postgres.shop',
    'get_user_upgrades': 'postgres.shop', 'get_user_upgrade': 'postgres.shop',
    'add_user_upgrade': 'postgres.shop', 'get_user_upgrade_count': 'postgres.shop',
    'complete_ready_builds': 'postgres.shop', 'get_building_upgrades': 'postgres.shop',
    'ensure_action_tokens_table': 'postgres.shop', 'is_action_token_used': 'postgres.shop',
    'mark_action_token_used': 'postgres.shop', 'get_next_mars_message': 'postgres.shop',

    # postgres.expeditions - Expedition CRUD, discoveries
    'create_expedition': 'postgres.expeditions', 'get_user_active_expeditions': 'postgres.expeditions',
    'get_expedition_by_id': 'postgres.expeditions', 'update_expedition_complete': 'postgres.expeditions',
    'get_user_completed_expeditions_count': 'postgres.expeditions',
    'get_user_visited_locations_count': 'postgres.expeditions',
    'get_user_expedition_history': 'postgres.expeditions',
    'get_expedition_discovery_items': 'postgres.expeditions',
    'record_landmark_discovery': 'postgres.expeditions', 'get_user_discovered_landmarks': 'postgres.expeditions',
    'get_discovery_items_catalog': 'postgres.expeditions',
    'create_expedition_discoveries': 'postgres.expeditions',
    'get_expedition_discoveries': 'postgres.expeditions',
    'unlock_discoveries_by_distance': 'postgres.expeditions',
    'claim_expedition_discovery': 'postgres.expeditions',
    'claim_all_pending_discoveries': 'postgres.expeditions',
    'get_recent_discoveries': 'postgres.expeditions',
    'get_total_unclaimed_discoveries_count': 'postgres.expeditions',
    'get_claimed_discoveries': 'postgres.expeditions',
    'get_sample_common_discovery': 'postgres.expeditions',
    'get_all_discovery_items': 'postgres.expeditions',
    'get_discovery_item_details': 'postgres.expeditions',

    # postgres.trails - Trail segments, crew missions, ARIA skills
    'ensure_trail_segments_table': 'postgres.trails', 'get_user_trail': 'postgres.trails',
    'increment_user_trail': 'postgres.trails', 'get_user_trails': 'postgres.trails',
    'add_km_to_trail': 'postgres.trails', 'get_trail_progress': 'postgres.trails',
    'get_aria_skills': 'postgres.trails', 'add_aria_skill_xp': 'postgres.trails',
    'ensure_crew_missions_schema': 'postgres.trails', 'get_crew_mission_status': 'postgres.trails',
    'start_crew_mission': 'postgres.trails', 'complete_crew_mission': 'postgres.trails',
    'get_trail_consumable_discoveries': 'postgres.trails',
    'consume_discovery_for_trail': 'postgres.trails',
    'use_aria_resonance': 'postgres.trails',
    'get_nearby_trails_for_missions': 'postgres.trails',
    'get_visited_sites_for_trails': 'postgres.trails',

    # postgres.map - Mars coordinates, landmarks, fog-of-war, frontier
    'get_random_mars_coordinates': 'postgres.map', 'get_nearest_mars_landmarks': 'postgres.map',
    'get_or_set_user_mars_home': 'postgres.map', 'get_mars_landmarks_within_radius': 'postgres.map',
    '_get_direction_from_angle': 'postgres.map',
    'get_user_furthest_expeditions_by_direction': 'postgres.map',
    'get_frontier_landmarks_beyond_point': 'postgres.map',
    'get_all_frontier_landmarks': 'postgres.map',
    'get_available_landmarks_by_discovery': 'postgres.map',

    # postgres.notifications - FOMO, email queries, captain quotes
    'get_users_with_completed_expeditions': 'postgres.notifications',
    'mark_expedition_notified': 'postgres.notifications',
    'get_inactive_users': 'postgres.notifications', 'mark_user_nudged': 'postgres.notifications',
    'get_user_fomo_data': 'postgres.notifications',
    'save_commander_quote': 'postgres.notifications', 'get_commander_quotes': 'postgres.notifications',
    'get_commander_quote_count': 'postgres.notifications',
}


def __getattr__(name):
    """Lazy re-export: load domain function on first access."""
    if name in _DOMAIN_EXPORTS:
        module = _importlib.import_module(f'utilities.{_DOMAIN_EXPORTS[name]}')
        func = getattr(module, name)
        globals()[name] = func
        return func
    raise AttributeError(f"module 'utilities.postgres_utils' has no attribute '{name}'")
