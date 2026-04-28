"""
Expedition lifecycle: launch, recall, complete, claim, discovery progress.

All the state-mutating orchestrators for an expedition's journey. Touches
wallet balance, blockchain tx (background), trail increments, SV awards,
signal events, and ARIA bonds. Returns immediately on launch using the
fast-UI / background-blockchain pattern.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from utilities.expeditions.config import (
    BASE_SPEED_KM_PER_HOUR,
    TERRAIN_MODIFIERS,
)
from utilities.expeditions.cost import calculate_expedition_cost
from utilities.postgres.trails import TRAIL_SPEED_MULTIPLIERS

logger = logging.getLogger(__name__)


def launch_expedition(
    user_id: int,
    destination_name: str,
    destination_type: str,
    destination_lat: float,
    destination_lon: float,
    distance_km: float,
    vehicle_type: str = 'rover',
    expedition_type: str = 'standard',
    signal_site_id: Optional[int] = None
) -> dict:
    """
    Launch expedition - handles all business logic:
    - Cost calculation with first mission cap
    - Blockchain transaction
    - DB updates
    - Discovery generation
    """
    from utilities.postgres.wallets import get_user_primary_sepolia_wallet, update_sepolia_wallet_balance
    from utilities.postgres.map import get_or_set_user_mars_home, get_nearest_mars_landmarks
    from utilities.postgres.expeditions import (
        get_user_completed_expeditions_count,
        create_expedition,
        get_discovery_items_catalog,
        create_expedition_discoveries,
        get_user_active_expeditions,
        get_user_discovered_landmarks,
    )
    from utilities.postgres.shop import create_depot_transaction
    from utilities.postgres.users import get_user_scientist
    from utilities.sepolia_utils import MarsAsteroidMiner
    from utilities.depot_utils import generate_commander_stats

    if not all([destination_name, distance_km]):
        return {'success': False, 'error': 'Missing destination data'}

    # Validate vehicle type
    if vehicle_type not in ('rover', 'drone', 'buggy'):
        vehicle_type = 'rover'

    # Phase 2.3b: signal_claim trips must reference a real, detected, unclaimed-by-this-user site.
    # Coords from the client are ignored — we re-source them from pilgrim.origin_sites to prevent spoofing.
    if expedition_type == 'signal_claim':
        if not signal_site_id:
            return {'success': False, 'error': 'signal_claim expedition requires signal_site_id'}
        from utilities.signal.claims import get_user_origin_site_eligibility
        eligibility = get_user_origin_site_eligibility(user_id)
        site = next((s for s in eligibility if s['id'] == signal_site_id), None)
        if not site:
            return {'success': False, 'error': 'Origin Site not found'}
        # Detection gate: captain must be within unlock_radius_km on some past expedition path.
        # This is the same can_claim / can_visit flag the Signal page renders.
        if site.get('has_visited'):
            return {'success': False, 'error': "You've already visited this site — the signal is yours."}
        if not (site.get('can_claim') or site.get('can_visit')):
            return {'success': False, 'error': "You haven't detected this signal yet — run a normal expedition near it first."}
        # Allow visits too — the site can be already-claimed; visitor flow plays the same cinematic.
        # Override destination coords/name with authoritative site row.
        destination_name = site['site_code']
        destination_type = 'OriginSite'
        destination_lat = float(site['latitude'])
        destination_lon = float(site['longitude'])
        # Recompute distance from base for cost honesty.
        from utilities.postgres.map import get_or_set_user_mars_home
        from utilities.mars_math import haversine_distance
        _home = get_or_set_user_mars_home(user_id)
        distance_km = haversine_distance(float(_home['latitude']), float(_home['longitude']),
                                          destination_lat, destination_lon)

    # Check vehicle is owned and get vehicle-specific stats
    from utilities.upgrades_utils import get_vehicle_for_expedition
    vehicle_data = get_vehicle_for_expedition(user_id, vehicle_type)
    if not vehicle_data:
        return {'success': False, 'error': f'{vehicle_type.capitalize()} not unlocked'}

    # Range scales with fog radius (more discoveries = further reach) × scanner vehicle_range_mult
    discovered = get_user_discovered_landmarks(user_id)
    fog_radius = min(1000, 300 + len(discovered) * 50)
    range_mult = fog_radius / 300.0
    from utilities.upgrades_utils import get_user_upgrade_effects as _get_eff
    scanner_range_mult = _get_eff(user_id).get('vehicle_range_mult', 1.0)
    max_range = int(vehicle_data.get('max_range_km', 9999) * range_mult * scanner_range_mult)
    if distance_km > max_range:
        return {'success': False, 'error': f'{vehicle_type.capitalize()} max range is {max_range} km. Destination is {distance_km:.0f} km away.'}

    # Speed stack for cost calculation
    from utilities.depot_utils import get_commander_and_stats
    commander_check, cmd_stats = get_commander_and_stats(user_id)
    if not cmd_stats:
        cmd_stats = {'exploration': 50, 'leadership': 50, 'strategy': 50, 'logistics': 50, 'charisma': 50}
    logistics_bonus = 1.0 + (cmd_stats.get('logistics', 50) / 100.0)
    scientist = get_user_scientist(user_id)
    sci_stats = scientist.get('stats', {}) if scientist else {}
    sci_nav_mult = 1.0 + (sci_stats.get('navigation', 0) / 150.0)
    # Drones fly — terrain doesn't slow them
    terrain_mult = 1.0
    if vehicle_type != 'drone':
        for terrain_type, info in TERRAIN_MODIFIERS.items():
            if terrain_type.lower() in destination_type.lower():
                terrain_mult = info.get('speed_mult', 1.0)
                break
    # Trail speed bonus for this route
    from utilities.postgres.trails import get_user_trail
    trail_data = get_user_trail(user_id, destination_name)
    launch_trail_mult = TRAIL_SPEED_MULTIPLIERS.get(trail_data['trail_level'], 1.0)

    # Check expedition capacity - 1 per vehicle type, capped by habitat module
    active_expeditions = get_user_active_expeditions(user_id)

    # Get expedition cap from habitat module (default 3 if no habitat built)
    from utilities.infrastructure_utils import get_user_infrastructure_effects
    infra_effects = get_user_infrastructure_effects(user_id)
    expedition_cap = infra_effects.get('expedition_capacity', 3)

    # Per-type constraint: only 1 of each vehicle type active at a time
    active_of_type = [e for e in active_expeditions if e.get('vehicle_type') == vehicle_type and e['status'] in ('traveling', 'recalled')]
    if active_of_type:
        dest = active_of_type[0]['destination_name']
        return {'success': False, 'error': f'Your {vehicle_type} is already on expedition to {dest}. Recall it first or wait for return.'}

    # Total cap: limited by habitat module capacity
    traveling = [e for e in active_expeditions if e['status'] in ('traveling', 'recalled')]
    if len(traveling) >= expedition_cap:
        return {'success': False, 'error': f'All {expedition_cap} expedition slots in use. Upgrade your Habitat Module for more slots.'}

    # Check for unclaimed discoveries blocking slots
    completed_with_unclaimed = [e for e in active_expeditions if e['status'] == 'complete' and e.get('unclaimed_count', 0) > 0]
    if completed_with_unclaimed and len(traveling) + len(completed_with_unclaimed) >= expedition_cap:
        destinations = ', '.join([e['destination_name'] for e in completed_with_unclaimed])
        return {'success': False, 'error': f'Claim your discoveries from {destinations} before starting a new expedition'}

    wallet = get_user_primary_sepolia_wallet(user_id)
    if not wallet:
        return {'success': False, 'error': 'No wallet found'}

    base_coords = get_or_set_user_mars_home(user_id)

    # Single query for both character_image and edited_image
    from utilities.postgres.assets import get_user_commander_images
    all_images = get_user_commander_images(user_id, limit=1)['all_images']

    if not all_images:
        return {'success': False, 'error': 'No commander found'}

    commander = all_images[0]

    # Use REAL commander stats (not random!) + EVA Suit bonuses
    from utilities.postgres.assets import get_commander_stats
    from utilities.shop_utils import get_effective_commander_stats
    base_commander_stats = get_commander_stats(user_id)
    if not base_commander_stats:
        base_commander_stats = generate_commander_stats()
    # Apply EVA Suit stat bonuses
    commander_stats = get_effective_commander_stats(user_id, base_commander_stats)

    expeditions_completed = get_user_completed_expeditions_count(user_id)
    user_expedition_count = expeditions_completed + 1

    # Get user's upgrade effects for cost calculation
    from utilities.upgrades_utils import get_user_upgrade_effects
    upgrade_effects = get_user_upgrade_effects(user_id)

    # Override with vehicle-specific speed × tech-only bonus
    # upgrade_effects['expedition_speed_mult'] is max(all vehicles) × tech — wrong for this vehicle.
    # We need THIS vehicle's speed × tech-only multiplier.
    from utilities.tech_utils import get_tech_effects
    tech_effects = get_tech_effects(user_id)
    tech_speed_mult = tech_effects.get('expedition_speed_mult', 1.0)
    upgrade_effects['expedition_speed_mult'] = vehicle_data['speed_mult'] * tech_speed_mult

    expedition_pricing = calculate_expedition_cost(
        distance_km=distance_km,
        destination_type=destination_type,
        commander_stats=commander_stats,
        user_expeditions_completed=expeditions_completed,
        base_coords=base_coords,
        upgrade_effects=upgrade_effects,
        scientist_nav_mult=sci_nav_mult,
        trail_speed_mult=launch_trail_mult
    )

    base_expedition_cost_eth = expedition_pricing['base_expedition_cost'] / 10000000

    # Bug #1290: preview uses calculate_cached_transaction_cost (DEFAULT_FEE_MULTIPLIER=1.0,
    # no blockchain call), but launch previously used miner.calculate_total_transaction_cost
    # (live Sepolia gas lookup). When Sepolia gas ticked up between preview and launch,
    # the fee_multiplier rose above 1.0 and total cost jumped ~47 shards — enough to push
    # players who could barely afford the preview cost into "Insufficient funds".
    # Fix: use the same cached pricing at launch so preview == launch cost, always.
    from utilities.depot_utils import calculate_cached_transaction_cost
    current_balance_eth = float(wallet.get('current_balance_eth', 0) or 0)
    total_pricing = calculate_cached_transaction_cost(
        base_expedition_cost_eth,
        user_balance_eth=current_balance_eth,
        message_length=250
    )
    total_pricing['success'] = True  # cached version always succeeds

    is_first_mission = expeditions_completed == 0
    user_balance_eth = total_pricing['current_balance_eth']

    if is_first_mission and user_balance_eth > 0:
        max_first_mission_cost_eth = user_balance_eth * 0.5

        if total_pricing['total_cost_eth'] > max_first_mission_cost_eth:
            remaining_for_base = max_first_mission_cost_eth - total_pricing['gas_cost_eth']

            if remaining_for_base > 0:
                max_base_cost_eth = remaining_for_base / (1 + (total_pricing['conditions']['fee_multiplier'] - 1.0))
                total_pricing = calculate_cached_transaction_cost(
                    max_base_cost_eth,
                    user_balance_eth=current_balance_eth,
                    message_length=250
                )
                total_pricing['success'] = True
                base_expedition_cost_eth = max_base_cost_eth
                logger.info(f"🎁 First mission cap applied: {total_pricing['total_cost_display']} (was {expedition_pricing['base_expedition_cost']})")
            else:
                logger.warning(f"⚠️ User balance too low for first mission cap ({user_balance_eth} ETH)")

    if not total_pricing['can_afford']:
        return {
            'success': False,
            'error': 'Insufficient Sepolia for expedition',
            'expedition_pricing': expedition_pricing,
            'total_pricing': total_pricing
        }

    travel_time_seconds = int(expedition_pricing['travel_hours'] * 3600)

    # --- Optimistic: create expedition + discoveries immediately ---
    try:
        # Use vehicle-specific cargo capacity + tech bonus + scientist engineering bonus
        cargo_capacity = vehicle_data.get('cargo', 5)
        cargo_tech_mult = upgrade_effects.get('cargo_capacity_mult', 1.0)
        cargo_capacity = int(cargo_capacity * cargo_tech_mult)
        engineering_stat = sci_stats.get('engineering', 0)
        cargo_capacity += engineering_stat // 10  # +1 per 10 engineering (max +5 at 50)

        # Optimistically deduct balance
        new_balance = total_pricing['current_balance_eth'] - total_pricing['total_cost_eth']
        update_sepolia_wallet_balance(wallet['wallet_address'], new_balance)

        expedition_id = create_expedition(
            user_id=user_id,
            commander_asset_id=commander['id'],
            destination_name=destination_name,
            destination_type=destination_type,
            destination_lat=destination_lat,
            destination_lon=destination_lon,
            distance_km=distance_km,
            fuel_cost_eth=total_pricing['total_cost_eth'],
            travel_time_seconds=travel_time_seconds,
            commander_stats=commander_stats,
            vehicle_type=vehicle_type,
            cargo_capacity=cargo_capacity,
            expedition_type=expedition_type,
            signal_site_id=signal_site_id
        )

        # signal_claim expeditions skip discovery generation entirely — they return 0 finds.
        # The reward is the founder/visitor slot, awarded at completion via _complete_signal_claim_expedition.
        if expedition_type != 'signal_claim':
            try:
                from utilities.discovery_utils import generate_expedition_discoveries
                from utilities.postgres.expeditions import get_total_discovery_count

                # Storage capacity check - counts ALL inventory (claimed + unclaimed, not analyzed)
                storage_capacity = upgrade_effects.get('storage_capacity', 300)
                current_total = get_total_discovery_count(user_id)
                remaining_capacity = max(0, storage_capacity - current_total)

                if remaining_capacity == 0:
                    logger.warning(f"⚠️ Storage full: {current_total}/{storage_capacity} discoveries. Limiting to minimum cargo.")
                    cargo_capacity = min(cargo_capacity, 3)  # Still get SOME finds
                elif remaining_capacity < cargo_capacity:
                    logger.info(f"📦 Storage nearly full: {current_total}/{storage_capacity}. Limiting cargo to {remaining_capacity}.")
                    cargo_capacity = max(3, remaining_capacity)  # Never below 3

                all_items = get_discovery_items_catalog()
                nearby_features = get_nearest_mars_landmarks(
                    base_coords['latitude'], base_coords['longitude'], limit=20
                )

                discoveries = generate_expedition_discoveries(
                    expedition_id=expedition_id,
                    expedition_data={
                        'distance_km': distance_km,
                        'commander_stats': commander_stats,
                        'scientist_stats': sci_stats,
                        'base_lat': base_coords['latitude'],
                        'base_lon': base_coords['longitude'],
                        'destination_lat': destination_lat,
                        'destination_lon': destination_lon,
                        'equipment_effects': upgrade_effects or {}
                    },
                    available_items=all_items,
                    nearby_features=nearby_features,
                    travel_time_seconds=travel_time_seconds,
                    user_expedition_count=user_expedition_count,
                    cargo_capacity=cargo_capacity
                )

                create_expedition_discoveries(discoveries)
                logger.info(f"✅ Created {len(discoveries)} discoveries for expedition {expedition_id}")
            except Exception as e:
                logger.error(f"Failed to generate discoveries: {e}")

        # Update activity timestamp for ARIA photo generation
        from utilities.postgres.users import update_user_activity
        update_user_activity(user_id)

        # --- Background thread: blockchain tx + depot transaction ---
        import threading
        def do_blockchain_tx():
            try:
                miner = MarsAsteroidMiner()
                if not miner.connect():
                    logger.error(f"❌ Blockchain connect failed for expedition {expedition_id}")
                    return
                tx_result = miner.return_to_hub_with_reconciliation(
                    from_address=wallet['wallet_address'],
                    from_private_key=wallet['wallet_private_key'],
                    estimated_total_eth=total_pricing['total_cost_eth'],
                    base_cost_eth=base_expedition_cost_eth,
                    reason=destination_name
                )
                if tx_result['success']:
                    create_depot_transaction(
                        user_id=user_id,
                        wallet_address=wallet['wallet_address'],
                        purchase_type='expedition_launch',
                        amount_eth=total_pricing['total_cost_eth'],
                        tx_hash=tx_result['tx_hash'],
                        etherscan_url=tx_result['etherscan_url'],
                        item_details={
                            'destination': destination_name,
                            'distance_km': distance_km,
                            'reconciliation_message': tx_result.get('reconciliation_message'),
                            'atmospheric_difference': tx_result.get('atmospheric_difference_display'),
                            'actual_ops_cost': tx_result.get('actual_gas_cost_display'),
                            'first_mission_cap_applied': is_first_mission
                        }
                    )
                    logger.info(f"✅ Blockchain tx confirmed for expedition {expedition_id}: {tx_result['tx_hash']}")
                else:
                    logger.error(f"❌ Blockchain tx failed for expedition {expedition_id}: {tx_result}")
            except Exception as e:
                logger.error(f"❌ Background blockchain tx error for expedition {expedition_id}: {e}")

        thread = threading.Thread(target=do_blockchain_tx)
        thread.start()

        # --- Return immediately ---
        from utilities.depot_utils import eth_to_display
        new_balance_display = eth_to_display(new_balance)

        now = datetime.now()
        arrives_at = now + timedelta(seconds=travel_time_seconds)
        return_arrives_at = arrives_at + timedelta(seconds=travel_time_seconds)

        return {
            'success': True,
            'expedition_id': expedition_id,
            'new_balance': new_balance_display,
            'pending': True,
            'travel_time_seconds': travel_time_seconds,
            'arrives_at': arrives_at.isoformat() + 'Z',
            'return_arrives_at': return_arrives_at.isoformat() + 'Z',
            'total_round_trip_seconds': travel_time_seconds * 2,
            'vehicle_type': vehicle_type,
            'cargo_capacity': cargo_capacity,
            'first_mission_discount': is_first_mission
        }

    except Exception as e:
        logger.error(f"Expedition launch failed: {e}")
        return {'success': False, 'error': str(e)}


def recall_expedition(user_id: int, expedition_id: int) -> dict:
    """
    Recall a vehicle mid-expedition. Vehicle turns around and heads back.
    Return speed uses full speed stack (vehicle × logistics × scientist × trail × terrain).
    No discoveries generated for recalled expeditions.
    """
    from utilities.postgres.expeditions import get_expedition_by_id
    from utilities.postgres.core import db_cursor
    from utilities.postgres.users import get_user_scientist
    from utilities.upgrades_utils import get_vehicle_for_expedition

    expedition = get_expedition_by_id(expedition_id)
    if not expedition:
        return {'success': False, 'error': 'Expedition not found'}

    if expedition['user_id'] != user_id:
        return {'success': False, 'error': 'Unauthorized'}

    if expedition['status'] != 'traveling':
        return {'success': False, 'error': 'Can only recall active expeditions'}

    # Phase 2.3b: signal_claim trips can't fail (Luke: "why would it? so you can just go back and lose 5 days?").
    if expedition.get('expedition_type') == 'signal_claim':
        return {'success': False, 'error': 'Signal claim expeditions cannot be recalled — the cinematic awaits.'}

    now = datetime.now()
    arrives_at = expedition['arrives_at']
    departed_at = expedition['departed_at']

    # Can only recall during outbound leg
    if now >= arrives_at:
        return {'success': False, 'error': 'Vehicle already at destination or returning'}

    # Calculate how far the vehicle has traveled
    total_outbound_seconds = (arrives_at - departed_at).total_seconds()
    elapsed_seconds = (now - departed_at).total_seconds()
    progress = min(max(elapsed_seconds / total_outbound_seconds, 0.0), 1.0)
    distance_covered_km = float(expedition['distance_km']) * progress  # Convert Decimal to float

    # Calculate return speed using speed stack
    vehicle_type = expedition.get('vehicle_type', 'rover')
    vehicle_data = get_vehicle_for_expedition(user_id, vehicle_type)
    vehicle_speed_mult = vehicle_data['speed_mult'] if vehicle_data else 1.25

    # Captain logistics bonus
    logistics = expedition.get('commander_logistics', 50)
    logistics_speed_bonus = 1.0 + (logistics / 100.0)

    # Scientist navigation bonus
    scientist = get_user_scientist(user_id)
    sci_stats = scientist.get('stats', {}) if scientist else {}
    scientist_nav_mult = 1.0 + (sci_stats.get('navigation', 0) / 150.0)

    # Trail speed bonus for this route
    from utilities.postgres.trails import get_user_trail
    trail_data = get_user_trail(user_id, expedition['destination_name'])
    trail_speed_mult = TRAIL_SPEED_MULTIPLIERS.get(trail_data['trail_level'], 1.0)

    # Terrain speed modifier (drones fly — terrain doesn't slow them)
    dest_type = expedition.get('destination_type', '')
    terrain_speed_mult = 1.0
    if expedition.get('vehicle_type') != 'drone':
        for terrain_type, info in TERRAIN_MODIFIERS.items():
            if terrain_type.lower() in dest_type.lower():
                terrain_speed_mult = info.get('speed_mult', 1.0)
                break

    total_speed_mult = vehicle_speed_mult * logistics_speed_bonus * scientist_nav_mult * trail_speed_mult * terrain_speed_mult
    effective_speed = BASE_SPEED_KM_PER_HOUR * total_speed_mult
    return_hours = distance_covered_km / effective_speed if effective_speed > 0 else distance_covered_km / BASE_SPEED_KM_PER_HOUR
    return_seconds = return_hours * 3600

    new_return_arrives_at = now + timedelta(seconds=return_seconds)

    # Update expedition: status='recalled', timestamps adjusted
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE pilgrim.expeditions
                SET status = 'recalled', arrives_at = %s, return_arrives_at = %s
                WHERE id = %s AND user_id = %s
            """, (now, new_return_arrives_at, expedition_id, user_id))

            # Delete pre-generated discoveries (vehicle didn't reach destination)
            cur.execute("""
                DELETE FROM pilgrim.expedition_discoveries WHERE expedition_id = %s
            """, (expedition_id,))

        logger.info(f"🔄 Recalled expedition {expedition_id}: {progress*100:.0f}% complete, "
                    f"{distance_covered_km:.1f}km covered, returning in {return_seconds:.0f}s")

        return {
            'success': True,
            'message': f'{vehicle_type.capitalize()} recalled from {expedition["destination_name"]}',
            'distance_covered_km': round(distance_covered_km, 1),
            'progress_percent': round(progress * 100, 1),
            'return_seconds': int(return_seconds),
            'return_arrives_at': new_return_arrives_at.isoformat() + 'Z',
            'speed_mult': round(total_speed_mult, 2)
        }
    except Exception as e:
        logger.error(f"Failed to recall expedition {expedition_id}: {e}")
        return {'success': False, 'error': 'Database error during recall'}


