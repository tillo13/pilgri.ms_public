#!/usr/bin/env python3
"""
New Player Walkthrough Test Harness
====================================
Validates the complete new player experience from first login to first expedition.

This tests the BACKEND journey - API endpoints, database state, and business logic.
UI/visual testing requires manual verification.

Usage:
    python tools/new_player_walkthrough.py              # Run all tests
    python tools/new_player_walkthrough.py --user 123   # Test specific user
    python tools/new_player_walkthrough.py --dry-run    # Check without modifying
    python tools/new_player_walkthrough.py --checklist  # Print manual QA checklist

New Player Journey (what we're testing):
=========================================
1. LOGIN         - User authenticates via Google OAuth
2. ONBOARDING    - Commander selection, scientist assignment, Mars landing
3. HOME PAGE     - See colony status, build first solar array (FREE)
4. WELCOME BONUS - Receive 750 shards for building solar array
5. DEPOT         - Buy battery (10 shards), then Research Station (500)
6. EXPEDITIONS   - Launch first expedition, discover items
7. HARVEST       - Claim solar income, extract discovery shards

Each step has:
- Prerequisites (what must exist before this step)
- Actions (what the player does)
- Validations (what we check worked)
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
from datetime import datetime, timedelta
from decimal import Decimal

# Test result tracking
class TestResult:
    def __init__(self, name):
        self.name = name
        self.passed = []
        self.failed = []
        self.warnings = []

    def ok(self, msg):
        self.passed.append(msg)
        print(f"  \033[92m✓\033[0m {msg}")

    def fail(self, msg):
        self.failed.append(msg)
        print(f"  \033[91m✗\033[0m {msg}")

    def warn(self, msg):
        self.warnings.append(msg)
        print(f"  \033[93m⚠\033[0m {msg}")

    def summary(self):
        total = len(self.passed) + len(self.failed)
        if self.failed:
            return f"\033[91m{self.name}: {len(self.passed)}/{total} passed\033[0m"
        return f"\033[92m{self.name}: {len(self.passed)}/{total} passed\033[0m"


def print_header(title):
    print(f"\n\033[1m{'='*60}\033[0m")
    print(f"\033[1m{title}\033[0m")
    print(f"\033[1m{'='*60}\033[0m")


def print_section(title):
    print(f"\n\033[96m--- {title} ---\033[0m")


# =============================================================================
# STEP 1: LOGIN & BASIC USER STATE
# =============================================================================
def test_user_exists(user_id):
    """Test that user exists and has basic data"""
    result = TestResult("User Exists")

    from utilities.postgres.core import db_cursor

    with db_cursor() as cur:
        cur.execute("SELECT id, email, given_name, created_at, login_count FROM pilgrim.users WHERE id = %s", (user_id,))
        user = cur.fetchone()

    if not user:
        result.fail(f"User {user_id} not found in database")
        return result

    result.ok(f"User found: {user['email']}")
    result.ok(f"Name: {user['given_name'] or '(not set)'}")
    result.ok(f"Created: {user['created_at']}")
    result.ok(f"Login count: {user['login_count']}")

    return result


# =============================================================================
# STEP 2: ONBOARDING COMPLETION
# =============================================================================
def test_onboarding_complete(user_id):
    """Test that user has completed onboarding (commander, scientist, wallet, location)"""
    result = TestResult("Onboarding Complete")

    from utilities.postgres.core import db_cursor
    from utilities.postgres.assets import get_user_replicate_assets
    from utilities.postgres.users import get_user_scientist
    from utilities.postgres.wallets import get_user_sepolia_wallets
    from utilities.postgres.map import get_or_set_user_mars_home

    # Check commander
    commanders = get_user_replicate_assets(user_id, asset_type='character_image')
    if commanders:
        primary = [c for c in commanders if c.get('is_primary')]
        result.ok(f"Commander exists: {len(commanders)} total, {len(primary)} primary")
        if primary:
            result.ok(f"Primary commander: {primary[0].get('commander_name', 'unnamed')}")
    else:
        result.fail("No commander found - user needs to complete /crew")

    # Check scientist
    scientist = get_user_scientist(user_id)
    if scientist:
        result.ok(f"Scientist assigned: {scientist.get('name', 'unknown')}")
    else:
        result.fail("No scientist assigned")

    # Check wallet
    wallets = get_user_sepolia_wallets(user_id)
    if wallets:
        primary_wallet = next((w for w in wallets if w.get('is_primary')), wallets[0])
        balance = float(primary_wallet.get('current_balance_eth', 0)) * 10000000
        result.ok(f"Wallet exists: {primary_wallet['wallet_address'][:10]}...")
        result.ok(f"Current balance: {balance:.1f} shards")
    else:
        result.fail("No wallet found - critical issue")

    # Check Mars location
    location = get_or_set_user_mars_home(user_id)
    if location:
        result.ok(f"Mars location set: {location['latitude']:.2f}°N, {location['longitude']:.2f}°E")
    else:
        result.fail("No Mars location set")

    return result


# =============================================================================
# STEP 3: INFRASTRUCTURE STATE
# =============================================================================
def test_infrastructure_state(user_id):
    """Test user's infrastructure - what they've built"""
    result = TestResult("Infrastructure State")

    from utilities.postgres.core import db_cursor
    from utilities.infrastructure_utils import get_user_infrastructure
    from config import INFRASTRUCTURE_CATALOG

    infrastructure = get_user_infrastructure(user_id)

    if not infrastructure:
        result.warn("No infrastructure built yet - new player should build solar array first")
        result.warn(f"Solar array is FREE - player should be prompted on /home")
        return result

    # Check what's built
    active = [i for i in infrastructure if i.get('status') == 'active']
    building = [i for i in infrastructure if i.get('status') == 'building']

    result.ok(f"Total infrastructure: {len(infrastructure)} ({len(active)} active, {len(building)} building)")

    # Check for solar array (essential for income)
    has_solar = any(i['structure_type'] == 'solar_array' for i in infrastructure)
    if has_solar:
        result.ok("Solar array: BUILT (generates income)")
    else:
        result.fail("Solar array: NOT BUILT - player cannot generate income!")

    # Check for battery (enables night generation)
    has_battery = any(i['structure_type'] == 'battery_storage' for i in infrastructure)
    if has_battery:
        result.ok("Battery: BUILT (night generation enabled)")
    else:
        result.warn("Battery: not built yet (only 10 shards, suggest to player)")

    # List all infrastructure
    for item in infrastructure:
        name = INFRASTRUCTURE_CATALOG.get(item['structure_type'], {}).get('name', item['structure_type'])
        status = item.get('status', 'unknown')
        if status == 'building':
            ready_at = item.get('ready_at')
            if ready_at:
                remaining = (ready_at - datetime.now()).total_seconds()
                if remaining > 0:
                    hours = remaining / 3600
                    result.ok(f"  {name}: building ({hours:.1f}h remaining)")
                else:
                    result.warn(f"  {name}: ready to activate!")
        else:
            rate = item.get('generation_rate', 0)
            if rate:
                result.ok(f"  {name}: active, generating {rate:.1f}/hr")
            else:
                result.ok(f"  {name}: active")

    return result


# =============================================================================
# STEP 4: WELCOME BONUS CHECK
# =============================================================================
def test_welcome_bonus(user_id):
    """Test that welcome bonus was received (750 shards for first solar array)"""
    result = TestResult("Welcome Bonus")

    from utilities.postgres.core import db_cursor

    # Check depot transactions for infrastructure_completion reward
    with db_cursor() as cur:
        cur.execute("""
            SELECT amount_eth, created_at, item_details
            FROM pilgrim.depot_transactions
            WHERE user_id = %s
              AND purchase_type = 'infrastructure_completion'
            ORDER BY created_at ASC
            LIMIT 1
        """, (user_id,))
        reward = cur.fetchone()

    if reward:
        amount_display = float(reward['amount_eth']) * 10000000
        result.ok(f"Welcome bonus received: {amount_display:.0f} shards")
        result.ok(f"Received at: {reward['created_at']}")

        # Check if it's the new 750 amount or old 100
        if amount_display >= 700:
            result.ok("Bonus is updated amount (750 shards)")
        else:
            result.warn(f"Bonus is old amount ({amount_display:.0f}) - player may have joined before update")
    else:
        result.warn("No welcome bonus found - either not built solar yet, or tx not recorded")

    return result


# =============================================================================
# STEP 5: EXPEDITION CAPABILITY
# =============================================================================
def test_expedition_capability(user_id):
    """Test that user can launch expeditions"""
    result = TestResult("Expedition Capability")

    from utilities.postgres.core import db_cursor
    from utilities.postgres.expeditions import get_user_active_expeditions
    from utilities.upgrades_utils import get_user_upgrade_level, get_user_owned_vehicles

    # Check vehicle levels
    rover_level = get_user_upgrade_level(user_id, 'vehicles', 'rover')
    drone_level = get_user_upgrade_level(user_id, 'vehicles', 'drone')
    buggy_level = get_user_upgrade_level(user_id, 'vehicles', 'buggy')

    result.ok(f"Rover level: {rover_level} (default: 1)")
    if drone_level > 0:
        result.ok(f"Drone level: {drone_level}")
    if buggy_level > 0:
        result.ok(f"Buggy level: {buggy_level}")

    # Check owned vehicles
    vehicles = get_user_owned_vehicles(user_id)
    if vehicles:
        result.ok(f"Owned vehicles: {len(vehicles)}")
        for v in vehicles:
            result.ok(f"  {v.get('name', v.get('vehicle_type', '?'))}")
    else:
        result.warn("No vehicles owned - using default rover")

    # Check active expeditions
    active = get_user_active_expeditions(user_id)
    if active:
        result.ok(f"Active expeditions: {len(active)}")
        for exp in active:
            status = exp.get('status', 'unknown')
            result.ok(f"  Expedition {exp['id']}: {status}")
    else:
        result.ok("No active expeditions - player can launch one")

    # Check total expedition count
    with db_cursor() as cur:
        cur.execute("""
            SELECT COUNT(*) as total,
                   COUNT(CASE WHEN status IN ('traveling', 'exploring', 'returning') THEN 1 END) as active,
                   COUNT(CASE WHEN status = 'complete' THEN 1 END) as completed
            FROM pilgrim.expeditions
            WHERE user_id = %s
        """, (user_id,))
        exp_stats = cur.fetchone()

    result.ok(f"Total expeditions: {exp_stats['total']} ({exp_stats['completed']} completed, {exp_stats['active']} in progress)")

    return result


# =============================================================================
# STEP 6: DISCOVERY & EXTRACTION
# =============================================================================
def test_discovery_state(user_id):
    """Test user's discovery inventory and extraction capability"""
    result = TestResult("Discoveries & Extraction")

    from utilities.postgres.core import db_cursor

    # Check discoveries via expeditions
    with db_cursor() as cur:
        cur.execute("""
            SELECT COUNT(*) as total,
                   COUNT(CASE WHEN ed.claimed_by_user = true THEN 1 END) as claimed,
                   COUNT(CASE WHEN ed.claimed_by_user = false THEN 1 END) as pending
            FROM pilgrim.expedition_discoveries ed
            JOIN pilgrim.expeditions e ON ed.expedition_id = e.id
            WHERE e.user_id = %s
        """, (user_id,))
        disc_stats = cur.fetchone()

    total = disc_stats['total']
    claimed = disc_stats['claimed']
    pending = disc_stats['pending']

    if total == 0:
        result.warn("No discoveries yet - player needs to complete an expedition")
    else:
        result.ok(f"Total discoveries: {total}")
        result.ok(f"  Claimed (sharded): {claimed}")
        result.ok(f"  Pending claim: {pending}")

        if pending > 0:
            result.warn(f"{pending} discoveries waiting to be claimed - player can extract for income")

    # Check discovery value
    with db_cursor() as cur:
        cur.execute("""
            SELECT COALESCE(SUM(ed.enhanced_value), 0) as total_value,
                   COALESCE(SUM(CASE WHEN ed.claimed_by_user = false THEN ed.enhanced_value ELSE 0 END), 0) as pending_value
            FROM pilgrim.expedition_discoveries ed
            JOIN pilgrim.expeditions e ON ed.expedition_id = e.id
            WHERE e.user_id = %s
        """, (user_id,))
        values = cur.fetchone()

    total_value = float(values['total_value']) * 10000000
    pending_value = float(values['pending_value']) * 10000000

    if total_value > 0:
        result.ok(f"Total discovery value: {total_value:.0f} shards")
        if pending_value > 0:
            result.ok(f"Pending claim value: {pending_value:.0f} shards (can be claimed)")

    return result


