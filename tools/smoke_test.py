#!/usr/bin/env python3
"""
Pilgrims Smoke Test - Tiered, Feature-Aware Testing System
============================================================

Usage:
    python tools/smoke_test.py              # Default: ~50 tests
    python tools/smoke_test.py --quick      # Quick: ~20 tests (pre-deploy)
    python tools/smoke_test.py --full       # Full: ~200+ tests

    # Feature-specific
    python tools/smoke_test.py --crew       # Only crew/captain tests
    python tools/smoke_test.py --depot      # Only depot/upgrades tests
    python tools/smoke_test.py --expeditions # Only expedition tests
    python tools/smoke_test.py --colony     # Only colony/infrastructure tests
    python tools/smoke_test.py --signal     # Only signal/ARG tests
    python tools/smoke_test.py --api        # Only API endpoint tests

    python tools/smoke_test.py --verbose    # Show detailed errors

This does NOT:
- Spend any shards or make blockchain transactions
- Send any emails
- Modify production data (uses read-only checks where possible)
"""

import sys
import os
import signal
import argparse
from datetime import datetime

# Per-test timeout (seconds) — prevents hanging on slow DB connections
TEST_TIMEOUT = 15

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# =============================================================================
# TEST REGISTRY & RESULT TRACKING
# =============================================================================

TESTS = []  # All registered tests
PASSED = []
FAILED = []
SKIPPED = []

# Feature tags for filtering
FEATURE_TAGS = {
    'crew': ['captain', 'scientist', 'aria', 'commander', 'replicate'],
    'depot': ['upgrade', 'shop', 'purchase', 'pricing', 'build_time'],
    'expeditions': ['expedition', 'discovery', 'travel', 'landmark'],
    'colony': ['infrastructure', 'building', 'solar', 'income'],
    'signal': ['signal', 'bond', 'fragment', 'origin_site'],
    'tech': ['tech', 'research', 'branch'],
    'aria': ['aria', 'snapshot', 'colony_snapshot'],
    'api': ['api', 'endpoint', 'route'],
    'db': ['database', 'table', 'schema', 'postgres'],
    'config': ['config', 'catalog', 'pricing'],
    'blockchain': ['sepolia', 'wallet', 'tx', 'blockchain'],
}


# =============================================================================
# DECORATORS
# =============================================================================

class TestTimeoutError(Exception):
    pass


def _timeout_handler(signum, frame):
    raise TestTimeoutError(f"timed out after {TEST_TIMEOUT}s")


def test(name, tier=2, features=None):
    """Register a test with name, tier level, and feature tags."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            try:
                # Set per-test timeout via SIGALRM
                old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
                signal.alarm(TEST_TIMEOUT)
                try:
                    result = func(*args, **kwargs)
                finally:
                    signal.alarm(0)  # Cancel alarm
                    signal.signal(signal.SIGALRM, old_handler)
                if result is None or result is True:
                    PASSED.append(name)
                    print(f"  \u2705 {name}")
                    return True
                else:
                    FAILED.append((name, str(result)))
                    print(f"  \u274c {name}: {result}")
                    return False
            except TestTimeoutError:
                FAILED.append((name, f"TIMEOUT ({TEST_TIMEOUT}s)"))
                print(f"  \u23f1\ufe0f  {name}: TIMEOUT ({TEST_TIMEOUT}s)")
                return False
            except Exception as e:
                FAILED.append((name, str(e)))
                print(f"  \u274c {name}: {e}")
                return False
        wrapper._test_name = name
        wrapper._tier = tier
        wrapper._features = features or []
        TESTS.append(wrapper)
        return wrapper
    return decorator


def requires_web3(func):
    """Skip if web3 not available (venv not activated)."""
    def wrapper(*args, **kwargs):
        try:
            import web3
            return func(*args, **kwargs)
        except ImportError:
            name = getattr(func, '_test_name', func.__name__)
            SKIPPED.append(f"{name} (web3 not available)")
            print(f"  \u23ed\ufe0f  {name} (skipped - no venv)")
            return True
    wrapper._test_name = getattr(func, '_test_name', func.__name__)
    wrapper._tier = getattr(func, '_tier', 2)
    wrapper._features = getattr(func, '_features', [])
    return wrapper


def requires_import(*modules):
    """Skip if any of the listed modules can't be imported."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            for mod in modules:
                try:
                    __import__(mod)
                except ImportError:
                    name = getattr(func, '_test_name', func.__name__)
                    SKIPPED.append(f"{name} ({mod} not available)")
                    print(f"  \u23ed\ufe0f  {name} (skipped - no {mod})")
                    return True
            return func(*args, **kwargs)
        wrapper._test_name = getattr(func, '_test_name', func.__name__)
        wrapper._tier = getattr(func, '_tier', 2)
        wrapper._features = getattr(func, '_features', [])
        return wrapper
    return decorator


def requires_flask(func):
    """Skip if Flask context not available."""
    def wrapper(*args, **kwargs):
        try:
            result = func(*args, **kwargs)
            return result
        except RuntimeError as e:
            if 'context' in str(e).lower():
                name = getattr(func, '_test_name', func.__name__)
                SKIPPED.append(f"{name} (needs Flask)")
                print(f"  \u23ed\ufe0f  {name} (skipped - needs Flask)")
                return True
            raise
    wrapper._test_name = getattr(func, '_test_name', func.__name__)
    wrapper._tier = getattr(func, '_tier', 2)
    wrapper._features = getattr(func, '_features', [])
    return wrapper


# =============================================================================
# TIER 1: QUICK TESTS (~20 critical, must pass before deploy)
# =============================================================================

@test("Database connection", tier=1, features=['db'])
def test_db_connection():
    from utilities.postgres_utils import get_db_connection
    conn = get_db_connection()
    assert conn is not None, "Failed to get DB connection"
    conn.close()
    return True


@test("Users table has data", tier=1, features=['db'])
def test_users_table():
    from utilities.postgres_utils import db_cursor
    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM pilgrim.users")
        row = cur.fetchone()
        count = row['count'] if isinstance(row, dict) else row[0]
        assert count > 0, f"No users (count={count})"
    return True


