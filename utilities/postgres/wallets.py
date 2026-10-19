"""Wallet and Sepolia asset database operations."""

import logging
from typing import Dict, Any, Optional, List

from utilities.postgres.core import db_cursor, _fetchone, _fetchall

logger = logging.getLogger(__name__)


def create_sepolia_wallet_for_user(wallet_name: str, wallet_address: str, wallet_private_key: str,
                                    initial_balance: float = 0.0, user_id: int = None, campaign_id: int = None,
                                    custom_message: str = None, mining_data: dict = None) -> Optional[int]:
    """Create Sepolia wallet with complete mining transaction data"""
    try:
        with db_cursor(commit=True) as cur:
            is_primary = False
            if user_id:
                cur.execute("SELECT COUNT(*) as cnt FROM pilgrim.sepolia_assets WHERE user_id = %s AND is_primary_wallet = true", (user_id,))
                count_result = cur.fetchone()
                is_primary = count_result['cnt'] == 0 if count_result else True
            md = mining_data or {}
            cur.execute("""
                INSERT INTO pilgrim.sepolia_assets
                (user_id, wallet_name, wallet_address, wallet_private_key, initial_balance_eth, current_balance_eth,
                 acquired_during_campaign_id, is_primary_wallet, last_balance_check, custom_message, mining_tx_hash,
                 mining_block_number, mining_block_hash, mining_block_timestamp, mining_tx_index, mining_from_address,
                 mining_nonce, mining_gas_limit, mining_gas_used, mining_gas_price_gwei, mining_tx_fee_eth,
                 mining_max_fee_gwei, mining_max_priority_gwei, mining_base_fee_gwei, mining_input_data_length,
                 mining_decoded_message, etherscan_tx_url, etherscan_wallet_url, mining_confirmations)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (user_id, wallet_name, wallet_address, wallet_private_key, initial_balance, initial_balance, campaign_id, is_primary,
                  custom_message, md.get('tx_hash'), md.get('block_number'), md.get('block_hash'), md.get('block_timestamp'),
                  md.get('tx_index'), md.get('from_address'), md.get('nonce'), md.get('gas_limit'), md.get('gas_used'),
                  md.get('gas_price_gwei'), md.get('tx_fee_eth'), md.get('max_fee_gwei'), md.get('max_priority_gwei'),
                  md.get('base_fee_gwei'), md.get('input_data_length'), md.get('decoded_message'),
                  md.get('etherscan_tx_url'), md.get('etherscan_wallet_url'), md.get('confirmations')))
            result = cur.fetchone()
            wallet_id = result['id'] if result else None
            logger.info(f"✅ Created Sepolia wallet '{wallet_name}' (ID: {wallet_id})")
            return wallet_id
    except Exception as e:
        logger.error(f"❌ Failed to create Sepolia wallet: {e}")
        return None


def get_user_sepolia_wallets(user_id: int) -> List[Dict]:
    """Get all Sepolia wallets for a user"""
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT id, wallet_name, wallet_address, initial_balance_eth, current_balance_eth,
                       is_primary_wallet, wallet_purpose, created_at, last_balance_check
                FROM pilgrim.sepolia_assets WHERE user_id = %s
                ORDER BY is_primary_wallet DESC, created_at DESC
            """, (user_id,))
            return _fetchall(cur)
    except Exception as e:
        logger.error(f"❌ Failed to get Sepolia wallets: {e}")
        return []


