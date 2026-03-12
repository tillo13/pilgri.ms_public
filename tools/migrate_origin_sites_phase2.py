#!/usr/bin/env python3
"""
Migration: Add Phase 2 columns to origin_sites for claiming system.

Adds:
- is_lost_signal: Boolean for sites that need decoder (InSight, Beagle-2, Pathfinder)
- unlock_code: The 0x... hex code required to unlock lost sites
- unlock_radius_km: 42km for normal sites, 200km for lost sites
- founder_wallet_prefix: "0x570a" format for Founder display

Run once: python tools/migrate_origin_sites_phase2.py
"""

import sys
import os
import secrets

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utilities.postgres_utils import get_db_connection

# The 3 lost sites that require decoder codes
LOST_SITES = ['INSIGHT', 'BEAGLE-2', 'PATHFINDER']

def generate_unlock_code():
    """Generate a random 0x... hex code (64 chars after 0x)"""
    return '0x' + secrets.token_hex(32)

def run_migration():
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        print("\n" + "="*60)
        print("MIGRATING ORIGIN SITES - Phase 2 Claiming System")
        print("="*60 + "\n")

        # Check if columns already exist
        cur.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'pilgrim'
            AND table_name = 'origin_sites'
            AND column_name IN ('is_lost_signal', 'unlock_code', 'unlock_radius_km', 'founder_wallet_prefix')
        """)
        existing = [row[0] for row in cur.fetchall()]

        # Add columns if they don't exist
        if 'is_lost_signal' not in existing:
            print("Adding is_lost_signal column...")
            cur.execute("ALTER TABLE pilgrim.origin_sites ADD COLUMN is_lost_signal BOOLEAN DEFAULT FALSE")
        else:
            print("   is_lost_signal already exists")

        if 'unlock_code' not in existing:
            print("Adding unlock_code column...")
            cur.execute("ALTER TABLE pilgrim.origin_sites ADD COLUMN unlock_code VARCHAR(66)")
        else:
            print("   unlock_code already exists")

        if 'unlock_radius_km' not in existing:
            print("Adding unlock_radius_km column...")
            cur.execute("ALTER TABLE pilgrim.origin_sites ADD COLUMN unlock_radius_km INTEGER DEFAULT 42")
        else:
            print("   unlock_radius_km already exists")

        if 'founder_wallet_prefix' not in existing:
            print("Adding founder_wallet_prefix column...")
            cur.execute("ALTER TABLE pilgrim.origin_sites ADD COLUMN founder_wallet_prefix VARCHAR(6)")
        else:
            print("   founder_wallet_prefix already exists")

        conn.commit()
        print("\n✅ Columns added/verified")

        # Update lost sites with their codes
        print("\nUpdating lost signal sites...")
        for site_code in LOST_SITES:
            # Check if already has unlock_code
            cur.execute(
                "SELECT unlock_code FROM pilgrim.origin_sites WHERE site_code = %s",
                (site_code,)
            )
            row = cur.fetchone()

            if row and row[0]:
                print(f"   {site_code}: already has unlock code")
            else:
                unlock_code = generate_unlock_code()
                cur.execute("""
                    UPDATE pilgrim.origin_sites
                    SET is_lost_signal = TRUE,
                        unlock_radius_km = 200,
                        unlock_code = %s
                    WHERE site_code = %s
                """, (unlock_code, site_code))
                print(f"   {site_code}: set as lost signal, radius=200km")
                print(f"      Code: {unlock_code[:10]}...{unlock_code[-6:]}")

        conn.commit()

        # Show summary
        print("\n" + "-"*60)
        print("SUMMARY")
        print("-"*60)

        cur.execute("""
            SELECT site_code, is_lost_signal, unlock_radius_km,
                   CASE WHEN unlock_code IS NOT NULL THEN 'YES' ELSE 'NO' END as has_code,
                   CASE WHEN founder_user_id IS NOT NULL THEN founder_commander_name ELSE 'UNCLAIMED' END as founder
            FROM pilgrim.origin_sites
            ORDER BY is_lost_signal DESC, site_code
        """)

        print(f"\n{'SITE':<15} {'LOST?':<7} {'RADIUS':<8} {'CODE?':<6} {'FOUNDER':<20}")
        print("-"*60)
        for row in cur.fetchall():
            code, is_lost, radius, has_code, founder = row
            lost_str = "🔒 YES" if is_lost else "NO"
            print(f"{code:<15} {lost_str:<7} {radius}km     {has_code:<6} {founder:<20}")

        print("\n✅ Migration complete!")
        print("\nNext: Implement /api/signal/origin/claim endpoint")

    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        if conn:
            conn.rollback()
        raise

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

if __name__ == "__main__":
    run_migration()