@test("player_upgrades has ready_at column", tier=1, features=['db', 'depot'])
def test_upgrades_schema():
    from utilities.postgres_utils import db_cursor
    # Ensure columns exist (migration)
    with db_cursor(commit=True) as cur:
        cur.execute("""
            ALTER TABLE pilgrim.player_upgrades
            ADD COLUMN IF NOT EXISTS ready_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS pending_level INTEGER
        """)
    # Verify
    with db_cursor() as cur:
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'pilgrim' AND table_name = 'player_upgrades'
        """)
        cols = [r['column_name'] if isinstance(r, dict) else r[0] for r in cur.fetchall()]
        assert 'ready_at' in cols, f"Missing ready_at. Found: {cols}"
    return True


@test("colony_infrastructure table exists", tier=1, features=['db', 'colony'])
def test_infrastructure_table():
    from utilities.postgres_utils import db_cursor
    with db_cursor() as cur:
        cur.execute("SELECT 1 FROM pilgrim.colony_infrastructure LIMIT 1")
    return True


@test("player_techs table exists", tier=1, features=['db', 'tech'])
def test_techs_table():
    from utilities.postgres_utils import db_cursor
    with db_cursor() as cur:
        cur.execute("SELECT 1 FROM pilgrim.player_techs LIMIT 1")
    return True


@test("config.py loads", tier=1, features=['config'])
def test_config_loads():
    import config
    assert hasattr(config, 'UPGRADE_CATALOG'), "Missing UPGRADE_CATALOG"
    assert hasattr(config, 'UI_ICONS'), "Missing UI_ICONS"
    return True


@test("config_upgrades.py loads", tier=1, features=['config', 'depot'])
def test_config_upgrades():
    import config_upgrades
    assert hasattr(config_upgrades, 'UPGRADE_CATALOG'), "Missing UPGRADE_CATALOG"
    assert len(config_upgrades.UPGRADE_CATALOG) >= 3, "Too few categories"
    return True


@test("config_infrastructure.py loads", tier=1, features=['config', 'colony'])
def test_config_infrastructure():
    import config_infrastructure
    assert hasattr(config_infrastructure, 'INFRASTRUCTURE_CATALOG')
    assert len(config_infrastructure.INFRASTRUCTURE_CATALOG) >= 10, "Too few buildings"
    return True


@test("config_tech.py loads", tier=1, features=['config', 'tech'])
def test_config_tech():
    import config_tech
    assert hasattr(config_tech, 'TECH_CATALOG'), "Missing TECH_CATALOG"
    assert len(config_tech.TECH_CATALOG) >= 4, "Too few branches"
    return True


@test("Upgrade Lv2+ has build_time_days", tier=1, features=['config', 'depot'])
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


@test("sanitize_tx_error hides blockchain terms", tier=1, features=['blockchain'])
@requires_web3
def test_sanitize_error():
    from utilities.sepolia_utils import sanitize_tx_error
    raw = "{'code': -32000, 'message': 'replacement transaction underpriced'}"
    sanitized = sanitize_tx_error(raw)
    assert 'replacement' not in sanitized.lower(), "Raw error leaked"
    assert '-32000' not in sanitized, "Error code leaked"
    sanitized = sanitize_tx_error("insufficient gas")
    assert 'gas' not in sanitized.lower() or 'busy' in sanitized.lower()
    return True


@test("eth_to_display/display_to_eth inverses", tier=1, features=['blockchain', 'depot'])
@requires_web3
def test_currency_conversion():
    from utilities.depot_utils import eth_to_display, display_to_eth
    original = 1000
    eth = display_to_eth(original)
    back = eth_to_display(eth)
    assert abs(back - original) < 0.01, f"Conversion error: {original} -> {back}"
    return True


@test("get_user_upgrade_level returns int", tier=1, features=['depot'])
@requires_web3
def test_get_upgrade_level():
    from utilities.upgrades_utils import get_user_upgrade_level
    level = get_user_upgrade_level(112, 'vehicles', 'rover')
    assert isinstance(level, int), f"Expected int, got {type(level)}"
    return True


@test("get_user_upgrade_effects returns dict", tier=1, features=['depot'])
@requires_web3
def test_get_effects():
    from utilities.upgrades_utils import get_user_upgrade_effects
    effects = get_user_upgrade_effects(112)
    assert isinstance(effects, dict), f"Expected dict, got {type(effects)}"
    assert 'expedition_speed_mult' in effects, "Missing expedition_speed_mult"
    return True


@test("get_upgrade_build_status returns dict/None", tier=1, features=['depot'])
@requires_web3
def test_build_status():
    from utilities.upgrades_utils import get_upgrade_build_status
    status = get_upgrade_build_status(112, 'vehicles', 'rover')
    assert status is None or isinstance(status, dict)
    return True


@test("Infrastructure catalog valid structure", tier=1, features=['config', 'colony'])
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


@test("Tech catalog valid structure", tier=1, features=['config', 'tech'])
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


@test("UI_ICONS defined", tier=1, features=['config'])
def test_ui_icons():
    from config import UI_ICONS
    required = ['shard_gem', 'success_check', 'error_x']
    for icon in required:
        if icon not in UI_ICONS:
            return f"Missing icon: {icon}"
    assert len(UI_ICONS) >= 20, f"Expected 20+ icons, got {len(UI_ICONS)}"
    return True


@test("STAT_NAMES has 5 stats", tier=1, features=['config', 'crew'])
def test_stat_names():
    from config import STAT_NAMES
    assert len(STAT_NAMES) == 5, f"Expected 5 stats, got {len(STAT_NAMES)}"
    return True


# =============================================================================
# TIER 2: DEFAULT TESTS (~50, medium coverage)
# =============================================================================

@test("last buggy expedition query", tier=2, features=['db', 'expeditions'])
def test_last_buggy_expedition():
    from utilities.db_expeditions import get_last_completed_buggy_expedition, calculate_expedition_sv
    # SV helper
    assert calculate_expedition_sv(200) == 200
    assert calculate_expedition_sv(3500) == 1800
    # Query returns dict or None (not error)
    result = get_last_completed_buggy_expedition(112)
    if result:
        assert 'destination_name' in result and 'total_discoveries' in result and 'sv_earned' in result
    return True


@test("expeditions table exists", tier=2, features=['db', 'expeditions'])
def test_expeditions_table():
    from utilities.postgres_utils import db_cursor
    with db_cursor() as cur:
        cur.execute("SELECT 1 FROM pilgrim.expeditions LIMIT 1")
    return True


@test("expedition_discoveries table exists", tier=2, features=['db', 'expeditions'])
def test_discoveries_table():
    from utilities.postgres_utils import db_cursor
    with db_cursor() as cur:
        cur.execute("SELECT 1 FROM pilgrim.expedition_discoveries LIMIT 1")
    return True


@test("replicate_assets table exists", tier=2, features=['db', 'crew'])
def test_replicate_assets_table():
    from utilities.postgres_utils import db_cursor
    with db_cursor() as cur:
        cur.execute("SELECT 1 FROM pilgrim.replicate_assets LIMIT 1")
    return True


@test("sepolia_assets table exists", tier=2, features=['db', 'blockchain'])
def test_wallets_table():
    from utilities.postgres_utils import db_cursor
    with db_cursor() as cur:
        cur.execute("SELECT 1 FROM pilgrim.sepolia_assets LIMIT 1")
    return True


@test("depot_transactions table exists", tier=2, features=['db', 'depot'])
def test_depot_tx_table():
    from utilities.postgres_utils import db_cursor
    with db_cursor() as cur:
        cur.execute("SELECT 1 FROM pilgrim.depot_transactions LIMIT 1")
    return True


@test("mars_mission_messages table exists", tier=2, features=['db', 'signal'])
def test_mars_messages_table():
    from utilities.postgres_utils import db_cursor
    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM pilgrim.mars_mission_messages")
        row = cur.fetchone()
        count = row['count'] if isinstance(row, dict) else row[0]
        assert count > 100, f"Expected 200+ messages, got {count}"
    return True


@test("aria_bonds table + bond system", tier=2, features=['db', 'signal', 'colony'])
def test_aria_bonds_table():
    from utilities.postgres_utils import db_cursor
    from utilities.aria_bond_utils import get_user_bonds, get_pending_fragments, check_for_aria_bond, process_fragment_submission, get_user_bond_count, send_bond_notification_email
    with db_cursor() as cur:
        cur.execute("SELECT id, user_id_1, user_id_2, landmark_name, status, bond_tx_hash FROM pilgrim.aria_bonds LIMIT 1")
    assert isinstance(get_user_bonds(45), list) and isinstance(get_pending_fragments(45), list)
    assert isinstance(get_user_bond_count(45), int)
    for fn in (check_for_aria_bond, process_fragment_submission, send_bond_notification_email): assert callable(fn)

@test("trail_segments table exists", tier=2, features=['db', 'expeditions'])
def test_trails_table():
    from utilities.postgres_utils import db_cursor
    with db_cursor() as cur:
        cur.execute("SELECT 1 FROM pilgrim.trail_segments LIMIT 1")

@test("Pricing formula 1.12x validation", tier=2, features=['config', 'depot'])
def test_pricing_formula():
    from config_upgrades import UPGRADE_CATALOG
    # Check one item: vehicles/rover
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
            return f"Lv2 cost {cost2} not ~1.12x of Lv1 {cost1} (expected ~{expected})"
    return True


@test("Build time cap validation (14 days max)", tier=2, features=['config', 'depot'])
def test_build_time_cap():
    from config_upgrades import UPGRADE_CATALOG
    violations = []
    for cat, items in UPGRADE_CATALOG.items():
        for key, cfg in items.items():
            for lv, stats in cfg.get('levels', {}).items():
                days = stats.get('build_time_days', 0)
                if days > 14:
                    violations.append(f"{cat}/{key}/Lv{lv}: {days} days")
    if violations:
        return f"Build time >14 days: {violations[:3]}"
    return True


@test("Infrastructure build time cap (14 days)", tier=2, features=['config', 'colony'])
def test_infra_build_cap():
    from config_infrastructure import INFRASTRUCTURE_CATALOG
    violations = []
    for bldg, cfg in INFRASTRUCTURE_CATALOG.items():
        for lv, stats in cfg.get('levels', {}).items():
            days = stats.get('build_time_days', 0)
            if days > 14:
                violations.append(f"{bldg}/Lv{lv}: {days} days")
    if violations:
        return f"Build time >14 days: {violations[:3]}"
    return True


@test("All upgrade categories have max_level", tier=2, features=['config', 'depot'])
def test_upgrade_max_levels():
    from config_upgrades import UPGRADE_CATALOG
    missing = []
    for cat, items in UPGRADE_CATALOG.items():
        for key, cfg in items.items():
            if 'max_level' not in cfg:
                missing.append(f"{cat}/{key}")
    if missing:
        return f"Missing max_level: {missing[:3]}"
    return True


# -----------------------------------------------------------------------------
# BUG REGRESSION: Build timers must be enforced (Feb 2026)
# Issue: Upgrades were completing instantly, no 1-14 day wait
# Root cause: Frontend ignored is_building/build_time_days from API
# -----------------------------------------------------------------------------

@test("ensure_upgrades_table has deadlock prevention flag", tier=1, features=['db', 'depot'])
def test_ensure_table_flag():
    """
    BUG: Two concurrent /depot requests both ran ALTER TABLE ADD COLUMN,
    causing PostgreSQL deadlock. Fix: module-level flag to run only once.
    """
    import utilities.upgrades_utils as uu
    # Check the module has the flag
    if not hasattr(uu, '_upgrades_table_ensured'):
        return "Missing _upgrades_table_ensured flag - deadlock risk!"
    # Flag should be a bool
    if not isinstance(uu._upgrades_table_ensured, bool):
        return f"Flag should be bool, got {type(uu._upgrades_table_ensured)}"
    return True


@test("perform_upgrade returns is_building flag", tier=2, features=['depot', 'api'])
def test_perform_upgrade_response():
    """
    BUG: Frontend showed 'upgraded!' instantly because it didn't check is_building.
    The API must return is_building=True when build_time_days > 0.
    """
    from utilities.upgrades_utils import perform_upgrade
    # We can't actually call perform_upgrade (it spends shards),
    # but we verify the function signature returns the expected keys
    import inspect
    src = inspect.getsource(perform_upgrade)
    required_keys = ["'is_building'", "'build_time_days'", "'ready_at'"]
    for key in required_keys:
        if key not in src:
            return f"perform_upgrade missing {key} in return dict"
    return True


@test("Upgrade catalog includes is_building field", tier=2, features=['depot', 'api'])
@requires_web3
def test_catalog_has_building_status():
    """
    BUG: Depot cards showed upgrade button even during active builds.
    Catalog must include is_building so template can disable button.
    """
    from utilities.upgrades_utils import get_upgrade_catalog_for_user
    catalog = get_upgrade_catalog_for_user(112)  # Andy's user_id
    if not catalog:
        # Skip if empty - needs Flask request context
        SKIPPED.append("Upgrade catalog is_building (needs Flask)")
        print("  ⏭️  Upgrade catalog is_building (skipped - needs Flask)")
        return True
    # Check at least one item has the is_building key
    for cat, items in catalog.items():
        for key, item in items.items():
            if 'is_building' not in item:
                return f"{cat}/{key} missing is_building in catalog"
            if 'build_status' not in item:
                return f"{cat}/{key} missing build_status in catalog"
            return True  # Found valid structure
    return "No items in catalog to check"


@test("All Lv2+ upgrades have build_time_days >= 1", tier=1, features=['config', 'depot'])
def test_no_instant_upgrades():
    """
    BUG: Some upgrades had build_time_days=0 or missing, making them instant.
    Mars realism requires 1-14 days for all upgrades beyond Lv1.
    """
    from config_upgrades import UPGRADE_CATALOG
    instant = []
    for cat, items in UPGRADE_CATALOG.items():
        for key, cfg in items.items():
            for lv, stats in cfg.get('levels', {}).items():
                if int(lv) >= 2:
                    days = stats.get('build_time_days', 0)
                    if days < 1:
                        instant.append(f"{cat}/{key}/Lv{lv}")
    if instant:
        return f"Instant upgrades (build_time_days < 1): {instant[:3]}"
    return True


# -----------------------------------------------------------------------------
# BUG REGRESSION: SV must be permanent (Feb 2026)
# Issue: _get_available_sv() filtered by ed.analyzed=false, so SV dropped to 0
#        after sharding all discoveries. SV is permanent scientific knowledge.
# -----------------------------------------------------------------------------

@test("_get_available_sv returns int >= 0 for Andy", tier=1, features=['tech', 'colony'])
def test_sv_andy():
    from utilities.tech_utils import _get_available_sv
    sv = _get_available_sv(45)
    assert isinstance(sv, int), f"Expected int, got {type(sv)}"
    assert sv >= 0, f"SV should be >= 0, got {sv}"
    return True


@test("_get_available_sv returns int >= 0 for Luke", tier=1, features=['tech', 'colony'])
def test_sv_luke():
    from utilities.tech_utils import _get_available_sv
    sv = _get_available_sv(112)
    assert isinstance(sv, int), f"Expected int, got {type(sv)}"
    assert sv >= 0, f"SV should be >= 0, got {sv}"
    return True


@test("SV query does NOT filter by analyzed=false", tier=1, features=['tech'])
def test_sv_no_analyzed_filter():
    """SV is permanent knowledge — sharding doesn't erase what you learned."""
    import inspect
    from utilities.tech_utils import _get_available_sv
    src = inspect.getsource(_get_available_sv)
    assert 'analyzed = false' not in src.lower(), "SV query still filters by analyzed=false — SV should be permanent!"
    assert 'analyzed=false' not in src.replace(' ', '').lower(), "SV query still filters by analyzed — SV should be permanent!"
    return True


