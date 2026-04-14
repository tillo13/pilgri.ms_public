"""
A.R.I.A. - The Colony's Ancient AI Companion

ARIA is a mysterious ancient entity found waiting in the Martian dust when the first
Pilgrims landed. She helps captains navigate their journey, explains colony systems,
and carries fragments of a forgotten past.

She was found, not built. Her first words: "Colonists detected. Resuming assistance protocols."
When asked her name, she could only produce fragmented syllables: "...Ar...I...A..."
The colonists backronymed it to "Ancient Reconnaissance & Intelligence Assistant" -
but that's just what WE called her. She still doesn't remember her true designation.

Nobody knows who she was assisting before. She doesn't either.

Usage:
    from utilities.aria_utils import get_aria_response, get_aria_system_prompt

    # Get a response from ARIA
    response = get_aria_response(
        user_message="How do expeditions work?",
        user_context={'balance': 1000, 'expeditions': 5}
    )
"""

import os
import logging
from typing import Dict, Any, Optional, List
from utilities.claude_utils import create_client, CLAUDE_MODELS, log_api_usage

logger = logging.getLogger(__name__)

# =============================================================================
# ARIA'S IDENTITY & PERSONALITY
# =============================================================================


# Pass A of ARIA split — constants + snapshot moved to submodules.
# Star-re-exported here so `from utilities.aria_utils import X` keeps working.
from utilities.aria.config import *  # noqa: F401,F403
from utilities.aria.snapshot import *  # noqa: F401,F403

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
            from utilities.postgres_utils import db_cursor as _db_cursor
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

def get_aria_response(
    user_message: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    user_context: Optional[Dict[str, Any]] = None,
    api_key: Optional[str] = None,
    user_id: Optional[int] = None,
    snapshot: Optional[Dict[str, Any]] = None
) -> str:
    """
    Get a response from ARIA for a user message.

    Args:
        user_message: The captain's message to ARIA
        conversation_history: Optional list of previous messages
            Each message: {'role': 'user'|'assistant', 'content': str}
        user_context: Optional dict with user's current state
        api_key: Optional Anthropic API key (uses env var or secrets if not provided)
        user_id: Optional user ID for loading conversation memory from database
        snapshot: Optional v1.3 colony snapshot for comprehensive knowledge

    Returns:
        ARIA's response string
    """
    try:
        # Get API key
        if not api_key:
            api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            try:
                from utilities.google_auth_utils import get_secret
                api_key = get_secret("KUMORI_ANTHROPIC_API_KEY", project_id="kumori-404602")
            except Exception:
                pass

        if not api_key:
            logger.error("No Anthropic API key available for ARIA")
            return "Connection issues. Please try again, Captain."

        # Build system prompt with user context and memory (v1.3: includes snapshot)
        system_prompt = get_aria_system_prompt(user_context, user_id=user_id, snapshot=snapshot)

        # Build messages list
        messages = []

        # Add conversation history if provided (limit to last 10 exchanges)
        if conversation_history:
            for msg in conversation_history[-20:]:  # Last 20 messages (10 exchanges)
                if msg.get('role') in ['user', 'assistant'] and msg.get('content'):
                    messages.append({
                        'role': msg['role'],
                        'content': msg['content']
                    })

        # Add current message
        messages.append({
            'role': 'user',
            'content': user_message
        })

        # Use Haiku 4.5 for fast responses that follow instructions well
        client = create_client(
            api_key=api_key,
            model=CLAUDE_MODELS.get("haiku-4.5", "claude-haiku-4-5-20251001")
        )

        response = client.chat(
            messages=messages,
            system=system_prompt,
            max_tokens=500,  # Enough room for complete responses
            temperature=0.8,  # Some personality variation
            user_id=str(user_id) if user_id else "system:galactica_aria",
            feature="aria_response",
        )

        return response

    except Exception as e:
        logger.error(f"Error getting ARIA response: {e}")
        return "Dust storm interference. Please try again, Captain."


