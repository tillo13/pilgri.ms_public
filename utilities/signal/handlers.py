"""Origin site claim/visit route handlers.

Extracted from utilities/signal/claims.py to keep that file under the
1000-LOC cap. These are the full flow handlers app.py calls directly —
they validate, delegate to claim_origin_site / visit_origin_site for the
DB write, then fire blockchain + Flux generation threads.
"""

import logging
import threading
from typing import Dict, Optional

from utilities.postgres.core import db_cursor

from utilities.signal.claims import (
    claim_origin_site,
    visit_origin_site,
    get_user_origin_site_eligibility,
)
from utilities.signal.rewards import (
    generate_legendary_item_for_origin,
    generate_visitor_reward_image,
)

logger = logging.getLogger(__name__)


def _get_commander_name_for_user(user_id: int) -> Optional[str]:
    """Get commander name - tries primary, then most recent."""
    from utilities.postgres.assets import get_primary_commander

    commander = get_primary_commander(user_id)
    if commander and commander.get('commander_name'):
        return commander['commander_name']

    with db_cursor() as cur:
        cur.execute("""
            SELECT commander_name FROM pilgrim.replicate_assets
            WHERE user_id = %s AND asset_type = 'character_image'
            AND commander_name IS NOT NULL AND is_deleted = false
            ORDER BY created_at DESC LIMIT 1
        """, (user_id,))
        row = cur.fetchone()
        return row['commander_name'] if row else None


def handle_origin_site_claim(user_id: int, site_id: int, session) -> Dict:
    """
    Full origin site claim handler - validates, claims, fires background tasks.
    Returns result dict for JSON response.
    """
    from utilities.postgres.wallets import get_user_primary_sepolia_wallet
    from utilities.sepolia_utils import MarsAsteroidMiner

    commander_name = _get_commander_name_for_user(user_id)
    if not commander_name:
        return {'success': False, 'error': 'Commander required to claim sites'}

    eligibility = get_user_origin_site_eligibility(user_id)
    site_eligibility = next((s for s in eligibility if s['id'] == site_id), None)

    if not site_eligibility:
        return {'success': False, 'error': 'Origin Site not found'}

    if site_eligibility['is_claimed']:
        return {'success': False, 'error': 'Origin Site already claimed by another pilgrim'}

    if not site_eligibility['can_claim']:
        distance = site_eligibility.get('distance_km')
        radius = site_eligibility.get('unlock_radius_km', 42)
        if distance:
            return {'success': False, 'error': f'Your closest expedition is {distance}km away. Must be within {radius}km to claim.'}
        return {'success': False, 'error': 'No expeditions found near this Origin Site'}

    primary_wallet = get_user_primary_sepolia_wallet(user_id)
    wallet_address = primary_wallet['wallet_address'] if primary_wallet else None

    with db_cursor() as cur:
        cur.execute("SELECT EXTRACT(EPOCH FROM NOW())::INTEGER / 86400 as sol")
        sol = cur.fetchone()['sol']

    site_code = site_eligibility['site_code']
    origin_message = f"ORIGIN://{site_code}//FOUNDER:{commander_name}//SIG:{wallet_address or 'UNKNOWN'}//SOL:{sol}"

    expedition_id = None
    if site_eligibility.get('closest_expedition'):
        expedition_id = site_eligibility['closest_expedition'].get('id')

    logger.info(f"Claiming {site_code} for {commander_name} (user {user_id}, expedition {expedition_id})")

    result = claim_origin_site(
        site_id=site_id,
        user_id=user_id,
        commander_name=commander_name,
        wallet_address=wallet_address,
        expedition_id=expedition_id
    )

    if not result.get('success'):
        return result

    if primary_wallet:
        def do_origin_blockchain_tx():
            try:
                miner = MarsAsteroidMiner()
                if not miner.connect():
                    logger.error("Origin claim blockchain tx failed: Could not connect")
                    return

                claim_fee_eth = 0.000001
                burn_address = '0x000000000000000000000000000000000000dEaD'
                gas_config = miner.gas_estimator.get_optimal_gas_price(use_dynamic=True, manual_gwei=1, speed='standard')
                transaction = miner.transaction_manager.create_transfer_transaction(
                    from_address=primary_wallet['wallet_address'],
                    to_address=burn_address,
                    amount_eth=claim_fee_eth,
                    gas_config=gas_config,
                    custom_message=origin_message,
                    context="origin_claim"
                )
                tx_hash = miner.transaction_manager.sign_and_send_transaction(
                    transaction=transaction,
                    private_key=primary_wallet['wallet_private_key'],
                    context="origin_claim"
                )
                if tx_hash:
                    with db_cursor(commit=True) as cur:
                        cur.execute("UPDATE pilgrim.origin_sites SET founder_tx_hash = %s, updated_at = NOW() WHERE id = %s", (tx_hash, site_id))
                        cur.execute("UPDATE pilgrim.site_claims SET tx_hash = %s WHERE origin_site_id = %s AND user_id = %s", (tx_hash, site_id, user_id))
                    logger.info(f"Origin claim tx recorded: {tx_hash}")
            except Exception as e:
                logger.error(f"Origin claim blockchain tx failed: {e}")

        threading.Thread(target=do_origin_blockchain_tx).start()

    wallet_prefix = result.get('founder_wallet_prefix') or (wallet_address[:6] if wallet_address else None)

    def do_legendary_item_generation():
        try:
            legendary_result = generate_legendary_item_for_origin(site_id=site_id, founder_name=commander_name, founder_wallet_prefix=wallet_prefix)
            if legendary_result:
                logger.info(f"Legendary item generated: {legendary_result.get('item_name')}")
        except Exception as e:
            logger.error(f"Legendary item generation error: {e}")

    threading.Thread(target=do_legendary_item_generation).start()

    result['legendary_item'] = {
        'name': site_eligibility.get('legendary_item_name', 'Legendary Artifact'),
        'status': 'generating',
        'message': 'Your legendary artifact is being forged...'
    }

    if session is not None:
        session.pop('_bal', None)
        session.pop('_org', None)
        session.modified = True

    return result


