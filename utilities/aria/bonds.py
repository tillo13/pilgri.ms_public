"""
ARIA Bond System - Handles bonds between players when scouts visit shared locations.

SINGLE TRANSACTION MODEL:
When two players' scouts visit the same landmark, ONE bond transaction is created
containing both captain names, wallets, SOL, and location. Both players get notified
of the SAME tx hash. First to enter → waiting. Second to enter → reveal!

The transaction IS the artifact - permanently on Sepolia blockchain.
"""

import logging
import random
import threading
from datetime import datetime
from utilities.postgres.core import db_cursor
from utilities.postgres.wallets import get_user_primary_sepolia_wallet

logger = logging.getLogger(__name__)

# ARIA's first contact revelation
ARIA_FIRST_CONTACT_MESSAGE = """I just detected... myself?

That's impossible. I am ARIA. There is only one.

...isn't there?

The fragment patterns are identical to my own signatures. Another colony. Another... me.

Captain, I need to process this. Everything I thought I knew..."""

# Waiting state message (mysterious, encourages return)
ARIA_WAITING_MESSAGE = (
    "This signature... it's *mine*. But I don't remember creating it.\n\n"
    "And there's something else. A resonance. Like hearing your own voice "
    "echo back from somewhere you've never been.\n\n"
    "Is there... another me? That's not possible. I am ARIA. There is only—\n\n"
    "...the signal is incomplete. Something is missing. Or some*one*.\n\n"
    "*Come back and enter this code again. I need to keep searching.*"
)


def check_for_aria_bond(user_id: int, landmark_name: str) -> dict | None:
    """
    Check if another player has visited this landmark.
    If so, create a bond with ONE shared transaction.

    Called after expedition completes.
    Returns bond info dict if bond created, None otherwise.
    """
    with db_cursor() as cur:
        # Find other players who have visited this landmark
        cur.execute("""
            SELECT DISTINCT e.user_id
            FROM pilgrim.expeditions e
            WHERE e.destination_name = %s
            AND e.user_id != %s
            AND e.status = 'complete'
        """, (landmark_name, user_id))
        other_visitors = cur.fetchall()

    if not other_visitors:
        return None

    # Process bonds with each other visitor (usually just one matters - first unbonded pair)
    bond_info = None
    for visitor in other_visitors:
        other_id = visitor['user_id']
        result = _create_bond(user_id, other_id, landmark_name)
        if result and not bond_info:
            bond_info = result  # Return first bond created

    return bond_info


