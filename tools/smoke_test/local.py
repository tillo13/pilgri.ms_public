#!/usr/bin/env python3
"""
Local Smoke Tests - Pre-deploy verification against local environment.
Run these before deploying to verify DB, config, and utility functions.
"""

from . import test, requires_web3, requires_flask, TESTS, PASSED, FAILED, SKIPPED

# =============================================================================
# TIER 1: QUICK TESTS (~20 critical, must pass before deploy)
# =============================================================================

@test("Database connection", tier=1, features=['db'], mode='local')
def test_db_connection():
    from utilities.postgres.core import get_db_connection
    conn = get_db_connection()
    assert conn is not None, "Failed to get DB connection"
    conn.close()
    return True


@test("Users table has data", tier=1, features=['db'], mode='local')
def test_users_table():
    from utilities.postgres.core import db_cursor
    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM pilgrim.users")
        row = cur.fetchone()
        count = row['count'] if isinstance(row, dict) else row[0]
        assert count > 0, f"No users (count={count})"
    return True


@test("player_upgrades has ready_at column", tier=1, features=['db', 'depot'], mode='local')
def test_upgrades_schema():
    from utilities.postgres.core import db_cursor
    with db_cursor(commit=True) as cur:
        cur.execute("""
            ALTER TABLE pilgrim.player_upgrades
            ADD COLUMN IF NOT EXISTS ready_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS pending_level INTEGER
        """)
    with db_cursor() as cur:
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'pilgrim' AND table_name = 'player_upgrades'
        """)
        cols = [r['column_name'] if isinstance(r, dict) else r[0] for r in cur.fetchall()]
        assert 'ready_at' in cols, f"Missing ready_at. Found: {cols}"
    return True


@test("colony_infrastructure table exists", tier=1, features=['db', 'colony'], mode='local')
def test_infrastructure_table():
    from utilities.postgres.core import db_cursor
    with db_cursor() as cur:
        cur.execute("SELECT 1 FROM pilgrim.colony_infrastructure LIMIT 1")
    return True


@test("player_techs table exists", tier=1, features=['db', 'tech'], mode='local')
def test_techs_table():
    from utilities.postgres.core import db_cursor
    with db_cursor() as cur:
        cur.execute("SELECT 1 FROM pilgrim.player_techs LIMIT 1")
    return True


@test("All Jinja2 templates parse", tier=1, features=['templates'], mode='local')
def test_all_templates_parse():
    import os
    from jinja2 import Environment, FileSystemLoader
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'templates'))
    env = Environment(loader=FileSystemLoader(root))
    broken = []
    for dirpath, _, files in os.walk(root):
        for f in files:
            if not f.endswith('.html'):
                continue
            rel = os.path.relpath(os.path.join(dirpath, f), root)
            try:
                env.get_template(rel)
            except Exception as e:
                broken.append(f"{rel}:{getattr(e, 'lineno', '?')} {e}")
    assert not broken, "Template parse errors:\n  " + "\n  ".join(broken)
    return True


@test("config.py loads", tier=1, features=['config'], mode='local')
def test_config_loads():
    import config
    assert hasattr(config, 'UPGRADE_CATALOG'), "Missing UPGRADE_CATALOG"
    assert hasattr(config, 'UI_ICONS'), "Missing UI_ICONS"
    return True


@test("config_upgrades.py loads", tier=1, features=['config', 'depot'], mode='local')
def test_config_upgrades():
    import config_upgrades
    assert hasattr(config_upgrades, 'UPGRADE_CATALOG'), "Missing UPGRADE_CATALOG"
    assert len(config_upgrades.UPGRADE_CATALOG) >= 3, "Too few categories"
    return True


@test("config_infrastructure.py loads", tier=1, features=['config', 'colony'], mode='local')
def test_config_infrastructure():
    import config_infrastructure
    assert hasattr(config_infrastructure, 'INFRASTRUCTURE_CATALOG')
    assert len(config_infrastructure.INFRASTRUCTURE_CATALOG) >= 10, "Too few buildings"
    return True


@test("config_tech.py loads", tier=1, features=['config', 'tech'], mode='local')
def test_config_tech():
    import config_tech
    assert hasattr(config_tech, 'TECH_CATALOG'), "Missing TECH_CATALOG"
    assert len(config_tech.TECH_CATALOG) >= 4, "Too few branches"
    return True


@test("math_registry.json constants match source", tier=1, features=['config', 'math'], mode='local')
def test_math_registry():
    from tools.validate_math_registry import validate
    mismatches = validate()
    if mismatches:
        details = "; ".join(f"{n}: registry={e}, code={a}" for n, e, a in mismatches)
        return f"Math registry drift: {details}"
    return True


@test("Upgrade Lv2+ has build_time_days", tier=1, features=['config', 'depot'], mode='local')
def test_upgrade_build_times():
    from config_upgrades import UPGRADE_CATALOG
    missing = []
    for cat, items in UPGRADE_CATALOG.items():
        for key, cfg in items.items():
            for lv, stats in cfg.get('levels', {}).items():
                if int(lv) >= 2 and 'build_time_days' not in stats:
                    missing.append(f"{cat}/{key}/Lv{lv}")
    if missing:
        return f"Missing build_time_days: {missing[:3]}..."
    return True


@test("sanitize_tx_error hides blockchain terms", tier=1, features=['blockchain'], mode='local')
@requires_web3
def test_sanitize_error():
    from utilities.sepolia_utils import sanitize_tx_error
    raw = "{'code': -32000, 'message': 'replacement transaction underpriced'}"
    sanitized = sanitize_tx_error(raw)
    assert 'replacement' not in sanitized.lower(), "Raw error leaked"
    assert '-32000' not in sanitized, "Error code leaked"
    return True


@test("eth_to_display/display_to_eth inverses", tier=1, features=['blockchain', 'depot'], mode='local')
@requires_web3
def test_currency_conversion():
    from utilities.depot_utils import eth_to_display, display_to_eth
    original = 1000
    eth = display_to_eth(original)
    back = eth_to_display(eth)
    assert abs(back - original) < 0.01, f"Conversion error: {original} -> {back}"
    return True


@test("get_user_upgrade_level returns int", tier=1, features=['depot'], mode='local')
@requires_web3
def test_get_upgrade_level():
    from utilities.upgrades_utils import get_user_upgrade_level
    level = get_user_upgrade_level(112, 'vehicles', 'rover')
    assert isinstance(level, int), f"Expected int, got {type(level)}"
    return True


@test("get_user_upgrade_effects returns dict", tier=1, features=['depot'], mode='local')
@requires_web3
def test_get_effects():
    from utilities.upgrades_utils import get_user_upgrade_effects
    effects = get_user_upgrade_effects(112)
    assert isinstance(effects, dict), f"Expected dict, got {type(effects)}"
    assert 'expedition_speed_mult' in effects, "Missing expedition_speed_mult"
    return True


@test("get_upgrade_build_status returns dict/None", tier=1, features=['depot'], mode='local')
@requires_web3
def test_build_status():
    from utilities.upgrades_utils import get_upgrade_build_status
    status = get_upgrade_build_status(112, 'vehicles', 'rover')
    assert status is None or isinstance(status, dict)
    return True


@test("Infrastructure catalog valid structure", tier=1, features=['config', 'colony'], mode='local')
def test_infra_structure():
    from config_infrastructure import INFRASTRUCTURE_CATALOG
    for bldg, cfg in INFRASTRUCTURE_CATALOG.items():
        if 'name' not in cfg:
            return f"{bldg} missing name"
        if 'levels' not in cfg:
            return f"{bldg} missing levels"
        if 1 not in cfg['levels']:
            return f"{bldg} missing level 1"
    return True


@test("Depot cost curve floors (#1405)", tier=1, features=['config', 'depot', 'colony'], mode='local')
def test_depot_cost_floors():
    """Bug #1405 rebalance: enforces the L4 / L8 cost floors so future edits
    can't silently undo Luke's calibration. If a path's cost drops below the
    floor at any level in [4..7] or [8..10], surface it. Either re-run
    tools/apply_depot_cost_rebalance.py or update the floors here with a note."""
    MID_L4_FLOOR = 4128   # 40h × Andy's 103.2 shards/hr
    LATE_L8_FLOOR = 54640  # 100h × Luke's 546.4 shards/hr
    from config_infrastructure import INFRASTRUCTURE_CATALOG
    from config_upgrades import UPGRADE_CATALOG

    def _violations(path_label, item_key, levels):
        bad = []
        for lvl, ldata in (levels or {}).items():
            if not isinstance(lvl, int):
                continue
            cost = int((ldata or {}).get('cost') or 0)
            if cost == 0:
                continue
            if 4 <= lvl <= 7 and cost < MID_L4_FLOOR:
                bad.append(f"{path_label}/{item_key} L{lvl}={cost} < mid floor {MID_L4_FLOOR}")
            elif 8 <= lvl <= 10 and cost < LATE_L8_FLOOR:
                bad.append(f"{path_label}/{item_key} L{lvl}={cost} < late floor {LATE_L8_FLOOR}")
        return bad

    violations = []
    for k, cfg in INFRASTRUCTURE_CATALOG.items():
        violations += _violations('infra', k, cfg.get('levels'))
    for cat, cat_dict in UPGRADE_CATALOG.items():
        if not isinstance(cat_dict, dict):
            continue
        for k, cfg in cat_dict.items():
            if isinstance(cfg, dict) and 'levels' in cfg:
                violations += _violations(cat, k, cfg.get('levels'))
    if violations:
        return f"{len(violations)} cost(s) below #1405 floor: " + '; '.join(violations[:5])
    return True


@test("Narog stat math matches #1436 spec", tier=1, features=['config', 'narog'], mode='local')
def test_narog_stat_math():
    """Bug #1436: Foundry L0 = 5/100, L10 = 100/100, linear in between."""
    from utilities.postgres.robot import compute_robot_stat_value, compute_robot_stats, STAT_UNLOCK_FOUNDRY_LEVEL
    if compute_robot_stat_value(0) != 5:
        return f"L0 stat should be 5, got {compute_robot_stat_value(0)}"
    if compute_robot_stat_value(10) != 100:
        return f"L10 stat should be 100, got {compute_robot_stat_value(10)}"
    if compute_robot_stat_value(11) != 100:
        return "L11 stat should clamp to 100"
    if compute_robot_stat_value(-1) != 5:
        return "Negative L should clamp to 5"
    # Spot-check linear ramp at L5 (~52, the midpoint)
    mid = compute_robot_stat_value(5)
    if mid < 50 or mid > 55:
        return f"L5 should be ~52, got {mid}"
    # Unlock thresholds match spec
    if STAT_UNLOCK_FOUNDRY_LEVEL != {'exploration': 0, 'logistics': 3, 'research': 6, 'expeditions': 9}:
        return f"Unlock thresholds drifted: {STAT_UNLOCK_FOUNDRY_LEVEL}"
    # compute_robot_stats locks per spec
    sm = compute_robot_stats(2)  # below all secondary unlocks
    if not sm['exploration']['unlocked']:
        return "Exploration must be unlocked at L2"
    if sm['logistics']['unlocked'] or sm['research']['unlocked'] or sm['expeditions']['unlocked']:
        return "Secondary slots must be locked at L2"
    sm = compute_robot_stats(6)
    if not (sm['logistics']['unlocked'] and sm['research']['unlocked']):
        return "Logistics + Research must unlock by L6"
    if sm['expeditions']['unlocked']:
        return "Expeditions must still be locked at L6"
    return True


