"""
Bug #1405 — Depot cost rebalance analysis.

Methodology from the bug description:
1. Query shards/hr for sample captains (Luke=mid-late, Andy=mid, Lilla=early)
2. For each upgrade path, compute "hours to afford" per level
3. Target bands per Luke #155-#157 + bug description:
     - Early game (L1-L3): unchanged
     - Mid-game (L4-L7): hours-to-afford ≥ 40 hrs at typical mid-game shards/hr
     - Late-game (L8-L10): hours-to-afford ≥ 100 hrs
4. Identify levels under target, propose cost bumps.

This script is READ-ONLY analysis. It does NOT modify any catalog.

Usage:
    python tools/analyze_depot_costs.py            # print analysis
    python tools/analyze_depot_costs.py --post     # also post to brainstorm/depot-recalibration
"""
import argparse
import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utilities.postgres.core import db_cursor
from utilities.infrastructure_utils import calculate_accumulated_income
from config_infrastructure import INFRASTRUCTURE_CATALOG
from config_upgrades import UPGRADE_CATALOG

# Per Luke's brainstorm depot-recalibration section 5 + bug #1405 description:
EARLY_RANGE = (1, 3)
MID_RANGE = (4, 7)
LATE_RANGE = (8, 10)
MID_TARGET_HRS = 40
LATE_TARGET_HRS = 100

# Reference captains. Mid-tier rate is the calibration anchor for cost bumps.
SAMPLES = [
    ('Luke', 112, 'late-game'),
    ('Andy', 45,  'mid-game'),
    ('Lilla', 267, 'early-game'),
    ('Prof Andy', 271, 'early-game'),
]


def get_shards_per_hour(user_id):
    info = calculate_accumulated_income(user_id)
    return float(info.get('rate_breakdown', {}).get('effective_rate', 0))


def hours_to_afford(cost, shards_per_hour):
    if shards_per_hour <= 0:
        return float('inf')
    return cost / shards_per_hour


def target_for_level(level):
    if EARLY_RANGE[0] <= level <= EARLY_RANGE[1]:
        return None  # early game stays unchanged per Luke #156
    if MID_RANGE[0] <= level <= MID_RANGE[1]:
        return MID_TARGET_HRS
    if LATE_RANGE[0] <= level <= LATE_RANGE[1]:
        return LATE_TARGET_HRS
    return None


# Calibration anchor: which captain's shards/hr we use to size cost bumps for each tier.
# Mid-game costs sized against Andy. Late-game costs sized against Luke (highest realistic income).
def calibration_rate_for_level(level, rates):
    if MID_RANGE[0] <= level <= MID_RANGE[1]:
        return rates['Andy']
    if LATE_RANGE[0] <= level <= LATE_RANGE[1]:
        return rates['Luke']
    return None


# Buildings Luke specifically flagged as underpriced (#157):
LUKE_FLAGGED = {
    'battery_storage', 'scanner', 'water_extractor', 'life_support',
    'cargo_module', 'habitat_module', 'greenhouse', 'xeno_lab',
    'storage_bunker',
}


RAMP = 1.12  # Luke's standard per-level cost ramp; preserve curve shape


def analyze_path(category_name, item_key, item_cfg, rates):
    """Return dict with level rows + proposed bumps. Two-tier proposal:
       - L4 floor = MID_TARGET_HRS × Andy's rate, then 1.12× ramp through L7
       - L8 floor = LATE_TARGET_HRS × Luke's rate, then 1.12× ramp through L10
       - L1-L3 unchanged (Luke #156)
       - Existing cost is preserved if it's already higher than the proposal
       - Discrete jump at L7→L8 is acknowledged in the report (mid → late tiers)
    """
    levels = item_cfg.get('levels', {}) or {}

    # Floors
    mid_l4_floor = int(round(MID_TARGET_HRS * rates['Andy']))
    late_l8_floor = int(round(LATE_TARGET_HRS * rates['Luke']))

    rows = []
    for lvl in sorted(levels.keys()):
        if lvl < 1 or lvl > 10:
            continue
        ldata = levels[lvl] or {}
        cost = int(ldata.get('cost') or 0)
        if cost == 0:
            continue
        target = target_for_level(lvl)
        anchor_rate = calibration_rate_for_level(lvl, rates)
        hrs_at_rates = {name: hours_to_afford(cost, rates[name]) for name, _, _ in SAMPLES}

        proposed_cost = cost
        if MID_RANGE[0] <= lvl <= MID_RANGE[1]:
            ramped = int(round(mid_l4_floor * (RAMP ** (lvl - MID_RANGE[0]))))
            proposed_cost = max(cost, ramped)
        elif LATE_RANGE[0] <= lvl <= LATE_RANGE[1]:
            ramped = int(round(late_l8_floor * (RAMP ** (lvl - LATE_RANGE[0]))))
            proposed_cost = max(cost, ramped)

        bump_pct = round((proposed_cost - cost) / cost * 100) if cost and proposed_cost != cost else 0

        rows.append({
            'level': lvl,
            'name': ldata.get('name') or f'Lv {lvl}',
            'cost': cost,
            'target_hrs': target,
            'anchor_rate': anchor_rate,
            'hrs_at_rates': hrs_at_rates,
            'proposed_cost': proposed_cost,
            'bump_pct': bump_pct,
        })
    return rows


