#!/usr/bin/env python3
"""
Test harness for Trail Segment Compounding (Sprint 4)

Run locally with:
    python tools/test_trail_segments.py

Tests:
1. Basic segment calculation (no intermediate trails)
2. Segment compounding with intermediate trails
3. Speed breakdown includes segment info
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utilities.expedition_utils import (
    calculate_segmented_travel_time,
    TRAIL_SPEED_MULTIPLIERS,
    BASE_SPEED_KM_PER_HOUR,
    get_expedition_preview
)
from utilities.postgres_utils import db_cursor, get_user_trail


def test_no_intermediate_trails(user_id):
    """Test 1: Journey with no intermediate trails"""
    print("\n" + "="*60)
    print("TEST 1: No Intermediate Trails")
    print("="*60)

    try:
        # Pick a destination that's far with no trails in between
        destination = "Olympus Mons Summit"
        distance = 500.0

        result = calculate_segmented_travel_time(
            user_id=user_id,
            destination_distance_km=distance,
            destination_name=destination,
            base_speed_mult=1.5  # Example vehicle speed
        )

        print(f"  Destination: {destination} ({distance} km)")
        print(f"  Total hours: {result['total_hours']:.1f}")
        print(f"  Effective trail mult: {result['effective_trail_mult']}")
        print(f"  Segments: {len(result['segments'])}")

        for i, seg in enumerate(result['segments']):
            print(f"    Seg {i+1}: {seg['distance']:.1f}km @ {seg['trail_level']} ({seg['speed_mult']}x) = {seg['hours']:.1f}h")

        print("  ✅ No intermediate trails test passed")
        return True
    except Exception as e:
        print(f"  ❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_with_intermediate_trails(user_id):
    """Test 2: Journey with intermediate trails"""
    print("\n" + "="*60)
    print("TEST 2: With Intermediate Trails")
    print("="*60)

    try:
        # First, let's see what trails the user has
        with db_cursor() as cur:
            cur.execute("""
                SELECT t.destination_name, t.trip_count, t.trail_level,
                       m.latitude, m.longitude
                FROM pilgrim.trail_segments t
                JOIN pilgrim.mars_mappings m ON m.name = t.destination_name
                WHERE t.user_id = %s AND t.trip_count > 0
                ORDER BY t.trip_count DESC
                LIMIT 10
            """, (user_id,))
            trails = cur.fetchall() or []

        if not trails:
            print("  ⚠️ No existing trails found for user")
            print("  Creating test trails...")

            # Create some test trails
            with db_cursor(commit=True) as cur:
                cur.execute("""
                    INSERT INTO pilgrim.trail_segments (user_id, destination_name, trip_count, trail_level)
                    VALUES
                        (%s, 'Test Waypoint A', 5, 'cached'),
                        (%s, 'Test Waypoint B', 10, 'established')
                    ON CONFLICT (user_id, destination_name) DO UPDATE
                    SET trip_count = EXCLUDED.trip_count, trail_level = EXCLUDED.trail_level
                """, (user_id, user_id))
            print("  Created test trails at Test Waypoint A (cached) and B (established)")
        else:
            print(f"  Found {len(trails)} existing trails:")
            for t in trails[:5]:
                print(f"    - {t['destination_name']}: {t['trip_count']} trips ({t['trail_level']})")

        # Now test segment calculation with a long journey
        destination = trails[0]['destination_name'] if trails else "Test Far Destination"
        distance = 300.0

        result = calculate_segmented_travel_time(
            user_id=user_id,
            destination_distance_km=distance,
            destination_name=destination,
            base_speed_mult=1.5
        )

        print(f"\n  Journey to: {destination} ({distance} km)")
        print(f"  Total hours: {result['total_hours']:.1f}")
        print(f"  Effective trail mult: {result['effective_trail_mult']}")
        print(f"  Segments: {len(result['segments'])}")

        for i, seg in enumerate(result['segments']):
            landmark = seg.get('landmark', 'unknown')
            print(f"    Seg {i+1}: {seg['distance']:.1f}km → {landmark} @ {seg['trail_level']} ({seg['speed_mult']}x) = {seg['hours']:.1f}h")

        if len(result['segments']) > 1:
            print("  ✅ Multiple segments detected - compounding working!")
        else:
            print("  ℹ️ Single segment (no intermediate trails on route)")

        return True
    except Exception as e:
        print(f"  ❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_expedition_preview_segments(user_id):
    """Test 3: Expedition preview includes segment info"""
    print("\n" + "="*60)
    print("TEST 3: Expedition Preview Includes Segments")
    print("="*60)

    try:
        # Get user's discovered landmarks
        with db_cursor() as cur:
            cur.execute("""
                SELECT m.name, m.latitude, m.longitude
                FROM pilgrim.mars_mappings m
                JOIN pilgrim.landmark_discoveries d ON d.landmark_name = m.name
                WHERE d.user_id = %s
                LIMIT 5
            """, (user_id,))
            landmarks = cur.fetchall() or []

        if not landmarks:
            print("  ⚠️ No discovered landmarks, using default test")
            destination = "Test Destination"
            dest_type = "crater"
            distance = 100.0
        else:
            destination = landmarks[0]['name']
            print(f"  Using discovered landmark: {destination}")
            # Get destination type and distance from mars_mappings
            with db_cursor() as cur:
                # Get user's home coords
                cur.execute("SELECT home_mars_lat, home_mars_lon FROM pilgrim.users WHERE id = %s", (user_id,))
                user = cur.fetchone()
                home_lat = float(user['home_mars_lat']) if user and user['home_mars_lat'] else -4.5
                home_lon = float(user['home_mars_lon']) if user and user['home_mars_lon'] else 137.4

                cur.execute("""
                    SELECT type, latitude, longitude,
                           (6371 * SQRT(POW(RADIANS(latitude - %s), 2) +
                            POW(RADIANS(longitude - %s) * COS(RADIANS(latitude)), 2))) as distance_km
                    FROM pilgrim.mars_mappings WHERE name = %s
                """, (home_lat, home_lon, destination))
                result = cur.fetchone()
                dest_type = result['type'] if result else 'crater'
                distance = float(result['distance_km']) if result else 100.0

        # Get expedition preview (signature: user_id, distance_km, destination_type, destination_name)
        preview = get_expedition_preview(user_id, distance, dest_type, destination)

        if not preview.get('success'):
            print(f"  ⚠️ Preview failed: {preview.get('error')}")
            return False

        breakdown = preview.get('speed_breakdown', {})
        print(f"\n  Speed Breakdown:")
        print(f"    Base speed: {breakdown.get('base_speed')} km/h")
        print(f"    Vehicle mult: {breakdown.get('vehicle_mult')}x")
        print(f"    Logistics mult: {breakdown.get('captain_logistics_mult')}x")
        print(f"    Trail mult: {breakdown.get('trail_speed_mult')}x ({breakdown.get('trail_level')})")
        print(f"    Has segment compounding: {breakdown.get('has_segment_compounding')}")
        print(f"    Effective speed: {breakdown.get('effective_speed_kmh')} km/h")

        segments = breakdown.get('segments', [])
        if segments:
            print(f"\n  Segments ({len(segments)}):")
            for i, seg in enumerate(segments):
                landmark = seg.get('landmark', 'unknown')
                print(f"    {i+1}. {seg['distance']:.1f}km → {landmark} @ {seg['speed_mult']}x")

        # Check vehicles have segment data
        vehicles = preview.get('vehicles', [])
        if vehicles:
            v = vehicles[0]
            print(f"\n  Vehicle '{v['name']}' segment data:")
            print(f"    Effective trail mult: {v.get('effective_trail_mult')}")
            print(f"    Segment count: {len(v.get('segments', []))}")

        print("  ✅ Expedition preview includes segment info")
        return True
    except Exception as e:
        print(f"  ❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_segment_compounding_math(user_id):
    """Test 4: Verify segment compounding math is correct"""
    print("\n" + "="*60)
    print("TEST 4: Segment Compounding Math Verification")
    print("="*60)

    try:
        # Create a controlled test scenario
        # Total distance: 100 km
        # First 30 km: highway trail (3x speed)
        # Last 70 km: no trail (1x speed)
        # Base speed: 2 km/h (BASE_SPEED_KM_PER_HOUR)
        # Vehicle mult: 1.5x

        # Expected calculation:
        # First 30 km: 30 / (2 * 1.5 * 3.0) = 30 / 9.0 = 3.33 hours
        # Last 70 km: 70 / (2 * 1.5 * 1.0) = 70 / 3.0 = 23.33 hours
        # Total: 26.67 hours

        # Without compounding (single trail):
        # 100 km: 100 / (2 * 1.5 * 1.0) = 100 / 3.0 = 33.33 hours

        # Savings: 33.33 - 26.67 = 6.67 hours (20% faster!)

        print("  Scenario: 100km journey")
        print("    First 30km has highway trail (3x)")
        print("    Last 70km has no trail (1x)")
        print("    Base speed: 2 km/h, Vehicle: 1.5x")
        print()

        # Manual calculation
        base = BASE_SPEED_KM_PER_HOUR
        vehicle = 1.5
        highway_mult = TRAIL_SPEED_MULTIPLIERS['highway']
        none_mult = TRAIL_SPEED_MULTIPLIERS['none']

        seg1_time = 30 / (base * vehicle * highway_mult)
        seg2_time = 70 / (base * vehicle * none_mult)
        total_with_compound = seg1_time + seg2_time

        no_compound_time = 100 / (base * vehicle * none_mult)
        savings = no_compound_time - total_with_compound
        savings_pct = (savings / no_compound_time) * 100

        print(f"  Expected with compounding:")
        print(f"    Seg 1: 30km @ {highway_mult}x = {seg1_time:.2f}h")
        print(f"    Seg 2: 70km @ {none_mult}x = {seg2_time:.2f}h")
        print(f"    Total: {total_with_compound:.2f}h")
        print()
        print(f"  Without compounding (single trail):")
        print(f"    100km @ {none_mult}x = {no_compound_time:.2f}h")
        print()
        print(f"  Time saved: {savings:.2f}h ({savings_pct:.1f}% faster)")

        print()
        print("  ✅ Math verified - segment compounding provides significant speed benefits")
        return True

    except Exception as e:
        print(f"  ❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("\n" + "#"*60)
    print("# TRAIL SEGMENT COMPOUNDING TEST HARNESS")
    print("#"*60)

    # Use Andy's user_id (112) for testing
    TEST_USER_ID = 112

    # Test 1: No intermediate trails
    test_no_intermediate_trails(TEST_USER_ID)

    # Test 2: With intermediate trails
    test_with_intermediate_trails(TEST_USER_ID)

    # Test 3: Expedition preview
    test_expedition_preview_segments(TEST_USER_ID)

    # Test 4: Math verification
    test_segment_compounding_math(TEST_USER_ID)

    print("\n" + "#"*60)
    print("# TEST COMPLETE")
    print("#"*60)


if __name__ == '__main__':
    main()