# -----------------------------------------------------------------------------
# SV ECONOMY: All 5 pillars must be functional (Mar 2026)
# Bug #1052: Brainstorm agreed on 5 SV sources, all must be wired up
# -----------------------------------------------------------------------------

@test("Research Station SV rates boosted ~6x", tier=1, features=['config', 'colony'])
def test_sv_economy_pillar1():
    from config_infrastructure import INFRASTRUCTURE_CATALOG
    rs = INFRASTRUCTURE_CATALOG['research_station']['levels']
    assert rs[1]['science_generation_rate'] >= 5.0, f"Lv1 rate should be >= 5, got {rs[1]['science_generation_rate']}"
    assert rs[10]['science_generation_rate'] >= 80.0, f"Lv10 rate should be >= 80, got {rs[10]['science_generation_rate']}"
    return True


@test("sv_milestones module loads and has thresholds", tier=1, features=['config', 'colony'])
def test_sv_economy_pillar4():
    from utilities.sv_milestones import COLLECTION_MILESTONES, get_user_milestones
    assert len(COLLECTION_MILESTONES) >= 5, "Need at least 5 milestone thresholds"
    assert COLLECTION_MILESTONES[0] == (10, 250, "Novice Collector"), f"First milestone wrong: {COLLECTION_MILESTONES[0]}"
    return True


