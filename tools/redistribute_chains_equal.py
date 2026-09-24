"""TRAILS v3 — equal-distribute existing chain km across all 4 N/E/S/W directions.

Per Andy 2026-04-28: every captain should visibly progress on all 4 chains, not just
the one their old expeditions happened to bucket toward. Total km is conserved —
just redistributed evenly across N/E/S/W so the plus sign reads.

Algorithm per captain:
1. Snapshot total km_built across all 4 directions + per-source attribution.
2. Reset every chain row's km_built (and per-source columns) to 0, completed_at=NULL.
3. Allocate total_km / 4 to each direction, greedy inward-to-outward (segment_index 1
   first, overflow into 2, etc), capped at each segment's segment_distance_km.
4. Conservation check: sum_before == sum_after to within 0.01 km per captain.
"""
import argparse
import logging
import sys
sys.path.insert(0, '.')

from utilities.postgres.core import db_cursor
from utilities.postgres.trails.chains import ensure_user_trail_chains_table

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

CONSERVATION_TOLERANCE_KM = 0.01


def redistribute_user(user_id, commit):
    with db_cursor(commit=commit) as cur:
        # Snapshot total km + per-source totals
        cur.execute("""
            SELECT COALESCE(SUM(km_built), 0)        AS total_km,
                   COALESCE(SUM(captain_km), 0)      AS captain_km,
                   COALESCE(SUM(scientist_km), 0)    AS scientist_km,
                   COALESCE(SUM(aria_km), 0)         AS aria_km,
                   COALESCE(SUM(drone_km), 0)        AS drone_km,
                   COALESCE(SUM(robot_km), 0)        AS robot_km
            FROM pilgrim.user_trail_chains WHERE user_id = %s
        """, (user_id,))
        row = cur.fetchone()
        total_km = float(row['total_km'])
        if total_km <= 0:
            return {'user_id': user_id, 'before': 0.0, 'after': 0.0, 'drift': 0.0, 'per_dir_km': {'N':0,'E':0,'S':0,'W':0}}
        ratios = {
            'captain':   float(row['captain_km'])   / total_km,
            'scientist': float(row['scientist_km']) / total_km,
            'aria':      float(row['aria_km'])      / total_km,
            'drone':     float(row['drone_km'])     / total_km,
            'robot':     float(row['robot_km'])     / total_km,
        }

        if commit:
            # Wipe the chain state for this user — fresh slate, no completed segments
            cur.execute("""
                UPDATE pilgrim.user_trail_chains
                SET km_built = 0,
                    captain_km = 0, scientist_km = 0, aria_km = 0, drone_km = 0, robot_km = 0,
                    completed_at = NULL
                WHERE user_id = %s
            """, (user_id,))

        per_dir = total_km / 4.0
        placed = {'N': 0.0, 'E': 0.0, 'S': 0.0, 'W': 0.0}
        for direction in ('N', 'E', 'S', 'W'):
            cur.execute("""
                SELECT segment_index, segment_distance_km
                FROM pilgrim.user_trail_chains
                WHERE user_id = %s AND direction = %s
                ORDER BY segment_index
            """, (user_id, direction))
            segs = cur.fetchall()
            remaining = per_dir
            for s in segs:
                if remaining <= 0:
                    break
                seg_dist = float(s['segment_distance_km'])
                add = min(seg_dist, remaining)
                if add <= 0:
                    continue
                completed = add >= seg_dist - 1e-6
                if commit:
                    cur.execute("""
                        UPDATE pilgrim.user_trail_chains
                        SET km_built = %s,
                            captain_km   = %s,
                            scientist_km = %s,
                            aria_km      = %s,
                            drone_km     = %s,
                            robot_km     = %s,
                            completed_at = CASE WHEN %s THEN NOW() ELSE NULL END
                        WHERE user_id = %s AND direction = %s AND segment_index = %s
                    """, (add,
                          add * ratios['captain'], add * ratios['scientist'], add * ratios['aria'],
                          add * ratios['drone'], add * ratios['robot'],
                          completed, user_id, direction, s['segment_index']))
                placed[direction] += add
                remaining -= add

        cur.execute("SELECT COALESCE(SUM(km_built), 0) AS s FROM pilgrim.user_trail_chains WHERE user_id = %s", (user_id,))
        actual_after = float(cur.fetchone()['s'])
        placed_total = sum(placed.values())
    drift = abs(placed_total - total_km)
    return {'user_id': user_id, 'before': total_km, 'after': placed_total, 'actual_db_after': actual_after, 'drift': drift, 'per_dir_km': placed}


def main():
    parser = argparse.ArgumentParser()
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument('--dry-run', action='store_true')
    g.add_argument('--commit', action='store_true')
    args = parser.parse_args()
    ensure_user_trail_chains_table()
    with db_cursor() as cur:
        cur.execute("SELECT DISTINCT user_id FROM pilgrim.user_trail_chains ORDER BY user_id")
        user_ids = [r['user_id'] for r in cur.fetchall()]
    print(f'Equal-redistributing chains for {len(user_ids)} captains (mode={"COMMIT" if args.commit else "DRY-RUN"})...')
    print()
    failures = []
    total_before = 0.0
    total_after = 0.0
    for uid in user_ids:
        try:
            r = redistribute_user(uid, args.commit)
            total_before += r['before']
            total_after += r['after']
            print(f"user {uid:>3}: before={r['before']:9.2f}km  after={r['after']:9.2f}km  drift={r['drift']:.4f}km  "
                  f"N={r['per_dir_km']['N']:7.1f} E={r['per_dir_km']['E']:7.1f} S={r['per_dir_km']['S']:7.1f} W={r['per_dir_km']['W']:7.1f}")
            if r['drift'] > CONSERVATION_TOLERANCE_KM:
                failures.append((uid, f"drift {r['drift']:.4f}km"))
        except Exception as e:
            failures.append((uid, str(e)))
            print(f'user {uid}: EXCEPTION — {e}')
    print()
    print(f'TOTAL: before={total_before:.2f}km  after={total_after:.2f}km  drift={abs(total_before-total_after):.4f}km')
    if failures:
        print(f'\nFAILURES: {len(failures)}')
        for uid, err in failures:
            print(f'  user {uid}: {err}')
        sys.exit(1)


if __name__ == '__main__':
    main()