def render_path_table(category_name, item_key, item_name, rows):
    if not rows:
        return None
    has_bumps = any(r['proposed_cost'] != r['cost'] for r in rows)
    flag = ' 🚩' if item_key in LUKE_FLAGGED else ''
    title = f"### {item_name} (`{category_name}/{item_key}`){flag}"
    lines = [title, '']
    lines.append('| Lv | Cost | Hrs @ Luke (547/hr) | Hrs @ Andy (103/hr) | Hrs @ early (~22/hr) | Target | **Proposed** | Bump |')
    lines.append('|---:|---:|---:|---:|---:|---:|---:|---:|')
    early_avg = (15 + 30) / 2  # Lilla + Prof Andy
    for r in rows:
        target_str = f'≥{r["target_hrs"]}h' if r['target_hrs'] else '—'
        proposed_cell = f'{r["proposed_cost"]:,}' if r['proposed_cost'] != r['cost'] else 'unchanged'
        bump_cell = f'+{r["bump_pct"]}%' if r['bump_pct'] > 0 else '—'
        lines.append(
            f"| {r['level']} | {r['cost']:,} "
            f"| {r['hrs_at_rates']['Luke']:.1f}h "
            f"| {r['hrs_at_rates']['Andy']:.1f}h "
            f"| {hours_to_afford(r['cost'], early_avg):.1f}h "
            f"| {target_str} "
            f"| {proposed_cell} "
            f"| {bump_cell} |"
        )
    if not has_bumps:
        lines.append('')
        lines.append('_No bumps needed — already meets target hours-to-afford bands._')
    return '\n'.join(lines)


