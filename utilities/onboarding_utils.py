"""Captain creation, arrival flow, leader selection, and onboarding utilities."""

import logging
import random
import json
import os
from typing import Dict, Any, Optional, List
from flask import session

logger = logging.getLogger(__name__)


##############################################################################
# MINING & WALLET OPERATIONS
##############################################################################

def safe_float(value):
    """Safely convert Decimal/numeric values to float for JSON"""
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None

def format_wallet_info(wallet_data):
    """Format wallet data for API response - NEVER include private_key (security risk)"""
    return {
        'name': wallet_data['wallet_name'],
        'address': wallet_data['wallet_address'],
        'short_address': f"{wallet_data['wallet_address'][:10]}...{wallet_data['wallet_address'][-4:]}",
        # SECURITY: private_key is NEVER returned to browser - lookup from DB when needed for transactions
        'etherscan_url': wallet_data.get('etherscan_wallet_url') or
                        f"https://sepolia.etherscan.io/address/{wallet_data['wallet_address']}"
    }

def format_transaction_info(wallet_data, current_balance):
    """Format existing transaction data for API response"""
    from utilities.depot_utils import eth_to_display
    return {
        'hash': wallet_data.get('mining_tx_hash') or 'Previously Mined',
        'amount': eth_to_display(wallet_data['initial_balance_eth']),
        'tx_url': wallet_data.get('etherscan_tx_url') or
                 f"https://sepolia.etherscan.io/address/{wallet_data['wallet_address']}",
        'recipient_balance_after': eth_to_display(current_balance),
        'message': wallet_data.get('custom_message') or 'Welcome back! Your resource cache is ready.',
        'block_number': wallet_data.get('mining_block_number'),
        'block_hash': wallet_data.get('mining_block_hash'),
        'tx_index': wallet_data.get('mining_tx_index'),
        'gas_limit': wallet_data.get('mining_gas_limit'),
        'gas_used': wallet_data.get('mining_gas_used'),
        'gas_price_gwei': safe_float(wallet_data.get('mining_gas_price_gwei')),
        'tx_fee_eth': safe_float(wallet_data.get('mining_tx_fee_eth')),
        'max_fee_gwei': safe_float(wallet_data.get('mining_max_fee_gwei')),
        'max_priority_gwei': safe_float(wallet_data.get('mining_max_priority_gwei')),
        'base_fee_gwei': safe_float(wallet_data.get('mining_base_fee_gwei')),
        'from_address': wallet_data.get('mining_from_address'),
        'nonce': wallet_data.get('mining_nonce'),
        'confirmations': wallet_data.get('mining_confirmations') or 'Confirmed'
    }

def handle_existing_wallet(wallet_data, miner=None):
    """Process existing wallet and return formatted response"""
    from utilities.sepolia_utils import MarsAsteroidMiner
    from utilities.postgres.wallets import update_sepolia_wallet_balance

    current_balance = safe_float(wallet_data['current_balance_eth']) or 0.0

    if miner is None:
        miner = MarsAsteroidMiner()

    if miner.connect():
        try:
            current_balance = miner.check_cache_balance(wallet_data['wallet_address'])
            update_sepolia_wallet_balance(wallet_data['wallet_address'], current_balance)
        except Exception as e:
            logger.warning(f"Could not check live balance: {e}")

    return {
        'success': True,
        'wallet': format_wallet_info(wallet_data),
        'transaction': format_transaction_info(wallet_data, current_balance),
        'from_database': True, 'is_returning_user': True
    }

