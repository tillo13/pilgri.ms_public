#!/usr/bin/env python3
"""
New User Smoke Test - Tests the complete new user onboarding flow

Simulates a brand new user going through:
1. Login/signup (mocked - we test with real DB)
2. Build first FREE infrastructure (solar array)
3. Check harvest/depot
4. View crew
5. Launch first expedition
6. Check colony page

Usage:
    python tools/smoke_test_new_user.py              # Run with test user
    python tools/smoke_test_new_user.py --cleanup    # Delete test user after
    python tools/smoke_test_new_user.py --verbose    # Show detailed output

This catches issues like:
- UnboundLocalError when building free structures
- Missing wallet initialization
- Broken harvest display
- Failed depot loads
- Expedition launch errors for new users
"""
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Test results
tests_run = 0
tests_passed = 0
tests_failed = 0
failures = []

def test(name, verbose=False):
    """Decorator for test functions"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            global tests_run, tests_passed, tests_failed, failures
            tests_run += 1
            try:
                result = func(*args, **kwargs)
                if result is False:
                    raise AssertionError("Test returned False")
                tests_passed += 1
                print(f"  ✅ {name}")
                if verbose and result:
                    print(f"     {result}")
                return result
            except Exception as e:
                tests_failed += 1
                failures.append(f"{name}: {str(e)}")
                print(f"  ❌ {name}: {str(e)}")
                if verbose:
                    import traceback
                    traceback.print_exc()
                return None
        return wrapper
    return decorator


def create_test_user():
    """Create a test user and try to claim an anonymous wallet"""
    from utilities.postgres.core import db_cursor
    from utilities.postgres.wallets import get_random_unclaimed_cache, claim_anonymous_wallet
    import random

    test_email = f"test_new_user_{random.randint(10000, 99999)}@pilgrims.test"

    with db_cursor(commit=True) as cur:
        # Create test user
        cur.execute("""
            INSERT INTO pilgrim.users (email, name, given_name, picture, google_id, locale, created_at, last_login, login_count)
            VALUES (%s, %s, %s, %s, %s, %s, NOW(), NOW(), 1)
            RETURNING id
        """, (test_email, "Test User", "Test", "", f"test_{random.randint(100000, 999999)}", "en"))
        user_id = cur.fetchone()['id']

    # Try to claim an anonymous wallet
    unclaimed = get_random_unclaimed_cache()
    if unclaimed:
        claim_anonymous_wallet(unclaimed['wallet_address'], user_id)
        print(f"Created test user: ID={user_id}, email={test_email}, wallet={unclaimed['wallet_address'][:10]}...")
    else:
        print(f"Created test user: ID={user_id}, email={test_email}, NO WALLET (pool empty - this will test graceful degradation)")

    return user_id, test_email


def cleanup_test_user(user_id):
    """Delete test user and all associated data"""
    from utilities.postgres.core import db_cursor

    with db_cursor(commit=True) as cur:
        # Delete in correct order (foreign key constraints)
        cur.execute("DELETE FROM pilgrim.expedition_discoveries WHERE expedition_id IN (SELECT id FROM pilgrim.expeditions WHERE user_id = %s)", (user_id,))
        cur.execute("DELETE FROM pilgrim.expeditions WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM pilgrim.colony_infrastructure WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM pilgrim.depot_transactions WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM pilgrim.replicate_assets WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM pilgrim.sepolia_assets WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM pilgrim.player_upgrades WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM pilgrim.player_techs WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM pilgrim.users WHERE id = %s", (user_id,))

    print(f"Cleaned up test user {user_id}")


def run_new_user_tests(user_id, verbose=False):
    """Run all new user onboarding tests"""

    print(f"\n{'='*70}")
    print(f"🧪 NEW USER SMOKE TEST")
    print(f"   User ID: {user_id}")
    print(f"{'='*70}\n")

    # Test 1: User has wallet (or gracefully handles no wallet)
    @test("User has wallet or handles missing wallet", verbose)
    def test_wallet():
        from utilities.postgres.wallets import get_user_primary_sepolia_wallet
        wallet = get_user_primary_sepolia_wallet(user_id)
        if wallet:
            assert wallet['wallet_address'], "Wallet exists but has no address"
            return f"Wallet: {wallet['wallet_address'][:10]}..."
        else:
            # No wallet is OK for new users if pool is empty - system should handle gracefully
            return "No wallet (pool empty - system must handle gracefully)"

    wallet_result = test_wallet()

    # Test 2: User can get Mars home coords
    @test("User has Mars home coordinates", verbose)
    def test_mars_home():
        from utilities.postgres.map import get_or_set_user_mars_home
        coords = get_or_set_user_mars_home(user_id)
        assert coords is not None, "No Mars home"
        assert 'latitude' in coords and 'longitude' in coords
        return f"Home: {coords['latitude']:.2f}, {coords['longitude']:.2f}"

    test_mars_home()

    # Test 3: Build FREE solar array (the bug Chloe hit!)
    @test("Build FREE solar array (critical for new users!)", verbose)
    def test_build_solar():
        from utilities.infrastructure_utils import start_construction
        from utilities.postgres.map import get_or_set_user_mars_home
        coords = get_or_set_user_mars_home(user_id)
        result = start_construction(user_id, 'solar_array', coords['latitude'], coords['longitude'])
        assert result['success'], f"Build failed: {result.get('error', 'unknown')}"
        assert 'construction_id' in result, "No construction ID returned"
        assert 'new_balance' in result, "No new_balance in response"
        assert result['new_balance'] >= 0, "new_balance is negative"
        return f"Built solar array, balance: {result['new_balance']}"

    solar_result = test_build_solar()

    # Test 4: Check infrastructure list
    @test("Get user infrastructure list", verbose)
    def test_infrastructure_list():
        from utilities.infrastructure_utils import get_user_infrastructure
        structures = get_user_infrastructure(user_id)
        assert isinstance(structures, list), "Infrastructure not a list"
        assert len(structures) > 0, "No infrastructure found"
        return f"Found {len(structures)} structure(s)"

    test_infrastructure_list()

    # Test 5: Get depot page data (depot UI must work!)
    @test("Load depot page data", verbose)
    def test_depot_page():
        from utilities.depot_utils import get_fast_balance_and_wallet_info
        balance, wallet_addr, _ = get_fast_balance_and_wallet_info(user_id)
        assert balance is not None, "Balance is None"
        assert balance >= 0, "Balance is negative"
        assert wallet_addr, "No wallet address"
        return f"Balance: {balance:.0f} Sepolia"

    test_depot_page()

    # Test 6: Get harvest data (harvest display must work!)
    @test("Load harvest/income data", verbose)
    def test_harvest():
        from utilities.infrastructure_utils import get_user_infrastructure_effects
        effects = get_user_infrastructure_effects(user_id)
        assert isinstance(effects, dict), "Effects not a dict"
        assert 'sepolia_generation_rate' in effects, "No generation rate"
        gen_rate = effects['sepolia_generation_rate']
        return f"Generation: {gen_rate} Sepolia/hr"

    test_harvest()

    # Test 7: Get crew page data
    @test("Load crew page", verbose)
    def test_crew_page():
        from utilities.postgres.users import get_user_scientist
        scientist = get_user_scientist(user_id)
        # New users don't have scientist until auto-assigned, so None is OK
        return f"Scientist: {scientist['scientist_name'] if scientist else 'None (will auto-assign)'}"

    test_crew_page()

    # Test 8: Get colony page data
    @test("Load colony page", verbose)
    def test_colony_page():
        from utilities.page_data_utils import get_colony_page_data_cached
        from flask import Flask
        app = Flask(__name__)
        with app.app_context():
            class MockAuth:
                def get_current_user(self):
                    return {'email': 'test@test.com', 'name': 'Test'}
            data = get_colony_page_data_cached(user_id, MockAuth())
            assert isinstance(data, dict), "Colony data not a dict"
            assert 'user' in data, "No user in colony data"
            return "Colony page loads"

    test_colony_page()

    # Test 9: Get expeditions page data
    @test("Load expeditions page", verbose)
    def test_expeditions_page():
        from utilities.expedition_utils import get_expeditions_page_data
        data = get_expeditions_page_data(user_id)
        assert isinstance(data, dict), "Expeditions data not a dict"
        assert 'landmarks' in data, "No landmarks"
        assert 'active_expeditions' in data, "No active_expeditions"
        return f"Landmarks: {len(data['landmarks'])}, Active: {len(data['active_expeditions'])}"

    test_expeditions_page()

    # Test 10: Check upgrade effects (depot tabs depend on this)
    @test("Get upgrade effects", verbose)
    def test_upgrade_effects():
        from utilities.upgrades_utils import get_user_upgrade_effects
        effects = get_user_upgrade_effects(user_id)
        assert isinstance(effects, dict), "Effects not a dict"
        # New users have no upgrades, so empty dict is fine
        return f"Effects: {len(effects)} upgrades"

    test_upgrade_effects()

    # Test 11: Get owned vehicles
    @test("Get owned vehicles", verbose)
    def test_owned_vehicles():
        from utilities.upgrades_utils import get_user_owned_vehicles
        vehicles = get_user_owned_vehicles(user_id)
        assert isinstance(vehicles, list), "Vehicles not a list"
        # New users should have at least 1 free rover
        assert len(vehicles) > 0, "No vehicles found - new users should have free rover!"
        return f"Vehicles: {len(vehicles)}"

    test_owned_vehicles()


def main():
    parser = argparse.ArgumentParser(description='New User Smoke Test')
    parser.add_argument('--cleanup', action='store_true', help='Delete test user after tests')
    parser.add_argument('--verbose', '-v', action='store_true', help='Show detailed output')
    parser.add_argument('--user-id', type=int, help='Use existing user ID instead of creating new one')
    args = parser.parse_args()

    user_id = None
    created_user = False

    try:
        if args.user_id:
            user_id = args.user_id
            print(f"Using existing user ID: {user_id}")
        else:
            user_id, email = create_test_user()
            created_user = True

        run_new_user_tests(user_id, verbose=args.verbose)

        # Summary
        print(f"\n{'='*70}")
        print(f"📊 RESULTS")
        print(f"{'='*70}")
        print(f"  ✅ Passed:  {tests_passed}")
        print(f"  ❌ Failed:  {tests_failed}")
        print(f"  📝 Total:   {tests_run}")

        if failures:
            print(f"\n❌ FAILURES:")
            for failure in failures:
                print(f"   • {failure}")

        print(f"\n{'='*70}")

        if tests_failed > 0:
            print(f"🔴 SOME TESTS FAILED - New user experience is broken!\n")
            sys.exit(1)
        else:
            print(f"✅ ALL TESTS PASSED - New user experience is working!\n")
            sys.exit(0)

    finally:
        if created_user and args.cleanup and user_id:
            cleanup_test_user(user_id)


if __name__ == '__main__':
    main()
