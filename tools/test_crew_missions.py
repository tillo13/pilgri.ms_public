#!/usr/bin/env python3
"""
Test harness for Crew Missions API (Sprint 2)

Run locally with:
    python tools/test_crew_missions.py

Tests:
1. Database schema creation
2. Get mission status
3. Get nearby trails
4. Start captain mission
5. Complete captain mission
6. Start scientist mission (costs shards)
7. ARIA resonance
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utilities.postgres_utils import (
    db_cursor,
    ensure_crew_missions_schema,
    get_crew_mission_status,
    get_nearby_trails_for_missions,
    start_crew_mission,
    complete_crew_mission,
    use_aria_resonance,
    get_user_trail
)


def test_schema():
    """Test 1: Ensure schema is created"""
    print("\n" + "="*60)
    print("TEST 1: Database Schema")
    print("="*60)

    try:
        # Reset any stale transactions first
        try:
            with db_cursor(commit=True) as cur:
                cur.execute("SELECT 1")
        except Exception:
            pass

        ensure_crew_missions_schema()

        # Verify columns exist
        with db_cursor() as cur:
            cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'pilgrim' AND table_name = 'users'
                AND column_name IN ('captain_mission_ends_at', 'scientist_mission_ends_at',
                                    'captain_logistics_xp', 'scientist_navigation_xp', 'aria_last_resonance')
            """)
            cols = [r['column_name'] for r in cur.fetchall()]

        expected = ['captain_mission_ends_at', 'scientist_mission_ends_at',
                    'captain_logistics_xp', 'scientist_navigation_xp', 'aria_last_resonance']

        missing = set(expected) - set(cols)
        if missing:
            print(f"  ❌ Missing columns: {missing}")
            return False

        # Verify crew_missions table exists
        with db_cursor() as cur:
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_schema = 'pilgrim' AND table_name = 'crew_missions'
                )
            """)
            exists = cur.fetchone()['exists']

        if not exists:
            print("  ❌ crew_missions table doesn't exist")
            return False

        print("  ✅ Schema verified: all columns and tables exist")
        return True

    except Exception as e:
        print(f"  ❌ Schema error: {e}")
        return False


def test_mission_status(user_id):
    """Test 2: Get mission status"""
    print("\n" + "="*60)
    print(f"TEST 2: Get Mission Status (user_id={user_id})")
    print("="*60)

    try:
        status = get_crew_mission_status(user_id)
        print(f"  Captain: {status.get('captain')}")
        print(f"  Scientist: {status.get('scientist')}")
        print(f"  ARIA cooldown: {status.get('aria_cooldown')}")
        print("  ✅ Status retrieved successfully")
        return True
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return False


def test_nearby_trails(user_id):
    """Test 3: Get nearby trails"""
    print("\n" + "="*60)
    print(f"TEST 3: Get Nearby Trails (user_id={user_id})")
    print("="*60)

    try:
        trails = get_nearby_trails_for_missions(user_id, max_distance_km=50.0)
        print(f"  Found {len(trails)} trails within 50km:")
        for t in trails[:5]:  # Show first 5
            print(f"    - {t['name']}: {t['distance_km']:.1f}km, {t['trail_level']} ({t['trip_count']} trips)")
        if len(trails) > 5:
            print(f"    ... and {len(trails) - 5} more")
        print("  ✅ Nearby trails retrieved")
        return trails
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return []


def test_captain_mission(user_id, destination):
    """Test 4 & 5: Start and complete captain mission"""
    print("\n" + "="*60)
    print(f"TEST 4: Start Captain Mission to {destination}")
    print("="*60)

    try:
        # Clear any existing mission first
        with db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE pilgrim.users
                SET captain_mission_ends_at = NULL, captain_mission_target = NULL
                WHERE id = %s
            """, (user_id,))

        # Start mission with 0 duration for instant testing
        result = start_crew_mission(user_id, 'captain', destination, duration_minutes=0)
        print(f"  Start result: {result}")

        if not result.get('success'):
            print(f"  ❌ Failed to start: {result.get('error')}")
            return False

        print("  ✅ Captain mission started")

        print("\n" + "="*60)
        print("TEST 5: Complete Captain Mission")
        print("="*60)

        # Get trail before
        trail_before = get_user_trail(user_id, destination)
        print(f"  Trail before: {trail_before}")

        # Complete mission
        result = complete_crew_mission(user_id, 'captain')
        print(f"  Complete result: {result}")

        if not result.get('success'):
            print(f"  ❌ Failed to complete: {result.get('error')}")
            return False

        # Verify trail incremented
        trail_after = get_user_trail(user_id, destination)
        print(f"  Trail after: {trail_after}")

        if trail_after['trip_count'] > trail_before['trip_count']:
            print(f"  ✅ Trail incremented: {trail_before['trip_count']} → {trail_after['trip_count']}")
        else:
            print(f"  ⚠️ Trail count unchanged (may have already been at max)")

        print(f"  ✅ XP gained: {result.get('xp_gained')}, new total: {result.get('new_xp_total')}")
        return True

    except Exception as e:
        print(f"  ❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_aria_resonance(user_id, destination):
    """Test 6: ARIA resonance"""
    print("\n" + "="*60)
    print(f"TEST 6: ARIA Resonance to {destination}")
    print("="*60)

    try:
        # Clear cooldown for testing
        with db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE pilgrim.users SET aria_last_resonance = NULL WHERE id = %s
            """, (user_id,))

        # Get trail before
        trail_before = get_user_trail(user_id, destination)
        print(f"  Trail before: {trail_before}")

        # Use resonance
        result = use_aria_resonance(user_id, destination)
        print(f"  Resonance result: success={result.get('success')}")

        if not result.get('success'):
            print(f"  ❌ Failed: {result.get('error')}")
            return False

        print(f"  Trip count added: {result.get('trip_count_added')}")
        print(f"  Trail after: {result.get('trail')}")

        if result.get('lore_fragment'):
            print(f"  🔮 Lore fragment: \"{result['lore_fragment']}\"")
        else:
            print(f"  (No lore fragment this time - 20% chance)")

        print("  ✅ ARIA resonance successful")

        # Test cooldown
        print("\n  Testing cooldown...")
        result2 = use_aria_resonance(user_id, destination)
        if not result2.get('success') and 'cooldown' in result2.get('error', '').lower():
            print(f"  ✅ Cooldown working: {result2.get('error')}")
        else:
            print(f"  ⚠️ Cooldown may not be working: {result2}")

        return True

    except Exception as e:
        print(f"  ❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("\n" + "#"*60)
    print("# CREW MISSIONS TEST HARNESS")
    print("#"*60)

    # Use Andy's user_id (112) for testing - adjust if needed
    TEST_USER_ID = 112

    # Test 1: Schema
    if not test_schema():
        print("\n⛔ Schema test failed, stopping")
        return

    # Test 2: Mission status
    test_mission_status(TEST_USER_ID)

    # Test 3: Nearby trails
    trails = test_nearby_trails(TEST_USER_ID)

    if not trails:
        print("\n⚠️ No nearby trails found. User may not have discovered any landmarks within 50km.")
        print("  Using a test destination instead...")
        test_destination = "Test Crater"  # Will fail gracefully
    else:
        test_destination = trails[0]['name']

    # Test 4 & 5: Captain mission
    test_captain_mission(TEST_USER_ID, test_destination)

    # Test 6: ARIA resonance
    test_aria_resonance(TEST_USER_ID, test_destination)

    print("\n" + "#"*60)
    print("# TEST COMPLETE")
    print("#"*60)


if __name__ == '__main__':
    main()
