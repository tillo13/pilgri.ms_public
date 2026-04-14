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
    # db_users - User CRUD, auth, session, research, escalation
    'ensure_scientist_column': 'db_users', 'ensure_passive_sv_column': 'db_users',
    'add_passive_sv': 'db_users', 'get_passive_sv': 'db_users',
    'assign_scientist_to_user': 'db_users', 'get_user_scientist': 'db_users',
    'upsert_user': 'db_users', 'get_user_by_id': 'db_users', 'get_user_by_google_id': 'db_users',
    'update_user_activity': 'db_users', 'get_user_email_info': 'db_users',
    'hydrate_user_session': 'db_users',
    'ensure_research_columns': 'db_users', 'get_user_research_data': 'db_users',
    'add_research_points': 'db_users', 'spend_research_points': 'db_users',
    'spend_research_points_for_tech': 'db_users',
    'ensure_escalation_columns': 'db_users', 'get_user_escalation_counts': 'db_users',
    'increment_reroll_count': 'db_users', 'increment_transmutation_count': 'db_users',
    'calculate_reroll_cost': 'db_users', 'calculate_transmutation_cost': 'db_users',

    # db_wallets - Sepolia asset operations
    'create_sepolia_wallet_for_user': 'db_wallets', 'get_user_sepolia_wallets': 'db_wallets',
    'get_user_primary_sepolia_wallet': 'db_wallets', 'update_sepolia_wallet_balance': 'db_wallets',
    'sync_all_wallet_balances': 'db_wallets', 'claim_anonymous_wallet': 'db_wallets',
    'get_wallet_by_address': 'db_wallets', 'get_random_unclaimed_cache': 'db_wallets',

    # db_assets - Replicate assets, captain management
    'create_replicate_asset': 'db_assets', 'get_user_replicate_assets': 'db_assets',
    'get_user_commander_images': 'db_assets', 'get_asset_edit_chain': 'db_assets',
    'claim_anonymous_assets': 'db_assets', 'update_asset_stats': 'db_assets',
    'delete_asset': 'db_assets', 'get_primary_commander': 'db_assets',
    'get_user_commander': 'db_assets', 'set_primary_commander': 'db_assets',
    'update_commander_name': 'db_assets', 'get_commander_stats': 'db_assets',

    # db_shop - Transactions, infrastructure, upgrades, action tokens, mars messages
    'ensure_dust_covered_column': 'db_shop', 'set_infrastructure_dust_covered': 'db_shop',
    'create_depot_transaction': 'db_shop', 'get_user_depot_transactions': 'db_shop',
    '_format_depot_activity': 'db_shop', 'get_unified_activity': 'db_shop',
    'create_infrastructure': 'db_shop', 'get_user_infrastructure': 'db_shop',
    'get_infrastructure_by_id': 'db_shop', 'update_infrastructure_status': 'db_shop',
    'get_user_upgrades': 'db_shop', 'get_user_upgrade': 'db_shop',
    'add_user_upgrade': 'db_shop', 'get_user_upgrade_count': 'db_shop',
    'complete_ready_builds': 'db_shop', 'get_building_upgrades': 'db_shop',
    'ensure_action_tokens_table': 'db_shop', 'is_action_token_used': 'db_shop',
    'mark_action_token_used': 'db_shop', 'get_next_mars_message': 'db_shop',

    # db_expeditions - Expedition CRUD, discoveries
    'create_expedition': 'db_expeditions', 'get_user_active_expeditions': 'db_expeditions',
    'get_expedition_by_id': 'db_expeditions', 'update_expedition_complete': 'db_expeditions',
    'get_user_completed_expeditions_count': 'db_expeditions',
    'get_user_visited_locations_count': 'db_expeditions',
    'get_user_expedition_history': 'db_expeditions',
    'get_expedition_discovery_items': 'db_expeditions',
    'record_landmark_discovery': 'db_expeditions', 'get_user_discovered_landmarks': 'db_expeditions',
    'get_discovery_items_catalog': 'db_expeditions',
    'create_expedition_discoveries': 'db_expeditions',
    'get_expedition_discoveries': 'db_expeditions',
    'unlock_discoveries_by_distance': 'db_expeditions',
    'claim_expedition_discovery': 'db_expeditions',
    'claim_all_pending_discoveries': 'db_expeditions',
    'get_recent_discoveries': 'db_expeditions',
    'get_total_unclaimed_discoveries_count': 'db_expeditions',
    'get_claimed_discoveries': 'db_expeditions',
    'get_sample_common_discovery': 'db_expeditions',
    'get_all_discovery_items': 'db_expeditions',
    'get_discovery_item_details': 'db_expeditions',

    # db_trails - Trail segments, crew missions, ARIA skills
    'ensure_trail_segments_table': 'db_trails', 'get_user_trail': 'db_trails',
    'increment_user_trail': 'db_trails', 'get_user_trails': 'db_trails',
    'add_km_to_trail': 'db_trails', 'get_trail_progress': 'db_trails',
    'get_aria_skills': 'db_trails', 'add_aria_skill_xp': 'db_trails',
    'ensure_crew_missions_schema': 'db_trails', 'get_crew_mission_status': 'db_trails',
    'start_crew_mission': 'db_trails', 'complete_crew_mission': 'db_trails',
    'get_trail_consumable_discoveries': 'db_trails',
    'consume_discovery_for_trail': 'db_trails',
    'use_aria_resonance': 'db_trails',
    'get_nearby_trails_for_missions': 'db_trails',
    'get_visited_sites_for_trails': 'db_trails',

    # db_map - Mars coordinates, landmarks, fog-of-war, frontier
    'get_random_mars_coordinates': 'db_map', 'get_nearest_mars_landmarks': 'db_map',
    'get_or_set_user_mars_home': 'db_map', 'get_mars_landmarks_within_radius': 'db_map',
    '_get_direction_from_angle': 'db_map',
    'get_user_furthest_expeditions_by_direction': 'db_map',
    'get_frontier_landmarks_beyond_point': 'db_map',
    'get_all_frontier_landmarks': 'db_map',
    'get_available_landmarks_by_discovery': 'db_map',

    # db_notifications - FOMO, email queries, captain quotes
    'get_users_with_completed_expeditions': 'db_notifications',
    'mark_expedition_notified': 'db_notifications',
    'get_inactive_users': 'db_notifications', 'mark_user_nudged': 'db_notifications',
    'get_user_fomo_data': 'db_notifications',
    'save_commander_quote': 'db_notifications', 'get_commander_quotes': 'db_notifications',
    'get_commander_quote_count': 'db_notifications',
}


def __getattr__(name):
    """Lazy re-export: load domain function on first access."""
    if name in _DOMAIN_EXPORTS:
        module = _importlib.import_module(f'utilities.{_DOMAIN_EXPORTS[name]}')
        func = getattr(module, name)
        globals()[name] = func
        return func
    raise AttributeError(f"module 'utilities.postgres_utils' has no attribute '{name}'")
