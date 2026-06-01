"""Colony page view data (formerly Inventory)."""

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def get_colony_page_data(user_id, auth):
    """
    Get all data needed for the Colony page (formerly Inventory).
    Includes: discoveries, equipment, infrastructure, vehicles, building items.
    """
    from datetime import datetime
    from utilities.postgres.shop import get_building_upgrades, complete_ready_builds
    from utilities.postgres.core import db_cursor
    from utilities.infrastructure_utils import get_user_infrastructure, INFRASTRUCTURE_CATALOG, get_or_set_user_mars_home, calculate_generation_rate
    from utilities.upgrades_utils import get_user_owned_vehicles
    from config_upgrades import UPGRADE_CATALOG
    from utilities.depot_utils import get_fast_balance_and_wallet_info

    total_balance = get_fast_balance_and_wallet_info(user_id)[0]

    # Get user's Mars home coordinates for solar calculations
    coords = get_or_set_user_mars_home(user_id)

    # Get infrastructure - separate active vs building
    existing_raw = get_user_infrastructure(user_id)
    active_infrastructure = []
    building_infrastructure = []

    # Fetch actual infrastructure levels from player_upgrades (single query)
    from utilities.upgrades_utils import get_all_user_upgrades
    all_upgrades = get_all_user_upgrades(user_id)
    infra_levels = all_upgrades.get('infrastructure', {})

    for building in existing_raw:
        enriched = dict(building)
        catalog_def = INFRASTRUCTURE_CATALOG.get(building['structure_type'], {})
        # Get actual level from player_upgrades, default to 1 if building exists
        current_level = infra_levels.get(building['structure_type'], 1)
        enriched['level'] = current_level
        level_data = catalog_def.get('levels', {}).get(current_level, {})

        # Basic catalog data
        enriched['name'] = catalog_def.get('name', building['structure_type'].replace('_', ' ').title())
        # Image resolution: walk back to nearest level with image (Lv2+ often empty)
        from utilities.upgrade_image_utils import get_best_available_image
        enriched['image_url'] = get_best_available_image('infrastructure', building['structure_type'], current_level)
        enriched['icon'] = catalog_def.get('icon', '')
        enriched['description'] = catalog_def.get('description', '')
        enriched['effect'] = catalog_def.get('effect')
        enriched['effect_value'] = catalog_def.get('effect_value')
        # #1409: surface level-scoped end-game bonuses (all-stat buffs + all_generation)
        # so the building modal shows what makes End-Game buildings rewarding — not just
        # shards/hr. Config sets the 5 captain-stat bonuses equal per level, so collapse
        # them to one "+N All Stats" value; fall back to per-stat if they ever diverge.
        _STAT_BONUS_KEYS = ('stat_exploration_bonus', 'stat_leadership_bonus',
                            'stat_strategy_bonus', 'stat_logistics_bonus', 'stat_charisma_bonus')
        _stat_vals = [level_data.get(k) for k in _STAT_BONUS_KEYS if level_data.get(k)]
        enriched['all_stats_bonus'] = (int(_stat_vals[0])
                                       if len(_stat_vals) == 5 and len(set(_stat_vals)) == 1 else None)
        enriched['all_generation_mult'] = level_data.get('all_generation_mult')
        enriched['generates_resource'] = catalog_def.get('generates_resource')
        enriched['tier'] = catalog_def.get('tier', 1)
        enriched['category'] = catalog_def.get('category', 'general')
        enriched['total_generated'] = float(building.get('total_generated', 0) or 0)
        enriched['cost_display'] = int(level_data.get('cost', 0))  # Already in display units
        enriched['requirements'] = catalog_def.get('requirements', [])
        enriched['build_time_total'] = level_data.get('build_time_days', 0) * 86400  # Convert to seconds
        enriched['tx_hash'] = building.get('tx_hash', '')

        # Format dates for display (include exact time for user reference)
        if building.get('created_at'):
            enriched['created_at_str'] = building['created_at'].strftime('%b %d, %Y at %I:%M %p')
            # Calculate time active/owned
            time_owned = datetime.now() - building['created_at']
            days_owned = time_owned.days
            if days_owned > 0:
                enriched['time_owned_str'] = f"{days_owned} day{'s' if days_owned != 1 else ''}"
            else:
                hours_owned = int(time_owned.total_seconds() / 3600)
                enriched['time_owned_str'] = f"{hours_owned} hour{'s' if hours_owned != 1 else ''}"
        else:
            enriched['time_owned_str'] = ''

        if building.get('build_completed_at'):
            enriched['completed_at_str'] = building['build_completed_at'].strftime('%b %d, %Y at %I:%M %p')
            # Time active since completion
            time_active = datetime.now() - building['build_completed_at']
            days_active = time_active.days
            if days_active > 0:
                enriched['time_active_str'] = f"{days_active} day{'s' if days_active != 1 else ''}"
            else:
                hours_active = int(time_active.total_seconds() / 3600)
                enriched['time_active_str'] = f"{hours_active} hour{'s' if hours_active != 1 else ''}"
        else:
            enriched['time_active_str'] = ''

        if building.get('ready_at'):
            enriched['ready_at_str'] = building['ready_at'].strftime('%b %d, %Y at %I:%M %p')
            enriched['ready_at_iso'] = building['ready_at'].isoformat()

        # Calculate generation rate
        if building['structure_type'] == 'solar_array':
            enriched['generation_rate'] = calculate_generation_rate('solar_array', coords['latitude'], coords['longitude'])
        else:
            enriched['generation_rate'] = float(catalog_def.get('generation_rate', 0.0))

        # Calculate remaining time for building items
        if building['status'] == 'building' and building.get('ready_at'):
            remaining = (building['ready_at'] - datetime.now()).total_seconds()
            enriched['seconds_remaining'] = max(0, int(remaining))
        else:
            enriched['seconds_remaining'] = 0

        if building['status'] == 'active':
            active_infrastructure.append(enriched)
        elif building['status'] == 'building':
            building_infrastructure.append(enriched)

    # Legacy shop building items removed — all builds now use upgrade system
    building_equipment = []

    # Get owned vehicles with COMPREHENSIVE stats
    raw_vehicles = get_user_owned_vehicles(user_id)
    owned_vehicles = []

    # Check which vehicles are currently on active expeditions + lifetime stats
    expedition_vehicles = {}
    vehicle_lifetime_stats = {}
    with db_cursor() as cur:
        cur.execute("""
            SELECT id, vehicle_type, destination_name, distance_km, status,
                   departed_at, arrives_at, return_arrives_at
            FROM pilgrim.expeditions
            WHERE user_id = %s AND status IN ('traveling', 'recalled')
        """, (user_id,))
        for row in cur.fetchall():
            expedition_vehicles[row['vehicle_type']] = {
                'id': row['id'],
                'destination': row['destination_name'],
                'distance_km': row['distance_km'],
                'status': row['status'],
                'departed_at': row['departed_at'],
                'arrives_at': row['arrives_at'],
                'returns_at': row['return_arrives_at'],
            }
        # Lifetime stats per vehicle type — uses denormalized discovery_count (no JOIN)
        cur.execute("""
            SELECT vehicle_type, COUNT(*) as trips, SUM(distance_km) as total_km,
                   SUM(discovery_count) as total_finds
            FROM pilgrim.expeditions
            WHERE user_id = %s AND status = 'complete'
            GROUP BY vehicle_type
        """, (user_id,))
        for row in cur.fetchall():
            vehicle_lifetime_stats[row['vehicle_type']] = {
                'trips': row['trips'],
                'total_km': float(row['total_km']),
                'total_finds': row['total_finds'] or 0,
            }

    # Bulk-fetch ALL vehicle acquisition dates in one query (not per-vehicle)
    vehicle_upgrades = {}
    with db_cursor() as cur:
        cur.execute("""
            SELECT item_key, upgraded_at, tx_hash FROM pilgrim.player_upgrades
            WHERE user_id = %s AND category = 'vehicles'
        """, (user_id,))
        for row in cur.fetchall():
            vehicle_upgrades[row['item_key']] = row

    from utilities.upgrade_image_utils import get_best_available_image

    for v in raw_vehicles:
        enriched = dict(v)
        vehicle_config = UPGRADE_CATALOG.get('vehicles', {}).get(v['vehicle_type'], {})
        level_stats = vehicle_config.get('levels', {}).get(v['level'], {})

        # Image fallback: walk back to nearest level with image (Lv2+ often empty)
        enriched['image_url'] = get_best_available_image('vehicles', v['vehicle_type'], v['level'])

        # Add catalog data
        enriched['description'] = vehicle_config.get('description', '')
        enriched['max_level'] = vehicle_config.get('max_level', 1)
        enriched['fuel_cost_mult'] = level_stats.get('fuel_cost_mult', 1.0)
        enriched['cost_paid'] = level_stats.get('cost', 0)

        # Lifetime stats
        lifetime = vehicle_lifetime_stats.get(v['vehicle_type'], {})
        enriched['lifetime_trips'] = lifetime.get('trips', 0)
        enriched['lifetime_km'] = lifetime.get('total_km', 0)
        enriched['lifetime_finds'] = lifetime.get('total_finds', 0)
        # Total Cost = sum of all upgrade costs from level 1 to current level
        total_cost = sum(vehicle_config.get('levels', {}).get(lv, {}).get('cost', 0) for lv in range(1, v['level'] + 1))
        enriched['lifetime_cost'] = total_cost

        # Range/speed breakdown data
        lv1_stats = vehicle_config.get('levels', {}).get(1, {})
        enriched['base_range_km'] = lv1_stats.get('max_range_km', v.get('max_range_km', 0))
        enriched['base_speed'] = lv1_stats.get('expedition_speed_mult', v.get('speed_mult', 1.0))

        # Next level preview
        next_level = v['level'] + 1
        next_stats = vehicle_config.get('levels', {}).get(next_level)
        if next_stats:
            enriched['next_level'] = next_level
            enriched['next_level_name'] = next_stats.get('name', f'Level {next_level}')
            enriched['next_level_cost'] = next_stats.get('cost', 0)
            enriched['next_level_cargo'] = next_stats.get('cargo', 0)
            enriched['next_level_speed'] = next_stats.get('expedition_speed_mult', 1.0)
            enriched['next_level_build_days'] = next_stats.get('build_time_days', 0)
        else:
            enriched['next_level'] = None  # Max level reached

        # Acquisition date from bulk-fetched data
        upgrade_row = vehicle_upgrades.get(v['vehicle_type'])
        if upgrade_row:
            enriched['acquired_at'] = upgrade_row['upgraded_at']
            enriched['acquired_at_str'] = upgrade_row['upgraded_at'].strftime('%b %d, %Y at %I:%M %p') if upgrade_row['upgraded_at'] else ''
            enriched['tx_hash'] = upgrade_row['tx_hash'] or ''
        else:
            enriched['acquired_at_str'] = 'Starting equipment'
            enriched['tx_hash'] = ''

        # Check expedition status
        exp_info = expedition_vehicles.get(v['vehicle_type'])
        if exp_info:
            enriched['on_expedition'] = True
            enriched['expedition_id'] = exp_info['id']
            enriched['expedition_destination'] = exp_info['destination']
            enriched['expedition_distance_km'] = exp_info['distance_km']
            enriched['expedition_status'] = exp_info['status']
            enriched['expedition_departed_at'] = exp_info['departed_at']
            enriched['expedition_departed_at_iso'] = exp_info['departed_at'].isoformat() + 'Z' if exp_info['departed_at'] else ''
            enriched['expedition_arrives_at_iso'] = exp_info['arrives_at'].isoformat() + 'Z' if exp_info['arrives_at'] else ''
            enriched['expedition_returns_at'] = exp_info['returns_at']
            enriched['expedition_returns_at_str'] = exp_info['returns_at'].strftime('%b %d, %Y at %I:%M %p') if exp_info['returns_at'] else ''
            enriched['expedition_returns_at_iso'] = exp_info['returns_at'].isoformat() + 'Z' if exp_info['returns_at'] else ''
        else:
            enriched['on_expedition'] = False

        owned_vehicles.append(enriched)

    # Welcome-back modal gating: compute hours_away from last meaningful activity
    welcome_back = {}
    try:
        with db_cursor() as cur:
            cur.execute("SELECT previous_login, last_login, last_meaningful_activity_at FROM pilgrim.users WHERE id = %s", (user_id,))
            urow = cur.fetchone()
        if urow and urow.get('previous_login') != urow.get('last_login'):
            from datetime import timezone
            ref = urow.get('last_meaningful_activity_at') or urow.get('previous_login') or urow.get('last_login')
            if ref:
                if ref.tzinfo is None:
                    ref = ref.replace(tzinfo=timezone.utc)
                hours_away = (datetime.now(timezone.utc) - ref).total_seconds() / 3600
                if hours_away > 1:
                    welcome_back = {'show': True, 'previous_activity_iso': ref.isoformat()}
    except Exception:
        pass

    # Get ARIA bond data (pending + completed)
    from utilities.aria.bonds import get_user_bonds
    raw_bonds = get_user_bonds(user_id)

    # Bulk-fetch all partner names in one query (not per-bond)
    partner_ids = [b.get('partner_id') for b in raw_bonds if b.get('partner_id')]
    partner_names = {}
    if partner_ids:
        with db_cursor() as cur:
            cur.execute("SELECT id, captain_name FROM pilgrim.users WHERE id = ANY(%s)", (partner_ids,))
            for row in cur.fetchall():
                partner_names[row['id']] = row['captain_name']

    aria_bonds = []
    for b in raw_bonds:
        partner_id = b.get('partner_id')
        partner_name = partner_names.get(partner_id, f"Captain {partner_id}") if partner_id else None
        aria_bonds.append({
            'id': b['id'],
            'landmark_name': b['landmark_name'],
            'status': b['status'],
            'partner_name': partner_name or 'Unknown',
            'partner_id': partner_id,
            'bond_tx_hash': b.get('bond_tx_hash', ''),
            'bond_image_url': b.get('bond_image_url', ''),
            'my_submitted': b.get('fragment_1_submitted') if user_id == b.get('user_id_1') else b.get('fragment_2_submitted'),
            'created_at': b['created_at'].strftime('%b %d, %Y') if b.get('created_at') else '',
            'bonded_at': b['bonded_at'].strftime('%b %d, %Y') if b.get('bonded_at') else '',
        })

    # Discovery-based range multiplier (for vehicle range display)
    from utilities.postgres.expeditions import get_user_discovered_landmarks
    discovered = get_user_discovered_landmarks(user_id)
    discovery_count = len(discovered) if discovered else 0
    fog_radius = min(1000, 300 + discovery_count * 50)
    range_mult = round(fog_radius / 300.0, 2)

    # Enrich vehicles with effective range
    for v in owned_vehicles:
        v['effective_range_km'] = int(v.get('max_range_km', 0) * range_mult)

    # Get income calculation with multipliers so colony UI shows effective rates
    income_data = {}
    try:
        from utilities.infrastructure_utils import calculate_accumulated_income
        income_calc = calculate_accumulated_income(user_id)
        income_data = {
            # effective_rate is the TRUE rate (day/night + dust + temp + bonuses),
            # NOT theoretical_max_rate (the ceiling). Bug fix: Effective Rate P1.
            'effective_rate': income_calc.get('rate_breakdown', {}).get('effective_rate', 0),
            'base_rate': income_calc.get('rate_breakdown', {}).get('base_hourly_rate', 0),
            'effective_base_rate': income_calc.get('rate_breakdown', {}).get('effective_base_rate', 0),
            'day_night_efficiency': income_calc.get('rate_breakdown', {}).get('day_night_efficiency', 100),
            'mars_env_multiplier': income_calc.get('rate_breakdown', {}).get('mars_env_multiplier', 100),
            'passive_income_mult': income_calc.get('bonuses_applied', {}).get('passive_income_mult', 1.0),
            'passive_income_source': income_calc.get('bonuses_applied', {}).get('passive_income_source'),
            'all_generation_mult': income_calc.get('bonuses_applied', {}).get('all_generation_mult', 1.0),
            'passive_income_base': income_calc.get('bonuses_applied', {}).get('passive_income_base', 0),
            'scientist_shard_mult': income_calc.get('bonuses_applied', {}).get('scientist_shard_mult', 1.0),
            'theoretical_max_rate': income_calc.get('rate_breakdown', {}).get('theoretical_max_rate', 0),
            'signal_bonus': income_calc.get('signal_bonus', {
                'shards_per_hour': 0, 'sv_per_hour': 0, 'sites_count': 0, 'per_tier': {}
            }),
            # Bug #1423: surface Fragment Bond contributions for the breakdown UI
            'bond_shards_per_hour': income_calc.get('bond_shards_per_hour', 0),
            'bond_sv_per_hour': income_calc.get('bond_sv_per_hour', 0),
            'bond_shards_mult': income_calc.get('bond_shards_mult', 1.0),
            'bond_sv_mult': income_calc.get('bond_sv_mult', 1.0),
        }
    except Exception as e:
        logger.warning(f"Could not get income calc for colony: {e}")

    # Bug #1160: Discoveries Collection Codex — lifetime grid + found-based milestones.
    # Server-rendered (no extra fetch). Exactly 3 reads: the discovery grid (1 grouped
    # LEFT JOIN) + the earned-milestone rows (1 cheap query, no join) + the Signal
    # Relics axis (1 grouped origin_sites LEFT JOIN site_claims, Option B). Rewards are
    # constants, no query. Deliberately NOT calling get_codex_milestones here — it would
    # re-run the per-category JOIN the grid already computed (db-speed-first / /colony db
    # budget; measured 24->25, smoke ceiling bumped to 26 to keep a 1-query cushion —
    # the NEXT /colony feature must bulk-fetch or bump again).
    try:
        from utilities.postgres.expeditions import get_user_discovery_codex
        from utilities.sv_milestones import (get_earned_codex_milestones,
                                             CODEX_CATEGORY_REWARD_SV, CODEX_TOTAL_REWARD_SV)
        discovery_codex = get_user_discovery_codex(user_id)
        _earned = get_earned_codex_milestones(user_id)
        codex_milestones = {
            'earned': _earned,
            'earned_keys': [r['milestone_key'] for r in _earned],
            'category_rewards': CODEX_CATEGORY_REWARD_SV,
            'total_reward': CODEX_TOTAL_REWARD_SV,
        }
    except Exception as e:
        logger.warning(f"Could not build discovery codex for colony: {e}")
        discovery_codex = {'categories': {}, 'total_collected': 0, 'total_items': 0}
        codex_milestones = {'earned': [], 'earned_keys': [], 'category_rewards': {}, 'total_reward': 0}

    # Bug #1160 Option B (Luke 2026-05-31): Signal Relics — the 14 Origin Site
    # legendaries shown as a DISTINCT axis so the legendary total reads honestly.
    # Display-only, no SV, doesn't touch the validated 60/25/12/3=100 discovery math.
    try:
        from utilities.signal.sites import get_user_signal_relics
        signal_relics = get_user_signal_relics(user_id)
    except Exception as e:
        logger.warning(f"Could not build signal relics for colony: {e}")
        signal_relics = {'relics': [], 'found_count': 0, 'total': 0}
    # Honest legendary reconciliation for Luke's count question (data-driven, no hardcode):
    discovery_legendary_count = sum(
        1 for cat in discovery_codex.get('categories', {}).values()
        for it in cat.get('items', []) if it.get('rarity') == 'legendary'
    )
    total_legendary_count = discovery_legendary_count + signal_relics.get('total', 0)

    return {
        'user': auth.get_current_user(),
        'total_balance': total_balance,
        'active_infrastructure': active_infrastructure,
        'building_infrastructure': building_infrastructure,
        'building_equipment': building_equipment,
        'owned_vehicles': owned_vehicles,
        'aria_bonds': aria_bonds,
        'welcome_back': welcome_back,
        'now': datetime.now(),
        'discovery_count': discovery_count,
        'range_mult': range_mult,
        'income_data': income_data,
        'discovery_codex': discovery_codex,
        'codex_milestones': codex_milestones,
        'signal_relics': signal_relics,
        'discovery_legendary_count': discovery_legendary_count,
        'total_legendary_count': total_legendary_count,
    }
