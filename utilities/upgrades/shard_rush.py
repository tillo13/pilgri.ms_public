"""Shard Rush — pay shards to instantly complete an in-progress build.

Bug #1270 Phase 4 (Luke section 4 point 1, 2026-04-12):
"Shard Rush anytime Building Time < 24 hours (25-50% of the Cost)
Maybe this increases with the higher levels of Life Support/Water Extractor."

Eligibility: the build is in progress AND remaining time < 24h.
Cost formula: max(0.25, 0.50 - 0.0125 × (life_support_lv + water_extractor_lv)) × base_upgrade_cost.
Combined L0/L0 = 50%; L20 (combined) hits the 25% floor.
"""

import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from utilities.postgres.core import db_cursor

logger = logging.getLogger(__name__)

RUSH_THRESHOLD_HOURS = 24
RUSH_FLOOR = 0.25
RUSH_CEILING = 0.50
RUSH_PER_LEVEL = 0.0125


def calculate_rush_cost_pct(user_id: int) -> float:
    """The pct of base cost that Shard Rush charges, based on Life Support + Water Extractor levels.
    Direct, read-only query — avoids the UPDATE+SELECT path in get_user_infrastructure()."""
    ls = 0
    water = 0
    try:
        with db_cursor() as cur:
            cur.execute(
                """
                SELECT c.structure_type, COALESCE(u.level, 1) AS level
                FROM pilgrim.colony_infrastructure c
                LEFT JOIN pilgrim.player_upgrades u
                  ON u.user_id = c.user_id
                 AND u.category = 'infrastructure'
                 AND u.item_key = c.structure_type
                WHERE c.user_id = %s
                  AND c.status = 'active'
                  AND c.structure_type IN ('life_support', 'water_extractor')
                """,
                (user_id,),
            )
            for row in cur.fetchall():
                if row['structure_type'] == 'life_support':
                    ls = int(row['level'])
                elif row['structure_type'] == 'water_extractor':
                    water = int(row['level'])
    except Exception as e:
        logger.warning(f"calculate_rush_cost_pct fallback: {e}")
    raw = RUSH_CEILING - RUSH_PER_LEVEL * (ls + water)
    return max(RUSH_FLOOR, raw)


def _upgrade_base_cost(category: str, item_key: str, target_level: int) -> int:
    """Lookup the shards cost of an upgrade's target level from UPGRADE_CATALOG."""
    from config_upgrades import UPGRADE_CATALOG
    return int(
        UPGRADE_CATALOG.get(category, {})
        .get(item_key, {})
        .get('levels', {})
        .get(target_level, {})
        .get('cost', 0)
    )


def _infrastructure_base_cost(structure_type: str, target_level: int) -> int:
    """Lookup the shards cost of a building's target level from INFRASTRUCTURE_CATALOG."""
    from utilities.infrastructure_utils import INFRASTRUCTURE_CATALOG
    return int(
        INFRASTRUCTURE_CATALOG.get(structure_type, {})
        .get('levels', {})
        .get(target_level, {})
        .get('cost', 0)
    )


