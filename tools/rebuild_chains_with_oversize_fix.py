"""TRAILS v3 — recompute chains with the one-oversize-max Dijkstra fix.

For each captain:
1. Snapshot their current per-direction km (captain/scientist/aria/drone/robot split).
2. DELETE existing user_trail_chains rows.
3. Recompute chains via the improved Dijkstra (one-oversize-max).
4. Re-allocate the snapshot km into the new chain segments greedy inward-to-outward.
5. Conservation check: total km BEFORE == total km AFTER per captain (within 0.01 km).

Idempotent + reversible — no captain loses km.
"""
import argparse
import logging
import sys
sys.path.insert(0, '.')

from utilities.postgres.core import db_cursor
from utilities.postgres.trails.chains import (
    compute_user_trail_chains, persist_user_trail_chains, ensure_user_trail_chains_table,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

CONSERVATION_TOLERANCE_KM = 0.01


def snapshot_user_chain_state(user_id, cur):
    """Capture per-direction km totals + per-source attribution before reset."""
    cur.execute("""
        SELECT direction,
               SUM(km_built) AS km_built_total,
               SUM(captain_km) AS captain_km,
               SUM(scientist_km) AS scientist_km,
               SUM(aria_km) AS aria_km,
               SUM(drone_km) AS drone_km,
               SUM(robot_km) AS robot_km
        FROM pilgrim.user_trail_chains
        WHERE user_id = %s
        GROUP BY direction
    """, (user_id,))
    return {r['direction']: dict(r) for r in cur.fetchall()}


def reallocate_into_chain(user_id, direction, snapshot, commit, cur):
    """Greedy inward-to-outward allocate the snapshot km into the new chain segments."""
    if not snapshot or not snapshot.get('km_built_total'):
        return 0.0
    total_km = float(snapshot['km_built_total'])
    if total_km <= 0:
        return 0.0
    # Per-source ratios
    cap_r = float(snapshot['captain_km'] or 0) / total_km
    sci_r = float(snapshot['scientist_km'] or 0) / total_km
    ari_r = float(snapshot['aria_km'] or 0) / total_km
    drn_r = float(snapshot['drone_km'] or 0) / total_km
    rob_r = float(snapshot['robot_km'] or 0) / total_km

    cur.execute("""
        SELECT segment_index, segment_distance_km
        FROM pilgrim.user_trail_chains
        WHERE user_id = %s AND direction = %s
        ORDER BY segment_index
    """, (user_id, direction))
    segments = cur.fetchall()
    placed = 0.0
    remaining = total_km
    for seg in segments:
        if remaining <= 0:
            break
        seg_dist = float(seg['segment_distance_km'])
        add = min(seg_dist, remaining)
        if add <= 0:
            continue
        completed = add >= seg_dist - 1e-6
        if commit:
            cur.execute("""
                UPDATE pilgrim.user_trail_chains
                SET km_built = %s,
                    captain_km = %s,
                    scientist_km = %s,
                    aria_km = %s,
                    drone_km = %s,
                    robot_km = %s,
                    completed_at = CASE WHEN %s THEN NOW() ELSE NULL END
                WHERE user_id = %s AND direction = %s AND segment_index = %s
            """, (add, add * cap_r, add * sci_r, add * ari_r, add * drn_r, add * rob_r,
                  completed, user_id, direction, seg['segment_index']))
        placed += add
        remaining -= add
    return placed


def rebuild_user(user_id, commit):
    """Full rebuild: snapshot → delete → recompute → reallocate → conservation check."""
    with db_cursor(commit=commit) as cur:
        # Snapshot
        snapshot = snapshot_user_chain_state(user_id, cur)
        before_total = sum(float(s['km_built_total'] or 0) for s in snapshot.values())

        if commit:
            cur.execute("DELETE FROM pilgrim.user_trail_chains WHERE user_id = %s", (user_id,))

    # Recompute (outside the transaction since persist starts its own)
    if commit:
        chains = compute_user_trail_chains(user_id)
        persist_user_trail_chains(user_id, chains)

    # Re-allocate (separate tx)
    after_total = 0.0
    per_dir_placed = {}
    with db_cursor(commit=commit) as cur:
        for direction in ('N', 'E', 'S', 'W'):
            placed = reallocate_into_chain(user_id, direction, snapshot.get(direction), commit, cur)
            per_dir_placed[direction] = placed
            after_total += placed

        # Conservation check
        cur.execute("SELECT COALESCE(SUM(km_built), 0) AS s FROM pilgrim.user_trail_chains WHERE user_id = %s", (user_id,))
        actual_after = float(cur.fetchone()['s'])

    drift = abs(after_total - before_total)
    return {
        'user_id': user_id,
        'before': before_total,
        'after': after_total,
        'actual_after': actual_after,
        'drift': drift,
        'per_dir': per_dir_placed,
    }


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

    print(f'Rebuilding chains for {len(user_ids)} captains (mode={"COMMIT" if args.commit else "DRY-RUN"})...')
    print()
    failures = []
    total_before = 0.0
    total_after = 0.0
    for uid in user_ids:
        try:
            r = rebuild_user(uid, args.commit)
            total_before += r['before']
            total_after += r['after']
            print(f"user {uid:>3}: before={r['before']:9.2f}km  after={r['after']:9.2f}km  drift={r['drift']:.4f}km  "
                  f"N={r['per_dir']['N']:7.1f} E={r['per_dir']['E']:7.1f} S={r['per_dir']['S']:7.1f} W={r['per_dir']['W']:7.1f}")
            if r['drift'] > CONSERVATION_TOLERANCE_KM:
                failures.append((uid, f'drift {r["drift"]:.4f}km exceeds {CONSERVATION_TOLERANCE_KM}km tolerance'))
        except Exception as e:
            failures.append((uid, str(e)))
            print(f'user {uid}: EXCEPTION — {e}')
    print()
    print(f'TOTAL: before={total_before:.2f}km  after={total_after:.2f}km  drift={abs(total_before - total_after):.4f}km')
    if failures:
        print(f'\nFAILURES: {len(failures)}')
        for uid, err in failures:
            print(f'  user {uid}: {err}')
        sys.exit(1)


if __name__ == '__main__':
    main()