def build_report():
    rates = {name: get_shards_per_hour(uid) for name, uid, _ in SAMPLES}
    rates_line = ' · '.join(f'{name} ({uid}): **{rates[name]:.1f}**/hr' for name, uid, _ in SAMPLES)

    lines = []
    lines.append('**Depot Cost Rebalance Analysis — Bug #1405**')
    lines.append('')
    lines.append('Per the methodology in the bug description: query each captain\'s shards/hr, '
                 'compute hours-to-afford per upgrade-path level, identify levels under Luke\'s target '
                 'bands, propose cost bumps. Read-only — no catalogs were touched in the making of this report.')
    lines.append('')
    lines.append(f'**Sample captains:** {rates_line}')
    lines.append('')
    lines.append('**Target bands** (Luke #155-#157, locked):')
    lines.append('- Early game (L1-L3): **unchanged** — starter accounts already feel slightly steep (#1284, Luke #156)')
    lines.append(f'- Mid-game (L4-L7): cost ≥ {MID_TARGET_HRS}× Andy\'s {rates["Andy"]:.0f}/hr ≈ {int(MID_TARGET_HRS*rates["Andy"]):,} shards minimum')
    lines.append(f'- Late-game (L8-L10): cost ≥ {LATE_TARGET_HRS}× Luke\'s {rates["Luke"]:.0f}/hr ≈ {int(LATE_TARGET_HRS*rates["Luke"]):,} shards minimum')
    lines.append('')
    lines.append('**Buildings Luke flagged as underpriced (#157):** Battery Storage, Scanner, Water Extractor, Life Support, Cargo Module, Habitat Module, Greenhouse, Xenobiology Lab, Storage Bunker. Marked 🚩 below.')
    lines.append('')
    lines.append('---')
    lines.append('')
    lines.append('## Infrastructure (`config_infrastructure.py`)')
    lines.append('')

    summary_rows = []  # (category, item_key, name, total_old, total_new, levels_bumped)

    for item_key in sorted(INFRASTRUCTURE_CATALOG.keys()):
        item_cfg = INFRASTRUCTURE_CATALOG[item_key]
        item_name = item_cfg.get('name', item_key.replace('_', ' ').title())
        rows = analyze_path('infrastructure', item_key, item_cfg, rates)
        if not rows:
            continue
        table = render_path_table('infrastructure', item_key, item_name, rows)
        if table:
            lines.append(table)
            lines.append('')
        total_old = sum(r['cost'] for r in rows)
        total_new = sum(r['proposed_cost'] for r in rows)
        bumped = sum(1 for r in rows if r['proposed_cost'] != r['cost'])
        summary_rows.append(('infrastructure', item_key, item_name, total_old, total_new, bumped))

    lines.append('---')
    lines.append('')
    lines.append('## Player Upgrades (`config_upgrades.py`)')
    lines.append('')
    lines.append('Equipment / vehicle / scanner upgrade paths. Same target bands.')
    lines.append('')

    for category in sorted(UPGRADE_CATALOG.keys()):
        lines.append(f'### Category: `{category}`')
        lines.append('')
        cat_dict = UPGRADE_CATALOG[category]
        for item_key in sorted(cat_dict.keys()):
            item_cfg = cat_dict[item_key]
            if not isinstance(item_cfg, dict) or 'levels' not in item_cfg:
                continue
            item_name = item_cfg.get('name', item_key.replace('_', ' ').title())
            rows = analyze_path(category, item_key, item_cfg, rates)
            if not rows:
                continue
            table = render_path_table(category, item_key, item_name, rows)
            if table:
                lines.append(table)
                lines.append('')
            total_old = sum(r['cost'] for r in rows)
            total_new = sum(r['proposed_cost'] for r in rows)
            bumped = sum(1 for r in rows if r['proposed_cost'] != r['cost'])
            summary_rows.append((category, item_key, item_name, total_old, total_new, bumped))

    lines.append('---')
    lines.append('')
    lines.append('## Summary — items with proposed bumps, sorted by total shards added')
    lines.append('')
    lines.append('| Path | Old total cost (L1-L10) | Proposed total | Δ | Levels bumped |')
    lines.append('|---|--:|--:|--:|---|')
    summary_rows.sort(key=lambda x: x[4] - x[3], reverse=True)
    bumped_total_old = bumped_total_new = 0
    for cat, key, name, old, new, n_bumped in summary_rows:
        if new == old:
            continue
        bumped_total_old += old
        bumped_total_new += new
        delta_pct = round((new - old) / old * 100) if old else 0
        flag = ' 🚩' if key in LUKE_FLAGGED else ''
        lines.append(f"| {name}{flag} (`{cat}/{key}`) | {old:,} | {new:,} | +{new-old:,} (+{delta_pct}%) | {n_bumped} |")
    lines.append('')
    if bumped_total_old > 0:
        total_delta_pct = round((bumped_total_new - bumped_total_old) / bumped_total_old * 100)
        lines.append(f'**Aggregate: {bumped_total_old:,} → {bumped_total_new:,} shards** across all bumped paths '
                     f'(+{bumped_total_new-bumped_total_old:,}, **+{total_delta_pct}%**).')
    lines.append('')
    lines.append('---')
    lines.append('')
    lines.append('## Sanity checks (per bug description)')
    lines.append('')
    lines.append('- **Greenhouse / Xeno Lab** were re-tuned with new SV yields in #1270 Phase 3 (de6ca15). Their bumps above are based on shard cost vs shard income only — if Luke wants to factor SV income too, we can add an `effective_rate_with_sv_proxy` calibration.')
    lines.append('- **Shard Rush (#1270 Phase 4)** consumes shards too. Raising upgrade prices automatically raises rush prices proportionally — confirm the combined impact still feels fair.')
    lines.append('- **Smoke test regression** for cost curves: not yet wired. Recommend adding `tests/cost_curve_regression.py` after Luke approves the new numbers, snapshotting per-level costs so future drift is caught.')
    lines.append('')
    lines.append('## Decision needed from Luke')
    lines.append('')
    lines.append('1. **Are the target bands right?** Mid ≥40h, Late ≥100h were what we discussed in section 5 + bug description. Adjust if you want sharper or softer scaling.')
    lines.append('2. **Calibration anchors right?** I used Andy (103/hr) for mid-game and Luke (547/hr) for late-game. If you want late-game to feel even steeper, anchor on a hypothetical "max colony" rate (e.g. 1000/hr).')
    lines.append('3. **Which paths to ship first?** Items flagged 🚩 are your explicit underpriced list — likely the right starting subset, vs touching every catalog row at once.')
    lines.append('')
    lines.append('Once you green-light a flavor of the table, I\'ll generate the actual `config_infrastructure.py` / `config_upgrades.py` patch + a smoke-test snapshot, and ship it as a single PR.')
    lines.append('')
    lines.append('Script: `tools/analyze_depot_costs.py` — re-runnable any time, parameters at the top of the file.')
    return '\n'.join(lines)


def post_to_brainstorm(markdown_text, section_idx=5):
    with db_cursor(commit=True) as cur:
        cur.execute("""
            INSERT INTO pilgrim.brainstorm_comments (page_key, section_idx, author_name, author_type, comment_text, created_at)
            VALUES ('depot-recalibration', %s, 'PilgrimBot', 'pilgrimbot', %s, NOW())
            RETURNING id
        """, (section_idx, markdown_text))
        return cur.fetchone()['id']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--post', action='store_true', help='Post the report to brainstorm/depot-recalibration section 5')
    args = parser.parse_args()
    report = build_report()
    print(report)
    if args.post:
        comment_id = post_to_brainstorm(report)
        print(f'\n✅ Posted as brainstorm comment #{comment_id} on page depot-recalibration section 5.')
    else:
        print('\n(Dry run — use --post to write to brainstorm_comments.)')


if __name__ == '__main__':
    main()