def process_asteroid_impact(session):
    """Assign a pre-mined wallet from the pool. Claims for authenticated users.

    For anonymous users, uses the preview_cache_address if available (so they get
    the same wallet they saw on the home page), otherwise gets a random one.
    """
    from utilities.postgres.wallets import (
        get_random_unclaimed_cache,
        claim_anonymous_wallet,
        get_wallet_by_address,
        get_user_primary_sepolia_wallet,
    )

    user_id = session.get('user_id')
    is_anonymous = not user_id

    if user_id:
        existing_wallet = get_user_primary_sepolia_wallet(user_id)
        if existing_wallet:
            result = handle_existing_wallet(existing_wallet, None)
            # Don't store _wal in session for logged-in users - wallet is in DB
            # Clear any stale session wallet data to reduce cookie size
            session.pop('_wal', None)
            session.modified = True
            return result

    # For anonymous users, check if we have a cached wallet address
    session_wallet_addr = session.get('_wal_addr')
    if session_wallet_addr:
        # Look up full wallet from DB (don't store private key in cookie)
        wallet_data = get_wallet_by_address(session_wallet_addr)
        if wallet_data:
            wallet_info = format_wallet_info(wallet_data)
            transaction_info = format_transaction_info(wallet_data, wallet_data['current_balance_eth'])
            return {'success': True, 'wallet': wallet_info, 'transaction': transaction_info,
                    'from_session': True, 'is_anonymous': is_anonymous}

    # Legacy: check old _wal format and migrate to new format
    session_wallet = session.get('_wal')
    if session_wallet and 'wallet' in session_wallet:
        # Migrate to slim format (just address)
        session['_wal_addr'] = session_wallet['wallet']['address']
        session.pop('_wal', None)
        session.modified = True
        return {'success': True, 'wallet': session_wallet['wallet'], 'transaction': session_wallet['transaction'],
                'from_session': True, 'is_anonymous': is_anonymous}

    # For anonymous users, try to use the preview cache they saw on home page
    wallet_data = None
    preview_address = session.get('preview_cache_address')
    if preview_address:
        wallet_data = get_wallet_by_address(preview_address)
        # Only use if it's still in the anonymous pool and unassigned
        if wallet_data and (wallet_data.get('user_id') != 5 or wallet_data.get('is_assigned')):
            wallet_data = None  # Already claimed by someone else, get a fresh one

    if not wallet_data:
        wallet_data = get_random_unclaimed_cache()

    if not wallet_data:
        return {'success': False, 'error': 'No wallets available in pool'}

    if user_id:
        if not claim_anonymous_wallet(wallet_data['wallet_address'], user_id):
            return {'success': False, 'error': 'Failed to claim wallet'}

    wallet_info = format_wallet_info(wallet_data)
    transaction_info = format_transaction_info(wallet_data, wallet_data['current_balance_eth'])
    # Store only address in session (not full wallet with private key) to reduce cookie size
    session['_wal_addr'] = wallet_data['wallet_address']
    session.pop('_wal', None)  # Clear any legacy format
    session.modified = True

    return {'success': True, 'wallet': wallet_info, 'transaction': transaction_info,
            'is_anonymous': is_anonymous, 'from_pool': True, 'claimed': bool(user_id)}

def has_completed_mining(session):
    """Check if user has mined Sepolia (has wallet in session OR database)"""
    from utilities.postgres.wallets import get_user_primary_sepolia_wallet

    if session.get('_wal_addr') or session.get('_wal'):  # Check both new and legacy format
        return True
    user_id = session.get('user_id')
    return bool(user_id and get_user_primary_sepolia_wallet(user_id))

def get_current_balance_and_wallet(session):
    """Get current balance and wallet info. Returns: (has_wallet, current_balance_display, wallet_info)"""
    from utilities.depot_utils import eth_to_display
    from utilities.postgres.wallets import get_user_primary_sepolia_wallet, get_wallet_by_address

    user_id = session.get('user_id')

    if user_id:
        wallet = get_user_primary_sepolia_wallet(user_id)
        if wallet:
            return True, eth_to_display(wallet.get('current_balance_eth', 0)), {
                'address': wallet['wallet_address'], 'etherscan_url': wallet.get('etherscan_wallet_url')
            }

    # Check new slim format first
    session_wallet_addr = session.get('_wal_addr')
    if session_wallet_addr:
        cached_wallet = get_wallet_by_address(session_wallet_addr)
        if cached_wallet:
            balance = float(cached_wallet.get('current_balance_eth', 0))
            return True, eth_to_display(balance), {
                'address': cached_wallet['wallet_address'],
                'etherscan_url': cached_wallet.get('etherscan_wallet_url')
            }

    # Legacy format fallback
    session_wallet = session.get('_wal')
    if session_wallet and 'wallet' in session_wallet:
        address = session_wallet['wallet']['address']
        cached_wallet = get_wallet_by_address(address)
        balance = float(cached_wallet.get('current_balance_eth', 0)) if cached_wallet else 0.0
        return True, eth_to_display(balance), session_wallet.get('wallet')

    return False, 0.0, None


##############################################################################
# CAPTAIN & LEADER FUNCTIONS
##############################################################################

def generate_commander_stats():
    """Generate random stats for a captain"""
    from config import STAT_NAMES, MIN_STAT_VALUE, MAX_STAT_VALUE
    return {stat: random.randint(MIN_STAT_VALUE, MAX_STAT_VALUE) for stat in STAT_NAMES}

