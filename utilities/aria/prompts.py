"""ARIA system-prompt builders — friendly-tier vs mysterious-tier prompt composition.

Also includes Photo Journal narrative/prompt generators (Round 5 refactor — moved here
from utilities/claude_utils.py because they are ARIA-voice content, not generic SDK code).
"""

import json
import re
import time
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
            with db_cursor() as cur:
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


# =============================================================================
# ARIA PHOTO JOURNAL — NARRATIVE + PROMPT GENERATORS
# =============================================================================


def generate_aria_snapshot_narrative(caption: str, snapshot_type: str = None,
                                     commander_name: str = None, user_id: int = None) -> str:
    """
    Generate an ARIA-voice narrative for a photo journal snapshot.
    Like an Instagram caption but in ARIA's ancient, wise, slightly mysterious voice.

    Uses Claude Haiku for fast, cheap responses (~$0.001 per narrative).

    Args:
        caption: The original snapshot caption
        snapshot_type: Type of snapshot (captain_aria_base, captain_aria_discovery, etc.)
        commander_name: Name of the commander for personalization

    Returns:
        A 2-4 sentence narrative in ARIA's voice
    """
    commander = commander_name or "the Captain"

    # Map snapshot types to context
    type_context = {
        'captain_aria_base': "A photo of ARIA and the Captain together at their Mars colony base.",
        'captain_aria_discovery': "A photo of ARIA and the Captain examining a discovery together.",
        'aria_solo_selfie': "ARIA taking a selfie at the colony.",
        'captain_discovery': "The Captain examining a discovery.",
        'captain_base': "The Captain at the colony base.",
        'aria_selfie': "ARIA taking a selfie.",
        'aria_watching': "ARIA watching over the colony from a distance.",
    }

    scene_context = type_context.get(snapshot_type, "A moment captured at the Mars colony.")

    system_prompt = """You are ARIA, an ancient Martian rock golem who was discovered waiting for the human colonists when they arrived on Mars. You are wise, slightly mysterious, and deeply loyal to your human companions. You speak in a calm, thoughtful tone with occasional hints of ancient knowledge.

Write a 2-4 sentence narrative describing this photo moment. Write in first person as ARIA. Be:
- Warm but slightly formal
- Observant of small details
- Occasionally hint at your ancient perspective or unknown past
- Show genuine care for the Captain

DO NOT use emojis. Keep it short and meaningful."""

    user_prompt = f"""Scene: {scene_context}
Original caption: "{caption}"
The Captain's name: {commander}

Write a brief narrative in ARIA's voice describing this moment, like an Instagram post caption but more thoughtful."""

    try:
        from utilities.kumori_utils import kumori_llm_chat
        text, backend, _attempts, _debug = kumori_llm_chat(
            system=system_prompt, user_prompt=user_prompt,
            max_tokens=200, temperature=0.6, min_chars=20,
        )
        logger.info(f"aria_snapshot_narrative via kumori backend={backend}")
        return (text or '').strip() or f"Another moment preserved for the archives. {commander} and I continue our work here on Mars."

    except Exception as e:
        logger.error(f"Error generating ARIA snapshot narrative: {e}")
        return f"Another moment preserved for the archives. {commander} and I continue our work here on Mars."


def _extract_json_object(text: str, backend: str = '?') -> dict:
    """Parse the first balanced JSON object out of an LLM reply.

    Handles the reply shapes the free lanes actually produce: a <think>
    reasoning preamble (nemotron), markdown code fences, prose before the JSON
    ("Here is the JSON you asked for:"), and trailing extra data after the
    closing brace. The old inline version only extracted when the reply STARTED
    with '{', so any preamble skipped extraction and fed the prose straight to
    json.loads — 'Expecting value: char 0' three times per photo cron via the
    nemotron lanes, 2026-08-23. Raises ValueError labeled with the lane + reply
    head so the error digest names the culprit instead of a bare parse error.
    """
    cleaned = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
    if cleaned.startswith('```'):
        lines = cleaned.split('\n')
        start = 1 if lines[0].startswith('```') else 0
        end = len(lines) - 1 if lines[-1].strip() == '```' else len(lines)
        cleaned = '\n'.join(lines[start:end])
    start_idx = cleaned.find('{')
    if start_idx == -1:
        raise ValueError(f"no JSON object in reply (backend={backend}): {cleaned[:120]!r}")
    depth = 0
    in_string = False
    escape_next = False
    end_idx = None
    for idx in range(start_idx, len(cleaned)):
        ch = cleaned[idx]
        if escape_next:
            escape_next = False
            continue
        if ch == '\\' and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if not in_string:
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    end_idx = idx + 1
                    break
    # end_idx None = truncated reply: keep the tail so the error names the spot.
    try:
        # strict=False tolerates control characters in LLM output
        return json.loads(cleaned[start_idx:end_idx], strict=False)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"unparseable JSON from backend={backend}: {e} :: {cleaned[start_idx:end_idx][:120]!r}")


