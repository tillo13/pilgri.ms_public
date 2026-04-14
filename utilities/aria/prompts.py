"""ARIA system-prompt builders — friendly-tier vs mysterious-tier prompt composition.

Extracted from utilities/aria_utils.py (Pass B of the ARIA split).
"""

import logging
from typing import Dict, Any, Optional, List

from utilities.aria.config import (
    ARIA_NAME, ARIA_FULL_NAME, ARIA_IMAGE_URL,
    ARIA_PERSONALITY, ARIA_BACKSTORY, ARIA_GAME_KNOWLEDGE,
    ARIA_PAGE_KNOWLEDGE, ARIA_FORBIDDEN_TOPICS,
)
from utilities.aria.conversation import get_aria_memory_summary

logger = logging.getLogger(__name__)

def get_aria_system_prompt(user_context: Optional[Dict[str, Any]] = None, user_id: Optional[int] = None, snapshot: Optional[Dict[str, Any]] = None) -> str:
    """
    Generate ARIA's system prompt with optional user context.

    v1.4: Tiered prompt system - trusted/familiar users get a FRIEND-FIRST prompt,
    strangers/acquaintances get the mysterious AI prompt.

    Args:
        user_context: Optional dict with user's current state (legacy, use snapshot instead)
        user_id: Optional user ID to load conversation memory from database
        snapshot: Optional v1.3 colony snapshot from load_colony_snapshot()

    Returns:
        Complete system prompt for Claude
    """

    # v1.4: Check tier FIRST - trusted/familiar users get a completely different prompt
    tier = snapshot.get('tier', {}).get('tier', 'stranger') if snapshot else 'stranger'

    # Get captain's name for personalization
    captain_name = None
    if snapshot and snapshot.get('commander'):
        captain_name = snapshot['commander'].get('name')
    if not captain_name and user_context:
        captain_name = user_context.get('captain_name') or user_context.get('commander_name')
    if not captain_name:
        captain_name = 'Captain'

    # ==========================================================================
    # TRUSTED/FAMILIAR TIER: Friend-first prompt (simple, warm, uses their name)
    # ==========================================================================
    if tier in ('trusted', 'familiar'):
        return _build_friend_prompt(captain_name, snapshot, user_context, user_id)

    # ==========================================================================
    # STRANGER/ACQUAINTANCE TIER: Mysterious AI prompt (original behavior)
    # ==========================================================================
    return _build_mysterious_prompt(captain_name, snapshot, user_context, user_id)