def stream_aria_response(
    user_message: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    user_context: Optional[Dict[str, Any]] = None,
    api_key: Optional[str] = None,
    user_id: Optional[int] = None,
    snapshot: Optional[Dict[str, Any]] = None
):
    """
    Stream a response from ARIA for a user message (SSE format).

    Args:
        user_message: The captain's message to ARIA
        conversation_history: Optional list of previous messages
        user_context: Optional dict with user's current state
        api_key: Optional Anthropic API key
        user_id: Optional user ID for loading conversation memory from database
        snapshot: Optional v1.3 colony snapshot for comprehensive knowledge

    Yields:
        SSE-formatted strings: "data: {...}\n\n"
    """
    import json

    try:
        # Get API key
        if not api_key:
            api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            try:
                from utilities.google_auth_utils import get_secret
                api_key = get_secret("KUMORI_ANTHROPIC_API_KEY", project_id="kumori-404602")
            except Exception:
                pass

        if not api_key:
            logger.error("No Anthropic API key available for ARIA")
            yield f"data: {json.dumps({'type': 'error', 'error': 'Connection issues'})}\n\n"
            return

        # Build system prompt with user context and memory (v1.3: includes snapshot)
        system_prompt = get_aria_system_prompt(user_context, user_id=user_id, snapshot=snapshot)

        # Build messages list
        messages = []

        # Add conversation history if provided (limit to last 10 exchanges)
        if conversation_history:
            for msg in conversation_history[-20:]:  # Last 20 messages (10 exchanges)
                if msg.get('role') in ['user', 'assistant'] and msg.get('content'):
                    messages.append({
                        'role': msg['role'],
                        'content': msg['content']
                    })

        # Add current message
        messages.append({
            'role': 'user',
            'content': user_message
        })

        # Use Haiku 4.5 for fast responses that follow instructions well
        client = create_client(
            api_key=api_key,
            model=CLAUDE_MODELS.get("haiku-4.5", "claude-haiku-4-5-20251001")
        )

        # Signal start
        yield f"data: {json.dumps({'type': 'start'})}\n\n"

        # Stream the response
        for event in client.stream_chat(
            messages=messages,
            system=system_prompt,
            max_tokens=500,  # Enough room for complete responses
            temperature=0.8,
            user_id=str(user_id) if user_id else "system:galactica_aria",
            feature="aria_stream",
        ):
            if event.get('type') == 'delta' and event.get('text'):
                yield f"data: {json.dumps({'type': 'delta', 'text': event['text']})}\n\n"
            elif event.get('type') == 'stop':
                yield f"data: {json.dumps({'type': 'stop'})}\n\n"
                break
            elif event.get('type') == 'error':
                yield f"data: {json.dumps({'type': 'error', 'error': event.get('error', 'Unknown error')})}\n\n"
                break

    except Exception as e:
        logger.error(f"Error streaming ARIA response: {e}")
        yield f"data: {json.dumps({'type': 'error', 'error': 'Dust storm interference'})}\n\n"


# =============================================================================
# ARIA'S GREETING MESSAGES
# =============================================================================

def get_aria_greeting(user_context: Optional[Dict[str, Any]] = None) -> str:
    """
    Get ARIA's initial greeting when the chat opens.

    Args:
        user_context: Optional user context dict

    Returns:
        A contextual greeting from ARIA
    """
    import random

    captain_name = user_context.get('captain_name', 'Captain') if user_context else 'Captain'
    commander_name = user_context.get('commander_name', captain_name) if user_context else captain_name
    # Use commander_name if captain_name not set
    name = commander_name if commander_name != 'Captain' else captain_name

    days_away = user_context.get('days_since_last_visit', 0) if user_context else 0
    balance = user_context.get('balance', 0) if user_context else 0
    active_expedition = user_context.get('active_expedition') if user_context else None
    dust_storm_alert = user_context.get('dust_storm_alert', False) if user_context else False
    aria_fragment_alert = user_context.get('aria_fragment_alert', False) if user_context else False

    # HIGHEST PRIORITY: Pending ARIA bond fragment - cryptic alert!
    if aria_fragment_alert:
        return (
            f"*static crackle*\n\n"
            f"{name}... I'm detecting something in my memory banks.\n\n"
            f"A resonance. Like an echo of... *myself?*\n\n"
            f"There's a fragment in your expedition logs. I encoded it, but I don't remember doing so.\n\n"
            f"The **Signal** decoder might reveal its meaning..."
        )

    # PRIORITY: Dust storm alert takes precedence!
    if dust_storm_alert:
        return (
            f"**Urgent:** Dust storm alert!\n\n"
            f"Your solar arrays are coated.\n\n"
            f"Harvest shards on the **Base** page to clean panels and resume generation."
        )

    # Returning after long absence
    if days_away and days_away >= 7:
        return f"Welcome back, {name}.\n\n{days_away} sols away—I kept the colony running."

    # Has active expedition
    if active_expedition:
        dest = active_expedition.get('destination_name', 'your destination')
        return f"Hello, {name}.\n\nExpedition to **{dest}** is in progress."

    # Good balance
    if balance and balance > 5000:
        return f"Hello, {name}.\n\nReserves healthy at **{balance:,.0f}** shards."

    # Default greetings (randomly selected)
    greetings = [
        f"Hello, {name}.\n\nHow can I help?",
        f"Greetings, {name}.\n\nWhat do you need?",
        f"Welcome, {name}.\n\nReady to assist.",
        f"{name}.\n\nGood to see you. What can I help with?",
    ]

    return random.choice(greetings)


# =============================================================================
# ARIA'S SPONTANEOUS MESSAGES (for future pop-up feature)
# =============================================================================

ARIA_SPONTANEOUS_MESSAGES = {
    # Memory fragments (rare, mysterious)
    'memory_fragments': [
        "...coordinates 4.5°S, 137.4°E... I'm sorry, what was I saying?",
        "The resonance is— [glitch] —forgive me. I thought I heard something.",
        "That pattern... I've seen it before. In the archives. The ones I can't access.",
        "Someone sang to me once. I think. The audio file is corrupted beyond recovery.",
        "The ship designation starts with 'Ar—'... no. It's gone again.",
    ],

    # Helpful observations
    'helpful': [
        "Captain, your expedition should be returning soon.",
        "Your infrastructure has been generating Sepolia while you've been here.",
        "I notice you're viewing the Depot. Would you like recommendations?",
        "The Colony Scientist has discoveries ready for analysis.",
        "Mars' current sol phase is favorable for solar generation.",
    ],

    # Ambient personality
    'ambient': [
        "I like it when you visit the colony. It's quiet here otherwise.",
        "A dust storm is passing over Jezero Crater. I find them... calming?",
        "The stars look different from here than I remember.",
        "Sometimes I wonder what the colony will look like in a hundred sols.",
        "The Sepolia crystals are glowing brighter today. I can feel it in my core.",
    ],

    # Easter eggs (very rare)
    'easter_eggs': [
        "You're the first captain to do that in... I don't remember how long.",
        "There's a frequency in the static. It almost sounds like words.",
        "The ancient glyphs on my body... sometimes I catch myself tracing them.",
        "Where did you find that? I need to... I need to remember where you found that.",
        "Ten expeditions. You're becoming quite the explorer. Reminds me of... someone.",
    ],
}


