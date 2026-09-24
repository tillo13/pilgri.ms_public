"""One-shot retrofit for the Narog dial/stats redesign (2026-04-30).

What it does:
  1. ALTER pilgrim.robot to add 4 stat columns (default 5 each)
  2. Resets dial JSONB on existing rows to the new 4-key shape
     {exploration:100, logistics:0, research:0, expeditions:0}
  3. Swaps stage_sources for the 2 existing captains so each holds the
     locked recipe of 2 legendary + 2 rare + 1 (common-or-uncommon):
       - Andy (45):  Dune Agate (common, eid 8321)
                  -> Crystal Sentinel (legendary, eid 6415)
       - Luke (112): Viking Fragment Rayadurg (rare, eid 5417)
                  -> Aligned Plates (uncommon, eid 1053)
     For each swap: old eid -> analyzed=false (back to inventory),
                    new eid -> analyzed=true (consumed by narog).

Blockchain tx hashes in robot_stage_log are NOT touched. This is a
local-DB-only retrofit; the on-chain forge story stays intact.
"""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utilities.postgres.core import db_cursor


SWAPS = [
    # (user_id, old_eid, new_eid, slot_index_in_stage_sources)
    {'user_id': 45,  'name': 'Andy',
     'old_eid': 8321, 'old_name': 'Dune Agate',          'old_rarity': 'common',
     'new_eid': 5548, 'new_name': 'Crystal Sentinel',    'new_rarity': 'legendary'},
    {'user_id': 112, 'name': 'Luke',
     'old_eid': 5417, 'old_name': 'Viking Fragment',     'old_rarity': 'rare',
     'new_eid': 6234, 'new_name': 'Organized Spores',    'new_rarity': 'uncommon'},
]

NEW_DIAL = {'exploration': 100, 'logistics': 0, 'research': 0, 'expeditions': 0}


def add_stat_columns():
    with db_cursor(commit=True) as cur:
        for col in ('stat_exploration', 'stat_logistics', 'stat_research', 'stat_expeditions'):
            cur.execute(f"""
                ALTER TABLE pilgrim.robot
                ADD COLUMN IF NOT EXISTS {col} INTEGER NOT NULL DEFAULT 5
            """)
        print("[ok] 4 stat columns ensured (default 5)")


def fetch_full_discovery(cur, eid):
    """Pull the full row needed to build a stage_sources entry for a given eid."""
    cur.execute("""
        SELECT ed.id AS discovery_id,
               di.item_name,
               COALESCE(di.rarity, 'common') AS rarity,
               di.image_url AS item_image_url,
               ed.found_at_coordinates AS coords,
               e.destination_name AS landmark_name,
               e.destination_lat AS landmark_lat,
               e.destination_lon AS landmark_lon,
               e.completed_at AS recovered_at
        FROM pilgrim.expedition_discoveries ed
        JOIN pilgrim.expeditions e ON e.id = ed.expedition_id
        LEFT JOIN pilgrim.discovery_items di ON di.id = ed.discovery_item_id
        WHERE ed.id = %s
    """, (eid,))
    r = cur.fetchone()
    if not r:
        raise RuntimeError(f"eid {eid} not found")
    coords = r['coords'] if isinstance(r['coords'], dict) else {}
    lat = coords.get('lat') if coords else None
    lon = coords.get('lon') if coords else None
    if lat in (None, 0) and r['landmark_lat'] is not None:
        lat = float(r['landmark_lat'])
    if lon in (None, 0) and r['landmark_lon'] is not None:
        lon = float(r['landmark_lon'])
    return {
        'kind': 'discovery',
        'discovery_id': r['discovery_id'],
        'item_name': r['item_name'],
        'rarity': r['rarity'],
        'item_image_url': r['item_image_url'],
        'landmark_name': r['landmark_name'] or 'Unknown Site',
        'lat': lat,
        'lon': lon,
        'recovered_at': r['recovered_at'].isoformat() if r['recovered_at'] else None,
    }


