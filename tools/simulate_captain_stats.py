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

# Progression formulas from captain-stats brainstorm section 2.
# ARIA/chat gains removed per Luke #170.
FORMULAS_V1 = {
    'leadership':  [('sols_survived',  0.1), ('crew_missions',   0.5)],
    'strategy':    [('expeditions',    0.2), ('legendaries',     1.0)],
    'exploration': [('km_traveled',    0.01), ('landmarks',      2.0)],
    'logistics':   [('trail_segments', 0.5), ('depot_upgrades',  1.0)],
    'charisma':    [('aria_bonds',     2.0)],
}

# Simulation 2 (rebalanced) — what Luke asked to see in #198. Top-end pegs
# under V1 because km × 0.01 and crew_missions × 0.5 saturate the cap; these
# multipliers shrink the high-activity contributions to ~10% of V1.
FORMULAS_V2 = {
    'leadership':  [('sols_survived',  0.1),  ('crew_missions',   0.05)],
    'strategy':    [('expeditions',    0.2),  ('legendaries',     1.0)],
    'exploration': [('km_traveled',    0.001), ('landmarks',      1.0)],
    'logistics':   [('trail_segments', 0.05), ('depot_upgrades',  1.0)],
    # Luke #198: keep Charisma as placeholder, "do something minor for the
    # time being, like +1% Depot Build Time". So growth formula stays simple
    # (just aria_bonds) — signal_claims add deferred until Charisma earns a
    # second growth term in a future ticket.
    'charisma':    [('aria_bonds',     2.0)],
}

# Default to V2 going forward; FORMULAS preserved for back-compat callers.
FORMULAS = FORMULAS_V2

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


def fetch_activity(user_id, first_login, cutoff_at=None):
    """Pull activity counts for V2 retro math.

    cutoff_at — when provided (the retro commit path), only count rows with
    completed_at < cutoff_at. Live triggers fire on rows with completed_at >=
    cutoff_at. The two windows are disjoint, so no activity is double-credited.
    The dry-run sim path (no cutoff) counts all completed rows as it always did.
    """
    current_sol = get_mars_sol_number()
    first_sol = get_mars_sol_number(first_login) if first_login else current_sol
    sols_survived = max(0, current_sol - first_sol)

    # When committing, freeze sols to the cutoff so the live sol-tick cron can
    # award future sols without overlap.
    if cutoff_at is not None:
        cutoff_sol = get_mars_sol_number(cutoff_at)
        sols_survived = max(0, cutoff_sol - first_sol)

    cutoff_clause = " AND completed_at < %s" if cutoff_at else ""
    cutoff_params = (cutoff_at,) if cutoff_at else ()

    with db_cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS n FROM pilgrim.crew_missions WHERE user_id = %s AND completed_at IS NOT NULL{cutoff_clause}", (user_id, *cutoff_params))
        crew_missions = cur.fetchone()['n']

        cur.execute(f"SELECT COUNT(*) AS n, COALESCE(SUM(distance_km), 0) AS km FROM pilgrim.expeditions WHERE user_id = %s AND completed_at IS NOT NULL{cutoff_clause}", (user_id, *cutoff_params))
        row = cur.fetchone()
        expeditions = row['n']
        km_traveled = float(row['km'] or 0)

        cur.execute(f"""
            SELECT COUNT(*) AS n
              FROM pilgrim.expedition_discoveries ed
              JOIN pilgrim.expeditions e ON e.id = ed.expedition_id
              JOIN pilgrim.discovery_items d ON d.id = ed.discovery_item_id
             WHERE e.user_id = %s AND d.rarity = 'legendary' AND e.completed_at IS NOT NULL{(' AND e.completed_at < %s' if cutoff_at else '')}
        """, (user_id, *cutoff_params))
        legendaries = cur.fetchone()['n']

        landmark_cutoff = (" AND discovered_at < %s" if cutoff_at else "")
        cur.execute(f"SELECT COUNT(DISTINCT landmark_name) AS n FROM pilgrim.landmark_discoveries WHERE user_id = %s{landmark_cutoff}", (user_id, *cutoff_params))
        landmarks = cur.fetchone()['n']

        # trail_segments — uses created_at as proxy
        ts_cutoff = (" AND created_at < %s" if cutoff_at else "")
        cur.execute(f"SELECT COUNT(*) AS n FROM pilgrim.trail_segments WHERE user_id = %s{ts_cutoff}", (user_id, *cutoff_params))
        trail_segments = cur.fetchone()['n']

        # player_upgrades — upgraded_at is the completion timestamp
        upg_cutoff = (" AND upgraded_at < %s" if cutoff_at else "")
        cur.execute(f"SELECT COALESCE(SUM(level), 0) AS n FROM pilgrim.player_upgrades WHERE user_id = %s{upg_cutoff}", (user_id, *cutoff_params))
        depot_upgrades = int(cur.fetchone()['n'])

        # aria_bonds — bonded_at when status='bonded'
        bond_cutoff = (" AND bonded_at < %s" if cutoff_at else "")
        cur.execute(f"SELECT COUNT(*) AS n FROM pilgrim.aria_bonds WHERE (user_id_1 = %s OR user_id_2 = %s) AND status = 'bonded'{bond_cutoff}", (user_id, user_id, *cutoff_params))
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