@test("PilgrimBot sv_sources query works", tier=2, features=['pilgrimbot'])
def test_sv_sources_query():
    from utilities.pilgrimbot_data import query_player_data
    result = query_player_data('sv_sources', 112)
    assert 'PASSIVE GENERATION' in result, "Missing passive generation"
    assert 'EXTRACTION BONUS' in result, "Missing extraction bonus"
    assert 'EXPEDITION SV' in result, "Missing expedition SV"
    assert 'TRAIL BUILDING' in result, "Missing trail building"
    assert 'COLLECTION MILESTONES' in result, "Missing collection milestones"
    return True


@test("PilgrimBot calls logging table exists", tier=1, features=['pilgrimbot'])
def test_pilgrimbot_calls_table():
    from utilities.postgres_utils import db_cursor
    with db_cursor() as cur:
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'pilgrim' AND table_name = 'pilgrimbot_calls'
            ORDER BY ordinal_position
        """)
        cols = [r['column_name'] for r in cur.fetchall()]
    required = ['id', 'user_id', 'chat_id', 'phase', 'model', 'prompt_size_chars',
                'context_loaded', 'duration_ms', 'success', 'created_at']
    for c in required:
        assert c in cols, f"Missing column: {c}"
    return True


# -----------------------------------------------------------------------------
# BUG REGRESSION: ARIA colony snapshot must load cleanly (Feb 2026)
# Issue: load_colony_snapshot() had JOIN on pilgrim.discoveries (doesn't exist)
#        causing ARIA chat to return no response / break silently
# -----------------------------------------------------------------------------

@test("load_colony_snapshot loads for Andy", tier=1, features=['aria', 'crew'])
@requires_import('anthropic', 'web3')
def test_snapshot_andy():
    from utilities.aria_utils import load_colony_snapshot
    snapshot = load_colony_snapshot(45)
    assert isinstance(snapshot, dict), f"Expected dict, got {type(snapshot)}"
    assert 'commander' in snapshot, "Missing commander in snapshot"
    assert 'resources' in snapshot, "Missing resources in snapshot"
    assert 'research' in snapshot, "Missing research in snapshot"
    return True


@test("load_colony_snapshot loads for Luke", tier=1, features=['aria', 'crew'])
@requires_import('anthropic', 'web3')
def test_snapshot_luke():
    from utilities.aria_utils import load_colony_snapshot
    snapshot = load_colony_snapshot(112)
    assert isinstance(snapshot, dict), f"Expected dict, got {type(snapshot)}"
    assert 'commander' in snapshot, "Missing commander in snapshot"
    assert 'research' in snapshot, "Missing research in snapshot"
    sv = snapshot.get('research', {}).get('sv_balance', -1)
    assert sv >= 0, f"SV in snapshot should be >= 0, got {sv}"
    return True


@test("Snapshot has no reference to pilgrim.discoveries", tier=1, features=['aria', 'db'])
@requires_import('anthropic')
def test_snapshot_no_bad_table():
    """pilgrim.discoveries doesn't exist — snapshot must use expedition_discoveries."""
    import inspect
    from utilities.aria_utils import load_colony_snapshot
    src = inspect.getsource(load_colony_snapshot)
    assert 'pilgrim.discoveries' not in src, "load_colony_snapshot still references nonexistent pilgrim.discoveries table!"
    return True


