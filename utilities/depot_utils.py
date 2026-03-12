"""
Depot Utilities - Supply Depot Operations
Handles pricing, purchases, transactions, and asset retrieval
"""
import json
import logging
import requests
from datetime import datetime
from utilities.sepolia_utils import MarsAsteroidMiner, sanitize_tx_error
from utilities.postgres_utils import (
    get_user_primary_sepolia_wallet,
    update_sepolia_wallet_balance,
    get_user_replicate_assets,
    create_depot_transaction,
    db_cursor
)

logger = logging.getLogger(__name__)

##############################################################################
# PRICING CONSTANTS
##############################################################################

STAT_REROLL_COST_ETH = 0.000001      # 10.0 Sepolia
CHARACTER_MODIFY_COST_ETH = 0.000002  # 20.0 Sepolia
VIDEO_GENERATION_COST_ETH = 0.000009  # 90.0 Sepolia

# Default gas pricing (Sepolia testnet is consistently low - ~0-2 gwei)
DEFAULT_GAS_GWEI = 1.0  # Typical Sepolia gas price
DEFAULT_GAS_UNITS = 21000 + (250 * 68)  # Base tx + typical message data
DEFAULT_FEE_MULTIPLIER = 1.0  # Optimal conditions (low gas = no fee)

# Operations fee buffer - add to all purchases to cover blockchain tx costs
# ~500 display shards covers typical gas, 1000 gives safety margin
OPERATIONS_FEE_BUFFER_ETH = 0.0001  # 1000 display shards
OPERATIONS_FEE_BUFFER_DISPLAY = 1000  # For display calculations

##############################################################################
# DISPLAY CONVERSION
##############################################################################

def eth_to_display(eth_value):
    """Convert ETH to display Sepolia (10,000,000x multiplier)"""
    if eth_value is None:
        return 0.0
    return round(float(eth_value) * 10000000, 1)

def display_to_eth(display_value):
    """Convert display Sepolia back to ETH"""
    if display_value is None:
        return 0.0
    return float(display_value) / 10000000

##############################################################################
# CONTENT FILTER
##############################################################################

def get_blocked_words():
    """Get blocked words from LDNOOBW repository"""
    try:
        url = "https://tinyurl.com/35wba3d6"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            return [word.strip() for word in response.text.split('\n') if word.strip()]
    except Exception as e:
        logger.warning(f"Failed to fetch blocked words: {e}")
    return ['placeholder1', 'placeholder2']

def check_content_filter(message: str) -> tuple:
    """Check if message contains disallowed content"""
    try:
        blocked_phrases = get_blocked_words()
        message_lower = message.lower()
        for phrase in blocked_phrases:
            if phrase.lower() in message_lower:
                return False, "Please keep modification requests appropriate and respectful."
        return True, None
    except Exception as e:
        logger.error(f"Content filter error: {e}")
        return True, None

##############################################################################
# ASSET RETRIEVAL
##############################################################################

def get_latest_character_image(user_id: int) -> tuple:
    """
    Get the ACTIVE commander's image (the one with is_primary_character=true).
    Falls back to most recent image if no primary is set.

    Returns:
        tuple: (image_url, asset_id)
    """
    from utilities.postgres_utils import get_primary_commander, get_user_commander_images

    # First, try to get the ACTIVE (primary) commander
    primary = get_primary_commander(user_id)
    if primary:
        logger.info(f"📸 Active commander: {primary['asset_type']} (ID: {primary['id']}) - {primary.get('commander_name', 'Unknown')}")
        return primary['gcs_url'], primary['id']

    # Fallback: get most recent image if no primary set
    result = get_user_commander_images(user_id, limit=1)
    all_images = result['all_images']

    if not all_images:
        raise Exception('No character image found')

    latest = all_images[0]
    logger.info(f"📸 Fallback to latest image: {latest['asset_type']} (ID: {latest['id']})")

    return latest['gcs_url'], latest['id']