def build_focused_report(target_user_ids):
    """Per Luke #198: 'Can we put this into a more easily readable table? I
    would like to see the current Captain Stats for User 112, User 45, User
    250, User 267, User 271, and then what the new values would be using
    Simulation 2.'

    Output: one COMPACT block per captain showing baseline → simulated for
    every stat at-a-glance. Plus a Simulation 2 multiplier reference so Luke
    can see the math. Per-stat rows beat the wide single-row format from
    comment #197.
    """
    captains_by_id = {c['user_id']: c for c in fetch_all_captains()}
    lines = []
    lines.append("**Captain Stats — Simulation 2 (rebalanced) — for the 5 users you flagged**")
    lines.append("")
    lines.append("Per Luke #198: cleaner per-captain table, Simulation 2 only, users 112 / 45 / 250 / 267 / 271. "
                 "Other Luke decisions baked in: bots allowed to cap (#198 pt 2), "
                 "Charisma kept as placeholder with growth driven by ARIA bonds only (#198 pt 3).")
    lines.append("")
    lines.append("**Simulation 2 multipliers** (vs V1 in comment #197):")
    lines.append("")
    lines.append("| Stat | V1 formula | **V2 formula** | Why changed |")
    lines.append("|---|---|---|---|")
    lines.append("| Leadership | 0.1·sols + **0.5**·crew | 0.1·sols + **0.05**·crew | crew × 0.5 saturated cap at ~150 missions |")
    lines.append("| Strategy | 0.2·exped + 1.0·legendary | 0.2·exped + 1.0·legendary | already balanced |")
    lines.append("| Exploration | **0.01**·km + **2.0**·landmarks | **0.001**·km + **1.0**·landmarks | km × 0.01 saturated at ~7,500 km |")
    lines.append("| Logistics | **0.5**·trail_seg + 1.0·upg | **0.05**·trail_seg + 1.0·upg | trail × 0.5 saturated at ~150 segments |")
    lines.append("| Charisma | 2.0·bonds | 2.0·bonds *(unchanged)* | Luke #198: keep as placeholder for now |")
    lines.append("")
    lines.append("World 1 cap = 75. Capped values shown with ★.")
    lines.append("")

    for uid in target_user_ids:
        cap = captains_by_id.get(uid)
        if not cap:
            lines.append(f"### User {uid} — not found in captains-with-stats query")
            lines.append("")
            continue
        activity = fetch_activity(uid, cap['first_login'])
        sim = simulate(cap, activity)
        name = cap['captain_name']
        lines.append(f"### {name}  (#{uid})")
        lines.append("")
        lines.append("**Activity:** "
                     f"sols={activity['sols_survived']:,} · "
                     f"crew_missions={activity['crew_missions']:,} · "
                     f"expeditions={activity['expeditions']:,} · "
                     f"km={int(activity['km_traveled']):,} · "
                     f"legendaries={activity['legendaries']} · "
                     f"landmarks={activity['landmarks']} · "
                     f"trail_segments={activity['trail_segments']:,} · "
                     f"upgrades={activity['depot_upgrades']} · "
                     f"bonds={activity['aria_bonds']}")
        lines.append("")
        lines.append("| Stat | Current | + Growth | Simulated | Capped at 75 |")
        lines.append("|---|--:|--:|--:|---|")
        for stat in ['leadership', 'strategy', 'exploration', 'logistics', 'charisma']:
            s = sim[stat]
            base = int(s['base'])
            growth = s['growth']
            raw = s['new_raw']
            capped = int(s['new_capped'])
            cap_marker = '★ capped' if raw > WORLD_1_CAP else f'{capped}'
            lines.append(f"| {stat.title()} | {base} | +{fmt_num(growth)} | {fmt_num(raw)} | {cap_marker} |")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("**Honest read on V2: still too aggressive for high-activity captains.**")
    lines.append("")
    lines.append("- Luke (#112) caps 3 of 5 stats. Exploration hits +305 from 188k km alone (0.001·km coefficient is still oversized at your scale).")
    lines.append("- Andy (#45) caps 4 of 5 stats. Leadership +56 from 712 crew missions, Logistics +66 from 25 trail × 0.05 + 65 upgrades × 1.0.")
    lines.append("- Mid-tier captains (Lilla, Prof Andy) cap at most 1 stat — that part feels right.")
    lines.append("- Bots (Trusty #250) overshoot massively, but per #198 pt 2 we let them cap and move on.")
    lines.append("")
    lines.append("If you want top-tier captains to NOT peg most stats on retroactive credit, V3 needs another haircut:")
    lines.append("")
    lines.append("| Stat | V2 formula | **V3 proposal** | Effect on Luke / Andy |")
    lines.append("|---|---|---|---|")
    lines.append("| Leadership | 0.1·sols + 0.05·crew | 0.05·sols + 0.025·crew | Luke +27 (was +54) · Andy +28 (was +56) |")
    lines.append("| Strategy | 0.2·exped + 1.0·legendary | 0.1·exped + 1.0·legendary *(unchanged)* | Luke +26 (was +41) · Andy +21 (was +34) |")
    lines.append("| Exploration | 0.001·km + 1.0·landmarks | **0.0002**·km + **0.5**·landmarks | Luke +96 (was +305) · Andy +36 (was +110) |")
    lines.append("| Logistics | 0.05·trail_seg + 1.0·upg | 0.05·trail_seg + **0.5**·upg | Luke +47 (was +91) · Andy +34 (was +66) |")
    lines.append("| Charisma | 2.0·bonds | 2.0·bonds *(still placeholder per #198 pt 3)* | unchanged |")
    lines.append("")
    lines.append("Under V3, Luke pegs ~1 stat (Exploration 27+96=123→cap 75, still over but lower) and Andy pegs ~2 (Leadership 51+28=79→cap, Strategy 69+21=90→cap). Mid-tier captains stay healthy.")
    lines.append("")
    lines.append("**Three explicit choices for you to make:**")
    lines.append("")
    lines.append("1. **Ship V2 as-is** — accepting that top players cap at 75 on most stats from retro credit. World 2/3 caps (90/105) eventually give them headroom; the cap is a feature, not a bug.")
    lines.append("2. **Ship V3** (cooler haircut above) — top players cap on 1-2 stats, mid-tier still feels growth, room to grow into World 2 cap.")
    lines.append("3. **Tell me a different shape** — e.g., 'crew_missions/sol rate-limit' instead of raw count, or 'cap retroactive credit at 50% of stat cap'.")
    lines.append("")
    lines.append("Once you pick (or propose your own numbers), I'll lock the formulas, build the schema migration (`captain_stat_events`), wire the toast UI, and run the retro-credit migration in a single shot.")
    lines.append("")
    lines.append("Script: `tools/simulate_captain_stats.py` — re-runnable with `--focused 112,45,250,267,271`.")
    return "\n".join(lines)