# =============================================================================
# STEP 7: INCOME GENERATION
# =============================================================================
def test_income_generation(user_id):
    """Test solar income accumulation and claim capability"""
    result = TestResult("Income Generation")

    from utilities.infrastructure_utils import calculate_accumulated_income, get_user_infrastructure

    infrastructure = get_user_infrastructure(user_id)
    generators = [i for i in infrastructure if i.get('generates_resource') == 'sepolia' and i.get('status') == 'active']

    if not generators:
        result.warn("No active generators - player needs to build and wait for solar array")
        return result

    # Calculate accumulated income
    income_data = calculate_accumulated_income(user_id)
    accumulated = income_data.get('total_accumulated', 0)

    result.ok(f"Active generators: {len(generators)}")
    for gen in generators:
        rate = gen.get('generation_rate', 0)
        result.ok(f"  {gen.get('structure_name', gen['structure_type'])}: {rate:.1f}/hr")

    result.ok(f"Accumulated income: {accumulated:.1f} shards")
    result.ok(f"All-time generated: {income_data.get('total_all_time', 0):.1f} shards")

    if accumulated > 0:
        result.ok("Income ready to harvest - player can click 'Harvest' on /home")
    else:
        result.warn("No accumulated income yet - generators need time to produce")

    if income_data.get('any_dust_covered'):
        result.warn("Some structures are dust-covered - player should harvest to clear")

    # Check Mars conditions
    try:
        from utilities.mars_environment_utils import get_mars_environment
        conditions = get_mars_environment()
        sol_phase = conditions.get('sol_time', {}).get('phase', 'unknown')
        result.ok(f"Current Mars time: {sol_phase}")
    except Exception:
        result.warn("Could not fetch Mars conditions")

    return result


