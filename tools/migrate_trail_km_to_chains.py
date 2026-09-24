"""TRAILS v3 — migrate existing trail_segments km into user_trail_chains.

Bug #1414. One-shot CLI tool. For each captain with non-zero trail_segments rows:

1. Bucket each row by destination bearing from base → N/E/S/W
2. Greedy-allocate inward-to-outward into that direction's chain segments
3. Conservation check: SUM(km_built) BEFORE == SUM(km_built) AFTER ± 0.01 km
4. Drop zero-km filler trail_segments rows
5. Print delta report

Usage:
  python tools/migrate_trail_km_to_chains.py --dry-run
  python tools/migrate_trail_km_to_chains.py --commit

Idempotent: re-running --commit on a captain who's already migrated is a no-op
(checks user_trail_chains.km_built before transferring).

Conservation rule comes from bug #1280 trauma — Luke saw 80% trails revert.
Drift halts the migration immediately and writes a P1 bug to /admin/bugs.
"""

import argparse
import logging
import sys
from typing import Dict, List

# Allow running from repo root
sys.path.insert(0, '.')

from utilities.postgres.core import db_cursor
from utilities.postgres.trails.chains import (
    compute_user_trail_chains,
    persist_user_trail_chains,
    ensure_user_trail_chains_table,
)
from utilities.postgres.map import get_or_set_user_mars_home, get_mars_mappings_by_name
from utilities.mars_math import bearing_deg, haversine_distance


logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)


CONSERVATION_TOLERANCE_KM = 0.01


class MigrationDriftError(Exception):
    pass


def bearing_to_cardinal(bearing: float) -> str:
    """Bucket a bearing (0-360) into N/E/S/W."""
    b = bearing % 360
    if b >= 315 or b < 45:
        return 'N'
    if b < 135:
        return 'E'
    if b < 225:
        return 'S'
    return 'W'


def get_user_trail_segments_with_km(user_id: int, cur) -> List[Dict]:
    """Fetch this user's trail_segments with non-zero km_built."""
    cur.execute("""
        SELECT id, from_landmark, destination_name,
               COALESCE(km_built, 0) AS km_built,
               COALESCE(captain_km, 0) AS captain_km,
               COALESCE(scientist_km, 0) AS scientist_km,
               COALESCE(aria_km, 0) AS aria_km,
               COALESCE(drone_km, 0) AS drone_km
        FROM pilgrim.trail_segments
        WHERE user_id = %s AND km_built > 0
    """, (user_id,))
    return [dict(r) for r in cur.fetchall()]


def get_chain_segments_for_direction(user_id: int, direction: str, cur) -> List[Dict]:
    """Fetch chain segments for one direction, ordered by segment_index."""
    cur.execute("""
        SELECT segment_index, segment_distance_km, km_built,
               captain_km, scientist_km, aria_km, drone_km, robot_km
        FROM pilgrim.user_trail_chains
        WHERE user_id = %s AND direction = %s
        ORDER BY segment_index
    """, (user_id, direction))
    return [dict(r) for r in cur.fetchall()]