def get_latest_character_video(user_id: int) -> tuple:
    """
    Get the LATEST character video
    
    Returns:
        tuple: (video_url, video_asset_id, linked_image_asset_id) or (None, None, None)
    """
    all_videos = get_user_replicate_assets(user_id, asset_type='character_video', limit=50)
    
    if not all_videos:
        return None, None, None
    
    all_videos.sort(key=lambda x: x['created_at'], reverse=True)
    latest_video = all_videos[0]
    
    logger.info(f"🎬 Latest video (ID: {latest_video['id']})")
    
    return (
        latest_video['gcs_url'],
        latest_video['id'],
        latest_video.get('parent_asset_id')
    )

##############################################################################
# PRICING
##############################################################################

def get_pricing_info(user_id: int = None) -> dict:
    """Get pricing info for templates, including escalating costs for authenticated users."""
    from utilities.postgres_utils import (
        get_user_escalation_counts, calculate_reroll_cost, calculate_transmutation_cost
    )

    # Base/fixed costs
    modify_cost = eth_to_display(CHARACTER_MODIFY_COST_ETH)

    # For authenticated users, get escalating costs
    if user_id:
        counts = get_user_escalation_counts(user_id)
        total_rerolls = counts.get('total_rerolls', 0)
        total_transmutations = counts.get('total_transmutations', 0)

        # First transmutation is FREE for new players!
        transmutation_cost = 0 if total_transmutations == 0 else calculate_transmutation_cost(total_transmutations)

        return {
            'reroll_cost': calculate_reroll_cost(total_rerolls),
            'transmutation_cost': transmutation_cost,
            'transmutation_is_free': total_transmutations == 0,  # Flag for UI
            'modify_cost': modify_cost,
            # Include counts for UI display (show "3rd reroll" etc)
            'reroll_count': total_rerolls,
            'transmutation_count': total_transmutations,
            # Next ordinal for display
            'next_reroll_ordinal': total_rerolls + 1,
            'next_transmutation_ordinal': total_transmutations + 1
        }

    # Anonymous users see base costs (first transmutation will be free when they log in)
    return {
        'reroll_cost': 500,  # First reroll cost
        'transmutation_cost': 0,  # First transmutation is FREE!
        'transmutation_is_free': True,
        'modify_cost': modify_cost,
        'reroll_count': 0,
        'transmutation_count': 0,
        'next_reroll_ordinal': 1,
        'next_transmutation_ordinal': 1
    }

def get__bal(user_id):
    """
    Get CACHED balance from database - fast, no blockchain call.
    Use this for display purposes (nav bar, page loads).

    Returns:
        float: balance in display units (Sepolia shards), or 0
    """
    primary_wallet = get_user_primary_sepolia_wallet(user_id)
    if not primary_wallet:
        return 0
    return eth_to_display(primary_wallet.get('current_balance_eth', 0))


# Session cache helpers - canonical implementations in session_helpers.py
# Re-exported here for backward compatibility with existing callers
from utilities.session_helpers import (  # noqa: E402
    invalidate_balance_cache,
    invalidate_nav_stats_cache,
    invalidate_commander_cache,
    invalidate_dust_storm_cache,
    invalidate_all_caches,
    update_session_balance,
)


def get_fast_balance_and_wallet_info(user_id):
    """
    FAST version - uses DB cache (not blockchain).
    ALWAYS syncs session cache to DB value to prevent inconsistencies.

    Returns:
        tuple: (balance_display, wallet_info_dict, primary_wallet) or (0, None, None)
    """
    primary_wallet = get_user_primary_sepolia_wallet(user_id)
    if not primary_wallet:
        return 0, None, None

    # Always use DB cache (accurate) - session cache can get stale
    balance = eth_to_display(primary_wallet.get('current_balance_eth', 0))

    # Sync session cache to DB value (only in request context — cron/QA bot has no session)
    try:
        from flask import session, has_request_context
        if has_request_context():
            session['_bal'] = balance
            session.modified = True
    except Exception:
        pass

    wallet_info = {
        'address': primary_wallet['wallet_address'],
        'etherscan_url': f"https://sepolia.etherscan.io/address/{primary_wallet['wallet_address']}"
    }

    return balance, wallet_info, primary_wallet