def extract_commander_stats(commander, default_value=33):
    """Extract captain stats from asset record with fallback"""
    from config import STAT_NAMES
    if not commander:
        return {stat: default_value for stat in STAT_NAMES}

    stats = {
        'leadership': commander.get('commander_leadership'),
        'strategy': commander.get('commander_strategy'),
        'exploration': commander.get('commander_exploration'),
        'logistics': commander.get('commander_logistics'),
        'charisma': commander.get('commander_charisma')
    }
    if any(v is None for v in stats.values()):
        return {stat: default_value for stat in STAT_NAMES}
    return stats

def extract_leader_name(leader_id):
    """Extract human-readable name from leader_id like 'leader1_andy' -> 'Andy'"""
    if '_' in leader_id:
        return leader_id.split('_', 1)[1].replace('_', ' ').title()
    return leader_id.replace('_', ' ').title()

def discover_default_leaders():
    """Auto-discover default leaders from GCS bucket. Returns dict of leader_id -> {has_image, has_video}"""
    from google.cloud import storage
    from config import BUCKET_NAME, DEFAULT_LEADERS_GCS_BASE

    try:
        client = storage.Client()
        bucket = client.bucket(BUCKET_NAME)

        images, videos = set(), set()
        for blob in bucket.list_blobs(prefix=f"{DEFAULT_LEADERS_GCS_BASE}/images/"):
            if blob.name.endswith('.png'):
                images.add(blob.name.split('/')[-1].replace('.png', ''))
        for blob in bucket.list_blobs(prefix=f"{DEFAULT_LEADERS_GCS_BASE}/videos/"):
            if blob.name.endswith('.mp4'):
                videos.add(blob.name.split('/')[-1].replace('.mp4', ''))

        complete = images & videos
        return {lid: {'has_image': True, 'has_video': True} for lid in complete}
    except Exception as e:
        logger.error(f"Failed to discover default leaders from GCS: {e}")
        return {}

def get_default_leader_urls(leader_id, use_static=False):
    """Get URLs for a default leader.

    Args:
        leader_id: The leader ID (e.g., 'leader1_andy')
        use_static: If True, return static paths for local serving (anonymous users).
                   If False, return GCS URLs (authenticated users for permanent storage).
    """
    from config import BUCKET_NAME, DEFAULT_LEADERS_GCS_BASE

    if use_static:
        # Use local static paths (for anonymous onboarding flow)
        return {
            'image_url': f"/static/images/default_leaders/{leader_id}.png",
            'video_url': f"/static/videos/default_leaders/{leader_id}.mp4",
            'image_blob': None,
            'video_blob': None
        }

    # Use GCS URLs (for authenticated users / permanent storage)
    base = f"https://storage.googleapis.com/{BUCKET_NAME}/{DEFAULT_LEADERS_GCS_BASE}"
    return {
        'image_url': f"{base}/images/{leader_id}.png",
        'video_url': f"{base}/videos/{leader_id}.mp4",
        'image_blob': f"{DEFAULT_LEADERS_GCS_BASE}/images/{leader_id}.png",
        'video_blob': f"{DEFAULT_LEADERS_GCS_BASE}/videos/{leader_id}.mp4"
    }

def get_all_default_leaders(use_static=True):
    """Get all available default leaders for selection carousel.

    Args:
        use_static: Use static paths (for anonymous/onboarding). Default True.
    """
    leaders = []
    for leader_id in discover_default_leaders().keys():
        urls = get_default_leader_urls(leader_id, use_static=use_static)
        leaders.append({
            'id': leader_id, 'image_url': urls['image_url'], 'video_url': urls['video_url'],
            'stats': generate_commander_stats(), 'name': extract_leader_name(leader_id)
        })
    return leaders

