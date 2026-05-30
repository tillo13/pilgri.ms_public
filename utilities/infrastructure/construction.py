"""Infrastructure construction flow: start, check status, completion reward."""
import logging
import threading
from datetime import datetime, timedelta

from config_infrastructure import INFRASTRUCTURE_CATALOG
from utilities.postgres.shop import (
    create_infrastructure,
    get_user_infrastructure,
    update_infrastructure_status,
    get_infrastructure_by_id,
    create_depot_transaction,
)
from utilities.postgres.wallets import get_user_primary_sepolia_wallet, update_sepolia_wallet_balance
from utilities.postgres.map import get_or_set_user_mars_home
from utilities.sepolia_utils import MarsAsteroidMiner

from utilities.infrastructure.environment import calculate_generation_rate

logger = logging.getLogger(__name__)


def _check_build_requirements_fast(structure_type, user_active_types, all_levels):
    """Check build requirements using pre-fetched data (no DB calls)."""
    definition = INFRASTRUCTURE_CATALOG.get(structure_type)
    if not definition:
        return False, ['Invalid structure type']

    missing = []

    for req in definition.get('requirements', []):
        if req not in user_active_types:
            missing.append(req)

    for req_building, req_level in definition.get('unlock_requirements', {}).items():
        if req_building not in user_active_types:
            missing.append(f"{req_building} (need Lv{req_level})")
        else:
            current_level = all_levels.get(req_building, 1)
            if current_level < req_level:
                catalog = INFRASTRUCTURE_CATALOG.get(req_building, {})
                building_name = catalog.get('name', req_building)
                missing.append(f"{building_name} Lv{req_level} (have Lv{current_level})")

    return len(missing) == 0, missing


def get_build_requirements(structure_type, user_id):
    """Check if user meets requirements to build this structure."""
    from utilities.upgrades_utils import get_infrastructure_level

    definition = INFRASTRUCTURE_CATALOG.get(structure_type)
    if not definition:
        return False, ['Invalid structure type']

    user_buildings = get_user_infrastructure(user_id)
    user_types = [b['structure_type'] for b in user_buildings if b.get('status') == 'active']
    missing = []

    requirements = definition.get('requirements', [])
    for req in requirements:
        if req not in user_types:
            missing.append(req)

    unlock_requirements = definition.get('unlock_requirements', {})
    for req_building, req_level in unlock_requirements.items():
        if req_building not in user_types:
            missing.append(f"{req_building} (need Lv{req_level})")
        else:
            current_level = get_infrastructure_level(user_id, req_building)
            if current_level < req_level:
                catalog = INFRASTRUCTURE_CATALOG.get(req_building, {})
                building_name = catalog.get('name', req_building)
                missing.append(f"{building_name} Lv{req_level} (have Lv{current_level})")

    return len(missing) == 0, missing