def check_equipment_rush_eligibility(user_id: int, category: str, item_key: str) -> Dict[str, Any]:
    """Return {eligible, reason, rush_cost, remaining_hours, target_level} for an in-progress equipment upgrade."""
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT level, pending_level, ready_at
            FROM pilgrim.player_upgrades
            WHERE user_id = %s AND category = %s AND item_key = %s
            """,
            (user_id, category, item_key),
        )
        row = cur.fetchone()
    if not row or row['pending_level'] is None or not row['ready_at']:
        return {'eligible': False, 'reason': 'No build in progress', 'rush_cost': 0, 'remaining_hours': 0, 'target_level': None}

    ready_at = row['ready_at']
    if ready_at.tzinfo is None:
        ready_at = ready_at.replace(tzinfo=timezone.utc)
    remaining = (ready_at - datetime.now(timezone.utc)).total_seconds()
    remaining_hours = remaining / 3600.0
    if remaining <= 0:
        return {'eligible': False, 'reason': 'Already complete', 'rush_cost': 0, 'remaining_hours': 0, 'target_level': row['pending_level']}
    if remaining_hours >= RUSH_THRESHOLD_HOURS:
        return {
            'eligible': False,
            'reason': f'Rush available when under {RUSH_THRESHOLD_HOURS}h remaining',
            'rush_cost': 0,
            'remaining_hours': round(remaining_hours, 2),
            'target_level': row['pending_level'],
        }

    base_cost = _upgrade_base_cost(category, item_key, row['pending_level'])
    pct = calculate_rush_cost_pct(user_id)
    rush_cost = int(round(base_cost * pct))
    return {
        'eligible': True,
        'reason': 'OK',
        'rush_cost': rush_cost,
        'rush_pct': round(pct, 4),
        'remaining_hours': round(remaining_hours, 2),
        'target_level': row['pending_level'],
    }


def check_infrastructure_rush_eligibility(user_id: int, structure_type: str) -> Dict[str, Any]:
    """Return rush eligibility for an in-progress INITIAL build (Lv1) in colony_infrastructure.
    Upgrades Lv2+ use check_equipment_rush_eligibility with category='infrastructure'."""
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT id, ready_at FROM pilgrim.colony_infrastructure
            WHERE user_id = %s AND structure_type = %s AND status = 'building'
            ORDER BY ready_at ASC LIMIT 1
            """,
            (user_id, structure_type),
        )
        row = cur.fetchone()
    if not row or not row['ready_at']:
        return {'eligible': False, 'reason': 'No build in progress', 'rush_cost': 0, 'remaining_hours': 0, 'target_level': None}

    ready_at = row['ready_at']
    if ready_at.tzinfo is None:
        ready_at = ready_at.replace(tzinfo=timezone.utc)
    remaining = (ready_at - datetime.now(timezone.utc)).total_seconds()
    remaining_hours = remaining / 3600.0
    if remaining <= 0:
        return {'eligible': False, 'reason': 'Already complete', 'rush_cost': 0, 'remaining_hours': 0, 'target_level': 1}
    if remaining_hours >= RUSH_THRESHOLD_HOURS:
        return {
            'eligible': False,
            'reason': f'Rush available when under {RUSH_THRESHOLD_HOURS}h remaining',
            'rush_cost': 0,
            'remaining_hours': round(remaining_hours, 2),
            'target_level': 1,
        }

    base_cost = _infrastructure_base_cost(structure_type, 1)
    pct = calculate_rush_cost_pct(user_id)
    rush_cost = int(round(base_cost * pct))
    return {
        'eligible': True,
        'reason': 'OK',
        'rush_cost': rush_cost,
        'rush_pct': round(pct, 4),
        'remaining_hours': round(remaining_hours, 2),
        'target_level': 1,
        'infrastructure_id': row['id'],
    }


def rush_equipment_upgrade(user_id: int, category: str, item_key: str) -> Dict[str, Any]:
    """Charge shards and promote pending_level → level on an in-progress equipment upgrade."""
    from utilities.postgres.wallets import get_user_primary_sepolia_wallet, update_sepolia_wallet_balance
    from utilities.depot_utils import background_blockchain_tx, display_to_eth
    from utilities.postgres.activity import log_activity

    eligibility = check_equipment_rush_eligibility(user_id, category, item_key)
    if not eligibility['eligible']:
        return {'success': False, 'error': eligibility['reason']}

    rush_cost = eligibility['rush_cost']
    target_level = eligibility['target_level']

    wallet = get_user_primary_sepolia_wallet(user_id)
    if not wallet:
        return {'success': False, 'error': 'No wallet found'}
    current_balance_eth = float(wallet.get('current_balance_eth', 0))
    current_balance_display = current_balance_eth * 10_000_000
    if current_balance_display < rush_cost:
        return {'success': False, 'error': f'Need {rush_cost} shards, have {int(current_balance_display)}'}

    cost_eth = display_to_eth(rush_cost)
    new_balance_eth = current_balance_eth - cost_eth
    update_sepolia_wallet_balance(wallet['wallet_address'], new_balance_eth)

    with db_cursor(commit=True) as cur:
        cur.execute(
            """
            UPDATE pilgrim.player_upgrades
            SET level = %s, pending_level = NULL, ready_at = NULL, upgraded_at = NOW()
            WHERE user_id = %s AND category = %s AND item_key = %s
            """,
            (target_level, user_id, category, item_key),
        )

    background_blockchain_tx(
        wallet_address=wallet['wallet_address'],
        wallet_private_key=wallet['wallet_private_key'],
        amount_eth=cost_eth,
        reason=f"Shard Rush: {category}/{item_key} Lv{target_level}",
        user_id=user_id,
        purchase_type='shard_rush',
        item_details={
            'category': category, 'item_key': item_key,
            'to_level': target_level, 'rush_cost_shards': rush_cost,
            'rush_pct': eligibility.get('rush_pct'),
        },
    )

    log_activity(
        user_id, 'upgrade', 'shard_rush',
        f"Shard Rush: {item_key.replace('_', ' ').title()} Lv{target_level}",
        amount=rush_cost, detail=f"{category} · rushed",
        source_table='player_upgrades',
        metadata={'category': category, 'item_key': item_key, 'to_level': target_level, 'rush_cost': rush_cost},
    )

    logger.info(f"⚡ User {user_id} Shard Rushed {category}/{item_key} to Lv{target_level} for {rush_cost} shards")

    try:
        from flask import session
        from utilities.session_helpers import invalidate_balance_cache
        invalidate_balance_cache(session)
    except Exception:
        pass

    return {
        'success': True,
        'rushed': True,
        'category': category,
        'item_key': item_key,
        'level': target_level,
        'rush_cost': rush_cost,
        'new_balance': int(new_balance_eth * 10_000_000),
    }


