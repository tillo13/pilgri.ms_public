"""
Idle Discovery System - Commanders passively find things while player is away

CONCEPT:
- Commanders with high stats have a chance to discover items while idle
- Runs as a scheduled job (cron) to check inactive users
- Generates AI images for discovered items using Flux
- Saves to inventory and can be featured in re-engagement emails

STAT THRESHOLDS & DISCOVERY CHANCES:
- exploration >= 50: +15% base discovery chance
- leadership >= 50: +10% chance for rare items
- strategy >= 50: reduces "cooldown" between discoveries
- logistics >= 50: +1 item capacity per discovery
- charisma >= 50: +5% chance for legendary

DISCOVERY TYPES:
1. Geological samples (common) - rocks, minerals, crystals
2. Ancient artifacts (uncommon) - alien tech fragments
3. Biological specimens (rare) - fossilized life, extremophiles
4. Anomalous objects (legendary) - unexplained phenomena

FLOW:
1. Cron runs daily: python -m utilities.idle_discovery_utils
2. For each user inactive 1+ days with commander stats:
   a. Calculate discovery chance based on stats
   b. Roll for discovery
   c. If success: generate item, create AI image, save to inventory
   d. Mark discovery for email notification
3. Email system includes new discoveries in nudge emails with images

DATABASE ADDITIONS NEEDED:
- idle_discoveries table (user_id, item_id, discovered_at, image_url, notified)
- Or reuse expedition_discoveries with source='idle'
"""

import logging
import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Discovery chance modifiers based on commander stats
STAT_THRESHOLDS = {
    'exploration': {'threshold': 50, 'base_chance_bonus': 0.15},
    'leadership': {'threshold': 50, 'rare_chance_bonus': 0.10},
    'strategy': {'threshold': 50, 'cooldown_reduction': 0.25},  # 25% faster discoveries
    'logistics': {'threshold': 50, 'extra_items': 1},
    'charisma': {'threshold': 50, 'legendary_chance_bonus': 0.05},
}

# Base discovery chances (per day of inactivity, capped)
BASE_DISCOVERY_CHANCE = 0.10  # 10% base per day
MAX_DISCOVERY_CHANCE = 0.50   # Cap at 50%
MAX_DAYS_ACCUMULATE = 7       # Only accumulate up to 7 days

# Rarity distribution for idle discoveries
IDLE_RARITY_WEIGHTS = {
    'common': 0.60,
    'uncommon': 0.25,
    'rare': 0.12,
    'legendary': 0.03,
}

# Item templates for idle discoveries (flavor text + image prompts)
IDLE_DISCOVERY_TEMPLATES = {
    'common': [
        {
            'name': 'Martian Iron Ore Sample',
            'description': 'A chunk of iron-rich regolith your commander found while surveying.',
            'image_prompt': 'photorealistic rust-red martian rock sample with metallic veins, held in gloved astronaut hand, mars surface background',
            'value_range': (5, 15),
        },
        {
            'name': 'Volcanic Glass Fragment',
            'description': 'Obsidian-like glass from ancient Mars volcanic activity.',
            'image_prompt': 'black volcanic glass shard with iridescent sheen, mars red dust background, scientific specimen',
            'value_range': (8, 20),
        },
        {
            'name': 'Dust Devil Core Sample',
            'description': 'Compressed sediment from the eye of a dust devil.',
            'image_prompt': 'cylindrical core sample of layered red and orange martian sediment, laboratory setting',
            'value_range': (3, 10),
        },
    ],
    'uncommon': [
        {
            'name': 'Crystallized Water Deposit',
            'description': 'Pure ice crystals from deep underground, billions of years old.',
            'image_prompt': 'translucent ice crystals with blue tint, frozen in martian rock, glowing softly',
            'value_range': (25, 50),
        },
        {
            'name': 'Magnetic Anomaly Stone',
            'description': 'A rock with unusual magnetic properties. Origin unknown.',
            'image_prompt': 'dark metallic stone floating slightly above surface, magnetic field visualization, mysterious',
            'value_range': (30, 60),
        },
    ],
    'rare': [
        {
            'name': 'Fossilized Microbial Mat',
            'description': 'Evidence of ancient microbial life. A historic find.',
            'image_prompt': 'layered rock with visible fossil patterns, microscopic life imprints, scientific discovery, mars',
            'value_range': (100, 200),
        },
        {
            'name': 'Ancient Lava Tube Crystal',
            'description': 'Perfectly formed crystals grown in a sealed lava tube for millions of years.',
            'image_prompt': 'geometric purple and blue crystals in cave setting, bioluminescent glow, pristine',
            'value_range': (80, 150),
        },
    ],
    'legendary': [
        {
            'name': 'Artifact Fragment Alpha',
            'description': 'Non-natural material of unknown origin. Analysis pending.',
            'image_prompt': 'alien artifact fragment, smooth metallic surface with geometric patterns, glowing symbols, mysterious technology',
            'value_range': (500, 1000),
        },
        {
            'name': 'Temporal Anomaly Core',
            'description': 'An object that seems to exist slightly out of phase with normal spacetime.',
            'image_prompt': 'glowing orb with reality distortion effect, warped space around it, ethereal light',
            'value_range': (750, 1500),
        },
    ],
}