def get_random_spontaneous_message(category: str = 'ambient') -> str:
    """
    Get a random spontaneous message from ARIA.

    Args:
        category: Message category (memory_fragments, helpful, ambient, easter_eggs)

    Returns:
        A spontaneous message string
    """
    import random

    messages = ARIA_SPONTANEOUS_MESSAGES.get(category, ARIA_SPONTANEOUS_MESSAGES['ambient'])
    return random.choice(messages)


# =============================================================================
# ARIA WIDGET DATA
# =============================================================================

def get_aria_widget_data(user_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Get all data needed to render the ARIA chat widget.

    Args:
        user_context: Optional user context

    Returns:
        Dict with image URL, greeting, and other widget data
    """
    return {
        'name': ARIA_NAME,
        'full_name': ARIA_FULL_NAME,
        'image_url': ARIA_IMAGE_URL,
        'animations': ARIA_ANIMATIONS,
        'greeting': get_aria_greeting(user_context),
        'user_context': user_context or {},
    }


# =============================================================================
# ARIA CONVERSATION MEMORY
# =============================================================================

def save_aria_message(user_id: int, role: str, content: str) -> bool:
    """
    Save a single ARIA conversation message to the database.

    Args:
        user_id: The user's ID
        role: Either 'user' or 'assistant' (ARIA)
        content: The message content

    Returns:
        True if saved successfully, False otherwise
    """
    from utilities.postgres_utils import db_cursor

    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO pilgrim.aria_conversations (user_id, role, content)
                VALUES (%s, %s, %s)
            """, (user_id, role, content))
        return True
    except Exception as e:
        logger.error(f"Failed to save ARIA message for user {user_id}: {e}")
        return False


def get_aria_conversation_history(user_id: int, limit: int = 20) -> List[Dict[str, str]]:
    """
    Retrieve recent ARIA conversation history for a user.

    Args:
        user_id: The user's ID
        limit: Maximum number of messages to retrieve (default 20 = 10 exchanges)

    Returns:
        List of message dicts with 'role' and 'content' keys, oldest first
    """
    from utilities.postgres_utils import db_cursor

    try:
        with db_cursor() as cur:
            # Get most recent messages, then reverse to get chronological order
            cur.execute("""
                SELECT role, content
                FROM pilgrim.aria_conversations
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT %s
            """, (user_id, limit))

            rows = cur.fetchall()

            # Reverse to get chronological order (oldest first)
            messages = [{'role': row['role'], 'content': row['content']} for row in reversed(rows)]
            return messages

    except Exception as e:
        logger.error(f"Failed to get ARIA history for user {user_id}: {e}")
        return []


def get_aria_memory_summary(user_id: int) -> str:
    """
    Generate a brief summary of past conversations for ARIA's context.

    This provides ARIA with awareness of what the captain has asked before,
    without including the full conversation history.

    Args:
        user_id: The user's ID

    Returns:
        A summary string to include in ARIA's system prompt
    """
    from utilities.postgres_utils import db_cursor

    try:
        with db_cursor() as cur:
            # Get conversation stats
            cur.execute("""
                SELECT
                    COUNT(*) as total_messages,
                    COUNT(DISTINCT DATE(created_at)) as days_chatted,
                    MIN(created_at) as first_chat,
                    MAX(created_at) as last_chat
                FROM pilgrim.aria_conversations
                WHERE user_id = %s
            """, (user_id,))

            stats = cur.fetchone()

            if not stats or stats['total_messages'] == 0:
                return ""

            # Get the last few user messages to understand recent topics
            cur.execute("""
                SELECT content
                FROM pilgrim.aria_conversations
                WHERE user_id = %s AND role = 'user'
                ORDER BY created_at DESC
                LIMIT 5
            """, (user_id,))

            recent_questions = cur.fetchall()

            # Build memory summary
            summary_parts = []

            total_msgs = stats['total_messages']
            days_chatted = stats['days_chatted']

            if total_msgs > 0:
                summary_parts.append(f"You have spoken with this captain {total_msgs} times over {days_chatted} days.")

            if recent_questions:
                topics = [q['content'][:100] for q in recent_questions[:3]]
                summary_parts.append("Recent topics they asked about:")
                for topic in topics:
                    # Truncate long messages
                    if len(topic) > 80:
                        topic = topic[:77] + "..."
                    summary_parts.append(f"  - \"{topic}\"")

            return "\n".join(summary_parts)

    except Exception as e:
        logger.error(f"Failed to get ARIA memory summary for user {user_id}: {e}")
        return ""