def rush_infrastructure_build(user_id: int, structure_type: str) -> Dict[str, Any]:
    """Charge shards and mark an in-progress building as built immediately."""
    from utilities.postgres.wallets import get_user_primary_sepolia_wallet, update_sepolia_wallet_balance
    from utilities.depot_utils import background_blockchain_tx, display_to_eth
    from utilities.postgres.activity import log_activity

    eligibility = check_infrastructure_rush_eligibility(user_id, structure_type)
    if not eligibility['eligible']:
        return {'success': False, 'error': eligibility['reason']}

    rush_cost = eligibility['rush_cost']
    target_level = eligibility['target_level']
    infra_id = eligibility['infrastructure_id']

    wallet = get_user_primary_sepolia_wallet(user_id)
    if not wallet:
        return {'success': False, 'error': 'No wallet found'}
    current_balance_eth = float(wallet.get('current_balance_eth', 0))
    current_balance_display = current_balance_eth * 10_000_000
    if current_balance_display < rush_cost:
        return {'success': False, 'error': f'Need {rush_cost} shards, have {int(current_balance_display)}'}

    cost_eth = display_to_eth(rush_cost)
    new_balance_eth = current_balance_eth - cost_eth
    update_sepolia_wallet_balance(wallet['wallet_address'], new_balance_eth)

    with db_cursor(commit=True) as cur:
        cur.execute(
            """
            UPDATE pilgrim.colony_infrastructure
            SET status = 'active', ready_at = NOW(), build_completed_at = NOW(), updated_at = NOW()
            WHERE id = %s AND user_id = %s
            """,
            (infra_id, user_id),
        )

    background_blockchain_tx(
        wallet_address=wallet['wallet_address'],
        wallet_private_key=wallet['wallet_private_key'],
        amount_eth=cost_eth,
        reason=f"Shard Rush: {structure_type} Lv{target_level}",
        user_id=user_id,
        purchase_type='shard_rush',
        item_details={
            'structure_type': structure_type,
            'to_level': target_level, 'rush_cost_shards': rush_cost,
            'rush_pct': eligibility.get('rush_pct'),
        },
    )

    log_activity(
        user_id, 'infrastructure', 'shard_rush',
        f"Shard Rush: {structure_type.replace('_', ' ').title()} Lv{target_level}",
        amount=rush_cost, detail='infrastructure · rushed',
        source_table='user_infrastructure',
        metadata={'structure_type': structure_type, 'to_level': target_level, 'rush_cost': rush_cost},
    )

    logger.info(f"⚡ User {user_id} Shard Rushed infrastructure {structure_type} to Lv{target_level} for {rush_cost} shards")

    try:
        from flask import session
        from utilities.session_helpers import invalidate_balance_cache
        invalidate_balance_cache(session)
    except Exception:
        pass

    return {
        'success': True,
        'rushed': True,
        'structure_type': structure_type,
        'level': target_level,
        'rush_cost': rush_cost,
        'new_balance': int(new_balance_eth * 10_000_000),
    }
