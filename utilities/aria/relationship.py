"""ARIA relationship tiers + spatial hints — personalization based on captain tenure and map position.

Extracted from utilities/aria_utils.py (Pass B of the ARIA split).
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

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
    from utilities.postgres.core import db_cursor
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
    from utilities.postgres.core import db_cursor
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