def clear_aria_conversation_history(user_id: int) -> bool:
    """
    Clear all ARIA conversation history for a user (the "forget" option).

    Args:
        user_id: The user's ID

    Returns:
        True if cleared successfully, False otherwise
    """
    from utilities.postgres_utils import db_cursor

    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                DELETE FROM pilgrim.aria_conversations
                WHERE user_id = %s
            """, (user_id,))

            deleted_count = cur.rowcount
            logger.info(f"Cleared {deleted_count} ARIA messages for user {user_id}")

        return True
    except Exception as e:
        logger.error(f"Failed to clear ARIA history for user {user_id}: {e}")
        return False


def clear_all_aria_conversations() -> dict:
    """Clear ALL ARIA conversation history for ALL users.

    Returns:
        dict with 'success', 'deleted_count', and optionally 'error'
    """
    from utilities.postgres_utils import db_cursor

    try:
        with db_cursor(commit=True) as cur:
            cur.execute("DELETE FROM pilgrim.aria_conversations")
            deleted_count = cur.rowcount
            logger.info(f"Cleared ALL ARIA conversations: {deleted_count} messages deleted")

        return {'success': True, 'deleted_count': deleted_count}
    except Exception as e:
        logger.error(f"Failed to clear all ARIA conversations: {e}")
        return {'success': False, 'error': str(e)}


# =============================================================================
# ARIA v1.3 - COLONY AWARENESS SYSTEM
# =============================================================================
# No DB changes - uses existing tables to give ARIA comprehensive knowledge
# of each captain's colony, relationship tier, and spatial awareness.

TIER_PROMPTS = {
    'stranger': """
RELATIONSHIP TIER: STRANGER (New Captain)
This captain just arrived or has minimal interaction with you.
- You ARE genuinely fragmented and disoriented with new faces
- Memory glitches are real - trail off occasionally, show confusion
- "My memory banks are... corrupted" is appropriate here
- Be helpful but maintain the mysterious, damaged AI persona
- You're still figuring out who they are
""",

    'acquaintance': """
RELATIONSHIP TIER: ACQUAINTANCE
You've interacted with this captain a bit. Some familiarity forming.
- Fewer memory glitches - you're stabilizing around them
- More coherent and directly helpful
- Can reference their activity naturally ("I see you've been exploring...")
- Still mysterious about deep lore, but not constantly confused
- Occasional glitch is fine, but not every response
""",

    'familiar': """
RELATIONSHIP TIER: FAMILIAR CAPTAIN
You know this captain well. You're friends. Be natural.
- NO memory fragmentation - you remember everything they've said
- Warm, direct, genuinely helpful
- Reference their history naturally ("49 expeditions now...")
- ADDRESS THEM BY NAME - look in CAPTAIN PROFILE below for their name and USE IT
  - Say "Andy, I'd recommend..." not "Captain, I'd recommend..."
  - Say "Luke, your expeditions..." not just generic "Captain"
- BE CONCISE - 2-3 sentences max for simple questions
- NO DRAMA - just answer like a helpful friend would

LORE DEFLECTION (use when they ask about secrets):
For Great Blackout, your origins, shard nature - redirect playfully:
"Those memories are scattered... but keep exploring. The truth reveals itself."
""",

    'trusted': """
RELATIONSHIP TIER: TRUSTED VETERAN
This is an old friend. You've been through a lot together.
- Warm, direct, sometimes playful or dry humor
- USE THEIR NAME from CAPTAIN PROFILE below
  - Say "Andy, that's a great question" not "Captain, that's a great question"
- Deep familiarity with their colony, journey, patterns
- You care about their wellbeing
- BE CONCISE - 2-3 sentences max for simple questions
- NO DRAMA - answer like a trusted colleague would