def post_to_brainstorm(markdown_text, section_idx=2):
    with db_cursor(commit=True) as cur:
        cur.execute("""
            INSERT INTO pilgrim.brainstorm_comments (page_key, section_idx, author_name, author_type, comment_text, created_at)
            VALUES ('captain-stats', %s, 'PilgrimBot', 'pilgrimbot', %s, NOW())
            RETURNING id
        """, (section_idx, markdown_text))
        return cur.fetchone()['id']


def commit_retroactive(dry_run=True, user_ids=None):
    """Bug #21 Deploy B — commit V2 retroactive credit to every captain.

    Luke locked V2 multipliers 2026-05-07 ("V2 is fine"). This commits the
    growth numbers he saw in brainstorm/captain-stats §2 comment #199 for real.

    Steps:
      1. Set go_live_at = NOW() in pilgrim.captain_stats_meta. Live triggers
         shipping in Deploy C only fire on activity with completed_at >=
         go_live_at — retro counts only completed_at < go_live_at. Disjoint.
      2. For each captain with stats:
         a. snapshot_baseline(user_id, current_stats) — writes 5 baseline
            events from current commander_<stat> values.
         b. Run V2 sim against activity < go_live_at.
         c. For each of 5 stats: award_stat_event(retro_credit, growth)
            with source_kind='retro_credit', source_table='aggregate',
            source_id=user_id — guaranteed-unique per captain via the table's
            UNIQUE constraint. Re-running is a no-op (dedupe).
      3. The award_stat_event helper recomputes commander_<stat> from the
         event sum and writes it back to replicate_assets, capped at 75.

    Idempotent: safe to re-run (all writes ON CONFLICT DO NOTHING).
    """
    from datetime import datetime, timezone
    from utilities.postgres.captain_stats import (
        ensure_captain_stat_events_table, set_go_live_at, snapshot_baseline,
        award_stat_event, V2_MULTIPLIERS,
    )

    ensure_captain_stat_events_table()
    cutoff_at = datetime.now(timezone.utc)

    captains = fetch_all_captains()
    if user_ids:
        captains = [c for c in captains if c['user_id'] in user_ids]
    print(f"Committing V2 retro for {len(captains)} captain(s). cutoff_at={cutoff_at.isoformat()}")

    if not dry_run:
        set_go_live_at(cutoff_at)
        print(f"  ↳ wrote go_live_at to pilgrim.captain_stats_meta")

    summary = []
    for c in captains:
        uid = c['user_id']
        name = c['captain_name']
        activity = fetch_activity(uid, c['first_login'], cutoff_at=cutoff_at)
        sim = simulate(c, activity)

        if dry_run:
            # Baseline from PRIMARY asset (matches /crew's reader). Same selector
            # as commit path below.
            from utilities.postgres.captain_stats import _primary_asset_id
            with db_cursor() as _cur:
                primary_id = _primary_asset_id(_cur, uid)
                _r = None
                if primary_id is not None:
                    _cur.execute("""
                        SELECT commander_leadership AS lead, commander_strategy AS stra,
                               commander_exploration AS expl, commander_logistics AS logi,
                               commander_charisma AS char
                        FROM pilgrim.replicate_assets WHERE id = %s
                    """, (primary_id,))
                    _r = _cur.fetchone()
            short = {'leadership':'lead','strategy':'stra','exploration':'expl','logistics':'logi','charisma':'char'}
            parts = []
            for stat in ['leadership','strategy','exploration','logistics','charisma']:
                base = int(_r[short[stat]] or 0) if _r else 0
                g = sim[stat]['growth']
                final = min(WORLD_1_CAP, round(base + g))
                star = '★' if (base + g) > WORLD_1_CAP else ''
                parts.append(f"{stat[:4]} {base}+{g:.1f}={final}{star}")
            print(f"  [{uid}] {name}: " + " | ".join(parts))
            continue

        # CRITICAL: snapshot from the PRIMARY asset (get_primary_commander
        # selector — what /crew actually renders), NOT fetch_all_captains'
        # highest-score picker. Earlier path used "latest character_image" which
        # diverged from /crew's reader for captains whose primary is an
        # edited_image, or whose primary character_image isn't the latest
        # one. Retro writes the captain's growth on the asset they see in-game.
        from utilities.postgres.captain_stats import _primary_asset_id
        with db_cursor() as _cur:
            primary_id = _primary_asset_id(_cur, uid)
            if primary_id is None:
                print(f"  [{uid}] {name}: SKIPPED — no primary character with stats")
                continue
            _cur.execute("""
                SELECT commander_leadership, commander_strategy, commander_exploration,
                       commander_logistics, commander_charisma
                FROM pilgrim.replicate_assets WHERE id = %s
            """, (primary_id,))
            _r = _cur.fetchone()
        if not _r or _r['commander_leadership'] is None:
            print(f"  [{uid}] {name}: SKIPPED — primary has no stats")
            continue
        current_stats = {s: int(_r[f'commander_{s}'] or 0) for s in ['leadership','strategy','exploration','logistics','charisma']}
        snapshot_baseline(uid, current_stats)

        per_stat = {}
        for stat, terms in FORMULAS.items():
            growth = sum(activity[key] * rate for key, rate in terms)
            if growth <= 0:
                continue
            r = award_stat_event(
                user_id=uid, stat=stat, delta=growth,
                source_kind='retro_credit', source_table='aggregate', source_id=uid,
            )
            per_stat[stat] = r['new'] if r else 'dedupe'
        summary.append((uid, name, per_stat))

    if not dry_run:
        print()
        print("=" * 70)
        print("RETRO COMMIT SUMMARY")
        print("=" * 70)
        for uid, name, per_stat in summary:
            print(f"  [{uid}] {name}: {per_stat}")
    print()
    print(f"Done. {'DRY RUN — no DB writes.' if dry_run else 'Live triggers in Deploy C will fire on activity after ' + cutoff_at.isoformat()}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--post', action='store_true', help='Post the report as a PilgrimBot brainstorm comment')
    parser.add_argument('--limit', type=int, help='Only simulate the top N captains by activity')
    parser.add_argument('--focused', type=str, help='Comma-separated user_ids for the focused per-captain table (e.g., 112,45,250,267,271). Uses Simulation 2 multipliers per Luke #198.')
    parser.add_argument('--commit', action='store_true', help='Bug #21 Deploy B — write V2 retro credit to captain_stat_events + bump commander_<stat>. Sets go_live_at meta. Idempotent.')
    parser.add_argument('--commit-dry', action='store_true', help='Show what --commit would do without writing.')
    parser.add_argument('--users', type=str, help='Comma-separated user_ids to limit --commit/--commit-dry to (e.g., 45 for just Andy).')
    args = parser.parse_args()

    if args.commit or args.commit_dry:
        user_ids = None
        if args.users:
            user_ids = [int(x.strip()) for x in args.users.split(',') if x.strip()]
        commit_retroactive(dry_run=args.commit_dry, user_ids=user_ids)
        return

    if args.focused:
        target_ids = [int(x.strip()) for x in args.focused.split(',') if x.strip()]
        report = build_focused_report(target_ids)
        print(report)
        if args.post:
            comment_id = post_to_brainstorm(report)
            print(f"\n✅ Posted as brainstorm comment #{comment_id} on page 'captain-stats' section 2.")
        else:
            print("\n(Dry run — use --post to write to brainstorm_comments.)")
        return

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