# =============================================================================
# STEP 8: BALANCE & AFFORDABILITY
# =============================================================================
def test_affordability(user_id):
    """Test what the player can afford to buy"""
    result = TestResult("Affordability Check")

    from utilities.depot_utils import get_live_balance_and_wallet_info
    from config import INFRASTRUCTURE_CATALOG

    balance, wallet_info, primary = get_live_balance_and_wallet_info(user_id)

    result.ok(f"Current balance: {balance:.1f} shards")

    # Check what infrastructure they can afford
    affordable = []
    next_goal = None

    for key, item in INFRASTRUCTURE_CATALOG.items():
        cost = item['cost_sepolia'] * 10000000
        if cost <= balance and cost < 1000000:  # Exclude mega-expensive items
            affordable.append((item['name'], cost))
        elif cost > balance and (next_goal is None or cost < next_goal[1]):
            next_goal = (item['name'], cost)

    if affordable:
        result.ok(f"Can afford {len(affordable)} infrastructure items:")
        for name, cost in sorted(affordable, key=lambda x: x[1])[:5]:
            result.ok(f"  {name}: {cost:.0f} shards")
    else:
        result.warn("Cannot afford any infrastructure - needs more shards")

    if next_goal and next_goal[1] < 10000:
        needed = next_goal[1] - balance
        result.ok(f"Next goal: {next_goal[0]} ({next_goal[1]:.0f} shards, need {needed:.0f} more)")

    return result


