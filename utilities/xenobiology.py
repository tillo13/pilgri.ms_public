"""Xenobiology Lab - research point experiments + stat upgrades.

Split from utilities/infrastructure_utils.py in R10a. Shim re-exports preserved
via utilities/infrastructure_utils.py for back-compat.
"""
import random


def _get_experiment_cost(total_experiments: int) -> int:
    """Calculate experiment cost based on total experiments run (escalating)"""
    if total_experiments < 5:
        return 5000 + (total_experiments * 200)
    elif total_experiments < 10:
        return 6000 + ((total_experiments - 5) * 300)
    elif total_experiments < 20:
        return 7500 + ((total_experiments - 10) * 500)
    return 12500 + ((total_experiments - 20) * 1000)


def _get_experiment_max_roll(total_experiments: int) -> int:
    """Get max roll range based on experiments run (decreases over time)"""
    if total_experiments < 5:
        return 6
    elif total_experiments < 10:
        return 5
    elif total_experiments < 20:
        return 4
    elif total_experiments < 35:
        return 3
    elif total_experiments < 50:
        return 2
    return 1


def get_xenobiology_status(user_id: int) -> dict:
    """Get research status for Xenobiology Lab modal"""
    from utilities.postgres.users import get_user_research_data
    from utilities.postgres.shop import get_user_infrastructure
    from utilities.postgres.assets import get_commander_stats
    from utilities.depot_utils import get_fast_balance_and_wallet_info
    from config import MAX_DISPLAY_STAT

    infrastructure = get_user_infrastructure(user_id, 'xenobiology_lab')
    has_lab = any(i['status'] == 'active' for i in infrastructure) if infrastructure else False
    if not has_lab:
        return {'success': False, 'error': 'Xenobiology Lab not built'}

    research_data = get_user_research_data(user_id)
    commander_stats = get_commander_stats(user_id)
    balance, _, _ = get_fast_balance_and_wallet_info(user_id)

    total_experiments = research_data.get('total_experiments_run', 0)
    experiment_cost = _get_experiment_cost(total_experiments)
    max_roll = _get_experiment_max_roll(total_experiments)

    stat_bonuses = research_data.get('stat_bonuses', {})
    effective_stats = {}
    for stat in ['leadership', 'strategy', 'exploration', 'logistics', 'charisma']:
        base = commander_stats.get(stat, 0) if commander_stats else 0
        bonus = stat_bonuses.get(stat, 0)
        effective_stats[stat] = {
            'base': base, 'bonus': bonus,
            'total': min(base + bonus, MAX_DISPLAY_STAT + 10),
            'can_upgrade': bonus < 10 and base + bonus < MAX_DISPLAY_STAT + 10
        }

    return {
        'success': True,
        'research_points': research_data.get('research_points', 0),
        'total_experiments': total_experiments,
        'experiment_cost': experiment_cost,
        'max_roll': max_roll,
        'current_balance': balance,
        'can_afford': balance >= experiment_cost,
        'effective_stats': effective_stats
    }


def run_xenobiology_experiment(user_id: int, session) -> dict:
    """Run an experiment to gain research points"""
    from utilities.postgres.users import get_user_research_data, add_research_points
    from utilities.postgres.shop import get_user_infrastructure
    from utilities.depot_utils import get_fast_balance_and_wallet_info, invalidate_balance_cache
    from utilities.sepolia_utils import MarsAsteroidMiner
    from utilities.depot_utils import display_to_eth

    infrastructure = get_user_infrastructure(user_id, 'xenobiology_lab')
    has_lab = any(i['status'] == 'active' for i in infrastructure) if infrastructure else False
    if not has_lab:
        return {'success': False, 'error': 'Xenobiology Lab not built'}

    research_data = get_user_research_data(user_id)
    total_experiments = research_data.get('total_experiments_run', 0)
    experiment_cost = _get_experiment_cost(total_experiments)
    max_roll = _get_experiment_max_roll(total_experiments)

    balance, _, primary_wallet = get_fast_balance_and_wallet_info(user_id)
    if balance < experiment_cost:
        return {'success': False, 'error': f'Need {experiment_cost} shards, have {balance:.1f}'}
    if not primary_wallet:
        return {'success': False, 'error': 'No wallet found'}

    points_gained = random.randint(1, max_roll)

    miner = MarsAsteroidMiner()
    tx_result = miner.log_transaction(
        private_key=primary_wallet['wallet_private_key'],
        amount_eth=display_to_eth(experiment_cost),
        message=f"XENO_EXP:{points_gained}pts"
    )
    if not tx_result.get('success'):
        return {'success': False, 'error': 'Transaction failed'}

    add_research_points(user_id, points_gained)
    invalidate_balance_cache(session)

    return {
        'success': True,
        'points_gained': points_gained,
        'max_roll': max_roll,
        'new_total_points': research_data.get('research_points', 0) + points_gained,
        'experiments_run': total_experiments + 1,
        'tx_hash': tx_result.get('tx_hash')
    }


def upgrade_xenobiology_stat(user_id: int, stat_name: str) -> dict:
    """Spend research points to upgrade a stat"""
    from utilities.postgres.users import get_user_research_data, spend_research_points
    from utilities.postgres.assets import get_commander_stats
    from config import MAX_DISPLAY_STAT

    if stat_name not in ['leadership', 'strategy', 'exploration', 'logistics', 'charisma']:
        return {'success': False, 'error': 'Invalid stat'}

    research_data = get_user_research_data(user_id)
    commander_stats = get_commander_stats(user_id)
    stat_bonuses = research_data.get('stat_bonuses', {})

    current_bonus = stat_bonuses.get(stat_name, 0)
    base_stat = commander_stats.get(stat_name, 0) if commander_stats else 0

    if current_bonus >= 10:
        return {'success': False, 'error': 'Stat bonus already at maximum (+10)'}
    if base_stat + current_bonus >= MAX_DISPLAY_STAT + 10:
        return {'success': False, 'error': 'Stat already at absolute maximum (100)'}

    if research_data.get('research_points', 0) < 1:
        return {'success': False, 'error': 'Need 1 research point'}

    result = spend_research_points(user_id, stat_name, 1)
    if not result:
        return {'success': False, 'error': 'Failed to upgrade stat'}

    new_bonus = result['stat_bonuses'].get(stat_name, 0)
    return {
        'success': True,
        'stat': stat_name,
        'new_bonus': new_bonus,
        'new_total': base_stat + new_bonus,
        'remaining_points': result['research_points']
    }