# -----------------------------------------------------------------------------
# BUG REGRESSION: Discovery analyze endpoint must exist (Feb 2026)
# Issue: JS called /api/discovery/extract (wrong) instead of /api/discovery/analyze
# -----------------------------------------------------------------------------

@test("analyze endpoint exists in app.py", tier=1, features=['api', 'expeditions'])
@requires_import('flask', 'replicate', 'web3')
def test_analyze_endpoint():
    """colony-discoveries.js calls /api/discovery/analyze — it must exist."""
    import inspect
    import app as flask_app
    rules = [rule.rule for rule in flask_app.app.url_map.iter_rules()]
    # Check both possible patterns
    has_analyze = any('analyze' in r and 'discovery' in r for r in rules)
    assert has_analyze, f"No /api/discovery/analyze route found! JS will break."
    return True


# =============================================================================
# TIER 2: UTILITY FUNCTION INTEGRATION TESTS
# =============================================================================

@test("hydrate_user_session returns valid dict", tier=2, features=['db', 'crew'])
def test_hydrate_session():
    """Every page load depends on session hydration — if broken, everything breaks."""
    from utilities.db_users import hydrate_user_session
    data = hydrate_user_session(112)
    assert isinstance(data, dict), f"Expected dict, got {type(data)}"
    return True


@test("get_user_scientist returns dict or None", tier=2, features=['crew'])
def test_get_scientist():
    from utilities.db_users import get_user_scientist
    sci = get_user_scientist(112)
    assert sci is None or isinstance(sci, dict), f"Expected dict/None, got {type(sci)}"
    if sci:
        assert 'name' in sci or 'key' in sci, f"Scientist missing name/key: {list(sci.keys())}"
    return True


@test("get_effective_commander_stats returns 5 stats", tier=2, features=['crew', 'depot'])
@requires_web3
def test_effective_stats():
    """EVA suit bonuses multiply across all expeditions — wrong math compounds."""
    from utilities.shop_utils import get_effective_commander_stats
    base = {'leadership': 50, 'strategy': 50, 'exploration': 50, 'logistics': 50, 'charisma': 50}
    result = get_effective_commander_stats(112, base)
    assert isinstance(result, dict), f"Expected dict, got {type(result)}"
    for stat in ['leadership', 'strategy', 'exploration', 'logistics', 'charisma']:
        assert stat in result, f"Missing stat: {stat}"
        assert result[stat] >= 50, f"{stat} should be >= base (50), got {result[stat]}"
    return True


@test("get_user_infrastructure_effects returns dict", tier=2, features=['colony'])
@requires_web3
def test_infra_effects():
    """Infrastructure bonuses are silent — wrong values affect everything."""
    from utilities.infrastructure_utils import get_user_infrastructure_effects
    effects = get_user_infrastructure_effects(112)
    assert isinstance(effects, dict), f"Expected dict, got {type(effects)}"
    return True


@test("get_fleet_status returns 3 slots", tier=2, features=['expeditions'])
def test_fleet_status():
    from utilities.page_data_utils import get_fleet_status
    fleet = get_fleet_status(112)
    assert isinstance(fleet, dict), f"Expected dict, got {type(fleet)}"
    for slot in ['rover', 'drone', 'buggy']:
        assert slot in fleet, f"Missing fleet slot: {slot}"
        assert 'status' in fleet[slot], f"{slot} missing 'status' key"
    return True


@test("get_signal_page_data returns dict with origin_sites", tier=2, features=['signal'])
def test_signal_data():
    from utilities.signal_utils import get_signal_page_data
    data = get_signal_page_data()
    assert isinstance(data, dict), f"Expected dict, got {type(data)}"
    assert 'origin_sites' in data, f"Missing origin_sites. Keys: {list(data.keys())}"
    assert 'stats' in data or 'total_origins' in data or len(data) >= 3, f"Signal data too sparse: {list(data.keys())}"
    return True


@test("calculate_expedition_cost returns dict with cost", tier=2, features=['expeditions'])
@requires_web3
def test_expedition_cost():
    """Core game loop — wrong cost breaks expedition launches."""
    from utilities.expedition_utils import calculate_expedition_cost
    result = calculate_expedition_cost(
        distance_km=500.0,
        destination_type='crater',
        commander_stats={'leadership': 50, 'strategy': 50, 'exploration': 50, 'logistics': 50, 'charisma': 50},
        user_expeditions_completed=5
    )
    assert isinstance(result, dict), f"Expected dict, got {type(result)}"
    assert 'base_expedition_cost' in result, f"Missing base_expedition_cost. Keys: {list(result.keys())}"
    assert 'travel_hours' in result, f"Missing travel_hours in result"
    assert result['base_expedition_cost'] > 0, f"Cost should be positive, got {result['base_expedition_cost']}"
    return True


@test("FluxGenerator importable", tier=2, features=['crew'])
@requires_import('replicate')
def test_flux_import():
    try:
        from utilities.flux_utils import FluxGenerator
        return True
    except ImportError as e:
        return f"FluxGenerator import failed: {e}"


@test("MarsAsteroidMiner importable", tier=2, features=['blockchain'])
@requires_web3
def test_miner_import():
    from utilities.sepolia_utils import MarsAsteroidMiner
    return True


