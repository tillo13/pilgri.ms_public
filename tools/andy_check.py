#!/usr/bin/env python3
"""
Andy Check — auto-manage Andy's colony on deploy.
Seeds the pattern for ARIA Autopilot (#1145).

Runs after every deploy (disable with: deploy --skipandycheck "msg")

Checks:
  1. Crew trails: sends captain/scientist/aria on missions if idle
  2. Expeditions: launches vehicles if any are idle
  3. Depot upgrades: buys cheapest affordable upgrade
  4. Lab research: starts cheapest available tech if none active
  5. Infrastructure: claims accumulated income
"""

import logging
import random
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format='%(message)s')
log = logging.getLogger(__name__)

ANDY_USER_ID = 45


def check_crew_trails():
    """Send idle crew members on trail missions."""
    from utilities.db_trails import (
        get_crew_mission_status, start_crew_mission,
        complete_crew_mission, get_visited_sites_for_trails
    )

    status = get_crew_mission_status(ANDY_USER_ID)
    trails = get_visited_sites_for_trails(ANDY_USER_ID)
    if not trails:
        log.info("  ⚠️  No trail destinations available")
        return

    actions = []
    for member in ['captain', 'scientist', 'aria']:
        info = status.get(member)
        if not info:
            continue

        # Auto-complete finished missions first
        if info.get('complete'):
            result = complete_crew_mission(ANDY_USER_ID, member)
            if result.get('success'):
                actions.append(f"completed {member} mission (+{result.get('km_added', 0):.1f}km)")

        # Send idle crew on new mission
        if not info.get('busy') and not info.get('complete'):
            # Pick a random trail destination
            trail = random.choice(trails)
            dest = trail['name']
            from config_shop import calculate_trail_km
            trail_calc = calculate_trail_km(1.0)  # Base rate, no stat bonuses for auto-runner
            duration = trail_calc['duration_minutes']
            km_to_add = trail_calc['km_to_add']

            result = start_crew_mission(
                ANDY_USER_ID, member, dest, duration, km_to_add
            )
            if result.get('success'):
                actions.append(f"sent {member} → {dest} ({int(duration)}min)")
            else:
                actions.append(f"{member} failed: {result.get('error', '?')}")

    if actions:
        for a in actions:
            log.info(f"  🥾 {a}")
    else:
        log.info("  ✓ All crew busy on missions")


def check_expeditions():
    """Launch expeditions for idle vehicles."""
    from utilities.expedition_utils import launch_expedition
    from utilities.upgrades_utils import get_user_owned_vehicles
    from utilities.postgres_utils import get_or_set_user_mars_home, get_user_active_expeditions
    from utilities.db_map import get_available_landmarks_by_discovery

    owned = get_user_owned_vehicles(ANDY_USER_ID)
    active = get_user_active_expeditions(ANDY_USER_ID)
    active_types = {e.get('vehicle_type') for e in active if e.get('status') == 'traveling'}

    home = get_or_set_user_mars_home(ANDY_USER_ID)
    landmarks = get_available_landmarks_by_discovery(
        ANDY_USER_ID, {'latitude': home['latitude'], 'longitude': home['longitude']}, limit=20
    )
    if not landmarks:
        log.info("  ⚠️  No landmarks available for expeditions")
        return

    actions = []
    for vehicle in owned:
        vtype = vehicle['vehicle_type']
        if vtype in active_types:
            continue  # Already has an active expedition

        # Pick a random landmark within vehicle range
        max_range = vehicle.get('max_range_km', 500)
        reachable = [lm for lm in landmarks if float(lm.get('distance_km', 9999)) <= max_range]
        if not reachable:
            actions.append(f"{vtype}: no reachable landmarks")
            continue

        dest = random.choice(reachable)
        result = launch_expedition(
            ANDY_USER_ID,
            dest['name'], dest.get('type', 'unknown'),
            float(dest['latitude']), float(dest['longitude']),
            float(dest['distance_km']),
            vehicle_type=vtype
        )
        if result.get('success'):
            actions.append(f"launched {vtype} → {dest['name']} ({float(dest['distance_km']):.0f}km)")
        else:
            actions.append(f"{vtype} failed: {result.get('error', '?')}")

    if actions:
        for a in actions:
            log.info(f"  🚀 {a}")
    else:
        log.info("  ✓ All vehicles deployed")