@test("Foundry per-level prereqs match #1436 spec", tier=1, features=['config', 'narog'], mode='local')
def test_foundry_level_prereqs():
    """Bug #1436: Foundry L3 ← Habitat Lv3, L6 ← RS+GH Lv6, L9 ← Habitat+GH+RS Lv9."""
    from config_infrastructure import INFRASTRUCTURE_CATALOG
    levels = INFRASTRUCTURE_CATALOG['robotics_lab']['levels']
    expected = {
        3: {'habitat_module': 3},
        6: {'research_station': 6, 'greenhouse': 6},
        9: {'habitat_module': 9, 'greenhouse': 9, 'research_station': 9},
    }
    for lvl, want in expected.items():
        got = levels[lvl].get('level_requires') or {}
        if got != want:
            return f"L{lvl} level_requires drift: got {got}, want {want}"
    # Ensure no other levels carry stray level_requires (would silently gate)
    for lvl in (1, 2, 4, 5, 7, 8, 10):
        if 'level_requires' in levels[lvl]:
            return f"L{lvl} has unexpected level_requires"
    # Catalog name matches Luke's renaming
    if INFRASTRUCTURE_CATALOG['robotics_lab']['name'] != 'Narog Foundry':
        return "robotics_lab.name should be 'Narog Foundry'"
    return True


@test("Reverse-unlocks index round-trips against level_requires (#1436)", tier=1, features=['config', 'narog'], mode='local')
def test_level_unlocks_reverse_index():
    """Bug #1436 reverse pointers — Habitat / Greenhouse / Research Station modals
    must surface 'Lv3 unlocks Narog Foundry Lv3' etc. The reverse-index helper is
    the data source for that UI; lock it against catalog drift in either direction.
    """
    from config_infrastructure import INFRASTRUCTURE_CATALOG
    from utilities.upgrades.catalog import get_infrastructure_level_unlocks_index

    # Force a fresh build so the test is independent of process state.
    import utilities.upgrades.catalog as _cat
    _cat._LEVEL_UNLOCKS_INDEX_CACHE = None
    index = get_infrastructure_level_unlocks_index()

    # Round-trip: every level_requires entry must appear in the reverse index.
    for target_key, target_cfg in INFRASTRUCTURE_CATALOG.items():
        for target_lvl, lvl_stats in (target_cfg.get('levels') or {}).items():
            for prereq_key, prereq_lvl in (lvl_stats.get('level_requires') or {}).items():
                hits = index.get(prereq_key, {}).get(int(prereq_lvl), [])
                if not any(h['key'] == target_key and h['level'] == int(target_lvl) for h in hits):
                    return f"{prereq_key} Lv{prereq_lvl} → {target_key} Lv{target_lvl} missing from reverse index"

    # And the inverse: every reverse-index entry must come from a real catalog requirement.
    for prereq_key, by_lvl in index.items():
        for prereq_lvl, hits in by_lvl.items():
            for h in hits:
                req = (INFRASTRUCTURE_CATALOG.get(h['key'], {}).get('levels', {}).get(h['level'], {}).get('level_requires') or {})
                if req.get(prereq_key) != prereq_lvl:
                    return f"Reverse-index hit {h} doesn't match catalog level_requires"

    # Spec spot-check: Habitat Module Lv3 + Lv9 unlock Narog Foundry; Greenhouse + RS Lv6/Lv9 also.
    hab_unlocks = {(h['key'], h['level']) for lvl in (3, 9) for h in index.get('habitat_module', {}).get(lvl, [])}
    if ('robotics_lab', 3) not in hab_unlocks or ('robotics_lab', 9) not in hab_unlocks:
        return f"Habitat Module reverse-unlocks drift: {hab_unlocks}"

    # Display name surfaces in payload (drives the "Narog Foundry Lv3" copy on the prereq modal).
    sample = next(iter(index['habitat_module'][3]))
    if sample.get('name') != 'Narog Foundry':
        return f"Reverse-index display name drift: {sample}"
    return True


@test("Chassis Reinforcement gives range, not speed (#1447)", tier=1, features=['config', 'tech'], mode='local')
def test_chassis_reinforcement_range_swap():
    """Bug #1447 (Luke 2026-05-06): Chassis swapped speed for range so Drone/Rover stay relevant.
    If a refactor reverts this, we want loud failure — speed is already on Suspension Eng + All-Terrain."""
    from config_tech import TECH_CATALOG
    chassis = TECH_CATALOG['vehicles']['techs']['chassis_reinforcement']
    effects = chassis.get('effects', {})
    if 'expedition_speed_mult' in effects:
        return f"chassis_reinforcement still grants expedition_speed_mult — should be vehicle_range_mult per #1447"
    if effects.get('vehicle_range_mult') != 1.20:
        return f"vehicle_range_mult should be 1.20, got {effects.get('vehicle_range_mult')}"
    if effects.get('cargo_capacity_mult') != 1.10:
        return f"cargo_capacity_mult should be 1.10 (kept), got {effects.get('cargo_capacity_mult')}"
    return True


@test("Tech catalog valid structure", tier=1, features=['config', 'tech'], mode='local')
def test_tech_structure():
    from config_tech import TECH_CATALOG
    for branch, cfg in TECH_CATALOG.items():
        if 'name' not in cfg:
            return f"{branch} missing name"
        if 'techs' not in cfg:
            return f"{branch} missing techs"
        # Should have 5 techs per branch
        if len(cfg['techs']) != 5:
            return f"{branch} has {len(cfg['techs'])} techs, expected 5"
    return True


@test("UI_ICONS defined", tier=1, features=['config'], mode='local')
def test_ui_icons():
    from config import UI_ICONS
    required = ['shard_gem', 'success_check', 'error_x']
    for icon in required:
        if icon not in UI_ICONS:
            return f"Missing icon: {icon}"
    assert len(UI_ICONS) >= 20, f"Expected 20+ icons, got {len(UI_ICONS)}"
    return True


@test("STAT_NAMES has 5 stats", tier=1, features=['config', 'crew'], mode='local')
def test_stat_names():
    from config import STAT_NAMES
    assert len(STAT_NAMES) == 5, f"Expected 5 stats, got {len(STAT_NAMES)}"
    return True