# =============================================================================
# MANUAL QA CHECKLIST
# =============================================================================
def print_manual_checklist():
    """Print checklist for manual QA testing"""
    print_header("MANUAL QA CHECKLIST - New Player Experience")

    checklist = """
\033[1m1. FIRST LANDING (/home as new user)\033[0m
   [ ] Page loads without errors
   [ ] Solar Array "Build" button is visible and prominent
   [ ] Build button shows "FREE" or 0 cost
   [ ] Clicking Build shows success toast
   [ ] Balance updates to show welcome bonus (~750 shards)
   [ ] ARIA welcome message appears (optional)

\033[1m2. CREW PAGE (/crew)\033[0m
   [ ] Commander portrait is visible
   [ ] Commander name is displayed
   [ ] Stats grid shows Leadership/Strategy/Exploration/Logistics/Charisma
   [ ] "Transmogrify" option is visible (costs shards)
   [ ] Scientist info is shown

\033[1m3. DEPOT PAGE (/depot)\033[0m
   [ ] Infrastructure section shows available buildings
   [ ] Battery shows as affordable (10 shards)
   [ ] Research Station shows cost (500 shards)
   [ ] "Build" buttons are clickable
   [ ] Built items show in "Your Infrastructure" section
   [ ] Under-construction items show countdown timer

\033[1m4. EXPEDITIONS PAGE (/expeditions)\033[0m
   [ ] Mars map loads with landmarks visible
   [ ] Rover is available (not greyed out)
   [ ] Clicking landmark shows destination info
   [ ] "Launch Expedition" button works
   [ ] Cost breakdown is shown before launch
   [ ] Active expedition shows travel progress

\033[1m5. COLONY PAGE (/colony)\033[0m
   [ ] All owned items display in grid
   [ ] Clicking item opens detail modal
   [ ] Modal shows rich data (stats, dates, values)
   [ ] Discoveries show "Shard It" option
   [ ] Equipment shows current bonuses

\033[1m6. HARVEST FLOW\033[0m
   [ ] After time passes, "Harvest" button appears on /home
   [ ] Clicking Harvest shows amount collected
   [ ] Balance increases by harvested amount
   [ ] Toast confirms successful harvest

\033[1m7. ARIA CHAT\033[0m
   [ ] ARIA orb appears in corner
   [ ] Clicking orb opens chat
   [ ] Typing message gets response
   [ ] Conversation feels helpful for new players

\033[1m8. ERROR HANDLING\033[0m
   [ ] Insufficient funds shows clear message (not "Network error")
   [ ] Network issues show "Please try again" message
   [ ] No console errors during normal flow
"""
    print(checklist)


