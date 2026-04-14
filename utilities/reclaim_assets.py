#!/usr/bin/env python3
"""
Asset reclamation utility for inactive accounts.

Usage:
    python -m utilities.reclaim_assets              # Dry run - show what would be reclaimed
    python -m utilities.reclaim_assets --execute    # Actually reclaim assets and clean data

This script:
1. Sweeps Sepolia from inactive wallets back to the hub
2. Deletes all user data from the database (expeditions, discoveries, infrastructure, etc.)
3. Sends an audit email with full transaction and deletion details

Protected users (by ID) are never touched regardless of activity.
"""
import argparse
import logging
import time
from datetime import datetime
from utilities.postgres.core import db_cursor
from utilities.sepolia_utils import MarsAsteroidMiner, PILGRIM_ADDRESS
from utilities.gmail_utils import send_email

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

# These user IDs are NEVER touched (core team / active accounts)
PROTECTED_USER_IDS = [
    5,    # pilgridotms@gmail.com (system account)
    45,   # andy.tillo@gmail.com
    112,  # luketillo@gmail.com
    130,  # jacob.stauch@gmail.com
    140,  # chriscappetta3@gmail.com
]

# Minimum balance to bother sweeping (in ETH) - below this, gas cost isn't worth it
MIN_BALANCE_ETH = 0.00001  # ~100 display Sepolia

# Gas buffer to leave in wallet for the transaction itself
GAS_BUFFER_ETH = 0.000005  # ~50 display Sepolia

# Email for audit trail
AUDIT_EMAIL = 'andy.tillo@gmail.com'


def get_reclaimable_users():
    """Get all users eligible for full asset reclamation"""
    try:
        with db_cursor() as cur:
            placeholders = ','.join(['%s'] * len(PROTECTED_USER_IDS))
            cur.execute(f"""
                SELECT u.id, u.email, u.given_name, u.name, u.last_login, u.login_count,
                       u.created_at
                FROM pilgrim.users u
                WHERE u.id NOT IN ({placeholders})
                ORDER BY u.last_login DESC NULLS LAST
            """, PROTECTED_USER_IDS)
            return [dict(row) for row in cur.fetchall()]
    except Exception as e:
        logger.error(f"Failed to get reclaimable users: {e}")
        return []


def get_reclaimable_wallets():
    """Get all wallets eligible for reclamation"""
    try:
        with db_cursor() as cur:
            placeholders = ','.join(['%s'] * len(PROTECTED_USER_IDS))
            cur.execute(f"""
                SELECT sa.id, sa.user_id, sa.wallet_address, sa.wallet_private_key,
                       sa.current_balance_eth, u.email, u.given_name, u.last_login, u.login_count
                FROM pilgrim.sepolia_assets sa
                JOIN pilgrim.users u ON sa.user_id = u.id
                WHERE sa.user_id NOT IN ({placeholders})
                  AND sa.current_balance_eth > %s
                  AND sa.wallet_private_key IS NOT NULL
                ORDER BY sa.current_balance_eth DESC
            """, (*PROTECTED_USER_IDS, MIN_BALANCE_ETH))
            return [dict(row) for row in cur.fetchall()]
    except Exception as e:
        logger.error(f"Failed to get reclaimable wallets: {e}")
        return []


def get_protected_summary():
    """Get summary of protected users"""
    try:
        with db_cursor() as cur:
            placeholders = ','.join(['%s'] * len(PROTECTED_USER_IDS))
            cur.execute(f"""
                SELECT u.id, u.email, u.given_name,
                       COALESCE(SUM(sa.current_balance_eth), 0) as total_balance
                FROM pilgrim.users u
                LEFT JOIN pilgrim.sepolia_assets sa ON sa.user_id = u.id
                WHERE u.id IN ({placeholders})
                GROUP BY u.id, u.email, u.given_name
                ORDER BY u.id
            """, PROTECTED_USER_IDS)
            return [dict(row) for row in cur.fetchall()]
    except Exception as e:
        logger.error(f"Failed to get protected summary: {e}")
        return []


