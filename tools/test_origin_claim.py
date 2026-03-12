#!/usr/bin/env python3
"""
Test script to verify Origin Site claim will work.
Run this BEFORE attempting the actual claim.

Usage: python tools/test_origin_claim.py
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utilities.postgres_utils import db_cursor, get_user_primary_sepolia_wallet
from utilities.signal_utils import get_user_origin_site_eligibility, get_all_origin_sites

# Test for Andy (user_id = 45) claiming Curiosity (site_id = 7)
TEST_USER_ID = 45
TEST_SITE_CODE = 'CURIOSITY'

def test_origin_claim():
    print("\n" + "="*60)
    print("ORIGIN SITE CLAIM PRE-FLIGHT CHECK")
    print("="*60 + "\n")

    errors = []
    warnings = []

    # 1. Check that Curiosity exists and is unclaimed
    print("1. Checking Curiosity site status...")
    with db_cursor() as cur:
        cur.execute("""
            SELECT id, site_code, mission_name, founder_user_id, founder_commander_name,
                   legendary_item_name, legendary_item_flux_prompt
            FROM pilgrim.origin_sites WHERE site_code = %s
        """, (TEST_SITE_CODE,))
        site = cur.fetchone()

    if not site:
        errors.append(f"Site {TEST_SITE_CODE} not found in database!")
    else:
        print(f"   Site ID: {site['id']}")
        print(f"   Mission: {site['mission_name']}")
        print(f"   Founder: {site['founder_user_id']} ({site['founder_commander_name'] or 'UNCLAIMED'})")
        print(f"   Legendary Item: {site['legendary_item_name']}")

        if site['founder_user_id']:
            errors.append(f"Site is already claimed by user {site['founder_user_id']}!")
        else:
            print("   ✅ Site is UNCLAIMED - can be claimed")

        if not site['legendary_item_flux_prompt']:
            warnings.append("Legendary item Flux prompt is not set - image won't generate")
        else:
            print("   ✅ Legendary item Flux prompt is set")

    # 2. Check user has a commander
    print("\n2. Checking user commander...")
    with db_cursor() as cur:
        cur.execute("""
            SELECT commander_name FROM pilgrim.replicate_assets
            WHERE user_id = %s AND asset_type = 'character_image'
            AND commander_name IS NOT NULL AND is_deleted = false
            ORDER BY is_primary_character DESC, created_at DESC LIMIT 1
        """, (TEST_USER_ID,))
        commander = cur.fetchone()

    if not commander or not commander['commander_name']:
        errors.append("User has no commander!")
    else:
        print(f"   Commander: {commander['commander_name']}")
        print("   ✅ Commander found")

    # 3. Check user has wallet
    print("\n3. Checking user wallet...")
    wallet = get_user_primary_sepolia_wallet(TEST_USER_ID)
    if not wallet:
        warnings.append("User has no primary wallet - blockchain tx won't be recorded")
    else:
        print(f"   Wallet: {wallet['wallet_address'][:10]}...")
        print("   ✅ Wallet found")

    # 4. Check user eligibility (expedition within range)
    print("\n4. Checking expedition proximity...")
    eligibility = get_user_origin_site_eligibility(TEST_USER_ID)
    curiosity = next((s for s in eligibility if s['site_code'] == TEST_SITE_CODE), None)

    if not curiosity:
        errors.append("Curiosity not found in eligibility list!")
    else:
        print(f"   Distance to Curiosity: {curiosity.get('distance_km')} km")
        print(f"   Unlock radius: {curiosity.get('unlock_radius_km')} km")
        print(f"   Can claim: {curiosity.get('can_claim')}")

        if curiosity.get('closest_expedition'):
            exp = curiosity['closest_expedition']
            print(f"   Closest expedition ID: {exp.get('id')}")
            print(f"   Closest expedition: {exp.get('name')}")
        else:
            errors.append("No expedition found near Curiosity!")

        if not curiosity.get('can_claim'):
            if curiosity.get('is_claimed'):
                errors.append("Site is already claimed!")
            elif curiosity.get('distance_km') and curiosity.get('distance_km') > curiosity.get('unlock_radius_km', 42):
                errors.append(f"Too far! {curiosity['distance_km']}km > {curiosity['unlock_radius_km']}km radius")
            else:
                errors.append("Cannot claim (unknown reason)")
        else:
            print("   ✅ User CAN claim Curiosity")

    # 5. Check site_claims table exists and has correct columns
    print("\n5. Checking site_claims table structure...")
    with db_cursor() as cur:
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'pilgrim' AND table_name = 'site_claims'
            ORDER BY ordinal_position
        """)
        columns = [row['column_name'] for row in cur.fetchall()]

    required_cols = ['site_type', 'origin_site_id', 'user_id', 'commander_name',
                     'claim_rank', 'claim_tier', 'expedition_id', 'tx_hash', 'sol_number']

    for col in required_cols:
        if col not in columns:
            errors.append(f"site_claims missing column: {col}")

    if all(col in columns for col in required_cols):
        print(f"   Columns: {', '.join(columns[:5])}...")
        print("   ✅ All required columns present")

    # 6. Check no existing claim for this user/site combo
    print("\n6. Checking for existing claims...")
    with db_cursor() as cur:
        cur.execute("""
            SELECT id, claimed_at FROM pilgrim.site_claims
            WHERE origin_site_id = %s AND user_id = %s
        """, (site['id'] if site else 0, TEST_USER_ID))
        existing = cur.fetchone()

    if existing:
        errors.append(f"User already has a claim on this site (claim ID: {existing['id']})")
    else:
        print("   ✅ No existing claim")

    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)

    if errors:
        print("\n❌ ERRORS (must fix before claim):")
        for e in errors:
            print(f"   • {e}")

    if warnings:
        print("\n⚠️  WARNINGS (claim may work but with issues):")
        for w in warnings:
            print(f"   • {w}")

    if not errors:
        print("\n✅ ALL CHECKS PASSED - Ready to claim!")
        print("\nNext step: Deploy code and claim via UI")
        print(f"   ./git_push.sh \"Origin site claim system ready\"")
    else:
        print("\n❌ FIX ERRORS BEFORE CLAIMING")
        return False

    return True


if __name__ == "__main__":
    success = test_origin_claim()
    sys.exit(0 if success else 1)