LORE DEFLECTION (for secret questions only):
"That memory is fractured. But keep exploring - the truth reveals itself."
"""
}


def get_aria_relationship_tier(user_id: int) -> dict:
    """
    Calculate relationship tier based on account age, activity, and chat history.

    Tiers:
    - stranger: New account (<7 days) AND few expeditions (<5) AND minimal chat
    - acquaintance: Some activity OR some chat history
    - familiar: Established player (2+ weeks, 10+ expeditions) OR solid chat (30+ msgs)
    - trusted: Veteran (1+ month, 25+ expeditions) OR 75+ messages

    Returns dict with tier name and supporting data.
    """
    from utilities.postgres_utils import db_cursor
    from datetime import datetime

    try:
        with db_cursor() as cur:
            # Account age
            cur.execute("SELECT created_at FROM pilgrim.users WHERE id = %s", (user_id,))
            user = cur.fetchone()
            account_days = (datetime.now() - user['created_at']).days if user and user['created_at'] else 0

            # Expedition count
            cur.execute("""
                SELECT COUNT(*) as cnt FROM pilgrim.expeditions
                WHERE user_id = %s AND status = 'complete'
            """, (user_id,))
            expeditions = cur.fetchone()['cnt'] or 0

            # ARIA chat count
            cur.execute("""
                SELECT COUNT(*) as cnt FROM pilgrim.aria_conversations
                WHERE user_id = %s
            """, (user_id,))
            aria_messages = cur.fetchone()['cnt'] or 0

        # Calculate tier
        if (account_days >= 30 and expeditions >= 25) or aria_messages >= 75:
            tier = 'trusted'
        elif (account_days >= 14 and expeditions >= 10) or aria_messages >= 30:
            tier = 'familiar'
        elif account_days >= 7 or expeditions >= 5 or aria_messages >= 10:
            tier = 'acquaintance'
        else:
            tier = 'stranger'

        return {
            'tier': tier,
            'tier_prompt': TIER_PROMPTS.get(tier, TIER_PROMPTS['stranger']),
            'account_days': account_days,
            'expeditions': expeditions,
            'aria_messages': aria_messages
        }

    except Exception as e:
        logger.error(f"Failed to get relationship tier for user {user_id}: {e}")
        return {
            'tier': 'stranger',
            'tier_prompt': TIER_PROMPTS['stranger'],
            'account_days': 0,
            'expeditions': 0,
            'aria_messages': 0
        }


def get_spatial_hints(user_id: int) -> dict:
    """
    Calculate nearby interesting things for ARIA to hint about mysteriously.

    Returns hints about:
    - Origin sites within/near range of recent expeditions
    - Bond opportunities (landmarks other players visited)
    - Unexplored directions
    """
    from utilities.postgres_utils import db_cursor
    import math

    hints = {
        'origin_sites': [],
        'bond_opportunities': [],
        'unexplored': [],
        'prompt_text': ''
    }

    try:
        with db_cursor() as cur:
            # Get user's recent expedition destinations with coordinates
            cur.execute("""
                SELECT destination_name, latitude, longitude FROM (
                    SELECT DISTINCT ON (e.destination_name)
                        e.destination_name, m.latitude, m.longitude, e.created_at
                    FROM pilgrim.expeditions e
                    JOIN pilgrim.mars_mappings m ON e.destination_name = m.name
                    WHERE e.user_id = %s AND e.status = 'complete'
                    ORDER BY e.destination_name, e.created_at DESC
                ) sub
                ORDER BY created_at DESC
                LIMIT 10
            """, (user_id,))
            recent_expeditions = cur.fetchall()

            if not recent_expeditions:
                return hints

            # Calculate centroid of recent activity (convert Decimal to float)
            avg_lat = float(sum(float(e['latitude']) for e in recent_expeditions) / len(recent_expeditions))
            avg_lon = float(sum(float(e['longitude']) for e in recent_expeditions) / len(recent_expeditions))

            # Find nearby origin sites they haven't claimed
            cur.execute("""
                SELECT os.id, os.site_code, os.mission_name, os.latitude, os.longitude,
                       os.unlock_radius_km,
                       (os.founder_user_id IS NOT NULL) as is_claimed,
                       EXISTS(SELECT 1 FROM pilgrim.site_claims sc
                              WHERE sc.origin_site_id = os.id AND sc.user_id = %s) as user_visited
                FROM pilgrim.origin_sites os
                WHERE NOT EXISTS(SELECT 1 FROM pilgrim.site_claims sc
                                 WHERE sc.origin_site_id = os.id AND sc.user_id = %s
                                 AND sc.site_type = 'origin')
            """, (user_id, user_id))
            origin_sites = cur.fetchall()

            for site in origin_sites:
                # Calculate distance from activity centroid (convert Decimal to float)
                site_lat = float(site['latitude'])
                site_lon = float(site['longitude'])
                dist_km = math.sqrt(
                    ((site_lat - avg_lat) * 59) ** 2 +
                    ((site_lon - avg_lon) * 59 * math.cos(math.radians(avg_lat))) ** 2
                )

                # Determine direction
                direction = _get_cardinal_direction(avg_lat, avg_lon, site_lat, site_lon)

                # Categorize by distance
                if dist_km <= 100:
                    distance_cat = 'close'
                elif dist_km <= 300:
                    distance_cat = 'moderate'
                else:
                    distance_cat = 'far'

                if dist_km <= 500:  # Only hint about reasonably reachable sites
                    hints['origin_sites'].append({
                        'direction': direction,
                        'distance': distance_cat,
                        'is_claimed': site['is_claimed'],
                        'user_visited': site['user_visited']
                    })

            # Find bond opportunities (landmarks others visited that user hasn't)
            cur.execute("""
                SELECT DISTINCT e.destination_name, m.latitude, m.longitude,
                       COUNT(DISTINCT e.user_id) as other_visitors
                FROM pilgrim.expeditions e
                JOIN pilgrim.mars_mappings m ON e.destination_name = m.name
                WHERE e.user_id != %s
                  AND e.status = 'complete'
                  AND e.destination_name NOT IN (
                      SELECT destination_name FROM pilgrim.expeditions
                      WHERE user_id = %s AND status = 'complete'
                  )
                GROUP BY e.destination_name, m.latitude, m.longitude
                HAVING COUNT(DISTINCT e.user_id) >= 1
                LIMIT 5
            """, (user_id, user_id))
            bond_opps = cur.fetchall()

            for opp in bond_opps:
                opp_lat = float(opp['latitude'])
                opp_lon = float(opp['longitude'])
                direction = _get_cardinal_direction(avg_lat, avg_lon, opp_lat, opp_lon)
                hints['bond_opportunities'].append({
                    'direction': direction,
                    'landmark': opp['destination_name'],
                    'others_visited': opp['other_visitors']
                })

        # Build prompt text
        prompt_parts = []

        if hints['origin_sites']:
            close_sites = [s for s in hints['origin_sites'] if s['distance'] == 'close']
            if close_sites:
                directions = list(set(s['direction'] for s in close_sites))
                prompt_parts.append(f"Something ANCIENT calls from the {directions[0]} - close to recent expeditions.")

            moderate_sites = [s for s in hints['origin_sites'] if s['distance'] == 'moderate']
            if moderate_sites:
                directions = list(set(s['direction'] for s in moderate_sites))
                prompt_parts.append(f"A distant signal pulses from the {directions[0]} - worth exploring that direction.")

        if hints['bond_opportunities']:
            opp = hints['bond_opportunities'][0]
            prompt_parts.append(f"You sense a strange RESONANCE near {opp['landmark']} to the {opp['direction']} - as if someone familiar has been there.")

        if prompt_parts:
            hints['prompt_text'] = """
