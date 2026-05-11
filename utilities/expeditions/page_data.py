"""
Expedition page data aggregator for the colony/expeditions page.

Consolidates all template variables needed by expeditions.html in one call:
landmarks (sorted by cost), active expeditions (with auto-complete), trails,
vehicles, storage, ARIA bonds, infrastructure bonuses.
"""

import json
import logging
from datetime import datetime

from utilities.expeditions.cost import sort_landmarks_by_cost
from utilities.expeditions.lifecycle import complete_expedition_if_ready

logger = logging.getLogger(__name__)


def get_expeditions_page_data(user_id: int) -> dict:
    """
    Get all data needed for the colony/expeditions page.
    Consolidates ~55 lines of logic from app.py.

    Returns:
        dict with all template variables for expeditions.html
    """
    from utilities.postgres.map import get_or_set_user_mars_home, get_available_landmarks_by_discovery
    from utilities.postgres.expeditions import get_user_active_expeditions, get_user_discovered_landmarks, get_user_completed_expeditions_count
    from utilities.depot_utils import get_fast_balance_and_wallet_info, get_commander_and_stats, generate_commander_stats

    total_balance, _, _ = get_fast_balance_and_wallet_info(user_id)  # FAST: no blockchain
    _, commander_stats = get_commander_and_stats(user_id)
    if not commander_stats:
        commander_stats = generate_commander_stats()

    home_coords = get_or_set_user_mars_home(user_id)
    landmarks = get_available_landmarks_by_discovery(user_id, home_coords, limit=30)
    active_expeditions = get_user_active_expeditions(user_id)
    discovered_landmarks = get_user_discovered_landmarks(user_id)

    # Auto-complete any arrived expeditions on page load
    # This ensures users see the correct state immediately
    # IMPORTANT: Only process expeditions that are still 'traveling', not already 'complete'
    just_completed_expedition = None
    now = datetime.now()  # Use local time to match stored timestamps
    for expedition in active_expeditions[:]:  # Copy list to allow modification
        # Auto-complete traveling/recalled expeditions that have returned
        # Already-complete expeditions with unclaimed items should stay visible
        if expedition['status'] in ('traveling', 'recalled') and expedition.get('return_arrives_at') and now >= expedition['return_arrives_at']:
            # Expedition has arrived - auto-complete it
            result = complete_expedition_if_ready(expedition['id'], user_id)
            if result.get('complete'):
                just_completed_expedition = {
                    'destination': expedition['destination_name'],
                    'discovery_message': result.get('discovery_message', ''),
                    'sepolia_earned': result.get('sepolia_earned', 0)
                }
                # Update expedition status in our local list (don't remove - it still has unclaimed items)
                expedition['status'] = 'complete'
                # Refresh balance after completion (fast - from session/DB cache)
                total_balance, _, _ = get_fast_balance_and_wallet_info(user_id)
    expeditions_completed = get_user_completed_expeditions_count(user_id)

    # Fetch upgrade effects ONCE — reused by sort_landmarks_by_cost, scanner range, and vehicle enrichment
    try:
        from utilities.upgrades_utils import get_user_upgrade_effects
        upgrade_effects = get_user_upgrade_effects(user_id)
    except Exception:
        upgrade_effects = {}

    landmarks = sort_landmarks_by_cost(landmarks, commander_stats, expeditions_completed, home_coords, user_id=user_id, upgrade_effects=upgrade_effects)

    # Fetch all user trails for map visualization
    from utilities.postgres.trails import get_user_trails
    all_trails = get_user_trails(user_id)
    trails_by_name = {t['destination_name']: t for t in all_trails}

    js_landmarks = []
    for i, landmark in enumerate(landmarks):
        trail = trails_by_name.get(landmark['name'], {})
        js_landmarks.append({
            'index': i,
            'name': str(landmark['name']),
            'type': str(landmark['type']),
            'latitude': float(landmark['latitude']),
            'longitude': float(landmark['longitude']),
            'distance_km': float(landmark['distance_km']),
            'travel_days': float(landmark.get('travel_days', 0)),
            'sepolia_cost': round(landmark.get('calculated_cost', 0), 1),
            'diameter_km': float(landmark['diameter_km']) if landmark.get('diameter_km') else 0,
            'quad_name': str(landmark['quad_name']),
            'link': str(landmark['link']),
            'is_discovered': landmark.get('is_discovered', False),
            'last_visit': landmark.get('last_visit').isoformat() if landmark.get('last_visit') else None,
            'last_yield': float(landmark.get('last_yield', 0)) * 10000000 if landmark.get('last_yield') else 0,
            'trail_level': trail.get('trail_level', 'none'),
            'trail_trip_count': trail.get('trip_count', 0)
        })

    # Get infrastructure effects for UI display
    try:
        from utilities.infrastructure_utils import get_user_infrastructure_effects
        infra_effects = get_user_infrastructure_effects(user_id)
    except Exception:
        infra_effects = {}

    # Bug #1419: surface every meaningful expedition bonus, not just the 3 infrastructure
    # ones. upgrade_effects already aggregates upgrades + infra + tech + scientist + bond
    # picks. Cargo capacity comes from the active vehicle list (cargo_slots is summed
    # across all owned vehicles, but for display we surface the highest single-vehicle slot).
    expedition_bonuses = {
        # Infrastructure / building bonuses (kept for backwards-compat keys + the
        # original Comms / Launch Pad / Space Elevator chips)
        'expedition_range_mult': infra_effects.get('expedition_range_mult', 1.0),
        'legendary_chance_bonus': upgrade_effects.get('legendary_chance_bonus', 0.0),
        'discovery_chance_bonus': upgrade_effects.get('discovery_chance_bonus', 0.0),

        # Bug #1419 — additional bonuses (all sourced from the universal effects aggregator)
        'expedition_speed_mult': upgrade_effects.get('expedition_speed_mult', 1.0),
        'vehicle_range_mult': upgrade_effects.get('vehicle_range_mult', 1.0),
        'rare_chance_bonus': upgrade_effects.get('rare_chance_bonus', 0.0),
        'discovery_value_mult': upgrade_effects.get('discovery_value_mult', 1.0),
        'bio_discovery_value_mult': upgrade_effects.get('bio_discovery_value_mult', 1.0),
        'fuel_cost_mult': upgrade_effects.get('fuel_cost_mult', 1.0),
        'life_support_cost_mult': upgrade_effects.get('life_support_cost_mult', 1.0),
        'cargo_slots': upgrade_effects.get('cargo_slots', 0),
        'signal_detection_enabled': upgrade_effects.get('signal_detection_enabled', False),
        'dust_storm_immune': upgrade_effects.get('dust_storm_immune', False),
    }

    # Calculate max concurrent expeditions - vehicle-based (max 3)
    try:
        from utilities.upgrades_utils import count_user_vehicles, get_user_owned_vehicles, get_upgrade_stats
        vehicle_count = count_user_vehicles(user_id)
        owned_vehicles = get_user_owned_vehicles(user_id)
    except Exception:
        vehicle_count = 1
        owned_vehicles = [{'vehicle_type': 'rover', 'name': 'Scout Rover', 'cargo': 5}]

    # Discovery-based range multiplier (same formula used in estimate_expedition)
    # × scanner vehicle_range_mult × tech vehicle_range_mult (Chassis Reinforcement, #1447).
    discovery_count = len(discovered_landmarks) if discovered_landmarks else 0
    fog_radius = min(1000, 300 + discovery_count * 50)
    range_mult = fog_radius / 300.0
    scanner_range_mult = upgrade_effects.get('vehicle_range_mult', 1.0)
    from utilities.tech_utils import get_tech_effects as _get_tech_eff
    tech_range_mult = _get_tech_eff(user_id).get('vehicle_range_mult', 1.0)

    # Determine which vehicle types are currently on active expeditions
    active_vehicle_types = {e.get('vehicle_type', 'rover') for e in active_expeditions
                            if e.get('status') in ('traveling', 'recalled')}

    # "In transit" — expeditions that consume a vehicle slot. Excludes returned-but-
    # unclaimed (status='complete'), which still appear in active_expeditions so users
    # can see the Claim button but do NOT occupy a slot.
    traveling_expeditions = [e for e in active_expeditions
                             if e.get('status') in ('traveling', 'recalled')]

    # Enrich vehicles with range breakdown data + availability
    for v in owned_vehicles:
        vtype = v.get('vehicle_type', 'rover')
        base_range = v.get('max_range_km', 9999)
        lv1_stats = get_upgrade_stats('vehicles', vtype, 1) or {}
        v['base_range_km'] = lv1_stats.get('max_range_km', base_range)
        v['base_speed'] = lv1_stats.get('expedition_speed_mult', v.get('speed_mult', 1.0))
        v['effective_range_km'] = int(base_range * range_mult * scanner_range_mult * tech_range_mult)
        v['available'] = vtype not in active_vehicle_types

    # Bug #1454 (Luke 2026-05-10 picked Option A): Active Bonuses panel must render
    # one Speed chip per owned vehicle showing THIS vehicle's launch multiplier
    # (vehicle.speed_mult × tech-only speed mult). The aggregate expedition_speed_mult
    # above is max-across-vehicles × tech and overstates speed for every vehicle
    # except the fastest owned — exactly the gap lifecycle.py:190-195 overrides
    # at launch time. Per-vehicle chips match launch reality 1:1.
    tech_speed_mult = _get_tech_eff(user_id).get('expedition_speed_mult', 1.0)
    _vehicle_icon_key = {'rover': 'vehicle_rover', 'drone': 'vehicle_drone', 'buggy': 'vehicle_buggy'}
    vehicle_speed_chips = []
    for v in owned_vehicles:
        vtype = v.get('vehicle_type', 'rover')
        speed_mult = float(v.get('speed_mult', 1.0)) * float(tech_speed_mult)
        vehicle_speed_chips.append({
            'vehicle_type': vtype,
            'label': f"{v.get('name', vtype.title())} Speed",
            'value_mult': speed_mult,
            'icon_key': _vehicle_icon_key.get(vtype, 'rocket_launch'),
        })
    expedition_bonuses['vehicle_speed_chips'] = vehicle_speed_chips

    # Expedition slots: vehicle count capped by habitat capacity (default 3 if no habitat)
    expedition_cap = infra_effects.get('expedition_capacity', 3)
    max_concurrent_expeditions = min(vehicle_count, expedition_cap)

    # ARIA bonds for Signal tab display
    signal_bonds = []
    try:
        from utilities.aria.bonds import get_bonds_for_display
        signal_bonds = get_bonds_for_display(user_id)
    except Exception:
        pass

    bond_bonus_state = None
    try:
        from utilities.aria.bond_bonuses import get_bond_bonus_state_for_user
        bond_bonus_state = get_bond_bonus_state_for_user(user_id)
    except Exception:
        pass

    return {
        'drop_coords': home_coords,
        'landmarks': landmarks,
        'active_expeditions': active_expeditions,
        'traveling_expeditions': traveling_expeditions,
        'discovered_landmarks': discovered_landmarks,
        'landmarks_json': json.dumps(js_landmarks),
        'base_lat': float(home_coords['latitude']),
        'base_lon': float(home_coords['longitude']),
        'total_balance': total_balance,
        'just_completed_expedition': just_completed_expedition,  # For ARIA to announce
        'expedition_bonuses': expedition_bonuses,  # Infrastructure bonuses for UI
        'max_concurrent_expeditions': max_concurrent_expeditions,  # Based on vehicles owned
        'owned_vehicles': owned_vehicles,  # List of user's vehicles for slot display
        'vehicle_count': vehicle_count,  # Total vehicles owned
        'expedition_count': expeditions_completed,  # Total completed expeditions for History tab
        'discovery_count': discovery_count,  # For range breakdown display
        'range_mult': round(range_mult, 2),  # Discovery-based range multiplier
        'signal_bonds': signal_bonds,  # ARIA bonds for Signal tab
        'bond_bonus_state': bond_bonus_state,  # Bug #1402 — fragment-bond bonus picker state
    }