def get_user_balance(user_id):
    """
    DEPRECATED: Hits blockchain - DO NOT USE for UI display.
    Use session['_bal'] or get__bal() instead.

    This function exists for backwards compatibility only.
    All new code should use the session cache as the golden value.

    Returns:
        float: Balance in display units (0 if no wallet)
    """
    import logging
    logging.getLogger(__name__).warning(f"⚠️ DEPRECATED: get_user_balance() called for user {user_id} - use session cache instead")
    balance, _, _ = get_live_balance_and_wallet_info(user_id)
    return balance

def get_live_balance_and_wallet_info(user_id):
    """
    Get live blockchain balance + wallet info dict for a user.
    WARNING: This hits the blockchain - use sparingly (purchases, explicit refresh).
    For display purposes, use get__bal() instead.

    Returns:
        tuple: (balance_display, wallet_info_dict, primary_wallet) or (0, None, None)
    """
    primary_wallet = get_user_primary_sepolia_wallet(user_id)
    if not primary_wallet:
        return 0, None, None

    miner = MarsAsteroidMiner()
    balance_eth = miner.get_live_wallet_balance(
        primary_wallet['wallet_address'],
        fallback_balance=primary_wallet.get('current_balance_eth', 0)
    )

    wallet_info = {
        'address': primary_wallet['wallet_address'],
        'etherscan_url': f"https://sepolia.etherscan.io/address/{primary_wallet['wallet_address']}"
    }

    return eth_to_display(balance_eth), wallet_info, primary_wallet

def get_commander_and_stats(user_id):
    """
    Get primary commander and extracted stats for a user.
    Replaces repeated commander fetch + stats extraction in app.py.

    Returns:
        tuple: (commander_dict, stats_dict) or (None, None)
    """
    from utilities.postgres_utils import get_primary_commander

    commander = get_primary_commander(user_id)
    stats = extract_commander_stats(commander) if commander else None
    return commander, stats

##############################################################################
# WALLET & BALANCE
##############################################################################

def get_user_wallet_and_balance(session) -> tuple:
    """Get user's wallet and current balance from database"""
    user_id = session.get('user_id')
    
    if user_id:
        wallet = get_user_primary_sepolia_wallet(user_id)
        if not wallet:
            raise Exception('No wallet found for authenticated user')
        current_balance_eth = float(wallet.get('current_balance_eth', 0))
        return wallet, current_balance_eth
    else:
        # New slim format: just wallet address in session, look up from DB
        from utilities.postgres_utils import get_wallet_by_address
        session_wallet_addr = session.get('_wal_addr')
        if session_wallet_addr:
            wallet = get_wallet_by_address(session_wallet_addr)
            if wallet:
                current_balance_eth = float(wallet.get('current_balance_eth', 0))
                return wallet, current_balance_eth

        # Legacy format fallback
        session_wallet = session.get('_wal')
        if not session_wallet or 'wallet' not in session_wallet:
            raise Exception('No wallet found for anonymous user')
        wallet = {
            'wallet_address': session_wallet['wallet']['address'],
            'wallet_private_key': session_wallet['wallet']['private_key'],
        }
        current_balance_eth = 0.0
        return wallet, current_balance_eth

def check_sufficient_balance(current_balance_eth: float, required_eth: float, include_ops_fee: bool = True) -> tuple:
    """Check if user has sufficient balance (includes operations fee buffer by default)"""
    total_needed = required_eth + (OPERATIONS_FEE_BUFFER_ETH if include_ops_fee else 0)
    if current_balance_eth < total_needed:
        return False, (
            f'Insufficient shards. Need {eth_to_display(total_needed):.0f} '
            f'(includes operations fee), have {eth_to_display(current_balance_eth):.0f}'
        )
    return True, None

##############################################################################
# TRANSACTION PROCESSING
##############################################################################

def execute_purchase_transaction(wallet: dict, amount_eth: float, reason: str,
                                  user_id=None, purchase_type=None,
                                  item_details=None, related_asset_id=None) -> float:
    """Deduct balance from DB immediately, fire blockchain tx in background.
    Returns new_balance_eth for callers to use."""
    current_balance = float(wallet.get('current_balance_eth', 0))
    new_balance = current_balance - amount_eth
    update_sepolia_wallet_balance(wallet['wallet_address'], new_balance)

    background_blockchain_tx(
        wallet_address=wallet['wallet_address'],
        wallet_private_key=wallet['wallet_private_key'],
        amount_eth=amount_eth, reason=reason,
        user_id=user_id, purchase_type=purchase_type,
        item_details=item_details, related_asset_id=related_asset_id
    )

    return new_balance