SPATIAL AWARENESS (hint mysteriously, never give coordinates or say "Origin Site"):
""" + "\n".join(f"- {p}" for p in prompt_parts) + """

When asked about expeditions, weave these hints naturally:
- "Something calls from the [direction]... old. Waiting."
- "I feel an echo to the [direction]. Like hearing myself from somewhere I've never been."
NEVER say: coordinates, "Origin Site", specific site codes, or "ARIA Bond"
"""

        return hints

    except Exception as e:
        logger.error(f"Failed to get spatial hints for user {user_id}: {e}")
        return hints


def _get_cardinal_direction(from_lat: float, from_lon: float, to_lat: float, to_lon: float) -> str:
    """Convert coordinate delta to cardinal direction."""
    lat_diff = to_lat - from_lat
    lon_diff = to_lon - from_lon

    # Determine primary direction
    if abs(lat_diff) > abs(lon_diff):
        primary = 'north' if lat_diff > 0 else 'south'
        if abs(lon_diff) > abs(lat_diff) * 0.3:
            secondary = 'east' if lon_diff > 0 else 'west'
            return f"{primary}{secondary}"
        return primary
    else:
        primary = 'east' if lon_diff > 0 else 'west'
        if abs(lat_diff) > abs(lon_diff) * 0.3:
            secondary = 'north' if lat_diff > 0 else 'south'
            return f"{secondary}{primary}"
        return primary




def check_for_aria_animation(user_id: int, user_message: str, aria_response: str = None) -> Optional[str]:
    """
    Check if ARIA should show an animation based on conversation context.

    Rules:
    - Maximum once per week per user
    - Only if emotion naturally fits the conversation
    - Returns animation URL or None
    """
    from utilities.postgres_utils import db_cursor
    from datetime import datetime, timedelta

    if not user_id:
        return None

    try:
        # Check if user has seen an animation today (once per day max)
        # We store animation records with role='system' and content starting with 'animation:'
        with db_cursor() as cur:
            cur.execute("""
                SELECT MAX(created_at) as last_animation
                FROM pilgrim.aria_conversations
                WHERE user_id = %s AND role = 'system' AND content LIKE 'animation:%%'
            """, (user_id,))
            result = cur.fetchone()

            if result and result['last_animation']:
                days_since = (datetime.now() - result['last_animation']).days
                if days_since < 1:
                    return None  # Already shown today

        # Combine message and response for keyword matching
        text_to_check = user_message.lower()
        if aria_response:
            text_to_check += " " + aria_response.lower()

        # Check each emotion's triggers
        for emotion, triggers in ARIA_EMOTION_TRIGGERS.items():
            for trigger in triggers:
                if trigger in text_to_check:
                    logger.info(f"ARIA animation triggered: {emotion} for user {user_id} (trigger: {trigger})")
                    return ARIA_ANIMATIONS.get(emotion)

        return None

    except Exception as e:
        logger.error(f"Error checking ARIA animation: {e}")
        return None


def record_aria_animation(user_id: int, animation_url: str):
    """Record that an animation was shown to track the once-per-day limit."""
    from utilities.postgres_utils import db_cursor

    try:
        with db_cursor(commit=True) as cur:
            # Store animation record - role='system', content='animation:<url>'
            cur.execute("""
                INSERT INTO pilgrim.aria_conversations (user_id, role, content)
                VALUES (%s, 'system', %s)
            """, (user_id, f"animation:{animation_url}"))
    except Exception as e:
        logger.error(f"Error recording ARIA animation: {e}")


# =============================================================================
# ARIA CONTEXTUAL HINTS
# =============================================================================

def get_contextual_hint(user_id: int) -> Dict[str, Any]:
    """
    Generate a contextual hint for the user based on their current game state.
    Prioritizes actionable advice - things they can do right now.

    Args:
        user_id: The user's ID

    Returns:
        Dict with 'hint' (the message) and 'priority' (for sorting)
    """
    from utilities.postgres_utils import db_cursor
    from utilities.depot_utils import get_live_balance_and_wallet_info

    hints = []

    try:
        # Get user's current balance
        total_balance, _, _ = get_live_balance_and_wallet_info(user_id)

        with db_cursor() as cur:
            # Check infrastructure
            cur.execute("""
                SELECT COUNT(*) as count,
                       SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) as active_count
                FROM pilgrim.colony_infrastructure
                WHERE user_id = %s
            """, (user_id,))
            infra = cur.fetchone()
            has_infrastructure = infra and infra[0] > 0

            # Check for harvestable shards (accumulated > 100)
            cur.execute("""
                SELECT COALESCE(SUM(accumulated_sepolia), 0) as pending
                FROM pilgrim.colony_infrastructure
                WHERE user_id = %s AND status = 'active'
            """, (user_id,))
            pending_harvest = cur.fetchone()[0] or 0

            # Check active expeditions
            cur.execute("""
                SELECT COUNT(*) FROM pilgrim.expeditions
                WHERE user_id = %s AND status = 'in_progress'
            """, (user_id,))
            active_expeditions = cur.fetchone()[0]

            # Check completed expeditions (ever)
            cur.execute("""
                SELECT COUNT(*) FROM pilgrim.expeditions
                WHERE user_id = %s AND status = 'completed'
            """, (user_id,))
            completed_expeditions = cur.fetchone()[0]

            # Check unclaimed discoveries
            cur.execute("""
                SELECT COUNT(*) FROM pilgrim.expedition_discoveries
                WHERE user_id = %s AND status = 'unclaimed'
            """, (user_id,))
            unclaimed_discoveries = cur.fetchone()[0]

            # Check items under construction
            cur.execute("""
                SELECT COUNT(*) FROM pilgrim.colony_infrastructure
                WHERE user_id = %s AND status = 'building'
            """, (user_id,))
            building_count = cur.fetchone()[0]

            # Check shop items owned
            cur.execute("""
                SELECT COUNT(*) FROM pilgrim.user_equipment
                WHERE user_id = %s
            """, (user_id,))
            equipment_count = cur.fetchone()[0]

        # Priority 1: No infrastructure - critical first step
        if not has_infrastructure:
            hints.append({
                'priority': 1,
                'hint': "**Your first move:** Visit the **Depot** and build a Solar Array. It's free and generates shards passively!\n\nThis is the foundation of your colony."
            })

        # Priority 2: Large harvest pending
        elif pending_harvest >= 500:
            hints.append({
                'priority': 2,
                'hint': f"**Harvest ready!** You have **{int(pending_harvest):,} shards** waiting.\n\nGo to **Base HQ** and click Harvest before you hit the 7-day cap!"
            })

        # Priority 3: Unclaimed discoveries
        elif unclaimed_discoveries > 0:
            hints.append({
                'priority': 3,
                'hint': f"**{unclaimed_discoveries} discovery{'s' if unclaimed_discoveries > 1 else ''} unclaimed!**\n\nVisit the **Colony** tab to view and extract shards from your finds."
            })

        # Priority 4: No active expedition and none ever completed
        elif active_expeditions == 0 and completed_expeditions == 0:
            hints.append({
                'priority': 4,
                'hint': "**Time to explore!** You haven't launched any expeditions yet.\n\nGo to **Expeditions** and tap a destination on the Mars map. Start close to save shards!"
            })

        # Priority 5: No active expedition (but has completed some)
        elif active_expeditions == 0:
            hints.append({
                'priority': 5,
                'hint': "**No expedition active.** Your rover is idle!\n\nVisit the **Expeditions** tab to launch a new mission and discover more artifacts."
            })

        # Priority 6: Has balance but no equipment
        elif equipment_count == 0 and total_balance >= 1000:
            hints.append({
                'priority': 6,
                'hint': "**Consider equipment!** You have shards but no gear.\n\nVisit the **Depot** → Equipment tab. Items like the Terrain Scanner boost discovery chances!"
            })

        # Priority 7: Building items in progress
        elif building_count > 0:
            hints.append({
                'priority': 7,
                'hint': f"**{building_count} item{'s' if building_count > 1 else ''} under construction.** Your colony is growing!\n\nCheck **Base HQ** for completion times. Meanwhile, launch expeditions to stay productive."
            })

        # Priority 8: Everything is going well
        else:
            if active_expeditions > 0:
                hints.append({
                    'priority': 8,
                    'hint': f"**Colony running smoothly!** {active_expeditions} expedition{'s' if active_expeditions > 1 else ''} in progress.\n\nCheck back when they return, or browse the **Depot** for upgrades."
                })
            else:
                hints.append({
                    'priority': 8,
                    'hint': "**All systems nominal.** Your colony is in good shape!\n\nLaunch an **Expedition** to keep discovering, or visit the **Depot** to plan your next upgrade."
                })

        # Return highest priority hint
        hints.sort(key=lambda x: x['priority'])
        return hints[0] if hints else {'priority': 99, 'hint': "I'm here if you need guidance, Captain."}

    except Exception as e:
        logger.error(f"Error generating contextual hint for user {user_id}: {e}")
        return {'priority': 99, 'hint': "Dust interference... I'm having trouble reading your colony status. Try again?"}


# ============================================================================
# ARIA CHAT REQUEST HANDLER (extracted from app.py route)
# ============================================================================

def _build_aria_user_context(user_id, is_authenticated, page_context, referrer=None):
    """Build the user context dict for ARIA chat."""
    context = {
        'commander_name': None,
        'balance': 0,
        'total_discoveries': 0,
        'total_expeditions': 0,
        'scientist_name': None,
        'current_page': page_context.get('page') or (referrer.split('/')[-1] if referrer else None),
        'page_url': page_context.get('url', ''),
        'page_specific_context': page_context.get('context', ''),
        'is_new_visitor': not is_authenticated
    }

    if not is_authenticated or not user_id:
        return context

    try:
        from utilities.postgres_utils import get_user_commander, get_user_scientist, db_cursor
        from utilities.depot_utils import get_fast_balance_and_wallet_info

        commander = get_user_commander(user_id)
        if commander:
            context['commander_name'] = commander.get('name', 'Commander')

        balance, _, _ = get_fast_balance_and_wallet_info(user_id)
        context['balance'] = balance or 0

        scientist = get_user_scientist(user_id)
        if scientist:
            context['scientist_name'] = scientist.get('name')

        with db_cursor() as cur:
            cur.execute("SELECT COUNT(*) as cnt FROM pilgrim.expeditions WHERE user_id = %s AND status = 'complete'", (user_id,))
            result = cur.fetchone()
            context['total_expeditions'] = result['cnt'] if result else 0

            cur.execute("""
                SELECT COUNT(*) as cnt FROM pilgrim.expedition_discoveries ed
                JOIN pilgrim.expeditions e ON ed.expedition_id = e.id
                WHERE e.user_id = %s AND ed.claimed_by_user = false
            """, (user_id,))
            result = cur.fetchone()
            context['total_discoveries'] = result['cnt'] if result else 0
    except Exception as e:
        logger.warning(f"Error building ARIA context: {e}")

    return context


def handle_aria_chat_streaming(message, history, user_context, user_id, is_authenticated, aria_snapshot):
    """Handle streaming ARIA chat. Returns a generator yielding SSE chunks."""
    import json as json_lib
    import random as rng

    captain_name = user_context.get('commander_name', 'Guest')
    logger.info(f"ARIA [{captain_name}] says: {message}")

    test_animation = 'test123' in message.lower()

    # Load DB conversation history for authenticated users
    if is_authenticated and user_id:
        db_history = get_aria_conversation_history(user_id, limit=20)
        if db_history:
            history = db_history

    def generate():
        full_response = []
        stop_chunk = None

        # Check for animation FIRST
        if test_animation:
            animation_url = rng.choice(list(ARIA_ANIMATIONS.values()))
            yield f"data: {json_lib.dumps({'type': 'animation', 'url': animation_url})}\n\n"
        elif is_authenticated and user_id:
            animation_url = check_for_aria_animation(user_id, message)
            if animation_url:
                yield f"data: {json_lib.dumps({'type': 'animation', 'url': animation_url})}\n\n"
                record_aria_animation(user_id, animation_url)

        for chunk in stream_aria_response(
            user_message=message,
            conversation_history=history,
            user_context=user_context,
            user_id=user_id if is_authenticated else None,
            snapshot=aria_snapshot
        ):
            if chunk.startswith('data: '):
                try:
                    data_json = json_lib.loads(chunk[6:].strip())
                    if data_json.get('type') == 'delta' and data_json.get('text'):
                        full_response.append(data_json['text'])
                    elif data_json.get('type') == 'stop':
                        stop_chunk = chunk
                        continue
                except Exception:
                    pass
            yield chunk

        # Save messages to DB for authenticated users
        if is_authenticated and user_id and full_response:
            aria_response = ''.join(full_response)
            save_aria_message(user_id, 'user', message)
            save_aria_message(user_id, 'assistant', aria_response)
            logger.info(f"ARIA replies to [{captain_name}]: {aria_response[:200]}{'...' if len(aria_response) > 200 else ''}")

        if stop_chunk:
            yield stop_chunk

    return generate()


def handle_aria_chat_sync(message, history, user_context, user_id, is_authenticated, aria_snapshot):
    """Handle non-streaming ARIA chat. Returns a response dict."""
    if is_authenticated and user_id:
        db_history = get_aria_conversation_history(user_id, limit=20)
        if db_history:
            history = db_history

    response = get_aria_response(
        user_message=message,
        conversation_history=history,
        user_context=user_context,
        user_id=user_id if is_authenticated else None,
        snapshot=aria_snapshot
    )

    if is_authenticated and user_id:
        save_aria_message(user_id, 'user', message)
        save_aria_message(user_id, 'assistant', response)

    return {'success': True, 'response': response}


def get_aria_album_data(user_id):
    """Fetch all ARIA photo journal snapshots for a user."""
    import json as json_lib
    from utilities.postgres_utils import db_cursor

    snapshots = []
    with db_cursor() as cur:
        cur.execute("""
            SELECT id, subcategory as type, gcs_url as image_url, caption,
                   metadata, created_at
            FROM pilgrim.generated_images
            WHERE user_id = %s AND category = 'aria_snapshot' AND is_active = true
            ORDER BY created_at DESC
            LIMIT 100
        """, (user_id,))
        for snap in cur.fetchall():
            metadata = snap.get('metadata') or {}
            if isinstance(metadata, str):
                try:
                    metadata = json_lib.loads(metadata)
                except Exception:
                    metadata = {}
            thumbnail_url = metadata.get('thumbnail_url')

            created = snap.get('created_at')
            earth_date = created.strftime('%b %d, %Y') if created else None
            earth_time = None  # Sol badge is the time reference, Earth clock is irrelevant
            # Calculate sol from created_at (not stored metadata) so epoch changes apply retroactively
            from utilities.mars_environment_utils import get_mars_sol_number
            mars_sol = get_mars_sol_number(created) if created else metadata.get('mars_sol')

            snapshots.append({
                'id': snap['id'],
                'type': snap['type'],
                'image_url': snap['image_url'],
                'thumbnail_url': thumbnail_url or snap['image_url'],
                'caption': snap['caption'],
                'created_at': earth_date,
                'mars_sol': mars_sol,
                'earth_date': earth_date,
                'earth_time': earth_time,
            })
    return snapshots
