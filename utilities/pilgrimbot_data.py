"""
PilgrimBot player data queries — tool for fetching live game state on demand.
Used by pilgrimbot_utils.py when PilgrimBot needs to answer questions about
a specific player's colony, upgrades, expeditions, etc.
"""

import logging
from utilities.postgres.core import db_cursor

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
                         "signal_claims", "overview", "leaderboard", "robot",
                         "discovery_catalog", "discovery_analytics", "discovery_ledger", "map_geography"],
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
  overview          — Captain name, scientist name/stats, account age, balance, tier, playstyle summary
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
  robot             — Fourth crew member (Step 4d): Narog Foundry level, build status, current visual stage, time until next stage, role dial split, source manifest of items used to forge each stage
  leaderboard       — Top players by shards, expeditions, and research (no user_id needed)
  discovery_catalog — Full discovery-item catalog grouped by rarity (Common/Uncommon/Rare/Legendary): count + % of catalog per rarity, top items by trade value, distance bands. USE THIS when user asks about what items exist or rarity tiers.
  discovery_analytics — Per-user discovery audit: actual rarity finds vs expected (computed by replaying each expedition's stored captain stats + distance through the actual drop-weight formula in discovery_utils.get_progressive_weights). Shows expedition-band breakdown so users can see WHY their drop rate is what it is (e.g. legendary weight is 0 below 300 km AND for first 19 expeditions). USE THIS when user suspects rare/legendary finds are too low.
  discovery_ledger — Per-user discovery LEDGER (item-level granularity): last legendary/rare/uncommon find with item_name + destination + distance_km + unlocked_at timestamp + claim status, plus per-rarity totals and the last 15 discoveries chronologically. USE THIS when user asks "when did I last find a legendary/rare?", "what was my most recent discovery?", "show me my finds over time", or any per-item question with timestamps.
  map_geography     — Mars destination geography: total named landmarks on the planet (pilgrim.mars_mappings), total origin sites, captain's home coords, current fog-of-war radius + formula, landmarks inside fog right now, unique landmarks visited, total trips taken. USE THIS for ANY question about "how many destinations", "how many can I visit", "how big is the map", "what can I see", "places I've been".
"""


def query_player_data(category, user_id):
    """Fetch specific player data by category. Returns formatted string."""
    from datetime import datetime, timezone
    try:
        if category == 'overview':
            from utilities.postgres.assets import get_user_commander
            from utilities.postgres.users import get_user_scientist
            from utilities.aria.relationship import get_aria_relationship_tier
            from utilities.aria.snapshot import analyze_playstyle
            commander = get_user_commander(user_id)
            scientist = get_user_scientist(user_id)
            tier = get_aria_relationship_tier(user_id)
            playstyle = analyze_playstyle(user_id)
            with db_cursor() as cur:
                cur.execute("SELECT current_balance_eth FROM pilgrim.sepolia_assets WHERE user_id = %s AND is_primary_wallet = true", (user_id,))
                w = cur.fetchone()
            balance = float(w['current_balance_eth']) * 10000000 if w and w['current_balance_eth'] else 0
            sci_line = ""
            if scientist:
                s = scientist.get('stats', {})
                sci_line = (f"Scientist: {scientist.get('name', 'None')} ({scientist.get('specialty', '?')} specialist)\n"
                           f"  Stats: Nav {s.get('navigation', 0)}, Analysis {s.get('analysis', 0)}, "
                           f"Geology {s.get('geology', 0)}, Engineering {s.get('engineering', 0)}\n")
            else:
                sci_line = "Scientist: None assigned\n"
            return (f"Captain: {commander.get('name', 'Unknown') if commander else 'Unknown'}\n"
                    f"{sci_line}"
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
                        f"SV generation: {calc.get('sv_hourly_rate', 0):.1f} SV/hr"
                        + (f" (base {calc.get('sv_base_rate', 0):.1f} + {calc['sv_scientist_name']} Analysis x{calc['sv_scientist_bonus']:.1f})" if calc.get('sv_scientist_name') and calc.get('sv_scientist_extra', 0) > 0 else f" (from buildings)"))
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
            sig_bonus = calc.get('signal_bonus', {})
            if sig_bonus.get('sites_count', 0) > 0:
                lines.append(f"  Signal Network flat bonus: +{sig_bonus.get('shards_per_hour', 0):.1f}/hr shards, +{sig_bonus.get('sv_per_hour', 0):.1f}/hr SV ({sig_bonus['sites_count']} claimed site{'s' if sig_bonus['sites_count'] != 1 else ''})")
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
                base_rate = calc.get('sv_base_rate', 0)
                sci_name = calc.get('sv_scientist_name')
                sci_bonus = calc.get('sv_scientist_bonus', 1.0)
                sci_extra = calc.get('sv_scientist_extra', 0)
                lines.append(f"PASSIVE GENERATION: {sv_rate:.1f} SV/hr")
                lines.append(f"  Building sources ({base_rate:.1f} SV/hr base): {source_text}")
                if sci_name and sci_extra > 0:
                    lines.append(f"  Scientist bonus: {sci_name} (Analysis) ×{sci_bonus:.1f} = +{sci_extra:.1f} SV/hr")
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
                # Phase 2.3b — pending + active signal_claim expeditions
                cur.execute("""
                    SELECT id, destination_name, status, return_arrives_at, cinematic_shown_at
                    FROM pilgrim.expeditions
                    WHERE user_id = %s AND expedition_type = 'signal_claim'
                    ORDER BY id DESC LIMIT 5
                """, (user_id,))
                signal_trips = cur.fetchall()
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
            if signal_trips:
                lines.append(f"Signal-claim expeditions ({len(signal_trips)}, Phase 2.3b two-step flow):")
                for t in signal_trips:
                    cin = 'cinematic_seen' if t['cinematic_shown_at'] else 'cinematic_pending'
                    lines.append(f"  exp#{t['id']} → {t['destination_name']}: {t['status']} ({cin})")
            lines.append("Two-step claim flow (Phase 2.3b): detect on a normal expedition → click 'Plan Claim Expedition' on /signal or the map → dedicated signal_claim trip launches → cinematic plays on arrival → site claimed.")
            return "\n".join(lines)

        elif category == 'robot':
            from utilities.postgres.robot import get_robot_page_data
            data = get_robot_page_data(user_id) or {}
            lines = ["=== ROBOT CREW MEMBER (Step 4d) ==="]
            lines.append(f"Narog Foundry: Lv{data.get('lab_level', 0)} ({'unlocked' if data.get('lab_unlocked') else 'LOCKED — needs Research Station Lv3 + Regolith Forge Lv3'})")
            if not data.get('has_robot'):
                lines.append("Build status: NOT STARTED")
                if data.get('lab_unlocked'):
                    lines.append("Captain can begin construction from /crew → Robot tab.")
                return "\n".join(lines)
            robot = data.get('robot') or {}
            lines.append(f"Name: {robot.get('name') or '(unnamed)'}")
            lines.append(f"Build status: {robot.get('build_status', '?')}")
            lines.append(f"Visual stage: {robot.get('visual_stage', 0)}/5")
            lines.append(f"Stages forged: {sum(1 for s in (data.get('stages') or []) if s.get('status') == 'complete')}/5")
            secs = data.get('seconds_until_next_stage')
            if secs is not None and not data.get('is_complete'):
                if secs >= 3600:
                    lines.append(f"Next stage ready in: {secs // 3600}h {(secs % 3600) // 60}m")
                elif secs >= 60:
                    lines.append(f"Next stage ready in: {secs // 60}m {secs % 60}s")
                else:
                    lines.append(f"Next stage ready in: {secs}s")
            dial = robot.get('dial') or {}
            if dial:
                lines.append(f"Robot Allocation: exploration {dial.get('exploration', 0)}% · logistics {dial.get('logistics', 0)}% · research {dial.get('research', 0)}% · expeditions {dial.get('expeditions', 0)}%")
            if data.get('is_complete'):
                lines.append("CONSTRUCTION COMPLETE — robot is ready to deploy.")
                lines.append(f"Cinematic played: {'yes' if robot.get('cinematic_played') else 'NO (build-complete celebration pending)'}")
            # Per-stage source manifest (the real items the robot was forged from)
            stages = data.get('stages') or []
            if stages:
                lines.append("Build manifest (real items recovered on expeditions):")
                for s in stages:
                    src = s.get('source') or {}
                    status = s.get('status', '?')
                    item = src.get('item_name') or '?'
                    landmark = src.get('landmark_name') or '?'
                    lines.append(f"  Stage {s.get('idx')}: {s.get('label')} [{status}] — {item} from {landmark}")
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

        elif category == 'discovery_catalog':
            from utilities.postgres.expeditions import get_discovery_items_catalog
            items = get_discovery_items_catalog()
            if not items:
                return "Discovery catalog is empty."
            buckets = {'common': [], 'uncommon': [], 'rare': [], 'legendary': []}
            for it in items:
                r = (it.get('rarity') or 'common').lower()
                if r in buckets:
                    buckets[r].append(it)
            total = len(items)
            lines = ["=== DISCOVERY ITEM CATALOG ==="]
            lines.append(f"Total active items: {total}")
            lines.append("")
            lines.append("CATALOG COMPOSITION (what % of distinct items are each rarity — NOT drop rates):")
            for r in ('common', 'uncommon', 'rare', 'legendary'):
                n = len(buckets[r])
                pct = (n / total * 100) if total else 0
                lines.append(f"  {r.title():10s}: {n} items ({pct:.1f}%)")
            for r in ('legendary', 'rare', 'uncommon', 'common'):
                bucket = buckets[r]
                if not bucket:
                    continue
                lines.append("")
                lines.append(f"--- {r.upper()} ({len(bucket)}) — top 5 by trade value ---")
                top = sorted(bucket, key=lambda x: float(x.get('base_trade_value_eth') or 0), reverse=True)[:5]
                for it in top:
                    shards = float(it.get('base_trade_value_eth') or 0) * 10000000
                    sv = it.get('base_scientific_value') or 0
                    mind = it.get('min_distance_km') or 0
                    maxd = it.get('max_distance_km') or 0
                    lines.append(f"  • {it.get('item_name','?')} ({it.get('item_type','?')}) — {shards:,.0f} shards, {sv} SV, distance band {mind}-{maxd} km")
            lines.append("")
            lines.append("NOTE: Drop rates per expedition are NOT this distribution. They're tiered by expedition # and distance — see discovery_analytics for the actual formula.")
            return "\n".join(lines)

        elif category == 'discovery_analytics':
            from utilities.postgres.expeditions import get_user_expedition_history
            history = get_user_expedition_history(user_id, limit=500)
            expeditions = history.get('expeditions') or []
            completed = [e for e in expeditions if e.get('completed_at')]
            completed.sort(key=lambda e: e.get('departed_at') or e.get('completed_at'))
            lines = ["=== DISCOVERY ANALYTICS ==="]
            lines.append("Drop-rate tiers (source: utilities/discovery_utils.py::get_progressive_weights):")
            lines.append("  Exp #  1-3:  common 50, uncommon 25, rare 15, legendary 0")
            lines.append("  Exp #  4-9:  common 75, uncommon 20, rare  5, legendary 0")
            lines.append("  Exp # 10-19: common 60, uncommon 25, rare 12, legendary 0")
            lines.append("  Exp # 20+:   common 60, uncommon 25, rare 12, legendary 0.5")
            lines.append("Then distance multipliers stack (legendary stays 0 below 300 km):")
            lines.append("  <100km: common ×1.5, uncommon ×1.0, rare ×0.5, legendary ×0")
            lines.append("  <300km: common ×1.0, uncommon ×1.0, rare ×1.0, legendary ×0")
            lines.append("  <600km: common ×0.75, uncommon ×1.0, rare ×1.5, legendary ×0.5")
            lines.append("  <1000km: common ×0.5, uncommon ×1.0, rare ×2.0, legendary ×1.5")
            lines.append("  <2000km: common ×0.4, uncommon ×1.0, rare ×2.5, legendary ×2.5")
            lines.append("  2000+km: common ×0.3, uncommon ×0.8, rare ×3.0, legendary ×4.0")
            lines.append("Exploration stat boosts rare (×(1+expl/90)) and legendary (×(1+(expl/90)²)). Strategy boosts rare (up to ×1.5).")
            lines.append("")
            if not completed:
                lines.append("No completed expeditions yet — nothing to analyze.")
                return "\n".join(lines)
            actual = {'common': 0, 'uncommon': 0, 'rare': 0, 'legendary': 0}
            band_counts = {'<300km': 0, '300-600km': 0, '600-1000km': 0, '1000-2000km': 0, '2000+km': 0}
            exp_band_counts = {'1-3': 0, '4-9': 0, '10-19': 0, '20+': 0}
            sum_discoveries = 0
            legendary_eligible = 0  # trips where legendary CAN drop (exp # >= 20 AND distance >= 300km)
            for idx, exp in enumerate(completed, start=1):
                actual['common']    += exp.get('common_count')    or 0
                actual['uncommon']  += exp.get('uncommon_count')  or 0
                actual['rare']      += exp.get('rare_count')      or 0
                actual['legendary'] += exp.get('legendary_count') or 0
                n_disc = exp.get('discovery_count') or 0
                sum_discoveries += n_disc
                dist = float(exp.get('distance_km') or 0)
                if dist < 300: band_counts['<300km'] += 1
                elif dist < 600: band_counts['300-600km'] += 1
                elif dist < 1000: band_counts['600-1000km'] += 1
                elif dist < 2000: band_counts['1000-2000km'] += 1
                else: band_counts['2000+km'] += 1
                if idx <= 3: exp_band_counts['1-3'] += 1
                elif idx <= 9: exp_band_counts['4-9'] += 1
                elif idx <= 19: exp_band_counts['10-19'] += 1
                else: exp_band_counts['20+'] += 1
                if idx >= 20 and dist >= 300:
                    legendary_eligible += 1
            lines.append(f"YOUR TRIPS: {len(completed)} completed | {sum_discoveries} total discoveries")
            lines.append("")
            lines.append("ACTUAL RARITY BREAKDOWN OF YOUR FINDS:")
            for r in ('legendary', 'rare', 'uncommon', 'common'):
                a = actual[r]
                pct = (a / sum_discoveries * 100) if sum_discoveries else 0
                lines.append(f"  {r.title():10s}: {a:4d} ({pct:5.1f}%)")
            lines.append("")
            lines.append("YOUR TIER EXPOSURE (what gate did each trip fall into?):")
            lines.append(f"  Expedition # bands: 1-3:{exp_band_counts['1-3']}  4-9:{exp_band_counts['4-9']}  10-19:{exp_band_counts['10-19']}  20+:{exp_band_counts['20+']}")
            lines.append(f"  Distance bands:     <300km:{band_counts['<300km']}  300-600:{band_counts['300-600km']}  600-1000:{band_counts['600-1000km']}  1000-2000:{band_counts['1000-2000km']}  2000+:{band_counts['2000+km']}")
            lines.append(f"  Legendary-eligible trips (exp # >= 20 AND >= 300 km): {legendary_eligible} of {len(completed)}")
            lines.append("")
            lines.append("WHY EXACT 'EXPECTED' NUMBERS ARE NOT SHOWN:")
            lines.append("  The drop pipeline has filters that the tier table alone can't model accurately:")
            lines.append("  • Slot 0 of every trip is a GUARANTEED common stackable (`generate_expedition_discoveries` lines 297-340) — this fixes a hard floor on common count.")
            lines.append("  • Each rare item ID can drop at most ONCE per trip (`rare_items_found` dedupe) — caps rare yield, since only 12 distinct rare items exist in the catalog.")
            lines.append("  • Per-checkpoint terrain matching: items with `preferred_mars_features` not matching `nearby_feature.type` are filtered from the weighted draw at that checkpoint.")
            lines.append("  • Item-level `min_distance_km`/`max_distance_km` re-filter the pool at each checkpoint (not just the trip's total distance).")
            lines.append("  • Cargo capacity overflow keeps highest-`enhanced_value` items — value-weighted, so rarity mix can shift after the cap.")
            lines.append("  • Equipment effects (scanner/drone rare+legendary bonuses) at time of trip are not stored historically.")
            lines.append("")
            lines.append("INTERPRETATION GUIDE: cross-reference the tier table at the top with YOUR TIER EXPOSURE. If legendary-eligible trips are low, low legendary count is by design. If exposure is high but actual count is still near zero, that's the signal to investigate the spawn pipeline.")
            return "\n".join(lines)

        elif category == 'map_geography':
            from utilities.postgres.map import get_or_set_user_mars_home, get_mars_landmarks_within_radius, get_available_landmarks_by_discovery
            home = get_or_set_user_mars_home(user_id) or {}
            base_lat = home.get('latitude')
            base_lon = home.get('longitude')
            with db_cursor() as cur:
                cur.execute("SELECT COUNT(*) AS n FROM pilgrim.mars_mappings")
                total_mappings = cur.fetchone()['n']
                cur.execute("SELECT COUNT(*) AS n FROM pilgrim.origin_sites")
                total_origins = cur.fetchone()['n']
                cur.execute("SELECT COUNT(DISTINCT landmark_name) AS uniq FROM pilgrim.landmark_discoveries WHERE user_id = %s", (user_id,))
                uniq_visited = cur.fetchone()['uniq']
                cur.execute("SELECT COUNT(DISTINCT destination_name) AS uniq_dests, COUNT(*) AS trips FROM pilgrim.expeditions WHERE user_id = %s AND status = 'complete'", (user_id,))
                erow = cur.fetchone()
                uniq_dests = erow['uniq_dests']
                trips = erow['trips']
            # Fog radius from math_registry formula: min(1000, 300 + uniq_visited × 50), then × Launch Pad range_mult
            base_radius = min(1000, 300 + uniq_visited * 50)
            range_mult = 1.0
            try:
                from utilities.infrastructure_utils import get_user_infrastructure_effects
                effects = get_user_infrastructure_effects(user_id) or {}
                range_mult = float(effects.get('expedition_range_mult', 1.0) or 1.0)
            except Exception:
                pass
            effective_fog_km = int(base_radius * range_mult)
            # Live count inside the fog right now
            in_fog_count = 0
            if base_lat is not None and base_lon is not None:
                try:
                    in_fog_count = len(get_mars_landmarks_within_radius(base_lat, base_lon, effective_fog_km))
                except Exception:
                    in_fog_count = -1
            # Visible-on-page-right-now (the actual fog-of-war pool, capped at 30 on the expeditions page)
            visible_on_page = 0
            if base_lat is not None and base_lon is not None:
                try:
                    visible_on_page = len(get_available_landmarks_by_discovery(user_id, {'latitude': base_lat, 'longitude': base_lon}, limit=30))
                except Exception:
                    visible_on_page = -1
            lines = ["=== MARS GEOGRAPHY ==="]
            lines.append(f"Planet destination pool: {total_mappings + total_origins} ({total_mappings} named Mars landmarks + {total_origins} origin sites)")
            lines.append(f"  Source: pilgrim.mars_mappings ({total_mappings}) + pilgrim.origin_sites ({total_origins}).")
            lines.append("")
            lines.append("YOUR LOCATION & FOG-OF-WAR:")
            if base_lat is not None:
                lines.append(f"  Base coords: ({base_lat:.4f}, {base_lon:.4f})")
            else:
                lines.append("  Base coords: NOT SET (user has no home tile yet)")
            lines.append(f"  Fog formula: min(1000, 300 + unique_discoveries × 50) × Launch Pad range_mult")
            lines.append(f"  Your fog radius right now: min(1000, 300 + {uniq_visited} × 50) × {range_mult:.2f} = {effective_fog_km} km")
            lines.append(f"  Landmarks inside your fog radius right now: {in_fog_count}")
            lines.append(f"  Total available on /expeditions page (fog candidates + all already-discovered): {visible_on_page}")
            lines.append("")
            lines.append("YOUR VISIT HISTORY:")
            lines.append(f"  Unique landmarks discovered: {uniq_visited} (from pilgrim.landmark_discoveries)")
            lines.append(f"  Unique destinations attempted (may include unnamed waypoints): {uniq_dests}")
            lines.append(f"  Total completed trips (revisits counted): {trips}")
            lines.append(f"  Coverage: {uniq_visited}/{total_mappings + total_origins} = {(uniq_visited / max(1, total_mappings + total_origins)) * 100:.2f}% of the planet")
            lines.append("")
            lines.append("NOTE: 'Unique destinations attempted' can differ from 'unique landmarks discovered' if some trips target points that aren't in mars_mappings (e.g. origin-site claim destinations, ARIA-bond meetups). The 168-vs-125 type gap is expected — it's not a bug.")
            return "\n".join(lines)

        elif category == 'discovery_ledger':
            # Bug #1478 (Luke 2026-05-17 P2 RFD escalation, dup of #1479):
            # discovery_catalog (added in #1470) returns the game-wide item catalog;
            # discovery_analytics returns actual-vs-expected counts. Neither answers
            # "when did I last find a legendary?" — the per-item ledger.
            #
            # Schema verified 2026-05-17 against information_schema.columns:
            #   pilgrim.expedition_discoveries.unlocked_at  → when the item was found
            #   pilgrim.expedition_discoveries.claimed_at   → when extracted to inventory
            #   pilgrim.expedition_discoveries.claimed_by_user (bool)
            #   pilgrim.discovery_items.item_name + .rarity + .base_trade_value_eth
            #   pilgrim.expeditions.destination_name + .distance_km + .completed_at
            #
            # One SQL pass — no N+1. Newest-first, limited to last 50 rows; per-rarity
            # totals come from a separate aggregate query.
            from datetime import datetime, timezone
            ROW_COLS = """
                di.rarity, di.item_name, di.base_trade_value_eth, di.base_scientific_value,
                e.destination_name, e.distance_km,
                ed.unlocked_at, ed.claimed_at, ed.claimed_by_user, ed.enhanced_value, ed.quantity
            """
            with db_cursor() as cur:
                # Per-rarity totals (full history)
                cur.execute("""
                    SELECT di.rarity, COUNT(*) AS n
                    FROM pilgrim.expedition_discoveries ed
                    JOIN pilgrim.discovery_items di ON di.id = ed.discovery_item_id
                    JOIN pilgrim.expeditions e ON e.id = ed.expedition_id
                    WHERE e.user_id = %s
                    GROUP BY di.rarity
                """, (user_id,))
                totals = {r['rarity']: r['n'] for r in cur.fetchall()}
                # Last find per rarity (one row per rarity from FULL history, not the 15-row payload).
                # DISTINCT ON in PG returns one row per rarity ordered by unlocked_at DESC.
                cur.execute(f"""
                    SELECT DISTINCT ON (di.rarity) {ROW_COLS}
                    FROM pilgrim.expedition_discoveries ed
                    JOIN pilgrim.discovery_items di ON di.id = ed.discovery_item_id
                    JOIN pilgrim.expeditions e ON e.id = ed.expedition_id
                    WHERE e.user_id = %s AND ed.unlocked_at IS NOT NULL
                    ORDER BY di.rarity, ed.unlocked_at DESC
                """, (user_id,))
                last_per_rarity = {r['rarity']: r for r in cur.fetchall()}
                # Newest-first payload (last 15 overall)
                cur.execute(f"""
                    SELECT {ROW_COLS}
                    FROM pilgrim.expedition_discoveries ed
                    JOIN pilgrim.discovery_items di ON di.id = ed.discovery_item_id
                    JOIN pilgrim.expeditions e ON e.id = ed.expedition_id
                    WHERE e.user_id = %s AND ed.unlocked_at IS NOT NULL
                    ORDER BY ed.unlocked_at DESC
                    LIMIT 15
                """, (user_id,))
                rows = cur.fetchall()

            if not rows and not totals:
                return "DISCOVERY LEDGER: no discoveries yet for this user."

            def fmt_ago(ts):
                if not ts: return "?"
                try:
                    dt = ts if hasattr(ts, 'tzinfo') and ts.tzinfo else ts.replace(tzinfo=timezone.utc) if ts else None
                    if not dt: return "?"
                    now = datetime.now(timezone.utc)
                    delta = now - dt
                    secs = int(delta.total_seconds())
                    if secs < 3600: return f"{secs // 60}m ago"
                    if secs < 86400: return f"{secs // 3600}h ago"
                    return f"{secs // 86400}d ago"
                except Exception:
                    return str(ts)

            def fmt_row(r, include_rarity=False):
                claim = "CLAIMED" if r.get('claimed_by_user') else "UNCLAIMED"
                qty = f"x{r['quantity']}" if r.get('quantity') and r['quantity'] > 1 else ""
                prefix = f"[{r['rarity'].upper()}] " if include_rarity else ""
                return (f"  {prefix}{r['item_name']}{qty} @ {r.get('destination_name') or '?'} "
                        f"({int(r.get('distance_km') or 0)} km) — "
                        f"unlocked {r['unlocked_at']} ({fmt_ago(r['unlocked_at'])}) — {claim}")

            lines = ["=== DISCOVERY LEDGER ==="]
            lines.append("")
            lines.append("PER-RARITY TOTALS:")
            for rar in ('legendary', 'rare', 'uncommon', 'common'):
                lines.append(f"  {rar.capitalize():10} {totals.get(rar, 0)}")
            lines.append(f"  {'TOTAL':10} {sum(totals.values())}")
            lines.append("")
            # Last-find-per-rarity is the answer to "when did I last find a legendary/rare?"
            # Uses DISTINCT ON from the SQL above against FULL history — not capped by the 15-row payload.
            lines.append("LAST FIND PER RARITY (most recent unlocked_at per rarity, full history):")
            for rar in ('legendary', 'rare', 'uncommon'):
                last = last_per_rarity.get(rar)
                if last:
                    lines.append(fmt_row(last, include_rarity=True))
                else:
                    lines.append(f"  [{rar.upper()}] none yet")
            lines.append("")
            lines.append(f"LAST {len(rows)} DISCOVERIES OVERALL (newest first):")
            for r in rows:
                lines.append(fmt_row(r, include_rarity=True))
            lines.append("")
            lines.append("Source: pilgrim.expedition_discoveries JOIN pilgrim.discovery_items JOIN pilgrim.expeditions. "
                         "Payload list capped at 15 newest rows; last-per-rarity scan covers full history. "
                         "For tier-band drop-rate audits, use discovery_analytics instead.")
            return "\n".join(lines)

        else:
            return f"Unknown category: {category}"
    except Exception as e:
        logger.error(f"query_player_data({category}, {user_id}) failed: {e}")
        return f"Error fetching {category}: {e}"
