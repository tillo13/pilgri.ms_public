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
from utilities.postgres_utils import db_cursor, get_user_primary_sepolia_wallet

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
        cur.execute("SELECT EXTRACT(EPOCH FROM NOW())::INTEGER / 86400 as sol")
        current_sol = cur.fetchone()['sol']

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
        from utilities.db_activity import log_activity
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
                logger.error("Failed to connect for bond tx")
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
        except Exception as e:
            logger.error(f"Bond tx creation failed: {e}")

    thread = threading.Thread(target=create_bond_tx_async, daemon=True)
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
    """Send a transaction with the bond message embedded."""
    try:
        input_data = miner.encode_message_to_hex(message)
        gas_config = miner.get_gas_config()
        nonce = miner.w3.eth.get_transaction_count(wallet_address)

        # Minimal value tx (just to have a transaction)
        value_wei = miner.w3.to_wei(0.0000001, 'ether')

        if gas_config['type'] == 'eip1559':
            tx = {
                'to': wallet_address,
                'value': value_wei,
                'gas': 50000,  # Slightly more gas for longer message
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

        tx_hash = miner.sign_and_send_transaction(tx, private_key, context="aria_bond")
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

            from utilities.flux_utils import FluxGenerator
            from utilities.google_cloud_storage_utils import upload_blob_from_url
            from config import FLUX_MODEL
            import time

            flux = FluxGenerator()
            logger.info(f"🎨 Generating bond image for bond {bond_id}...")

            replicate_url = flux.client.run(FLUX_MODEL, input={'prompt': prompt})
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

    thread = threading.Thread(target=generate, daemon=True)
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
    with db_cursor() as cur:
        cur.execute("""
            SELECT id, user_id_1, user_id_2, landmark_name,
                   fragment_1_submitted, fragment_2_submitted,
                   status, bond_tx_hash, bond_image_url
            FROM pilgrim.aria_bonds
            WHERE bond_tx_hash = %s
        """, (tx_hash,))
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
        sol = int(details['bonded_at'].timestamp() / 86400) if details and details['bonded_at'] else '?'

        return {
            'success': True,
            'is_fragment': True,
            'bond_complete': True,
            'already_bonded': True,
            'bond_number': bond_number,
            'bond_tx': bond['bond_tx_hash'],
            'landmark': bond['landmark_name'],
            'captain_1': captain_1,
            'captain_2': captain_2,
            'sol': sol,
            'bond_image_url': bond['bond_image_url'],
            'aria_revelation': ARIA_FIRST_CONTACT_MESSAGE,
            'message': f"⚡ ARIA Bond #{bond_number} at {bond['landmark_name']} - the resonance is eternal."
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

        cur.execute("SELECT EXTRACT(EPOCH FROM NOW())::INTEGER / 86400 as sol")
        current_sol = cur.fetchone()['sol']

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
            (user_id, asset_type, name, prompt, image_url, is_deleted)
            VALUES (%s, 'aria_bond', %s, %s, %s, false)
        """, (bond['user_id_1'], item_name, item_description, bond_image_url))

        cur.execute("""
            INSERT INTO pilgrim.replicate_assets
            (user_id, asset_type, name, prompt, image_url, is_deleted)
            VALUES (%s, 'aria_bond', %s, %s, %s, false)
        """, (bond['user_id_2'], item_name, item_description, bond_image_url))

    logger.info(f"🎉 ARIA BOND #{bond_number} COMPLETE! {bond['bond_tx_hash'][:20] if bond['bond_tx_hash'] else 'no-tx'}... at {bond['landmark_name']}")

    return {
        'success': True,
        'is_fragment': True,
        'bond_complete': True,
        'bond_number': bond_number,
        'bond_tx': bond['bond_tx_hash'],
        'landmark': bond['landmark_name'],
        'captain_1': captain_1,
        'captain_2': captain_2,
        'sol': current_sol,
        'bond_image_url': bond_image_url,
        'aria_revelation': ARIA_FIRST_CONTACT_MESSAGE,
        'message': f"⚡ ARIA Bond #{bond_number} - Two ARIAs remember as one."
    }


def _get_commander_name(user_id: int) -> str | None:
    """Get commander name for a user."""
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT name FROM pilgrim.replicate_assets
                WHERE user_id = %s AND asset_type = 'character_image'
                LIMIT 1
            """, (user_id,))
            result = cur.fetchone()
            return result['name'] if result else None
    except:
        return None


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


def get_pending_fragments(user_id: int) -> list:
    """
    Get pending bonds for this user - returns the SHARED tx hash.
    Both users get the same code to enter on /signal.
    """
    with db_cursor() as cur:
        cur.execute("""
            SELECT b.id, b.landmark_name, b.bond_tx_hash,
                   CASE WHEN b.user_id_1 = %s THEN b.fragment_1_submitted ELSE b.fragment_2_submitted END as my_submitted
            FROM pilgrim.aria_bonds b
            WHERE (b.user_id_1 = %s OR b.user_id_2 = %s)
            AND b.status = 'pending'
            AND b.bond_tx_hash IS NOT NULL
        """, (user_id, user_id, user_id))
        results = cur.fetchall() or []

        # Format for compatibility with existing code
        return [{
            'id': r['id'],
            'landmark_name': r['landmark_name'],
            'my_fragment': r['bond_tx_hash'],  # The shared tx hash
            'my_submitted': r['my_submitted']
        } for r in results]


def send_bond_notification_email(bond_id: int, user_id_1: int, user_id_2: int,
                                  landmark_name: str, captain_1: str, captain_2: str,
                                  bond_image_url: str = None):
    """
    Send individual bond notification emails to BOTH captains.
    Each gets their own email (To: their email) — no email sharing between users.
    Also BCC's andy.tillo@gmail.com for monitoring.
    """
    from utilities.gmail_utils import send_email
    try:
        # Get emails for both users
        with db_cursor() as cur:
            cur.execute("SELECT id, email, commander_name FROM pilgrim.users WHERE id IN (%s, %s)", (user_id_1, user_id_2))
            users = {row['id']: row for row in cur.fetchall()}

        for uid in [user_id_1, user_id_2]:
            user = users.get(uid)
            if not user or not user.get('email'):
                logger.warning(f"No email for user {uid}, skipping bond notification")
                continue

            partner_id = user_id_2 if uid == user_id_1 else user_id_1
            partner = users.get(partner_id, {})
            my_name = user.get('commander_name') or f'Captain {uid}'
            partner_name = partner.get('commander_name') or f'Captain {partner_id}'

            subject = f"ARIA Bond Detected at {landmark_name}"
            img_block = f'<img src="{bond_image_url}" alt="Bond at {landmark_name}" style="width:100%;max-width:480px;border-radius:12px;margin:16px auto;display:block;">' if bond_image_url else ''

            body = f"""
<div style="max-width:520px;margin:0 auto;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#e8e8e8;background:#1a1a2e;padding:28px;border-radius:16px;">
    <div style="text-align:center;margin-bottom:20px;">
        <div style="font-size:32px;margin-bottom:8px;">&#9830;</div>
        <h1 style="color:#06b6d4;font-size:22px;margin:0;">ARIA Bond Detected</h1>
        <p style="color:#94a3b8;font-size:13px;margin:6px 0 0;">Something extraordinary has happened on Mars</p>
    </div>

    {img_block}

    <div style="background:#0f0f23;border-radius:12px;padding:20px;margin:16px 0;border:1px solid rgba(6,182,212,0.2);">
        <p style="font-size:14px;line-height:1.7;margin:0 0 12px;">
            Captain <strong style="color:#06b6d4;">{my_name}</strong> — your ARIA system has detected
            a crystal resonance with Captain <strong style="color:#f59e0b;">{partner_name}</strong>.
        </p>
        <p style="font-size:14px;line-height:1.7;margin:0 0 12px;">
            Both of your expeditions explored the same Mars landmark:
            <strong style="color:#e2e8f0;">{landmark_name}</strong>.
            This has never happened before in your colony's history.
        </p>
        <p style="font-size:14px;line-height:1.7;margin:0;">
            ARIA created a permanent crystal fragment — a shared record of this moment
            etched forever on the Sepolia network. You both share the same fragment code.
        </p>
    </div>

    <div style="background:#0f0f23;border-radius:12px;padding:16px;margin:16px 0;border:1px solid rgba(245,158,11,0.2);">
        <h3 style="color:#f59e0b;font-size:14px;margin:0 0 10px;">What Happens Next</h3>
        <ol style="font-size:13px;line-height:1.8;padding-left:20px;margin:0;color:#cbd5e1;">
            <li>Visit your <strong>Colony page</strong> — you'll see a new <strong>ARIA Bonds</strong> section at the top</li>
            <li>Click the bond card to see full details — location, partner, fragment code</li>
            <li>Go to <strong>The Signal</strong> page and enter the fragment code to decode it</li>
            <li>First captain to decode enters a <em>waiting</em> state. When the second captain decodes — <strong>the bond is revealed</strong></li>
        </ol>
    </div>

    <div style="text-align:center;margin:20px 0;">
        <a href="https://pilgri.ms/colony" style="display:inline-block;background:#06b6d4;color:#fff;padding:12px 28px;border-radius:8px;text-decoration:none;font-weight:600;font-size:14px;">View Your Bond</a>
    </div>

    <p style="font-size:11px;color:#64748b;text-align:center;margin:20px 0 0;line-height:1.5;">
        This is a one-time notification. ARIA bonds are permanent and visible on your Colony page anytime.
    </p>
</div>"""

            send_email(
                subject=subject,
                body=body,
                to_emails=[user.get('email')],
                bcc_emails=['andy.tillo@gmail.com'],
                is_html=True
            )
            logger.info(f"Bond notification email sent to user {uid} ({user.get('email')})")

    except Exception as e:
        logger.error(f"Failed to send bond notification emails: {e}")