def start_construction(user_id, structure_type, latitude, longitude):
    """Begin building infrastructure - charge user if needed, set ready_at time"""
    catalog_def = INFRASTRUCTURE_CATALOG.get(structure_type)
    if not catalog_def:
        return {'success': False, 'error': 'Invalid structure type'}

    level_1 = catalog_def.get('levels', {}).get(1, {})
    definition = {
        'name': catalog_def.get('name', structure_type),
        'description': catalog_def.get('description', ''),
        'icon': catalog_def.get('icon', ''),
        'generates_resource': catalog_def.get('generates_resource'),
        'cost_sepolia': level_1.get('cost', 0) / 10_000_000,
        'build_time_seconds': level_1.get('build_time_days', 0) * 86400,
    }

    can_build, missing = get_build_requirements(structure_type, user_id)
    if not can_build:
        return {'success': False, 'error': f'Missing prerequisites: {", ".join(missing)}'}

    generation_rate = calculate_generation_rate(structure_type, latitude, longitude)
    from utilities.upgrades_utils import get_user_upgrade_effects
    build_mult = get_user_upgrade_effects(user_id).get('build_time_mult', 1.0)
    adjusted_seconds = max(60, definition['build_time_seconds'] * build_mult)
    ready_at = datetime.now() + timedelta(seconds=adjusted_seconds)

    new_balance = None

    if definition['cost_sepolia'] > 0:
        wallet = get_user_primary_sepolia_wallet(user_id)
        if not wallet:
            return {'success': False, 'error': 'No wallet found'}

        current_balance = float(wallet.get('current_balance_eth', 0))
        cost_eth = float(definition['cost_sepolia'])

        if current_balance < cost_eth:
            return {
                'success': False,
                'error': f"Insufficient shards. Need {cost_eth * 10000000:.0f}, have {current_balance * 10000000:.0f}"
            }

        cost_display = cost_eth * 10000000
        new_balance = current_balance - cost_eth
        update_sepolia_wallet_balance(wallet['wallet_address'], new_balance)

        logger.info(f"💰 INFRASTRUCTURE PURCHASE: {definition['name']}")
        logger.info(f"   Cost: {cost_display:.1f} Sepolia ({cost_eth} ETH)")
        logger.info(f"   Build Time: {definition['build_time_seconds'] / 86400:.1f} days")
        logger.info(f"   Balance: {current_balance * 10000000:.1f} → {new_balance * 10000000:.1f} Sepolia")

        from utilities.depot_utils import background_blockchain_tx
        background_blockchain_tx(
            wallet_address=wallet['wallet_address'],
            wallet_private_key=wallet['wallet_private_key'],
            amount_eth=cost_eth,
            reason=f"Building {definition['name']}",
            user_id=user_id, purchase_type='infrastructure_purchase',
            item_details={
                'structure_type': structure_type,
                'structure_name': definition['name'],
                'build_time_days': definition['build_time_seconds'] / 86400
            }
        )

    construction_id = create_infrastructure(
        user_id=user_id, structure_type=structure_type, structure_name=definition['name'],
        latitude=latitude, longitude=longitude, cost_sepolia=definition['cost_sepolia'],
        # #1486: store the ADJUSTED duration (build_time_mult applied). check_construction_status
        # decides completion off build_duration_seconds — storing the raw base here meant the
        # "26% faster" discount was cosmetic on ready_at while the building actually took full
        # base time, AND the toast/card/timer showed three different numbers.
        build_duration=adjusted_seconds, generates_resource=definition.get('generates_resource'),
        generation_rate=generation_rate, ready_at=ready_at
    )

    if not construction_id:
        return {'success': False, 'error': 'Database error'}

    reward_result = None
    if definition['cost_sepolia'] == 0 and definition.get('generates_resource') == 'sepolia':
        def send_reward_async():
            try:
                wallet = get_user_primary_sepolia_wallet(user_id)
                if not wallet:
                    logger.warning(f"No wallet for user {user_id}, skipping infrastructure reward")
                    return

                miner = MarsAsteroidMiner()
                if not miner.connect():
                    logger.error(f"Failed to connect to Sepolia for infrastructure reward")
                    return

                coords = get_or_set_user_mars_home(user_id)
                lat = abs(coords['latitude'])
                efficiency = (1.0 - (lat / 90.0) * 0.4) * 100

                initial_reward_eth = 0.000075

                message = (
                    f"{definition['name']} deployed at {coords['latitude']:.2f}°N, {coords['longitude']:.2f}°E. "
                    f"Latitude efficiency: {efficiency:.1f}%. Solar constant: 590 W/m². "
                    f"First shard harvest complete. System now generating {generation_rate:.1f} Sepolia/hour. "
                )

                result = miner.send_sepolia_reward_fast(
                    wallet['wallet_address'],
                    initial_reward_eth,
                    message,
                    context="infrastructure_completion"
                )

                if result['success']:
                    create_depot_transaction(
                        user_id=user_id,
                        wallet_address=wallet['wallet_address'],
                        purchase_type='infrastructure_completion',
                        amount_eth=initial_reward_eth,
                        tx_hash=result['tx_hash'],
                        etherscan_url=result['etherscan_url'],
                        item_details={
                            'construction_id': construction_id,
                            'structure_type': structure_type
                        }
                    )
                    update_sepolia_wallet_balance(
                        wallet['wallet_address'],
                        wallet.get('current_balance_eth', 0) + initial_reward_eth
                    )
                    logger.info(f"⚡ Infrastructure reward broadcast for user {user_id}: {initial_reward_eth * 10000000:.1f} Sepolia")
            except Exception as e:
                logger.error(f"Failed to send async infrastructure reward: {e}")

        thread = threading.Thread(target=send_reward_async)
        thread.start()

        reward_result = {
            'success': True,
            'amount': 750.0,
            'pending': True,
            'message': 'Welcome bonus processing'
        }

    # #1486: same ADJUSTED seconds + same formatter as the depot card (days_hours filter),
    # so the card, this toast, the ready-at countdown, and actual completion all match.
    from utilities.mars_math import format_days_hours
    time_display = format_days_hours(adjusted_seconds)

    if new_balance is None:
        wallet = get_user_primary_sepolia_wallet(user_id)
        new_balance = float(wallet.get('current_balance_eth', 0)) if wallet else 0
    new_balance_display = new_balance * 10000000

    return {
        'success': True,
        'construction_id': construction_id,
        'ready_at': ready_at.isoformat(),
        'time_display': time_display,
        'cost_paid': definition['cost_sepolia'] * 10000000 if definition['cost_sepolia'] > 0 else 0,
        'new_balance': new_balance_display,
        'reward_sent': reward_result is not None,
        'reward': reward_result
    }


