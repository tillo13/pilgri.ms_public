"""Infrastructure page data + route handler glue."""
import time
from datetime import datetime

from config_infrastructure import INFRASTRUCTURE_CATALOG
from utilities.postgres.shop import get_user_infrastructure
from utilities.postgres.map import get_or_set_user_mars_home

from utilities.infrastructure.environment import calculate_generation_rate
from utilities.infrastructure.construction import (
    _check_build_requirements_fast,
    start_construction,
    check_construction_status,
    send_completion_reward,
)
from utilities.infrastructure.income import calculate_accumulated_income


def get_infrastructure_page_data(user_id: int) -> dict:
    """Get all data needed for the colony/infrastructure page."""
    coords = get_or_set_user_mars_home(user_id)
    existing_raw = get_user_infrastructure(user_id)

    from utilities.upgrades_utils import get_all_infrastructure_levels, get_all_upgrade_build_statuses
    all_levels = get_all_infrastructure_levels(user_id, structures=existing_raw)
    all_build_statuses = get_all_upgrade_build_statuses(user_id, 'infrastructure')

    existing = []
    building_infrastructure = []

    for building in existing_raw:
        enriched = dict(building)
        catalog_def = INFRASTRUCTURE_CATALOG.get(building['structure_type'], {})
        current_level = max(1, all_levels.get(building['structure_type'], 1))
        level_data = catalog_def.get('levels', {}).get(current_level, {})

        enriched['name'] = catalog_def.get('name', building['structure_type'].replace('_', ' ').title())
        enriched['icon'] = catalog_def.get('icon', '')
        enriched['image_url'] = level_data.get('image_url', '')
        enriched['description'] = catalog_def.get('description', '')
        enriched['effect'] = catalog_def.get('effect')
        enriched['effect_value'] = catalog_def.get('effect_value')
        enriched['generates_resource'] = catalog_def.get('generates_resource')
        enriched['tier'] = catalog_def.get('tier', 1)
        enriched['cost_display'] = int(level_data.get('cost', 0))
        enriched['category'] = catalog_def.get('category', 'general')
        enriched['total_generated'] = float(building.get('total_generated', 0) or 0)

        enriched['level'] = current_level
        enriched['max_level'] = catalog_def.get('max_level', 10)
        enriched['level_name'] = level_data.get('name', f'Level {current_level}')

        upgrade_status = all_build_statuses.get(building['structure_type'])
        enriched['is_upgrading'] = upgrade_status.get('is_building', False) if upgrade_status else False
        enriched['upgrade_status'] = upgrade_status

        if current_level < catalog_def.get('max_level', 10):
            next_level_data = catalog_def.get('levels', {}).get(current_level + 1, {})
            enriched['next_level_cost'] = int(next_level_data.get('cost', 0))
            enriched['next_level_name'] = next_level_data.get('name', f'Level {current_level + 1}')
            enriched['next_build_time_days'] = next_level_data.get('build_time_days', 0)
        else:
            enriched['next_level_cost'] = None
            enriched['is_max_level'] = True

        if building['structure_type'] == 'solar_array':
            enriched['generation_rate'] = calculate_generation_rate('solar_array', coords['latitude'], coords['longitude'], current_level)
        else:
            enriched['generation_rate'] = float(level_data.get('generation_rate', 0.0))

        if building['status'] == 'active':
            existing.append(enriched)
        elif building['status'] == 'building':
            if building.get('ready_at'):
                remaining = (building['ready_at'] - datetime.now()).total_seconds()
                enriched['seconds_remaining'] = max(0, int(remaining))
            else:
                enriched['seconds_remaining'] = 0
            building_infrastructure.append(enriched)

    existing_types = {b['structure_type']: b for b in existing_raw}
    user_active_types = [b['structure_type'] for b in existing_raw if b.get('status') == 'active']

    available_structures = []
    for structure_type, definition in INFRASTRUCTURE_CATALOG.items():
        if structure_type in existing_types:
            continue

        can_build, missing = _check_build_requirements_fast(structure_type, user_active_types, all_levels)
        rate = calculate_generation_rate(structure_type, coords['latitude'], coords['longitude'])

        level_1 = definition.get('levels', {}).get(1, {})
        enriched_definition = {
            **definition,
            'cost_sepolia': level_1.get('cost', 0) / 10_000_000,
            'build_time_seconds': level_1.get('build_time_days', 0) * 86400,
            'image_url': level_1.get('image_url', ''),
            'generation_rate': level_1.get('generation_rate', 0),
        }

        available_structures.append({
            'type': structure_type,
            'definition': enriched_definition,
            'can_build': can_build,
            'missing_requirements': missing,
            'generation_rate': rate
        })

    return {
        'coords': coords,
        'structures': available_structures,
        'existing': existing,
        'building_infrastructure': building_infrastructure,
        'now': datetime.now()
    }


def handle_infrastructure_build(user_id, structure_type, session):
    """Handle infrastructure build request - check prereqs, start construction, update session."""
    from utilities.depot_utils import update_session_balance

    if not structure_type:
        return {'success': False, 'error': 'Missing structure_type'}

    existing = get_user_infrastructure(user_id, structure_type)
    if existing and len(existing) > 0:
        return {'success': False, 'error': 'Structure already built', 'already_exists': True}

    active_construction = session.get('active_construction')
    if active_construction and active_construction.get('type') == structure_type:
        return {'success': False, 'error': 'Construction already in progress', 'in_progress': True}

    coords = get_or_set_user_mars_home(user_id)
    result = start_construction(user_id, structure_type, coords['latitude'], coords['longitude'])

    if result['success']:
        session['active_construction'] = {
            'id': result['construction_id'],
            'type': structure_type,
            'started_at': time.time()
        }
        session['construction_reward_sent'] = False
        update_session_balance(session, result['new_balance'])
        session.modified = True
        from utilities.postgres.users import update_user_activity
        update_user_activity(user_id)

    return result


def handle_infrastructure_status(session):
    """Check construction status and send reward if complete."""
    construction = session.get('active_construction')
    if not construction:
        return {'complete': False, 'error': 'No active construction'}

    status = check_construction_status(construction['id'])

    if status.get('complete') and not session.get('construction_reward_sent'):
        user_id = session.get('user_id')
        reward = send_completion_reward(construction['id'], user_id)

        if reward.get('success'):
            session['construction_reward_sent'] = True
            session.modified = True
            status['reward'] = reward
        else:
            status['reward'] = {'success': False, 'error': reward.get('error')}

    return status


def handle_accumulated_income(user_id):
    """Get accumulated income with total_all_time calculated."""
    result = calculate_accumulated_income(user_id)
    structures = get_user_infrastructure(user_id)
    total_all_time = sum(float(s.get('total_generated', 0)) for s in structures)
    result['total_all_time'] = total_all_time
    return result
