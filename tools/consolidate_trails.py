"""One-time migration: Consolidate all trail km into 4 closest HOME trails per user.

This fixes the fragmented trail system where km was spread across dozens of disconnected
segments. After this, each user has exactly 4 trails from HOME to their 4 closest landmarks,
with km distributed proportionally (inverse distance weighted).

Run: PATH="$(pwd)/venv_galactica/bin:$PATH" python tools/consolidate_trails.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utilities.postgres.core import db_cursor
from utilities.mars_math import haversine_distance


def consolidate_user_trails(user_id, user_name, dry_run=True):
    """Consolidate all trail km for a user into 4 closest HOME trails."""
    with db_cursor() as cur:
        # Get home coords
        cur.execute('SELECT home_mars_lat, home_mars_lon FROM pilgrim.users WHERE id = %s', (user_id,))
        u = cur.fetchone()
        if not u or not u['home_mars_lat']:
            print(f"  Skipping {user_name} (no home coords)")
            return
        lat, lon = float(u['home_mars_lat']), float(u['home_mars_lon'])

        # Sum all km
        cur.execute("""
            SELECT SUM(km_built) as total, SUM(captain_km) as cap,
                   SUM(scientist_km) as sci, SUM(aria_km) as aria
            FROM pilgrim.trail_segments WHERE user_id = %s AND km_built > 0
        """, (user_id,))
        totals = cur.fetchone()
        total_km = float(totals['total'] or 0)
        total_cap = float(totals['cap'] or 0)
        total_sci = float(totals['sci'] or 0)
        total_aria = float(totals['aria'] or 0)

        if total_km == 0:
            print(f"  {user_name}: No km to consolidate")
            return

        # Find 4 closest landmarks
        cur.execute('SELECT name, type, latitude, longitude FROM pilgrim.mars_mappings')
        landmarks = cur.fetchall()
        dists = []
        for lm in landmarks:
            d = haversine_distance(lat, lon, float(lm['latitude']), float(lm['longitude']))
            dists.append((lm['name'], lm['type'], d, float(lm['latitude']), float(lm['longitude'])))
        dists.sort(key=lambda x: x[2])
        top4 = dists[:4]

        # Inverse distance weighted distribution
        inv_dists = [1/d for _, _, d, _, _ in top4]
        total_inv = sum(inv_dists)

        print(f"\n  {user_name} (user {user_id}): {total_km:.4f} km total")
        print(f"    Cap: {total_cap:.4f}, Sci: {total_sci:.4f}, Aria: {total_aria:.4f}")

        new_trails = []
        for (name, ltype, dist, dlat, dlon), inv in zip(top4, inv_dists):
            pct = inv / total_inv
            new_trails.append({
                'destination': name,
                'type': ltype,
                'total_distance_km': dist,
                'km_built': round(total_km * pct, 6),
                'captain_km': round(total_cap * pct, 6),
                'scientist_km': round(total_sci * pct, 6),
                'aria_km': round(total_aria * pct, 6),
            })
            print(f"    -> {name}: {total_km * pct:.4f} km ({pct*100:.1f}%) of {dist:.2f} km")

    if dry_run:
        print("  [DRY RUN - no changes made]")
        return

    # Execute the migration
    with db_cursor(commit=True) as cur:
        # Count old segments
        cur.execute('SELECT COUNT(*) as cnt FROM pilgrim.trail_segments WHERE user_id = %s', (user_id,))
        old_count = cur.fetchone()['cnt']

        # Delete ALL trail segments for this user
        cur.execute('DELETE FROM pilgrim.trail_segments WHERE user_id = %s', (user_id,))
        print(f"    Deleted {old_count} old trail segments")

        # Create 4 new HOME trails
        for t in new_trails:
            cur.execute("""
                INSERT INTO pilgrim.trail_segments
                (user_id, from_landmark, destination_name, total_distance_km,
                 km_built, captain_km, scientist_km, aria_km, trip_count, trail_level)
                VALUES (%s, 'HOME', %s, %s, %s, %s, %s, %s, 0, 'none')
            """, (user_id, t['destination'], t['total_distance_km'],
                  t['km_built'], t['captain_km'], t['scientist_km'], t['aria_km']))
        print(f"    Created {len(new_trails)} new consolidated trails")


def main():
    dry_run = '--execute' not in sys.argv

    if dry_run:
        print("=== TRAIL CONSOLIDATION (DRY RUN) ===")
        print("Add --execute to apply changes\n")
    else:
        print("=== TRAIL CONSOLIDATION (EXECUTING) ===\n")

    # Get all users with trail segments
    with db_cursor() as cur:
        cur.execute("""
            SELECT DISTINCT ts.user_id, u.name
            FROM pilgrim.trail_segments ts
            JOIN pilgrim.users u ON u.id = ts.user_id
            WHERE ts.km_built > 0 OR ts.trip_count > 0
        """)
        users = cur.fetchall()

    for u in users:
        consolidate_user_trails(u['user_id'], u['name'], dry_run=dry_run)

    print("\nDone.")


if __name__ == '__main__':
    main()