def background_blockchain_tx(wallet_address, wallet_private_key, amount_eth, reason,
                              user_id=None, purchase_type=None, item_details=None,
                              related_asset_id=None):
    """Send blockchain tx in background thread. DB balance must already be deducted."""
    import threading

    def _send():
        try:
            miner = MarsAsteroidMiner()
            tx_result = miner.return_to_hub(
                from_address=wallet_address,
                from_private_key=wallet_private_key,
                amount_eth=amount_eth,
                reason=reason
            )
            if tx_result.get('success'):
                logger.info(f"✅ Background tx confirmed: {tx_result['tx_hash']}")
                if user_id and purchase_type:
                    create_depot_transaction(
                        user_id=user_id, wallet_address=wallet_address,
                        purchase_type=purchase_type, amount_eth=amount_eth,
                        tx_hash=tx_result['tx_hash'],
                        block_number=tx_result.get('block_number'),
                        gas_used=tx_result.get('gas_used'),
                        etherscan_url=tx_result.get('etherscan_url'),
                        item_details=item_details,
                        related_asset_id=related_asset_id
                    )
            else:
                logger.error(f"❌ Background tx failed for {reason}: {tx_result.get('error')}")
        except Exception as e:
            logger.error(f"❌ Background tx error for {reason}: {e}")

    threading.Thread(target=_send, daemon=True).start()

def record_purchase(user_id, wallet_address, purchase_type, amount_eth, tx_result, 
                   item_details=None, related_asset_id=None) -> int:
    """Record purchase in database"""
    return create_depot_transaction(
        user_id=user_id or 5,
        wallet_address=wallet_address,
        purchase_type=purchase_type,
        amount_eth=amount_eth,
        tx_hash=tx_result['tx_hash'],
        block_number=tx_result.get('block_number'),
        block_timestamp=None,
        gas_used=tx_result.get('gas_used'),
        tx_fee_eth=None,
        etherscan_url=tx_result['etherscan_url'],
        item_details=item_details,
        related_asset_id=related_asset_id
    )

##############################################################################
# SHARD INFUSION (formerly Stat Reroll)
##############################################################################

def calculate_infusion_chance(current_stat: int) -> float:
    """
    Calculate probability of +1 improvement based on current stat value.
    Higher stats = harder to improve. Stats at 90+ cannot improve.

    Sliding scale:
    - 0-50:  40% chance
    - 51-70: 25% chance
    - 71-85: 10% chance
    - 86-89: 3% chance
    - 90+:   0% (hard cap)
    """
    if current_stat >= 90:
        return 0.0
    elif current_stat >= 86:
        return 0.03
    elif current_stat >= 71:
        return 0.10
    elif current_stat >= 51:
        return 0.25
    else:
        return 0.40


def apply_shard_infusion(current_stats: dict) -> tuple[dict, dict]:
    """
    Apply shard infusion to stats. Each stat has a chance to gain +1 based on
    its current value. Stats can NEVER decrease - worst case is no change.

    Returns:
        tuple of (new_stats dict, changes dict showing which stats improved)
    """
    import random
    from config import STAT_NAMES

    new_stats = {}
    changes = {}

    for stat in STAT_NAMES:
        current_value = current_stats.get(stat, 50)
        chance = calculate_infusion_chance(current_value)

        if random.random() < chance:
            # Success! +1 to this stat (capped at 89 to leave room for natural 90s)
            new_value = min(current_value + 1, 89)
            new_stats[stat] = new_value
            if new_value > current_value:
                changes[stat] = {'old': current_value, 'new': new_value, 'gained': 1}
            else:
                new_stats[stat] = current_value  # Was already at cap
        else:
            # No change - stat stays exactly the same
            new_stats[stat] = current_value

    return new_stats, changes


