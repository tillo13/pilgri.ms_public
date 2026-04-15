"""Narog (golem) name suggestion generator.

Extracted from utilities/claude_utils.py (Round 5 refactor).
"""

import logging

from utilities.anthropic.pricing import CLAUDE_MODELS
from utilities.anthropic.client import _get_anthropic_api_key
from utilities.anthropic.convenience import create_client

logger = logging.getLogger("claude_utils")

_GOLEM_FALLBACK_NAMES = ['Cairn', 'Regolith', 'Basalt', 'Cinder', 'Shard']


def suggest_golem_names(user_id: int, commander_name: str = None,
                        scientist_name: str = None, stage_sources: list = None,
                        api_key: str = None) -> list:
    """
    Generate 5 lore-appropriate Narog name suggestions using Haiku.
    (Narog = Not A Robot Or Golem — the crew couldn't agree what to call it.)
    Mines ARIA chat history, captain/scientist context, and expedition
    discoveries for personality clues and any names the captain mentioned.
    """
    context_parts = []
    if commander_name:
        context_parts.append(f"Captain's name: {commander_name}")
    if scientist_name:
        context_parts.append(f"Scientist's name: {scientist_name}")
    if stage_sources:
        items = [s.get('item_name', '') for s in stage_sources if s]
        landmarks = [s.get('landmark_name', '') for s in stage_sources if s]
        if items:
            context_parts.append(f"Narog forged from these discoveries: {', '.join(items)}")
        if landmarks:
            context_parts.append(f"Discoveries recovered at: {', '.join(landmarks)}")

    # Mine ARIA chat history for personality, preferences, name mentions
    chat_snippet = ""
    try:
        from utilities.aria.conversation import get_aria_conversation_history
        history = get_aria_conversation_history(user_id, limit=40)
        if history:
            user_msgs = [m['content'][:200] for m in history if m['role'] == 'user']
            if user_msgs:
                chat_snippet = "Recent things the captain said to ARIA:\n" + "\n".join(user_msgs[-15:])
    except Exception as e:
        logger.warning(f"Failed to load ARIA history for golem names: {e}")

    context = ". ".join(context_parts) if context_parts else "A Mars colony Narog"

    prompt = f"""You are naming a Narog — a stone creature built from Martian rock and Sepolia crystal,
forged from real expedition discoveries on Mars. (Narog = "Not A Robot Or Golem" — the captain
and scientist couldn't agree what to call it, so the name stuck.)

Colony context: {context}

{chat_snippet}

Study the captain's chat history and colony context carefully. Look for:
- Any names they mentioned wanting to call their Narog, golem, or robot
- Personality clues, favorite places, references, jokes
- The discovery items and landmarks the Narog was forged from

Generate exactly 5 short Narog names (1-2 words each) that feel PERSONAL to this specific captain.
Names should feel ancient, geological, Martian — like a stone companion, not a weapon.
If the captain mentioned a specific name in chat, include it as the first suggestion.

Output ONLY the 5 names, one per line, nothing else. No numbering, no explanations."""

    try:
        api_key = _get_anthropic_api_key(api_key)
        client = create_client(api_key, model=CLAUDE_MODELS.get("haiku-4.5", "claude-haiku-4-5-20251001"))
        result = client.generate_text(
            prompt, max_tokens=100, temperature=1.0,
            user_id=str(user_id) if user_id else "system:galactica_golem_names",
            feature="golem_names",
        )
        names = [n.strip().strip('"').strip("'") for n in result.strip().split('\n') if n.strip()]
        return names[:5] if len(names) >= 5 else names + _GOLEM_FALLBACK_NAMES[len(names):5]
    except Exception as e:
        logger.warning(f"Failed to generate golem names: {e}")
        return _GOLEM_FALLBACK_NAMES[:5]