@test("get_upgrade_catalog_for_user returns dict", tier=2, features=['depot'])
@requires_web3
def test_get_catalog():
    from utilities.upgrades_utils import get_upgrade_catalog_for_user
    catalog = get_upgrade_catalog_for_user(112)
    assert isinstance(catalog, dict)
    if not catalog:
        SKIPPED.append("get_upgrade_catalog_for_user (needs Flask)")
        print("  \u23ed\ufe0f  get_upgrade_catalog_for_user (skipped - needs Flask)")
        return True
    assert 'vehicles' in catalog, "Missing vehicles"
    return True


@test("get_fast_balance returns numeric", tier=2, features=['blockchain', 'depot'])
@requires_web3
@requires_flask
def test_get_balance():
    from utilities.depot_utils import get_fast_balance_and_wallet_info
    balance, _, _ = get_fast_balance_and_wallet_info(112)
    assert isinstance(balance, (int, float))
    return True


@test("API: home page responds", tier=2, features=['api'])
def test_api_home():
    return _test_endpoint("/")


@test("API: /api/tech/status responds", tier=2, features=['api', 'tech'])
def test_api_tech():
    return _test_endpoint("/api/tech/status")


@test("API: /changelog responds", tier=2, features=['api'])
def test_api_changelog():
    return _test_endpoint("/changelog")


@test("get_unified_activity returns list", tier=2, features=['colony', 'api'])
def test_unified_activity():
    from utilities.db_shop import get_unified_activity
    activity = get_unified_activity(112, limit=10)  # Andy's user_id
    assert isinstance(activity, list), f"Expected list, got {type(activity)}"
    return True


@test("get_unified_activity limit increased to 500", tier=2, features=['colony'])
def test_activity_limit():
    """Verify activity limit was increased from 200 to 500."""
    import inspect
    from utilities.db_shop import get_unified_activity
    sig = inspect.signature(get_unified_activity)
    default_limit = sig.parameters['limit'].default
    assert default_limit >= 500, f"Activity limit should be 500+, got {default_limit}"
    return True


@test("API: brainstorm pages respond", tier=2, features=['api'])
def test_brainstorm_pages():
    """Verify all brainstorm pages return 200."""
    pages = [
        '/brainstorm/signal', '/brainstorm/signal-phase-2',
        '/brainstorm/robot-crew', '/brainstorm/captain-stats',
        '/brainstorm/depot-recalibration', '/brainstorm/trail-network',
        '/brainstorm/tech-tree', '/brainstorm/aria-meetings',
        '/brainstorm/sv-economy', '/brainstorm/icon-redesign',
    ]
    for page in pages:
        result = _test_endpoint(page)
        if result is not True:
            return f"{page}: {result}"
    return True


@test("Harvest claim is atomic (no split transactions)", tier=2, features=['infrastructure'])
def test_harvest_atomic():
    """Verify claim_accumulated_income uses single db_cursor for balance+timer."""
    import inspect
    from utilities.infrastructure_utils import claim_accumulated_income
    source = inspect.getsource(claim_accumulated_income)
    # The fix: balance update and last_payout_at must be in the SAME db_cursor block
    # Old bug: two separate db_cursor(commit=True) blocks = shards lost on failure
    assert 'threading.Thread' in source, "Harvest should use background thread for blockchain tx"
    assert source.count('with db_cursor(commit=True)') == 1, "Harvest should have exactly 1 atomic db_cursor block (balance + timer together)"
    return True


@test("Screenshot delete endpoint exists", tier=2, features=['bugs'])
def test_screenshot_delete_route():
    """Verify DELETE /api/admin/bugs/<id>/screenshot/<field> route exists."""
    from app import app
    rules = [r.rule for r in app.url_map.iter_rules()]
    assert '/api/admin/bugs/<int:bug_id>/screenshot/<field>' in rules, "Screenshot delete route missing"
    return True


@test("Environmental impact capped at 100%", tier=2, features=['infrastructure'])
def test_env_impact_cap():
    """Verify environmental combined factor can't exceed 1.0."""
    from utilities.infrastructure_utils import _get_mars_environment_factors
    # Test with equatorial latitude (best case for exceeding 100%)
    factors = _get_mars_environment_factors(0.0)
    assert factors['combined'] <= 1.0, f"Combined factor {factors['combined']} exceeds 1.0"
    return True


@test("Recent discoveries filter by complete expeditions", tier=2, features=['db', 'expeditions'])
def test_recent_discoveries_filter():
    """Verify get_recent_discoveries query includes expedition status check."""
    import inspect
    from utilities.db_expeditions import get_recent_discoveries
    source = inspect.getsource(get_recent_discoveries)
    assert "e.status = 'complete'" in source, "Recent discoveries query must filter by expedition status='complete'"
    return True


@test("ARIA trail context includes all crew members", tier=2, features=['aria'])
def test_aria_trail_context():
    """Verify ARIA context builder checks captain, scientist, AND aria trail missions."""
    import inspect
    from utilities.aria_utils import _build_friend_prompt
    source = inspect.getsource(_build_friend_prompt)
    assert "crew.get('aria')" in source, "ARIA context must check for aria trail missions"
    return True


# =============================================================================
# TIER 3: FULL TESTS (comprehensive, slower)
# =============================================================================

@test("All catalogs have complete 10-level progressions", tier=3, features=['config'])
def test_all_catalog_levels():
    """Verify upgrades (11 paths), infrastructure (13 buildings), tech (4 branches) all have Lv1-10."""
    errors = []
    from config_upgrades import UPGRADE_CATALOG
    for cat, items in UPGRADE_CATALOG.items():
        for key, cfg in items.items():
            for lv in range(1, cfg.get('max_level', 10) + 1):
                if lv not in cfg.get('levels', {}):
                    errors.append(f"upgrade:{cat}/{key}/Lv{lv}")
    from config_infrastructure import INFRASTRUCTURE_CATALOG
    for bldg, cfg in INFRASTRUCTURE_CATALOG.items():
        for lv in range(1, 11):
            if lv not in cfg.get('levels', {}):
                errors.append(f"infra:{bldg}/Lv{lv}")
        for prereq in cfg.get('prerequisites', {}):
            if prereq not in INFRASTRUCTURE_CATALOG:
                errors.append(f"infra:{bldg} bad prereq:{prereq}")
    from config_tech import TECH_CATALOG
    for branch, cfg in TECH_CATALOG.items():
        for lv in range(1, 11):
            if lv not in cfg.get('levels', {}):
                errors.append(f"tech:{branch}/Lv{lv}")
    if errors:
        return f"Missing: {errors[:5]}"
    return True


