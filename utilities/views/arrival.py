"""Arrival / command page view data."""

import logging

logger = logging.getLogger(__name__)


def get_crew_page_data_authenticated(user_id):
    """Full data bundle for the authenticated crew page (reuses command page data)."""
    from utilities.depot_utils import get_pricing_info
    from utilities.postgres.robot import get_robot_page_data
    from utilities.upgrades_utils import get_user_upgrade_level
    data = get_command_page_data(user_id)
    data['pricing'] = get_pricing_info(user_id)
    data['robot_data'] = get_robot_page_data(user_id)
    # Bug #1303: trails tab needs to know whether to surface a Drone card +
    # Narog card in the "Your Crew" contribution row. Drone km is fed by the
    # maintenance + mining drone upgrades' trail_km_per_hour values (see
    # utilities/postgres/trails/segments.py:545); either one being level ≥ 1
    # means the captain has a contributing drone.
    data['has_drone'] = (
        get_user_upgrade_level(user_id, 'maintenance', 'maintenance') >= 1
        or get_user_upgrade_level(user_id, 'mining', 'mining') >= 1
    )
    return data


def get_command_page_data(user_id):
    """
    Get all data needed for the colony/command page.
    Consolidates ~80 lines of logic from app.py.

    Returns:
        dict with all template variables for command.html
    """
    from utilities.postgres.assets import get_asset_edit_chain
    from utilities.postgres.users import get_user_scientist, assign_scientist_to_user, get_user_research_data
    from utilities.depot_utils import get_commander_and_stats, get_fast_balance_and_wallet_info, get_pricing_info, get_latest_character_image, eth_to_display
    from utilities.postgres.assets import get_user_replicate_assets
    from utilities.shop_utils import get_effective_commander_stats

    primary_commander, base_stats = get_commander_and_stats(user_id)
    # Apply EVA Suit stat bonuses for display
    commander_stats = get_effective_commander_stats(user_id, base_stats) if base_stats else None

    # Get research bonuses for stat display
    research_data = get_user_research_data(user_id)
    stat_bonuses = research_data.get('stat_bonuses', {}) if research_data else {}

    # Get or assign scientist
    scientist = get_user_scientist(user_id)
    if not scientist:
        assign_scientist_to_user(user_id)
        scientist = get_user_scientist(user_id)
    total_balance, wallet_info, _ = get_fast_balance_and_wallet_info(user_id)  # FAST: no blockchain

    # Single query for both character_image and edited_image
    from utilities.postgres.assets import get_user_commander_images
    commander_images = get_user_commander_images(user_id, limit=50)
    all_images = commander_images['all_images']  # Already sorted by created_at desc
    all_videos = get_user_replicate_assets(user_id, asset_type='character_video', limit=50)

    has_commander = len(all_images) > 0
    commander = character_url = character_video_url = None
    image_history = []
    original_image_url = current_asset_id = None
    all_commanders = []

    if has_commander:
        # Use the PRIMARY/ACTIVE captain, not just the latest by date
        if primary_commander:
            commander = primary_commander
            character_url = commander['gcs_url']
            current_asset_id = commander['id']
        else:
            # Fallback to latest if no primary set
            try:
                character_url, current_asset_id = get_latest_character_image(user_id)
                commander = next((img for img in all_images if img['id'] == current_asset_id), all_images[0])
            except:
                commander = all_images[0]
                character_url, current_asset_id = commander['gcs_url'], commander['id']

        # Get video linked to the active captain, or latest video
        linked_video = next((v for v in all_videos if v.get('parent_asset_id') == current_asset_id), None)
        if linked_video:
            character_video_url = linked_video['gcs_url']
        elif all_videos:
            character_video_url = all_videos[0]['gcs_url']

        chain = get_asset_edit_chain(current_asset_id)
        image_history = [asset['gcs_url'] for asset in chain]
        original_image_url = image_history[0] if image_history else None

        for img in all_images:
            linked_vid = next((v for v in all_videos if v.get('parent_asset_id') == img['id']), None)
            all_commanders.append({
                'id': img['id'], 'image_url': img['gcs_url'], 'asset_type': img['asset_type'],
                'is_original': img.get('is_original', False), 'edit_number': img.get('edit_number'),
                'created_at': img['created_at'], 'is_active': img.get('is_primary_character', False),
                'video_url': linked_vid['gcs_url'] if linked_vid else None,
                'prompt_used': img.get('prompt_used')
            })

    # Check if user has research station for crew page link
    from utilities.tech_utils import _has_research_station
    has_research_station = _has_research_station(user_id)

    # Scientist research stats for crew page
    scientist_research = {'sv_rate': 0, 'sv_total': 0, 'sv_available': 0, 'sv_accumulated': 0}
    if scientist and has_research_station:
        from utilities.postgres.users import get_passive_sv
        from utilities.tech_utils import _get_available_sv
        from utilities.infrastructure_utils import calculate_accumulated_income
        scientist_research['sv_rate'] = 2.0  # From research_station config
        scientist_research['sv_total'] = int(get_passive_sv(user_id))
        scientist_research['sv_available'] = _get_available_sv(user_id)
        calc = calculate_accumulated_income(user_id)
        scientist_research['sv_accumulated'] = round(calc.get('sv_accumulated', 0), 1)

    # Get base coordinates for trail map centering
    from utilities.infrastructure_utils import get_or_set_user_mars_home
    base_coords = get_or_set_user_mars_home(user_id)

    # ARIA skills for crew page display (Resonance, Crystal Sensing, Lore Memory)
    from utilities.postgres.trails import get_aria_skills
    aria_skills = get_aria_skills(user_id)

    return {
        'has_commander': has_commander, 'commander': commander, 'character_url': character_url,
        'character_video_url': character_video_url, 'commander_stats': commander_stats,
        'stat_bonuses': stat_bonuses,
        'current_balance': total_balance, 'wallet_info': wallet_info, 'pricing': get_pricing_info(),
        'image_history': image_history, 'original_image_url': original_image_url,
        'current_asset_id': current_asset_id, 'all_commanders': all_commanders,
        'scientist': scientist, 'has_research_station': has_research_station,
        'scientist_research': scientist_research, 'base_coords': base_coords,
        'all_scientists': _get_all_scientists_with_bonuses(),
        'aria_skills': aria_skills,
    }

def _get_all_scientists_with_bonuses():
    """Get all scientists with their research branch bonuses for the swap modal."""
    from config import COLONY_SCIENTISTS
    from config_tech import get_scientist_branch_bonuses
    result = {}
    for key, sci in COLONY_SCIENTISTS.items():
        entry = dict(sci)
        entry['_branch_bonuses'] = get_scientist_branch_bonuses(key)
        result[key] = entry
    return result
