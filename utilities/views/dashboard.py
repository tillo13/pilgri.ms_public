"""Dashboard page view data + fleet status helper."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any

from utilities.views.while_you_were_away import get_while_you_were_away_summary
from utilities.views.misc import build_recent_activity

logger = logging.getLogger(__name__)


def get_fleet_status(user_id: int, debug_mode: bool = False) -> Dict[str, Any]:
    """
    Get status of all 3 mobility slots (rover, drone, buggy) for Fleet Status bar.

    Returns dict with 3 slots, each containing:
    - status: 'at_base', 'en_route', 'returned'
    - For en_route: destination, eta, distance_km, progress_pct
    - For returned: distance_km, shards_earned, discoveries (list with rarity breakdown), distance_bonus

    Distance bonus tiers (Fallout Shelter style):
    - < 200km: 1x (none)
    - 200-500km: 2x "Long Haul"
    - 500-1000km: 3x "Deep Expedition"
    - 1000-2000km: 5x "Frontier Run"
    - 2000+ km: 10x "Legendary Journey"
    """
    from utilities.postgres.core import db_cursor

    def get_distance_bonus(distance_km: float) -> Dict:
        """Get multiplier and label for distance."""
        if distance_km < 200:
            return {'mult': 1, 'label': None}
        elif distance_km < 500:
            return {'mult': 2, 'label': 'Long Haul'}
        elif distance_km < 1000:
            return {'mult': 3, 'label': 'Deep Expedition'}
        elif distance_km < 2000:
            return {'mult': 5, 'label': 'Frontier Run'}
        else:
            return {'mult': 10, 'label': 'Legendary Journey'}

    # Initialize all 3 slots as "at_base"
    fleet = {
        'rover': {'status': 'at_base', 'vehicle_name': 'Rover', 'icon': '🚗'},
        'drone': {'status': 'at_base', 'vehicle_name': 'Drone', 'icon': '🚁'},
        'buggy': {'status': 'at_base', 'vehicle_name': 'Buggy', 'icon': '🛞'}
    }

    # Debug mode: show mock data for all slots
    if debug_mode:
        now = datetime.now()
        fleet['rover'] = {
            'status': 'en_route', 'vehicle_name': 'Rover', 'icon': '🚗',
            'destination': 'Olympus Mons', 'distance_km': 847,
            'eta_iso': (now + timedelta(hours=2, minutes=34)).isoformat(),
            'progress_pct': 65, 'departed_at_iso': (now - timedelta(hours=5)).isoformat()
        }
        fleet['drone'] = {
            'status': 'returned', 'vehicle_name': 'Drone', 'icon': '🚁',
            'destination': 'Jezero Crater', 'distance_km': 1247,
            'shards_earned': 142, 'expedition_id': 999,
            'discoveries': [
                {'rarity': 'rare', 'count': 1},
                {'rarity': 'uncommon', 'count': 2},
                {'rarity': 'common', 'count': 1}
            ],
            'total_discoveries': 4,
            'distance_bonus': get_distance_bonus(1247)
        }
        fleet['buggy'] = {
            'status': 'at_base', 'vehicle_name': 'Buggy', 'icon': '🛞'
        }
        return fleet

    try:
        with db_cursor() as cur:
            now = datetime.now()

            # Get all expeditions for this user that are active or recently completed
            cur.execute("""
                SELECT e.id, e.vehicle_type, e.status, e.destination_name, e.distance_km,
                       e.departed_at, e.arrives_at, e.return_arrives_at, e.sepolia_earned,
                       e.completed_at,
                       COALESCE(unclaimed.count, 0) as unclaimed_discoveries
                FROM pilgrim.expeditions e
                LEFT JOIN (
                    SELECT expedition_id, COUNT(*) as count
                    FROM pilgrim.expedition_discoveries
                    WHERE claimed_by_user = false
                    GROUP BY expedition_id
                ) unclaimed ON unclaimed.expedition_id = e.id
                WHERE e.user_id = %s
                  AND (e.status = 'traveling'
                       OR (e.status = 'complete' AND COALESCE(unclaimed.count, 0) > 0))
                ORDER BY e.departed_at DESC
            """, (user_id,))
            expeditions = cur.fetchall()

            # Bug #1431: bulk-fetch unclaimed discovery breakdowns for every expedition that
            # might need one, instead of issuing a per-expedition query inside the loop below.
            # Was N+1 (up to 3 extra queries per dashboard load); now 1 query covers all slots.
            disc_breakdown_by_exp: Dict[int, list] = {}
            disc_total_by_exp: Dict[int, int] = {}
            exp_ids = [e['id'] for e in expeditions]
            if exp_ids:
                cur.execute("""
                    SELECT ed.expedition_id, di.rarity, COUNT(*) as count
                    FROM pilgrim.expedition_discoveries ed
                    JOIN pilgrim.discovery_items di ON di.id = ed.discovery_item_id
                    WHERE ed.expedition_id = ANY(%s) AND ed.claimed_by_user = false
                    GROUP BY ed.expedition_id, di.rarity
                """, (exp_ids,))
                for row in cur.fetchall():
                    eid = row['expedition_id']
                    disc_breakdown_by_exp.setdefault(eid, []).append({'rarity': row['rarity'], 'count': row['count']})
                    disc_total_by_exp[eid] = disc_total_by_exp.get(eid, 0) + row['count']

            for exp in expeditions:
                vehicle_type = exp['vehicle_type'] or 'rover'
                if vehicle_type not in fleet:
                    continue

                # Skip if this slot already has data (take most recent)
                if fleet[vehicle_type]['status'] != 'at_base':
                    continue

                distance_km = float(exp['distance_km'] or 0)
                distance_bonus = get_distance_bonus(distance_km)

                if exp['status'] == 'traveling':
                    # Calculate progress and ETA
                    departed_at = exp['departed_at']
                    return_arrives_at = exp['return_arrives_at'] or exp['arrives_at']
                    total_seconds = (return_arrives_at - departed_at).total_seconds() if departed_at and return_arrives_at else 0
                    elapsed_seconds = (now - departed_at).total_seconds() if departed_at else 0
                    progress_pct = min(100, (elapsed_seconds / total_seconds * 100)) if total_seconds > 0 else 0

                    # Check if expedition has actually returned (return_arrives_at passed)
                    if return_arrives_at and now >= return_arrives_at:
                        # Discovery breakdown was bulk-fetched above (bug #1431)
                        discoveries = disc_breakdown_by_exp.get(exp['id'], [])
                        total_disc = disc_total_by_exp.get(exp['id'], 0)

                        fleet[vehicle_type] = {
                            'status': 'returned', 'vehicle_name': vehicle_type.title(), 'icon': fleet[vehicle_type]['icon'],
                            'destination': exp['destination_name'], 'distance_km': distance_km,
                            'shards_earned': round(float(exp['sepolia_earned'] or 0) * 10000000, 1),
                            'expedition_id': exp['id'],
                            'discoveries': discoveries, 'total_discoveries': total_disc,
                            'distance_bonus': distance_bonus
                        }
                    else:
                        # Still traveling
                        fleet[vehicle_type] = {
                            'status': 'en_route', 'vehicle_name': vehicle_type.title(), 'icon': fleet[vehicle_type]['icon'],
                            'destination': exp['destination_name'], 'distance_km': distance_km,
                            'eta_iso': return_arrives_at.isoformat() if return_arrives_at else None,
                            'progress_pct': round(progress_pct, 1),
                            'departed_at_iso': departed_at.isoformat() if departed_at else None
                        }

                elif exp['status'] == 'complete' and exp['unclaimed_discoveries'] > 0:
                    # Returned with unclaimed discoveries — breakdown bulk-fetched above (bug #1431)
                    discoveries = disc_breakdown_by_exp.get(exp['id'], [])
                    total_disc = disc_total_by_exp.get(exp['id'], 0)

                    fleet[vehicle_type] = {
                        'status': 'returned', 'vehicle_name': vehicle_type.title(), 'icon': fleet[vehicle_type]['icon'],
                        'destination': exp['destination_name'], 'distance_km': distance_km,
                        'shards_earned': round(float(exp['sepolia_earned'] or 0) * 10000000, 1),
                        'expedition_id': exp['id'],
                        'discoveries': discoveries, 'total_discoveries': total_disc,
                        'distance_bonus': distance_bonus
                    }

    except Exception as e:
        logger.error(f"Error getting fleet status for user {user_id}: {e}")

    return fleet


def get_dashboard_page_data(user_id, auth):
    """Get all data needed for colony/dashboard page."""
    from utilities.postgres.wallets import get_user_sepolia_wallets
    from utilities.postgres.users import get_user_by_google_id
    from utilities.postgres.expeditions import get_user_active_expeditions, get_user_completed_expeditions_count, get_user_visited_locations_count
    from utilities.postgres.trails import get_crew_mission_status
    from utilities.postgres.assets import get_user_replicate_assets
    from utilities.postgres.core import db_cursor
    from utilities.infrastructure_utils import get_user_infrastructure
    from utilities.depot_utils import get_fast_balance_and_wallet_info, get_commander_and_stats

    wallets = get_user_sepolia_wallets(user_id)
    images = get_user_replicate_assets(user_id, asset_type='character_image', limit=1)

    # If user is missing wallet or captain, something went wrong during onboarding
    # Log the issue but don't redirect - let them stay on dashboard
    if not wallets:
        logger.warning(f"User {user_id} has no wallet - onboarding incomplete")
    if not images:
        logger.warning(f"User {user_id} has no captain - onboarding incomplete")

    user = get_user_by_google_id(auth.get_current_user().get('google_id'))
    total_balance, _, primary_wallet = get_fast_balance_and_wallet_info(user_id)  # FAST: no blockchain
    commander, commander_stats = get_commander_and_stats(user_id)
    active_expeditions = get_user_active_expeditions(user_id)

    # Get real expedition stats
    completed_expeditions = get_user_completed_expeditions_count(user_id)
    visited_locations = get_user_visited_locations_count(user_id)
    total_expeditions = completed_expeditions + len(active_expeditions)

    # Safely get captain - handle case where user has no captain yet
    has_commander = commander is not None or len(images) > 0
    commander_data = commander or (images[0] if images else None)

    # Get live Mars environment data
    try:
        from utilities.mars_environment_utils import get_mars_environment_summary
        mars_env = get_mars_environment_summary()
    except Exception as e:
        logger.warning(f"Failed to get Mars environment: {e}")
        mars_env = None

    # Get "While You Were Away" summary
    away_summary = get_while_you_were_away_summary(user_id)

    # Get building items (upgrades + infrastructure)
    building_items = []
    # Upgrade system builds
    try:
        from utilities.upgrades_utils import get_active_builds
        for build in get_active_builds(user_id):
            building_items.append({
                'name': build['name'],
                'seconds_remaining': build['seconds_remaining'],
                'total_seconds': build['seconds_remaining'],
                'progress_pct': 0,
                'ready_at': None,
                'ready_at_str': build.get('ready_at_str', '')
            })
    except Exception as e:
        logger.warning(f"Failed to get upgrade builds for dashboard: {e}")
    # Add infrastructure builds
    # Bug #1431: fetch infrastructure ONCE — was being queried twice per dashboard load
    # (once here for the building queue, once at the bottom for has_infrastructure).
    user_infrastructure = get_user_infrastructure(user_id)
    try:
        from config_infrastructure import INFRASTRUCTURE_CATALOG
        for infra in user_infrastructure:
            if infra.get('status') == 'building' and infra.get('ready_at'):
                ready_at = infra['ready_at']
                if hasattr(ready_at, 'tzinfo') and ready_at.tzinfo is None:
                    ready_at = ready_at.replace(tzinfo=timezone.utc)
                secs = max(0, int((ready_at - datetime.now(timezone.utc)).total_seconds()))
                cat = INFRASTRUCTURE_CATALOG.get(infra['structure_type'], {})
                building_items.append({
                    'name': cat.get('name', infra['structure_type'].replace('_', ' ').title()),
                    'seconds_remaining': secs,
                    'total_seconds': secs,
                    'progress_pct': 0,
                    'ready_at': ready_at,
                    'ready_at_str': ready_at.strftime('%b %d')
                })
    except Exception as e:
        logger.warning(f"Failed to get infra builds for dashboard: {e}")
    building_items.sort(key=lambda b: b['seconds_remaining'])

    crew_missions = get_crew_mission_status(user_id)

    # Bug #1317 items 7+8: enrich with seconds_remaining so briefing can show time-left
    _now = datetime.now(timezone.utc)
    for _exp in active_expeditions:
        _end = _exp.get('return_arrives_at') or _exp.get('arrives_at')
        if _end and _exp.get('status') not in ('complete',):
            _end_aware = _end if getattr(_end, 'tzinfo', None) else _end.replace(tzinfo=timezone.utc)
            _exp['seconds_until_arrival'] = max(0, int((_end_aware - _now).total_seconds()))
    for _member in ('captain', 'scientist', 'aria'):
        _m = crew_missions.get(_member) if crew_missions else None
        if _m and _m.get('ends_at'):
            try:
                _ends = datetime.fromisoformat(_m['ends_at'].replace('Z', '+00:00'))
                if not _ends.tzinfo:
                    _ends = _ends.replace(tzinfo=timezone.utc)
                _m['seconds_remaining'] = max(0, int((_ends - _now).total_seconds()))
            except Exception:
                _m['seconds_remaining'] = 0

    # ========================================================================
    # LIVE RATES: Calculate rates for ticking briefing panel stats
    # All rates are per SECOND for smooth JS animation
    # ========================================================================
    live_rates = {
        'shard_rate': 0,      # shards per second
        'km_rate': 0,         # km per second (from expeditions)
        'tech_rate': 0,       # tech tree % per second (from active research)
        'trail_rate': 0,      # trail km per second (from crew missions)
        'build_rate': 0,      # build % per second (from building queue)
    }

    # 1. SHARD RATE: From infrastructure
    try:
        from utilities.infrastructure_utils import calculate_accumulated_income
        income_calc = calculate_accumulated_income(user_id)
        # Use effective_rate (day/night/env/dust accounted for), NOT theoretical_max_rate
        # which is the ceiling assuming perpetual daylight — would tick the top bar faster
        # than the player actually earns. Bug fix: Effective Rate P1.
        hourly_rate = income_calc.get('rate_breakdown', {}).get('effective_rate', 0)
        live_rates['shard_rate'] = hourly_rate / 3600  # per second
    except Exception:
        pass

    # 2. KM RATE: From active expeditions (round trip: out + back)
    try:
        for exp in active_expeditions:
            if exp.get('status') in ('traveling', 'recalled') and exp.get('distance_km') and exp.get('departed_at'):
                departed = exp['departed_at']
                # Use return_arrives_at for full round-trip, fall back to arrives_at for one-way
                end_time = exp.get('return_arrives_at') or exp.get('arrives_at')
                if end_time and hasattr(departed, 'timestamp') and hasattr(end_time, 'timestamp'):
                    travel_seconds = (end_time - departed).total_seconds()
                    if travel_seconds > 0:
                        # Round trip = distance * 2
                        round_trip_km = float(exp['distance_km']) * 2
                        speed_per_sec = round_trip_km / travel_seconds
                        live_rates['km_rate'] += speed_per_sec
    except Exception:
        pass

    # 3. TECH RATE: From active research (% progress per second)
    try:
        tech_prog = away_summary.get('tech_progress', {})
        if tech_prog.get('active_research') and tech_prog.get('active_remaining_secs', 0) > 0:
            current_pct = tech_prog.get('active_progress_pct', 0)
            remaining_secs = tech_prog['active_remaining_secs']
            # Rate = remaining % / remaining seconds
            remaining_pct = 100 - current_pct
            live_rates['tech_rate'] = remaining_pct / remaining_secs
    except Exception:
        pass

    # 4. TRAIL RATE: From crew missions (km per second)
    try:
        now = datetime.now(timezone.utc)
        for member in ['captain', 'scientist', 'aria']:
            mission = crew_missions.get(member)
            if mission and mission.get('busy') and not mission.get('complete'):
                ends_at_str = mission.get('ends_at')
                km_to_add = mission.get('km_pending', 0)
                if ends_at_str and km_to_add > 0:
                    # ends_at is ISO string, parse it
                    ends_at = datetime.fromisoformat(ends_at_str.replace('Z', '+00:00'))
                    if ends_at.tzinfo is None:
                        ends_at = ends_at.replace(tzinfo=timezone.utc)
                    secs_remaining = (ends_at - now).total_seconds()
                    if secs_remaining > 0:
                        live_rates['trail_rate'] += km_to_add / secs_remaining
        logger.debug(f"Trail rate calculated: {live_rates['trail_rate']}")
    except Exception as e:
        logger.warning(f"Trail rate calculation failed: {e}")

    # 5. BUILD RATE: From building queue (average % per second across all builds)
    avg_build_progress = 0
    try:
        if building_items:
            total_progress = sum(b['progress_pct'] for b in building_items)
            avg_build_progress = total_progress / len(building_items)
            # Rate = average remaining % / average remaining seconds
            total_remaining_pct = sum(100 - b['progress_pct'] for b in building_items)
            total_remaining_secs = sum(b['seconds_remaining'] for b in building_items if b['seconds_remaining'] > 0)
            if total_remaining_secs > 0:
                live_rates['build_rate'] = total_remaining_pct / total_remaining_secs / len(building_items)
    except Exception as e:
        logger.warning(f"Build rate calculation failed: {e}")

    # Fleet Status bar (debug mode from query param)
    from flask import request
    fleet_debug = request.args.get('show_expeditions', '').lower() == 'true'
    fleet_status = get_fleet_status(user_id, debug_mode=fleet_debug)
    if fleet_debug:
        logger.info(f"🚀 FLEET DEBUG MODE: fleet_status={fleet_status}")

    # Welcome-back modal gating
    welcome_back = {}
    try:
        with db_cursor() as cur:
            cur.execute("SELECT previous_login, last_login, last_meaningful_activity_at FROM pilgrim.users WHERE id = %s", (user_id,))
            urow = cur.fetchone()
        if urow and urow.get('previous_login') != urow.get('last_login'):
            ref = urow.get('last_meaningful_activity_at') or urow.get('previous_login') or urow.get('last_login')
            if ref:
                if ref.tzinfo is None:
                    ref = ref.replace(tzinfo=timezone.utc)
                hours_away = (datetime.now(timezone.utc) - ref).total_seconds() / 3600
                if hours_away > 1:
                    welcome_back = {'show': True, 'previous_activity_iso': ref.isoformat()}
    except Exception:
        pass

    # Get completed ARIA bonds for dashboard display
    completed_bonds = []
    try:
        from utilities.aria.bonds import get_bonds_for_display
        completed_bonds = get_bonds_for_display(user_id)
    except Exception as e:
        logger.warning(f"Could not fetch completed bonds: {e}")

    # Last completed buggy expedition for cinematic card
    last_buggy_expedition = None
    try:
        from utilities.postgres.expeditions import get_last_completed_buggy_expedition
        from utilities.upgrades_utils import get_user_upgrade_level
        lbe = get_last_completed_buggy_expedition(user_id)
        if lbe:
            buggy_level = get_user_upgrade_level(user_id, 'vehicles', 'buggy')
            lbe['buggy_level'] = buggy_level
            lbe['shards_display'] = int(float(lbe.get('sepolia_earned') or 0) * 10000000)
            if lbe.get('departed_at') and lbe.get('completed_at'):
                lbe['travel_hours'] = round((lbe['completed_at'] - lbe['departed_at']).total_seconds() / 3600, 1)
            # Get longhaul hero image for player's buggy level
            from config_upgrades import UPGRADE_CATALOG
            buggy_cfg = UPGRADE_CATALOG.get('vehicles', {}).get('buggy', {}).get('levels', {}).get(buggy_level, {})
            lbe['longhaul_image_url'] = buggy_cfg.get('longhaul_image_url') or buggy_cfg.get('image_url', '')
            lbe['buggy_name'] = buggy_cfg.get('name', 'Buggy')
            # Sol date for return
            SOL_EPOCH = datetime(2025, 10, 4, tzinfo=timezone.utc)
            if lbe.get('completed_at'):
                completed_utc = lbe['completed_at'].replace(tzinfo=timezone.utc) if not lbe['completed_at'].tzinfo else lbe['completed_at']
                lbe['return_sol'] = int((completed_utc - SOL_EPOCH).total_seconds() // 86400)
            # Current buggy status: idle, traveling, or returned
            buggy_now = next((e for e in active_expeditions if e.get('vehicle_type') == 'buggy' and e.get('status') == 'traveling'), None)
            if buggy_now:
                lbe['buggy_status'] = 'traveling'
                lbe['buggy_current_dest'] = buggy_now.get('destination_name', '')
                lbe['buggy_current_distance'] = float(buggy_now.get('distance_km', 0))
            else:
                lbe['buggy_status'] = 'idle'
                # How long since the last expedition returned
                if lbe.get('completed_at'):
                    now = datetime.now(timezone.utc) if lbe['completed_at'].tzinfo else datetime.now()
                    idle_hours = (now - lbe['completed_at']).total_seconds() / 3600
                    lbe['buggy_idle_hours'] = round(idle_hours, 1)
            # Bug #1317 item 1: hide the card if idle and last expedition returned >7 days ago
            if lbe.get('buggy_status') == 'idle' and lbe.get('buggy_idle_hours', 0) > 24 * 7:
                lbe = None
            last_buggy_expedition = lbe
    except Exception as e:
        logger.warning(f"Could not fetch last buggy expedition: {e}")

    # Bug #1441 (Luke 2026-05-14 P1): the Narog "Passive Trails" summary chip
    # moved from /home Base HQ hero to /crew Narog tab. The helper now lives at
    # utilities/postgres/robot.py::build_narog_summary and is invoked from
    # utilities/views/arrival.py::get_crew_page_data_authenticated.

    return {
        'user': user, 'wallets': wallets, 'primary_wallet': primary_wallet,
        'total_balance': total_balance, 'primary_balance': total_balance, 'has_commander': has_commander,
        'commander': commander_data, 'commander_stats': commander_stats,
        'recent_activity': build_recent_activity(user_id, 10),
        'active_expeditions': active_expeditions,
        'has_infrastructure': len(user_infrastructure) > 0,
        'expedition_stats': {
            'total': total_expeditions,
            'completed': completed_expeditions,
            'active': len(active_expeditions),
            'locations_visited': visited_locations
        },
        'mars_env': mars_env,
        'away_summary': away_summary,
        'building_items': building_items,
        'avg_build_progress': avg_build_progress,
        'crew_missions': crew_missions,
        'live_rates': live_rates,
        'fleet_status': fleet_status,
        'fleet_debug': fleet_debug,
        'welcome_back': welcome_back,
        'completed_bonds': completed_bonds,
        'last_buggy_expedition': last_buggy_expedition,
    }
