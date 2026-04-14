"""ARIA greetings and widget data — context-sensitive first messages + spontaneous ambient lines.

Extracted from utilities/aria_utils.py (Pass B of the ARIA split).
"""

import logging
from typing import Dict, Any, Optional

from utilities.aria.config import ARIA_NAME, ARIA_IMAGE_URL

logger = logging.getLogger(__name__)

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