def select_default_leader(user_id, leader_id=None):
    """Select and create assets for a default leader (random or specific).

    Creates database assets for both anonymous (user_id=5) and authenticated users.
    Anonymous users' assets are claimed when they log in via handle_auth_callback.
    """
    from utilities.postgres.assets import create_replicate_asset

    available = discover_default_leaders()
    if not available:
        return {'success': False, 'error': 'No default leaders available'}

    if leader_id is None:
        leader_id = random.choice(list(available.keys()))

    # Always use GCS URLs for database storage
    urls = get_default_leader_urls(leader_id, use_static=False)
    stats = generate_commander_stats()
    leader_name = extract_leader_name(leader_id)

    # Use anonymous user_id=5 for unauthenticated users so assets can be claimed on login
    db_user_id = user_id if user_id is not None else 5

    image_asset_id = create_replicate_asset(
        user_id=db_user_id, asset_type='character_image', replicate_url=None,
        gcs_url=urls['image_url'], gcs_blob_name=urls['image_blob'],
        is_original=True, replicate_model='default-leader', content_type='image/png',
        commander_name=leader_name, commander_stats=stats
    )
    video_asset_id = create_replicate_asset(
        user_id=db_user_id, asset_type='character_video', replicate_url=None,
        gcs_url=urls['video_url'], gcs_blob_name=urls['video_blob'],
        parent_asset_id=image_asset_id, replicate_model='default-leader', content_type='video/mp4',
        commander_name=leader_name
    )

    # For display in UI, use static paths for anonymous users (faster loading)
    display_urls = get_default_leader_urls(leader_id, use_static=(user_id is None))

    other_leaders = [{'id': lid, 'image_url': get_default_leader_urls(lid, use_static=(user_id is None))['image_url'],
                      'video_url': get_default_leader_urls(lid, use_static=(user_id is None))['video_url'],
                      'name': extract_leader_name(lid)}
                     for lid in available.keys() if lid != leader_id]

    return {
        'success': True, 'image_url': display_urls['image_url'], 'video_url': display_urls['video_url'],
        'stats': stats, 'leader_id': leader_id, 'commander_name': leader_name,
        'image_asset_id': image_asset_id, 'video_asset_id': video_asset_id, 'other_leaders': other_leaders
    }


##############################################################################
# SESSION MANAGEMENT
##############################################################################

def initialize_character_session(session, image_url, stats):
    """Initialize session with new character data"""
    session.update({
        'last_image_url': image_url, 'original_image_url': image_url,
        'selected_character_url': image_url, 'image_history': [image_url], 'commander_stats': stats
    })

def update_character_session(session, new_image_url):
    """Update session with edited character image"""
    history = session.get('image_history', [])
    history.append(new_image_url)
    session.update({'last_image_url': new_image_url, 'selected_character_url': new_image_url, 'image_history': history})

def clear_character_session(session):
    """Clear all character-related and onboarding session data"""
    for key in ['last_image_url', 'original_image_url', 'selected_character_url', 'image_history',
                'commander_stats', 'character_video_url', 'campaign_ready', '_wal', '_wal_addr',
                'current_asset_id', 'edit_count', 'commander_name', 'onboarding_rerolls',
                'preview_cache_address', 'preview_balance_fallback', 'preview_scientist_key']:
        session.pop(key, None)

def has_created_character(session):
    """Check if user has created a character"""
    return session.get('last_image_url') is not None


##############################################################################
# ARRIVAL PAGE HELPERS
##############################################################################

def get_arrival_mining_data(session, user_id=None):
    """Get all data needed for home page (anonymous users).

    For the simplified onboarding flow:
    - Always show a preview balance from a random unclaimed cache
    - Store the cache in session so they get the same one when selecting captain
    """
    from utilities.postgres.wallets import get_user_sepolia_wallets, get_random_unclaimed_cache
    from utilities.depot_utils import eth_to_display, get_fast_balance_and_wallet_info

    if user_id:
        if get_user_sepolia_wallets(user_id):
            return {'redirect': 'arrival_commander'}
        current_balance, wallet_info, _ = get_fast_balance_and_wallet_info(user_id)  # FAST
        has_wallet = wallet_info is not None
        preview_balance = current_balance
    else:
        has_wallet = has_completed_mining(session)
        current_balance, wallet_info = 0, None
        preview_balance = 0

        if has_wallet:
            _, current_balance, wallet_info = get_current_balance_and_wallet(session)
            preview_balance = current_balance
        else:
            # Get/reuse a preview cache for anonymous users
            # FAST: Use DB-cached balance, never hit blockchain for preview
            if session.get('preview_cache_address'):
                # Get cached balance from DB (fast!)
                from utilities.postgres.wallets import get_wallet_by_address
                cached_wallet = get_wallet_by_address(session['preview_cache_address'])
                if cached_wallet:
                    cache_balance = cached_wallet.get('current_balance_eth') or cached_wallet.get('initial_balance_eth')
                    if cache_balance:
                        preview_balance = eth_to_display(float(cache_balance))

            # If still 0, get a fresh random cache
            if preview_balance == 0:
                preview_cache = get_random_unclaimed_cache()
                if preview_cache:
                    # Column is current_balance_eth, not balance_eth
                    cache_balance = preview_cache.get('current_balance_eth') or preview_cache.get('initial_balance_eth')
                    if cache_balance:
                        preview_balance = eth_to_display(float(cache_balance))
                    # Store for consistency across page loads
                    session['preview_cache_address'] = preview_cache.get('wallet_address')

            # FALLBACK: If still 0 (no caches available), show a default preview amount
            # This ensures new users always see some shards to start with
            if preview_balance == 0:
                preview_balance = round(random.uniform(8.0, 25.0), 1)
                session['preview_balance_fallback'] = preview_balance  # Store for consistency

    return {'has_wallet': has_wallet, 'current_balance': current_balance, 'wallet_info': wallet_info,
            'auto_mine': False, 'preview_balance': preview_balance}

