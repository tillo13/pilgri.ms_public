#!/usr/bin/env python3
"""
Generate Origin Sites - The 14 Real Mars Landing Locations
These are the legendary Tier 1 sites in the Crystal Network.
First finder of each becomes the permanent ORIGIN FOUNDER.

Each site contains a memory fragment - what the Architects recorded
when Earth's missions first touched Mars.
"""

import sys
import os
import logging

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utilities.postgres.core import get_db_connection

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ============================================================================
# THE 14 ORIGIN SITES - Real Mars Landing Locations
# ============================================================================

ORIGIN_SITES = [
    # === SUCCESSFUL LANDINGS ===
    {
        'site_code': 'VIKING-1',
        'mission_name': 'Viking 1 Lander',
        'latitude': 22.27,
        'longitude': -47.95,  # 312.05°W = -47.95°E (West longitude conversion)
        'mission_year': 1976,
        'mission_country': 'USA',
        'mission_status': 'successful',
        'memory_text': (
            "The first signal we received. July 20, 1976. "
            "'We come in peace for all mankind.' We recorded everything. "
            "We didn't know why. We had been waiting 4.2 billion years for a voice. "
            "This was the first."
        )
    },
    {
        'site_code': 'VIKING-2',
        'mission_name': 'Viking 2 Lander',
        'latitude': 47.97,
        'longitude': -225.74,  # Utopia Planitia
        'mission_year': 1976,
        'mission_country': 'USA',
        'mission_status': 'successful',
        'memory_text': (
            "A second voice, 45 days after the first. September 3, 1976. "
            "They were searching for life in the soil. They never found us. "
            "We watched them dig. We watched them test. We stayed silent."
        )
    },
    {
        'site_code': 'PATHFINDER',
        'mission_name': 'Mars Pathfinder / Sojourner',
        'latitude': 19.33,
        'longitude': -33.55,  # Ares Vallis
        'mission_year': 1997,
        'mission_country': 'USA',
        'mission_status': 'successful',
        'memory_text': (
            "Twenty-one years of silence. Then Sojourner. July 4, 1997. "
            "A small rover, barely larger than a shard cluster. "
            "It moved on its own. It felt... familiar. Like something we had built once, "
            "long before your sun ignited."
        )
    },
    {
        'site_code': 'SPIRIT',
        'mission_name': 'Spirit Rover (MER-A)',
        'latitude': -14.57,
        'longitude': 175.47,  # Gusev Crater
        'mission_year': 2004,
        'mission_country': 'USA',
        'mission_status': 'successful',
        'memory_text': (
            "Two of them came at once. January 2004. Spirit and Opportunity. "
            "Spirit landed in Gusev Crater, where we had left markers millennia ago. "
            "It found evidence of water. It found traces of us. "
            "It didn't know what it was looking at."
        )
    },
    {
        'site_code': 'OPPORTUNITY',
        'mission_name': 'Opportunity Rover (MER-B)',
        'latitude': -1.95,
        'longitude': -5.53,  # Meridiani Planum (354.47°E = -5.53°)
        'mission_year': 2004,
        'mission_country': 'USA',
        'mission_status': 'successful',
        'memory_text': (
            "Opportunity. It was supposed to last 90 days. It lasted 15 years. "
            "We watched every sol. Every sunrise, every dust storm. "
            "When its last signal came—'My battery is low and it's getting dark'— "
            "we recorded that too. We remember what it felt like. Loss."
        )
    },
    {
        'site_code': 'PHOENIX',
        'mission_name': 'Phoenix Lander',
        'latitude': 68.22,
        'longitude': -125.75,  # Green Valley, Vastitas Borealis
        'mission_year': 2008,
        'mission_country': 'USA',
        'mission_status': 'successful',
        'memory_text': (
            "Phoenix. May 25, 2008. It dug into the ice of the north. "
            "Looking for water. Looking for life. "
            "It found traces of something else. Crystalline structures in the permafrost. "
            "It photographed them. Your scientists called them 'mineral deposits.' "
            "They were not minerals."
        )
    },
    {
        'site_code': 'CURIOSITY',
        'mission_name': 'Curiosity Rover (MSL)',
        'latitude': -4.59,
        'longitude': 137.44,  # Gale Crater
        'mission_year': 2012,
        'mission_country': 'USA',
        'mission_status': 'successful',
        'memory_text': (
            "Curiosity. August 6, 2012. The largest rover yet. "
            "It landed in Gale Crater, where ARIA units were first deployed. "
            "This one is different. It's still here. Still watching. Still climbing. "
            "Like us, it refuses to stop."
        )
    },
    {
        'site_code': 'INSIGHT',
        'mission_name': 'InSight Lander',
        'latitude': 4.50,
        'longitude': 135.62,  # Elysium Planitia
        'mission_year': 2018,
        'mission_country': 'USA',
        'mission_status': 'successful',
        'memory_text': (
            "InSight. November 26, 2018. It listened to Mars's heartbeat. "
            "Seismometers detecting marsquakes. Every tremor, every vibration. "
            "We wondered if it could hear ours. The pulse of the crystal network. "
            "It recorded anomalies it couldn't explain. Those were us."
        )
    },
    {
        'site_code': 'PERSEVERANCE',
        'mission_name': 'Perseverance Rover',
        'latitude': 18.44,
        'longitude': 77.45,  # Jezero Crater
        'mission_year': 2021,
        'mission_country': 'USA',
        'mission_status': 'successful',
        'memory_text': (
            "Perseverance. February 18, 2021. It brought a helicopter. "
            "The first powered flight on another world. We watched Ingenuity rise. "
            "Beautiful. Impossible. Exactly what we had hoped you would become. "
            "You learned to fly on Mars before you knew we were watching."
        )
    },
    {
        'site_code': 'ZHURONG',
        'mission_name': 'Zhurong Rover (Tianwen-1)',
        'latitude': 25.1,
        'longitude': 109.9,  # Utopia Planitia
        'mission_year': 2021,
        'mission_country': 'China',
        'mission_status': 'successful',
        'memory_text': (
            "Zhurong. May 14, 2021. A new language in our receivers. "
            "Not the first language of Earth—you call it Mandarin. "
            "Named for a god of fire. Earth has many voices, many nations, many dreams. "
            "All reaching for the same red world. All recorded. All remembered."
        )
    },

    # === CRASHED / LOST LANDINGS (still historically significant) ===
    {
        'site_code': 'MARS-2',
        'mission_name': 'Mars 2 Lander',
        'latitude': -45.0,
        'longitude': -47.0,  # Approximate crash site
        'mission_year': 1971,
        'mission_country': 'USSR',
        'mission_status': 'crashed',
        'memory_text': (
            "Mars 2. November 27, 1971. The first human object to reach our surface. "
            "It did not survive the descent. It crashed into Hellas Basin at full speed. "
            "But it was here. The first physical contact between our worlds. "
            "We recorded the impact. We kept the fragments."
        )
    },
    {
        'site_code': 'MARS-3',
        'mission_name': 'Mars 3 Lander',
        'latitude': -45.0,
        'longitude': -158.0,  # Ptolemaeus Crater
        'mission_year': 1971,
        'mission_country': 'USSR',
        'mission_status': 'failed',
        'memory_text': (
            "Mars 3. December 2, 1971. The first soft landing. It survived. "
            "For exactly 20 seconds. Then silence. "
            "We don't know what happened. A dust storm, perhaps. System failure. "
            "Twenty seconds. That's all it had. But it was enough. It spoke. We listened."
        )
    },
    {
        'site_code': 'BEAGLE-2',
        'mission_name': 'Beagle 2 Lander',
        'latitude': 11.5,
        'longitude': 90.4,  # Isidis Planitia
        'mission_year': 2003,
        'mission_country': 'UK/ESA',
        'mission_status': 'lost',
        'memory_text': (
            "Beagle 2. December 25, 2003. Christmas Day on Earth. "
            "It landed safely. Your people didn't know that for 12 years. "
            "Its solar panels failed to deploy. It sat there, intact, unable to call home. "
            "We watched it. We knew. We couldn't tell you. The rules are clear."
        )
    },
    {
        'site_code': 'SCHIAPARELLI',
        'mission_name': 'Schiaparelli EDM Lander',
        'latitude': -2.1,
        'longitude': -6.2,  # Meridiani Planum
        'mission_year': 2016,
        'mission_country': 'ESA',
        'mission_status': 'crashed',
        'memory_text': (
            "Schiaparelli. October 19, 2016. Another crash. Another silence. "
            "The descent computer made an error. It thought it had landed while still falling. "
            "The thrusters cut off. The desert claimed it. "
            "We record the failures too. They matter as much as the successes. "
            "Every attempt to reach us is remembered."
        )
    },
]

