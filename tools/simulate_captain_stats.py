"""
Bug #21 — Retroactive captain stat simulation.

Luke's ask (captain-stats brainstorm section 2):
> "We should simulate what the stats would be if we do retroactive, and then
>  see if it feels right. No point in redesigning the system, and then just
>  keeps the current Captain stats."

This script is READ-ONLY. It:
  1. Pulls every captain with stats + their lifetime activity counts.
  2. Applies the proposed progression formulas (brainstorm section 2).
  3. Prints a side-by-side table: current stats vs. simulated retroactive stats.
  4. Optionally posts a markdown comment on the captain-stats brainstorm page.

Usage:
    python tools/simulate_captain_stats.py            # print table only
    python tools/simulate_captain_stats.py --post     # also post to brainstorm
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utilities.postgres.core import db_cursor
from utilities.mars_environment_utils import get_mars_sol_number

# Progression formulas from captain-stats brainstorm section 2
# (PilgrimBot proposals reacted to by Luke; ARIA/chat gains REMOVED per Luke)
FORMULAS = {
    'leadership':  [('sols_survived',  0.1), ('crew_missions',   0.5)],
    'strategy':    [('expeditions',    0.2), ('legendaries',     1.0)],
    'exploration': [('km_traveled',    0.01), ('landmarks',      2.0)],
    'logistics':   [('trail_segments', 0.5), ('depot_upgrades',  1.0)],
    'charisma':    [('aria_bonds',     2.0)],  # conversation gains cut
}
WORLD_1_CAP = 75


def fetch_all_captains():
    with db_cursor() as cur:
        cur.execute("""
            SELECT ra.user_id,
                   COALESCE(u.captain_name, u.given_name, u.name, 'user_' || ra.user_id) AS captain_name,
                   ra.commander_leadership  AS leadership,
                   ra.commander_strategy    AS strategy,
                   ra.commander_exploration AS exploration,
                   ra.commander_logistics   AS logistics,
                   ra.commander_charisma    AS charisma,
                   u.first_login
              FROM pilgrim.replicate_assets ra
              JOIN pilgrim.users u ON u.id = ra.user_id
             WHERE ra.asset_type = 'character_image'
               AND ra.is_deleted = FALSE
               AND ra.commander_leadership IS NOT NULL
        """)
        rows = [dict(r) for r in cur.fetchall()]

    # Keep only the highest-stat record per user (most recent character with stats)
    best = {}
    for r in rows:
        uid = r['user_id']
        score = (r['leadership'] or 0) + (r['strategy'] or 0) + (r['exploration'] or 0) + (r['logistics'] or 0) + (r['charisma'] or 0)
        if uid not in best or score > best[uid]['_score']:
            r['_score'] = score
            best[uid] = r
    return list(best.values())


def fetch_activity(user_id, first_login):
    current_sol = get_mars_sol_number()
    first_sol = get_mars_sol_number(first_login) if first_login else current_sol
    sols_survived = max(0, current_sol - first_sol)

    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM pilgrim.crew_missions WHERE user_id = %s AND completed_at IS NOT NULL", (user_id,))
        crew_missions = cur.fetchone()['n']

        cur.execute("SELECT COUNT(*) AS n, COALESCE(SUM(distance_km), 0) AS km FROM pilgrim.expeditions WHERE user_id = %s AND completed_at IS NOT NULL", (user_id,))
        row = cur.fetchone()
        expeditions = row['n']
        km_traveled = float(row['km'] or 0)

        cur.execute("""
            SELECT COUNT(*) AS n
              FROM pilgrim.expedition_discoveries ed
              JOIN pilgrim.expeditions e ON e.id = ed.expedition_id
              JOIN pilgrim.discovery_items d ON d.id = ed.discovery_item_id
             WHERE e.user_id = %s AND d.rarity = 'legendary'
        """, (user_id,))
        legendaries = cur.fetchone()['n']

        cur.execute("SELECT COUNT(DISTINCT landmark_name) AS n FROM pilgrim.landmark_discoveries WHERE user_id = %s", (user_id,))
        landmarks = cur.fetchone()['n']

        cur.execute("SELECT COUNT(*) AS n FROM pilgrim.trail_segments WHERE user_id = %s", (user_id,))
        trail_segments = cur.fetchone()['n']

        # player_upgrades is the live table (upgrade_transactions is empty/unused).
        # Sum of current levels = total upgrade-level-ups the captain has completed.
        cur.execute("SELECT COALESCE(SUM(level), 0) AS n FROM pilgrim.player_upgrades WHERE user_id = %s", (user_id,))
        depot_upgrades = int(cur.fetchone()['n'])

        cur.execute("SELECT COUNT(*) AS n FROM pilgrim.aria_bonds WHERE (user_id_1 = %s OR user_id_2 = %s) AND status = 'bonded'", (user_id, user_id))
        aria_bonds = cur.fetchone()['n']

    return {
        'sols_survived': sols_survived,
        'crew_missions': crew_missions,
        'expeditions': expeditions,
        'km_traveled': km_traveled,
        'legendaries': legendaries,
        'landmarks': landmarks,
        'trail_segments': trail_segments,
        'depot_upgrades': depot_upgrades,
        'aria_bonds': aria_bonds,
    }


def simulate(captain, activity):
    sim = {}
    for stat, terms in FORMULAS.items():
        base = captain.get(stat) or 0
        growth = sum(activity[key] * rate for key, rate in terms)
        sim[stat] = {
            'base': base,
            'growth': growth,
            'new_raw': base + growth,
            'new_capped': min(WORLD_1_CAP, base + growth),
        }
    return sim


def fmt_num(n):
    if isinstance(n, float):
        if n >= 100:
            return f'{n:.0f}'
        if n >= 10:
            return f'{n:.1f}'
        return f'{n:.2f}'
    return f'{n:,}'


def build_markdown_report(results):
    lines = []
    lines.append("**Retroactive Captain Stats Simulation — Bug #21**")
    lines.append("")
    lines.append("Formulas applied (from brainstorm section 2 — ARIA/chat gains removed per Luke):")
    lines.append("")
    lines.append("- **Leadership** = base + 0.1·sols + 0.5·crew_missions")
    lines.append("- **Strategy**   = base + 0.2·expeditions + 1.0·legendaries")
    lines.append("- **Exploration** = base + 0.01·km + 2.0·landmarks")
    lines.append("- **Logistics**  = base + 0.5·trail_segments + 1.0·depot_upgrades")
    lines.append("- **Charisma**   = base + 2.0·ARIA_bonds")
    lines.append("")
    lines.append(f"World 1 cap = {WORLD_1_CAP}. Table below shows `current → simulated (+growth, capped)`.")
    lines.append("Users sorted by total growth descending.")
    lines.append("")
    lines.append("| Captain | Sols | CrewMis | Exped | km | Legs | Land | Trail | Upg | Bonds | LEAD | STRAT | EXPL | LOGI | CHAR |")
    lines.append("|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|---|---|---|---|")

    enriched = []
    for captain, activity, sim in results:
        total_growth = sum(s['growth'] for s in sim.values())
        enriched.append((total_growth, captain, activity, sim))
    enriched.sort(reverse=True, key=lambda x: x[0])

    for _, c, a, s in enriched:
        def cell(stat):
            base = s[stat]['base']
            growth = s[stat]['growth']
            capped = s[stat]['new_capped']
            raw = s[stat]['new_raw']
            cap_hit = '★' if raw > WORLD_1_CAP else ''
            return f"{int(base)}→{int(capped)}{cap_hit} (+{fmt_num(growth)})"
        lines.append(
            f"| {c['captain_name']} (#{c['user_id']}) "
            f"| {a['sols_survived']} | {a['crew_missions']} | {a['expeditions']} | {fmt_num(a['km_traveled'])} "
            f"| {a['legendaries']} | {a['landmarks']} | {a['trail_segments']} | {a['depot_upgrades']} | {a['aria_bonds']} "
            f"| {cell('leadership')} | {cell('strategy')} | {cell('exploration')} "
            f"| {cell('logistics')} | {cell('charisma')} |"
        )

    lines.append("")
    lines.append("★ = would exceed World 1 cap of 75, capped.")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("**Calibration findings:**")
    lines.append("")
    lines.append("1. **Formulas are too aggressive at the top end.** Luke (#112) pegs 4 of 5 stats at 75. Andy (#45) pegs 4 of 5 at 75. Trustable (#250) shows +3029 Leadership growth — that account has ~6,000 bot-farmed crew missions, so the raw number is junk, but even at Luke's real 570 crew missions, `0.5 × 570 = 285` Leadership. That's 4× the cap from one activity.")
    lines.append("2. **`km_traveled × 0.01` breaks at Luke-scale.** 117k km × 0.01 = +1,170 Exploration. Needs to be ~0.001 or lower, otherwise anyone running serious expeditions pegs instantly.")
    lines.append("3. **Mid-tier players move naturally.** Debra, Lilla, Don, Jacob — all sit in the +10 to +25 growth range. That feels healthy.")
    lines.append("4. **Bottom-tier captains barely move.** Heather (#331, 79 sols, 0 activity) gets +7.9 Leadership from sols alone. That's fine — sols are the passive-participation floor.")
    lines.append("5. **Charisma is nearly dead.** Only ARIA bonds drive it, and most captains have 0-1 bond. Either add a second growth term or merge Charisma into Leadership (brainstorm section 3 floated this).")
    lines.append("6. **Bot/test accounts need filtering.** User #250 has 6,038 crew missions — clearly an automation run, not real play. Before activating progression, we need either a mission-per-sol rate limit or exclusion of known test accounts.")
    lines.append("")
    lines.append("**Proposed rebalance for round 2** (if Luke agrees the above is the problem):")
    lines.append("")
    lines.append("| Stat | Old formula | Proposed (×5 to ×10 conservative) |")
    lines.append("|---|---|---|")
    lines.append("| Leadership | 0.1·sols + 0.5·crew_missions | 0.1·sols + **0.05**·crew_missions |")
    lines.append("| Strategy | 0.2·expeditions + 1.0·legendaries | 0.2·expeditions + 1.0·legendaries *(unchanged — already balanced)* |")
    lines.append("| Exploration | 0.01·km + 2.0·landmarks | **0.001**·km + **1.0**·landmarks |")
    lines.append("| Logistics | 0.5·trail_segments + 1.0·upgrades | **0.05**·trail_segments + 1.0·upgrades |")
    lines.append("| Charisma | 2.0·aria_bonds | 2.0·aria_bonds + **0.1·signal_claims** *(need new term)* |")
    lines.append("")
    lines.append("Under the rebalanced numbers, Luke's retroactive growth drops from `+303 Lead` to `+47 Lead` (realistic), and mid-tier players still feel meaningful gains. Happy to run a round 2 simulation on request.")
    lines.append("")
    lines.append("**Decision needed from Luke:**")
    lines.append("- Are the proposed rebalanced multipliers in the right neighborhood?")
    lines.append("- How to handle bot/test accounts — exclude entirely, or let them cap at 75 and move on?")
    lines.append("- Charisma: add signal_claims as a growth term, or fold into Leadership?")
    lines.append("")
    lines.append("Script: `tools/simulate_captain_stats.py` (read-only, rerunnable).")

    return "\n".join(lines)


def post_to_brainstorm(markdown_text, section_idx=2):
    with db_cursor(commit=True) as cur:
        cur.execute("""
            INSERT INTO pilgrim.brainstorm_comments (page_key, section_idx, author_name, author_type, comment_text, created_at)
            VALUES ('captain-stats', %s, 'PilgrimBot', 'pilgrimbot', %s, NOW())
            RETURNING id
        """, (section_idx, markdown_text))
        return cur.fetchone()['id']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--post', action='store_true', help='Post the report as a PilgrimBot brainstorm comment')
    parser.add_argument('--limit', type=int, help='Only simulate the top N captains by activity')
    args = parser.parse_args()

    print("Fetching captains...")
    captains = fetch_all_captains()
    print(f"Found {len(captains)} captains with stats.\n")

    results = []
    for c in captains:
        activity = fetch_activity(c['user_id'], c['first_login'])
        sim = simulate(c, activity)
        results.append((c, activity, sim))

    if args.limit:
        results.sort(key=lambda r: sum(s['growth'] for s in r[2].values()), reverse=True)
        results = results[: args.limit]

    report = build_markdown_report(results)
    print(report)

    if args.post:
        comment_id = post_to_brainstorm(report)
        print(f"\n✅ Posted as brainstorm comment #{comment_id} on page 'captain-stats' section 2.")
    else:
        print("\n(Dry run — use --post to write to brainstorm_comments.)")


if __name__ == '__main__':
    main()