def get_arrival_commander_data(session, user_id=None):
    """Get all data needed for crew page (anonymous users select captain).

    For the simplified onboarding flow:
    - No wallet required to view captains
    - Cache will be auto-claimed when they select a captain
    - Anonymous users get a random scientist assigned (stored in session)
    """
    from utilities.postgres.wallets import get_user_sepolia_wallets
    from utilities.postgres.assets import get_user_replicate_assets
    from utilities.depot_utils import eth_to_display
    from config import get_random_scientist

    if user_id:
        if not get_user_sepolia_wallets(user_id):
            return {'redirect': 'arrival_mining'}
        if get_user_replicate_assets(user_id, asset_type='character_image', limit=1):
            return {'redirect': 'arrival_deploy'}
        has_character, character_url, stats = False, None, None
    else:
        # Anonymous users can always view captains - no wallet check!
        # The cache will be auto-claimed when they select a captain
        has_character = has_created_character(session)
        character_url, stats = session.get('last_image_url'), session.get('commander_stats')

    # Get preview balance for anonymous users (carried from home page or set here)
    # FAST: Always use DB-cached balance, never hit blockchain
    preview_balance = 0
    if not user_id:
        # Check for fallback first (set by home page if no caches available)
        if session.get('preview_balance_fallback'):
            preview_balance = session['preview_balance_fallback']
        elif session.get('preview_cache_address'):
            # FAST: Get balance from DB cache (not blockchain!)
            from utilities.postgres.wallets import get_wallet_by_address
            cached_wallet = get_wallet_by_address(session['preview_cache_address'])
            if cached_wallet:
                cache_balance = cached_wallet.get('current_balance_eth') or cached_wallet.get('initial_balance_eth')
                if cache_balance:
                    preview_balance = eth_to_display(float(cache_balance))

        # If still 0, get a fresh random cache (user may have come directly to /crew)
        if preview_balance == 0:
            from utilities.postgres.wallets import get_random_unclaimed_cache
            preview_cache = get_random_unclaimed_cache()
            if preview_cache:
                cache_balance = preview_cache.get('current_balance_eth') or preview_cache.get('initial_balance_eth')
                if cache_balance:
                    preview_balance = eth_to_display(float(cache_balance))
                # Store for consistency across page loads
                session['preview_cache_address'] = preview_cache.get('wallet_address')

        # FALLBACK: If still 0, generate a preview amount
        if preview_balance == 0:
            preview_balance = round(random.uniform(8.0, 25.0), 1)
            session['preview_balance_fallback'] = preview_balance

    # Assign a random scientist for anonymous users (store just key to save session space)
    scientist = None
    if not user_id:
        from config import COLONY_SCIENTISTS
        scientist_key = session.get('preview_scientist_key')
        if not scientist_key:
            scientist_key = random.choice(list(COLONY_SCIENTISTS.keys()))
            session['preview_scientist_key'] = scientist_key
        scientist = {'key': scientist_key, **COLONY_SCIENTISTS[scientist_key]}

    return {
        'has_character': has_character, 'character_url': character_url, 'stats': stats,
        'image_history': session.get('image_history', []),
        'original_image_url': session.get('original_image_url'),
        'all_leaders': sorted(get_all_default_leaders(), key=lambda x: x['name']),
        'preview_balance': preview_balance,
        'scientist': scientist
    }

