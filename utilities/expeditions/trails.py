"""
Trail-building crew mission orchestration.

When a captain/scientist/aria is dispatched to build a trail segment, this
module computes km-to-add from stats × scanner × suit × consumables, finds
the nearest trail node to chain from, and kicks off the crew mission.
"""

import logging

logger = logging.getLogger(__name__)


def handle_trail_build_request(user_id, data):
    """v3 (#1414): trail build mission targets the captain's active chain segment.

    Body still accepts `destination_name` for back-compat (e.g. "N chain seg 3")
    but the actual target is auto-resolved to the next unbuilt segment of the
    captain's active chain direction.
    """
    from utilities.postgres.trails import get_crew_mission_status, start_crew_mission, consume_discovery_for_trail
    from utilities.postgres.trails.chains import (
        ensure_user_trail_chains_table, get_user_active_direction, get_active_chain_segments,
    )
    from utilities.postgres.core import db_cursor
    from utilities.shop_utils import get_scanner_trail_bonus
    from config import get_scientist_trail_bonus, COLONY_SCIENTISTS

    worker_type = data.get('worker_type', '').lower()
    if worker_type not in ('captain', 'scientist', 'aria'):
        return {'success': False, 'error': 'Invalid worker type'}

    # Check if crew member is already busy
    status = get_crew_mission_status(user_id)
    member_status = status.get(worker_type) or {}
    if member_status.get('busy'):
        return {'success': False, 'error': f'{worker_type.title()} is already on a mission'}
    if member_status.get('complete'):
        return {'success': False, 'error': f'{worker_type.title()} has a mission to claim first'}

    # Resolve target: the next unbuilt segment of the captain's active chain.
    ensure_user_trail_chains_table()
    direction = get_user_active_direction(user_id)
    chain_state = get_active_chain_segments(user_id).get(direction) or {}
    next_seg = chain_state.get('next_unbuilt')
    if not next_seg:
        return {'success': False, 'error': f'Your {direction} chain is complete — switch direction to keep building'}
    destination = next_seg['to_landmark']
    from_landmark = next_seg['from_landmark']

    # Calculate km based on crew stats, scanner, and consumable
    # Stats are the PRIMARY driver (1x-6x). See config_shop.BASE_TRAIL_RATE_KMH.
    from config_shop import calculate_trail_km
    stat_multiplier = 1.0
    stat_bonus_desc = ""

    with db_cursor() as cur:
        if worker_type == 'captain':
            # Captain: commander_logistics stat (0-90) is primary, XP is secondary
            cur.execute("SELECT captain_logistics_xp FROM pilgrim.users WHERE id = %s", (user_id,))
            r = cur.fetchone()
            logistics_xp = r.get('captain_logistics_xp') or 0 if r else 0
            # Get the actual character stat (commander_logistics) from replicate_assets
            cur.execute("""
                SELECT commander_logistics FROM pilgrim.replicate_assets
                WHERE user_id = %s AND asset_type = 'character_image' AND is_deleted = FALSE
                ORDER BY created_at DESC LIMIT 1
            """, (user_id,))
            asset = cur.fetchone()
            commander_logistics = float(asset.get('commander_logistics') or 0) if asset else 0
            stat_multiplier = 1.0 + (commander_logistics / 30) + (logistics_xp / 2000)
            stat_bonus_desc = f"Logistics {int(commander_logistics)} + {logistics_xp} XP ({stat_multiplier:.1f}x)"

        elif worker_type == 'scientist':
            cur.execute("SELECT scientist_navigation_xp, scientist_key FROM pilgrim.users WHERE id = %s", (user_id,))
            r = cur.fetchone()
            nav_xp = r.get('scientist_navigation_xp') or 0 if r else 0
            nav_multiplier = 1.0 + (nav_xp / 1500)
            scientist_key = r.get('scientist_key') if r else None
            specialty_geology_bonus = get_scientist_trail_bonus(scientist_key) if scientist_key else 0
            stat_multiplier = nav_multiplier * (1.0 + specialty_geology_bonus)
            scientist_name = COLONY_SCIENTISTS.get(scientist_key, {}).get('specialty', 'Science') if scientist_key else 'Science'
            stat_bonus_desc = f"Nav {nav_xp} XP + {scientist_name} ({stat_multiplier:.1f}x)"

        elif worker_type == 'aria':
            # ARIA: resonance is primary multiplier, lore_memory adds efficiency
            cur.execute("SELECT resonance_level, lore_memory_level FROM pilgrim.aria_skills WHERE user_id = %s", (user_id,))
            r = cur.fetchone()
            resonance_level = r.get('resonance_level') or 1 if r else 1
            lore_memory_level = r.get('lore_memory_level') or 1 if r else 1
            stat_multiplier = 1.0 + (resonance_level / 20) + (lore_memory_level / 200)
            stat_bonus_desc = f"Resonance Lv{resonance_level} + Lore Lv{lore_memory_level} ({stat_multiplier:.1f}x)"

    scanner_bonus = get_scanner_trail_bonus(user_id)
    scanner_multiplier = scanner_bonus['multiplier']

    # EVA Suit bonus: +5% trail speed per suit level (Lv10 = +50%)
    from utilities.upgrades_utils import get_user_upgrade_level
    suit_level = get_user_upgrade_level(user_id, 'gear', 'suit')
    suit_multiplier = 1.0 + (suit_level * 0.05)

    # Consumable bonus (optional)
    consumable_multiplier = 1.0
    consumable_used = None
    consumable_id = data.get('consumable_id')
    if consumable_id:
        consume_result = consume_discovery_for_trail(user_id, int(consumable_id))
        if consume_result.get('success'):
            consumable_multiplier = 1.0 + consume_result['bonus']
            consumable_used = consume_result

    total_multiplier = stat_multiplier * scanner_multiplier * suit_multiplier * consumable_multiplier
    trail_calc = calculate_trail_km(total_multiplier)
    duration_minutes = trail_calc['duration_minutes']
    km_to_add = trail_calc['km_to_add']

    # v3: chain segment is pre-resolved (next_seg above). No need to look up origin.
    result = start_crew_mission(user_id, worker_type, destination, duration_minutes, km_to_add, from_landmark)

    if result.get('success'):
        result['km_to_add'] = round(km_to_add, 4)
        result['from_landmark'] = from_landmark
        result['segment_distance_km'] = round(float(next_seg['segment_distance_km']), 2)
        result['chain_direction'] = direction
        result['chain_segment_index'] = next_seg['segment_index']
        result['stat_multiplier'] = round(stat_multiplier, 2)
        result['stat_bonus'] = stat_bonus_desc
        result['scanner_multiplier'] = round(scanner_multiplier, 2)
        result['scanner_bonus'] = scanner_bonus
        result['suit_multiplier'] = round(suit_multiplier, 2)
        result['suit_level'] = suit_level
        result['consumable_multiplier'] = round(consumable_multiplier, 2)
        result['consumable_used'] = consumable_used
        result['total_multiplier'] = round(total_multiplier, 2)
        if from_landmark == 'HOME':
            result['message'] = f'{worker_type.title()} heading to {destination} for {duration_minutes} min session'
        else:
            result['message'] = f'{worker_type.title()} building {from_landmark} → {destination} for {duration_minutes} min session'

    return result