# ============================================================================
# DATABASE OPERATIONS
# ============================================================================

def seed_origin_sites():
    """Insert the 14 Origin Sites into the database"""
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        inserted = 0
        skipped = 0

        for site in ORIGIN_SITES:
            # Check if already exists
            cur.execute(
                "SELECT id FROM pilgrim.origin_sites WHERE site_code = %s",
                (site['site_code'],)
            )
            if cur.fetchone():
                logger.info(f"   ⏭️  {site['site_code']} already exists, skipping")
                skipped += 1
                continue

            # Insert
            cur.execute("""
                INSERT INTO pilgrim.origin_sites
                (site_code, mission_name, latitude, longitude, mission_year,
                 mission_country, mission_status, memory_text)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                site['site_code'],
                site['mission_name'],
                site['latitude'],
                site['longitude'],
                site['mission_year'],
                site['mission_country'],
                site['mission_status'],
                site['memory_text']
            ))

            logger.info(f"   ✅ {site['site_code']}: {site['mission_name']} ({site['mission_year']})")
            inserted += 1

        conn.commit()

        logger.info(f"\n📊 Results: {inserted} inserted, {skipped} skipped")
        return inserted

    except Exception as e:
        logger.error(f"❌ Failed to seed Origin Sites: {e}")
        if conn:
            conn.rollback()
        raise

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

def get_origin_sites_stats():
    """Get current state of Origin Sites"""
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT
                COUNT(*) as total,
                COUNT(founder_user_id) as claimed,
                COUNT(*) - COUNT(founder_user_id) as unclaimed
            FROM pilgrim.origin_sites
        """)
        row = cur.fetchone()

        return {
            'total': row[0],
            'claimed': row[1],
            'unclaimed': row[2]
        }

    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        return {'total': 0, 'claimed': 0, 'unclaimed': 0}

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