def purchase_stat_reroll(session) -> dict:
    """
    Process Shard Infusion purchase.

    SHARD INFUSION MECHANICS:
    - Stats can ONLY go up or stay the same - NEVER down
    - Each stat has independent chance to gain +1
    - Chance decreases as stat approaches 90 (diminishing returns)
    - Cost doubles with each infusion (500, 1000, 2000, 4000...)
    - Hard cap at 89 via infusion (natural 90s stay special)

    The shards gamble: you always pay, but might not improve.
    """
    from utilities.postgres_utils import (
        get_user_escalation_counts, increment_reroll_count, calculate_reroll_cost,
        get_commander_stats, update_asset_stats, db_cursor
    )

    user_id = session.get('user_id')
    wallet, current_balance_eth = get_user_wallet_and_balance(session)

    # Calculate escalating cost based on previous infusions
    if user_id:
        counts = get_user_escalation_counts(user_id)
        total_infusions = counts.get('total_rerolls', 0)
    else:
        # For anonymous users (during onboarding), use session count
        total_infusions = session.get('onboarding_rerolls', 0)

    infusion_cost_display = calculate_reroll_cost(total_infusions)
    infusion_cost_eth = display_to_eth(infusion_cost_display)

    sufficient, error_msg = check_sufficient_balance(current_balance_eth, infusion_cost_eth)
    if not sufficient:
        raise Exception(f"Need {infusion_cost_display:,} shards for infusion #{total_infusions + 1}")

    # Get current stats before infusion
    if user_id:
        current_stats = get_commander_stats(user_id)
        if not current_stats:
            # Fallback if no stats found - use session or generate
            current_stats = session.get('commander_stats') or generate_commander_stats()
    else:
        current_stats = session.get('commander_stats') or generate_commander_stats()

    # Apply shard infusion first (before purchase - game logic is instant)
    new_stats, changes = apply_shard_infusion(current_stats)
    session['commander_stats'] = new_stats
    total_gained = sum(c['gained'] for c in changes.values())

    # Deduct balance immediately, blockchain tx fires in background
    new_balance_eth = execute_purchase_transaction(
        wallet, infusion_cost_eth, f"INFUSE:{total_infusions + 1}",
        user_id=user_id, purchase_type='shard_infusion',
        item_details={
            'old_stats': current_stats, 'new_stats': new_stats,
            'changes': changes, 'total_gained': total_gained,
            'infusion_number': total_infusions + 1
        }
    )

    # Update database for authenticated users
    if user_id:
        increment_reroll_count(user_id)

        # Update the primary commander's stats in the database
        try:
            with db_cursor(commit=True) as cur:
                cur.execute("""
                    UPDATE pilgrim.replicate_assets
                    SET commander_leadership = %s, commander_strategy = %s,
                        commander_exploration = %s, commander_logistics = %s,
                        commander_charisma = %s, updated_at = NOW()
                    WHERE user_id = %s
                    AND asset_type IN ('character_image', 'edited_image')
                    AND is_primary_character = true AND is_deleted = false
                """, (new_stats['leadership'], new_stats['strategy'], new_stats['exploration'],
                      new_stats['logistics'], new_stats['charisma'], user_id))
        except Exception as e:
            logger.error(f"Failed to update commander stats in DB: {e}")
    else:
        # For anonymous users, track reroll count in session
        session['onboarding_rerolls'] = total_infusions + 1
        # Legacy: update _wal if present (new format doesn't store transaction data)
        if '_wal' in session:
            session['_wal']['transaction']['amount'] = eth_to_display(new_balance_eth)
        session.modified = True

    stats_improved = list(changes.keys())

    # Update session cached balance
    update_session_balance(session, eth_to_display(new_balance_eth))

    # Calculate next infusion cost for UI
    next_cost = calculate_reroll_cost(total_infusions + 1)

    # Build result message
    if total_gained > 0:
        improved_list = ', '.join([f"{s.title()} +1" for s in stats_improved])
        result_message = f"The shards resonate! {improved_list}"
    else:
        result_message = "The shards pulse but find no room to grow. Your potential remains intact."

    logger.info(f"✅ Shard Infusion #{total_infusions + 1}: {total_gained} points gained, cost {infusion_cost_display} shards")

    return {
        'success': True,
        'stats': new_stats,
        'old_stats': current_stats,
        'changes': changes,
        'total_gained': total_gained,
        'stats_improved': stats_improved,
        'result_message': result_message,
        'new_balance': eth_to_display(new_balance_eth),
        'infusion_number': total_infusions + 1,
        'next_infusion_cost': next_cost,
        # Keep old field names for backwards compatibility
        'reroll_number': total_infusions + 1,
        'next_reroll_cost': next_cost
    }

