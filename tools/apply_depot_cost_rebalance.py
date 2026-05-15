"""
Bug #1405 — apply the depot cost rebalance.

v2 (2026-05-15, Luke ReOpen on 2026-05-09):
  Luke: "the bump was not enough. I incorrectly forgot to account for the
  expedition shards along with hr shard generation. End Level Sepolia Chamber
  level 1 is only 80K shards. Level 10 Research Station is only 70K shards.
  Level 10 Rover is only 70K shards. Those are the 'best' buildings in the
  game, and i can buy them all in ~2-3 days."

  Translation: actual income (hourly + expedition payouts) ~7× the anchor used
  in v1. Late target stretched 100h → 700h to recover the "~3 weeks to afford
  end-game" feel. End-game buildings (L1 cost ≥ END_GAME_L1_THRESHOLD) now
  apply the late floor to L1-L3 too, since their "early levels" ARE the
  late-game experience — addresses Luke's Resonance Chamber L1=80K callout.

Algorithm:
  - Mid tier (L4-L7): floor = round(MID_TARGET_HRS × Andy's shards/hr), then ×1.12 ramp
  - Late tier (L8-L10): floor = round(LATE_TARGET_HRS × Luke's shards/hr), then ×1.12 ramp
  - End-game buildings (L1 cost ≥ END_GAME_L1_THRESHOLD): L1-L3 ALSO use late floor (no ramp on L2/L3, max-only)
  - Regular buildings: L1-L3 unchanged (Luke #156 — starter economy untouched)
  - max(existing_cost, ramped_floor) — never lower an already-high cost

Usage:
    python tools/apply_depot_cost_rebalance.py --dry-run   # print diff, no writes
    python tools/apply_depot_cost_rebalance.py             # apply edits
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config_infrastructure import INFRASTRUCTURE_CATALOG
from config_upgrades import UPGRADE_CATALOG

# Frozen anchors from brainstorm comment #200 (analyzer run on 2026-04-29).
# v2 (2026-05-15): LATE target raised 100h → 700h per Luke's ReOpen — true
# shards/hr ~7× the v1 anchor once expedition payouts are included.
ANCHOR_ANDY_RATE = 103.2
ANCHOR_LUKE_RATE = 546.4
MID_TARGET_HRS = 40
LATE_TARGET_HRS = 700
RAMP = 1.12
MID_RANGE = (4, 7)
LATE_RANGE = (8, 10)
EARLY_RANGE = (1, 3)

# Buildings whose L1 cost ≥ this threshold are treated as end-game from L1
# (their L1-L3 also get the late floor, since they're not part of the starter loop).
END_GAME_L1_THRESHOLD = 20_000

MID_L4_FLOOR = int(round(MID_TARGET_HRS * ANCHOR_ANDY_RATE))      # 4128
LATE_L8_FLOOR = int(round(LATE_TARGET_HRS * ANCHOR_LUKE_RATE))    # 382480


def proposed_cost(level: int, current_cost: int, l1_cost: int = 0) -> int:
    is_end_game = l1_cost >= END_GAME_L1_THRESHOLD
    if EARLY_RANGE[0] <= level <= EARLY_RANGE[1]:
        if is_end_game:
            return max(current_cost, LATE_L8_FLOOR)
        return current_cost
    if MID_RANGE[0] <= level <= MID_RANGE[1]:
        if is_end_game:
            return max(current_cost, LATE_L8_FLOOR)
        ramped = int(round(MID_L4_FLOOR * (RAMP ** (level - MID_RANGE[0]))))
        return max(current_cost, ramped)
    if LATE_RANGE[0] <= level <= LATE_RANGE[1]:
        ramped = int(round(LATE_L8_FLOOR * (RAMP ** (level - LATE_RANGE[0]))))
        return max(current_cost, ramped)
    return current_cost


def collect_diffs():
    """Return list of (file_path, item_key, level, old_cost, new_cost)."""
    diffs = []
    infra_path = ROOT / 'config_infrastructure.py'
    for item_key, item_cfg in INFRASTRUCTURE_CATALOG.items():
        levels = item_cfg.get('levels') or {}
        l1_cost = int((levels.get(1) or {}).get('cost') or 0)
        for lvl, ldata in levels.items():
            if not isinstance(lvl, int) or lvl < 1 or lvl > 10:
                continue
            old = int(ldata.get('cost') or 0)
            if old == 0:
                continue
            new = proposed_cost(lvl, old, l1_cost=l1_cost)
            if new != old:
                diffs.append((infra_path, item_key, lvl, old, new))

    upg_path = ROOT / 'config_upgrades.py'
    for category, cat_dict in UPGRADE_CATALOG.items():
        if not isinstance(cat_dict, dict):
            continue
        for item_key, item_cfg in cat_dict.items():
            if not isinstance(item_cfg, dict) or 'levels' not in item_cfg:
                continue
            levels = item_cfg.get('levels') or {}
            l1_cost = int((levels.get(1) or {}).get('cost') or 0)
            for lvl, ldata in levels.items():
                if not isinstance(lvl, int) or lvl < 1 or lvl > 10:
                    continue
                old = int(ldata.get('cost') or 0)
                if old == 0:
                    continue
                new = proposed_cost(lvl, old, l1_cost=l1_cost)
                if new != old:
                    diffs.append((upg_path, item_key, lvl, old, new))
    return diffs


def patch_file(path: Path, edits, dry_run=False):
    """Apply cost edits scoped per item_key. edits = list of (item_key, level, old, new)."""
    text = path.read_text()
    lines = text.split('\n')

    # Build map of item_key -> (start_line, end_line) by finding top-level '<key>': {
    # We treat any line matching r"^( {4}|        )'(\w+)': \{" as an item header.
    # Both files have items at the same indentation depth (4 spaces for infra,
    # 8 spaces for nested upgrade categories). Detect dynamically.
    item_starts = {}  # item_key -> line_idx
    item_keys_in_order = []
    needed_keys = {e[0] for e in edits}
    for i, line in enumerate(lines):
        m = re.match(r"^(\s+)'(\w+)':\s*\{", line)
        if not m:
            continue
        key = m.group(2)
        if key in needed_keys and key not in item_starts:
            item_starts[key] = i
            item_keys_in_order.append((i, key))

    # Determine each item's slice end as the next captured item start (or EOF).
    item_keys_in_order.sort()
    item_bounds = {}
    for idx, (start, key) in enumerate(item_keys_in_order):
        end = item_keys_in_order[idx + 1][0] if idx + 1 < len(item_keys_in_order) else len(lines)
        item_bounds[key] = (start, end)

    n_changed = 0
    for item_key, level, old, new in edits:
        if item_key not in item_bounds:
            print(f'  ⚠️  {item_key}: not found in {path.name}', file=sys.stderr)
            continue
        start, end = item_bounds[item_key]
        # Find the level header `<level>: {` within the slice.
        level_re = re.compile(rf"^\s+{level}:\s*\{{")
        cost_re = re.compile(rf"('cost':\s*){old}\b")
        level_idx = None
        for j in range(start, end):
            if level_re.match(lines[j]):
                level_idx = j
                break
        if level_idx is None:
            print(f'  ⚠️  {item_key} L{level}: level header not found', file=sys.stderr)
            continue
        # Within the next ~12 lines, find the cost line and replace.
        replaced = False
        for j in range(level_idx, min(level_idx + 15, end)):
            new_line, n = cost_re.subn(rf"\g<1>{new}", lines[j], count=1)
            if n:
                lines[j] = new_line
                n_changed += 1
                replaced = True
                break
        if not replaced:
            print(f'  ⚠️  {item_key} L{level}: cost {old} not found near header', file=sys.stderr)

    new_text = '\n'.join(lines)
    if not dry_run and new_text != text:
        path.write_text(new_text)
    return n_changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    print(f'Anchors: MID L4 floor = {MID_L4_FLOOR} ({MID_TARGET_HRS}h × {ANCHOR_ANDY_RATE}/hr), '
          f'LATE L8 floor = {LATE_L8_FLOOR} ({LATE_TARGET_HRS}h × {ANCHOR_LUKE_RATE}/hr), '
          f'end-game L1 threshold = {END_GAME_L1_THRESHOLD:,}, ramp = {RAMP}x/lvl')
    print()

    diffs = collect_diffs()
    if not diffs:
        print('No changes — catalogs already at or above target costs.')
        return

    by_path = {}
    for d in diffs:
        by_path.setdefault(d[0], []).append(d[1:])

    total_old = total_new = 0
    for path, edits in by_path.items():
        print(f'=== {path.name} ===')
        # Group by item_key for readability
        by_item = {}
        for (k, lvl, old, new) in edits:
            by_item.setdefault(k, []).append((lvl, old, new))
        for k in sorted(by_item):
            print(f'  {k}:')
            for lvl, old, new in sorted(by_item[k]):
                bump = (new - old) / old * 100
                print(f'    L{lvl}: {old:>7,} → {new:>7,}  (+{bump:>6.0f}%)')
                total_old += old
                total_new += new
        print()
        n = patch_file(path, edits, dry_run=args.dry_run)
        print(f'  edits applied: {n}{" (dry run)" if args.dry_run else ""}')
        print()

    delta = total_new - total_old
    pct = delta / total_old * 100 if total_old else 0
    print(f'Aggregate (L4-L10 across all bumped paths):')
    print(f'  before: {total_old:>10,} shards')
    print(f'  after:  {total_new:>10,} shards')
    print(f'  delta:  +{delta:>9,} (+{pct:.0f}%)')


if __name__ == '__main__':
    main()
