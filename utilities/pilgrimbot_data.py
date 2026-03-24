"""
PilgrimBot player data queries — tool for fetching live game state on demand.
Used by pilgrimbot_utils.py when PilgrimBot needs to answer questions about
a specific player's colony, upgrades, expeditions, etc.
"""

import logging
from utilities.postgres_utils import db_cursor

logger = logging.getLogger("pilgrimbot")


PLAYER_DATA_TOOL = {
    "name": "query_player_data",
    "description": "Fetch live game data for any player. Use categories from the PLAYER DATA MAP.",
    "input_schema": {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "enum": ["balance", "shard_generation", "sv_sources", "upgrades", "infrastructure", "building_queue",
                         "expeditions", "research", "crew_missions", "discoveries",
                         "signal_claims", "overview", "leaderboard"],
                "description": "Which data category to fetch"
            },
            "user_id": {
                "type": "integer",
                "description": "Player user ID. Use the current user's ID if asking about 'my' data."
            }
        },
        "required": ["category", "user_id"]
    }
}

PLAYER_DATA_MAP = """PLAYER DATA MAP (use query_player_data tool to fetch any category):
  overview          — Captain name, account age, balance, tier, playstyle summary
  balance           — Shard balance, generation rate summary, accumulated unharvested
  shard_generation  — DETAILED shard generation: every source, every multiplier, every bonus, environmental factors. USE THIS when user asks about income/generation.
  sv_sources        — Science Value economy: ALL SV sources (passive, extraction, expeditions, trails, milestones), collection milestone progress
  upgrades          — All upgrade levels by category (vehicles, rovers, scanners, etc.)
  infrastructure    — Colony buildings, levels, construction status
  building_queue    — Items currently under construction with ready times
  expeditions       — Active expeditions with ETAs, recent completed, total count
  research          — Active research, SV balance, completed techs by branch
  crew_missions     — Captain/Scientist/ARIA trail missions with time remaining
  discoveries       — Unclaimed/total discoveries, storage capacity
  signal_claims     — Origin site claims, ARIA bonds
  leaderboard       — Top players by shards, expeditions, and research (no user_id needed)
"""