##############################################################################
# CHARACTER MODIFICATION
##############################################################################

def purchase_character_modification(session, edit_prompt: str, flux_generator) -> dict:
    """
    Process character modification purchase
    ALWAYS modifies the LATEST image (edited or original)
    """
    from utilities.flux_utils import edit_character_image

    if not edit_prompt or not edit_prompt.strip():
        raise Exception('No modification description provided')
    
    is_allowed, filter_message = check_content_filter(edit_prompt)
    if not is_allowed:
        raise Exception(filter_message)
    
    user_id = session.get('user_id')
    wallet, current_balance_eth = get_user_wallet_and_balance(session)
    
    sufficient, error_msg = check_sufficient_balance(current_balance_eth, CHARACTER_MODIFY_COST_ETH)
    if not sufficient:
        raise Exception(error_msg)
    
    # Deduct balance immediately, blockchain tx fires in background
    new_balance_eth = execute_purchase_transaction(
        wallet, CHARACTER_MODIFY_COST_ETH, f"Character modification: {edit_prompt[:50]}",
        user_id=user_id, purchase_type='character_modification',
        item_details={'prompt': edit_prompt}
    )

    # Get the LATEST image to modify
    last_image_url = None
    parent_asset_id = None

    if user_id:
        last_image_url, parent_asset_id = get_latest_character_image(user_id)
    else:
        last_image_url = session.get('selected_character_url') or session.get('last_image_url')
        parent_asset_id = session.get('current_asset_id')

    if not last_image_url:
        raise Exception('No character image found')

    logger.info(f"🎨 Modifying: {last_image_url[:50]}...")
    logger.info(f"📝 Prompt: {edit_prompt}")

    result_url = edit_character_image(last_image_url, edit_prompt, flux_generator)
    update_character_session(session, result_url)

    new_asset_id = session.get('current_asset_id')

    if user_id:
        # Make the new edited image the active commander
        if new_asset_id:
            from utilities.postgres_utils import set_primary_commander
            set_primary_commander(user_id, new_asset_id)

    commander_stats = None
    if user_id:
        from utilities.postgres_utils import get_commander_stats
        commander_stats = get_commander_stats(user_id)
    else:
        commander_stats = session.get('commander_stats')

    # Update session cached balance
    update_session_balance(session, eth_to_display(new_balance_eth))

    logger.info(f"✅ Character modification complete")

    return {
        'success': True,
        'image_url': result_url,
        'new_balance': eth_to_display(new_balance_eth),
        'prompt': edit_prompt,
        'stats': commander_stats
    }

##############################################################################
# VIDEO GENERATION
##############################################################################

def purchase_video_generation(session, flux_generator) -> dict:
    """
    Process video generation purchase
    ALWAYS uses the LATEST image
    """
    user_id = session.get('user_id')
    wallet, current_balance_eth = get_user_wallet_and_balance(session)
    
    sufficient, error_msg = check_sufficient_balance(current_balance_eth, VIDEO_GENERATION_COST_ETH)
    if not sufficient:
        raise Exception(error_msg)
    
    # Get LATEST image to generate video from
    character_url, character_asset_id = get_latest_character_image(user_id)
    
    logger.info(f"🎬 Generating video from: {character_url[:50]}... (asset {character_asset_id})")
    
    # Deduct balance immediately, blockchain tx fires in background
    new_balance_eth = execute_purchase_transaction(
        wallet, VIDEO_GENERATION_COST_ETH,
        f"Video generation for commander (asset {character_asset_id})",
        user_id=user_id, purchase_type='video_generation',
        item_details={'character_asset_id': character_asset_id},
        related_asset_id=character_asset_id
    )

    # Update session cached balance
    update_session_balance(session, eth_to_display(new_balance_eth))

    logger.info(f"✅ Video generation purchased")

    return {
        'success': True,
        'new_balance': eth_to_display(new_balance_eth),
        'character_url': character_url,
        'character_asset_id': character_asset_id
    }