def calculate_discovery_chance(commander_stats: Dict, days_inactive: int) -> Dict:
    """
    Calculate discovery chance based on commander stats and time away.
    Returns dict with chance breakdown.
    """
    # Cap days for calculation
    effective_days = min(days_inactive, MAX_DAYS_ACCUMULATE)

    # Base chance accumulates with time
    base_chance = min(BASE_DISCOVERY_CHANCE * effective_days, MAX_DISCOVERY_CHANCE)

    # Stat bonuses
    exploration_bonus = 0
    if commander_stats.get('exploration', 0) >= STAT_THRESHOLDS['exploration']['threshold']:
        exploration_bonus = STAT_THRESHOLDS['exploration']['base_chance_bonus']

    total_chance = min(base_chance + exploration_bonus, MAX_DISCOVERY_CHANCE)

    # Rarity modifiers
    rare_bonus = 0
    legendary_bonus = 0

    if commander_stats.get('leadership', 0) >= STAT_THRESHOLDS['leadership']['threshold']:
        rare_bonus = STAT_THRESHOLDS['leadership']['rare_chance_bonus']

    if commander_stats.get('charisma', 0) >= STAT_THRESHOLDS['charisma']['threshold']:
        legendary_bonus = STAT_THRESHOLDS['charisma']['legendary_chance_bonus']

    return {
        'total_chance': total_chance,
        'base_chance': base_chance,
        'exploration_bonus': exploration_bonus,
        'rare_bonus': rare_bonus,
        'legendary_bonus': legendary_bonus,
        'effective_days': effective_days,
    }


def roll_for_discovery(chance_data: Dict) -> Optional[str]:
    """
    Roll for discovery and determine rarity if successful.
    Returns rarity string or None.
    """
    # First roll: did they discover anything?
    if random.random() > chance_data['total_chance']:
        return None

    # Second roll: what rarity?
    weights = IDLE_RARITY_WEIGHTS.copy()

    # Apply stat bonuses to rarity
    if chance_data['rare_bonus'] > 0:
        weights['rare'] += chance_data['rare_bonus']
        weights['common'] -= chance_data['rare_bonus'] / 2
        weights['uncommon'] -= chance_data['rare_bonus'] / 2

    if chance_data['legendary_bonus'] > 0:
        weights['legendary'] += chance_data['legendary_bonus']
        weights['common'] -= chance_data['legendary_bonus']

    # Normalize and pick
    total = sum(weights.values())
    roll = random.random() * total
    cumulative = 0

    for rarity, weight in weights.items():
        cumulative += weight
        if roll <= cumulative:
            return rarity

    return 'common'  # Fallback


def select_discovery_item(rarity: str) -> Dict:
    """Select a random item template for the given rarity."""
    templates = IDLE_DISCOVERY_TEMPLATES.get(rarity, IDLE_DISCOVERY_TEMPLATES['common'])
    template = random.choice(templates)

    # Calculate value
    value = random.randint(template['value_range'][0], template['value_range'][1])

    return {
        'name': template['name'],
        'description': template['description'],
        'image_prompt': template['image_prompt'],
        'rarity': rarity,
        'value': value,
    }


def generate_discovery_image(item: Dict, flux_generator=None) -> Optional[str]:
    """
    Generate an AI image for the discovered item using Flux.
    Returns GCS URL or None.
    """
    if not flux_generator:
        logger.warning("No Flux generator available, skipping image generation")
        return None

    try:
        # Use Flux to generate the image
        # This would call replicate_utils.generate_item_image() or similar
        # For now, return None - implement when ready
        logger.info(f"Would generate image for: {item['name']}")
        return None
    except Exception as e:
        logger.error(f"Failed to generate discovery image: {e}")
        return None


def process_idle_discoveries(dry_run: bool = False):
    """
    Main entry point: check all inactive users and process discoveries.
    Run via cron: python -m utilities.idle_discovery_utils
    """
    from utilities.postgres.notifications import get_inactive_users
    from utilities.postgres.assets import get_commander_stats

    logger.info("Starting idle discovery processing...")

    # Get users inactive for 1+ days
    inactive_users = get_inactive_users(days_inactive=1)
    logger.info(f"Found {len(inactive_users)} inactive users")

    discoveries_made = 0

    for user in inactive_users:
        user_id = user['id']
        days_away = int(user.get('days_away', 1))

        # Get commander stats
        stats = get_commander_stats(user_id)
        if not stats:
            continue

        # Calculate and roll
        chance_data = calculate_discovery_chance(stats, days_away)
        rarity = roll_for_discovery(chance_data)

        if rarity:
            item = select_discovery_item(rarity)
            logger.info(f"User {user_id} discovered: {item['name']} ({rarity})")

            if not dry_run:
                # TODO: Save to database
                # TODO: Generate image
                # TODO: Mark for notification
                pass

            discoveries_made += 1

    logger.info(f"Idle discovery complete: {discoveries_made} discoveries made")
    return discoveries_made


# ============================================================================
# EMAIL INTEGRATION
# ============================================================================

def get_pending_idle_discoveries(user_id: int) -> List[Dict]:
    """Get idle discoveries that haven't been notified yet."""
    # TODO: Implement database query
    return []


def format_discovery_for_email(discovery: Dict) -> str:
    """Format a discovery for inclusion in email."""
    rarity_emoji = {
        'common': '⚪',
        'uncommon': '🟢',
        'rare': '🔵',
        'legendary': '🟡',
    }

    emoji = rarity_emoji.get(discovery['rarity'], '⚪')
    return f"{emoji} {discovery['name']} - {discovery['value']:.0f} Sepolia value"


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Process idle discoveries')
    parser.add_argument('--dry-run', action='store_true', help='Simulate without saving')
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    process_idle_discoveries(dry_run=args.dry_run)