def query_player_data(category, user_id):
    """Fetch specific player data by category. Returns formatted string."""
    from datetime import datetime, timezone
    try:
        if category == 'overview':
            from utilities.postgres_utils import get_user_commander
            from utilities.aria_utils import get_aria_relationship_tier, analyze_playstyle
            commander = get_user_commander(user_id)
            tier = get_aria_relationship_tier(user_id)
            playstyle = analyze_playstyle(user_id)
            with db_cursor() as cur:
                cur.execute("SELECT current_balance_eth FROM pilgrim.sepolia_assets WHERE user_id = %s AND is_primary_wallet = true", (user_id,))
                w = cur.fetchone()
            balance = float(w['current_balance_eth']) * 10000000 if w and w['current_balance_eth'] else 0
            return (f"Captain: {commander.get('name', 'Unknown') if commander else 'Unknown'}\n"
                    f"Days on Mars: {tier.get('account_days', '?')}\n"
                    f"Balance: {balance:,.0f} shards\n"
                    f"Tier: {tier.get('tier_name', '?')} ({tier.get('tier_level', '?')}/5)\n"
                    f"Expeditions completed: {tier.get('expeditions', 0)}\n"
                    f"Playstyle: {playstyle.get('primary_style', '?')}\n"
                    f"Activity: {playstyle.get('activity_level', '?')}")

        elif category == 'balance':
            with db_cursor() as cur:
                cur.execute("SELECT current_balance_eth, wallet_address FROM pilgrim.sepolia_assets WHERE user_id = %s AND is_primary_wallet = true", (user_id,))
                w = cur.fetchone()
            if not w:
                return "No wallet found for this user."
            balance = float(w['current_balance_eth']) * 10000000 if w['current_balance_eth'] else 0
            try:
                from utilities.infrastructure_utils import calculate_accumulated_income
                calc = calculate_accumulated_income(user_id)
                rb = calc.get('rate_breakdown', {})
                bonuses = calc.get('bonuses_applied', {})
                generators = calc.get('generators_breakdown', [])
                gen_lines = [f"  {g['name']}: {g['hourly_rate']:.1f}/hr" for g in generators]
                return (f"Balance: {balance:,.0f} shards\n"
                        f"Effective shard rate: {rb.get('actual_avg_rate', 0):.1f}/hr\n"
                        f"Base hourly rate: {rb.get('base_hourly_rate', 0):.1f}/hr\n"
                        f"Passive income bonus: +{(bonuses.get('passive_income_mult', 1) - 1) * 100:.0f}%\n"
                        f"Tech bonus: +{(bonuses.get('tech_passive_mult', 1) - 1) * 100:.0f}%\n"
                        f"All-generation bonus: +{(bonuses.get('all_generation_mult', 1) - 1) * 100:.0f}%\n"
                        f"Scientist shard bonus: +{(bonuses.get('scientist_shard_mult', 1) - 1) * 100:.0f}%\n"
                        f"Mining drone bonus: +{bonuses.get('passive_income_base', 0)}/hr\n"
                        f"Day/night efficiency: {rb.get('day_night_efficiency', 0):.0f}%\n"
                        f"Mars environment multiplier: {rb.get('mars_env_multiplier', 0):.0f}%\n"
                        f"Generators:\n" + "\n".join(gen_lines) if gen_lines else "" +
                        f"\nAccumulated (unharvested): {calc.get('total_accumulated', 0):.1f} shards\n"
                        f"SV generation: {calc.get('sv_hourly_rate', 0):.1f} SV/hr")
            except Exception:
                return f"Balance: {balance:,.0f} shards"

        elif category == 'shard_generation':
            from utilities.infrastructure_utils import calculate_accumulated_income
            calc = calculate_accumulated_income(user_id)
            rb = calc.get('rate_breakdown', {})
            bonuses = calc.get('bonuses_applied', {})
            generators = calc.get('generators_breakdown', [])
            env = rb.get('mars_env_factors', {})
            lines = ["=== SHARD GENERATION DETAILED BREAKDOWN ==="]
            lines.append(f"Effective average rate: {rb.get('actual_avg_rate', 0):.1f} shards/hr")
            lines.append(f"Theoretical max rate: {rb.get('theoretical_max_rate', 0):.1f} shards/hr")
            lines.append(f"Base hourly rate (all generators): {rb.get('base_hourly_rate', 0):.1f}/hr")
            lines.append("")
            lines.append("GENERATORS:")
            for g in generators:
                lines.append(f"  {g['name']}: {g['hourly_rate']:.1f}/hr"
                             + (" (day/night affected)" if g.get('has_day_night') else "")
                             + (" (latitude affected)" if g.get('latitude_affected') else ""))
            lines.append("")
            lines.append("MULTIPLIERS & BONUSES:")
            lines.append(f"  Passive income bonus: +{(bonuses.get('passive_income_mult', 1) - 1) * 100:.0f}%")
            src = bonuses.get('passive_income_source')
            if src:
                lines.append(f"    Source: {src.get('name', '?')} (+{(float(src.get('mult', 1)) - 1) * 100:.0f}%)")
            lines.append(f"  Tech tree bonus: +{(bonuses.get('tech_passive_mult', 1) - 1) * 100:.0f}%")
            lines.append(f"  All-generation bonus: +{(bonuses.get('all_generation_mult', 1) - 1) * 100:.0f}%")
            lines.append(f"  Scientist shard bonus: +{(bonuses.get('scientist_shard_mult', 1) - 1) * 100:.0f}% (+2% per analysis point, max +100% at 50)")
            lines.append(f"  Mining drone flat bonus: +{bonuses.get('passive_income_base', 0)}/hr")
            lines.append("")
            lines.append("ENVIRONMENTAL FACTORS:")
            lines.append(f"  Day/night cycle efficiency: {rb.get('day_night_efficiency', 0):.0f}%")
            lines.append(f"  Mars environment combined: {rb.get('mars_env_multiplier', 0):.0f}%")
            lines.append(f"    Dust: {env.get('dust', 1):.0%} ({env.get('dust_condition', '?')})")
            lines.append(f"    Temperature: {env.get('temperature', 1):.0%} ({env.get('temp_celsius', '?')}C)")
            lines.append(f"    Latitude: {env.get('latitude', 1):.0%}")
            lines.append("")
            lines.append("ACCUMULATION STATUS:")
            lines.append(f"  Unharvested shards: {calc.get('total_accumulated', 0):.1f}")
            lines.append(f"  Has battery (night gen): {'Yes' if calc.get('has_battery') else 'No'}")
            lines.append(f"  Has maintenance drone: {'Yes' if calc.get('has_maintenance_drone') else 'No'}")
            lines.append(f"  Any dust-covered: {'Yes' if calc.get('any_dust_covered') else 'No'}")
            lines.append(f"  Any at accumulation cap: {'Yes' if calc.get('any_at_cap') else 'No'}")
            if calc.get('any_at_cap'):
                lines.append(f"  Cap: {calc.get('cap_days', 7)} days — MUST harvest to resume generation")
            lines.append(f"  SV generation: {calc.get('sv_hourly_rate', 0):.1f} SV/hr")
            return "\n".join(lines)

        elif category == 'sv_sources':
            lines = ["=== SCIENCE VALUE (SV) SOURCES ==="]
            # 1. Passive generation (any building with science_generation_rate)
            try:
                from utilities.infrastructure_utils import calculate_accumulated_income, get_user_infrastructure, INFRASTRUCTURE_CATALOG
                from utilities.upgrades_utils import get_infrastructure_level
                calc = calculate_accumulated_income(user_id)
                sv_rate = calc.get('sv_hourly_rate', 0)
                # List actual SV-generating buildings the user owns
                sv_buildings = []
                for infra in get_user_infrastructure(user_id):
                    if infra['status'] != 'active':
                        continue
                    cat = INFRASTRUCTURE_CATALOG.get(infra['structure_type'], {})
                    level = get_infrastructure_level(user_id, infra['structure_type'])
                    level_data = cat.get('levels', {}).get(max(1, level), {})
                    sg_rate = level_data.get('science_generation_rate', 0)
                    if sg_rate > 0:
                        sv_buildings.append(f"{cat.get('name', infra['structure_type'])} Lv{level} ({sg_rate:.0f} SV/hr)")
                source_text = ', '.join(sv_buildings) if sv_buildings else 'no SV-generating buildings'
                lines.append(f"PASSIVE GENERATION: {sv_rate:.1f} SV/hr")
                lines.append(f"  Sources: {source_text}")
                lines.append(f"  SV accumulated (unharvested): {calc.get('sv_accumulated', 0):.1f}")
            except Exception:
                lines.append("PASSIVE GENERATION: unable to calculate")
            # 2. Extraction bonus
            lines.append(f"EXTRACTION BONUS: 50% of shard value when sharding items")
            # 3. Expedition SV
            lines.append(f"EXPEDITION SV: 100-2,000 SV per completed expedition (scales with distance)")
            lines.append(f"  Short (<200km): 100-200 SV | Medium (200-500km): 200-500 SV")
            lines.append(f"  Long (500-1500km): 500-1,000 SV | Epic (1500+km): 1,000-2,000 SV")
            # 4. Trail SV
            lines.append(f"TRAIL BUILDING: 5 SV per km of trail built")
            # 5. Collection milestones
            try:
                from utilities.sv_milestones import get_user_milestones
                ms = get_user_milestones(user_id)
                lines.append(f"\nCOLLECTION MILESTONES (Dr. Bo's Research Program):")
                lines.append(f"  Total items analyzed: {ms['total_analyzed']}")
                for m in ms['all_milestones']:
                    if m['earned'] or ms['total_analyzed'] >= m['threshold']:
                        status = "EARNED"
                    else:
                        status = f"{m['threshold'] - ms['total_analyzed']} more needed"
                    lines.append(f"  {m['name']} ({m['threshold']} items): +{m['sv_reward']} SV — {status}")
                if ms['next']:
                    lines.append(f"\n  NEXT MILESTONE: {ms['next']['name']} — {ms['next']['items_remaining']} items to go (+{ms['next']['sv_reward']} SV)")
            except Exception as e:
                lines.append(f"COLLECTION MILESTONES: error loading ({e})")
            return "\n".join(lines)

        elif category == 'upgrades':
            from utilities.upgrades_utils import get_all_user_upgrades, get_upgrade_stats
            from utilities.legacy_migration import ensure_legacy_migrated
            ensure_legacy_migrated(user_id)
            all_ups = get_all_user_upgrades(user_id)
            lines = []
            for cat, items in sorted(all_ups.items()):
                if items:
                    item_strs = []
                    for k, v in sorted(items.items()):
                        entry = f"{k}: Lv{v}"
                        # Include key stats for vehicles so PilgrimBot can answer speed/range questions
                        if cat == 'vehicles' and v > 0:
                            stats = get_upgrade_stats('vehicles', k, v)
                            if stats:
                                spd = stats.get('expedition_speed_mult', 1.0)
                                rng = stats.get('max_range_km', 0)
                                cargo = stats.get('cargo', 0)
                                entry += f" (speed {spd}x = {2.0 * spd:.0f} km/h, range {rng} km, cargo {cargo})"
                        item_strs.append(entry)
                    lines.append(f"  {cat}: {', '.join(item_strs)}")
            if lines:
                result = "Upgrades:\n" + "\n".join(lines)
                result += f"\n\nNote: Vehicle speed = BASE_SPEED (2.0 km/h) x speed_mult x captain_logistics x terrain x trail"
                return result
            return "No upgrades yet."

        elif category == 'infrastructure':
            with db_cursor() as cur:
                cur.execute("""
                    SELECT ci.structure_type, ci.status, ci.ready_at,
                           COALESCE(pu.level, 1) as level, pu.pending_level, pu.ready_at as upgrade_ready_at
                    FROM pilgrim.colony_infrastructure ci
                    LEFT JOIN pilgrim.player_upgrades pu ON pu.user_id = ci.user_id
                        AND pu.category = 'infrastructure' AND pu.item_key = ci.structure_type
                    WHERE ci.user_id = %s
                """, (user_id,))
                rows = cur.fetchall()
            if not rows:
                return "No infrastructure built yet."
            lines = []
            for r in rows:
                line = f"  {r['structure_type']}: Lv{r['level']} ({r['status']})"
                if r['pending_level']:
                    line += f" → upgrading to Lv{r['pending_level']}"
                    if r['upgrade_ready_at']:
                        line += f" (ready: {r['upgrade_ready_at'].isoformat()})"
                lines.append(line)
            return "Infrastructure:\n" + "\n".join(lines)

        elif category == 'building_queue':
            with db_cursor() as cur:
                cur.execute("""
                    SELECT category, item_key, level, pending_level, ready_at
                    FROM pilgrim.player_upgrades
                    WHERE user_id = %s AND pending_level IS NOT NULL AND ready_at > NOW()
                    ORDER BY ready_at ASC
                """, (user_id,))
                rows = cur.fetchall()
            if not rows:
                return "Nothing under construction."
            lines = []
            for r in rows:
                lines.append(f"  {r['item_key']} ({r['category']}): Lv{r['level']} → Lv{r['pending_level']} — ready {r['ready_at'].isoformat()}")
            return f"Building queue ({len(rows)} items):\n" + "\n".join(lines)

        elif category == 'expeditions':
            with db_cursor() as cur:
                cur.execute("""
                    SELECT destination_name, arrives_at, return_arrives_at, status, vehicle_type
                    FROM pilgrim.expeditions WHERE user_id = %s AND status IN ('traveling', 'returning')
                """, (user_id,))
                active = cur.fetchall()
                cur.execute("SELECT COUNT(*) as total FROM pilgrim.expeditions WHERE user_id = %s AND status = 'complete'", (user_id,))
                total = cur.fetchone()['total']
                cur.execute("""
                    SELECT destination_name, vehicle_type, sepolia_earned, distance_km
                    FROM pilgrim.expeditions WHERE user_id = %s AND status = 'complete'
                    ORDER BY created_at DESC LIMIT 5
                """, (user_id,))
                recent = cur.fetchall()
            lines = [f"Total completed: {total}"]
            if active:
                lines.append(f"Active ({len(active)}):")
                for e in active:
                    lines.append(f"  {e['destination_name']} via {e['vehicle_type']} — {e['status']}, ETA: {e['arrives_at'].isoformat() if e['arrives_at'] else '?'}")
            if recent:
                lines.append("Recent:")
                for e in recent:
                    earned = float(e['sepolia_earned'] or 0)
                    lines.append(f"  {e['destination_name']} ({e['vehicle_type']}) — {earned:,.0f} shards, {float(e['distance_km'] or 0):,.0f} km")
            return "\n".join(lines)

        elif category == 'research':
            from utilities.tech_utils import _get_available_sv
            sv = _get_available_sv(user_id)
            with db_cursor() as cur:
                cur.execute("""
                    SELECT branch, tech_key, branch_level, research_started_at, research_duration_seconds
                    FROM pilgrim.player_techs WHERE user_id = %s AND status = 'researching'
                """, (user_id,))
                active = cur.fetchone()
                cur.execute("""
                    SELECT branch, COUNT(*) as count FROM pilgrim.player_techs
                    WHERE user_id = %s AND status = 'completed' GROUP BY branch
                """, (user_id,))
                completed = cur.fetchall()
            lines = [f"SV balance: {sv:,.0f}"]
            if active:
                now = datetime.now(timezone.utc)
                started = active['research_started_at']
                if started and started.tzinfo is None:
                    started = started.replace(tzinfo=timezone.utc)
                remaining = max(0, active['research_duration_seconds'] - (now - started).total_seconds()) if started else 0
                hrs = int(remaining // 3600)
                lines.append(f"Researching: {active['tech_key']} (branch: {active['branch']}, ~{hrs}h remaining)")
            for c in completed:
                lines.append(f"  {c['branch']}: {c['count']} techs completed")
            return "\n".join(lines) if lines else "No research activity."

        elif category == 'crew_missions':
            with db_cursor() as cur:
                cur.execute("""
                    SELECT captain_mission_ends_at, captain_mission_target,
                           scientist_mission_ends_at, scientist_mission_target,
                           aria_mission_ends_at, aria_mission_target
                    FROM pilgrim.users WHERE id = %s
                """, (user_id,))
                row = cur.fetchone()
            if not row:
                return "User not found."
            now = datetime.now(timezone.utc)
            lines = []
            for member in ['captain', 'scientist', 'aria']:
                ends_at = row.get(f'{member}_mission_ends_at')
                target = row.get(f'{member}_mission_target')
                if ends_at and target:
                    if ends_at.tzinfo is None:
                        ends_at = ends_at.replace(tzinfo=timezone.utc)
                    if ends_at > now:
                        remaining = int((ends_at - now).total_seconds() / 60)
                        lines.append(f"  {member.title()}: heading to {target} (~{remaining} min remaining)")
                    else:
                        lines.append(f"  {member.title()}: returned from {target}")
                else:
                    lines.append(f"  {member.title()}: idle (no active mission)")
            return "Crew missions:\n" + "\n".join(lines)

        elif category == 'discoveries':
            with db_cursor() as cur:
                cur.execute("""
                    SELECT COUNT(*) FILTER (WHERE NOT ed.claimed_by_user) as unclaimed, COUNT(*) as total
                    FROM pilgrim.expedition_discoveries ed
                    JOIN pilgrim.expeditions e ON ed.expedition_id = e.id WHERE e.user_id = %s
                """, (user_id,))
                disc = cur.fetchone()
            from utilities.upgrades_utils import get_user_upgrade_effects
            effects = get_user_upgrade_effects(user_id)
            cap = effects.get('storage_capacity', 300)
            return (f"Discoveries: {disc['total'] or 0} total, {disc['unclaimed'] or 0} unclaimed\n"
                    f"Storage capacity: {cap}")

        elif category == 'signal_claims':
            with db_cursor() as cur:
                cur.execute("""
                    SELECT os.site_code, os.mission_name, sc.claim_tier, sc.claim_rank
                    FROM pilgrim.site_claims sc
                    JOIN pilgrim.origin_sites os ON sc.origin_site_id = os.id WHERE sc.user_id = %s
                """, (user_id,))
                claims = cur.fetchall()
                cur.execute("""
                    SELECT landmark_name, status FROM pilgrim.aria_bonds
                    WHERE user_id_1 = %s OR user_id_2 = %s
                """, (user_id, user_id))
                bonds = cur.fetchall()
            lines = []
            if claims:
                lines.append(f"Origin claims ({len(claims)}):")
                for c in claims:
                    lines.append(f"  {c['site_code']}: {c['mission_name']} (tier {c['claim_tier']}, rank #{c['claim_rank']})")
            else:
                lines.append("No origin site claims.")
            if bonds:
                lines.append(f"ARIA bonds ({len(bonds)}):")
                for b in bonds:
                    lines.append(f"  {b['landmark_name']}: {b['status']}")
            return "\n".join(lines)

        elif category == 'leaderboard':
            with db_cursor() as cur:
                cur.execute("""
                    SELECT u.id, COALESCE(ra.commander_name, u.name) as name, sa.current_balance_eth
                    FROM pilgrim.users u
                    JOIN pilgrim.sepolia_assets sa ON u.id = sa.user_id AND sa.is_primary_wallet = true
                    LEFT JOIN pilgrim.replicate_assets ra ON u.id = ra.user_id AND ra.is_primary_character = true
                    WHERE sa.current_balance_eth > 0
                    ORDER BY sa.current_balance_eth DESC LIMIT 5
                """)
                top_shards = cur.fetchall()
                cur.execute("""
                    SELECT u.id, COALESCE(ra.commander_name, u.name) as name, COUNT(*) as exp_count
                    FROM pilgrim.users u
                    JOIN pilgrim.expeditions e ON u.id = e.user_id AND e.status = 'complete'
                    LEFT JOIN pilgrim.replicate_assets ra ON u.id = ra.user_id AND ra.is_primary_character = true
                    GROUP BY u.id, ra.commander_name, u.name ORDER BY exp_count DESC LIMIT 5
                """)
                top_exp = cur.fetchall()
                cur.execute("""
                    SELECT u.id, COALESCE(ra.commander_name, u.name) as name, COUNT(*) as tech_count
                    FROM pilgrim.users u
                    JOIN pilgrim.player_techs pt ON u.id = pt.user_id AND pt.status = 'completed'
                    LEFT JOIN pilgrim.replicate_assets ra ON u.id = ra.user_id AND ra.is_primary_character = true
                    GROUP BY u.id, ra.commander_name, u.name ORDER BY tech_count DESC LIMIT 5
                """)
                top_tech = cur.fetchall()
            lines = ["=== LEADERBOARD ===", "Top by Shards:"]
            for i, r in enumerate(top_shards):
                bal = float(r['current_balance_eth'] or 0) * 10000000
                lines.append(f"  {i+1}. {r['name']} — {bal:,.0f} shards")
            lines.append("Top by Expeditions:")
            for i, r in enumerate(top_exp):
                lines.append(f"  {i+1}. {r['name']} — {r['exp_count']} completed")
            lines.append("Top by Research:")
            for i, r in enumerate(top_tech):
                lines.append(f"  {i+1}. {r['name']} — {r['tech_count']} techs")
            return "\n".join(lines)

        else:
            return f"Unknown category: {category}"
    except Exception as e:
        logger.error(f"query_player_data({category}, {user_id}) failed: {e}")
        return f"Error fetching {category}: {e}"