# =============================================================================
# TIER 2: DEFAULT TESTS
# =============================================================================

@test("expeditions table exists", tier=2, features=['db', 'expeditions'], mode='local')
def test_expeditions_table():
    from utilities.postgres.core import db_cursor
    with db_cursor() as cur:
        cur.execute("SELECT 1 FROM pilgrim.expeditions LIMIT 1")
    return True


@test("expeditions has signal_claim columns", tier=1, features=['db', 'expeditions', 'signal'], mode='local')
def test_expeditions_signal_claim_columns():
    """Phase 2.3b: required columns for two-step signal claim flow."""
    from utilities.postgres.expeditions import ensure_signal_claim_columns
    from utilities.postgres.core import db_cursor
    ensure_signal_claim_columns()
    with db_cursor() as cur:
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema='pilgrim' AND table_name='expeditions'
              AND column_name IN ('expedition_type','signal_site_id','cinematic_shown_at','cinematic_payload')
        """)
        present = {r['column_name'] for r in cur.fetchall()}
    missing = {'expedition_type', 'signal_site_id', 'cinematic_shown_at', 'cinematic_payload'} - present
    if missing:
        return f"Missing columns: {missing}"
    return True


@test("signal_claim launch validates site_id", tier=2, features=['expeditions', 'signal'], mode='local')
def test_signal_claim_requires_site_id():
    """Phase 2.3b: launch must reject signal_claim without signal_site_id."""
    from utilities.expeditions.lifecycle import launch_expedition
    result = launch_expedition(
        user_id=999999, destination_name='X', destination_type='OriginSite',
        destination_lat=0, destination_lon=0, distance_km=1,
        vehicle_type='rover', expedition_type='signal_claim', signal_site_id=None,
    )
    if result.get('success'):
        return "Should have rejected missing signal_site_id"
    return True


@test("signal_claim cinematic getters return shape", tier=2, features=['expeditions', 'signal'], mode='local')
def test_signal_cinematic_getter_shape():
    """Phase 2.3b: get_pending_signal_cinematic returns None for users with no pending claim."""
    from utilities.postgres.expeditions import get_pending_signal_cinematic, mark_signal_cinematic_shown, write_signal_cinematic_payload
    # Should not raise; returns None or row dict.
    result = get_pending_signal_cinematic(999999)
    if result is not None and 'id' not in result:
        return f"Unexpected shape: {result}"
    # mark and write helpers should be callable (no-op for nonexistent row)
    mark_signal_cinematic_shown(99999999, 999999)
    write_signal_cinematic_payload(99999999, {'test': True})
    return True


@test("user_trail_chains schema exists", tier=1, features=['db', 'trails'], mode='local')
def test_user_trail_chains_schema():
    """v3 (#1414): table + active_trail_direction column exist."""
    from utilities.postgres.trails.chains import ensure_user_trail_chains_table
    from utilities.postgres.core import db_cursor
    ensure_user_trail_chains_table()
    with db_cursor() as cur:
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='pilgrim' AND table_name='user_trail_chains'")
        cols = {r['column_name'] for r in cur.fetchall()}
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='pilgrim' AND table_name='users' AND column_name='active_trail_direction'")
        has_col = bool(cur.fetchone())
    required = {'user_id', 'direction', 'segment_index', 'from_landmark', 'to_landmark',
                'segment_distance_km', 'km_built', 'captain_km', 'scientist_km', 'aria_km',
                'drone_km', 'robot_km', 'completed_at'}
    missing = required - cols
    if missing:
        return f"missing columns: {missing}"
    if not has_col:
        return "missing pilgrim.users.active_trail_direction"
    return True


@test("antipode chain persisted for Andy", tier=2, features=['trails'], mode='local')
def test_andy_chain_persisted():
    """v3 (#1414): read Andy's persisted chains, validate totals against comment 607."""
    from utilities.postgres.core import db_cursor
    expected = {
        'S': (10488, 18), 'W': (10553, 17), 'E': (10804, 19), 'N': (11015, 18)
    }
    with db_cursor() as cur:
        cur.execute("""
            SELECT direction, COUNT(*) AS hops, SUM(segment_distance_km) AS total,
                   MAX(to_landmark) FILTER (WHERE segment_index = (
                     SELECT MAX(segment_index) FROM pilgrim.user_trail_chains x
                     WHERE x.user_id = 45 AND x.direction = pilgrim.user_trail_chains.direction
                   )) AS antipode
            FROM pilgrim.user_trail_chains WHERE user_id = 45
            GROUP BY direction
        """)
        rows = {r['direction']: r for r in cur.fetchall()}
    for d, (km_exp, hops_exp) in expected.items():
        r = rows.get(d)
        if not r:
            return f"{d} chain not persisted for Andy"
        total = float(r['total'])
        delta_pct = abs(total - km_exp) / km_exp * 100
        if delta_pct > 2.0:
            return f"{d} chain {total:.0f}km diverges {delta_pct:.1f}% from {km_exp}km"
        if abs(int(r['hops']) - hops_exp) > 1:
            return f"{d} chain {r['hops']} hops, expected {hops_exp}"
        if r['antipode'] != 'Da Vinci':
            return f"{d} chain ends at {r['antipode']}"
    return True


@test("get_active_chain_segments shape", tier=2, features=['trails'], mode='local')
def test_active_chain_segments_shape():
    from utilities.postgres.trails.chains import get_active_chain_segments
    result = get_active_chain_segments(45)
    for d in ('N', 'S', 'E', 'W'):
        if d not in result:
            return f"missing direction {d}"
    return True


@test("Bug #21: captain_stat_events schema exists with UNIQUE dedupe", tier=1, features=['captain_stats', 'db'], mode='local')
def test_captain_stat_events_schema():
    from utilities.postgres.captain_stats import ensure_captain_stat_events_table
    from utilities.postgres.core import db_cursor
    ensure_captain_stat_events_table()
    with db_cursor() as cur:
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='pilgrim' AND table_name='captain_stat_events'")
        cols = {r['column_name'] for r in cur.fetchall()}
        required = {'id', 'user_id', 'stat_name', 'delta', 'source_kind', 'source_table', 'source_id', 'created_at'}
        missing = required - cols
        if missing:
            return f"missing columns: {missing}"
        # UNIQUE constraint must exist or retro/triggers double-credit
        cur.execute("""
            SELECT conname FROM pg_constraint
            WHERE conrelid = 'pilgrim.captain_stat_events'::regclass AND contype='u'
        """)
        if not cur.fetchall():
            return "missing UNIQUE constraint (user_id, stat_name, source_kind, source_table, source_id) — dedupe broken"
    return True


@test("Bug #21: V2_MULTIPLIERS match Luke-locked formulas (2026-05-07 'V2 is fine')", tier=1, features=['captain_stats'], mode='local')
def test_v2_multipliers_locked():
    """If anyone changes these numbers without a new Luke directive on bug #21,
    this fails the deploy. Luke spent 3 weeks tuning V1 → V2; protect it."""
    from utilities.postgres.captain_stats import V2_MULTIPLIERS, WORLD_1_CAP, STAT_NAMES
    expected = {
        'leadership':  {'sol_tick': 0.1,   'crew_mission': 0.05},
        'strategy':    {'expedition': 0.2, 'legendary':    1.0},
        'exploration': {'km':        0.001, 'landmark':    1.0},
        'logistics':   {'trail_segment': 0.05, 'upgrade':  1.0},
        'charisma':    {'aria_bond': 2.0},
    }
    if V2_MULTIPLIERS != expected:
        return f"V2_MULTIPLIERS drifted from Luke-locked! got {V2_MULTIPLIERS}, expected {expected}"
    if WORLD_1_CAP != 75:
        return f"WORLD_1_CAP drifted from Luke spec (75): got {WORLD_1_CAP}"
    if set(STAT_NAMES) != {'leadership', 'strategy', 'exploration', 'logistics', 'charisma'}:
        return f"STAT_NAMES drift: {STAT_NAMES}"
    # Also pin the simulate script's FORMULAS_V2 — that's the retro math
    from tools.simulate_captain_stats import FORMULAS_V2
    sim_terms = {stat: dict(terms) for stat, terms in FORMULAS_V2.items()}
    # simulate uses activity keys: sols_survived, crew_missions, expeditions, km_traveled, legendaries, landmarks, trail_segments, depot_upgrades, aria_bonds
    sim_expected = {
        'leadership':  {'sols_survived': 0.1,  'crew_missions': 0.05},
        'strategy':    {'expeditions':   0.2,  'legendaries':   1.0},
        'exploration': {'km_traveled':   0.001, 'landmarks':    1.0},
        'logistics':   {'trail_segments': 0.05, 'depot_upgrades': 1.0},
        'charisma':    {'aria_bonds':    2.0},
    }
    if sim_terms != sim_expected:
        return f"simulate_captain_stats.FORMULAS_V2 drifted: got {sim_terms}, expected {sim_expected}"
    return True


@test("Bug #21: award_stat_event inserts + bumps + dedupes + caps", tier=2, features=['captain_stats'], mode='local')
@requires_web3
def test_award_stat_event_e2e():
    """End-to-end smoke: award produces correct old/new, second call dedupes,
    huge delta caps at 75. Uses sentinel source_table='smoke_test' + cleans up."""
    from utilities.postgres.captain_stats import award_stat_event, get_event_totals
    from utilities.postgres.core import db_cursor
    USER = 250  # Trusty bot — Luke OK'd bots capping
    SENTINEL = 'smoke_test'
    # Snapshot + clean
    with db_cursor() as cur:
        cur.execute("""
            SELECT commander_leadership, commander_strategy, commander_exploration,
                   commander_logistics, commander_charisma
            FROM pilgrim.replicate_assets
            WHERE user_id=%s AND asset_type='character_image' AND is_deleted=FALSE
            ORDER BY (commander_leadership IS NOT NULL) DESC, created_at DESC LIMIT 1
        """, (USER,))
        pre = dict(cur.fetchone())
    with db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM pilgrim.captain_stat_events WHERE user_id=%s AND source_table=%s", (USER, SENTINEL))
    try:
        r1 = award_stat_event(USER, 'leadership', 0.05, 'crew_mission', SENTINEL, 999001)
        if r1 is None or r1['delta'] != 0.05:
            return f"first award returned bad result: {r1}"
        r2 = award_stat_event(USER, 'leadership', 0.05, 'crew_mission', SENTINEL, 999001)
        if r2 is not None:
            return f"dedupe failed — second award returned {r2}"
        r3 = award_stat_event(USER, 'leadership', 9999, 'sol_tick', SENTINEL, 999002)
        if r3 is None or r3['new'] != 75 or not r3['capped']:
            return f"cap failed — got {r3}"
    finally:
        # Cleanup sentinel events; restore commander values
        with db_cursor(commit=True) as cur:
            cur.execute("DELETE FROM pilgrim.captain_stat_events WHERE user_id=%s AND source_table=%s", (USER, SENTINEL))
            cur.execute("""
                UPDATE pilgrim.replicate_assets
                SET commander_leadership=%s, commander_strategy=%s, commander_exploration=%s,
                    commander_logistics=%s, commander_charisma=%s
                WHERE user_id=%s AND asset_type='character_image' AND is_deleted=FALSE
            """, (pre['commander_leadership'], pre['commander_strategy'], pre['commander_exploration'],
                  pre['commander_logistics'], pre['commander_charisma'], USER))
    return True


@test("Bug #21: retro committed for all 16 captains with baselines + retro_credit", tier=2, features=['captain_stats'], mode='local')
def test_retro_landed():
    """Post-Deploy B: every captain with stats should have baseline + retro_credit
    events for all 5 stats. If this fails post-deploy, retro didn't run."""
    from utilities.postgres.core import db_cursor
    with db_cursor() as cur:
        cur.execute("""
            SELECT user_id,
                   SUM(CASE WHEN source_kind='baseline' THEN 1 ELSE 0 END) AS baselines,
                   SUM(CASE WHEN source_kind='retro_credit' THEN 1 ELSE 0 END) AS retros
            FROM pilgrim.captain_stat_events
            GROUP BY user_id
        """)
        rows = list(cur.fetchall())
    if len(rows) < 1:
        return "no retro events found — Deploy B retro didn't commit"
    # Every captain should have exactly 5 baselines (one per stat) and >=1 retro_credit
    bad = [r for r in rows if r['baselines'] != 5]
    if bad:
        return f"{len(bad)} captain(s) missing baselines (got != 5): {[r['user_id'] for r in bad[:5]]}"
    # go_live_at must be set so live triggers (Deploy C) know the cutoff
    from utilities.postgres.captain_stats import get_go_live_at
    if get_go_live_at() is None:
        return "go_live_at not set — Deploy C triggers would fire on retro-already-counted activity"
    return True


@test("Bug #21 Deploy C: every trigger source_kind has a V2_MULTIPLIERS entry", tier=1, features=['captain_stats'], mode='local')
def test_trigger_source_kinds_match_v2():
    """If a trigger writes a source_kind that V2_MULTIPLIERS doesn't know about,
    it won't show up in dry-run sims, won't be retro-credited correctly, and
    will look like a phantom event. This pins the trigger sites to V2."""
    from utilities.postgres.captain_stats import V2_MULTIPLIERS, SOURCE_KIND_TO_STAT
    # Every source_kind we award from a trigger must map to exactly one stat
    # AND that stat's V2 terms must include this source_kind.
    for kind, stat in SOURCE_KIND_TO_STAT.items():
        if stat not in V2_MULTIPLIERS:
            return f"SOURCE_KIND_TO_STAT[{kind!r}] = {stat!r} but stat not in V2_MULTIPLIERS"
        if kind not in V2_MULTIPLIERS[stat]:
            return f"trigger {kind!r} would write events that V2_MULTIPLIERS[{stat!r}] doesn't know about"
    # Inverse: every term in V2_MULTIPLIERS should be a trigger
    for stat, terms in V2_MULTIPLIERS.items():
        for kind in terms:
            if SOURCE_KIND_TO_STAT.get(kind) != stat:
                return f"V2_MULTIPLIERS[{stat!r}][{kind!r}] has no matching SOURCE_KIND_TO_STAT entry"
    return True


@test("Bug #21 Deploy C: record_landmark_discovery returns (id, is_new) tuple", tier=1, features=['expeditions'], mode='local')
def test_record_landmark_signature():
    """Bug #21 relies on the new (id, is_new) return shape. Pre-change it
    returned True/False — any caller that does `if record_landmark_discovery(...)`
    still works either way, but the trigger code at lifecycle.py needs the tuple
    unpack. This smoke catches a future re-revert."""
    import inspect
    from utilities.postgres.expeditions import record_landmark_discovery
    src = inspect.getsource(record_landmark_discovery)
    if "RETURNING id, (xmax = 0) AS is_new" not in src:
        return "record_landmark_discovery no longer RETURNING (id, is_new) — Bug #21 lifecycle trigger will break"
    return True


@test("Bug #1452 Tier A: codemap always in Phase 1 + Phase 2 (no bug_mode gate)", tier=1, features=['pilgrimbot'], mode='local')
def test_codemap_always_loaded():
    """Bug #1452: Phase 1 was lying — codemap was only loaded when bug_mode=True.
    Now it's always appended to phase1_system AND deep_system. This pins the
    behavior so a future revert can't quietly re-introduce the hallucination."""
    import inspect
    from utilities.pilgrimbot import streaming
    src = inspect.getsource(streaming)
    if "codemap_manifest_block" not in src:
        return "Phase 1 codemap manifest var missing — Bug #1452 Tier A regression"
    # The Phase 2 unconditional append: codemap loaded outside the `if bug_mode:` block
    if "if bug_mode:\n            deep_tools.append(READ_FILE_TOOL)\n            codemap = load_codemap()" in src:
        return "Phase 2 still gates codemap load on bug_mode — Bug #1452 Tier A regression"
    from utilities.pilgrimbot_context import load_codemap
    cm = load_codemap()
    if not cm or len(cm) < 100:
        return f"codemap.json failed to load or too small (got {len(cm)} entries)"
    return True


@test("Bug #21 Deploy D: XP grants removed from complete_crew_mission", tier=1, features=['captain_stats'], mode='local')
def test_xp_grants_deprecated():
    """Luke 2026-05-09 #2: 'Ok to deprecate extra experience'. The +5 XP grant
    per crew mission MUST be gone — folded into the +0.05 Leadership stat
    event (Deploy C). If anyone re-adds the SET captain_logistics_xp = ...
    UPDATE in complete_crew_mission, this fails the deploy."""
    import inspect
    from utilities.postgres.trails.crew import complete_crew_mission
    src = inspect.getsource(complete_crew_mission)
    if "captain_logistics_xp = %s" in src or "scientist_navigation_xp = %s" in src:
        return "complete_crew_mission still writes XP columns — Deploy D regression"
    # Captain + scientist branches: xp_gain must be 0 (folded into stat events).
    # ARIA branch still has xp_gain=5 but writes to aria_skills (separate system
    # Luke explicitly preserved §4 "ARIA stats grow"). Check the captain/sci
    # write paths specifically:
    cap_block = src[src.find("if crew_member == 'captain'"):src.find("elif crew_member == 'scientist'")]
    sci_block = src[src.find("elif crew_member == 'scientist'"):src.find("elif crew_member == 'aria'")]
    if "xp_gain = 5" in cap_block:
        return "captain branch still grants +5 XP — Deploy D regression"
    if "xp_gain = 5" in sci_block:
        return "scientist branch still grants +5 XP — Deploy D regression"
    return True


@test("Bug #21 Deploy C: sol-tick cron route exists", tier=1, features=['captain_stats'], mode='local')
@requires_flask
def test_sol_tick_route():
    from app import app
    with app.test_request_context():
        rules = [r for r in app.url_map.iter_rules() if r.rule == '/api/cron/sol_tick_captain_stats']
        if not rules:
            return "missing /api/cron/sol_tick_captain_stats route"
    return True


@test("Bug #1454: per-vehicle speed chips match lifecycle launch math", tier=2, features=['expeditions'], mode='local')
@requires_web3
def test_vehicle_speed_chips_match_launch():
    """The Active Bonuses Speed chip used to show max(all vehicles) × tech, but
    each launch uses THIS vehicle × tech (lifecycle.py:190-195). Luke picked
    Option A on 2026-05-10: render one chip per owned vehicle whose value
    matches the exact number the captain experiences on launch."""
    from utilities.expeditions.page_data import get_expeditions_page_data
    from utilities.upgrades.vehicles import get_user_owned_vehicles
    from utilities.tech_utils import get_tech_effects
    USER = 45  # Andy — has multiple vehicles
    data = get_expeditions_page_data(USER)
    chips = (data.get('expedition_bonuses') or {}).get('vehicle_speed_chips')
    assert isinstance(chips, list), f"vehicle_speed_chips missing/not list: {type(chips)}"
    owned = get_user_owned_vehicles(USER)
    assert len(chips) == len(owned), f"chip count {len(chips)} != owned {len(owned)}"
    tech_mult = get_tech_effects(USER).get('expedition_speed_mult', 1.0)
    owned_by_type = {v['vehicle_type']: v for v in owned}
    for chip in chips:
        vtype = chip['vehicle_type']
        v = owned_by_type[vtype]
        expected = float(v['speed_mult']) * float(tech_mult)
        got = float(chip['value_mult'])
        if abs(got - expected) > 1e-6:
            return f"{vtype} chip={got} != lifecycle launch={expected} (vehicle={v['speed_mult']} × tech={tech_mult})"
    return True


@test("chain speed mult for off-chain dest is 1.0", tier=2, features=['trails', 'expeditions'], mode='local')
def test_off_chain_speed_mult():
    from utilities.postgres.trails.chains import get_chain_speed_mult_for_destination
    mult = get_chain_speed_mult_for_destination(45, '__definitely_not_a_landmark__')
    if mult != 1.0:
        return f"off-chain mult should be 1.0, got {mult}"
    return True


@test("Maintenance Drone L1-L3 has build_time_mult", tier=1, features=['config', 'depot'], mode='local')
def test_maintenance_drone_build_time_mult():
    """Phase 4b (#1270 section 4 point 3): Maintenance Drone passive build-speed bonus."""
    from config_upgrades import UPGRADE_CATALOG
    levels = UPGRADE_CATALOG.get('maintenance', {}).get('maintenance', {}).get('levels', {})
    expected = {1: 0.98, 2: 0.95, 3: 0.92}
    for lv, want in expected.items():
        got = levels.get(lv, {}).get('build_time_mult')
        if got != want:
            return f"L{lv} build_time_mult expected {want}, got {got}"
    return True


@test("puzzle_fragments tables seeded", tier=1, features=['db', 'signal'], mode='local')
def test_puzzle_fragments_seeded():
    """Phase 2.3c: catalog has 14 fragments seeded."""
    from utilities.signal.puzzle_fragments import ensure_puzzle_fragment_tables
    from utilities.postgres.core import db_cursor
    ensure_puzzle_fragment_tables()
    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM pilgrim.puzzle_fragments")
        n = cur.fetchone()['n']
    if n < 14:
        return f"Expected 14 fragments, got {n}"
    return True


@test("get_user_fragments returns shape", tier=2, features=['signal'], mode='local')
def test_get_user_fragments_shape():
    from utilities.signal.puzzle_fragments import get_user_fragments
    result = get_user_fragments(999999)
    for k in ('collected', 'locked', 'total', 'collected_count'):
        if k not in result:
            return f"missing key: {k}"
    if result['total'] != 14:
        return f"expected total=14, got {result['total']}"
    if result['collected_count'] != 0:
        return f"new user should have 0 collected, got {result['collected_count']}"
    return True


@test("recall blocks signal_claim", tier=2, features=['expeditions', 'signal'], mode='local')
def test_recall_blocks_signal_claim():
    """Phase 2.3b: recall_expedition refuses signal_claim type — they can't fail."""
    # Synthesize a fake expedition by inserting + immediately checking the recall guard.
    # Simpler: just verify the guard string appears in source.
    import inspect
    from utilities.expeditions.lifecycle import recall_expedition
    src = inspect.getsource(recall_expedition)
    if 'signal_claim' not in src or 'cannot be recalled' not in src.lower():
        return "recall_expedition missing signal_claim guard"
    return True


@test("expedition_discoveries table exists", tier=2, features=['db', 'expeditions'], mode='local')
def test_discoveries_table():
    from utilities.postgres.core import db_cursor
    with db_cursor() as cur:
        cur.execute("SELECT 1 FROM pilgrim.expedition_discoveries LIMIT 1")
    return True


@test("replicate_assets table exists", tier=2, features=['db', 'crew'], mode='local')
def test_replicate_assets_table():
    from utilities.postgres.core import db_cursor
    with db_cursor() as cur:
        cur.execute("SELECT 1 FROM pilgrim.replicate_assets LIMIT 1")
    return True


@test("sepolia_assets table exists", tier=2, features=['db', 'blockchain'], mode='local')
def test_wallets_table():
    from utilities.postgres.core import db_cursor
    with db_cursor() as cur:
        cur.execute("SELECT 1 FROM pilgrim.sepolia_assets LIMIT 1")
    return True


@test("depot_transactions table exists", tier=2, features=['db', 'depot'], mode='local')
def test_depot_tx_table():
    from utilities.postgres.core import db_cursor
    with db_cursor() as cur:
        cur.execute("SELECT 1 FROM pilgrim.depot_transactions LIMIT 1")
    return True


@test("mars_mission_messages table exists", tier=2, features=['db', 'signal'], mode='local')
def test_mars_messages_table():
    from utilities.postgres.core import db_cursor
    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM pilgrim.mars_mission_messages")
        row = cur.fetchone()
        count = row['count'] if isinstance(row, dict) else row[0]
        assert count > 100, f"Expected 200+ messages, got {count}"
    return True


@test("aria_bonds table exists", tier=2, features=['db', 'signal'], mode='local')
def test_aria_bonds_table():
    from utilities.postgres.core import db_cursor
    with db_cursor() as cur:
        cur.execute("SELECT 1 FROM pilgrim.aria_bonds LIMIT 1")
    return True


@test("point_to_path_distance correctness", tier=1, features=['math', 'signal'], mode='local')
def test_point_to_path_distance():
    """Phase 2.1: closest-approach math for path-based Signal detection."""
    from utilities.mars_math import point_to_path_distance, haversine_distance

    # 1. Point exactly on the path should be near zero.
    d_on = point_to_path_distance(0.0, 5.0, 0.0, 0.0, 0.0, 10.0)
    assert d_on < 1.0, f"On-path distance should be ~0, got {d_on}"

    # 2. Point perpendicular to the midpoint: path-distance < endpoint-distance.
    d_perp = point_to_path_distance(1.0, 5.0, 0.0, 0.0, 0.0, 10.0)
    d_end = min(haversine_distance(1.0, 5.0, 0.0, 0.0), haversine_distance(1.0, 5.0, 0.0, 10.0))
    assert d_perp < d_end, f"Perp distance {d_perp} should be < endpoint distance {d_end}"

    # 3. Point past the endpoint clamps to the endpoint distance.
    d_past = point_to_path_distance(0.0, 20.0, 0.0, 0.0, 0.0, 10.0)
    d_clamp = haversine_distance(0.0, 20.0, 0.0, 10.0)
    assert abs(d_past - d_clamp) < 1.0, f"Past-endpoint should clamp: {d_past} vs {d_clamp}"
    return True


@test("get_user_signal_income_bonuses structure", tier=2, features=['signal', 'income'], mode='local')
def test_signal_income_bonuses():
    """Phase 2.2: helper returns the shape the colony page + pilgrimbot expect."""
    from utilities.signal.rewards import get_user_signal_income_bonuses
    from utilities.signal.config import VISITOR_TIER_INCOME_BONUSES

    # Founder tier must exist alongside the visitor tiers.
    for tier in ('Founder', 'Early Witness', 'Pioneer', 'Pilgrim', 'Wanderer'):
        assert tier in VISITOR_TIER_INCOME_BONUSES, f"missing tier: {tier}"
        bonus = VISITOR_TIER_INCOME_BONUSES[tier]
        assert bonus['shards_per_hour'] >= 0
        assert bonus['sv_per_hour'] >= 0

    # Pick a real user; result shape must match what colony.html consumes.
    from utilities.postgres.core import db_cursor
    with db_cursor() as cur:
        cur.execute("SELECT id FROM pilgrim.users ORDER BY id LIMIT 1")
        row = cur.fetchone()
    if not row:
        return True  # empty DB — helper not exercised
    result = get_user_signal_income_bonuses(row['id'])
    for key in ('shards_per_hour', 'sv_per_hour', 'sites_count', 'per_tier'):
        assert key in result, f"missing key: {key}"
    assert isinstance(result['per_tier'], dict)
    return True


@test("ARIA signal hints table + helper", tier=2, features=['aria', 'signal'], mode='local')
def test_aria_signal_hints():
    """Phase 2.3a: ensure_hint_log_table + SIGNAL_HINTS + get_next_unshown_hint shape."""
    from utilities.aria.signal_hints import (
        ensure_hint_log_table, SIGNAL_HINTS, get_next_unshown_hint
    )
    from utilities.postgres.core import db_cursor

    ensure_hint_log_table()

    assert isinstance(SIGNAL_HINTS, list) and len(SIGNAL_HINTS) >= 4
    for h in SIGNAL_HINTS:
        for key in ('id', 'trigger', 'threshold', 'text'):
            assert key in h, f"hint missing key: {key}"
        assert h['trigger'] in ('sol', 'expeditions', 'claims', 'detections_any')

    with db_cursor() as cur:
        cur.execute("""
            SELECT 1 FROM information_schema.tables
            WHERE table_schema='pilgrim' AND table_name='aria_hint_log'
        """)
        assert cur.fetchone() is not None, "aria_hint_log table not created"

        cur.execute("SELECT id FROM pilgrim.users LIMIT 1")
        row = cur.fetchone()
    if row:
        result = get_next_unshown_hint(row['id'])
        assert result is None or ('id' in result and 'text' in result)
    return True


@test("origin_sites.unlock_radius_km column", tier=2, features=['db', 'signal'], mode='local')
def test_origin_sites_radius_column():
    """Phase 2.1: per-site variable radii column must exist and be populated."""
    from utilities.postgres.core import db_cursor
    with db_cursor() as cur:
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema='pilgrim' AND table_name='origin_sites'
              AND column_name='unlock_radius_km'
        """)
        assert cur.fetchone() is not None, "unlock_radius_km column missing"
        cur.execute("SELECT COUNT(*) FROM pilgrim.origin_sites WHERE unlock_radius_km IS NOT NULL")
        row = cur.fetchone()
        count = row['count'] if isinstance(row, dict) else row[0]
        assert count > 0, "No origin sites have unlock_radius_km populated"
    return True


@test("trail_segments table exists", tier=2, features=['db', 'expeditions'], mode='local')
def test_trails_table():
    from utilities.postgres.core import db_cursor
    with db_cursor() as cur:
        cur.execute("SELECT 1 FROM pilgrim.trail_segments LIMIT 1")
    return True


@test("Pricing formula 1.12x validation", tier=2, features=['config', 'depot'], mode='local')
def test_pricing_formula():
    from config_upgrades import UPGRADE_CATALOG
    rover = UPGRADE_CATALOG.get('vehicles', {}).get('rover', {})
    levels = rover.get('levels', {})
    if 1 not in levels or 2 not in levels:
        return "Rover missing levels 1 or 2"
    cost1 = levels[1].get('cost', 0)
    cost2 = levels[2].get('cost', 0)
    if cost1 > 0:
        expected = round(cost1 * 1.12)
        tolerance = expected * 0.05
        if abs(cost2 - expected) > tolerance:
            return f"Lv2 cost {cost2} not ~1.12x of Lv1 {cost1}"
    return True


@test("Build time cap (14 days max)", tier=2, features=['config', 'depot'], mode='local')
def test_build_time_cap():
    from config_upgrades import UPGRADE_CATALOG
    violations = []
    for cat, items in UPGRADE_CATALOG.items():
        for key, cfg in items.items():
            for lv, stats in cfg.get('levels', {}).items():
                days = stats.get('build_time_days', 0)
                if days > 14:
                    violations.append(f"{cat}/{key}/Lv{lv}")
    if violations:
        return f"Build time >14 days: {violations[:3]}"
    return True


@test("FluxGenerator importable", tier=2, features=['crew'], mode='local')
def test_flux_import():
    try:
        from utilities.replicate_utils import FluxGenerator
        return True
    except ImportError as e:
        return f"FluxGenerator import failed: {e}"


@test("MarsAsteroidMiner importable", tier=2, features=['blockchain'], mode='local')
@requires_web3
def test_miner_import():
    from utilities.sepolia_utils import MarsAsteroidMiner
    return True


# =============================================================================
# TIER 3: FULL TESTS
# =============================================================================

@test("All 11 upgrade paths have 10 levels", tier=3, features=['config', 'depot'], mode='local')
def test_all_upgrade_levels():
    from config_upgrades import UPGRADE_CATALOG
    errors = []
    for cat, items in UPGRADE_CATALOG.items():
        for key, cfg in items.items():
            levels = cfg.get('levels', {})
            max_lv = cfg.get('max_level', 10)
            for lv in range(1, max_lv + 1):
                if lv not in levels:
                    errors.append(f"{cat}/{key} missing Lv{lv}")
    if errors:
        return f"Missing levels: {errors[:5]}"
    return True


@test("All 13 buildings have 10 levels", tier=3, features=['config', 'colony'], mode='local')
def test_all_infra_levels():
    from config_infrastructure import INFRASTRUCTURE_CATALOG
    errors = []
    for bldg, cfg in INFRASTRUCTURE_CATALOG.items():
        levels = cfg.get('levels', {})
        for lv in range(1, 11):
            if lv not in levels:
                errors.append(f"{bldg} missing Lv{lv}")
    if errors:
        return f"Missing levels: {errors[:5]}"
    return True


@test("All 4 tech branches have 5 techs and max_branch_level 10", tier=3, features=['config', 'tech'], mode='local')
def test_all_tech_levels():
    from config_tech import TECH_CATALOG
    errors = []
    for branch, cfg in TECH_CATALOG.items():
        techs = cfg.get('techs', {})
        if len(techs) != 5:
            errors.append(f"{branch} has {len(techs)} techs, expected 5")
        if cfg.get('max_branch_level') != 10:
            errors.append(f"{branch} max_branch_level is {cfg.get('max_branch_level')}, expected 10")
    if errors:
        return f"Errors: {errors[:5]}"
    return True


@test("Trail summary counts drone + robot km (#1303)", tier=1, features=['crew', 'trails'], mode='local')
def test_trail_summary_includes_drone_and_robot():
    """Bug #1303 (Luke 2026-05-06): the 3 visible crew cards always summed to
    100% because updateCrewTrailContributions() in crew-map.js was only
    adding captain+scientist+aria — drone_km + robot_km from
    pilgrim.user_trail_chains were dropped on the floor, so both the per-crew
    percentages AND the 'Your Total Trail Progress' km value were wrong.

    Pin three things so the bug can't silently regress:
      1. The view layer exposes `has_drone` to the trails tab so the Drone
         card can be conditionally rendered.
      2. The crew-map.js source counts every per-source km column when
         computing the grand total.
      3. The trails-tab template renders both the drone and narog contrib
         hooks (#drone-trail-contrib / #robot-trail-contrib) under the right
         template gates."""
    import inspect
    from utilities.views import arrival as arrival_mod

    src = inspect.getsource(arrival_mod.get_crew_page_data_authenticated)
    assert "has_drone" in src, "get_crew_page_data_authenticated must expose has_drone for the Drone card gate"

    js_path = '/Users/at/Desktop/code/galactica/static/js/crew-map.js'
    with open(js_path) as f:
        js = f.read()
    for k in ('captain_km', 'scientist_km', 'aria_km', 'drone_km', 'robot_km'):
        assert k in js, f"crew-map.js must read t.{k} when summing crew contributions"
    # The grand-total expression must include drone + robot terms — the
    # original bug was the literal omission, so guard against it directly.
    assert 'droneTotal' in js and 'robotTotal' in js, (
        "crew-map.js grandTotal must include droneTotal + robotTotal — "
        "Luke's bug #1303 was caused by these being missing"
    )

    tpl_path = '/Users/at/Desktop/code/galactica/templates/crew/_tab_trails.html'
    with open(tpl_path) as f:
        tpl = f.read()
    for hook in ('drone-trail-contrib', 'robot-trail-contrib'):
        assert hook in tpl, f"_tab_trails.html must render #{hook} for crew-map.js to populate"
    assert 'has_drone' in tpl, "_tab_trails.html must gate the Drone card on has_drone"
    assert 'robot_data.is_complete' in tpl, "_tab_trails.html must gate the Narog card on robot_data.is_complete"
    return True


@test("Lab Research Summary lifetime totals (#1424)", tier=1, features=['tech'], mode='local')
def test_research_summary_lifetime_totals():
    """Bug #1424: header must show '/200' lifetime cap (10 levels × 5 techs ×
    4 branches in W1) instead of the old '/20' per-current-tier count, and
    every branch must expose lifetime_completed / lifetime_total so the
    template can render Luke's per-branch 'Exploration X/50 · ...' breakdown.
    Andy (user 45) is canonical so we validate the live shape on his row."""
    from utilities.tech_utils import get_tech_summary
    s = get_tech_summary(45)
    for k in ('lifetime_completed', 'lifetime_total'):
        assert k in s, f"tech_summary missing top-level '{k}' — header would render blank"
    # W1 shape: 4 branches × 5 techs × 10 max levels = 200.
    assert s['lifetime_total'] == 200, f"lifetime_total should be 200 in W1, got {s['lifetime_total']}"
    # lifetime_completed counts every (tech_key, branch_level) row, must be ≥ distinct count.
    assert s['lifetime_completed'] >= s['total_completed'], (
        f"lifetime_completed ({s['lifetime_completed']}) should be ≥ distinct total_completed "
        f"({s['total_completed']}) — every distinct tech has at least one row"
    )
    # Per-branch shape — what the new branch-count chips read.
    for b in s['branches']:
        for k in ('lifetime_completed', 'lifetime_total'):
            assert k in b, f"branch '{b.get('branch_key')}' missing '{k}'"
        assert b['lifetime_total'] == 50, (
            f"branch {b['branch_key']} lifetime_total should be 50 in W1, got {b['lifetime_total']}"
        )
    # Sums must reconcile.
    assert sum(b['lifetime_completed'] for b in s['branches']) == s['lifetime_completed']
    assert sum(b['lifetime_total'] for b in s['branches']) == s['lifetime_total']
    return True


@test("Infrastructure prerequisites valid", tier=3, features=['config', 'colony'], mode='local')
def test_infra_prerequisites():
    from config_infrastructure import INFRASTRUCTURE_CATALOG
    all_buildings = set(INFRASTRUCTURE_CATALOG.keys())
    errors = []
    for bldg, cfg in INFRASTRUCTURE_CATALOG.items():
        prereqs = cfg.get('prerequisites', {})
        for prereq_bldg in prereqs.keys():
            if prereq_bldg not in all_buildings:
                errors.append(f"{bldg} requires unknown {prereq_bldg}")
    if errors:
        return f"Invalid prereqs: {errors[:3]}"
    return True


@test("haversine_distance returns positive", tier=3, features=['expeditions'], mode='local')
def test_haversine():
    from utilities.mars_math import haversine_distance
    dist = haversine_distance(18.65, -133.8, 18.4, 77.7)
    assert dist > 0, f"Distance should be positive, got {dist}"
    assert dist < 10000, f"Distance unreasonably large: {dist}"
    return True


@test("page-data db-call budgets (N+1 guard)", tier=2, features=['api', 'db'], mode='local')
def test_page_data_db_budgets():
    """Bug #1431 (perf): every page-data fn has a per-load DB-call budget. Going
    over means somebody added an N+1. Adjust the budget DOWN as you bulk-fetch;
    only adjust UP with explicit justification.

    Calibrated against Andy (user 45). Cushion is ~1-3 over post-fix baseline so a
    single-query addition won't fail the smoke, but a real N+1 (5+ extra) will."""
    from utilities.postgres.core import reset_db_counter, get_db_counter
    from utilities.admin.speed_testing import _StubAuth
    from utilities.page_data_utils import (
        get_dashboard_page_data, get_command_page_data,
        get_colony_page_data, get_depot_page_data,
    )
    from utilities.expeditions.page_data import get_expeditions_page_data
    from utilities.tech_utils import get_research_page_data
    from utilities.admin_utils import get_admin_dashboard_data
    from utilities.signal_utils import get_signal_page_render_data

    user_id = 45
    auth = _StubAuth(user_id)

    # Push a Flask request context so page-data fns that read flask.g/session don't blow up.
    ctx = None
    try:
        from flask import has_request_context, session, g
        if not has_request_context():
            from app import app as _app
            ctx = _app.test_request_context('/')
            ctx.push()
            session['user'] = auth.get_current_user()
            session['user_id'] = user_id
            g.user_id = user_id
    except Exception:
        ctx = None

    cases = [
        ('Home /',         52, lambda: get_dashboard_page_data(user_id, auth)),
        ('Expeditions',    40, lambda: get_expeditions_page_data(user_id)),
        ('Crew /crew',     25, lambda: get_command_page_data(user_id)),
        ('Depot /depot',   25, lambda: get_depot_page_data(user_id, auth)),
        ('Colony /colony', 25, lambda: get_colony_page_data(user_id, auth)),
        ('Signal /signal', 20, lambda: get_signal_page_render_data(user_id)),
        ('Research',       18, lambda: get_research_page_data(user_id)),
        ('Admin /admin',   15, lambda: get_admin_dashboard_data(user_id)),
    ]

    breaches = []
    try:
        for label, budget, fn in cases:
            reset_db_counter()
            try:
                fn()
            except Exception as e:
                breaches.append(f"{label}: errored ({type(e).__name__}: {str(e)[:60]})")
                continue
            db_calls = get_db_counter()
            if db_calls > budget:
                breaches.append(f"{label}: db:{db_calls} > budget {budget}")
    finally:
        if ctx is not None:
            try:
                ctx.pop()
            except Exception:
                pass

    if breaches:
        return "Budget exceeded — " + "; ".join(breaches) + ". Fix the N+1 or raise the budget here with a justification comment."
    return True


@test("Narog: pilgrim.robot.build_error column exists", tier=1, features=['db', 'crew'], mode='local')
def test_narog_build_error_column():
    """The build_error column was added so failed Flux forges don't silently
    drop a placeholder narog. ensure_robot_tables() should idempotently add it."""
    from utilities.postgres.robot import ensure_robot_tables
    from utilities.postgres.core import db_cursor
    ensure_robot_tables()
    with db_cursor() as cur:
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema='pilgrim' AND table_name='robot' AND column_name='build_error'
        """)
        row = cur.fetchone()
        assert row, "pilgrim.robot.build_error column missing — did the migration in ensure_robot_tables run?"
    return True


@test("Narog reforge SV gate uses _get_available_sv (#1438)", tier=1, features=['db', 'crew'], mode='local')
def test_narog_reforge_uses_available_sv():
    """Bug #1438: status bar showed 71,792 SV but reforge said 'Need 5 science,
    you have 0' because charge_reforge_action read the legacy
    users.research_points column (always 0) instead of _get_available_sv —
    same source the status bar uses. Lock both pieces in:
      1. pilgrim.robot.reforge_sv_spent column exists (the new spend bucket).
      2. charge_reforge_action source references _get_available_sv.
      3. _get_available_sv source subtracts reforge_sv_spent.
    """
    import inspect
    from utilities.postgres.robot import ensure_robot_tables, charge_reforge_action
    from utilities.postgres.core import db_cursor
    from utilities import tech_utils
    ensure_robot_tables()
    with db_cursor() as cur:
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema='pilgrim' AND table_name='robot' AND column_name='reforge_sv_spent'
        """)
        assert cur.fetchone(), "pilgrim.robot.reforge_sv_spent column missing — migration didn't run"
    src = inspect.getsource(charge_reforge_action)
    assert "_get_available_sv" in src, "charge_reforge_action must use _get_available_sv (status bar source), not legacy research_points"
    assert "spend_research_points_for_tech" not in src, "spend_research_points_for_tech is the legacy bug — remove it from charge_reforge_action"
    avail_src = inspect.getsource(tech_utils._get_available_sv)
    assert "reforge_sv_spent" in avail_src, "_get_available_sv must subtract reforge_sv_spent so status bar reflects narog spend"
    return True