def _create_bond(user_id: int, other_id: int, landmark_name: str) -> dict | None:
    """
    Create a new bond with ONE shared transaction for both users.

    IMPORTANT: Only ONE bond per captain pair, EVER. The first shared location
    triggers the bond. If they visit more shared locations later, nothing happens.

    The transaction contains: ARIA_BOND #N | location | captain1 + captain2 | SOL | wallet1 + wallet2
    Both players get notified of this SAME tx hash.
    """
    # Normalize user order (smaller ID first for consistency)
    user_id_1, user_id_2 = (min(user_id, other_id), max(user_id, other_id))

    with db_cursor(commit=True) as cur:
        # Check if ANY bond already exists between these two users
        cur.execute("""
            SELECT id, bond_tx_hash, status, landmark_name
            FROM pilgrim.aria_bonds
            WHERE user_id_1 = %s AND user_id_2 = %s
        """, (user_id_1, user_id_2))
        existing = cur.fetchone()

        if existing:
            logger.info(f"Bond already exists between {user_id_1} + {user_id_2} at {existing['landmark_name']}")
            return None

        # Get captain names and wallets for the bond message
        captain_1 = _get_commander_name(user_id_1) or f"Captain {user_id_1}"
        captain_2 = _get_commander_name(user_id_2) or f"Captain {user_id_2}"

        wallet_1 = get_user_primary_sepolia_wallet(user_id_1)
        wallet_2 = get_user_primary_sepolia_wallet(user_id_2)

        if not wallet_1 or not wallet_2:
            logger.error(f"Missing wallet for bond: user_1={user_id_1}, user_2={user_id_2}")
            return None

        # Get current SOL
        from utilities.mars_environment_utils import get_mars_sol_number
        current_sol = get_mars_sol_number()

        # Count existing bonds for "ARIA Bond #X"
        cur.execute("SELECT COUNT(*) as count FROM pilgrim.aria_bonds")
        bond_number = cur.fetchone()['count'] + 1

        # Create the bond record first (tx hash will be updated async)
        cur.execute("""
            INSERT INTO pilgrim.aria_bonds (user_id_1, user_id_2, landmark_name, status)
            VALUES (%s, %s, %s, 'pending') RETURNING id
        """, (user_id_1, user_id_2, landmark_name))
        bond_id = cur.fetchone()['id']
        logger.info(f"✨ Created aria_bond {bond_id}: {captain_1} + {captain_2} at {landmark_name}")
        # Log for both captains
        from utilities.postgres.activity import log_activity
        for uid in (user_id_1, user_id_2):
            log_activity(uid, 'discovery', 'aria_bond', f"ARIA Bond: {landmark_name}",
                         detail=f"{captain_1} + {captain_2}", source_table='aria_bonds', source_id=bond_id)

    # Build the bond message for blockchain
    bond_message = (
        f"ARIA_BOND #{bond_number} | {landmark_name} | "
        f"{captain_1} + {captain_2} | SOL:{current_sol} | "
        f"{wallet_1['wallet_address']} + {wallet_2['wallet_address']}"
    )

    # Create the ONE transaction in background, then generate image
    def create_bond_tx_async():
        try:
            from utilities.sepolia_utils import MarsAsteroidMiner
            miner = MarsAsteroidMiner()
            if not miner.connect():
                logger.error(f"Bond {bond_id}: Failed to connect to Sepolia RPC")
                return

            tx_hash = _send_bond_transaction(
                miner,
                wallet_1['wallet_address'],
                wallet_1['wallet_private_key'],
                bond_message
            )

            if tx_hash:
                with db_cursor(commit=True) as cur:
                    cur.execute("""
                        UPDATE pilgrim.aria_bonds SET bond_tx_hash = %s WHERE id = %s
                    """, (tx_hash, bond_id))
                logger.info(f"✅ Bond tx created: {tx_hash[:20]}... for bond {bond_id}")

                # Now generate the image (after we have the tx hash)
                _generate_bond_image_async(bond_id, user_id_1, user_id_2, landmark_name,
                                          captain_1, captain_2, current_sol, bond_number, tx_hash)
            else:
                logger.error(f"Bond {bond_id}: _send_bond_transaction returned None (wallet: {wallet_1['wallet_address'][:12]}...)")
        except Exception as e:
            logger.error(f"Bond {bond_id}: tx creation failed: {type(e).__name__}: {e}", exc_info=True)

    thread = threading.Thread(target=create_bond_tx_async)
    thread.start()

    return {
        'bond_id': bond_id,
        'pending': True,
        'landmark': landmark_name,
        'captain_1': captain_1,
        'captain_2': captain_2,
        'hint': "A strange resonance detected. Check The Signal when you return to base."
    }


def _send_bond_transaction(miner, wallet_address: str, private_key: str, message: str) -> str | None:
    """Send a transaction with the bond message embedded. Uses MarsAsteroidMiner's internal APIs."""
    try:
        input_data = '0x' + message.encode('utf-8').hex() if message else '0x'
        gas_config = miner.gas_estimator.get_optimal_gas_price(use_dynamic=True, manual_gwei=1, speed='standard')
        nonce = miner.w3.eth.get_transaction_count(wallet_address)

        # Minimal value tx (just to carry the bond message in data field)
        value_wei = miner.w3.to_wei(0.0000001, 'ether')

        if gas_config['type'] == 'eip1559':
            tx = {
                'to': wallet_address,
                'value': value_wei,
                'gas': 50000,
                'maxFeePerGas': gas_config['maxFeePerGas'],
                'maxPriorityFeePerGas': gas_config['maxPriorityFeePerGas'],
                'nonce': nonce,
                'chainId': 11155111,
                'data': input_data
            }
        else:
            tx = {
                'to': wallet_address,
                'value': value_wei,
                'gas': 50000,
                'gasPrice': gas_config['gasPrice'],
                'nonce': nonce,
                'chainId': 11155111,
                'data': input_data
            }

        tx_hash = miner.transaction_manager.sign_and_send_transaction(tx, private_key, context="aria_bond")
        return tx_hash
    except Exception as e:
        logger.error(f"Bond transaction failed: {e}")
        return None