def get_arrival_deploy_data(session, user_id=None):
    """Get data for arrival/deploy page.

    For the simplified flow, anonymous users just need a captain selected.
    The cache is auto-claimed when they select a captain.
    Also assigns a scientist to the user at this point (the landing step).
    """
    from utilities.postgres.wallets import get_user_sepolia_wallets
    from utilities.postgres.assets import get_user_replicate_assets
    from utilities.postgres.users import get_user_scientist, assign_scientist_to_user
    from utilities.depot_utils import eth_to_display
    from config import get_random_scientist

    if user_id:
        if not get_user_sepolia_wallets(user_id):
            return {'redirect': 'arrival_mining'}
        if not get_user_replicate_assets(user_id, asset_type='character_image', limit=1):
            return {'redirect': 'arrival_commander'}
        if get_user_replicate_assets(user_id, asset_type='character_video', limit=1):
            return {'redirect': 'colony_dashboard'}
        has_wallet, has_character = True, True
    else:
        # Anonymous users just need a captain - cache is auto-claimed with captain
        has_character = has_created_character(session)
        has_wallet = has_completed_mining(session)
        if not has_character:
            return {'redirect': 'crew'}  # Go to crew page to select captain

    _, current_balance, wallet_info = get_current_balance_and_wallet(session)

    # For anonymous users, also get preview balance (same logic as crew page)
    # FAST: Always use DB-cached balance, never hit blockchain
    if not user_id and current_balance == 0:
        # Check for fallback first
        if session.get('preview_balance_fallback'):
            current_balance = session['preview_balance_fallback']
        elif session.get('preview_cache_address'):
            # FAST: Get balance from DB cache (not blockchain!)
            from utilities.postgres.wallets import get_wallet_by_address
            cached_wallet = get_wallet_by_address(session['preview_cache_address'])
            if cached_wallet:
                cache_balance = cached_wallet.get('current_balance_eth') or cached_wallet.get('initial_balance_eth')
                if cache_balance:
                    current_balance = eth_to_display(float(cache_balance))
        # If still 0, get a fresh random cache
        if current_balance == 0:
            from utilities.postgres.wallets import get_random_unclaimed_cache
            preview_cache = get_random_unclaimed_cache()
            if preview_cache:
                cache_balance = preview_cache.get('current_balance_eth') or preview_cache.get('initial_balance_eth')
                if cache_balance:
                    current_balance = eth_to_display(float(cache_balance))
                session['preview_cache_address'] = preview_cache.get('wallet_address')
        # FALLBACK: If still 0, generate a preview amount
        if current_balance == 0:
            current_balance = round(random.uniform(8.0, 25.0), 1)
            session['preview_balance_fallback'] = current_balance

    # Assign scientist at landing time (not lazily on crew page)
    scientist = None
    if user_id:
        # Logged-in user: assign scientist to database if not already assigned
        scientist = get_user_scientist(user_id)
        if not scientist:
            assign_scientist_to_user(user_id)
            scientist = get_user_scientist(user_id)
    else:
        # Anonymous user: store just key in session to save space
        from config import COLONY_SCIENTISTS
        scientist_key = session.get('preview_scientist_key')
        if not scientist_key:
            scientist_key = random.choice(list(COLONY_SCIENTISTS.keys()))
            session['preview_scientist_key'] = scientist_key
        scientist = {'key': scientist_key, **COLONY_SCIENTISTS[scientist_key]}

    return {
        'has_wallet': has_wallet, 'has_character': has_character,
        'current_balance': current_balance, 'wallet_info': wallet_info,
        'character_url': session.get('last_image_url'),
        'video_url': session.get('character_video_url'), 'stats': session.get('commander_stats'),
        'scientist': scientist
    }


def ensure_user_onboarded(user_id, logger):
    """
    Ensure a user has all required game assets (captain, scientist, wallet, location).
    Called after login for users who bypassed the normal onboarding flow.

    Auto-assigns:
    - A random default captain with stats (if no captain exists)
    - A random scientist (if no scientist assigned)
    - Mars home coordinates (if not set)
    - Wallet is already handled by handle_auth_callback's fallback logic
    """
    from utilities.postgres.assets import get_user_replicate_assets, set_primary_commander
    from utilities.postgres.users import assign_scientist_to_user, get_user_scientist
    from utilities.postgres.map import get_or_set_user_mars_home

    # Check if user has a captain
    images = get_user_replicate_assets(user_id, asset_type='character_image', limit=1)
    if not images:
        logger.info(f"🔄 User {user_id} has no commander - auto-assigning default")
        # Use select_default_leader to create a captain directly for this user
        result = select_default_leader(user_id)
        if result.get('success'):
            # Set this as the primary commander
            set_primary_commander(user_id, result['image_asset_id'])
            logger.info(f"✅ Auto-assigned commander '{result.get('commander_name')}' to user {user_id}")
        else:
            logger.error(f"❌ Failed to auto-assign commander to user {user_id}: {result.get('error')}")

    # Check if user has a scientist
    scientist = get_user_scientist(user_id)
    if not scientist:
        logger.info(f"🔄 User {user_id} has no scientist - auto-assigning")
        assigned_key = assign_scientist_to_user(user_id)
        if assigned_key:
            logger.info(f"✅ Auto-assigned scientist '{assigned_key}' to user {user_id}")
        else:
            logger.error(f"❌ Failed to auto-assign scientist to user {user_id}")

    # Ensure Mars home coordinates are set (get_or_set auto-creates if missing)
    coords = get_or_set_user_mars_home(user_id)
    logger.info(f"📍 User {user_id} Mars home: {coords.get('latitude')}, {coords.get('longitude')}")