@test("Narog: prereq cards match Luke's spec (Lab L1 only)", tier=1, features=['crew'], mode='local')
def test_narog_prereqs_lab_only():
    """The UI used to over-promise RS L3 + RF L3 alongside Lab L1. The server
    gate only enforces Lab L1 (matches Luke's brainstorm robot-crew §2). The
    UI was fixed to match the gate. Smoke-check the source list directly."""
    import inspect
    from utilities.postgres import robot as robot_mod
    src = inspect.getsource(robot_mod.get_robot_page_data)
    # Should reference robotics_lab; should NOT reference research_station/regolith_forge
    # in the prereq_defs list.
    assert "'robotics_lab'" in src, "robotics_lab missing from prereq_defs"
    # Find the prereq_defs literal
    pre_idx = src.find("prereq_defs = [")
    end_idx = src.find("]", pre_idx)
    block = src[pre_idx:end_idx]
    assert "research_station" not in block, "research_station still in prereq_defs (UI over-promise)"
    assert "regolith_forge" not in block, "regolith_forge still in prereq_defs (UI over-promise)"
    return True


@test("Narog: _load_claimed_inventory excludes consumed items", tier=1, features=['db', 'crew'], mode='local')
def test_narog_inventory_excludes_consumed():
    """Once a discovery is consumed (analyzed=true) it must leave the narog
    source pool, otherwise a captain could re-roll the same legendary forever."""
    import inspect
    from utilities.postgres import robot as robot_mod
    src = inspect.getsource(robot_mod._load_claimed_inventory)
    assert "analyzed = FALSE" in src or "analyzed=FALSE" in src or "analyzed = false" in src.lower(), \
        "_load_claimed_inventory must filter out analyzed=true items"
    return True


