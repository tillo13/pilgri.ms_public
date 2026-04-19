"""Accumulated income: calculation, claim, science value recording."""
import logging
import threading
from datetime import datetime

from config_infrastructure import INFRASTRUCTURE_CATALOG
from utilities.postgres.shop import (
    get_user_infrastructure,
    create_depot_transaction,
)
from utilities.postgres.wallets import get_user_primary_sepolia_wallet, update_sepolia_wallet_balance
from utilities.postgres.core import db_cursor
from utilities.postgres.map import get_or_set_user_mars_home
from utilities.sepolia_utils import MarsAsteroidMiner

from utilities.infrastructure.environment import (
    ACCUMULATION_CAP_HOURS,
    calculate_daylight_fraction,
    calculate_generation_rate,
    _get_mars_environment_multiplier,
    _get_mars_environment_factors,
)

logger = logging.getLogger(__name__)


def user_has_maintenance_drone(user_id: int) -> bool:
    """Check if user has dust immunity from the Maintenance Drone path (Lv3 = Dust Guard)."""
    from utilities.upgrades_utils import get_user_upgrade_level
    return get_user_upgrade_level(user_id, 'maintenance', 'maintenance') >= 3


def calculate_accumulated_income(user_id):
    """
    Calculate total accumulated Sepolia from all active generators.

    ACCUMULATION CAP (CORE MECHANIC - prevents infinite stacking):
    - ALL generators accumulate up to ACCUMULATION_CAP_HOURS (7 days) maximum
    - After 7 days, generation STOPS completely - no more shards accumulate
    - User must claim to reset the timer and resume generation
    """
    from utilities.postgres.shop import ensure_dust_covered_column, set_infrastructure_dust_covered
    ensure_dust_covered_column()

    structures = get_user_infrastructure(user_id)
    coords = get_or_set_user_mars_home(user_id)
    total_accumulated = 0.0
    total_all_time = 0.0
    details = []
    dust_covered_structures = []
    structures_at_cap = []

    try:
        from utilities.upgrades_utils import get_user_upgrade_effects
        from utilities.shop_utils import get_passive_income_source
        user_effects = get_user_upgrade_effects(user_id)
        passive_income_source = get_passive_income_source(user_id)
    except Exception as e:
        logger.warning(f"Could not get user upgrade effects: {e}")
        user_effects = {}
        passive_income_source = None

    tech_passive_mult = 1.0
    try:
        from utilities.tech_utils import get_tech_effects
        tech_effects = get_tech_effects(user_id)
        tech_passive_mult = tech_effects.get('passive_income_mult', 1.0)
    except Exception:
        pass

    passive_income_mult = user_effects.get('passive_income_mult', 1.0)
    passive_income_base = user_effects.get('passive_income_base', 0)
    all_generation_mult = user_effects.get('all_generation_mult', 1.0)

    from utilities.upgrades_utils import get_all_infrastructure_levels
    all_levels = get_all_infrastructure_levels(user_id, structures=structures)

    has_battery = any(s['structure_type'] == 'battery_storage' and s['status'] == 'active' for s in structures)
    night_multiplier = 0.5 if has_battery else 0.0

    has_maintenance_drone = user_has_maintenance_drone(user_id)

    for structure in structures:
        if structure['status'] != 'active' or not structure['generates_resource'] or structure['generates_resource'] != 'sepolia':
            continue

        total_all_time += float(structure.get('total_generated', 0))

        is_dust_covered = structure.get('dust_covered', False)

        last_payout = structure.get('last_payout_at') or structure['build_completed_at'] or structure['created_at']
        hours_elapsed = (datetime.utcnow() - last_payout).total_seconds() / 3600

        building_level = all_levels.get(structure['structure_type'], 1)
        if building_level < 1:
            building_level = 1

        db_rate = float(structure['generation_rate'])
        catalog_def = INFRASTRUCTURE_CATALOG.get(structure['structure_type'], {})
        level_data = catalog_def.get('levels', {}).get(building_level, {})
        catalog_rate = float(level_data.get('generation_rate', 0.0))

        if structure['structure_type'] == 'solar_array':
            hourly_rate = calculate_generation_rate('solar_array', coords['latitude'], coords['longitude'], building_level)
        else:
            hourly_rate = catalog_rate if catalog_rate > 0 else db_rate

        capped_hours = min(hours_elapsed, ACCUMULATION_CAP_HOURS)
        at_cap = hours_elapsed >= ACCUMULATION_CAP_HOURS

        if at_cap:
            structures_at_cap.append(structure['structure_type'])

        if structure['structure_type'] == 'solar_array':
            day_fraction, night_fraction = calculate_daylight_fraction(capped_hours, coords['longitude'])
            env_mult = _get_mars_environment_multiplier(coords['latitude'])
            if has_maintenance_drone:
                factors = _get_mars_environment_factors(coords['latitude'])
                dust = factors['dust']
                improved_dust = dust + (1.0 - dust) * 0.5
                env_mult = round(improved_dust * factors['temperature'], 3)
            effective_rate = hourly_rate * (day_fraction + night_fraction * night_multiplier) * env_mult
            accumulated = effective_rate * capped_hours

            if at_cap and not has_maintenance_drone and not is_dust_covered:
                set_infrastructure_dust_covered(user_id, structure['structure_type'], True)
                is_dust_covered = True

            if is_dust_covered:
                dust_covered_structures.append(structure['structure_type'])

            day_night_info = {
                'day_fraction': round(day_fraction, 2),
                'night_fraction': round(night_fraction, 2),
                'has_battery': has_battery,
                'effective_multiplier': round((day_fraction + night_fraction * night_multiplier) * env_mult, 2),
                'env_multiplier': round(env_mult, 2),
            }
        else:
            accumulated = hourly_rate * capped_hours
            day_night_info = None

        total_accumulated += accumulated

        detail = {
            'structure_type': structure['structure_type'],
            'structure_name': structure['structure_name'],
            'building_level': building_level,
            'hourly_rate': hourly_rate,
            'hours_elapsed': hours_elapsed,
            'capped_hours': capped_hours,
            'accumulated': accumulated,
            'last_payout': last_payout,
            'dust_covered': is_dust_covered,
            'at_cap': at_cap,
            'cap_reached_hours_ago': max(0, hours_elapsed - ACCUMULATION_CAP_HOURS) if at_cap else 0
        }
        if day_night_info:
            detail['day_night'] = day_night_info
        details.append(detail)

    base_accumulated = total_accumulated

    if passive_income_mult > 1.0:
        total_accumulated *= passive_income_mult

    if all_generation_mult > 1.0:
        total_accumulated *= all_generation_mult

    if passive_income_base > 0 and details:
        avg_capped_hours = sum(d['capped_hours'] for d in details) / len(details) if details else ACCUMULATION_CAP_HOURS
        drone_income = passive_income_base * avg_capped_hours
        total_accumulated += drone_income

    scientist_shard_mult = 1.0
    try:
        from utilities.postgres.users import get_user_scientist
        scientist = get_user_scientist(user_id)
        if scientist:
            analysis_stat = scientist.get('stats', {}).get('analysis', 0)
            scientist_shard_mult = 1.0 + (min(analysis_stat, 50) * 0.02)
            if scientist_shard_mult > 1.0:
                total_accumulated *= scientist_shard_mult
    except Exception:
        pass

    # Signal Network passive bonus — per-claim hourly shards + SV, stacks across sites.
    # Luke's hard requirement: Base homepage must reflect Signal income.
    signal_bonus = {'shards_per_hour': 0.0, 'sv_per_hour': 0.0, 'sites_count': 0, 'per_tier': {}}
    signal_shards_accumulated = 0.0
    try:
        from utilities.signal.rewards import get_user_signal_income_bonuses
        signal_bonus = get_user_signal_income_bonuses(user_id)
        if signal_bonus['shards_per_hour'] > 0 and details:
            avg_capped_hours = sum(d['capped_hours'] for d in details) / len(details)
            signal_shards_accumulated = signal_bonus['shards_per_hour'] * avg_capped_hours
            total_accumulated += signal_shards_accumulated
    except Exception as e:
        logger.warning(f"Signal income bonus calc failed for user {user_id}: {e}")

    base_hourly_rate = sum(d['hourly_rate'] for d in details)

    generating_details = [d for d in details if d['hourly_rate'] > 0]
    avg_hours = sum(d['capped_hours'] for d in generating_details) / len(generating_details) if generating_details else 0

    actual_avg_rate = round(total_accumulated / avg_hours, 1) if avg_hours > 0 else 0

    day_night_efficiency = 1.0
    mars_env_multiplier = 1.0
    mars_env_factors = None
    if details:
        solar_details = [d for d in details if d.get('day_night')]
        if solar_details:
            mars_env_multiplier = solar_details[0]['day_night'].get('env_multiplier', 1.0)
            env_m = mars_env_multiplier if mars_env_multiplier > 0 else 1.0
            avg_effective = sum(d['day_night']['effective_multiplier'] for d in solar_details) / len(solar_details)
            day_night_efficiency = round(avg_effective / env_m, 3) if env_m > 0 else avg_effective
            mars_env_factors = _get_mars_environment_factors(coords['latitude'])

    effective_base_rate = round(base_hourly_rate * day_night_efficiency * mars_env_multiplier, 1)

    theoretical_max_rate = round(((base_hourly_rate * passive_income_mult * all_generation_mult) + passive_income_base) * scientist_shard_mult, 1)

    if actual_avg_rate > 0:
        effective_rate = actual_avg_rate
    else:
        effective_rate = round(
            ((effective_base_rate * passive_income_mult * all_generation_mult) + passive_income_base) * scientist_shard_mult,
            1
        )

    generators_breakdown = []
    for d in generating_details:
        struct_type = d['structure_type']
        catalog_entry = INFRASTRUCTURE_CATALOG.get(struct_type, {})
        generators_breakdown.append({
            'structure_type': struct_type,
            'name': d['structure_name'],
            'level': d.get('building_level', 1),
            'max_level': len(catalog_entry.get('levels', {})),
            'icon': catalog_entry.get('icon', '⚡'),
            'hourly_rate': d['hourly_rate'],
            'has_day_night': d.get('day_night') is not None,
            'latitude_affected': struct_type == 'solar_array',
        })

    sv_accumulated = 0.0
    sv_base_rate = 0.0
    sv_sources = []
    for structure in structures:
        if structure['status'] != 'active':
            continue
        building_level = all_levels.get(structure['structure_type'], 1)
        if building_level < 1:
            building_level = 1

        catalog_def = INFRASTRUCTURE_CATALOG.get(structure['structure_type'], {})
        level_data = catalog_def.get('levels', {}).get(building_level, {})
        sv_rate = float(level_data.get('science_generation_rate', 0))
        if sv_rate <= 0:
            continue
        sv_base_rate += sv_rate
        sv_sources.append({
            'name': level_data.get('name', catalog_def.get('name', structure['structure_type'])),
            'type': structure['structure_type'],
            'level': building_level,
            'rate': sv_rate,
        })
        last_payout = structure.get('last_payout_at') or structure['build_completed_at'] or structure['created_at']
        hours_elapsed = (datetime.utcnow() - last_payout).total_seconds() / 3600
        capped_hours = min(hours_elapsed, ACCUMULATION_CAP_HOURS)
        sv_accumulated += sv_rate * capped_hours

    sv_scientist_name = None
    sv_scientist_bonus = 1.0
    sv_scientist_extra = 0.0
    try:
        from utilities.postgres.users import get_user_scientist
        scientist = get_user_scientist(user_id)
        if scientist:
            analysis_stat = scientist.get('stats', {}).get('analysis', 0)
            sv_scientist_bonus = 1.0 + (analysis_stat / 50.0)
            sv_scientist_name = scientist.get('name')
            sv_scientist_extra = round(sv_base_rate * (sv_scientist_bonus - 1.0), 1)
            sv_accumulated *= sv_scientist_bonus
    except Exception:
        pass
    sv_signal_accumulated = 0.0
    if signal_bonus.get('sv_per_hour', 0) > 0 and details:
        avg_cap = sum(d['capped_hours'] for d in details) / len(details)
        sv_signal_accumulated = signal_bonus['sv_per_hour'] * avg_cap
        sv_accumulated += sv_signal_accumulated

    sv_hourly_rate = round(sv_base_rate * sv_scientist_bonus + signal_bonus.get('sv_per_hour', 0), 1)

    return {
        'total_accumulated': round(total_accumulated, 2),
        'base_accumulated': round(base_accumulated, 2),
        'total_all_time': round(total_all_time, 2),
        'details': details,
        'can_claim': total_accumulated > 0.1,
        'has_battery': has_battery,
        'has_maintenance_drone': has_maintenance_drone,
        'dust_covered_structures': dust_covered_structures,
        'any_dust_covered': len(dust_covered_structures) > 0,
        'structures_at_cap': structures_at_cap,
        'any_at_cap': len(structures_at_cap) > 0,
        'cap_hours': ACCUMULATION_CAP_HOURS,
        'cap_days': ACCUMULATION_CAP_HOURS / 24,
        'signal_bonus': {
            'shards_per_hour': signal_bonus['shards_per_hour'],
            'sv_per_hour': signal_bonus['sv_per_hour'],
            'sites_count': signal_bonus['sites_count'],
            'per_tier': signal_bonus['per_tier'],
            'shards_accumulated': round(signal_shards_accumulated, 2),
            'sv_accumulated': round(sv_signal_accumulated, 1),
        },
        'bonuses_applied': {
            'passive_income_mult': passive_income_mult,
            'passive_income_source': passive_income_source,
            'tech_passive_mult': tech_passive_mult,
            'all_generation_mult': all_generation_mult,
            'passive_income_base': passive_income_base,
            'scientist_shard_mult': scientist_shard_mult,
            'signal_shards_per_hour': signal_bonus['shards_per_hour'],
            'signal_sites_count': signal_bonus['sites_count'],
        },
        'rate_breakdown': {
            'base_hourly_rate': round(base_hourly_rate, 1),
            'day_night_efficiency': round(day_night_efficiency * 100, 0),
            'effective_base_rate': effective_base_rate,
            'theoretical_max_rate': theoretical_max_rate,
            'actual_avg_rate': actual_avg_rate,
            'effective_rate': effective_rate,
            'mars_env_multiplier': round(mars_env_multiplier * 100, 0),
            'mars_env_factors': mars_env_factors,
        },
        'generators_breakdown': generators_breakdown,
        'latitude': coords['latitude'],
        'sv_accumulated': round(sv_accumulated, 1),
        'sv_hourly_rate': round(sv_hourly_rate, 1),
        'sv_base_rate': round(sv_base_rate, 1),
        'sv_sources': sv_sources,
        'sv_scientist_name': sv_scientist_name,
        'sv_scientist_bonus': round(sv_scientist_bonus, 2),
        'sv_scientist_extra': sv_scientist_extra,
    }