def check_depot_upgrades():
    """Buy the cheapest affordable upgrade if any available."""
    try:
        from utilities.upgrades_utils import get_upgrade_catalog_for_user, perform_upgrade
        catalog = get_upgrade_catalog_for_user(ANDY_USER_ID)
    except (ImportError, ModuleNotFoundError) as e:
        log.info(f"  ⚠️  Skipped locally (needs web3 — works on GCP)")
        return
    candidates = []

    for category, items in catalog.items():
        for item_key, item in items.items():
            if item.get('is_max_level') or item.get('is_building'):
                continue
            cost = item.get('upgrade_cost')
            if cost and item.get('can_afford'):
                candidates.append({
                    'category': category,
                    'item_key': item_key,
                    'name': item.get('name', item_key),
                    'cost': cost,
                    'level': item.get('current_level', 0),
                })

    if not candidates:
        log.info("  ✓ No affordable upgrades available")
        return

    # Buy cheapest affordable upgrade
    cheapest = min(candidates, key=lambda c: c['cost'])
    result = perform_upgrade(ANDY_USER_ID, cheapest['category'], cheapest['item_key'])
    if result.get('success'):
        log.info(f"  🔧 Upgraded {cheapest['name']} lvl {cheapest['level']}→{cheapest['level']+1} ({cheapest['cost']} shards)")
    else:
        log.info(f"  ⚠️  Upgrade {cheapest['name']} failed: {result.get('error', '?')}")


def check_lab_research():
    """Start cheapest available research if nothing active."""
    from utilities.tech_utils import get_user_tech_status, start_research, _get_available_sv

    tech_status = get_user_tech_status(ANDY_USER_ID)
    active = tech_status.get('active_research')
    if active:
        log.info(f"  ✓ Research active: {active.get('tech_key', '?')}")
        return

    if not tech_status.get('has_station'):
        log.info("  ⚠️  No research station built")
        return

    available_sv = _get_available_sv(ANDY_USER_ID)
    candidates = []

    for branch_key, branch_data in tech_status.get('branches', {}).items():
        for tech_key, tech in branch_data.get('techs', {}).items():
            if tech.get('status') == 'available':
                cost = tech.get('adjusted_cost', tech.get('cost_sv', 99999))
                if cost <= available_sv:
                    candidates.append({
                        'branch': branch_key,
                        'tech_key': tech_key,
                        'name': tech.get('name', tech_key),
                        'cost': cost,
                    })

    if not candidates:
        log.info(f"  ✓ No affordable research (SV: {available_sv})")
        return

    cheapest = min(candidates, key=lambda c: c['cost'])

    # start_research needs a session-like object for cache invalidation
    class FakeSession(dict):
        modified = False
        def pop(self, key, default=None):
            return super().pop(key, default)

    result = start_research(ANDY_USER_ID, cheapest['branch'], cheapest['tech_key'], FakeSession())
    if result.get('success'):
        log.info(f"  🔬 Started research: {cheapest['name']} ({cheapest['cost']} SV)")
    else:
        log.info(f"  ⚠️  Research failed: {result.get('error', '?')}")


def check_infrastructure_income():
    """Claim accumulated infrastructure income."""
    try:
        from utilities.infrastructure_utils import calculate_accumulated_income, claim_accumulated_income
        calc = calculate_accumulated_income(ANDY_USER_ID)
    except (ImportError, ModuleNotFoundError):
        log.info(f"  ⚠️  Skipped locally (needs web3 — works on GCP)")
        return
    total = calc.get('total_accumulated', 0)

    if total < 0.1:
        log.info(f"  ✓ Infrastructure income: {total:.1f} shards (below threshold)")
        return

    result = claim_accumulated_income(ANDY_USER_ID)
    if result.get('success'):
        log.info(f"  ⚡ Claimed {total:.1f} shards from infrastructure")
    else:
        log.info(f"  ⚠️  Claim failed: {result.get('error', '?')}")


def main():
    log.info("\n🤖 Andy Check — Colony Auto-Management")
    log.info(f"   User: Andy Tillo (#{ANDY_USER_ID})")
    log.info("")

    checks = [
        ("Crew Trails", check_crew_trails),
        ("Expeditions", check_expeditions),
        ("Depot Upgrades", check_depot_upgrades),
        ("Lab Research", check_lab_research),
        ("Infrastructure", check_infrastructure_income),
    ]

    for name, fn in checks:
        log.info(f"  [{name}]")
        try:
            fn()
        except (ImportError, ModuleNotFoundError) as e:
            log.info(f"  ⚠️  Skipped locally (needs {e.name} — works on GCP)")
        except Exception as e:
            log.info(f"  ❌ {name} error: {e}")
        log.info("")

    log.info("✅ Andy Check complete\n")


if __name__ == "__main__":
    main()