@test("Narog: real Sepolia broadcast helpers exist", tier=2, features=['crew', 'blockchain'], mode='local')
def test_narog_sepolia_helpers():
    """Stage tx writes must go through the real Sepolia broadcast path, not
    fabricated 0xpending/0xforge strings."""
    from utilities.postgres.robot import (
        broadcast_stage_async, _send_narog_stage_transaction,
        _build_narog_stage_message,
    )
    msg = _build_narog_stage_message(45, 3, {
        'item_name': 'Quantum Crystal',
        'landmark_name': 'Aethiopis',
        'lat': 1.234, 'lon': 5.678,
    })
    assert 'NAROG_STAGE_3' in msg
    assert 'Quantum Crystal' in msg
    assert 'Aethiopis' in msg
    return True


@test("Narog: get_robot_page_data executes without raising for Andy", tier=1, features=['crew', 'db'], mode='local')
def test_narog_get_robot_page_data_runs():
    """Catches the SQL syntax + datetime UnboundLocalError class of bugs by
    actually exercising the function end-to-end against Andy's live row.
    Before this test was added, the prereq_defs trim broke 'IN (\\'x\\',)' SQL
    and the local datetime import shadowed the module-level one — both
    silently passed source-inspection tests but blew up at runtime."""
    from utilities.postgres.robot import get_robot_page_data
    data = get_robot_page_data(45)
    assert 'lab_unlocked' in data, "missing lab_unlocked key"
    assert 'prereqs' in data, "missing prereqs key"
    assert isinstance(data['prereqs'], list), "prereqs must be a list"
    return True