# =============================================================================
# MAIN
# =============================================================================
def run_all_tests(user_id, dry_run=False):
    """Run all new player tests for a user"""
    print_header(f"NEW PLAYER WALKTHROUGH TEST - User {user_id}")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if dry_run:
        print("\033[93m[DRY RUN - No modifications will be made]\033[0m")

    results = []

    # Run each test
    print_section("Step 1: User Exists")
    results.append(test_user_exists(user_id))

    print_section("Step 2: Onboarding Complete")
    results.append(test_onboarding_complete(user_id))

    print_section("Step 3: Infrastructure State")
    results.append(test_infrastructure_state(user_id))

    print_section("Step 4: Welcome Bonus")
    results.append(test_welcome_bonus(user_id))

    print_section("Step 5: Expedition Capability")
    results.append(test_expedition_capability(user_id))

    print_section("Step 6: Discoveries")
    results.append(test_discovery_state(user_id))

    print_section("Step 7: Income Generation")
    results.append(test_income_generation(user_id))

    print_section("Step 8: Affordability")
    results.append(test_affordability(user_id))

    # Summary
    print_header("SUMMARY")
    total_passed = sum(len(r.passed) for r in results)
    total_failed = sum(len(r.failed) for r in results)
    total_warnings = sum(len(r.warnings) for r in results)

    for r in results:
        print(f"  {r.summary()}")

    print(f"\n\033[1mTotal: {total_passed} passed, {total_failed} failed, {total_warnings} warnings\033[0m")

    if total_failed > 0:
        print("\n\033[91mACTION REQUIRED: Fix failed tests before player can progress\033[0m")
    elif total_warnings > 5:
        print("\n\033[93mNOTE: Many warnings - player may be early in journey\033[0m")
    else:
        print("\n\033[92mPlayer experience looks good!\033[0m")

    return total_failed == 0


def get_test_users():
    """Get list of recent users for testing"""
    from utilities.postgres.core import db_cursor

    with db_cursor() as cur:
        cur.execute("""
            SELECT id, email, given_name, created_at, login_count
            FROM pilgrim.users
            ORDER BY created_at DESC
            LIMIT 10
        """)
        return cur.fetchall()


def main():
    parser = argparse.ArgumentParser(description='New Player Walkthrough Test Harness')
    parser.add_argument('--user', type=int, help='Test specific user ID')
    parser.add_argument('--dry-run', action='store_true', help='Check without modifying')
    parser.add_argument('--checklist', action='store_true', help='Print manual QA checklist')
    parser.add_argument('--list-users', action='store_true', help='List recent users')
    args = parser.parse_args()

    if args.checklist:
        print_manual_checklist()
        return

    if args.list_users:
        print_header("Recent Users")
        users = get_test_users()
        for u in users:
            print(f"  ID {u['id']:4} | {u['email']:35} | {u['given_name'] or '?':15} | logins: {u['login_count']}")
        return

    if not args.user:
        print("Usage: python tools/new_player_walkthrough.py --user USER_ID")
        print("       python tools/new_player_walkthrough.py --list-users")
        print("       python tools/new_player_walkthrough.py --checklist")
        return

    success = run_all_tests(args.user, dry_run=args.dry_run)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
