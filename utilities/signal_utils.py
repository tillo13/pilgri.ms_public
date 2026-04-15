"""Shim — real code moved to utilities.signal package.

Kept at this path so gitignored tools/ callers (and any remaining
`from utilities.signal_utils import ...` lines) keep working without
edits. All public names are re-exported explicitly below.
"""

# Constants and tier config
from utilities.signal.config import (
    ECHO_SPAWN_CHANCE,
    ECHO_PITY_TIMER,
    ECHO_MAX_RANKED_CLAIMS,
    ECHO_SITE_EXPIRY_DAYS,
    ORIGIN_DETECTION_RADIUS_KM,
    ORIGIN_LOST_SIGNAL_RADIUS_KM,
    VISITOR_TIERS,
    VISITOR_ITEM_CONFIG,
    get_visitor_tier,
)

# Origin + echo site queries, signal-page data, closest-pilgrim, blockchain msg
from utilities.signal.sites import (
    get_all_origin_sites,
    get_origin_site_by_code,
    check_origin_site_proximity,
    get_active_echo_sites,
    get_recent_echo_claims,
    get_origin_site_visitors,
    _bulk_get_origin_visitors,
    get_expeditions_since_last_echo,
    maybe_spawn_echo_site,
    claim_echo_site,
    get_signal_page_data,
    generate_blockchain_message,
    get_signal_page_render_data,
    get_closest_pilgrim_to_origin,
)

# Claim/visit/eligibility + lost-signal + puzzle decoders
from utilities.signal.claims import (
    claim_origin_site,
    visit_origin_site,
    get_user_origin_site_eligibility,
    get_user_origin_site_discovery_count,
    get_claimable_origin_sites_for_user,
    decode_lost_signal_site,
    get_user_signal_claims,
    decode_signal_puzzle,
    get_puzzle_solvers,
    decode_signal_tx,
)

# Route handlers for claim/visit flows
from utilities.signal.handlers import (
    _get_commander_name_for_user,
    handle_origin_site_claim,
    handle_origin_site_visit,
)

# Legendary item + visitor reward Flux generators
from utilities.signal.rewards import (
    generate_legendary_item_for_origin,
    get_origin_site_legendary_item,
    generate_visitor_reward_image,
)

__all__ = [
    # config
    'ECHO_SPAWN_CHANCE', 'ECHO_PITY_TIMER', 'ECHO_MAX_RANKED_CLAIMS',
    'ECHO_SITE_EXPIRY_DAYS', 'ORIGIN_DETECTION_RADIUS_KM',
    'ORIGIN_LOST_SIGNAL_RADIUS_KM', 'VISITOR_TIERS', 'VISITOR_ITEM_CONFIG',
    'get_visitor_tier',
    # sites
    'get_all_origin_sites', 'get_origin_site_by_code', 'check_origin_site_proximity',
    'get_active_echo_sites', 'get_recent_echo_claims',
    'get_origin_site_visitors', '_bulk_get_origin_visitors',
    'get_expeditions_since_last_echo', 'maybe_spawn_echo_site', 'claim_echo_site',
    'get_signal_page_data', 'generate_blockchain_message',
    'get_signal_page_render_data', 'get_closest_pilgrim_to_origin',
    # claims
    'claim_origin_site', 'visit_origin_site',
    'get_user_origin_site_eligibility', 'get_user_origin_site_discovery_count',
    'get_claimable_origin_sites_for_user', '_get_commander_name_for_user',
    'handle_origin_site_claim', 'handle_origin_site_visit',
    'decode_lost_signal_site', 'get_user_signal_claims',
    'decode_signal_puzzle', 'get_puzzle_solvers', 'decode_signal_tx',
    # rewards
    'generate_legendary_item_for_origin', 'get_origin_site_legendary_item',
    'generate_visitor_reward_image',
]