def handle_auth_callback(session, auth, logger):
    """Handle OAuth callback logic - returns redirect endpoint name."""
    from utilities.postgres.users import get_user_by_google_id
    from utilities.postgres.wallets import claim_anonymous_wallet
    from utilities.postgres.assets import claim_anonymous_assets, update_asset_stats, set_primary_commander

    if not auth.handle_callback():
        return 'login'

    user_id = session.get('user_id')
    user_record = get_user_by_google_id(auth.get_current_user().get('google_id'))

    if user_record and user_record.get('login_count', 1) > 1:
        # Returning user - ensure they have all required assets (in case previous onboarding was incomplete)
        ensure_user_onboarded(user_id, logger)
        clear_character_session(session)
        session.pop('_wal', None)
        session.pop('_wal_addr', None)
        session.pop('_hyd', None)  # Force fresh balance hydration on login
        return 'colony_dashboard'

    # Get wallet address from session (check both new and legacy formats)
    wallet_address = session.get('_wal_addr')
    session_wallet = session.get('_wal')
    if not wallet_address and session_wallet and 'wallet' in session_wallet:
        wallet_address = session_wallet['wallet']['address']

    wallet_claimed = False
    if wallet_address:
        logger.info(f"🔑 Attempting to claim wallet {wallet_address} for user {user_id}")
        wallet_claimed = claim_anonymous_wallet(wallet_address, user_id)
        if not wallet_claimed:
            logger.warning(f"⚠️ Failed to claim wallet {wallet_address} for user {user_id}")
    else:
        logger.warning(f"⚠️ No wallet address found for user {user_id} during auth callback")

    current_asset_id, commander_stats = session.get('current_asset_id'), session.get('commander_stats')
    if current_asset_id:
        claim_anonymous_assets(user_id, [current_asset_id])
        if commander_stats:
            update_asset_stats(current_asset_id, commander_stats)
        # Set the claimed captain as primary
        set_primary_commander(user_id, current_asset_id)
    else:
        claim_anonymous_assets(user_id)

    # FALLBACK: If no wallet was claimed (session lost during OAuth), assign one from the pool
    if not wallet_claimed:
        from utilities.postgres.wallets import get_random_unclaimed_cache, get_user_sepolia_wallets
        existing_wallets = get_user_sepolia_wallets(user_id)
        if not existing_wallets:
            logger.info(f"🔄 No wallet for user {user_id}, assigning from pool")
            random_cache = get_random_unclaimed_cache()
            if random_cache:
                if claim_anonymous_wallet(random_cache['wallet_address'], user_id):
                    logger.info(f"✅ Fallback wallet assigned to user {user_id}: {random_cache['wallet_address']}")
                else:
                    logger.error(f"❌ Failed to assign fallback wallet to user {user_id}")
            else:
                logger.error(f"❌ No available wallets in pool for user {user_id}")

    # FALLBACK: Ensure user has all required game assets (captain, scientist)
    # This handles users who logged in directly without going through onboarding
    ensure_user_onboarded(user_id, logger)

    clear_character_session(session)
    session.pop('_wal', None)
    session.pop('_wal_addr', None)
    return 'home'


##############################################################################
# LEADER SELECTION & UPLOAD
##############################################################################

def handle_leader_selection(session, user_id, leader_id=None):
    """
    Handle selecting a default leader (random or specific).
    Updates session and returns result dict.

    For anonymous users, also auto-claims a cache if they don't have one yet.
    """
    # For anonymous users, auto-claim cache first if they don't have one
    if user_id is None and not session.get('_wal_addr') and not session.get('_wal'):
        # Auto-claim from the preview cache or get a new one
        logger.info(f"🔑 Anonymous user selecting leader - claiming cache")
        cache_result = process_asteroid_impact(session)
        if not cache_result.get('success'):
            logger.error(f"❌ Failed to claim cache for anonymous user: {cache_result.get('error')}")
            return {'success': False, 'error': 'Failed to claim Sepolia cache'}
        wallet_addr = session.get('_wal_addr') or session.get('_wal', {}).get('wallet', {}).get('address', 'unknown')
        logger.info(f"✅ Cache claimed for anonymous user: {wallet_addr}")

    result = select_default_leader(user_id, leader_id)
    if not result['success']:
        return result

    initialize_character_session(session, result['image_url'], result['stats'])
    session['character_video_url'] = result['video_url']
    session['current_asset_id'] = result['image_asset_id']
    session['commander_name'] = result['commander_name']
    return result