def get_user_data_counts(user_id: int) -> dict:
    """Get counts of all data for a user (for audit purposes)"""
    counts = {}
    try:
        with db_cursor() as cur:
            # Count expeditions
            cur.execute("SELECT COUNT(*) as cnt FROM pilgrim.expeditions WHERE user_id = %s", (user_id,))
            counts['expeditions'] = cur.fetchone()['cnt']

            # Count expedition discoveries (via expedition_id)
            cur.execute("""
                SELECT COUNT(*) as cnt FROM pilgrim.expedition_discoveries ed
                JOIN pilgrim.expeditions e ON ed.expedition_id = e.id
                WHERE e.user_id = %s
            """, (user_id,))
            counts['discoveries'] = cur.fetchone()['cnt']

            # Count infrastructure
            cur.execute("SELECT COUNT(*) as cnt FROM pilgrim.colony_infrastructure WHERE user_id = %s", (user_id,))
            counts['infrastructure'] = cur.fetchone()['cnt']

            # Count depot transactions
            cur.execute("SELECT COUNT(*) as cnt FROM pilgrim.depot_transactions WHERE user_id = %s", (user_id,))
            counts['transactions'] = cur.fetchone()['cnt']

            # Count replicate assets
            cur.execute("SELECT COUNT(*) as cnt FROM pilgrim.replicate_assets WHERE user_id = %s", (user_id,))
            counts['replicate_assets'] = cur.fetchone()['cnt']

            # Count sepolia assets
            cur.execute("SELECT COUNT(*) as cnt FROM pilgrim.sepolia_assets WHERE user_id = %s", (user_id,))
            counts['sepolia_assets'] = cur.fetchone()['cnt']

            # Count landmark discoveries
            cur.execute("SELECT COUNT(*) as cnt FROM pilgrim.landmark_discoveries WHERE user_id = %s", (user_id,))
            counts['landmark_discoveries'] = cur.fetchone()['cnt']

    except Exception as e:
        logger.error(f"Failed to get data counts for user {user_id}: {e}")

    return counts


def delete_user_data(user_id: int, dry_run: bool = True) -> dict:
    """
    Delete all data for a user from the database.

    Order matters due to foreign key constraints:
    1. expedition_discoveries (references expeditions)
    2. expeditions
    3. colony_infrastructure
    4. depot_transactions
    5. replicate_assets
    6. sepolia_assets
    7. landmark_discoveries
    8. users
    """
    result = {
        'user_id': user_id,
        'deleted': {},
        'success': False,
        'error': None
    }

    if dry_run:
        # Just return counts, don't delete
        result['deleted'] = get_user_data_counts(user_id)
        result['success'] = True
        return result

    try:
        with db_cursor(commit=True) as cur:
            # 1. Delete expedition_discoveries (references expeditions)
            cur.execute("""
                DELETE FROM pilgrim.expedition_discoveries
                WHERE expedition_id IN (
                    SELECT id FROM pilgrim.expeditions WHERE user_id = %s
                )
            """, (user_id,))
            result['deleted']['discoveries'] = cur.rowcount

            # 2. Delete landmark_discoveries (references expeditions)
            cur.execute("DELETE FROM pilgrim.landmark_discoveries WHERE user_id = %s", (user_id,))
            result['deleted']['landmark_discoveries'] = cur.rowcount

            # 3. Delete expeditions (now safe - no more references)
            cur.execute("DELETE FROM pilgrim.expeditions WHERE user_id = %s", (user_id,))
            result['deleted']['expeditions'] = cur.rowcount

            # 4. Clear related_asset_id references in depot_transactions before deleting replicate_assets
            cur.execute("""
                UPDATE pilgrim.depot_transactions
                SET related_asset_id = NULL
                WHERE related_asset_id IN (
                    SELECT id FROM pilgrim.replicate_assets WHERE user_id = %s
                )
            """, (user_id,))

            # 5. Delete depot_transactions
            cur.execute("DELETE FROM pilgrim.depot_transactions WHERE user_id = %s", (user_id,))
            result['deleted']['transactions'] = cur.rowcount

            # 6. Delete replicate_assets (now safe - no more references)
            cur.execute("DELETE FROM pilgrim.replicate_assets WHERE user_id = %s", (user_id,))
            result['deleted']['replicate_assets'] = cur.rowcount

            # 7. Delete colony_infrastructure
            cur.execute("DELETE FROM pilgrim.colony_infrastructure WHERE user_id = %s", (user_id,))
            result['deleted']['infrastructure'] = cur.rowcount

            # 8. Delete sepolia_assets
            cur.execute("DELETE FROM pilgrim.sepolia_assets WHERE user_id = %s", (user_id,))
            result['deleted']['sepolia_assets'] = cur.rowcount

            # 9. Delete user record
            cur.execute("DELETE FROM pilgrim.users WHERE id = %s", (user_id,))
            result['deleted']['user'] = cur.rowcount

            result['success'] = True

    except Exception as e:
        result['error'] = str(e)
        logger.error(f"Failed to delete data for user {user_id}: {e}")

    return result