def complete_expedition_if_ready(expedition_id: int, user_id: int) -> dict:
    """
    Check if expedition is complete and process rewards if ready
    Returns status with completion data if finished
    """
    from utilities.postgres.expeditions import get_expedition_by_id, update_expedition_complete, record_landmark_discovery
    from utilities.postgres.wallets import get_user_primary_sepolia_wallet
    from utilities.postgres.shop import create_depot_transaction
    from utilities.sepolia_utils import MarsAsteroidMiner
    from utilities.depot_utils import eth_to_display
    from utilities.discovery_utils import calculate_expedition_discovery

    expedition = get_expedition_by_id(expedition_id)
    if not expedition:
        return {'success': False, 'error': 'Expedition not found'}

    if expedition['user_id'] != user_id:
        return {'success': False, 'error': 'Unauthorized'}

    if expedition['status'] == 'complete':
        return {
            'success': True,
            'complete': True,
            'discovery_type': expedition['discovery_type'],
            'sepolia_earned': eth_to_display(expedition['sepolia_earned']),
            'discovery_message': expedition['discovery_message']
        }

    now = datetime.now()  # Use local time to match how arrives_at was stored
    arrives_at = expedition['arrives_at']
    return_arrives_at = expedition.get('return_arrives_at') or arrives_at  # Fallback for old expeditions

    # Determine expedition phase
    if now < arrives_at:
        # Outbound: traveling to destination
        remaining = (arrives_at - now).total_seconds()
        return {
            'success': True,
            'complete': False,
            'phase': 'outbound',
            'remaining_seconds': remaining,
            'arrives_at': arrives_at.isoformat() + 'Z',
            'return_arrives_at': return_arrives_at.isoformat() + 'Z' if return_arrives_at else None
        }
    elif now < return_arrives_at:
        # At destination or returning: can view discoveries but can't extract yet
        phase = 'recalled' if expedition['status'] == 'recalled' else 'returning'
        remaining = (return_arrives_at - now).total_seconds()
        return {
            'success': True,
            'complete': False,
            'phase': phase,
            'remaining_seconds': remaining,
            'arrives_at': arrives_at.isoformat() + 'Z',
            'return_arrives_at': return_arrives_at.isoformat() + 'Z'
        }

    # Recalled expeditions: no discoveries, just free the vehicle
    if expedition['status'] == 'recalled':
        update_expedition_complete(
            expedition_id, 'recalled', 0.0,
            f'Vehicle recalled from {expedition["destination_name"]} - no discoveries'
        )
        return {
            'success': True,
            'complete': True,
            'discovery_type': 'recalled',
            'sepolia_earned': 0,
            'discovery_message': f'Vehicle recalled from {expedition["destination_name"]}'
        }

    # Phase 2.3b: signal_claim expeditions take a dedicated path — no random discovery roll,
    # no SV grant via the standard formula, no trail increment, no Echo-Site spawn, no ARIA
    # bond check. They run claim/visit at the site and stash the cinematic payload for
    # before_request to redirect on the next page load.
    if expedition.get('expedition_type') == 'signal_claim':
        return _complete_signal_claim_expedition(expedition, user_id)

    discovery = calculate_expedition_discovery(expedition)

    # LOCAL DB FIRST: credit shards immediately, blockchain in background
    # (Same pattern as claim_accumulated_income — shards can never be lost)
    wallet = get_user_primary_sepolia_wallet(user_id)
    if wallet:
        # 1. Credit balance atomically in DB — this is the source of truth
        from utilities.postgres.core import db_cursor
        with db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE pilgrim.sepolia_assets
                SET current_balance_eth = current_balance_eth + %s,
                    last_balance_check = NOW()
                WHERE wallet_address = %s
            """, (discovery['sepolia_earned'], wallet['wallet_address']))

        # 2. Blockchain tx in background — best effort, doesn't block reward
        try:
            miner = MarsAsteroidMiner()
            if miner.connect():
                reward_result = miner.send_sepolia_reward_fast(
                    wallet['wallet_address'],
                    discovery['sepolia_earned'],
                    discovery['message'],
                    context="expedition_discovery"
                )

                if reward_result['success']:
                    create_depot_transaction(
                        user_id=user_id,
                        wallet_address=wallet['wallet_address'],
                        purchase_type='expedition_discovery',
                        amount_eth=discovery['sepolia_earned'],
                        tx_hash=reward_result['tx_hash'],
                        etherscan_url=reward_result['etherscan_url'],
                        item_details={
                            'destination': expedition['destination_name'],
                            'expedition_id': expedition_id,
                            'discovery_type': discovery['discovery_type'],
                            'discovery_quality': discovery['discovery_quality'],
                            'breakdown': discovery['breakdown']
                        }
                    )
        except Exception as e:
            logger.error(f"Failed to send expedition reward: {e}")

    update_expedition_complete(
        expedition_id,
        discovery['discovery_type'],
        discovery['sepolia_earned'],
        discovery['message']
    )

    record_landmark_discovery(
        user_id=user_id,
        landmark_name=expedition['destination_name'],
        landmark_type=expedition['destination_type'],
        latitude=expedition['destination_lat'],
        longitude=expedition['destination_lon'],
        distance_km=expedition['distance_km'],
        sepolia_earned=discovery['sepolia_earned'],
        expedition_id=expedition_id
    )

    # ========================================================================
    # TRAIL NETWORK (v3 — bug #1414): expeditions no longer mutate trails.
    # Trails are 4 deterministic cardinal chains per captain, built by crew /
    # drones / ARIA. Expedition arrival is a no-op for the trail system.
    # ========================================================================

    # ========================================================================
    # SV ECONOMY: Award Science Value on expedition completion
    # Per brainstorm: 100-200 short, 200-500 medium, 500-1000 long, 1000-2000 epic
    # Formula: base SV scales with distance, Dr. Bo analyzes field data on return
    # ========================================================================
    try:
        from utilities.postgres.users import add_passive_sv
        distance = float(expedition.get('distance_km', 0))
        if distance <= 200:
            expedition_sv = 100 + int(distance * 0.5)  # 100-200 SV
        elif distance <= 500:
            expedition_sv = 200 + int((distance - 200) * 1.0)  # 200-500 SV
        elif distance <= 1500:
            expedition_sv = 500 + int((distance - 500) * 0.5)  # 500-1000 SV
        else:
            expedition_sv = 1000 + int((distance - 1500) * 0.4)  # 1000-2000+ SV
        expedition_sv = max(100, min(expedition_sv, 2000))  # Clamp to 100-2000
        add_passive_sv(user_id, expedition_sv)
        logger.info(f"🔬 Expedition SV: user {user_id} earned {expedition_sv} SV from {distance:.0f} km expedition to {expedition['destination_name']}")
    except Exception as e:
        logger.error(f"Failed to award expedition SV: {e}")

    # ========================================================================
    # SHARD NETWORK: Check for Origin Site proximity and roll for Echo Site
    # ========================================================================
    # Fetch Base coords so signal detection can evaluate the full path, not just destination
    from utilities.postgres.map import get_or_set_user_mars_home
    _base = get_or_set_user_mars_home(user_id)
    signal_events = check_signal_events(
        user_id=user_id,
        expedition_id=expedition_id,
        lat=expedition['destination_lat'],
        lon=expedition['destination_lon'],
        landmark_name=expedition['destination_name'],
        base_lat=float(_base['latitude']),
        base_lon=float(_base['longitude'])
    )

    # ========================================================================
    # ARIA BONDS: Check if another player has visited this landmark
    # ========================================================================
    aria_fragment = None
    try:
        from utilities.aria.bonds import check_for_aria_bond
        aria_fragment = check_for_aria_bond(user_id, expedition['destination_name'])
        if aria_fragment:
            logger.info(f"⚡ ARIA fragment created for user {user_id} at {expedition['destination_name']}")
    except Exception as e:
        logger.error(f"ARIA bond check failed: {e}")

    # ========================================================================
    # PHASE 2.3c: PUZZLE FRAGMENTS — roll for a Signal puzzle fragment drop.
    # Each carries an ARIA whisper that fires the moment it's picked up.
    # Skipped for signal_claim (their cinematic IS the discovery moment).
    # ========================================================================
    puzzle_fragment = None
    try:
        from utilities.signal.puzzle_fragments import maybe_drop_fragment
        puzzle_fragment = maybe_drop_fragment(user_id, expedition_id)
    except Exception as e:
        logger.error(f"Puzzle fragment roll failed: {e}")

    return {
        'success': True,
        'complete': True,
        'discovery_type': discovery['discovery_type'],
        'sepolia_earned': eth_to_display(discovery['sepolia_earned']),
        'discovery_message': discovery['message'],
        'signal_events': signal_events,  # Origin/Echo site discoveries
        'aria_fragment': aria_fragment,  # Entangled crystal fragment (ARIA bond)
        'puzzle_fragment': puzzle_fragment,  # Phase 2.3c: Signal puzzle fragment + whisper
    }


def _complete_signal_claim_expedition(expedition: dict, user_id: int) -> dict:
    """Phase 2.3b: complete a signal_claim expedition. NO-FAIL.

    Tries to claim as Founder; if site is already claimed, falls back to a visitor
    record. Records cinematic_payload on the expedition so the cinematic page can
    render even hours later, and marks the expedition complete. before_request
    will redirect the captain to /signal-claim/<id> on the next page load.
    """
    from utilities.postgres.expeditions import (
        update_expedition_complete,
        write_signal_cinematic_payload,
    )
    from utilities.signal.handlers import (
        handle_origin_site_claim,
        handle_origin_site_visit,
    )

    expedition_id = expedition['id']
    site_id = expedition.get('signal_site_id')
    destination = expedition.get('destination_name') or 'Unknown Site'

    payload = {'site_id': site_id, 'expedition_id': expedition_id, 'tier': None, 'outcome': None}

    if not site_id:
        # Defensive: should never happen — launch validation requires signal_site_id.
        payload['outcome'] = 'error'
        payload['error'] = 'Signal claim expedition missing signal_site_id'
        write_signal_cinematic_payload(expedition_id, payload)
        update_expedition_complete(
            expedition_id, 'signal_claim', 0.0,
            f'Signal claim to {destination} completed (data error)'
        )
        return {'success': True, 'complete': True, 'discovery_type': 'signal_claim',
                'sepolia_earned': 0, 'discovery_message': payload['error']}

    # Try claim first — if the site is unclaimed, this captain becomes Founder.
    claim_result = handle_origin_site_claim(user_id, site_id, session=None)

    if claim_result.get('success'):
        payload['outcome'] = 'founder'
        payload['tier'] = 'legendary'
        payload['result'] = claim_result
    else:
        # Already claimed (or other error) — fall back to a visit. No-fail: even if
        # visit also returns success=False (e.g., already visited this site), we still
        # mark the expedition complete with an "already_visited" cinematic variant.
        visit_result = handle_origin_site_visit(user_id, site_id, session=None)
        if visit_result.get('success'):
            payload['outcome'] = 'visitor'
            payload['tier'] = visit_result.get('claim_tier') or visit_result.get('tier')
            payload['result'] = visit_result
        else:
            payload['outcome'] = 'already_visited'
            payload['result'] = {'claim_error': claim_result.get('error'),
                                 'visit_error': visit_result.get('error')}

    write_signal_cinematic_payload(expedition_id, payload)

    update_expedition_complete(
        expedition_id, 'signal_claim', 0.0,
        f'Signal claim to {destination} ({payload["outcome"]})'
    )

    logger.info(f"📡 Signal claim complete: expedition={expedition_id} user={user_id} "
                f"site={site_id} outcome={payload['outcome']}")

    return {
        'success': True,
        'complete': True,
        'discovery_type': 'signal_claim',
        'sepolia_earned': 0,
        'discovery_message': f'Signal claim complete — cinematic awaits.',
        'signal_claim_pending_cinematic': True,
    }


def get_expedition_discovery_progress(expedition_id: int, user_id: int) -> dict:
    """
    Get expedition discoveries with current progress unlocking
    FIXED: Ensures discoveries persist after expedition completion and shows claim status
    """
    from utilities.postgres.expeditions import get_expedition_by_id, get_expedition_discoveries, unlock_discoveries_by_distance

    expedition = get_expedition_by_id(expedition_id)
    if not expedition or expedition['user_id'] != user_id:
        return {'success': False, 'error': 'Unauthorized'}

    # For completed expeditions, unlock ALL discoveries and show full distance
    if expedition['status'] == 'complete':
        current_distance = float(expedition['distance_km'])
        # Ensure all discoveries are unlocked for completed expeditions
        unlock_discoveries_by_distance(expedition_id, current_distance)
        logger.info(f"✅ Completed expedition {expedition_id}: unlocked all discoveries at {current_distance} km")
    else:
        elapsed = (datetime.now() - expedition['departed_at']).total_seconds()  # Use local time to match stored timestamps
        return_arrives_at = expedition.get('return_arrives_at') or expedition['arrives_at']
        total_time = (return_arrives_at - expedition['departed_at']).total_seconds()
        progress = min(1.0, elapsed / total_time)
        current_distance = float(expedition['distance_km']) * progress
        unlock_discoveries_by_distance(expedition_id, current_distance)
        logger.debug(f"⏳ Active expedition {expedition_id}: {progress:.1%} complete, {current_distance:.1f}/{expedition['distance_km']} km")

    all_discoveries = get_expedition_discoveries(expedition_id, unlocked_only=False)
    unlocked = [d for d in all_discoveries if d['unlocked_at']]
    locked = [d for d in all_discoveries if not d['unlocked_at']]

    # For completed expeditions, include claim status and make sure discoveries persist
    unclaimed_count = 0
    if expedition['status'] == 'complete':
        for discovery in unlocked:
            discovery['can_claim'] = not discovery.get('claimed_by_user', False)
            if discovery['can_claim']:
                unclaimed_count += 1

        logger.info(f"🏆 Completed expedition {expedition_id}: {len(unlocked)} unlocked discoveries, {unclaimed_count} unclaimed")

    return {
        'success': True,
        'expedition_status': expedition['status'],
        'expedition_complete': expedition['status'] == 'complete',
        'current_distance_km': round(current_distance, 2),
        'total_distance_km': float(expedition['distance_km']),
        'unlocked_count': len(unlocked),
        'total_count': len(all_discoveries),
        'unlocked_discoveries': unlocked,
        'locked_discoveries': locked,
        'unclaimed_count': unclaimed_count,
        'has_claimable_discoveries': unclaimed_count > 0,
        'fuel_cost_display': round(float(expedition.get('fuel_cost_eth', 0) or 0) * 10000000, 1),
        'destination_name': expedition.get('destination_name', 'Unknown')
    }


def claim_all_discoveries(user_id, expedition_id=None):
    """Claim all unlocked discoveries for user (optionally for specific expedition).
    Uses batch SQL update for efficiency - handles 1000s of discoveries in one query.
    """
    from utilities.postgres.expeditions import claim_all_pending_discoveries, get_expedition_by_id

    # Verify expedition ownership and completion if specified
    if expedition_id:
        expedition = get_expedition_by_id(expedition_id)
        if not expedition or expedition['user_id'] != user_id:
            return {'success': False, 'error': 'Unauthorized'}
        if expedition['status'] not in ('complete', 'recalled'):
            return {'success': False, 'error': 'Expedition still in progress'}

    # Use batch claim (single SQL UPDATE instead of loop)
    result = claim_all_pending_discoveries(user_id, expedition_id)

    if result['claimed_count'] == 0:
        return {'success': False, 'error': 'No discoveries to claim'}

    # Claim-all from banner is an implicit acknowledgement — free the slot.
    # Without this, completed expeditions with notified_at=NULL linger in the
    # active list for up to 7 days and block new launches (bug #1332).
    if expedition_id and expedition.get('status') == 'complete' and not expedition.get('notified_at'):
        try:
            from utilities.postgres.core import db_cursor
            with db_cursor(commit=True) as cur:
                cur.execute("UPDATE pilgrim.expeditions SET notified_at = NOW() WHERE id = %s", (expedition_id,))
        except Exception as e:
            logger.warning(f"Failed to mark expedition {expedition_id} notified after claim: {e}")

    return {
        'success': True,
        'claimed_count': result['claimed_count'],
        'total_value': result['total_value'],
        'message': f"Claimed {result['claimed_count']} discoveries"
    }


def get_discovery_progress_formatted(expedition_id, user_id):
    """Get expedition discovery progress with frontend formatting."""
    import json as json_module

    result = get_expedition_discovery_progress(expedition_id, user_id)
    if not result.get('success'):
        return result

    for discovery in result.get('unlocked_discoveries', []):
        discovery['can_claim'] = not discovery.get('claimed_by_user', False)
        discovery['claimed_by_user'] = discovery.get('claimed_by_user', False)
        if isinstance(discovery.get('found_at_coordinates'), str):
            try:
                discovery['found_at_coordinates'] = json_module.loads(discovery['found_at_coordinates'])
            except:
                discovery['found_at_coordinates'] = {'lat': 0, 'lon': 0}

    return result


def start_expedition_from_request(user_id, data, session=None):
    """Start expedition from request data."""
    result = launch_expedition(
        user_id=user_id,
        destination_name=data.get('destination_name'),
        destination_type=data.get('destination_type'),
        destination_lat=data.get('latitude'),
        destination_lon=data.get('longitude'),
        distance_km=data.get('distance_km'),
        vehicle_type=data.get('vehicle_type', 'rover'),
        expedition_type=data.get('expedition_type', 'standard'),
        signal_site_id=data.get('signal_site_id'),
    )

    # Invalidate cached balance since we spent Sepolia
    if result.get('success') and session is not None:
        from utilities.depot_utils import invalidate_balance_cache
        invalidate_balance_cache(session)

    return result


def check_signal_events(
    user_id: int,
    expedition_id: int,
    lat: float,
    lon: float,
    landmark_name: str = None,
    base_lat: float = None,
    base_lon: float = None
) -> Dict[str, Any]:
    """
    Check for Shard Network events after expedition completion:
    1. Check proximity to unclaimed Origin Sites — Phase 2: path-based closest-approach
       along the full Base → Destination route, using per-site unlock_radius_km
    2. Roll for Echo Site spawn (2% base + pity timer)

    Returns dict with any discovered/spawned sites.
    """
    from utilities.signal_utils import (
        check_origin_site_proximity,
        maybe_spawn_echo_site
    )

    events = {
        'origin_site_nearby': None,
        'echo_site_spawned': None
    }

    # Fetch base coords if caller didn't supply them (backward compat)
    if base_lat is None or base_lon is None:
        from utilities.postgres.map import get_or_set_user_mars_home
        base_coords = get_or_set_user_mars_home(user_id)
        base_lat = float(base_coords['latitude'])
        base_lon = float(base_coords['longitude'])

    try:
        # 1. Check for Origin Site proximity along the entire expedition path
        origin_site = check_origin_site_proximity(base_lat, base_lon, lat, lon)
        if origin_site:
            events['origin_site_nearby'] = {
                'id': origin_site['id'],
                'site_code': origin_site['site_code'],
                'mission_name': origin_site['mission_name'],
                'distance_km': origin_site.get('distance_km', 0),
                'memory_preview': origin_site['memory_text'][:100] + '...' if len(origin_site['memory_text']) > 100 else origin_site['memory_text']
            }
            logger.info(f"🎯 Origin Site {origin_site['site_code']} detected near expedition to {landmark_name}!")

        # 2. Roll for Echo Site spawn (2% base + pity timer up to guaranteed)
        echo_site = maybe_spawn_echo_site(
            user_id=user_id,
            expedition_lat=lat,
            expedition_lon=lon,
            expedition_id=expedition_id,
            nearby_landmark=landmark_name
        )
        if echo_site:
            events['echo_site_spawned'] = {
                'id': echo_site['id'],
                'site_code': echo_site['site_code'],
                'latitude': echo_site['latitude'],
                'longitude': echo_site['longitude'],
                'memory_preview': echo_site['memory_text'][:100] + '...' if len(echo_site['memory_text']) > 100 else echo_site['memory_text']
            }
            logger.info(f"✨ Echo Site {echo_site['site_code']} spawned near {landmark_name}!")

    except Exception as e:
        logger.error(f"Error checking signal events: {e}")

    return events