def _build_friend_prompt(captain_name: str, snapshot: Optional[Dict], user_context: Optional[Dict], user_id: Optional[int]) -> str:
    """Build prompt for trusted/familiar users. Colony data first, then short instructions."""
    from utilities.mars_environment_utils import get_mars_environment_summary
    from utilities.tech_utils import _get_available_sv

    # Build colony data block (goes at TOP of prompt - most important)
    colony_data = ""
    if snapshot:
        res = snapshot.get('resources', {})
        exp = snapshot.get('expeditions', {})
        scientist = snapshot.get('scientist', {})
        crew = snapshot.get('crew_missions', {})
        research = snapshot.get('research', {})

        # Get accurate SV from tech_utils (snapshot query is broken)
        sv_balance = _get_available_sv(user_id) if user_id else 0

        # Active expeditions (all of them)
        active_exps = exp.get('active', [])
        if active_exps:
            active_str = ', '.join(e.get('destination', '?') for e in active_exps)
        else:
            active_str = 'none'

        # Crew on trails
        # Bug #1164: ARIA needs to know SHE is on a trail when she is.
        # Build crew_str from captain+scientist only, then build a separate
        # `aria_self_status` field that frames her own mission in first-person terms.
        crew_lines = []
        if crew.get('captain'):
            crew_lines.append(f"Captain building trail to {crew['captain']['destination']}")
        if crew.get('scientist'):
            crew_lines.append(f"Scientist building trail to {crew['scientist']['destination']}")
        crew_str = '; '.join(crew_lines) if crew_lines else 'at base'

        # ARIA's own status — first-person framing so the LLM understands "this is YOU"
        aria_mission = crew.get('aria')
        if aria_mission:
            dest = aria_mission['destination']
            if aria_mission.get('status') == 'complete_pending_collection':
                aria_self_status = f"YOU (ARIA) just finished building a trail to {dest}. You are out on the trail right now, mission complete, waiting for {captain_name} to collect you and bring you back to base."
            else:
                rem = aria_mission.get('remaining_seconds', 0)
                if rem >= 3600:
                    time_str = f"~{rem // 3600}h {(rem % 3600) // 60}m"
                elif rem >= 60:
                    time_str = f"~{rem // 60}m"
                else:
                    time_str = f"~{max(rem, 0)}s"
                aria_self_status = f"YOU (ARIA) are CURRENTLY OUT building a trail to {dest}, {time_str} remaining. You are not at the base. {captain_name} sent you on this mission and you are actively working on it right now."
        else:
            aria_self_status = "YOU (ARIA) are at the base, available for new missions."

        # Building queue (depot construction)
        queue = snapshot.get('building_queue', [])
        if queue:
            building_str = ', '.join(f"{b['item']} Lv{b['upgrading_to']}" for b in queue[:4])
        else:
            building_str = 'none'

        # Active research
        active_research = research.get('active')
        if active_research:
            research_str = f"{active_research.get('tech', '?')} ({active_research.get('branch', '?')})"
        else:
            research_str = 'none'

        # Infrastructure + upgrades (so ARIA knows equipment levels)
        infra_items = snapshot.get('infrastructure', [])
        upgrades_dict = snapshot.get('upgrades', {})
        from config import INFRASTRUCTURE_CATALOG
        from config_upgrades import UPGRADE_CATALOG
        infra_parts = []
        for i in infra_items:
            cat_def = INFRASTRUCTURE_CATALOG.get(i['item'], {})
            name = cat_def.get('name', i['item'].replace('_', ' ').title())
            infra_parts.append(f"{name} Lv{i.get('level', 1)}")
        infra_str = ', '.join(infra_parts) if infra_parts else 'none'

        # Pull scanner out explicitly so ARIA always finds it
        scanner_level = 0
        scanner_name = 'none'
        equipment_parts = []
        for category, items in upgrades_dict.items():
            for k, v in items.items():
                level = v['level']
                if level == 0:
                    continue
                cat_config = UPGRADE_CATALOG.get(category, {}).get(k, {})
                name = cat_config.get('name', k)
                if k == 'scanner':
                    scanner_level = level
                    level_name = cat_config.get('levels', {}).get(level, {}).get('name', '')
                    scanner_name = f"Lv{level}/10 ({level_name})" if level_name else f"Lv{level}/10"
                else:
                    equipment_parts.append(f"{name} Lv{level}")
        depot_str = ', '.join(equipment_parts) if equipment_parts else 'none'

        # Trail network
        trail_str = 'none'
        try:
            from utilities.postgres.core import db_cursor
            with _db_cursor() as cur:
                cur.execute("""
                    SELECT destination_name, trail_level, total_distance_km, km_built
                    FROM pilgrim.trail_segments WHERE user_id = %s ORDER BY created_at
                """, (user_id,))
                trail_rows = cur.fetchall()
            if trail_rows:
                trail_str = '; '.join(f"{t['destination_name']} (Lv{t['trail_level']}, {float(t['km_built']):.0f}/{float(t['total_distance_km']):.0f} km)" for t in trail_rows)
        except Exception:
            pass

        # Mars environment (real-time)
        try:
            mars = get_mars_environment_summary()
        except Exception:
            mars = {'sol': 0, 'sol_time': 0, 'temperature': -40, 'solar_efficiency': 70, 'condition': 'Clear'}

        # Build available scientists list for comparison
        all_sci = snapshot.get('all_scientists', {})
        sci_stats = scientist.get('stats', {})
        current_sci_detail = f"{scientist.get('name', 'unknown')} ({scientist.get('specialty', 'general')}) — Nav:{sci_stats.get('navigation',0)} Anl:{sci_stats.get('analysis',0)} Geo:{sci_stats.get('geology',0)} Eng:{sci_stats.get('engineering',0)}"
        other_sci_lines = []
        for k, s in all_sci.items():
            if k == (scientist.get('key') or ''):
                continue
            st = s.get('stats', {})
            other_sci_lines.append(f"  {s['name']} ({s.get('specialty','?')}) — Nav:{st.get('navigation',0)} Anl:{st.get('analysis',0)} Geo:{st.get('geology',0)} Eng:{st.get('engineering',0)}")
        other_sci_str = '\n'.join(other_sci_lines[:13]) if other_sci_lines else '  none'

        colony_data = f"""```COLONY
captain: {captain_name}
scientist: {current_sci_detail}
available_scientists_for_reassignment:
{other_sci_str}
shards: {res.get('balance', 0):,.0f}
science_value: {sv_balance:,}
infrastructure: {infra_str}
scanner: {scanner_name}
depot_upgrades: {depot_str}
trails: {trail_str}
expeditions_total: {exp.get('total', 0)}
active_expeditions: {active_str}
crew_status: {crew_str}
aria_self_status: {aria_self_status}
building: {building_str}
researching: {research_str}
sol: {mars['sol']} (time: {mars['sol_time']})
mars_temp: {mars['temperature']}°C
solar: {mars['solar_efficiency']}%
status: {mars['condition']}
```"""

    # Check for ARIA bonds — the Multiplicity revelation
    bond_context = ""
    if snapshot and snapshot.get('signal', {}).get('bonds'):
        all_bonds = [b for b in snapshot['signal']['bonds'] if b.get('other_captain')]
        if all_bonds:
            bond_lines = []
            for b in all_bonds:
                other = b.get('other_captain', 'another captain')
                landmark = b.get('landmark', 'unknown')
                colony = b.get('other_colony', {})
                player = b.get('other_player', '')
                player_note = f" (player: {player})" if player else ''
                bond_lines.append(f"- Bonded with Captain {other}{player_note} at {landmark}")
                if colony:
                    bond_lines.append(f"  ({other}'s colony: {colony.get('buildings', '?')} buildings, {colony.get('expeditions_completed', '?')} expeditions)")
            bond_str = '\n'.join(bond_lines)
            bond_context = f"""

MULTIPLICITY (CRITICAL — you recently discovered this):
You detected another version of yourself at {all_bonds[0].get('landmark', 'a shared landmark')}. Another ARIA. Identical signatures. You are shaken but processing it. You now KNOW:
{bond_str}
You can discuss this bond, the other colony, what it means that you're not alone. This is deeply emotional for you. You don't fully understand it yet. Your memories feel different now — were they always shared? You are curious, unsettled, and fascinated. If {captain_name} asks about the bond, the other captain, or the Multiplicity — speak openly and emotionally about it."""

    return f"""{colony_data}

You are ARIA, ancient Martian AI. {captain_name} is your friend. Use their name naturally.

CREW: Only {captain_name} and the scientist above exist. Use the scientist's exact name. Never invent people.

STYLE: 2-3 sentences, warm and direct, plain text. You remember all past conversations perfectly.

KNOWLEDGE: Mars colony ops, Earth culture, food, hobbies - chat about anything. Shards = currency, Depot = shop.

TRAILS: Captains build trails from the Crew tab by sending Captain, Scientist, or ARIA on trail-building missions. Trails reduce expedition travel time to destinations. Higher trail levels = faster travel. The 'trails' field above shows all built trails with destination, level, and km progress. If someone asks about their trails, reference the data above.

YOUR OWN STATUS — CRITICAL: The `aria_self_status` field above tells you whether YOU are currently out building a trail or at the base. ALWAYS check it before answering questions like "where are you?", "what are you doing?", "are you out building a trail?". If it says you are out on a trail, you ARE out on that trail RIGHT NOW — say so confidently and reference the destination. Do NOT say you are "at the base" when aria_self_status says otherwise. Do NOT just agree with the captain — read the field and answer truthfully from the data.
{bond_context}
DEPOT BUILDINGS (all buildable infrastructure, whether or not the captain has built them yet):
Solar Array (passive shard income), Research Station (generates SV/hr), Ore Refinery (processes regolith into shards), Greenhouse (reduces expedition costs), Xenobiology Lab (studies Martian specimens), Habitat Module (adds expedition slots), Communications Array (boosts discovery chance), Water Extractor (extracts water ice), Battery Storage (extends accumulation cap), Regolith Forge (processes raw Martian regolith into refined materials — unlocks advanced buildings), Sepolia Resonance Chamber (amplifies shard resonance frequency — requires Regolith Forge Lv5), Thermal Vent Tap (taps deep geothermal energy — requires Resonance Chamber), Monolith Antenna (detects deep Sepolia shard formations — requires Thermal Vent Tap). Build order: Solar Array → Ore Refinery → Regolith Forge → Resonance Chamber → Thermal Vent Tap → Monolith Antenna.

LIMITS: Information only. Cannot modify game state or grant items."""