def claim_accumulated_income(user_id, session=None):
    """Claim all accumulated Sepolia from generators and send to wallet.

    Bug #1268 fix: LOCAL DB FIRST, blockchain in background thread.
    """
    calc = calculate_accumulated_income(user_id)

    if not calc['can_claim']:
        return {
            'success': False,
            'error': 'No income to claim (minimum: 0.1 Sepolia)',
            'accumulated': calc['total_accumulated']
        }

    wallet = get_user_primary_sepolia_wallet(user_id)
    if not wallet:
        return {'success': False, 'error': 'No wallet found'}

    coords = get_or_set_user_mars_home(user_id)
    amount_eth = calc['total_accumulated'] / 10000000
    total_hours = sum(d['hours_elapsed'] for d in calc['details'])

    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE pilgrim.sepolia_assets
                SET current_balance_eth = current_balance_eth + %s, last_balance_check = NOW()
                WHERE wallet_address = %s
            """, (amount_eth, wallet['wallet_address']))

            for structure in calc['details']:
                cur.execute("""
                    UPDATE pilgrim.colony_infrastructure
                    SET last_payout_at = NOW(),
                        total_generated = total_generated + %s,
                        dust_covered = FALSE,
                        dust_covered_at = NULL,
                        updated_at = NOW()
                    WHERE user_id = %s AND structure_type = %s AND status = 'active'
                """, (structure['accumulated'], user_id, structure['structure_type']))
    except Exception as e:
        logger.error(f"Failed to claim income for user {user_id} (DB update): {e}")
        return {'success': False, 'error': 'Harvest failed — shards are safe, try again'}

    if session is not None:
        from utilities.depot_utils import update_session_balance
        old_balance = session.get('_bal', 0)
        new_balance = old_balance + calc['total_accumulated']
        update_session_balance(session, new_balance)
    else:
        from utilities.depot_utils import get__bal
        old_balance = float(get__bal(user_id))
        new_balance = old_balance + calc['total_accumulated']

    dust_cleared = calc.get('any_dust_covered', False)
    if dust_cleared:
        logger.info(f"✨ Dust cleared from solar arrays for user {user_id}")

    logger.info(f"✅ User {user_id} harvested {calc['total_accumulated']} Sepolia from {coords['latitude']:.2f}°N, {coords['longitude']:.2f}°E")

    from utilities.postgres.users import update_user_activity
    update_user_activity(user_id)

    def _background_harvest_tx():
        try:
            harvest_details = []
            for detail in calc['details']:
                if detail['structure_type'] == 'solar_array':
                    lat = abs(coords['latitude'])
                    efficiency = (1.0 - (lat / 90.0) * 0.4) * 100
                    harvest_details.append(
                        f"Solar Array at {coords['latitude']:.2f}°N {coords['longitude']:.2f}°E: "
                        f"{detail['accumulated']:.1f} Sepolia over {detail['hours_elapsed']:.1f}h. "
                        f"Efficiency: {efficiency:.1f}%. "
                    )
            message = (
                f"Colony shard systems generated {calc['total_accumulated']:.1f} Sepolia over {total_hours:.1f} hours. "
                f"Base: {coords['latitude']:.2f}°N, {coords['longitude']:.2f}°E. "
                f"{''.join(harvest_details)}"
                f"Resources harvested and transferred to cache. "
            )
            miner = MarsAsteroidMiner()
            if miner.connect():
                result = miner.send_sepolia_reward_fast(
                    wallet['wallet_address'], amount_eth, message, context="infrastructure_income"
                )
                if result.get('success'):
                    create_depot_transaction(
                        user_id=user_id,
                        wallet_address=wallet['wallet_address'],
                        purchase_type='infrastructure_income',
                        amount_eth=amount_eth,
                        tx_hash=result['tx_hash'],
                        etherscan_url=result['etherscan_url'],
                        item_details={
                            'hours_accumulated': total_hours,
                            'structures': [d['structure_type'] for d in calc['details']],
                            'base_coordinates': {'latitude': coords['latitude'], 'longitude': coords['longitude']},
                            'solar_efficiency_percent': (1.0 - (abs(coords['latitude']) / 90.0) * 0.4) * 100,
                            'structure_details': calc['details']
                        }
                    )
                    logger.info(f"📡 Background harvest tx complete: {result['tx_hash']}")
                else:
                    logger.warning(f"⚠️ Background harvest tx failed for user {user_id}: {result.get('error')}")
        except Exception as e:
            logger.error(f"⚠️ Background harvest tx error for user {user_id}: {e}")

    threading.Thread(target=_background_harvest_tx, daemon=True).start()

    return {
        'success': True,
        'amount_claimed': calc['total_accumulated'],
        'new_balance': new_balance,
        'tx_hash': 'pending',
        'etherscan_url': '',
        'details': calc['details'],
        'base_coordinates': coords,
        'dust_cleared': dust_cleared,
        'panels_cleaned': len(calc.get('dust_covered_structures', []))
    }


def record_science_value(user_id):
    """Record (claim) accumulated Science Value from Research Station. Separate from shard harvest."""
    calc = calculate_accumulated_income(user_id)
    sv_amount = calc.get('sv_accumulated', 0)

    if sv_amount < 1:
        return {'success': False, 'error': 'Not enough SV to record (minimum: 1)'}

    from utilities.postgres.users import add_passive_sv
    add_passive_sv(user_id, sv_amount)

    sv_building_types = [stype for stype, cat in INFRASTRUCTURE_CATALOG.items()
                         if any(lv.get('science_generation_rate', 0) > 0
                                for lv in cat.get('levels', {}).values())]
    if sv_building_types:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE pilgrim.colony_infrastructure
                SET last_payout_at = NOW(), updated_at = NOW()
                WHERE user_id = %s AND structure_type = ANY(%s) AND status = 'active'
            """, (user_id, sv_building_types))

    logger.info(f"🔬 User {user_id} recorded {sv_amount:.1f} SV")

    # Bug #1315: mirror harvest/upgrade events — every SV record hits the log.
    try:
        from utilities.postgres.activity import log_activity
        log_activity(
            user_id, 'research', 'sv_recorded',
            f"Recorded {round(sv_amount, 1)} SV",
            amount=float(sv_amount),
            detail='from Research Station + Scientist'
        )
    except Exception as _e:
        logger.warning(f"activity log (sv_recorded) failed for user {user_id}: {_e}")

    from utilities.tech_utils import _get_available_sv
    return {
        'success': True,
        'sv_recorded': round(sv_amount, 1),
        'sv_available': _get_available_sv(user_id),
    }