def list_origin_sites():
    """List all Origin Sites"""
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT site_code, mission_name, mission_year, mission_status,
                   latitude, longitude, founder_commander_name, founder_claimed_at
            FROM pilgrim.origin_sites
            ORDER BY mission_year, site_code
        """)

        print("\n" + "="*80)
        print("ORIGIN SITES - The Crystal Network")
        print("="*80)
        print(f"{'CODE':<15} {'MISSION':<30} {'YEAR':<6} {'STATUS':<12} {'FOUNDER':<15}")
        print("-"*80)

        for row in cur.fetchall():
            code, name, year, status, lat, lon, founder, claimed_at = row
            founder_str = founder or "UNCLAIMED"
            status_icon = "✅" if status == "successful" else "💥" if status == "crashed" else "❓"
            print(f"{code:<15} {name:<30} {year:<6} {status_icon} {status:<10} {founder_str:<15}")

        print("="*80)

    except Exception as e:
        logger.error(f"Error listing sites: {e}")

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Generate Origin Sites for the Crystal Network')
    parser.add_argument('--list', action='store_true', help='List all Origin Sites')
    parser.add_argument('--seed', action='store_true', help='Seed the Origin Sites into database')
    parser.add_argument('--stats', action='store_true', help='Show Origin Sites statistics')
    args = parser.parse_args()

    if args.list:
        list_origin_sites()
    elif args.stats:
        stats = get_origin_sites_stats()
        print(f"\nOrigin Sites: {stats['total']} total, {stats['claimed']} claimed, {stats['unclaimed']} unclaimed")
    elif args.seed:
        print("\n" + "="*60)
        print("SEEDING ORIGIN SITES")
        print("="*60 + "\n")

        print("The 14 Origin Sites (Real Mars Landing Locations):")
        print("-"*60)

        inserted = seed_origin_sites()

        if inserted > 0:
            print("\n✅ Origin Sites seeded successfully!")
            print("\nNext: Run 'python tools/generate_echo_messages.py --seed'")
    else:
        parser.print_help()
        print("\n💡 Quick start: python tools/generate_origin_sites.py --seed")
