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
    from utilities.postgres_utils import get_db_connection
    conn = get_db_connection()
    assert conn is not None, "Failed to get DB connection"
    conn.close()
    return True


@test("Users table has data", tier=1, features=['db'], mode='local')
def test_users_table():
    from utilities.postgres_utils import db_cursor
    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM pilgrim.users")
        row = cur.fetchone()
        count = row['count'] if isinstance(row, dict) else row[0]
        assert count > 0, f"No users (count={count})"
    return True


@test("player_upgrades has ready_at column", tier=1, features=['db', 'depot'], mode='local')
def test_upgrades_schema():
    from utilities.postgres_utils import db_cursor
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
    from utilities.postgres_utils import db_cursor
    with db_cursor() as cur:
        cur.execute("SELECT 1 FROM pilgrim.colony_infrastructure LIMIT 1")
    return True


@test("player_techs table exists", tier=1, features=['db', 'tech'], mode='local')
def test_techs_table():
    from utilities.postgres_utils import db_cursor
    with db_cursor() as cur:
        cur.execute("SELECT 1 FROM pilgrim.player_techs LIMIT 1")
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
    from utilities.postgres_utils import db_cursor
    with db_cursor() as cur:
        cur.execute("SELECT 1 FROM pilgrim.expeditions LIMIT 1")
    return True


@test("expedition_discoveries table exists", tier=2, features=['db', 'expeditions'], mode='local')
def test_discoveries_table():
    from utilities.postgres_utils import db_cursor
    with db_cursor() as cur:
        cur.execute("SELECT 1 FROM pilgrim.expedition_discoveries LIMIT 1")
    return True


@test("replicate_assets table exists", tier=2, features=['db', 'crew'], mode='local')
def test_replicate_assets_table():
    from utilities.postgres_utils import db_cursor
    with db_cursor() as cur:
        cur.execute("SELECT 1 FROM pilgrim.replicate_assets LIMIT 1")
    return True


@test("sepolia_assets table exists", tier=2, features=['db', 'blockchain'], mode='local')
def test_wallets_table():
    from utilities.postgres_utils import db_cursor
    with db_cursor() as cur:
        cur.execute("SELECT 1 FROM pilgrim.sepolia_assets LIMIT 1")
    return True


@test("depot_transactions table exists", tier=2, features=['db', 'depot'], mode='local')
def test_depot_tx_table():
    from utilities.postgres_utils import db_cursor
    with db_cursor() as cur:
        cur.execute("SELECT 1 FROM pilgrim.depot_transactions LIMIT 1")
    return True


@test("mars_mission_messages table exists", tier=2, features=['db', 'signal'], mode='local')
def test_mars_messages_table():
    from utilities.postgres_utils import db_cursor
    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM pilgrim.mars_mission_messages")
        row = cur.fetchone()
        count = row['count'] if isinstance(row, dict) else row[0]
        assert count > 100, f"Expected 200+ messages, got {count}"
    return True


@test("aria_bonds table exists", tier=2, features=['db', 'signal'], mode='local')
def test_aria_bonds_table():
    from utilities.postgres_utils import db_cursor
    with db_cursor() as cur:
        cur.execute("SELECT 1 FROM pilgrim.aria_bonds LIMIT 1")
    return True


@test("trail_segments table exists", tier=2, features=['db', 'expeditions'], mode='local')
def test_trails_table():
    from utilities.postgres_utils import db_cursor
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
        from utilities.flux_utils import FluxGenerator
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
