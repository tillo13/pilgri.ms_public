"""ARIA animation triggers and contextual hints — weekly animation choice + page-aware hint text.

Extracted from utilities/aria_utils.py (Pass B of the ARIA split).
"""

import logging
from typing import Dict, Any, Optional

from utilities.aria.config import ARIA_ANIMATIONS, ARIA_EMOTION_TRIGGERS

logger = logging.getLogger(__name__)

def check_for_aria_animation(user_id: int, user_message: str, aria_response: str = None) -> Optional[str]:
    """
    Check if ARIA should show an animation based on conversation context.

    Rules:
    - Maximum once per week per user
    - Only if emotion naturally fits the conversation
    - Returns animation URL or None
    """
    from utilities.postgres.core import db_cursor
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
    from utilities.postgres.core import db_cursor

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
    from utilities.postgres.core import db_cursor

    hints = []

    try:
        # One read against the live schema (rewritten 2026-09-27: the old reads named columns and
        # tables that no longer exist, so every player got the fallback line). Expeditions are
        # traveling/returning while out and complete when done; a discovery is unclaimed until
        # it is extracted to inventory (claimed_at).
        with db_cursor() as cur:
            cur.execute("""
                SELECT (SELECT COUNT(*) FROM pilgrim.colony_infrastructure
                         WHERE user_id = %(u)s AND status = 'active') AS infrastructure,
                       (SELECT COUNT(*) FROM pilgrim.expeditions
                         WHERE user_id = %(u)s AND status IN ('traveling', 'returning')) AS active,
                       (SELECT COUNT(*) FROM pilgrim.expeditions
                         WHERE user_id = %(u)s AND status = 'complete') AS completed,
                       (SELECT COUNT(*) FROM pilgrim.expedition_discoveries ed
                          JOIN pilgrim.expeditions e ON e.id = ed.expedition_id
                         WHERE e.user_id = %(u)s AND e.status = 'complete' AND ed.claimed_at IS NULL) AS unclaimed
            """, {'u': user_id})
            row = cur.fetchone()
        active_expeditions, unclaimed_discoveries = row['active'], row['unclaimed']

        if not row['infrastructure']:
            hints.append({
                'priority': 1,
                'hint': "**Your first move:** Visit the **Depot** and build a Solar Array. It's free and generates shards passively!\n\nThis is the foundation of your colony."
            })
        elif unclaimed_discoveries > 0:
            hints.append({
                'priority': 3,
                'hint': f"**{unclaimed_discoveries} {'discoveries' if unclaimed_discoveries > 1 else 'discovery'} unclaimed!**\n\nVisit the **Colony** tab to view and extract shards from your finds."
            })
        elif active_expeditions == 0 and row['completed'] == 0:
            hints.append({
                'priority': 4,
                'hint': "**Time to explore!** You haven't launched any expeditions yet.\n\nGo to **Expeditions** and tap a destination on the Mars map. Start close to save shards!"
            })
        elif active_expeditions == 0:
            hints.append({
                'priority': 5,
                'hint': "**No expedition active.** Your rover is idle!\n\nVisit the **Expeditions** tab to launch a new mission and discover more artifacts."
            })
        else:
            hints.append({
                'priority': 8,
                'hint': f"**Colony running smoothly!** {active_expeditions} expedition{'s' if active_expeditions > 1 else ''} in progress.\n\nCheck back when they return, or browse the **Depot** for upgrades."
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