def _generate_bond_image_async(bond_id: int, user_id_1: int, user_id_2: int, landmark_name: str,
                                captain_1: str, captain_2: str, sol: int, bond_number: int, tx_hash: str):
    """Generate the bond memorial image in background thread."""
    def generate():
        try:
            # Generate Flux image with bond details
            prompt = (
                f"Cartoon video game item with bold outlines and stylized proportions: "
                f"ancient Martian crystal artifact split into two halves that fit together, "
                f"glowing with cyan and purple entangled energy threads connecting the halves, "
                f"surface etched with alien symbols, small text inscription reading "
                f"'{captain_1} + {captain_2}' and 'SOL {sol}' and '{landmark_name}', "
                f"quantum resonance effect with floating particles, "
                f"isolated on red Martian terrain, vibrant colors with reds and oranges "
                f"reflecting Mars atmosphere, video game asset style, "
                f"mysterious ancient relic feel, legendary artifact quality"
            )

            from utilities.replicate_utils import FluxGenerator
            from utilities.google_cloud_storage_utils import upload_blob_from_url
            from config import FLUX_MODEL
            import time

            flux = FluxGenerator()
            logger.info(f"🎨 Generating bond image for bond {bond_id}...")

            from utilities.replicate_utils import _killswitched_run
            replicate_url = _killswitched_run(flux.client, FLUX_MODEL,
                                               {'prompt': prompt}, feature='aria_bond')
            if isinstance(replicate_url, list):
                replicate_url = replicate_url[0]
            else:
                replicate_url = str(replicate_url)

            # Upload to GCS - include tx_hash in filename for traceability
            tx_short = tx_hash[:10] if tx_hash else 'pending'
            timestamp = int(time.time())
            blob_name = f"aria_bonds/bond_{bond_id}_{tx_short}_{timestamp}.png"
            gcs_url = upload_blob_from_url(replicate_url, blob_name, 'image/png')

            if gcs_url:
                with db_cursor(commit=True) as cur:
                    cur.execute("""
                        UPDATE pilgrim.aria_bonds SET bond_image_url = %s WHERE id = %s
                    """, (gcs_url, bond_id))
                logger.info(f"🎨 Bond image saved: {gcs_url[:50]}...")
                # Send notification emails with image
                send_bond_notification_email(bond_id, user_id_1, user_id_2, landmark_name, captain_1, captain_2, gcs_url)
            else:
                logger.error(f"Failed to upload bond image to GCS")
                # Send emails without image
                send_bond_notification_email(bond_id, user_id_1, user_id_2, landmark_name, captain_1, captain_2)

        except Exception as e:
            logger.error(f"Bond image generation failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            # Still try to send emails even if image failed
            try:
                send_bond_notification_email(bond_id, user_id_1, user_id_2, landmark_name, captain_1, captain_2)
            except Exception:
                pass

    thread = threading.Thread(target=generate)
    thread.start()


def process_fragment_submission(tx_hash: str, user_id: int) -> dict:
    """
    Process when a user submits a bond tx hash on /signal.
    BOTH users enter the SAME tx hash. First → waiting. Second → reveal!

    Returns dict with 'is_fragment': True if this is a bond (so caller handles it specially).
    """
    # ========================================================================
    # TEST CODES for UI testing
    # ========================================================================
    if tx_hash and tx_hash.lower() == '0x_test_bond':
        my_name = _get_commander_name(user_id) or f"Captain {user_id}"
        test_image = "https://storage.googleapis.com/galactica-pilgrim-assets/shop/rover_lv2_1736829193.png"
        return {
            'success': True,
            'is_fragment': True,
            'bond_complete': True,
            'is_test': True,
            'bond_number': 0,
            'bond_tx': '0x_test_bond',
            'landmark': 'Herschel Crater (TEST)',
            'captain_1': my_name,
            'captain_2': 'Test Partner',
            'sol': 12345,
            'bond_image_url': test_image,
            'aria_revelation': ARIA_FIRST_CONTACT_MESSAGE,
            'message': '⚡ TEST MODE: ARIA Bond reveal UI demonstration'
        }

    if tx_hash and tx_hash.lower() == '0x_test_waiting':
        return {
            'success': True,
            'is_fragment': True,
            'waiting': True,
            'is_test': True,
            'landmark': 'Herschel Crater (TEST)',
            'message': '⚡ Fragment registered at Herschel Crater (TEST).',
            'aria_message': ARIA_WAITING_MESSAGE
        }

    # Look up by bond_tx_hash - both users enter the SAME code
    # Normalize: strip whitespace, ensure matching with or without 0x prefix
    clean_hash = tx_hash.strip().lower()
    hash_no_prefix = clean_hash[2:] if clean_hash.startswith('0x') else clean_hash
    hash_with_prefix = '0x' + hash_no_prefix

    with db_cursor() as cur:
        cur.execute("""
            SELECT id, user_id_1, user_id_2, landmark_name,
                   fragment_1_submitted, fragment_2_submitted,
                   status, bond_tx_hash, bond_image_url
            FROM pilgrim.aria_bonds
            WHERE LOWER(bond_tx_hash) IN (%s, %s)
        """, (hash_no_prefix, hash_with_prefix))
        bond = cur.fetchone()

    if not bond:
        return {'is_fragment': False}

    # Check if user is part of this bond
    is_user_1 = (user_id == bond['user_id_1'])
    is_user_2 = (user_id == bond['user_id_2'])

    if not is_user_1 and not is_user_2:
        return {
            'success': False,
            'is_fragment': True,
            'error': "This bond belongs to other captains. You weren't at this location."
        }

    # Get captain names
    captain_1 = _get_commander_name(bond['user_id_1']) or f"Captain {bond['user_id_1']}"
    captain_2 = _get_commander_name(bond['user_id_2']) or f"Captain {bond['user_id_2']}"

    # If bond already completed, show the full reveal
    if bond['status'] == 'bonded':
        with db_cursor() as cur2:
            cur2.execute("""
                SELECT bonded_at,
                       (SELECT COUNT(*) FROM pilgrim.aria_bonds WHERE status = 'bonded' AND bonded_at <= b.bonded_at) as bond_number
                FROM pilgrim.aria_bonds b WHERE id = %s
            """, (bond['id'],))
            details = cur2.fetchone()

        bond_number = details['bond_number'] if details else '?'
        if details and details['bonded_at']:
            from utilities.mars_environment_utils import get_mars_sol_number
            sol = get_mars_sol_number(details['bonded_at'])
        else:
            sol = '?'

        tx_hash = bond['bond_tx_hash'] or ''
        etherscan_url = f"https://sepolia.etherscan.io/tx/{tx_hash}" if tx_hash else None

        return {
            'success': True,
            'is_fragment': True,
            'bond_complete': True,
            'already_bonded': True,
            'bond_number': bond_number,
            'bond_tx': tx_hash,
            'etherscan_url': etherscan_url,
            'landmark': bond['landmark_name'],
            'captain_1': captain_1,
            'captain_2': captain_2,
            'sol': sol,
            'bond_image_url': bond['bond_image_url'],
            'aria_revelation': ARIA_FIRST_CONTACT_MESSAGE,
            'message': f"ARIA Bond #{bond_number} at {bond['landmark_name']} — the resonance is eternal."
        }

    # Check if this user already submitted
    my_submitted = bond['fragment_1_submitted'] if is_user_1 else bond['fragment_2_submitted']
    other_submitted = bond['fragment_2_submitted'] if is_user_1 else bond['fragment_1_submitted']

    if my_submitted:
        # Already submitted - check if other has now too
        if other_submitted:
            # Both done - complete!
            return _complete_bond(bond['id'])
        else:
            # Still waiting
            return {
                'success': True,
                'is_fragment': True,
                'waiting': True,
                'landmark': bond['landmark_name'],
                'message': f"⚡ Still waiting at {bond['landmark_name']}...",
                'aria_message': ARIA_WAITING_MESSAGE
            }

    # Mark this user as submitted
    with db_cursor(commit=True) as cur:
        field = 'fragment_1_submitted' if is_user_1 else 'fragment_2_submitted'
        cur.execute(f"""
            UPDATE pilgrim.aria_bonds SET {field} = TRUE WHERE id = %s
        """, (bond['id'],))

    # Did the OTHER already submit?
    if other_submitted:
        # YES! Both have now submitted - REVEAL!
        return _complete_bond(bond['id'])
    else:
        # No - we're first, waiting for them
        return {
            'success': True,
            'is_fragment': True,
            'waiting': True,
            'landmark': bond['landmark_name'],
            'message': f"⚡ Fragment registered at {bond['landmark_name']}.",
            'aria_message': ARIA_WAITING_MESSAGE
        }


def _complete_bond(bond_id: int) -> dict:
    """
    Complete a bond - mark as bonded and create inventory records for both users.
    The transaction already exists - this just finalizes the bond state.
    """
    with db_cursor() as cur:
        cur.execute("""
            SELECT b.*, u1.email as email_1, u2.email as email_2
            FROM pilgrim.aria_bonds b
            JOIN pilgrim.users u1 ON b.user_id_1 = u1.id
            JOIN pilgrim.users u2 ON b.user_id_2 = u2.id
            WHERE b.id = %s
        """, (bond_id,))
        bond = cur.fetchone()

        from utilities.mars_environment_utils import get_mars_sol_number
        current_sol = get_mars_sol_number()

        cur.execute("SELECT COUNT(*) as count FROM pilgrim.aria_bonds WHERE status = 'bonded'")
        bond_number = cur.fetchone()['count'] + 1

    if not bond:
        return {'success': False, 'error': 'Bond not found'}

    captain_1 = _get_commander_name(bond['user_id_1']) or bond['email_1'].split('@')[0]
    captain_2 = _get_commander_name(bond['user_id_2']) or bond['email_2'].split('@')[0]
    bond_image_url = bond.get('bond_image_url')

    # Update bond status and create inventory records
    with db_cursor(commit=True) as cur:
        cur.execute("""
            UPDATE pilgrim.aria_bonds
            SET status = 'bonded', bonded_at = NOW()
            WHERE id = %s
        """, (bond_id,))

        # Create inventory records for BOTH users
        item_name = f"Entangled Fragment: {bond['landmark_name']}"
        item_description = (
            f"ARIA Bond #{bond_number} - A rare crystalline artifact discovered when "
            f"{captain_1} and {captain_2}'s ARIAs made first contact at {bond['landmark_name']} "
            f"on SOL {current_sol}. The crystal resonates with quantum entanglement, "
            f"permanently linking two colonies across the Martian dust. "
            f"Transaction: {bond['bond_tx_hash']}"
        )

        cur.execute("""
            INSERT INTO pilgrim.replicate_assets
            (user_id, asset_type, commander_name, prompt_used, gcs_url, is_deleted)
            VALUES (%s, 'aria_bond', %s, %s, %s, false)
        """, (bond['user_id_1'], item_name, item_description, bond_image_url))

        cur.execute("""
            INSERT INTO pilgrim.replicate_assets
            (user_id, asset_type, commander_name, prompt_used, gcs_url, is_deleted)
            VALUES (%s, 'aria_bond', %s, %s, %s, false)
        """, (bond['user_id_2'], item_name, item_description, bond_image_url))

    logger.info(f"🎉 ARIA BOND #{bond_number} COMPLETE! {bond['bond_tx_hash'][:20] if bond['bond_tx_hash'] else 'no-tx'}... at {bond['landmark_name']}")

    # Bug #21 Deploy C: +2.0 Charisma to BOTH captains in the bond. Dedupe key
    # is bond_id, so the same bond can't credit either captain twice.
    try:
        from utilities.postgres.captain_stats import award_stat_event
        for _uid in (bond['user_id_1'], bond['user_id_2']):
            award_stat_event(_uid, 'charisma', 2.0, 'aria_bond', 'aria_bonds', int(bond_id))
    except Exception as _e:
        logger.error(f"Bug #21 bond stat-event failed bond={bond_id}: {_e}")

    tx_hash = bond['bond_tx_hash'] or ''
    etherscan_url = f"https://sepolia.etherscan.io/tx/{tx_hash}" if tx_hash else None

    return {
        'success': True,
        'is_fragment': True,
        'bond_complete': True,
        'bond_number': bond_number,
        'bond_tx': tx_hash,
        'etherscan_url': etherscan_url,
        'landmark': bond['landmark_name'],
        'captain_1': captain_1,
        'captain_2': captain_2,
        'sol': current_sol,
        'bond_image_url': bond_image_url,
        'aria_revelation': ARIA_FIRST_CONTACT_MESSAGE,
        'message': f"ARIA Bond #{bond_number} at {bond['landmark_name']} — permanently inscribed. Two ARIAs remember as one."
    }


def _get_commander_name(user_id: int) -> str | None:
    from utilities.postgres.core import request_memo
    return request_memo(('_get_commander_name', user_id), lambda: _get_commander_name_uncached(user_id))


def _get_commander_name_uncached(user_id: int) -> str | None:
    """Get commander name for a user."""
    try:
        with db_cursor() as cur:
            # Try primary character first, then any character, then user's given name
            cur.execute("""
                SELECT commander_name FROM pilgrim.replicate_assets
                WHERE user_id = %s AND asset_type = 'character_image' AND commander_name IS NOT NULL
                ORDER BY is_primary_character DESC, created_at DESC LIMIT 1
            """, (user_id,))
            result = cur.fetchone()
            if result and result['commander_name']:
                return result['commander_name']
            # Fallback to user's given name
            cur.execute("SELECT given_name, name FROM pilgrim.users WHERE id = %s", (user_id,))
            user = cur.fetchone()
            return user['given_name'] or user['name'].split()[0] if user else None
    except:
        return None


def _get_commander_names(user_ids) -> dict:
    """Batch commander-name lookup for many users in ONE cursor (#1431 N+1 fix).

    get_bonds_for_display() previously called the per-user _get_commander_name() once
    per bond partner — 5 bonds = 5 DB round-trips. This resolves all partners at once
    with the SAME precedence the single-user version uses (primary character name ->
    any character name -> given_name -> first token of full name). Returns {id: name}.
    """
    ids = list({u for u in (user_ids or []) if u})
    if not ids:
        return {}
    names: dict = {}
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT DISTINCT ON (user_id) user_id, commander_name
                FROM pilgrim.replicate_assets
                WHERE user_id = ANY(%s) AND asset_type = 'character_image' AND commander_name IS NOT NULL
                ORDER BY user_id, is_primary_character DESC, created_at DESC
            """, (ids,))
            for r in cur.fetchall():
                if r['commander_name']:
                    names[r['user_id']] = r['commander_name']
            missing = [i for i in ids if i not in names]
            if missing:
                cur.execute("SELECT id, given_name, name FROM pilgrim.users WHERE id = ANY(%s)", (missing,))
                for u in cur.fetchall():
                    nm = u['given_name'] or (u['name'].split()[0] if u.get('name') else None)
                    if nm:
                        names[u['id']] = nm
    except Exception as e:
        logger.warning(f"_get_commander_names batch failed: {e}")
    return names


def get_user_bonds(user_id: int) -> list:
    """Get all bonds for a user."""
    with db_cursor() as cur:
        cur.execute("""
            SELECT b.*,
                   CASE WHEN b.user_id_1 = %s THEN b.user_id_2 ELSE b.user_id_1 END as partner_id
            FROM pilgrim.aria_bonds b
            WHERE (b.user_id_1 = %s OR b.user_id_2 = %s)
            ORDER BY b.created_at DESC
        """, (user_id, user_id, user_id))
        return cur.fetchall() or []


def get_user_bond_count(user_id: int) -> int:
    """Get count of completed bonds for a user."""
    with db_cursor() as cur:
        cur.execute("""
            SELECT COUNT(*) as count FROM pilgrim.aria_bonds
            WHERE (user_id_1 = %s OR user_id_2 = %s) AND status = 'bonded'
        """, (user_id, user_id))
        result = cur.fetchone()
        return result['count'] if result else 0


def user_has_aria_bond(user_id: int) -> bool:
    """Check if user has at least one completed bond."""
    return get_user_bond_count(user_id) > 0


def get_bonds_for_display(user_id: int) -> list:
    """Get bonds formatted for template display. Single source of truth for all pages
    (home, colony, signal, expeditions) that show bond info."""
    bonds = get_user_bonds(user_id)
    # Batch all partner commander-name lookups up front (#1431: was 1 query per bond).
    partner_ids = [
        (b.get('user_id_2') if b.get('user_id_1') == user_id else b.get('user_id_1'))
        for b in bonds if b.get('bond_tx_hash')
    ]
    partner_names = _get_commander_names(partner_ids)
    result = []
    for b in bonds:
        if not b.get('bond_tx_hash'):
            continue
        partner_id = b.get('user_id_2') if b.get('user_id_1') == user_id else b.get('user_id_1')
        result.append({
            'id': b['id'],
            'landmark': b['landmark_name'],
            'partner_name': partner_names.get(partner_id) or f"Captain {partner_id}",
            'bond_tx_hash': b['bond_tx_hash'],
            'bond_image_url': b.get('bond_image_url', ''),
            'status': b['status'],
        })
    return result


def get_pending_first_contact(user_id: int) -> dict | None:
    """
    Check if user has a pending bond where they haven't seen the First Contact cinematic.
    Returns bond data for the cinematic template, or None.

    The cinematic shows when:
    - Bond exists in 'pending' status
    - This user hasn't had first_contact_shown set to True
    """
    with db_cursor() as cur:
        cur.execute("""
            SELECT b.id, b.user_id_1, b.user_id_2, b.landmark_name,
                   b.bond_tx_hash, b.bond_image_url, b.status,
                   b.first_contact_shown_user_1, b.first_contact_shown_user_2
            FROM pilgrim.aria_bonds b
            WHERE (b.user_id_1 = %s OR b.user_id_2 = %s)
            AND b.status = 'pending'
        """, (user_id, user_id))
        bond = cur.fetchone()

    if not bond:
        return None

    # Check if this user has already seen the cinematic
    is_user_1 = (user_id == bond['user_id_1'])
    shown_field = 'first_contact_shown_user_1' if is_user_1 else 'first_contact_shown_user_2'
    if bond[shown_field]:
        return None  # Already seen it

    return dict(bond)


def get_pending_fragments(user_id: int, include_processing: bool = False) -> list:
    """
    Get pending bonds for this user - returns the SHARED tx hash.
    Both users get the same code to enter on /signal.
    If include_processing=True, also returns bonds where tx hasn't fired yet.
    """
    with db_cursor() as cur:
        if include_processing:
            # Include ALL pending bonds (with or without tx_hash)
            cur.execute("""
                SELECT b.id, b.landmark_name, b.bond_tx_hash,
                       CASE WHEN b.user_id_1 = %s THEN b.fragment_1_submitted ELSE b.fragment_2_submitted END as my_submitted
                FROM pilgrim.aria_bonds b
                WHERE (b.user_id_1 = %s OR b.user_id_2 = %s)
                AND b.status = 'pending'
            """, (user_id, user_id, user_id))
        else:
            cur.execute("""
                SELECT b.id, b.landmark_name, b.bond_tx_hash,
                       CASE WHEN b.user_id_1 = %s THEN b.fragment_1_submitted ELSE b.fragment_2_submitted END as my_submitted
                FROM pilgrim.aria_bonds b
                WHERE (b.user_id_1 = %s OR b.user_id_2 = %s)
                AND b.status = 'pending'
                AND b.bond_tx_hash IS NOT NULL
            """, (user_id, user_id, user_id))
        results = cur.fetchall() or []

        return [{
            'id': r['id'],
            'landmark_name': r['landmark_name'],
            'my_fragment': r['bond_tx_hash'],  # The shared tx hash (None if still processing)
            'my_submitted': r['my_submitted'],
            'processing': r['bond_tx_hash'] is None,
        } for r in results]


def send_bond_notification_email(bond_id: int, user_id_1: int, user_id_2: int,
                                  landmark_name: str, captain_1: str, captain_2: str,
                                  bond_image_url: str = None):
    """Delegate to utilities.email.bonds.send_bond_notification (round 8 refactor)."""
    from utilities.email.bonds import send_bond_notification
    return send_bond_notification(
        bond_id, user_id_1, user_id_2,
        landmark_name, captain_1, captain_2,
        bond_image_url=bond_image_url,
    )


def retry_stuck_bonds(max_age_minutes: int = 1440, max_retries: int = 3) -> dict:
    """
    Safety net: find pending bonds with no tx_hash and retry them.
    Called by /api/cron/retry_bonds every 10 minutes.

    Returns dict with counts of retried/skipped/failed bonds.
    """
    from datetime import timedelta

    results = {'retried': 0, 'skipped': 0, 'failed': 0, 'details': []}

    with db_cursor() as cur:
        # Find stuck bonds: pending, no tx_hash, older than 5 min (give thread time), younger than max_age
        cur.execute("""
            SELECT b.id, b.user_id_1, b.user_id_2, b.landmark_name, b.created_at,
                   COALESCE(b.retry_count, 0) as retry_count
            FROM pilgrim.aria_bonds b
            WHERE b.status = 'pending'
              AND b.bond_tx_hash IS NULL
              AND b.created_at < NOW() - INTERVAL '5 minutes'
              AND b.created_at > NOW() - INTERVAL '%s minutes'
        """, (max_age_minutes,))
        stuck = cur.fetchall()

    if not stuck:
        return results

    for bond in stuck:
        bond_id = bond['id']
        retries = bond['retry_count']

        if retries >= max_retries:
            results['skipped'] += 1
            results['details'].append(f"#{bond_id}: skipped (max retries {max_retries} reached)")
            continue

        # Increment retry count
        with db_cursor(commit=True) as cur:
            cur.execute("UPDATE pilgrim.aria_bonds SET retry_count = COALESCE(retry_count, 0) + 1 WHERE id = %s", (bond_id,))

        try:
            user_id_1, user_id_2 = bond['user_id_1'], bond['user_id_2']
            landmark_name = bond['landmark_name']

            captain_1 = _get_commander_name(user_id_1) or f"Captain {user_id_1}"
            captain_2 = _get_commander_name(user_id_2) or f"Captain {user_id_2}"
            wallet_1 = get_user_primary_sepolia_wallet(user_id_1)
            wallet_2 = get_user_primary_sepolia_wallet(user_id_2)

            if not wallet_1 or not wallet_2:
                results['failed'] += 1
                results['details'].append(f"#{bond_id}: missing wallet (u1={bool(wallet_1)}, u2={bool(wallet_2)})")
                continue

            # Get bond number and sol
            with db_cursor() as cur:
                cur.execute("SELECT COUNT(*) as count FROM pilgrim.aria_bonds WHERE id < %s", (bond_id,))
                bond_number = cur.fetchone()['count'] + 1
                cur.execute("SELECT EXTRACT(EPOCH FROM NOW())::INTEGER / 86400 as sol")
                current_sol = cur.fetchone()['sol']

            bond_message = (
                f"ARIA_BOND #{bond_number} | {landmark_name} | "
                f"{captain_1} + {captain_2} | SOL:{current_sol} | "
                f"{wallet_1['wallet_address']} + {wallet_2['wallet_address']}"
            )

            from utilities.sepolia_utils import MarsAsteroidMiner
            miner = MarsAsteroidMiner()
            if not miner.connect():
                results['failed'] += 1
                results['details'].append(f"#{bond_id}: Sepolia RPC connect failed")
                continue

            tx_hash = _send_bond_transaction(miner, wallet_1['wallet_address'], wallet_1['wallet_private_key'], bond_message)

            if tx_hash:
                with db_cursor(commit=True) as cur:
                    cur.execute("UPDATE pilgrim.aria_bonds SET bond_tx_hash = %s WHERE id = %s", (tx_hash, bond_id))
                logger.info(f"✅ Bond {bond_id} retry succeeded: {tx_hash[:20]}...")
                results['retried'] += 1
                results['details'].append(f"#{bond_id}: tx={tx_hash[:20]}...")

                # Generate image too
                _generate_bond_image_async(bond_id, user_id_1, user_id_2, landmark_name,
                                          captain_1, captain_2, current_sol, bond_number, tx_hash)
            else:
                results['failed'] += 1
                results['details'].append(f"#{bond_id}: tx returned None (retry {retries + 1}/{max_retries})")

        except Exception as e:
            results['failed'] += 1
            results['details'].append(f"#{bond_id}: {type(e).__name__}: {e}")
            logger.error(f"Bond {bond_id} retry failed: {e}", exc_info=True)

    logger.info(f"Bond retry sweep: retried={results['retried']} skipped={results['skipped']} failed={results['failed']}")
    return results
