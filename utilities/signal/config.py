"""Signal system constants and visitor-tier configuration."""

# ============================================================================
# CONSTANTS
# ============================================================================

ECHO_SPAWN_CHANCE = 0.02  # 2% base chance per expedition
ECHO_PITY_TIMER = 50  # Guaranteed spawn after this many expeditions without one
ECHO_MAX_RANKED_CLAIMS = 10  # First 10 finders get ranked
ECHO_SITE_EXPIRY_DAYS = 7  # Echo sites expire after 7 days
ORIGIN_DETECTION_RADIUS_KM = 42  # Default km radius to claim normal origin sites (42 = Easter egg)
ORIGIN_LOST_SIGNAL_RADIUS_KM = 200  # Km radius for lost signal sites (need decoder first)


# Visitor tier definitions (no cap - 43+ become Wanderers)
VISITOR_TIERS = {
    # Rank range: (tier_name, tier_color, item_rarity)
    (2, 3): ('Early Witness', '#10b981', 'rare'),      # Green - Rare item
    (4, 10): ('Pioneer', '#3b82f6', 'uncommon'),       # Blue - Uncommon item
    (11, 42): ('Pilgrim', '#8b5cf6', 'common'),        # Purple - Common item
    (43, 99999): ('Wanderer', '#6b7280', 'common'),    # Gray - Common item (no cap)
}

# Visitor reward item definitions
VISITOR_ITEM_CONFIG = {
    'Early Witness': {
        'name_pattern': 'Witness Shard: {mission}',
        'description_pattern': "You stood where {mission} first touched Mars. {mission_year}. One of the first to make the pilgrimage after the Founder. Rank #{rank} Early Witness. Witnessed by {commander} ({wallet}).",
        'flux_prompt': "Cartoon video game item with bold outlines and stylized proportions: glowing amber crystal shard with etched ancient circuit patterns running through it, small holographic inscription floating above showing visitor name, rare artifact quality with golden edges, orange-red Mars glow emanating from within, isolated on red Martian terrain, vibrant colors with reds and oranges reflecting Mars atmosphere, video game asset style",
        'blockchain_msg': "ORIGIN_VISIT #{rank} | {mission} | {commander} | {wallet} | The answer may be 42. You are one of them.",
    },
    'Pioneer': {
        'name_pattern': 'Pioneer Fragment: {mission}',
        'description_pattern': "A pilgrim's memento from {mission}. {mission_year}. You followed in the footsteps of the Founder, carrying forward the legacy. Rank #{rank} Pioneer. Carried by {commander} ({wallet}).",
        'flux_prompt': "Cartoon video game item with bold outlines and stylized proportions: rough-hewn crystal fragment with faint geometric markings etched on surface, blue-purple Sepolia veins visible running through the interior, weathered but treasured pilgrim memento, isolated on red Martian terrain, vibrant colors with reds and oranges reflecting Mars atmosphere, video game asset style",
        'blockchain_msg': "ORIGIN_VISIT #{rank} | {mission} | {commander} | {wallet} | The answer may be 42. You are one of them.",
    },
    'Pilgrim': {
        'name_pattern': 'Pilgrim Stone: {mission}',
        'description_pattern': "You made the journey to {mission}. {mission_year}. The path was long, but you found your way. Rank #{rank} Pilgrim. {commander} ({wallet}) was here.",
        'flux_prompt': "Cartoon video game item with bold outlines and stylized proportions: small polished Mars stone with a single Sepolia crystal chip embedded in center, simple but meaningful pilgrim keepsake, red-orange Martian rock coloring, isolated on red Martian terrain, vibrant colors with reds and oranges reflecting Mars atmosphere, video game asset style",
        'blockchain_msg': "ORIGIN_VISIT #{rank} | {mission} | {commander} | {wallet} | The answer may be 42. You are one of them.",
    },
    'Wanderer': {
        'name_pattern': "Wanderer's Mark: {mission}",
        'description_pattern': "One of many who found their way to {mission}. {mission_year}. The journey matters more than the arrival. Rank #{rank} Wanderer. {commander} ({wallet}) passed through.",
        'flux_prompt': "Cartoon video game item with bold outlines and stylized proportions: worn pebble of compressed Martian dust with tiny crystal fleck embedded, humble traveler token showing signs of a long journey, dusty red-brown coloring, isolated on red Martian terrain, vibrant colors with reds and oranges reflecting Mars atmosphere, video game asset style",
        'blockchain_msg': "ORIGIN_VISIT #{rank} | {mission} | {commander} | {wallet} | A pilgrim passed through.",
    },
}


def get_visitor_tier(rank: int) -> tuple:
    """Get tier info for a visitor rank. Returns (tier_name, tier_color, item_rarity)"""
    for (min_rank, max_rank), tier_info in VISITOR_TIERS.items():
        if min_rank <= rank <= max_rank:
            return tier_info
    return ('Wanderer', '#6b7280', 'common')  # Default for overflow