@test("Narog: dry-run gate skips Sepolia broadcast for dev users", tier=1, features=['crew', 'blockchain'], mode='local')
def test_narog_dry_run_gate():
    """Andy (45) is in NAROG_DRY_RUN_USER_IDS by default so dev rehearsal forges
    skip the on-chain broadcast. Luke (112) MUST NOT be in this set — his first
    forge IS the canonical on-chain one. This is the hard guard against
    polluting the ARG breadcrumb trail with dev-test transactions."""
    from utilities.admin_utils import (
        is_narog_dry_run, NAROG_DRY_RUN_USER_IDS,
        is_app_dev, APP_DEV_USER_IDS,
    )
    # Production invariant: NO ONE should be in dry-run by default. This set
    # is meant for explicit, deliberate dev rehearsal only — Andy was in it
    # until 2026-04-30, then went live for his canonical on-chain forge. If
    # this assertion fires, someone left a captain in rehearsal mode and
    # their forge will quietly produce a Narog with no on-chain tx.
    assert NAROG_DRY_RUN_USER_IDS == set(), \
        f"NAROG_DRY_RUN_USER_IDS must be empty in production, got {NAROG_DRY_RUN_USER_IDS}"
    assert not is_narog_dry_run(45), "Andy (45) MUST NOT be in dry-run — canonical forge fired 2026-04-30"
    assert not is_narog_dry_run(112), "Luke (user 112) MUST NOT be in dry-run — his first forge is canonical"
    assert not is_narog_dry_run(999), "Random user MUST NOT be in dry-run"
    # APP_DEV_USER_IDS is empty in production after Andy's canonical forge
    # 2026-04-30. Start Over is gone for everyone — captains' Narogs are
    # permanent. This invariant prevents the destructive endpoint from being
    # silently re-enabled by a typo.
    assert APP_DEV_USER_IDS == set(), \
        f"APP_DEV_USER_IDS must be empty in production, got {APP_DEV_USER_IDS}"
    assert not is_app_dev(45), "Andy MUST NOT be in APP_DEV_USER_IDS post-canonical-forge"
    assert not is_app_dev(112), "Luke MUST NOT be in APP_DEV_USER_IDS"
    return True