def update_wallet_balance(wallet_id: int, new_balance: float):
    """Update wallet balance in database after sweep"""
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE pilgrim.sepolia_assets
                SET current_balance_eth = %s, last_balance_check = NOW()
                WHERE id = %s
            """, (new_balance, wallet_id))
            return True
    except Exception as e:
        logger.error(f"Failed to update wallet balance: {e}")
        return False


def send_audit_email(wallet_results: list, deletion_results: list,
                     total_reclaimed: float, wallet_success: int, wallet_fail: int):
    """Send detailed audit email with all transaction and deletion results"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Build wallet transaction details
    tx_details = ""
    for r in wallet_results:
        status = "SUCCESS" if r['success'] else "FAILED"
        tx_details += f"""
{status}: {r['email']} (User ID: {r['user_id']})
  Wallet: {r['wallet_address']}
  Amount: {r['amount_eth']:.6f} ETH ({r['amount_eth'] * 10_000_000:.0f} display)
  TX Hash: {r.get('tx_hash', 'N/A')}
  Etherscan: {r.get('etherscan_url', 'N/A')}
  Error: {r.get('error', 'None')}
"""

    # Build deletion details
    deletion_details = ""
    total_deleted = {'expeditions': 0, 'discoveries': 0, 'infrastructure': 0,
                     'transactions': 0, 'replicate_assets': 0, 'sepolia_assets': 0,
                     'landmark_discoveries': 0, 'user': 0}

    for r in deletion_results:
        status = "SUCCESS" if r['success'] else "FAILED"
        deletion_details += f"""
{status}: User ID {r['user_id']} ({r.get('email', 'unknown')})
  Expeditions: {r['deleted'].get('expeditions', 0)}
  Discoveries: {r['deleted'].get('discoveries', 0)}
  Infrastructure: {r['deleted'].get('infrastructure', 0)}
  Transactions: {r['deleted'].get('transactions', 0)}
  Replicate Assets: {r['deleted'].get('replicate_assets', 0)}
  Sepolia Assets: {r['deleted'].get('sepolia_assets', 0)}
  Landmark Discoveries: {r['deleted'].get('landmark_discoveries', 0)}
  User Record: {r['deleted'].get('user', 0)}
  Error: {r.get('error', 'None')}
"""
        for key in total_deleted:
            total_deleted[key] += r['deleted'].get(key, 0)

    body = f"""PILGRIMS ASSET RECLAMATION AUDIT REPORT
==========================================
Timestamp: {timestamp}
Hub Address: {PILGRIM_ADDRESS}

WALLET RECLAMATION SUMMARY
--------------------------
Wallets Processed: {len(wallet_results)}
Successful: {wallet_success}
Failed: {wallet_fail}
Total Reclaimed: {total_reclaimed:.6f} ETH ({total_reclaimed * 10_000_000:.0f} display Sepolia)

DATABASE CLEANUP SUMMARY
------------------------
Users Deleted: {len(deletion_results)}
Total Records Deleted:
  - Expeditions: {total_deleted['expeditions']}
  - Discoveries: {total_deleted['discoveries']}
  - Infrastructure: {total_deleted['infrastructure']}
  - Transactions: {total_deleted['transactions']}
  - Replicate Assets: {total_deleted['replicate_assets']}
  - Sepolia Assets: {total_deleted['sepolia_assets']}
  - Landmark Discoveries: {total_deleted['landmark_discoveries']}
  - User Records: {total_deleted['user']}

PROTECTED USERS (not touched)
-----------------------------
User IDs: {PROTECTED_USER_IDS}

WALLET TRANSACTION DETAILS
--------------------------
{tx_details if tx_details else "No wallet transactions"}

DATABASE DELETION DETAILS
-------------------------
{deletion_details if deletion_details else "No deletions"}

==========================================
End of Report
"""

    subject = f"Pilgrims Asset Reclaim: {wallet_success} wallets, {len(deletion_results)} users cleaned"

    result = send_email(subject, body, [AUDIT_EMAIL], from_name="Pilgrims Admin")
    if result:
        logger.info(f"Audit email sent to {AUDIT_EMAIL}")
    else:
        logger.error(f"Failed to send audit email to {AUDIT_EMAIL}")


