"""Scientist/Commander character quote generators — used in email notifications.

Extracted from utilities/claude_utils.py (Round 5 refactor).
"""

import logging

logger = logging.getLogger("claude_utils")


def _generate_character_quote(prompt: str, fallback_key: str, fallbacks: dict,
                              default_fallback: str, max_tokens: int = 80,
                              truncate_at: int = 200, api_key: str = None) -> str:
    """
    Generate a character quote using Haiku. Shared by scientist and commander quote generators.
    """
    try:
        # FREE kumori catalog — single-shot, no history. min_chars=1: a one-line
        # quote can fall under the default 80-char gate.
        from utilities.kumori_utils import kumori_llm_chat
        quote, _backend, _a, _d = kumori_llm_chat(
            system="", user_prompt=prompt, max_tokens=max_tokens, temperature=0.9, min_chars=1,
        )
        quote = quote.strip().strip('"').strip("'")
        if len(quote) > truncate_at:
            quote = quote[:truncate_at - 3] + "..."
        return quote
    except Exception as e:
        logger.warning(f"Failed to generate character quote: {e}")
        return fallbacks.get(fallback_key, default_fallback)


# Scientist fallbacks used by generate_scientist_quote
_SCIENTIST_FALLBACKS = {
    'Geology': "The mineral compositions in these samples suggest Mars has far more secrets to reveal.",
    'Astrobiology': "Every specimen brings us closer to answering humanity's greatest question.",
    'Atmospheric Science': "The atmospheric readings are fascinating - Mars continues to surprise us.",
    'Botany': "The growth patterns we're seeing could revolutionize off-world agriculture.",
    'Chemistry': "The molecular structures in these samples are unlike anything we've catalogued before.",
    'Engineering': "These components could improve our infrastructure efficiency significantly.",
    'Physics': "The energy signatures we're detecting warrant much deeper investigation.",
    'Hydrology': "Water traces in these samples tell a compelling story about Mars' past.",
    'Xenobiology': "The organic compounds we're finding challenge our assumptions about life.",
    'Planetary Science': "Each discovery paints a richer picture of Mars' geological history.",
}

# Commander fallbacks used by generate_commander_quote
_COMMANDER_FALLBACKS = {
    'leadership': "The crew looks to us for direction. Every decision we make shapes our colony's future.",
    'strategy': "I've been studying the terrain data. There's an optimal route forming in my mind.",
    'exploration': "The horizon calls to me. Every unexplored region holds secrets waiting to be found.",
    'logistics': "Efficient supply chains are the backbone of any successful expedition. We're well-prepared.",
    'charisma': "Building relationships with the crew pays dividends. A motivated team achieves the impossible.",
}


def generate_scientist_quote(scientist_name: str, specialty: str,
                            total_scientific_value: float = 0,
                            research_points: int = 0,
                            pending_discoveries: int = 0,
                            latest_discovery: str = None,
                            api_key: str = None) -> str:
    """
    Generate a personalized scientist quote for email notifications.
    Uses Haiku for speed and cost-efficiency.
    """
    context_parts = []
    if pending_discoveries > 0:
        context_parts.append(f"{pending_discoveries} discoveries awaiting analysis")
    if research_points > 0:
        context_parts.append(f"{research_points} research points available for experiments")
    if total_scientific_value > 100:
        context_parts.append(f"total scientific contributions worth {total_scientific_value:.0f} points")
    if latest_discovery:
        context_parts.append(f"recently found: {latest_discovery}")

    context = ", ".join(context_parts) if context_parts else "ongoing Mars research"

    prompt = f"""You are {scientist_name}, a Mars colony scientist specializing in {specialty}.
Generate a single short sentence (15-25 words max) that you might say in an email update to a colony commander.

Current colony status: {context}

Your quote should:
- Sound like a real scientist excited about their work
- Reference your specialty ({specialty}) naturally
- Be encouraging and hint at discoveries/potential
- Feel personal, not generic

Just output the quote, no quotation marks or attribution. One sentence only."""

    return _generate_character_quote(
        prompt=prompt, fallback_key=specialty, fallbacks=_SCIENTIST_FALLBACKS,
        default_fallback="The specimens you've brought back are truly remarkable.",
        max_tokens=80, truncate_at=200, api_key=api_key
    )


def generate_commander_quote(commander_name: str, stats: dict,
                            active_expeditions: list = None,
                            suggested_destinations: list = None,
                            total_expeditions: int = 0,
                            api_key: str = None) -> str:
    """
    Generate a personalized commander quote for email notifications.
    Uses Haiku for speed and cost-efficiency.
    """
    stat_descriptions = {
        'leadership': 'inspiring crews and managing colony morale',
        'strategy': 'planning expeditions and optimizing routes',
        'exploration': 'discovering new territories and finding rare specimens',
        'logistics': 'efficient resource management and faster travel',
        'charisma': 'negotiation and extraction bonuses'
    }

    if stats:
        best_stat = max(stats.items(), key=lambda x: x[1] if isinstance(x[1], (int, float)) else 0)
        best_stat_name, best_stat_value = best_stat
        stat_context = f"Your strongest trait is {best_stat_name} ({best_stat_value}) - {stat_descriptions.get(best_stat_name, 'a valuable skill')}"
    else:
        stat_context = "You're a balanced commander"
        best_stat_name = "leadership"

    if active_expeditions and len(active_expeditions) > 0:
        exp = active_expeditions[0]
        dest_name = exp.get('destination_name') or exp.get('name', 'an uncharted location')
        expedition_context = f"Currently on expedition to {dest_name}"
    elif suggested_destinations and len(suggested_destinations) > 0:
        dest = suggested_destinations[0]
        dest_name = dest.get('name', 'an unexplored region')
        expedition_context = f"Potential destination: {dest_name}"
    else:
        expedition_context = f"Total expeditions completed: {total_expeditions}"

    prompt = f"""You are Captain {commander_name}, a Mars colony leader reflecting on your mission.

Your profile:
- {stat_context}
- {expedition_context}

Generate 1-2 short sentences (25-40 words max) as a personal message to your colony report.
- Reference your strongest stat ({best_stat_name}) naturally in how you approach things
- Mention the expedition context (where you're headed OR where you could go)
- Sound like a confident but thoughtful leader
- Be motivational without being cheesy

Just output the quote directly, no quotation marks. One to two sentences only."""

    return _generate_character_quote(
        prompt=prompt, fallback_key=best_stat_name, fallbacks=_COMMANDER_FALLBACKS,
        default_fallback=_COMMANDER_FALLBACKS['leadership'],
        max_tokens=100, truncate_at=250, api_key=api_key
    )