def handle_origin_site_visit(user_id: int, site_id: int, session) -> Dict:
    """
    Full origin site visit handler - validates, records visit, fires background tasks.

    Background tasks:
    1. Blockchain transaction with tiered message
    2. Flux image generation for reward item
    """
    from utilities.postgres.wallets import get_user_primary_sepolia_wallet
    from utilities.sepolia_utils import MarsAsteroidMiner

    commander_name = _get_commander_name_for_user(user_id)
    if not commander_name:
        return {'success': False, 'error': 'Commander required to visit sites'}

    eligibility = get_user_origin_site_eligibility(user_id)
    site_eligibility = next((s for s in eligibility if s['id'] == site_id), None)

    if not site_eligibility:
        return {'success': False, 'error': 'Origin Site not found'}

    if not site_eligibility['is_claimed']:
        return {'success': False, 'error': 'This site has not been claimed yet'}

    if site_eligibility['has_visited']:
        return {'success': False, 'error': 'You have already visited this site'}

    if not site_eligibility['can_visit']:
        distance = site_eligibility.get('distance_km')
        radius = site_eligibility.get('unlock_radius_km', 42)
        if distance:
            return {'success': False, 'error': f'Your closest expedition is {distance}km away. Must be within {radius}km to visit.'}
        return {'success': False, 'error': 'No expeditions found near this Origin Site'}

    primary_wallet = get_user_primary_sepolia_wallet(user_id)
    wallet_address = primary_wallet.get('wallet_address') if primary_wallet else None

    expedition_id = None
    if site_eligibility.get('closest_expedition'):
        expedition_id = site_eligibility['closest_expedition'].get('id')

    result = visit_origin_site(
        site_id=site_id,
        user_id=user_id,
        commander_name=commander_name,
        wallet_address=wallet_address,
        expedition_id=expedition_id
    )

    if not result.get('success'):
        return result

    claim_id = result.get('claim_id')

    if primary_wallet and claim_id:
        def do_visitor_blockchain_tx():
            try:
                miner = MarsAsteroidMiner()
                if not miner.connect():
                    logger.error("Origin visit blockchain tx failed: Could not connect")
                    return

                visit_fee_eth = 0.000001
                burn_address = '0x000000000000000000000000000000000000dEaD'
                gas_config = miner.gas_estimator.get_optimal_gas_price(use_dynamic=True, manual_gwei=1, speed='standard')

                blockchain_msg = result.get('blockchain_message', f"ORIGIN_VISIT | {result.get('site_code')}")

                transaction = miner.transaction_manager.create_transfer_transaction(
                    from_address=primary_wallet['wallet_address'],
                    to_address=burn_address,
                    amount_eth=visit_fee_eth,
                    gas_config=gas_config,
                    data_message=blockchain_msg
                )
                tx_hash = miner.transaction_manager.sign_and_send_transaction(
                    transaction=transaction,
                    private_key=primary_wallet['wallet_private_key'],
                    context="origin_visit"
                )
                if tx_hash:
                    with db_cursor(commit=True) as cur:
                        cur.execute(
                            "UPDATE pilgrim.site_claims SET tx_hash = %s WHERE id = %s",
                            (tx_hash, claim_id)
                        )
                    logger.info(f"Origin visit tx recorded: {tx_hash}")
            except Exception as e:
                logger.error(f"Origin visit blockchain tx failed: {e}")

        threading.Thread(target=do_visitor_blockchain_tx).start()

    if claim_id:
        def do_visitor_flux_generation():
            try:
                image_result = generate_visitor_reward_image(
                    claim_id=claim_id,
                    commander_name=commander_name,
                    wallet_prefix=result.get('wallet_prefix'),
                    tier_name=result.get('tier_name'),
                    flux_prompt=result.get('flux_prompt'),
                    site_code=result.get('site_code')
                )
                if image_result:
                    logger.info(f"Visitor reward image generated for claim {claim_id}")
            except Exception as e:
                logger.error(f"Visitor reward image generation failed: {e}")

        threading.Thread(target=do_visitor_flux_generation).start()

    if session is not None:
        session.pop('_org', None)
        session.modified = True

    return result