def get_user_primary_sepolia_wallet(user_id: int) -> Optional[Dict]:
    """Get user's primary Sepolia wallet with FULL mining transaction data"""
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT id, wallet_name, wallet_address, wallet_private_key, initial_balance_eth, current_balance_eth,
                       custom_message, mining_tx_hash, mining_block_number, mining_block_hash, mining_tx_index,
                       mining_from_address, mining_nonce, mining_gas_limit, mining_gas_used, mining_gas_price_gwei,
                       mining_tx_fee_eth, mining_confirmations, etherscan_tx_url, etherscan_wallet_url, created_at
                FROM pilgrim.sepolia_assets WHERE user_id = %s AND is_primary_wallet = true LIMIT 1
            """, (user_id,))
            return _fetchone(cur)
    except Exception as e:
        logger.error(f"❌ Failed to get primary wallet: {e}")
        return None


def update_sepolia_wallet_balance(wallet_address: str, new_balance: float) -> bool:
    """Update cached balance for a Sepolia wallet"""
    from utilities.postgres.core import _update
    return _update('sepolia_assets', 'current_balance_eth = %s, last_balance_check = NOW()', 'wallet_address = %s', (new_balance, wallet_address), 'wallet balance')


def sync_all_wallet_balances() -> dict:
    """
    CRON JOB: Sync all user wallet balances from blockchain to DB.
    Called hourly via /api/cron/sync_balances.

    This allows page loads to use fast DB-cached balances.
    Returns stats on how many wallets were updated.
    """
    from utilities.sepolia_utils import MarsAsteroidMiner

    miner = MarsAsteroidMiner()
    if not miner.connect():
        logger.error("❌ Balance sync: Failed to connect to blockchain")
        return {'success': False, 'error': 'Network unavailable', 'total': 0, 'updated': 0}

    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT wallet_address, current_balance_eth
                FROM pilgrim.sepolia_assets
                WHERE user_id != 5 AND is_assigned = true
            """)
            wallets = _fetchall(cur)
    except Exception as e:
        logger.error(f"❌ Balance sync: Failed to fetch wallets: {e}")
        return {'success': False, 'error': str(e), 'total': 0, 'updated': 0}

    total = len(wallets)
    updated = 0
    errors = 0

    for wallet in wallets:
        try:
            address = wallet['wallet_address']
            old_balance = float(wallet['current_balance_eth'] or 0)
            new_balance = miner.get_live_wallet_balance(address, old_balance)

            if abs(new_balance - old_balance) > 0.0000001:
                update_sepolia_wallet_balance(address, new_balance)
                updated += 1
                logger.info(f"💰 Balance sync: {address[:10]}... {old_balance:.6f} → {new_balance:.6f}")
        except Exception as e:
            errors += 1
            logger.warning(f"⚠️ Balance sync error for {wallet['wallet_address'][:10]}...: {e}")

    logger.info(f"✅ Balance sync complete: {updated}/{total} wallets updated, {errors} errors")
    return {'success': True, 'total': total, 'updated': updated, 'errors': errors}


def claim_anonymous_wallet(wallet_address: str, new_user_id: int) -> bool:
    """Transfer anonymous wallet to authenticated user"""
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE pilgrim.sepolia_assets
                SET user_id = %s, is_primary_wallet = true, is_assigned = true, assigned_at = NOW(), updated_at = NOW()
                WHERE wallet_address = %s AND user_id = 5 AND is_assigned = false
            """, (new_user_id, wallet_address))
            if cur.rowcount > 0:
                logger.info(f"✅ Claimed wallet {wallet_address} for user {new_user_id}")
                return True
            return False
    except Exception as e:
        logger.error(f"❌ Failed to claim wallet: {e}")
        return False


def get_wallet_by_address(wallet_address: str) -> Optional[Dict]:
    """Get wallet by address"""
    from utilities.postgres.core import _get_one
    return _get_one('sepolia_assets', 'wallet_address = %s', (wallet_address,), 'wallet')


def get_random_unclaimed_cache() -> Optional[Dict]:
    """Get a random wallet from the user_id=5 pool that hasn't been assigned yet"""
    try:
        with db_cursor() as cur:
            cur.execute("SELECT * FROM pilgrim.sepolia_assets WHERE user_id = 5 AND is_assigned = false ORDER BY RANDOM() LIMIT 1")
            return _fetchone(cur)
    except Exception as e:
        logger.error(f"Failed to get random unclaimed cache: {e}")
        return None