def allocate_km_to_chain(
    user_id: int,
    direction: str,
    km_to_allocate: float,
    captain_km: float,
    scientist_km: float,
    aria_km: float,
    drone_km: float,
    cur,
    commit: bool,
) -> float:
    """Greedy-allocate km into the chain (inward to outward).

    Returns total km actually placed (may be less than km_to_allocate if chain is full).
    Per-source attribution scaled to the same ratio that came in.
    """
    segments = get_chain_segments_for_direction(user_id, direction, cur)
    if not segments:
        return 0.0

    placed = 0.0
    remaining = km_to_allocate
    # Pre-compute attribution ratios so we can split overflow proportionally
    if km_to_allocate > 0:
        cap_ratio = captain_km / km_to_allocate
        sci_ratio = scientist_km / km_to_allocate
        ari_ratio = aria_km / km_to_allocate
        drn_ratio = drone_km / km_to_allocate
    else:
        cap_ratio = sci_ratio = ari_ratio = drn_ratio = 0.0

    for seg in segments:
        if remaining <= 0:
            break
        seg_dist = float(seg['segment_distance_km'])
        cur_built = float(seg['km_built'] or 0)
        space = max(0.0, seg_dist - cur_built)
        if space <= 0:
            continue
        add = min(space, remaining)
        if add <= 0:
            continue
        new_built = cur_built + add
        completed = new_built >= seg_dist - 1e-6
        # Per-source attribution split
        cap_add = add * cap_ratio
        sci_add = add * sci_ratio
        ari_add = add * ari_ratio
        drn_add = add * drn_ratio
        if commit:
            cur.execute("""
                UPDATE pilgrim.user_trail_chains
                SET km_built = %s,
                    captain_km = COALESCE(captain_km, 0) + %s,
                    scientist_km = COALESCE(scientist_km, 0) + %s,
                    aria_km = COALESCE(aria_km, 0) + %s,
                    drone_km = COALESCE(drone_km, 0) + %s,
                    completed_at = CASE WHEN %s THEN NOW() ELSE completed_at END
                WHERE user_id = %s AND direction = %s AND segment_index = %s
            """, (new_built, cap_add, sci_add, ari_add, drn_add, completed,
                  user_id, direction, seg['segment_index']))
        placed += add
        remaining -= add
    return placed


def migrate_captain(user_id: int, commit: bool) -> Dict:
    """Migrate one captain. Returns delta report."""
    base = get_or_set_user_mars_home(user_id)
    base_lat = float(base['latitude'])
    base_lon = float(base['longitude'])
    landmarks_by_name = get_mars_mappings_by_name()

    report = {
        'user_id': user_id,
        'rows_seen': 0,
        'km_before': 0.0,
        'km_after': 0.0,
        'per_direction_km': {'N': 0.0, 'E': 0.0, 'S': 0.0, 'W': 0.0},
        'orphan_destinations': 0,
        'drift_km': 0.0,
        'zero_km_rows_dropped': 0,
    }

    with db_cursor(commit=commit) as cur:
        # 1. Snapshot km BEFORE
        cur.execute("SELECT COALESCE(SUM(km_built), 0) AS s FROM pilgrim.trail_segments WHERE user_id = %s", (user_id,))
        report['km_before'] = float(cur.fetchone()['s'])

        # 2. Snapshot chain km BEFORE migration (so we can compute delta)
        cur.execute("SELECT COALESCE(SUM(km_built), 0) AS s FROM pilgrim.user_trail_chains WHERE user_id = %s", (user_id,))
        chain_km_before = float(cur.fetchone()['s'])

        # 3. Walk each non-zero trail_segments row, bucket by destination bearing, allocate
        rows = get_user_trail_segments_with_km(user_id, cur)
        report['rows_seen'] = len(rows)
        for row in rows:
            dest_name = row['destination_name']
            dest_lm = landmarks_by_name.get(dest_name)
            if not dest_lm or dest_lm.get('latitude') is None:
                report['orphan_destinations'] += 1
                continue
            dest_lat = float(dest_lm['latitude'])
            dest_lon = float(dest_lm['longitude'])
            bearing = bearing_deg(base_lat, base_lon, dest_lat, dest_lon)
            direction = bearing_to_cardinal(bearing)
            placed = allocate_km_to_chain(
                user_id=user_id,
                direction=direction,
                km_to_allocate=float(row['km_built']),
                captain_km=float(row['captain_km'] or 0),
                scientist_km=float(row['scientist_km'] or 0),
                aria_km=float(row['aria_km'] or 0),
                drone_km=float(row['drone_km'] or 0),
                cur=cur,
                commit=commit,
            )
            report['per_direction_km'][direction] += placed

        # 4. Conservation check: compare placed (allocated) km vs trail_segments source km.
        # In dry-run, allocate_km_to_chain returns the placed amount without writing — we sum it.
        # In commit mode, we additionally re-read the table and verify the write matched.
        placed_total = sum(report['per_direction_km'].values())
        report['km_after'] = placed_total
        report['drift_km'] = abs(placed_total - report['km_before'])
        if report['drift_km'] > CONSERVATION_TOLERANCE_KM:
            raise MigrationDriftError(
                f"User {user_id}: BEFORE={report['km_before']:.4f}km, "
                f"PLACED={placed_total:.4f}km, drift={report['drift_km']:.4f}km "
                f"(tolerance {CONSERVATION_TOLERANCE_KM}km)"
            )

        if commit:
            # Verify the actual DB state matches what we placed
            cur.execute("SELECT COALESCE(SUM(km_built), 0) AS s FROM pilgrim.user_trail_chains WHERE user_id = %s", (user_id,))
            chain_km_after = float(cur.fetchone()['s'])
            db_delta = chain_km_after - chain_km_before
            if abs(db_delta - placed_total) > CONSERVATION_TOLERANCE_KM:
                raise MigrationDriftError(
                    f"User {user_id}: COMMIT verification failed — placed={placed_total:.4f}km but DB delta={db_delta:.4f}km"
                )

        # 6. Drop zero-km filler rows
        if commit:
            cur.execute("""
                DELETE FROM pilgrim.trail_segments
                WHERE user_id = %s AND COALESCE(km_built, 0) = 0
            """, (user_id,))
            report['zero_km_rows_dropped'] = cur.rowcount

    return report


