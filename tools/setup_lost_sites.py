#!/usr/bin/env python3
"""
Setup Lost Signal Sites - Mark crashed/failed missions as Lost Sites

Lost Sites require the decoder on /signal to unlock before claiming.
They have a larger detection radius (200km vs 42km for Origin Sites).
Each has a unique unlock_code that must be decoded.
"""

import sys
import os
import hashlib

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utilities.postgres.core import db_cursor
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Lost Sites are the crashed/failed missions - mysteries to decode
# Only 3 sites (must be within 42km like Origin Sites to see cyan dot)
LOST_SITES = {
    'MARS-3': {
        'unlock_code': '0x4d41525333313937314465633230736563732d34352d313538',  # MARS31971Dec20secs-45-158 (hex)
        'aria_hint': "Twenty seconds of contact, then silence. December 1971. So close..."
    },
    'BEAGLE-2': {
        'unlock_code': '0x424541474c45324368726973746d6173323030332d31312d3930',  # BEAGLE2Christmas2003-11-90 (hex)
        'aria_hint': "A Christmas gift that never opened. 2003. It's still there, waiting."
    },
    'SCHIAPARELLI': {
        'unlock_code': '0x534348494150415245204c4c49323031362d322d362d6572726f72',  # SCHIAPARELLI2016-2-6-error (hex)
        'aria_hint': "The computer thought it had landed. It hadn't. 2016. A tragic miscalculation."
    }
}


def setup_lost_sites():
    """Mark crashed/failed missions as Lost Signal sites"""
    try:
        with db_cursor(commit=True) as cur:
            updated = 0

            for site_code, config in LOST_SITES.items():
                cur.execute("""
                    UPDATE pilgrim.origin_sites
                    SET is_lost_signal = TRUE,
                        unlock_radius_km = 200,
                        unlock_code = %s
                    WHERE site_code = %s
                    RETURNING id, mission_name
                """, (config['unlock_code'], site_code))

                result = cur.fetchone()
                if result:
                    logger.info(f"✅ {site_code}: {result['mission_name']} marked as Lost Signal")
                    updated += 1
                else:
                    logger.warning(f"⚠️  {site_code}: Not found in database")

            logger.info(f"\n📊 Updated {updated} Lost Signal sites")
            return updated

    except Exception as e:
        logger.error(f"❌ Failed to setup Lost Sites: {e}")
        raise


def list_lost_sites():
    """Show current Lost Signal sites"""
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT site_code, mission_name, mission_year, mission_status,
                       is_lost_signal, unlock_radius_km, unlock_code,
                       founder_commander_name
                FROM pilgrim.origin_sites
                WHERE is_lost_signal = TRUE OR mission_status IN ('crashed', 'failed', 'lost')
                ORDER BY mission_year
            """)

            print("\n" + "="*90)
            print("LOST SIGNAL SITES - Require Decoder to Unlock")
            print("="*90)
            print(f"{'CODE':<15} {'MISSION':<25} {'YEAR':<6} {'STATUS':<10} {'LOST?':<6} {'RADIUS':<8} {'FOUNDER':<15}")
            print("-"*90)

            for row in cur.fetchall():
                is_lost = "✅" if row['is_lost_signal'] else "❌"
                radius = row['unlock_radius_km'] or 42
                founder = row['founder_commander_name'] or "UNCLAIMED"
                print(f"{row['site_code']:<15} {row['mission_name']:<25} {row['mission_year']:<6} {row['mission_status']:<10} {is_lost:<6} {radius}km    {founder:<15}")

            print("="*90)

    except Exception as e:
        logger.error(f"Error listing sites: {e}")


def generate_unlock_codes():
    """Helper to generate hex codes for Lost Sites (for reference)"""
    print("\nGenerated unlock codes for Lost Sites:")
    print("-"*60)

    codes = [
        ('MARS-2', 'MARS21971Nov19-45-47-crash'),
        ('MARS-3', 'MARS31971Dec20secs-45-158'),
        ('BEAGLE-2', 'BEAGLE2Christmas2003-11-90'),
        ('SCHIAPARELLI', 'SCHIAPARELLI2016-2-6-error'),
    ]

    for site, plaintext in codes:
        hex_code = '0x' + plaintext.encode().hex()
        print(f"{site}: {plaintext}")
        print(f"   → {hex_code}\n")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Setup Lost Signal Sites')
    parser.add_argument('--setup', action='store_true', help='Mark crashed missions as Lost Sites')
    parser.add_argument('--list', action='store_true', help='List current Lost Signal sites')
    parser.add_argument('--codes', action='store_true', help='Show unlock code generation')
    args = parser.parse_args()

    if args.setup:
        print("\n" + "="*60)
        print("SETTING UP LOST SIGNAL SITES")
        print("="*60 + "\n")
        setup_lost_sites()
        print("\n✅ Lost Sites configured!")
        print("They will appear as cyan dots within 200km of expeditions.")
    elif args.list:
        list_lost_sites()
    elif args.codes:
        generate_unlock_codes()
    else:
        parser.print_help()
        print("\n💡 Quick start: python tools/setup_lost_sites.py --setup")