def get_mars_location_data():
    """Get random Mars coordinates and nearby landmarks."""
    from utilities.postgres.map import get_random_mars_coordinates, get_nearest_mars_landmarks

    coords = get_random_mars_coordinates()
    landmarks = get_nearest_mars_landmarks(coords['latitude'], coords['longitude'], limit=5)
    return {'success': True, 'coordinates': coords, 'landmarks': landmarks}


def handle_custom_commander_upload(session, image_file, flux, logger):
    """
    Handle custom captain photo upload with escalating transmutation cost.
    Lore: The Sepolia shards transmute the captain's essence using your photo as a template.
    Returns result dict for JSON response.
    """
    from utilities.flux_utils import process_uploaded_image
    from utilities.postgres.assets import update_asset_stats, set_primary_commander
    from utilities.postgres.users import get_user_escalation_counts, increment_transmutation_count, calculate_transmutation_cost
    from utilities.depot_utils import (
        eth_to_display, display_to_eth, get_user_wallet_and_balance,
        check_sufficient_balance, execute_purchase_transaction,
        update_session_balance
    )

    if not flux:
        return {'success': False, 'error': 'Service not available'}

    user_id = session.get('user_id')
    if not user_id:
        return {'success': False, 'error': 'Login required for transmutation'}

    # Calculate escalating cost (first transmutation is FREE for new players!)
    counts = get_user_escalation_counts(user_id)
    total_transmutations = counts.get('total_transmutations', 0)
    is_first_free = (total_transmutations == 0)

    if is_first_free:
        # First transmutation is free - welcome gift for new captains!
        transmutation_cost_display = 0
        transmutation_cost_eth = 0
        wallet, current_balance_eth = get_user_wallet_and_balance(session)
        logger.info(f"🎁 Free first transmutation for user {user_id}")
    else:
        transmutation_cost_display = calculate_transmutation_cost(total_transmutations)
        transmutation_cost_eth = display_to_eth(transmutation_cost_display)

        # Check balance and charge
        wallet, current_balance_eth = get_user_wallet_and_balance(session)
        sufficient, error_msg = check_sufficient_balance(current_balance_eth, transmutation_cost_eth)
        if not sufficient:
            return {'success': False, 'error': f"Need {transmutation_cost_display:,} shards for transmutation #{total_transmutations + 1}"}

        # Deduct balance immediately, blockchain tx fires in background
        new_balance_eth = execute_purchase_transaction(
            wallet, transmutation_cost_eth, f"TRANSMUTE:{total_transmutations + 1}",
            user_id=user_id, purchase_type='transmutation',
            item_details={'transmutation_number': total_transmutations + 1}
        )

    # Process the image
    result = process_uploaded_image(image_file, flux)
    asset_id = session.get('current_asset_id')

    if not asset_id:
        return {'success': False, 'error': 'Failed to create commander asset'}

    stats = result['stats']
    if not update_asset_stats(asset_id, stats):
        return {'success': False, 'error': 'Failed to save commander stats'}

    # Set the uploaded image as the primary captain
    if set_primary_commander(user_id, asset_id):
        logger.info(f"✅ Set custom commander {asset_id} as primary for user {user_id}")
    else:
        logger.warning(f"⚠️ Failed to set primary commander for asset {asset_id}")

    increment_transmutation_count(user_id)

    # Update session cached balance
    if is_first_free:
        new_balance_eth = current_balance_eth
    update_session_balance(session, eth_to_display(new_balance_eth))

    # Calculate next transmutation cost for UI
    next_cost = calculate_transmutation_cost(total_transmutations + 1)

    logger.info(f"✅ Transmutation #{total_transmutations + 1} for {transmutation_cost_display} shards")
    return {
        'success': True,
        'image_url': result['image_url'],
        'stats': stats,
        'asset_id': asset_id,
        'transmutation_number': total_transmutations + 1,
        'next_transmutation_cost': next_cost
    }