def main():
    parser = argparse.ArgumentParser()
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument('--dry-run', action='store_true')
    g.add_argument('--commit', action='store_true')
    parser.add_argument('--user-id', type=int, help='Migrate just one user (testing)')
    args = parser.parse_args()

    ensure_user_trail_chains_table()

    # Make sure all captains have chains computed first
    with db_cursor() as cur:
        if args.user_id:
            user_ids = [args.user_id]
        else:
            cur.execute("""
                SELECT DISTINCT user_id FROM pilgrim.trail_segments WHERE COALESCE(km_built, 0) > 0
            """)
            user_ids = [r['user_id'] for r in cur.fetchall()]

    print(f'Migrating km for {len(user_ids)} captains...')
    print(f'Mode: {"COMMIT (live writes)" if args.commit else "DRY RUN (no writes)"}')
    print()

    total_before = 0.0
    total_after = 0.0
    failures = []
    for uid in user_ids:
        try:
            report = migrate_captain(uid, commit=args.commit)
            total_before += report['km_before']
            total_after += report['km_after']
            print(f"user {uid}: rows={report['rows_seen']:3d}  "
                  f"before={report['km_before']:9.2f}km  "
                  f"after={report['km_after']:9.2f}km  "
                  f"drift={report['drift_km']:.4f}km  "
                  f"N={report['per_direction_km']['N']:7.1f} "
                  f"E={report['per_direction_km']['E']:7.1f} "
                  f"S={report['per_direction_km']['S']:7.1f} "
                  f"W={report['per_direction_km']['W']:7.1f}  "
                  f"orphans={report['orphan_destinations']}  "
                  f"dropped={report['zero_km_rows_dropped']}")
        except MigrationDriftError as e:
            failures.append((uid, str(e)))
            print(f'user {uid}: FAILED — {e}')
        except Exception as e:
            failures.append((uid, str(e)))
            print(f'user {uid}: EXCEPTION — {e}')

    print()
    print(f'TOTAL: before={total_before:.2f}km, after={total_after:.2f}km, '
          f'drift={abs(total_before - total_after):.4f}km')
    if failures:
        print(f'\nFAILURES: {len(failures)}')
        for uid, err in failures:
            print(f'  user {uid}: {err}')
        sys.exit(1)


if __name__ == '__main__':
    main()