def reclaim_assets(dry_run: bool = True):
    """Full asset reclamation: sweep wallets and delete user data"""

    # Show protected users first
    protected = get_protected_summary()
    protected_total = sum(float(p['total_balance'] or 0) for p in protected)

    logger.info("=" * 70)
    logger.info("PROTECTED USERS (will NOT be touched)")
    logger.info("=" * 70)
    for p in protected:
        balance = float(p['total_balance'] or 0) * 10_000_000
        logger.info(f"  ID {p['id']:>3} | {p['email']:35} | {balance:>10.0f}")
    logger.info(f"  TOTAL PROTECTED: {protected_total * 10_000_000:.0f} display Sepolia")
    logger.info("")

    # Get users and wallets to reclaim
    users = get_reclaimable_users()
    wallets = get_reclaimable_wallets()

    if not users:
        logger.info("No users eligible for reclamation.")
        return

    # Show what will be deleted
    logger.info("=" * 70)
    logger.info(f"USERS TO RECLAIM ({len(users)} users)")
    logger.info("=" * 70)

    for u in users:
        last_login = str(u['last_login'])[:10] if u['last_login'] else 'never'
        name = u['given_name'] or u['name'] or 'unknown'
        counts = get_user_data_counts(u['id'])
        logger.info(f"  ID {u['id']:>3} | {u['email']:35} | last: {last_login}")
        logger.info(f"         exp:{counts.get('expeditions', 0):>3} disc:{counts.get('discoveries', 0):>3} infra:{counts.get('infrastructure', 0):>3} tx:{counts.get('transactions', 0):>3}")

    # Show wallets with balance
    if wallets:
        total_reclaimable = sum(float(w['current_balance_eth'] or 0) for w in wallets)
        logger.info("")
        logger.info("=" * 70)
        logger.info(f"WALLETS WITH BALANCE ({len(wallets)} wallets)")
        logger.info("=" * 70)

        for w in wallets:
            balance = float(w['current_balance_eth'] or 0)
            display = balance * 10_000_000
            logger.info(f"  ID {w['user_id']:>3} | {w['email']:35} | {display:>10.0f}")

        logger.info("-" * 70)
        logger.info(f"TOTAL RECLAIMABLE: {total_reclaimable:.6f} ETH ({total_reclaimable * 10_000_000:.0f} display)")
        logger.info(f"HUB ADDRESS: {PILGRIM_ADDRESS}")
    else:
        total_reclaimable = 0

    logger.info("")

    if dry_run:
        logger.info("=" * 70)
        logger.info("DRY RUN - No changes made")
        logger.info("Run with --execute to actually reclaim assets and delete data")
        logger.info("=" * 70)
        return

    # =========================================================================
    # EXECUTE: Sweep wallets first, then delete data
    # =========================================================================

    logger.info("=" * 70)
    logger.info("EXECUTING ASSET RECLAMATION...")
    logger.info("=" * 70)

    wallet_results = []
    wallet_success = 0
    wallet_fail = 0
    total_reclaimed = 0

    # Step 1: Sweep wallets
    if wallets:
        logger.info("")
        logger.info("STEP 1: Sweeping wallets...")
        logger.info("-" * 70)

        miner = MarsAsteroidMiner()
        if not miner.connect():
            logger.error("Failed to connect to Sepolia network - skipping wallet sweep")
        else:
            for w in wallets:
                balance = float(w['current_balance_eth'] or 0)
                sweep_amount = balance - GAS_BUFFER_ETH

                if sweep_amount <= 0:
                    logger.warning(f"  SKIP {w['email']}: balance too low after gas buffer")
                    continue

                logger.info(f"  Sweeping {w['email']}...")
                logger.info(f"    Balance: {balance:.6f} ETH, Sweeping: {sweep_amount:.6f} ETH")

                audit_record = {
                    'user_id': w['user_id'],
                    'email': w['email'],
                    'wallet_address': w['wallet_address'],
                    'amount_eth': sweep_amount,
                    'success': False,
                    'tx_hash': None,
                    'etherscan_url': None,
                    'error': None
                }

                try:
                    result = miner.return_to_hub(
                        from_address=w['wallet_address'],
                        from_private_key=w['wallet_private_key'],
                        amount_eth=sweep_amount,
                        reason=f"Asset reclamation (user {w['user_id']})"
                    )

                    if result.get('success'):
                        wallet_success += 1
                        total_reclaimed += sweep_amount
                        logger.info(f"    SUCCESS: {result.get('etherscan_url')}")

                        audit_record['success'] = True
                        audit_record['tx_hash'] = result.get('tx_hash')
                        audit_record['etherscan_url'] = result.get('etherscan_url')

                        # Update DB balance
                        update_wallet_balance(w['id'], GAS_BUFFER_ETH)

                        time.sleep(2)
                    else:
                        wallet_fail += 1
                        audit_record['error'] = result.get('error')
                        logger.error(f"    FAILED: {result.get('error')}")

                except Exception as e:
                    wallet_fail += 1
                    audit_record['error'] = str(e)
                    logger.error(f"    EXCEPTION: {e}")

                wallet_results.append(audit_record)

    # Step 2: Delete user data
    logger.info("")
    logger.info("STEP 2: Deleting user data...")
    logger.info("-" * 70)

    deletion_results = []
    for u in users:
        logger.info(f"  Deleting data for {u['email']} (ID: {u['id']})...")

        result = delete_user_data(u['id'], dry_run=False)
        result['email'] = u['email']
        deletion_results.append(result)

        if result['success']:
            logger.info(f"    SUCCESS: {sum(result['deleted'].values())} records deleted")
        else:
            logger.error(f"    FAILED: {result['error']}")

    # Summary
    logger.info("")
    logger.info("=" * 70)
    logger.info("RECLAMATION COMPLETE")
    logger.info("=" * 70)
    logger.info(f"  Wallets swept: {wallet_success} success, {wallet_fail} failed")
    logger.info(f"  Sepolia reclaimed: {total_reclaimed:.6f} ETH ({total_reclaimed * 10_000_000:.0f} display)")
    logger.info(f"  Users deleted: {len([r for r in deletion_results if r['success']])}")

    # Send audit email
    logger.info("")
    logger.info("Sending audit email...")
    send_audit_email(wallet_results, deletion_results, total_reclaimed, wallet_success, wallet_fail)


def main():
    parser = argparse.ArgumentParser(description='Reclaim assets from inactive accounts')
    parser.add_argument('--execute', action='store_true',
                        help='Actually execute reclamation (default is dry run)')
    args = parser.parse_args()

    logger.info("")
    logger.info("=" * 70)
    logger.info("PILGRIMS ASSET RECLAMATION UTILITY")
    logger.info("=" * 70)
    logger.info("")

    reclaim_assets(dry_run=not args.execute)


if __name__ == '__main__':
    main()