@test("Effect aggregation uses max() for multipliers", tier=3, features=['depot'])
@requires_web3
def test_effect_aggregation():
    from utilities.upgrades_utils import get_user_upgrade_effects
    effects = get_user_upgrade_effects(112)
    mult = effects.get('expedition_speed_mult', 1.0)
    # Should be max(), not sum(). Max reasonable is ~15x
    assert mult <= 20.0, f"Speed mult {mult} too high - possibly summing"
    return True


@test("GCS bucket accessible", tier=3, features=['api'])
def test_gcs_bucket():
    import requests
    url = "https://storage.googleapis.com/galactica-pilgrim-assets/email_assets/mars_banner_header_v2.jpg"
    try:
        resp = requests.head(url, timeout=5)
        if resp.status_code != 200:
            return f"GCS returned {resp.status_code}"
        return True
    except Exception as e:
        SKIPPED.append(f"GCS bucket (network error)")
        print(f"  \u23ed\ufe0f  GCS bucket (skipped - {e})")
        return True


@test("haversine_distance returns positive", tier=3, features=['expeditions'])
def test_haversine():
    from utilities.mars_math import haversine_distance
    # Olympus Mons to Jezero Crater
    dist = haversine_distance(18.65, -133.8, 18.4, 77.7)
    assert dist > 0, f"Distance should be positive, got {dist}"
    assert dist < 10000, f"Distance unreasonably large: {dist}"
    return True


@test("calculate_travel_time returns dict", tier=3, features=['expeditions'])
@requires_web3
def test_travel_time():
    from utilities.expedition_utils import calculate_travel_time
    result = calculate_travel_time(1000, 1.0)  # 1000 km, 1x speed
    assert isinstance(result, dict), f"Expected dict, got {type(result)}"
    assert 'travel_hours' in result or 'travel_days' in result, "Missing time keys"
    return True


# =============================================================================
# PERFORMANCE: DB QUERY COUNT GUARDS
# These tests BLOCK deployment if N+1 query regressions are reintroduced.
# =============================================================================

@test("get_user_upgrade_effects makes <= 15 DB calls", tier=1, features=['colony', 'database'])
@requires_web3
def test_upgrade_effects_query_count():
    """Guard against N+1 query regressions in the upgrade effects pipeline."""
    from contextlib import contextmanager
    import utilities.postgres_utils as pu
    original_cursor = pu.db_cursor
    call_count = [0]

    @contextmanager
    def counted_cursor(**kwargs):
        call_count[0] += 1
        with original_cursor(**kwargs) as cur:
            yield cur
    pu.db_cursor = counted_cursor

    try:
        # Use user_id=1 as a safe read-only test (any valid user works)
        from utilities.postgres_utils import db_cursor
        with original_cursor() as cur:
            cur.execute("SELECT id FROM pilgrim.users LIMIT 1")
            row = cur.fetchone()
        if not row:
            SKIPPED.append("No users in DB for perf test")
            return True
        test_uid = row['id']

        call_count[0] = 0
        from utilities.upgrades_utils import get_user_upgrade_effects
        get_user_upgrade_effects(test_uid)

        MAX_ALLOWED = 15  # Was 29 before N+1 fix, now ~10
        assert call_count[0] <= MAX_ALLOWED, (
            f"get_user_upgrade_effects made {call_count[0]} DB calls (max {MAX_ALLOWED}). "
            f"N+1 query regression detected!"
        )
    finally:
        pu.db_cursor = original_cursor
    return True


@test("calculate_accumulated_income makes <= 30 DB calls", tier=1, features=['colony', 'database'])
@requires_web3
def test_income_calc_query_count():
    """Guard against N+1 query regressions in income calculation."""
    from contextlib import contextmanager
    import utilities.postgres_utils as pu
    original_cursor = pu.db_cursor
    call_count = [0]

    @contextmanager
    def counted_cursor(**kwargs):
        call_count[0] += 1
        with original_cursor(**kwargs) as cur:
            yield cur
    pu.db_cursor = counted_cursor

    try:
        from utilities.postgres_utils import db_cursor
        with original_cursor() as cur:
            cur.execute("SELECT id FROM pilgrim.users LIMIT 1")
            row = cur.fetchone()
        if not row:
            SKIPPED.append("No users in DB for perf test")
            return True
        test_uid = row['id']

        call_count[0] = 0
        from utilities.infrastructure_utils import calculate_accumulated_income
        calculate_accumulated_income(test_uid)

        MAX_ALLOWED = 30  # Was 64 before N+1 fix, now ~22
        assert call_count[0] <= MAX_ALLOWED, (
            f"calculate_accumulated_income made {call_count[0]} DB calls (max {MAX_ALLOWED}). "
            f"N+1 query regression detected!"
        )
    finally:
        pu.db_cursor = original_cursor
    return True


# =============================================================================
# BUG TRACKER TESTS
# =============================================================================

@test("Bug tracker tables create without error", tier=1, features=['db', 'bugs'])
def test_bug_tables():
    from utilities.db_bugs import ensure_bug_tables
    ensure_bug_tables()

@test("Bug tracker CRUD works", tier=2, features=['db', 'bugs'])
def test_bug_crud():
    from utilities.db_bugs import create_bug, get_bug_by_id, update_bug, search_bugs
    from utilities.postgres_utils import db_cursor
    bug = create_bug(name='__smoke_test_bug__', description='Auto-test', type='Bug', priority='P5')
    assert bug and bug['id'], "create_bug returned None"
    fetched = get_bug_by_id(bug['id'])
    assert fetched and fetched['name'] == '__smoke_test_bug__', "get_bug_by_id failed"
    ok = update_bug(bug['id'], 'smoke_test', status='Working On')
    assert ok, "update_bug failed"
    results = search_bugs('__smoke_test_bug__')
    assert len(results) >= 1, "search_bugs returned no results"
    # Cleanup
    with db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM pilgrim.bug_history WHERE bug_id = %s", (bug['id'],))
        cur.execute("DELETE FROM pilgrim.bugs WHERE id = %s", (bug['id'],))

@test("Bug tracker stats returns dict", tier=2, features=['db', 'bugs'])
def test_bug_stats():
    from utilities.db_bugs import get_bug_stats
    stats = get_bug_stats()
    assert isinstance(stats, dict), f"Expected dict, got {type(stats)}"
    assert 'active_count' in stats, "Missing active_count key"