def calculate_cached_transaction_cost(base_cost_eth: float, user_balance_eth: float = None, message_length: int = 250) -> dict:
    """
    Calculate transaction cost using cached/default gas values (NO blockchain call).

    SPEED OPTIMIZATION: Sepolia gas prices are consistently low (0-2 gwei).
    Using defaults eliminates ~400ms blockchain call per pricing calculation.
    Actual transaction will use live gas at execution time.
    """
    base_cost_eth = float(base_cost_eth)

    # Use sensible defaults for Sepolia testnet
    gas_gwei = DEFAULT_GAS_GWEI
    total_gas = 21000 + (message_length * 68) if message_length > 0 else 21000
    gas_cost_eth = (total_gas * gas_gwei * 1e9) / 1e18

    # Atmospheric fee based on gas (but Sepolia is always low = optimal)
    fee_multiplier = DEFAULT_FEE_MULTIPLIER
    atmospheric_fee_eth = base_cost_eth * (fee_multiplier - 1.0)

    total_cost_eth = base_cost_eth + atmospheric_fee_eth + gas_cost_eth

    # Determine affordability if balance provided
    can_afford = True
    current_balance = user_balance_eth if user_balance_eth is not None else 0.0
    if user_balance_eth is not None:
        can_afford = current_balance >= total_cost_eth

    return {
        'success': True,
        'base_cost_eth': base_cost_eth,
        'base_cost_display': base_cost_eth * 10000000,
        'atmospheric_fee_eth': atmospheric_fee_eth,
        'atmospheric_fee_display': atmospheric_fee_eth * 10000000,
        'gas_cost_eth': gas_cost_eth,
        'gas_cost_display': gas_cost_eth * 10000000,
        'total_cost_eth': total_cost_eth,
        'total_cost_display': total_cost_eth * 10000000,
        'conditions': {
            'gas_gwei': gas_gwei,
            'solar_angle': 45.0,
            'efficiency': 98,
            'condition': 'Optimal',
            'fee_multiplier': fee_multiplier,
            'base_gas_cost_eth': (21000 * gas_gwei * 1e9) / 1e18
        },
        'estimated_gas_units': total_gas,
        'gas_price_gwei': gas_gwei,
        'can_afford': can_afford,
        'current_balance_eth': current_balance,
        'current_balance_display': current_balance * 10000000,
        'shortfall_eth': max(0, total_cost_eth - current_balance) if user_balance_eth is not None else 0,
        'shortfall_display': max(0, (total_cost_eth - current_balance) * 10000000) if user_balance_eth is not None else 0
    }


def get_mars_conditions():
    """
    Get current Mars atmospheric conditions and pricing for all purchase types.

    SPEED OPTIMIZATION: Uses cached gas pricing instead of blockchain call.
    """
    def format_pricing(pricing):
        return {k: pricing[k] for k in ['base_cost_display', 'atmospheric_fee_display', 'gas_cost_display', 'total_cost_display', 'total_cost_eth']}

    reroll = calculate_cached_transaction_cost(float(STAT_REROLL_COST_ETH))
    modify = calculate_cached_transaction_cost(float(CHARACTER_MODIFY_COST_ETH))
    video = calculate_cached_transaction_cost(float(VIDEO_GENERATION_COST_ETH))

    return {
        'success': True, 'conditions': reroll['conditions'],
        'pricing': {'reroll': format_pricing(reroll), 'modify': format_pricing(modify), 'video': format_pricing(video)}
    }

def check_sepolia_balance(session):
    """Check current Sepolia balance for user.

    PERFORMANCE: Returns session-cached balance to avoid blockchain calls.
    This endpoint is deprecated - balance is now injected via context_processor.
    Kept for backwards compatibility with cached JS.
    """
    user_id = session.get('user_id')

    # Return session-cached balance if available (no blockchain call needed)
    if '_bal' in session:
        return {'success': True, 'has_wallet': True, 'balance': session['_bal'], 'cached': True}

    wallet = None
    if user_id:
        wallet = get_user_primary_sepolia_wallet(user_id)
    else:
        # Check new slim format first
        session_wallet_addr = session.get('_wal_addr')
        if session_wallet_addr:
            wallet = {'wallet_address': session_wallet_addr}
        else:
            # Legacy format fallback
            session_wallet = session.get('_wal')
            if session_wallet and 'wallet' in session_wallet:
                wallet = {'wallet_address': session_wallet['wallet']['address']}

    if not wallet:
        return {'success': True, 'has_wallet': False, 'balance': 0.0}

    # Only hit blockchain if no cached balance exists
    miner = MarsAsteroidMiner()
    balance = miner.get_live_wallet_balance(wallet['wallet_address'], fallback_balance=0.0)
    display_balance = eth_to_display(balance)

    # Cache for future calls this session
    session['_bal'] = display_balance
    session.modified = True

    return {'success': True, 'has_wallet': True, 'balance': display_balance, 'wallet_address': wallet['wallet_address']}