@test("Narog: admin reset restores consumed discoveries (true reversibility)", tier=1, features=['crew', 'db'], mode='local')
def test_narog_reset_restore_pattern():
    """api_robot_reset must (a) read stage_sources BEFORE deleting the robot
    row, (b) UPDATE expedition_discoveries to flip analyzed=false on those
    sources, and (c) gate on is_app_dev (not is_admin — Luke is admin).

    inspect.getsource sees the @handle_api_error wrapper, not the route body,
    so we read app.py directly and isolate the api_robot_reset function block.
    """
    import os
    path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'app.py'))
    with open(path) as f:
        text = f.read()
    start = text.find('def api_robot_reset(')
    assert start > 0, "api_robot_reset not found in app.py"
    # Slice ~80 lines after the def to capture the function body.
    end = text.find('\n@app.route(', start)
    body = text[start:end] if end > 0 else text[start:start + 4000]
    assert 'analyzed = FALSE' in body, "api_robot_reset must restore consumed items via analyzed=FALSE"
    assert 'stage_sources' in body, "api_robot_reset must read stage_sources before delete"
    assert 'is_app_dev' in body, "api_robot_reset must use is_app_dev gate, not is_admin"
    sources_idx = body.find('SELECT stage_sources')
    delete_idx = body.find('DELETE FROM pilgrim.robot WHERE')
    assert sources_idx > 0 and delete_idx > 0 and sources_idx < delete_idx, \
        "stage_sources read must come BEFORE robot DELETE"
    return True