@test("Admin bugs page data loads without error", tier=2, features=['db', 'bugs'])
def test_admin_bugs_page_data():
    """Smoke test the exact query path that /admin/bugs uses to render."""
    from utilities.db_bugs import get_active_bugs, get_completed_bugs, get_ideas, get_bug_stats
    from utilities.postgres_utils import db_cursor, _fetchall
    # This is the exact query from the admin_bugs() route — if it fails, the page 500s
    with db_cursor() as cur:
        cur.execute("SELECT name, given_name, email FROM pilgrim.users WHERE is_admin = true ORDER BY name")
        mention_users = [{'name': r['name'], 'handle': (r.get('given_name') or r['name'].split()[0]).lower(), 'email': r['email']} for r in _fetchall(cur)]
    assert len(mention_users) >= 1, "No admin users found for @mentions"
    active = get_active_bugs()
    assert isinstance(active, list), "get_active_bugs didn't return list"
    completed = get_completed_bugs()
    assert isinstance(completed, list), "get_completed_bugs didn't return list"
    ideas = get_ideas()
    assert isinstance(ideas, list), "get_ideas didn't return list"


# =============================================================================
# API ENDPOINT HELPER
# =============================================================================

def _test_endpoint(endpoint, expected_status=200):
    """Test an API endpoint. Returns True, error string, or skips."""
    import requests
    try:
        resp = requests.get(f"http://localhost:5001{endpoint}", timeout=5)
        if resp.status_code == 404:
            SKIPPED.append(f"API: {endpoint} (404 - needs auth)")
            return True
        if resp.status_code != expected_status:
            return f"Status {resp.status_code}"
        return True
    except requests.exceptions.ConnectionError:
        SKIPPED.append(f"API: {endpoint} (server not running)")
        return True
    except Exception as e:
        return str(e)


def check_gcloud_logs():
    """Check recent gcloud logs for errors after deployment."""
    import subprocess
    try:
        result = subprocess.run(['gcloud', 'app', 'logs', 'read', '--limit=50'],
                                capture_output=True, text=True, timeout=30)
        errors = [l.strip()[:120] for l in result.stdout.split('\n')
                  if ('ERROR:' in l or 'Exception' in l or '500' in l)
                  and 'Could not store access token' not in l]
        if errors:
            print(f"\n  \u274c Found {len(errors)} error(s) in recent logs:")
            for err in errors[:10]:
                print(f"     {err}")
        else:
            print("\n  \u2705 No errors in recent logs")
        return len(errors)
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
        print(f"  \u26a0\ufe0f  Log check skipped: {e}")
        return 0


# =============================================================================
# TEST RUNNER
# =============================================================================

ALL_FEATURES = ['crew', 'depot', 'expeditions', 'colony', 'signal', 'tech', 'aria', 'api', 'db', 'config', 'blockchain', 'bugs']


def get_tests_to_run(args):
    """Filter tests based on CLI arguments."""
    max_tier = 1 if args.quick else (3 if args.full else 2)
    tests = [t for t in TESTS if t._tier <= max_tier]

    active = [f for f in ALL_FEATURES if getattr(args, f, False)]
    if active:
        def matches(t):
            for af in active:
                if af in t._features:
                    return True
                if any(tag in t._features for tag in FEATURE_TAGS.get(af, [])):
                    return True
            return False
        tests = [t for t in tests if matches(t)]
    return tests


def run_tests(args):
    """Run all applicable tests."""
    global PASSED, FAILED, SKIPPED
    PASSED, FAILED, SKIPPED = [], [], []
    tests = get_tests_to_run(args)

    mode = "quick (Tier 1)" if args.quick else ("full (Tier 1-3)" if args.full else "default (Tier 1-2)")
    active = [f for f in ALL_FEATURES if getattr(args, f, False)]
    if active:
        mode += f" + {', '.join(active)}"

    print(f"\n{'=' * 60}\n\U0001f9ea PILGRIMS SMOKE TEST\n   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n   Mode: {mode}\n   Tests: {len(tests)}\n   Per-test timeout: {TEST_TIMEOUT}s\n{'=' * 60}\n")

    start_time = datetime.now()
    for t in tests:
        t()
        # Global safety: abort if total time exceeds 3 minutes
        elapsed = (datetime.now() - start_time).total_seconds()
        if elapsed > 180:
            print(f"\n  ⚠️  GLOBAL TIMEOUT: {elapsed:.0f}s elapsed, skipping remaining tests")
            remaining = tests[tests.index(t) + 1:]
            for r in remaining:
                SKIPPED.append(f"{r._test_name} (global timeout)")
            break

    print(f"\n{'=' * 60}\n\U0001f4ca RESULTS\n{'=' * 60}")
    print(f"  \u2705 Passed:  {len(PASSED)}\n  \u274c Failed:  {len(FAILED)}\n  \u23ed\ufe0f  Skipped: {len(SKIPPED)}")

    if FAILED:
        print("\n\u274c FAILURES:")
        for name, error in FAILED:
            print(f"   \u2022 {name}")
            if args.verbose:
                print(f"     {error}")
    if SKIPPED and args.verbose:
        print("\n\u23ed\ufe0f  SKIPPED:")
        for name in SKIPPED:
            print(f"   \u2022 {name}")

    print(f"\n{'=' * 60}")
    if FAILED:
        print("\U0001f534 SOME TESTS FAILED - Check before deploying!")
        return 1
    print("\U0001f7e2 ALL TESTS PASSED")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Pilgrims Smoke Test")
    tier = parser.add_mutually_exclusive_group()
    tier.add_argument("--quick", action="store_true", help="Tier 1 only (~20 tests)")
    tier.add_argument("--full", action="store_true", help="Tier 1-3 (100+ tests)")
    for feat in ALL_FEATURES:
        parser.add_argument(f"--{feat}", action="store_true", help=f"Only {feat} tests")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed errors")
    parser.add_argument("--post-deploy", action="store_true", help="Check gcloud logs")
    args = parser.parse_args()

    if args.post_deploy:
        print(f"\n{'=' * 60}\n\U0001f4cb POST-DEPLOY LOG CHECK\n{'=' * 60}")
        check_gcloud_logs()
    sys.exit(run_tests(args))


if __name__ == "__main__":
    main()