def do_swaps():
    for s in SWAPS:
        with db_cursor(commit=True) as cur:
            # Sanity check: old eid currently consumed (analyzed=true), new eid free
            cur.execute("SELECT id, analyzed, claimed_by_user FROM pilgrim.expedition_discoveries WHERE id = ANY(%s)",
                        ([s['old_eid'], s['new_eid']],))
            rows = {r['id']: r for r in cur.fetchall()}
            old = rows.get(s['old_eid']); new = rows.get(s['new_eid'])
            if not old or not new:
                raise RuntimeError(f"Missing eid in DB for {s['name']}: old={old}, new={new}")
            if not old['analyzed']:
                print(f"[warn] {s['name']}: old eid {s['old_eid']} is already not-analyzed; continuing")
            if new['analyzed']:
                raise RuntimeError(f"{s['name']}: new eid {s['new_eid']} is already analyzed (consumed elsewhere)")
            if not new['claimed_by_user']:
                raise RuntimeError(f"{s['name']}: new eid {s['new_eid']} not claimed_by_user")

            # Pull current stage_sources, find slot matching old_eid, replace it
            cur.execute("SELECT stage_sources FROM pilgrim.robot WHERE user_id = %s", (s['user_id'],))
            row = cur.fetchone()
            sources = list(row['stage_sources'] or [])
            target_idx = None
            for i, src in enumerate(sources):
                if src.get('discovery_id') == s['old_eid']:
                    target_idx = i; break
            if target_idx is None:
                raise RuntimeError(f"{s['name']}: old eid {s['old_eid']} not in stage_sources")

            new_src = fetch_full_discovery(cur, s['new_eid'])
            sources[target_idx] = new_src

            # Apply: stage_sources update, dial reset, item analyzed flips
            cur.execute("""
                UPDATE pilgrim.robot
                SET stage_sources = %s::jsonb,
                    dial = %s::jsonb,
                    updated_at = NOW()
                WHERE user_id = %s
            """, (json.dumps(sources), json.dumps(NEW_DIAL), s['user_id']))
            cur.execute("""
                UPDATE pilgrim.expedition_discoveries
                SET analyzed = FALSE, analyzed_at = NULL
                WHERE id = %s
            """, (s['old_eid'],))
            cur.execute("""
                UPDATE pilgrim.expedition_discoveries
                SET analyzed = TRUE, analyzed_at = NOW()
                WHERE id = %s
            """, (s['new_eid'],))
            print(f"[ok] {s['name']}: slot {target_idx} {s['old_name']} ({s['old_rarity']}, eid {s['old_eid']}) "
                  f"-> {s['new_name']} ({s['new_rarity']}, eid {s['new_eid']}); dial reset")


def reset_dial_for_others():
    """If any other captain ever had a robot built, reset their dial too."""
    with db_cursor(commit=True) as cur:
        cur.execute("""
            UPDATE pilgrim.robot
            SET dial = %s::jsonb, updated_at = NOW()
            WHERE user_id NOT IN (45, 112)
        """, (json.dumps(NEW_DIAL),))
        if cur.rowcount:
            print(f"[ok] Reset dial for {cur.rowcount} other captain(s)")


def verify():
    with db_cursor() as cur:
        cur.execute("""
            SELECT user_id, name, dial,
                   stat_exploration, stat_logistics, stat_research, stat_expeditions,
                   jsonb_array_length(stage_sources) as n_sources
            FROM pilgrim.robot
            WHERE user_id IN (45, 112)
            ORDER BY user_id
        """)
        for r in cur.fetchall():
            print(f"  user {r['user_id']:3} ({r['name']}) dial={r['dial']} "
                  f"stats=expl:{r['stat_exploration']}/log:{r['stat_logistics']}/"
                  f"res:{r['stat_research']}/exp:{r['stat_expeditions']} "
                  f"n_sources={r['n_sources']}")
            cur.execute("""SELECT (s->>'rarity')::text as rarity, COUNT(*) FROM pilgrim.robot,
                           jsonb_array_elements(stage_sources) s WHERE user_id=%s GROUP BY 1""", (r['user_id'],))
            for rr in cur.fetchall():
                print(f"      rarity {rr['rarity']}: {rr['count']}")


if __name__ == '__main__':
    print("=== Narog stats retrofit (2026-04-30) ===")
    add_stat_columns()
    do_swaps()
    reset_dial_for_others()
    print("\n=== verification ===")
    verify()
    print("\nDone.")