def get_trail_consumables_data(user_id):
    """Get available consumables and scanner bonus for trail building."""
    from utilities.postgres.trails import get_trail_consumable_discoveries
    from utilities.shop_utils import get_scanner_trail_bonus
    from config import TRAIL_CONSUMABLE_BONUSES

    scanner = get_scanner_trail_bonus(user_id)
    discoveries = get_trail_consumable_discoveries(user_id)

    for d in discoveries:
        item_type = d.get('item_type', '')
        item_name = (d.get('item_name') or '').lower()
        type_bonuses = TRAIL_CONSUMABLE_BONUSES.get(item_type, {})
        bonus = type_bonuses.get('default', 0.05)
        for kw, val in type_bonuses.items():
            if kw != 'default' and kw in item_name:
                bonus = val
                break
        d['trail_bonus'] = bonus
        d['trail_bonus_percent'] = int(bonus * 100)

    # Group consumables by name+bonus, keep oldest ID for FIFO
    grouped = {}
    for d in sorted(discoveries, key=lambda x: x.get('claimed_at', '')):
        key = f"{d['item_name']}|{d['trail_bonus_percent']}"
        if key not in grouped:
            grouped[key] = {
                'id': d['id'],
                'item_name': d['item_name'],
                'trail_bonus_percent': d['trail_bonus_percent'],
                'count': 1
            }
        else:
            grouped[key]['count'] += 1

    return {'success': True, 'scanner': scanner, 'consumables': list(grouped.values())}