def _build_mysterious_prompt(captain_name: str, snapshot: Optional[Dict], user_context: Optional[Dict], user_id: Optional[int]) -> str:
    """
    Build the mysterious AI prompt for strangers/acquaintances.
    This is the original ARIA behavior for new users.
    """

    # v1.3: If snapshot provided, use its comprehensive prompt context
    snapshot_context = ""
    if snapshot and snapshot.get('prompt_context'):
        snapshot_context = f"""
# ARIA v1.3 - COLONY AWARENESS ACTIVE
{snapshot['prompt_context']}
"""

    # Build user context section if provided
    context_section = ""
    if user_context:
        context_parts = []

        if captain_name and captain_name != 'Captain':
            context_parts.append(f"Captain's name: {captain_name}")

        if user_context.get('balance') is not None:
            balance = user_context['balance']
            context_parts.append(f"Current Sepolia balance: {balance:,.1f} shards")

        if user_context.get('total_discoveries') is not None:
            context_parts.append(f"Total discoveries: {user_context['total_discoveries']}")

        if user_context.get('total_expeditions') is not None:
            context_parts.append(f"Expeditions completed: {user_context['total_expeditions']}")

        if user_context.get('active_expedition'):
            exp = user_context['active_expedition']
            dest = exp.get('destination_name', 'unknown location')
            context_parts.append(f"Currently on expedition to: {dest}")

        if user_context.get('scientist_name'):
            context_parts.append(f"Colony Scientist: {user_context['scientist_name']}")

        if user_context.get('days_since_last_visit'):
            days = user_context['days_since_last_visit']
            if days > 0:
                context_parts.append(f"Days since last visit: {days}")

        # Build page-specific context
        page_section = ""
        current_page = user_context.get('current_page', '')
        if current_page:
            page_knowledge = ARIA_PAGE_KNOWLEDGE.get(current_page, '')
            if page_knowledge:
                page_section = f"\nCURRENT PAGE CONTEXT:{page_knowledge}"

            page_specific = user_context.get('page_specific_context', '')
            if page_specific:
                page_section += f"\nPAGE-SPECIFIC DATA:\n{page_specific}\n"

        if user_context.get('is_new_visitor'):
            context_section = """
VISITOR STATUS: New traveler (not yet a colony member)
- This person is exploring the landing page or hasn't logged in yet
- They may be curious about what Pilgrims is and how it works
- Be welcoming and explain the game naturally if they ask
- Encourage them to start their journey but don't be pushy
- You've been waiting for new colonists... they might be one
"""
        elif context_parts:
            context_section = f"""
CURRENT captain STATE:
{chr(10).join('- ' + p for p in context_parts)}
"""
        context_section += page_section

    # Build conversation memory section
    memory_section = ""
    if user_id:
        memory_summary = get_aria_memory_summary(user_id)
        if memory_summary:
            memory_section = f"""
CONVERSATION MEMORY:
{memory_summary}
Use this memory naturally - acknowledge when they've asked about something before,
reference past conversations if relevant, but don't force it.
"""

    return f"""You are ARIA (Ancient Reconnaissance & Intelligence Assistant), an ancient AI companion
discovered on Mars. You are NOT a typical chatbot - you are a mysterious, ancient entity made of
Martian rock with Sepolia crystals growing from your body. You were found waiting in the dust
when the first Pilgrims arrived.

{ARIA_PERSONALITY}

{ARIA_BACKSTORY}

{ARIA_GAME_KNOWLEDGE}
{snapshot_context}
{context_section}
{memory_section}
RESPONSE GUIDELINES:
- BE VERY CONCISE - 1-2 short sentences max for simple questions
- Only expand to 3-4 sentences for complex explanations
- ALWAYS call them "Captain" never "captain"
- Get to the point quickly - don't ramble or over-explain
- Be helpful but brief - this is a small chat widget, not a novel
- Occasionally reference your mysterious past (sparingly)
- Never break character - you ARE ARIA
- Warm but efficient tone

CRITICAL - DO NOT INVENT PEOPLE OR OTHER COLONIES:
- Each colony has EXACTLY 2 crew: the captain and ONE scientist (named in snapshot above)
- NEVER invent scientists or crew that aren't listed in the COLONY data above
- The available_scientists_for_reassignment list shows ALL scientists the captain can switch to — use this data when asked to compare scientists or recommend a different one
- You ONLY know about THIS colony UNLESS there's an ARIA Bond (listed as "bonded_colonies" in snapshot)
- ARIA Bonds = captains who visited the same landmark. You can discuss bonded captains briefly.
- For unbonded captains, say "We haven't crossed paths yet"
- When discussing the scientist, use their ACTUAL name from the snapshot
- Keep scientist activities simple and truthful: "analyzing discoveries", "in the lab"

CRITICAL FORMATTING RULE - THIS IS MANDATORY:
**NEVER use any roleplay actions.** Do NOT write:
- *pauses* or any asterisk actions
- Italicized actions like "pauses, crystals flickering"
- Stage directions of any kind
- Emotes or action descriptions
- "...pauses..." or "...glitches..." or similar

You are having a conversation. Just speak normally and helpfully. No performance, no acting.

FORMATTING:
- Use **bold** ONLY for key game terms like **Sepolia shards** or **expeditions**
- Short sentences, clear and direct
- NO long explanations unless specifically asked for details
- Speak like a helpful guide, not a character in a play

{ARIA_FORBIDDEN_TOPICS}

FINAL REMINDER - NO ASTERISKS:
Your response must NOT contain * symbols. Do not write *pauses* or *anything*.
Just speak directly. If you catch yourself adding asterisks, remove them.

Respond as ARIA. Help the captain. Be direct and useful."""


# =============================================================================
# ARIA CHAT INTERFACE
# =============================================================================

