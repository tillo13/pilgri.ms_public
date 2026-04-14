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