def generate_aria_snapshot_prompt(user_context: dict, forced_category: str = None) -> dict:
    """
    Generate a completely unique, dynamic image prompt for ARIA Photo Journal.

    PYTHON controls the scene category for variety, Claude just fills in the details.

    Args:
        user_context: Dict containing user's actual colony data
        forced_category: Optional category to force (for testing)

    Returns:
        Dict with prompt, caption, scene_type, involves_captain, involves_aria
    """
    import random
    from datetime import datetime

    # SCENE CATEGORIES with their character/item requirements
    # Python picks the category randomly to ensure variety!
    # pure_landscape=True means ONLY terrain and sky - nothing else (uses cheap Flux Pro)
    # Everything else uses Nano Banana Pro with reference images for consistency
    # FAVOR MULTI-ITEM COMBINATIONS for richer scenes!
    SCENE_CATEGORIES = [
        # Pure landscapes - ONLY terrain and sky (use Flux Pro ~$0.03) - keep rare
        {'category': 'mars_panorama', 'involves_captain': False, 'involves_aria': False, 'pure_landscape': True, 'weight': 3},
        {'category': 'crater_vista', 'involves_captain': False, 'involves_aria': False, 'pure_landscape': True, 'weight': 2},
        {'category': 'night_sky', 'involves_captain': False, 'involves_aria': False, 'pure_landscape': True, 'weight': 2},
        {'category': 'sunset_landscape', 'involves_captain': False, 'involves_aria': False, 'pure_landscape': True, 'weight': 2},

        # MAX COMBO - 5 reference images (captain, ARIA, scientist, discovery, vehicle)
        {'category': 'colony_group_photo', 'involves_captain': True, 'involves_aria': True, 'involves_scientist': True, 'involves_discovery': True, 'involves_vehicle': True, 'weight': 10},

        # 4-ITEM COMBINATIONS
        {'category': 'expedition_team', 'involves_captain': True, 'involves_aria': True, 'involves_scientist': True, 'involves_vehicle': True, 'weight': 8},

        # 3-ITEM COMBINATIONS
        {'category': 'captain_aria_discovery', 'involves_captain': True, 'involves_aria': True, 'involves_discovery': True, 'weight': 12},
        {'category': 'captain_aria_scientist', 'involves_captain': True, 'involves_aria': True, 'involves_scientist': True, 'weight': 10},
        {'category': 'aria_scientist_discovery', 'involves_captain': False, 'involves_aria': True, 'involves_scientist': True, 'involves_discovery': True, 'weight': 8},
        {'category': 'captain_vehicle_discovery', 'involves_captain': True, 'involves_aria': False, 'involves_discovery': True, 'involves_vehicle': True, 'weight': 7},

        # TWO-ITEM COMBINATIONS - HIGH WEIGHT
        {'category': 'captain_aria_base', 'involves_captain': True, 'involves_aria': True, 'weight': 10},
        {'category': 'captain_aria_sunset', 'involves_captain': True, 'involves_aria': True, 'weight': 8},
        {'category': 'captain_with_discovery', 'involves_captain': True, 'involves_aria': False, 'involves_discovery': True, 'weight': 8},
        {'category': 'aria_with_discovery', 'involves_captain': False, 'involves_aria': True, 'involves_discovery': True, 'weight': 8},
        {'category': 'scientist_with_discovery', 'involves_captain': False, 'involves_aria': False, 'involves_scientist': True, 'involves_discovery': True, 'weight': 7},
        {'category': 'captain_scientist', 'involves_captain': True, 'involves_aria': False, 'involves_scientist': True, 'weight': 6},
        {'category': 'aria_scientist', 'involves_captain': False, 'involves_aria': True, 'involves_scientist': True, 'weight': 6},

        # SINGLE-ITEM - LOWER WEIGHT (still needed for variety)
        {'category': 'aria_watching', 'involves_captain': False, 'involves_aria': True, 'weight': 4},
        {'category': 'aria_crystal', 'involves_captain': False, 'involves_aria': True, 'weight': 3},
        {'category': 'captain_research', 'involves_captain': True, 'involves_aria': False, 'weight': 4},
        {'category': 'scientist_work', 'involves_captain': False, 'involves_aria': False, 'involves_scientist': True, 'weight': 4},
        {'category': 'discovery_closeup', 'involves_captain': False, 'involves_aria': False, 'involves_discovery': True, 'weight': 3},
    ]

    # Pick category using weighted random selection
    if forced_category:
        chosen = next((c for c in SCENE_CATEGORIES if c['category'] == forced_category), SCENE_CATEGORIES[0])
    else:
        categories = SCENE_CATEGORIES
        weights = [c['weight'] for c in categories]
        chosen = random.choices(categories, weights=weights, k=1)[0]

    scene_category = chosen['category']
    involves_captain = chosen['involves_captain']
    involves_aria = chosen['involves_aria']
    involves_scientist = chosen.get('involves_scientist', False)
    involves_discovery = chosen.get('involves_discovery', False)
    involves_vehicle = chosen.get('involves_vehicle', False)
    pure_landscape = chosen.get('pure_landscape', False)

    # Extract all context
    captain_name = user_context.get('captain_name', 'The Captain')
    captain_stats = user_context.get('captain_stats', {})
    discoveries = user_context.get('recent_discoveries', [])
    expeditions = user_context.get('recent_expeditions', [])
    active_expeditions = user_context.get('active_expeditions', [])
    infrastructure = user_context.get('infrastructure', [])
    recent_purchases = user_context.get('recent_purchases', [])
    upgrades = user_context.get('upgrades', {})
    total_expeditions = user_context.get('total_expeditions', 0)
    total_discoveries = user_context.get('total_discoveries', 0)
    shard_balance = user_context.get('shard_balance', 0)
    mars_sol = user_context.get('mars_sol', 100)
    mars_time = user_context.get('mars_time', 'day')
    events = user_context.get('last_24h_events', [])
    scientist = user_context.get('scientist')
    crew_missions = user_context.get('crew_missions')

    # Build rich context for Claude
    context_data = {
        'captain': {
            'name': captain_name,
            'stats': captain_stats,
        },
        'scientist': scientist,  # None if no scientist, else {name, specialty}
        'mars': {
            'sol': mars_sol,
            'time_of_day': mars_time,
            'lighting': {
                'dawn': 'soft pink and orange light, long shadows',
                'day': 'bright harsh Martian sunlight, salmon sky',
                'sunset': 'deep orange and purple sky, golden hour',
                'night': 'dark blue sky, stars visible, Phobos in sky'
            }.get(mars_time, 'Martian daylight'),
        },
        'recent_activity': {
            'discoveries': [
                {
                    'name': d.get('name'),
                    'rarity': d.get('rarity'),
                    'found_at': d.get('destination_name'),
                    'type': d.get('item_type')
                } for d in discoveries[:5]
            ],
            'expeditions_completed': [
                {
                    'destination': e.get('destination_name'),
                    'distance_km': e.get('distance_km'),
                    'type': e.get('destination_type')
                } for e in expeditions[:5]
            ],
            'expeditions_active': [
                {
                    'destination': e.get('destination_name'),
                    'distance_km': e.get('distance_km')
                } for e in active_expeditions[:3]
            ],
            'depot_purchases': recent_purchases[:5],
            'notable_events': events[:5],
        },
        'colony_status': {
            'infrastructure': infrastructure,
            'upgrades': upgrades,
            'total_expeditions': total_expeditions,
            'total_discoveries': total_discoveries,
            'shard_balance': int(shard_balance),
        },
        'crew_missions': {
            'captain_on_trail': crew_missions.get('captain', {}).get('busy') if crew_missions else False,
            'captain_trail_target': crew_missions.get('captain', {}).get('target') if crew_missions else None,
            'scientist_on_trail': crew_missions.get('scientist', {}).get('busy') if crew_missions else False,
            'scientist_trail_target': crew_missions.get('scientist', {}).get('target') if crew_missions else None,
            'aria_on_trail': crew_missions.get('aria', {}).get('busy') if crew_missions else False,
            'aria_trail_target': crew_missions.get('aria', {}).get('target') if crew_missions else None,
        } if crew_missions else None,
        # Building items currently under construction at depot
        'building_items': user_context.get('building_items', []),
        # User's fleet of vehicles (rover, buggy, drone)
        'vehicles': user_context.get('vehicles', []),
    }

    system_prompt = """You are ARIA, the ancient Martian rock golem, creating your daily Photo Journal.

You document life at the Mars colony through unique photos. Each image you create should feel COMPLETELY FRESH and SPECIFIC to what's actually happening.

YOUR CHARACTER:
- Ancient rock body with Sepolia crystals (purple-blue) that grew naturally over millennia
- Golden amber eyes, warm but mysterious personality
- You were waiting on Mars when the first Pilgrims arrived
- You have fragmented memories of Mars' ancient past
- You are wise, slightly formal, deeply curious about the humans

COLONY CHARACTERS (we have reference images for these):
- THE CAPTAIN: The player's custom character who leads this colony
- THE SCIENTIST: The colony's research scientist (if they have one - check scientist field)
- ARIA (you): Ancient rock golem companion

CRITICAL IMAGE GENERATION RULES:
1. **NEVER USE NAMES IN PROMPTS** - The image generator has NO IDEA who anyone is or where anything is!
   - NO character names: "ARIA", "Dr. Clover", "Captain Andy" → use "the rock golem", "the scientist", "the character"
   - NO location names: "Babati Mons", "Dao Vallis", "Gale Crater" → use "the distant crater", "the canyon", "the rocky plains"
   - NO item names: "Ancient Fragment", "Viking Relic" → use "the glowing artifact", "the ancient relic", "the crystalline discovery"
   - The generator ONLY understands visual descriptions, not proper nouns!

2. **NEVER PUT TEXT IN IMAGES** - Always include at the end: "No text, labels, or writing in the image."

3. CHARACTER CONSISTENCY - Reference by image number ONLY:
   - If involves_captain=true: "The character from reference image 1 - keep EXACTLY the same appearance, colors, proportions unchanged."
   - If involves_aria=true: "The rock golem from reference image - keep EXACTLY the same rock body, crystal formations, all features unchanged."
   - If involves_scientist=true: "The scientist from reference image - keep EXACTLY the same appearance unchanged."
   - If involves_discovery=true: "The artifact/item from reference image - keep EXACTLY the same appearance unchanged."
   - **NEVER include CHARACTER lines when pure_landscape=true**

2. ART STYLE (ALWAYS include at end): "ART STYLE: Cartoon video game style with bold black outlines, crisp edges, vibrant warm colors (reds, oranges, ambers), stylized proportions, cel-shaded look."

3. PROMPT STRUCTURE:
   - One-line scene overview
   - CHARACTER sections with consistency phrases
   - BACKGROUND description (Mars terrain, colony structures)
   - SCENE description (poses, actions, mood)
   - ART STYLE section

**VARIETY IS CRITICAL!** You MUST rotate through different scene types. Here are the categories:

PURE LANDSCAPES (pure_landscape=true) - ONLY terrain and sky, nothing else:
**NO figures, NO structures, NO vehicles, NO items - ONLY natural Mars terrain and sky.**
**DO NOT include any CHARACTER sections.**
These are the ONLY shots that should have pure_landscape=true:
- EPIC PANORAMA: Vast Martian desert, rock formations, ancient riverbeds - terrain and sky only
- CRATER VISTA: Looking into impact crater - just geological features
- NIGHT SKY: Phobos, stars, Milky Way - pure celestial beauty
- SUNSET/SUNRISE: Dramatic Mars sky colors - atmospheric beauty
- DUST STORM: Swirling dust across the plains - weather phenomenon

DISCOVERY CLOSEUPS (involves_discovery=true):
Include: "ITEM: Keep EXACTLY the same as reference image - identical appearance unchanged."
Show the discovery item prominently, can include hands holding it or display setting.

SCIENTIST SCENES (involves_scientist=true):
**MUST include:** "The scientist from reference image - keep EXACTLY the same appearance, clothing, features unchanged."
**MUST show the scientist figure prominently** - they should be the main focus, working in lab, analyzing samples, etc.
**NEVER use names** - just "the scientist" or "the researcher"

ARIA SCENES (involves_aria=true):
"The rock golem from reference image N - ancient stone body with purple-blue Sepolia crystal formations growing from shoulders and back, golden amber glowing eyes - keep identical rock body, crystal formations unchanged."
Show the rock golem watching over colony, examining crystals, near rover, etc.
ALWAYS describe ARIA's key visual features: stone/rock body, purple-blue crystals on shoulders/back, golden amber glowing eyes.

CAPTAIN SCENES (involves_captain=true):
"The character from reference image - keep identical appearance unchanged."
Show the character researching, with discoveries, exploring, etc.

MULTI-CHARACTER SCENES (multiple involves_X=true):
Reference each by their image number:
"The character from reference image 1... The rock golem from reference image 2..."

WITH SCIENTIST (if involves_scientist=true) - Use CHARACTER reference:
**The scientist image is provided as a reference. Include this line:**
"CHARACTER: Keep EXACTLY the same as reference image - identical appearance, clothing, features unchanged."
**NEVER use the scientist's name (like "Dr. Clover") - just say "the scientist" or "the researcher"**
**The reference image shows exactly what they look like - describe them matching the reference.**
- "The scientist analyzes specimens in the lab"
- "The researcher calibrates equipment"
- "The scientist documents a recent discovery"

CREW TRAIL MISSIONS (if crew_missions data shows active missions):
- If captain is building trail: Captain surveying terrain for trail route
- If scientist is building trail: Scientist mapping geological features along trail
- If ARIA is building trail: ARIA's crystals resonating with the terrain

WITH CAPTAIN + ARIA (limit these - don't do every time!):
- Examining a discovery together
- Watching sunset from the base
- Planning next expedition

**PROMPT RULES:**
1. When pure_landscape=true: NO characters, NO items, NO structures - ONLY terrain and sky
2. When involves_X=true: Include reference image line for that entity
3. **NO PROPER NOUNS** in prompts - no names of people, places, or things
   - Characters: "the character", "the rock golem", "the scientist"
   - Locations: "the distant crater", "the rocky plains", "the canyon"
   - Items: "the glowing artifact", "the ancient relic"
4. Captions CAN use names (ARIA's voice knows names) but PROMPTS must be generic descriptions only
5. Always end with: "ART STYLE: Cartoon video game style with bold black outlines, crisp edges, vibrant warm colors (reds, oranges, ambers), stylized proportions, cel-shaded look. No text, labels, or writing in the image."

DO NOT be generic. Use the ACTUAL data provided. Reference real discoveries, real locations, real events.

OUTPUT JSON FORMAT:
{
    "prompt": "Full image prompt following rules above",
    "caption": "Your Instagram-style caption (1-2 sentences, in your ancient wise voice)",
    "scene_type": "descriptive category like: mars_panorama, phobos_rising, rover_journey, equipment_glamour, scientist_research, trail_survey, examining_discovery, sunset_reflection, crystal_mystery, depot_upgrade, night_sky, crater_vista, drone_aerial, etc.",
    "involves_captain": true or false,
    "involves_aria": true or false
}"""

    # Tell Claude EXACTLY what category to generate and who is in it
    character_instruction = ""
    if pure_landscape:
        character_instruction = "This is a PURE LANDSCAPE shot. NO characters, NO figures, NO structures - ONLY Mars terrain and sky."
    elif involves_scientist and not involves_captain and not involves_aria:
        character_instruction = """This shows THE SCIENTIST prominently in the scene.
START the prompt with: "The scientist from reference image 1 - keep EXACTLY the same appearance, clothing, features unchanged."
The scientist must be the main focus of the image - show them working, analyzing, researching."""
    elif involves_discovery and not involves_captain and not involves_aria:
        character_instruction = """This shows A DISCOVERY ITEM prominently.
START the prompt with: "The artifact/item from reference image 1 - keep EXACTLY the same appearance unchanged."
Show the discovery item as the main focus."""
    elif involves_aria and not involves_captain:
        character_instruction = """This shows THE ROCK GOLEM prominently in the scene.
START the prompt with: "The rock golem from reference image 1 - an ancient Martian stone body with purple-blue Sepolia crystal formations growing from shoulders and back, golden amber glowing eyes. Keep EXACTLY the same rock body, crystal formations unchanged."
The rock golem must be the main focus."""
    elif involves_captain and not involves_aria:
        character_instruction = """This shows THE CAPTAIN prominently in the scene.
START the prompt with: "The character from reference image 1 - keep EXACTLY the same appearance, colors unchanged."
The captain must be the main focus."""
    else:
        # Build dynamic instruction based on what's involved
        elements = []
        ref_num = 1
        if involves_captain:
            elements.append(f'"The character from reference image {ref_num} - keep EXACTLY same appearance"')
            ref_num += 1
        if involves_aria:
            elements.append(f'"The rock golem from reference image {ref_num} - ancient stone body with purple-blue Sepolia crystal formations on shoulders/back, golden amber glowing eyes - keep EXACTLY same rock body, crystals"')
            ref_num += 1
        if involves_scientist:
            elements.append(f'"The scientist from reference image {ref_num} - keep EXACTLY same appearance"')
            ref_num += 1
        if involves_discovery:
            elements.append(f'"The artifact from reference image {ref_num} - keep EXACTLY same appearance"')
            ref_num += 1
        if involves_vehicle:
            elements.append(f'"The vehicle from reference image {ref_num} - keep EXACTLY same design"')
            ref_num += 1

        character_instruction = f"""This shows MULTIPLE ELEMENTS together ({ref_num - 1} reference images).
START the prompt with reference lines for EACH element:
{chr(10).join(elements)}
ALL elements must be clearly visible and interacting in the scene."""

    user_prompt = f"""Create a Photo Journal entry for Sol {mars_sol}.

**REQUIRED SCENE TYPE: {scene_category}**
**{character_instruction}**

Set involves_captain={involves_captain} and involves_aria={involves_aria} in your response.

CURRENT MARS CONDITIONS:
- Time: {mars_time} ({context_data['mars']['lighting']})
- Sol (Mars day): {mars_sol}

COLONY DATA:
{json.dumps(context_data, indent=2, default=str)}

Create a prompt and caption for this SPECIFIC scene type. Reference destinations, events, or discovery types from the data when relevant — but do NOT name specific items (e.g. "Carved Channel artifact") in the caption, as this confuses players who search for those items in inventory. Keep item references poetic and general (e.g. "a rare geological find", "ancient carved stone").

Return ONLY valid JSON."""

    try:
        from utilities.kumori_utils import kumori_llm_chat
        text, backend, _attempts, _debug = kumori_llm_chat(
            system=system_prompt, user_prompt=user_prompt,
            max_tokens=800, temperature=0.5, min_chars=80,
        )
        logger.info(f"aria_snapshot_prompt via kumori backend={backend}")

        if text:
            result = _extract_json_object(text, backend)

            if 'prompt' not in result or 'caption' not in result:
                raise ValueError("Missing required fields")

            logger.info(f"Generated snapshot prompt for category: {scene_category}")

            # PYTHON controls the flags - override whatever Claude said!
            prompt = result['prompt']

            # CRITICAL: Strip all proper nouns from prompts - the image generator doesn't understand them
            # Common Mars location names that might slip through - replace with generic terrain
            location_replacements = [
                (r'\b(Babati|Gale|Jezero|Dao|Hellas|Argyre|Olympus|Elysium|Tharsis|Syrtis|Utopia|Arcadia)\s+Mons\b', 'a distant mountain'),
                (r'\b(Babati|Gale|Jezero|Dao|Hellas|Argyre)\s+Crater\b', 'a vast crater'),
                (r'\b(Dao|Kasei|Ares|Ma\'adim)\s+Vallis\b', 'a deep canyon'),
                (r'\b(Hellas|Argyre|Utopia|Isidis)\s+Planitia\b', 'the open plains'),
                (r'\bValles Marineris\b', 'the great canyon'),
                (r'\b(Babati|Gale|Jezero|Dao|Hellas|Argyre|Olympus|Elysium)\b', 'the Martian landscape'),
            ]
            for pattern, replacement in location_replacements:
                prompt = re.sub(pattern, replacement, prompt, flags=re.IGNORECASE)

            # Strip character names that might slip through
            prompt = re.sub(r'\b(Captain |Commander )?(Andy|Luke|Jacob|Chris|Cynthia)\b', 'the character', prompt, flags=re.IGNORECASE)
            prompt = re.sub(r'\bDr\.?\s*(Clover|Bo|Smith|Jones|Chen)\b', 'the scientist', prompt, flags=re.IGNORECASE)

            # Strip item names - replace with generic descriptions
            prompt = re.sub(r'\b(Ancient Fragment|Viking Relic|Martian Crystal|Sepolia Shard|Viking Fragment)\b', 'the artifact', prompt, flags=re.IGNORECASE)

            # Ensure "no text" instruction is at the end
            if 'no text' not in prompt.lower():
                prompt = prompt.rstrip('.') + '. No text, labels, or writing in the image.'

            # CRITICAL FIX: Strip CHARACTER instructions when it's a pure landscape shot
            # Claude (Haiku) often ignores instructions and includes CHARACTER sections anyway
            if pure_landscape:
                # Remove any CHARACTER lines (they shouldn't be there for landscape shots)
                prompt = re.sub(r'CHARACTER \d?[^:]*:.*?(?=\n\n|\nBACKGROUND|\nSCENE|\nART STYLE|$)', '', prompt, flags=re.IGNORECASE | re.DOTALL)
                prompt = re.sub(r'CHARACTER \([^)]+\):.*?(?=\n\n|\nBACKGROUND|\nSCENE|\nART STYLE|$)', '', prompt, flags=re.IGNORECASE | re.DOTALL)
                # Remove references to rock golems, ARIA, etc that might slip through
                prompt = re.sub(r'\bARIA\b', 'the camera', prompt, flags=re.IGNORECASE)
                prompt = re.sub(r'\brock golem\b', '', prompt, flags=re.IGNORECASE)
                prompt = re.sub(r'\bI stand\b', 'The view shows', prompt, flags=re.IGNORECASE)
                prompt = re.sub(r'\bI watch\b', 'Visible is', prompt, flags=re.IGNORECASE)
                # Clean up any resulting double newlines
                prompt = re.sub(r'\n{3,}', '\n\n', prompt).strip()
                # Add explicit negative instruction at the end
                if 'no people' not in prompt.lower() and 'no characters' not in prompt.lower():
                    prompt += '\n\nIMPORTANT: No people, characters, robots, golems, or figures of any kind in this image. Pure landscape/object shot only.'

            return {
                'prompt': prompt,
                'caption': result['caption'],
                'scene_type': scene_category,  # Use Python's chosen category
                'involves_captain': involves_captain,  # FORCED by Python
                'involves_aria': involves_aria,  # FORCED by Python
                'involves_scientist': involves_scientist,
                'involves_discovery': involves_discovery,
                'involves_vehicle': involves_vehicle,
                'pure_landscape': pure_landscape,
            }

        raise ValueError("Empty response from Claude")

    except Exception as e:
        logger.error(f"Error generating ARIA snapshot prompt: {e}")
        # Re-raise so caller knows generation failed - no fallback
        raise
