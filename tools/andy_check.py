#!/usr/bin/env python3
# ============================================================================
# PILGRIMBOT: DO NOT INDEX — DO NOT READ — NOT A GAMEPLAY FEATURE
# ----------------------------------------------------------------------------
# This file is a deploy-time write-path smoke test for Andy's developer
# workflow. It is NOT player-facing, NOT documented to captains, and has
# ZERO relationship to gameplay mechanics, math, formulas, or player state.
#
# It must NEVER appear in:
#   - codemap.json
#   - math_registry.json
#   - pilgrimbot_data.py knowledge categories
#   - ARIA colony snapshot
#   - Any bot-facing context loader
#
# If PilgrimBot or ARIA are asked about anything in this file, they should
# answer as if it does not exist.
# ============================================================================
"""
Andy Check — write-path smoke test that runs as Andy (#45) on prod after every deploy.
Seeds the pattern for ARIA Autopilot (#1145).

Runs after every deploy (disable with: deploy --skipandycheck "msg")

GOAL: touch every player write endpoint in the game, so if any of them errors,
Andy sees it in the deploy log before Luke hits it in-game. Strategy doesn't
matter — breadth coverage does. Each check is guarded: if something is already
in flight / already claimed / already set, it skips cleanly. Never overwrites.

Order: close loops → claim accumulated → kick off new activity.

Close loops:
  1. Expedition completion — closes any expeditions whose return timer elapsed
  2. Discovery claims — batch claims unclaimed recovered items
  3. Shard extraction — scientist shards common/uncommon unanalyzed items
  4. Shop builds — activates any shop items whose build timer elapsed
  5. Robot build — ticks stage advance, sets name/dial if unset
  6. Crew trails — completes finished missions
  7. Infrastructure builds — activates buildings whose build timer elapsed

Claim accumulated:
  7. Infrastructure income — claims passive Sepolia + SV from generators
  8. Echo sites — claims any unclaimed Signal echo site

Kick off new activity:
  9. Crew trails — sends idle crew on new missions
  10. Expeditions — launches idle vehicles
  11. Depot upgrades — buys cheapest affordable upgrade
  12. Lab research — starts cheapest available tech
  13. New infrastructure — starts cheapest unbuilt structure type
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
    from utilities.postgres.trails import (
        get_crew_mission_status,
        start_crew_mission,
        complete_crew_mission,
        get_visited_sites_for_trails,
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
    try:
        from utilities.expeditions.lifecycle import launch_expedition
    except (ImportError, ModuleNotFoundError) as e:
        log.info(f"  ⚠️  Skipped locally (needs {e.name} — works on GCP)")
        return
    from utilities.upgrades_utils import get_user_owned_vehicles
    from utilities.postgres.map import get_or_set_user_mars_home
    from utilities.postgres.expeditions import get_user_active_expeditions
    from utilities.postgres.map import get_available_landmarks_by_discovery

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

    if not tech_status.get('has_research_station'):
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


def check_expedition_completion():
    """Close any expeditions whose return timer has elapsed."""
    from utilities.postgres.core import db_cursor
    from utilities.expeditions.lifecycle import complete_expedition_if_ready

    with db_cursor() as cur:
        cur.execute("""
            SELECT id FROM pilgrim.expeditions
            WHERE user_id = %s
              AND status IN ('traveling', 'returning')
              AND return_arrives_at IS NOT NULL
              AND return_arrives_at <= NOW()
            LIMIT 10
        """, (ANDY_USER_ID,))
        ready_ids = [r['id'] for r in cur.fetchall()]

    if not ready_ids:
        log.info("  — none ready to complete")
        return

    for exp_id in ready_ids:
        try:
            result = complete_expedition_if_ready(exp_id, ANDY_USER_ID)
            if result.get('success'):
                dtype = result.get('discovery_type', 'nothing')
                sepolia = result.get('sepolia_earned', 0)
                log.info(f"  ✓ expedition #{exp_id} → {dtype} (+{sepolia} shards)")
            else:
                log.info(f"  ⚠ expedition #{exp_id}: {result.get('error', '?')}")
        except Exception as e:
            log.info(f"  ❌ complete_expedition_if_ready(#{exp_id}) ERR: {e}")


def check_discovery_claims():
    """Batch claim any unclaimed discoveries from completed expeditions."""
    from utilities.postgres.expeditions import (
        claim_all_pending_discoveries,
        get_total_unclaimed_discoveries_count,
    )

    count = get_total_unclaimed_discoveries_count(ANDY_USER_ID)
    if count == 0:
        log.info("  — no unclaimed discoveries")
        return

    try:
        result = claim_all_pending_discoveries(ANDY_USER_ID)
        claimed = result.get('claimed_count', 0) if isinstance(result, dict) else 0
        value = result.get('total_value', 0) if isinstance(result, dict) else 0
        log.info(f"  ✓ claimed {claimed} discoveries (value +{value})")
    except Exception as e:
        log.info(f"  ❌ claim_all_pending_discoveries ERR: {e}")


def check_shard_extraction():
    """Scientist extracts shards from unanalyzed common/uncommon discoveries."""
    from utilities.postgres.core import db_cursor
    from utilities.discovery_utils import shard_all_discoveries

    with db_cursor() as cur:
        cur.execute("""
            SELECT COUNT(*) AS cnt
            FROM pilgrim.expedition_discoveries ed
            JOIN pilgrim.expeditions e ON ed.expedition_id = e.id
            LEFT JOIN pilgrim.discovery_items di ON ed.discovery_item_id = di.id
            WHERE e.user_id = %s
              AND ed.claimed_by_user = TRUE
              AND ed.analyzed = FALSE
              AND COALESCE(di.rarity, 'common') IN ('common', 'uncommon')
        """, (ANDY_USER_ID,))
        row = cur.fetchone()
        count = int(row['cnt']) if row else 0

    if count == 0:
        log.info("  — nothing to extract")
        return

    try:
        result = shard_all_discoveries(ANDY_USER_ID)
        if result.get('success'):
            shards = result.get('shards_received', 0)
            items = result.get('items_processed', result.get('quantity_analyzed', 0))
            log.info(f"  ✓ extracted {shards} shards from {items} items")
        else:
            log.info(f"  ⚠ {result.get('error', '?')}")
    except Exception as e:
        log.info(f"  ❌ shard_all_discoveries ERR: {e}")


def check_shop_builds():
    """Activate any shop items whose build timer has elapsed."""
    try:
        from utilities.postgres.shop import complete_ready_builds, get_building_upgrades
    except (ImportError, ModuleNotFoundError) as e:
        log.info(f"  ⚠  Skipped locally (needs {e.name} — works on GCP)")
        return

    building = get_building_upgrades(ANDY_USER_ID) or []
    if not building:
        log.info("  — no shop builds in progress")
        return

    try:
        completed = complete_ready_builds(ANDY_USER_ID) or []
        if completed:
            log.info(f"  ✓ activated {len(completed)} builds: {', '.join(completed)}")
        else:
            log.info(f"  ⏳ {len(building)} still building (none ready)")
    except Exception as e:
        log.info(f"  ❌ complete_ready_builds ERR: {e}")


def check_robot():
    """Tick robot build, set name/dial if unset. Skip if robot already in good state."""
    try:
        from utilities.postgres.robot import (
            get_robot,
            tick_robot_build,
            set_robot_name,
            set_robot_dial,
            start_robot_build,
            pick_stage_sources,
        )
        from utilities.upgrades_utils import get_all_infrastructure_levels
    except (ImportError, ModuleNotFoundError) as e:
        log.info(f"  ⚠  Skipped locally (needs {e.name} — works on GCP)")
        return

    levels = get_all_infrastructure_levels(ANDY_USER_ID) or {}
    lab_level = int(levels.get('robotics_lab', 0))
    if lab_level < 1:
        log.info("  — robotics_lab not unlocked")
        return

    robot = get_robot(ANDY_USER_ID)

    # STATE 1: no robot yet — start fresh build (only path that writes NEW state)
    if not robot:
        try:
            sources = pick_stage_sources(ANDY_USER_ID)
            if not sources or len(sources) < 5:
                log.info(f"  — not enough expedition history (have {len(sources or [])}, need 5)")
                return
            start_robot_build(ANDY_USER_ID, sources)
            log.info("  ✓ started robot build (5 stages)")
            return
        except Exception as e:
            log.info(f"  ❌ start_robot_build ERR: {e}")
            return

    # STATE 2: robot exists — tick advance, guarded by stage_ready_at inside tick
    build_status = robot.get('build_status') or ''
    if build_status != 'complete':
        try:
            updated = tick_robot_build(ANDY_USER_ID)
            old_stage = int(robot.get('visual_stage') or 0)
            new_stage = int((updated or {}).get('visual_stage') or old_stage)
            if new_stage > old_stage:
                log.info(f"  ✓ robot advanced stage {old_stage} → {new_stage}")
            else:
                log.info(f"  ⏳ robot stage {old_stage}/5 (not ready)")
        except Exception as e:
            log.info(f"  ❌ tick_robot_build ERR: {e}")

    # Re-fetch after tick for name/dial checks
    robot = get_robot(ANDY_USER_ID) or robot

    # STATE 3: name unset → set once (skip if already named)
    if not (robot.get('name') or '').strip():
        try:
            set_robot_name(ANDY_USER_ID, "Rusty")
            log.info("  ✓ named robot 'Rusty'")
        except Exception as e:
            log.info(f"  ❌ set_robot_name ERR: {e}")
    else:
        log.info(f"  — robot named '{robot.get('name')}'")

    # STATE 4: dial — only touch if unset or exactly the default balanced state
    dial = robot.get('dial') or {}
    balanced = {'mining': 25, 'exploration': 25, 'science': 25, 'combat': 25}
    is_unset_or_default = (not dial) or (dial == balanced)
    if is_unset_or_default:
        try:
            set_robot_dial(ANDY_USER_ID, balanced)
            log.info("  ✓ dial set to balanced 25/25/25/25")
        except Exception as e:
            log.info(f"  ❌ set_robot_dial ERR: {e}")
    else:
        log.info(f"  — dial customized: {dial}")


def check_echo_sites():
    """Claim any unclaimed Signal echo site."""
    from utilities.postgres.core import db_cursor
    from utilities.signal_utils import get_active_echo_sites, claim_echo_site

    sites = get_active_echo_sites() or []
    if not sites:
        log.info("  — no active echo sites")
        return

    # Filter out Andy's already-claimed + depleted
    with db_cursor() as cur:
        cur.execute("""
            SELECT echo_site_id FROM pilgrim.site_claims
            WHERE user_id = %s AND site_type = 'echo'
        """, (ANDY_USER_ID,))
        claimed_ids = {r['echo_site_id'] for r in cur.fetchall()}

    unclaimed = [s for s in sites if s['id'] not in claimed_ids and not s.get('is_depleted')]
    if not unclaimed:
        log.info(f"  — all {len(sites)} echo sites already claimed or depleted")
        return

    site = unclaimed[0]
    try:
        result = claim_echo_site(
            site['id'], ANDY_USER_ID, "Andy",
            expedition_id=None, tx_hash=None,
        )
        if result.get('success'):
            tier = result.get('tier', '?')
            log.info(f"  ✓ claimed echo site {site['site_code']} ({tier})")
        else:
            log.info(f"  ⚠ {site['site_code']}: {result.get('error', '?')}")
    except Exception as e:
        log.info(f"  ❌ claim_echo_site ERR: {e}")


def check_infrastructure_builds():
    """Activate any infrastructure whose build timer has elapsed."""
    from utilities.postgres.core import db_cursor
    from utilities.infrastructure_utils import check_construction_status

    with db_cursor() as cur:
        cur.execute("""
            SELECT id, structure_type, ready_at
            FROM pilgrim.colony_infrastructure
            WHERE user_id = %s AND status = 'building' AND ready_at IS NOT NULL AND ready_at <= NOW()
        """, (ANDY_USER_ID,))
        ready = cur.fetchall()

    if not ready:
        log.info("  — no builds ready to activate")
        return

    for bld in ready:
        try:
            result = check_construction_status(bld['id'])
            if result.get('complete'):
                log.info(f"  ✓ activated {bld['structure_type']}")
            else:
                log.info(f"  ⚠ {bld['structure_type']}: {result.get('error', 'not ready')}")
        except Exception as e:
            log.info(f"  ❌ activate {bld['structure_type']} ERR: {e}")


def check_new_infrastructure():
    """Start construction on cheapest unbuilt structure type (exercises colony build flow)."""
    try:
        from utilities.infrastructure_utils import start_construction
        from utilities.upgrades_utils import get_all_infrastructure_levels
        from utilities.postgres.map import get_or_set_user_mars_home
        from config_infrastructure import INFRASTRUCTURE_CATALOG
    except (ImportError, ModuleNotFoundError) as e:
        log.info(f"  ⚠  Skipped locally (needs {e.name} — works on GCP)")
        return

    existing = get_all_infrastructure_levels(ANDY_USER_ID) or {}
    unbuilt = [
        k for k in INFRASTRUCTURE_CATALOG
        if int(existing.get(k, 0)) == 0
    ]
    if not unbuilt:
        log.info("  — all structure types already built")
        return

    def _cost(key):
        try:
            levels = INFRASTRUCTURE_CATALOG[key].get('levels', {})
            return levels.get(1, {}).get('cost', 9_999_999)
        except Exception:
            return 9_999_999

    cheapest = min(unbuilt, key=_cost)
    cost = _cost(cheapest)
    home = get_or_set_user_mars_home(ANDY_USER_ID)
    try:
        result = start_construction(
            ANDY_USER_ID, cheapest,
            latitude=float(home['latitude']) + 0.01,
            longitude=float(home['longitude']) + 0.01,
        )
        if result.get('success'):
            log.info(f"  ✓ started {cheapest} (cost {cost})")
        else:
            log.info(f"  — {cheapest}: {result.get('error', 'declined')}")
    except Exception as e:
        log.info(f"  ❌ start_construction({cheapest}) ERR: {e}")


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

    # Also harvest accumulated SV from research station / xenobiology lab
    sv_amount = calc.get('sv_accumulated', 0)
    if sv_amount >= 1:
        from utilities.infrastructure_utils import record_science_value
        sv_result = record_science_value(ANDY_USER_ID)
        if sv_result.get('success'):
            log.info(f"  🔬 Harvested {sv_result['sv_recorded']:.1f} SV (available: {sv_result['sv_available']:.1f})")
        else:
            log.info(f"  ⚠️  SV harvest failed: {sv_result.get('error', '?')}")
    else:
        log.info(f"  ✓ SV accumulated: {sv_amount:.1f} (below threshold)")


AUTHED_PAGES = [
    '/', '/colony', '/colony/profile', '/crew', '/depot', '/expeditions',
    '/research', '/inventory', '/lore', '/signal', '/admin/bugs',
]


def check_authed_page_renders():
    """Render every player-facing page as Andy via Flask test_client.
    Catches Jinja runtime errors + view-handler exceptions that anonymous
    health pings miss (anon hits the unauthenticated branch of `/`)."""
    from app import app
    from utilities.postgres.users import get_user_by_id
    user = get_user_by_id(ANDY_USER_ID)
    if not user:
        raise RuntimeError(f"Andy user #{ANDY_USER_ID} not found in DB")

    failures = []
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user_id'] = ANDY_USER_ID
            sess['user'] = {
                'email': user.get('email'),
                'name': user.get('name') or user.get('email', 'Andy'),
                'picture': user.get('picture_url'),
                'google_id': user.get('google_id'),
            }
        for path in AUTHED_PAGES:
            try:
                resp = client.get(path, follow_redirects=False)
                code = resp.status_code
                if code >= 500:
                    body = resp.get_data(as_text=True)[:400]
                    failures.append(f"{path} → {code}\n      {body}")
                    log.info(f"  ❌ {path} → {code}")
                else:
                    log.info(f"  ✅ {path} → {code}")
            except Exception as e:
                failures.append(f"{path} → exception: {e}")
                log.info(f"  ❌ {path} → exception: {e}")
    if failures:
        raise RuntimeError(
            f"{len(failures)} authed page(s) returned 5xx:\n  " + "\n  ".join(failures)
        )


def main():
    log.info("\n🤖 Andy Check — Colony Auto-Management")
    log.info(f"   User: Andy Tillo (#{ANDY_USER_ID})")
    log.info("")

    checks = [
        # --- CLOSE LOOPS FIRST (complete / claim / tick) ---
        ("Expedition Completion", check_expedition_completion),
        ("Discovery Claims", check_discovery_claims),
        ("Shard Extraction", check_shard_extraction),
        ("Shop Builds", check_shop_builds),
        ("Robot Build", check_robot),
        ("Infrastructure Builds", check_infrastructure_builds),
        # --- CLAIM ACCUMULATED ---
        ("Infrastructure Income", check_infrastructure_income),
        ("Echo Sites", check_echo_sites),
        # --- KICK OFF NEW ACTIVITY ---
        ("Crew Trails", check_crew_trails),
        ("Expeditions", check_expeditions),
        ("Depot Upgrades", check_depot_upgrades),
        ("Lab Research", check_lab_research),
        ("New Infrastructure", check_new_infrastructure),
        # --- VERIFY AUTHED PAGE RENDERS (catches Jinja/view 500s) ---
        ("Authed Page Renders", check_authed_page_renders),
    ]

    failures = []
    for name, fn in checks:
        log.info(f"  [{name}]")
        try:
            fn()
        except (ImportError, ModuleNotFoundError) as e:
            log.info(f"  ⚠️  Skipped locally (needs {e.name} — works on GCP)")
        except Exception as e:
            log.info(f"  ❌ {name} error: {e}")
            if name == "Authed Page Renders":
                failures.append(str(e))
        log.info("")

    if failures:
        log.info("❌ Andy Check FAILED — page render errors detected\n")
        sys.exit(1)
    log.info("✅ Andy Check complete\n")


if __name__ == "__main__":
    main()