def start_video_generation(session, flux, app_config, animate_fn):
    """
    Start background video generation for shop purchase.
    Returns result dict with status_key for polling.
    """
    from threading import Thread

    result = purchase_video_generation(session, flux)
    if not result['success']:
        return result

    character_url = result['character_url']
    character_asset_id = result['character_asset_id']
    user_id = session.get('user_id')

    status_key = f'video_gen_{character_asset_id}'
    app_config[status_key] = {
        'generating': True, 'url': None,
        'character_url': character_url, 'asset_id': character_asset_id
    }

    def generate_video():
        try:
            logger.info(f"🎬 Starting background video generation for asset {character_asset_id}")
            video_url = animate_fn(character_url, flux, user_id=user_id, asset_id=character_asset_id)
            app_config[status_key].update({'url': video_url, 'generating': False})
            logger.info(f"🎬 ✅ Video generation complete: {video_url}")
        except Exception as e:
            logger.error(f"🎬 ❌ Video generation failed: {e}")
            app_config[status_key].update({'url': None, 'generating': False, 'error': str(e)})

    Thread(target=generate_video, daemon=True).start()
    return {**result, 'status_key': status_key}


def start_deploy_video_generation(session, app_config, flux, animate_fn, logger):
    """
    Start video generation for deployment step.
    Returns result dict for JSON response.
    """
    from threading import Thread

    if not flux:
        return {'success': False, 'error': 'Service not available'}

    character_url = session.get('selected_character_url') or session.get('last_image_url')
    if not character_url:
        return {'success': False, 'error': 'No character selected'}

    session.update({'selected_character_url': character_url, 'video_generating': True, 'character_video_url': None})
    asset_id = session.get('current_asset_id')
    user_id = session.get('user_id')
    app_config['video_status'] = {'generating': True, 'url': None, 'character_url': character_url}

    def generate_video():
        try:
            video_url = animate_fn(character_url, flux, user_id=user_id, asset_id=asset_id)
            app_config['video_status'].update({'url': video_url, 'generating': False})
        except Exception as e:
            logger.error(f"Video generation failed: {e}")
            app_config['video_status'].update({'url': None, 'generating': False})

    Thread(target=generate_video, daemon=True).start()
    return {'success': True}


# ============================================================================
# RE-EXPORTS: Functions moved to onboarding_utils.py and page_data_utils.py
# Existing `from utilities.depot_utils import X` statements keep working.
# ============================================================================

from utilities.onboarding_utils import (  # noqa: F401
    safe_float, format_wallet_info, format_transaction_info,
    handle_existing_wallet, process_asteroid_impact,
    has_completed_mining, get_current_balance_and_wallet,
    generate_commander_stats, extract_commander_stats, extract_leader_name,
    discover_default_leaders, get_default_leader_urls, get_all_default_leaders,
    select_default_leader,
    initialize_character_session, update_character_session,
    clear_character_session, has_created_character,
    get_arrival_mining_data, get_arrival_commander_data, get_arrival_deploy_data,
    ensure_user_onboarded, handle_auth_callback,
    handle_leader_selection, get_mars_location_data, handle_custom_commander_upload,
)

from utilities.page_data_utils import (  # noqa: F401
    get_command_page_data, build_recent_activity,
    get_while_you_were_away_summary, get_dashboard_page_data,
    get_profile_page_data, get_colony_page_data, get_depot_page_data,
    get_claimed_discoveries_data, get_formatted_discovery_items,
)