def check_construction_status(construction_id):
    """Check if construction is complete. Auto-activates when build timer elapses."""
    building = get_infrastructure_by_id(construction_id)
    if not building:
        return {'complete': False, 'error': 'Not found'}

    if building['status'] == 'active':
        return {
            'complete': True,
            'already_active': True,
            'generation_rate': float(building['generation_rate']),
            'structure_type': building['structure_type']
        }

    elapsed = (datetime.utcnow() - building['build_started_at']).total_seconds()
    required = building['build_duration_seconds']

    if elapsed >= required:
        update_infrastructure_status(construction_id, 'active')
        logger.info(f"✅ Auto-activated {building['structure_type']} (ID: {construction_id})")

        try:
            from utilities.upgrade_image_utils import maybe_generate_infrastructure_image
            image_result = maybe_generate_infrastructure_image(
                structure_type=building['structure_type'],
                level=1,
                user_id=building.get('user_id')
            )
            if image_result.get('is_first_reveal'):
                logger.info(f"🎉 First Reveal! User discovered {building['structure_type']} level 1 image")
        except Exception as e:
            logger.warning(f"Image generation failed (non-blocking): {e}")

        return {
            'complete': True,
            'generation_rate': float(building['generation_rate']),
            'structure_type': building['structure_type'],
            'is_first_reveal': image_result.get('is_first_reveal', False) if 'image_result' in dir() else False
        }

    return {
        'complete': False,
        'progress': elapsed / required,
        'remaining': required - elapsed
    }


def send_completion_reward(construction_id, user_id):
    """Send first payout when construction completes (mostly legacy)."""
    building = get_infrastructure_by_id(construction_id)
    if not building or not building['generates_resource'] or building['generates_resource'] != 'sepolia':
        return {'success': False, 'reason': 'Not a Sepolia generator'}

    wallet = get_user_primary_sepolia_wallet(user_id)
    if not wallet:
        return {'success': False, 'error': 'No wallet'}

    amount_eth = float(building['generation_rate']) / 10000000

    miner = MarsAsteroidMiner()
    if not miner.connect():
        return {'success': False, 'error': 'Network error'}

    coords = get_or_set_user_mars_home(user_id)
    lat = abs(coords['latitude'])
    efficiency = (1.0 - (lat / 90.0) * 0.4) * 100

    message = (
        f"{building['structure_name']} construction complete at {coords['latitude']:.2f}°N, {coords['longitude']:.2f}°E. "
        f"First shard harvest: {building['generation_rate']:.1f} Sepolia. "
        f"Latitude efficiency: {efficiency:.1f}%. System operational. "
    )

    result = miner.send_sepolia_reward_fast(
        wallet['wallet_address'],
        amount_eth,
        message,
        context="infrastructure_completion"
    )

    if result['success']:
        create_depot_transaction(
            user_id=user_id,
            wallet_address=wallet['wallet_address'],
            purchase_type='infrastructure_completion',
            amount_eth=amount_eth,
            tx_hash=result['tx_hash'],
            etherscan_url=result['etherscan_url'],
            item_details={
                'construction_id': construction_id,
                'structure_type': building['structure_type']
            }
        )
        update_sepolia_wallet_balance(
            wallet['wallet_address'],
            wallet.get('current_balance_eth', 0) + amount_eth
        )
        return {
            'success': True,
            'amount': amount_eth * 10000000,
            'tx_hash': result['tx_hash'],
            'broadcast': True
        }

    return {'success': False, 'error': 'Transaction failed'}