@test("Narog: broadcast_stage_async honors the dry-run guard", tier=2, features=['crew', 'blockchain'], mode='local')
def test_narog_broadcast_dry_run_guard():
    """The broadcast helper must early-return for dry-run users — no thread
    spawned, no chain write."""
    import inspect
    from utilities.postgres import robot as robot_mod
    src = inspect.getsource(robot_mod.broadcast_stage_async)
    assert 'is_narog_dry_run' in src, "broadcast_stage_async must check is_narog_dry_run"
    assert 'SKIPPED' in src or 'skip' in src.lower(), "must log skip behavior"
    return True


@test("Narog: no fabricated tx_hash strings remain", tier=2, features=['crew', 'blockchain'], mode='local')
def test_narog_no_fake_tx_hashes():
    """Forge code must not write '0xpending...' or '0xforge...' tx_hash
    placeholders — those would render as fake on-chain receipts."""
    import os
    files = [
        'utilities/postgres/robot.py',
        'utilities/robot_visuals.py',
    ]
    bad_patterns = ['0xpending{', '0xforge{', "0xstub{"]
    offenders = []
    for f in files:
        path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', f))
        if not os.path.exists(path):
            continue
        with open(path) as fp:
            text = fp.read()
        for pat in bad_patterns:
            if pat in text:
                # Allow them in _stub_advance_one_stage (the legacy helper that's
                # no longer called from the production happy path) — but flag
                # any new uses elsewhere.
                # Simple gate: only allow inside _stub_advance_one_stage body.
                # If the pattern appears outside that function, flag it.
                # Quick approximation: count occurrences and require all to be
                # within ~30 lines of '_stub_advance_one_stage'.
                pos = 0
                while True:
                    pos = text.find(pat, pos)
                    if pos == -1:
                        break
                    window_start = max(0, pos - 800)
                    window = text[window_start:pos]
                    if 'def _stub_advance_one_stage' not in window:
                        offenders.append(f"{f}: {pat} found outside _stub_advance_one_stage")
                    pos += len(pat)
    assert not offenders, "Fake tx_hash patterns found:\n  " + "\n  ".join(offenders)
    return True


@test("GCS bucket accessible", tier=3, features=['api'], mode='local')
def test_gcs_bucket():
    import requests
    url = "https://storage.googleapis.com/galactica-pilgrim-assets/email_assets/mars_banner_header_v2.jpg"
    try:
        resp = requests.head(url, timeout=5)
        if resp.status_code != 200:
            return f"GCS returned {resp.status_code}"
        return True
    except Exception:
        SKIPPED.append("GCS bucket (network error)")
        return True
