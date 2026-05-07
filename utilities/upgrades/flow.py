"""Purchase / upgrade action flow (write paths).

handle_upgrade_request = route-glue wrapper for POST /api/upgrade.
perform_upgrade = the real write: balance check, DB update, build timer,
background blockchain tx, image generation hook.
"""

import logging
from typing import Dict, Any
from utilities.postgres.core import db_cursor

logger = logging.getLogger(__name__)


def handle_upgrade_request(user_id, data: dict, flask_session) -> Dict[str, Any]:
    """Route-glue wrapper for POST /api/upgrade.

    Validates login + payload, calls perform_upgrade, and invalidates the
    cached balance on success so the next nav tick shows the new value.
    """
    if not user_id:
        return {'success': False, 'error': 'Not logged in'}

    category = (data or {}).get('category')
    item_key = (data or {}).get('item_key')
    if not category or not item_key:
        return {'success': False, 'error': 'Missing category or item_key'}

    result = perform_upgrade(user_id, category, item_key)

    if result.get('success'):
        flask_session.pop('_bal', None)
        flask_session.modified = True

    return result


def perform_upgrade(user_id: int, category: str, item_key: str) -> Dict[str, Any]:
    """
    Upgrade an item to the next level.
    Handles both unlock (0→1) and upgrade (1→2, etc.)
    Uses build_time_days from config - upgrade isn't usable until timer completes.

    Returns:
        {
            'success': True/False,
            'error': 'message' (if failed),
            'category': 'vehicles',
            'item_key': 'rover',
            'old_level': 1,
            'new_level': 2,
            'cost': 5000,
            'stats': {...},  # New level stats
            'ready_at': '2026-02-05T12:00:00Z',  # When upgrade completes
            'build_time_days': 2
        }
    """
    from datetime import datetime, timezone, timedelta
    from utilities.depot_utils import get_fast_balance_and_wallet_info, display_to_eth
    from utilities.upgrades.catalog import get_item_config
    from utilities.upgrades.state import (
        ensure_upgrades_table,
        get_upgrade_build_status,
        count_concurrent_upgrades,
        get_user_upgrade_cap,
        get_user_upgrade_level,
        get_upgrade_stats,
    )
    from utilities.upgrades.effects import get_user_upgrade_effects

    try:
        ensure_upgrades_table()

        # DOUBLE-CLICK PROTECTION: Check if upgrade already in progress
        build_status = get_upgrade_build_status(user_id, category, item_key)
        if build_status and build_status.get('is_building'):
            return {
                'success': False,
                'error': 'Upgrade already in progress. Please wait for it to complete.',
                'is_building': True,
                'ready_at': build_status.get('ready_at'),
                'seconds_remaining': build_status.get('seconds_remaining')
            }

        # CONCURRENT UPGRADE CAP: Check if user has too many upgrades in progress
        current_building = count_concurrent_upgrades(user_id)
        max_cap = get_user_upgrade_cap(user_id)
        if current_building >= max_cap:
            return {
                'success': False,
                'error': f'Maximum concurrent upgrades reached ({current_building}/{max_cap}). Wait for one to complete or upgrade your Habitat Module.',
                'cap_reached': True,
                'current_building': current_building,
                'max_cap': max_cap
            }

        # Get current level
        current_level = get_user_upgrade_level(user_id, category, item_key)
        next_level = current_level + 1

        # Get item config (handles both upgrades and infrastructure)
        item_config = get_item_config(category, item_key)
        if not item_config:
            return {'success': False, 'error': f'Unknown item: {category}/{item_key}'}

        # Infrastructure-specific: building must exist before it can be upgraded
        if category == 'infrastructure':
            if current_level == 0:
                return {'success': False, 'error': f'You must build {item_config["name"]} first before upgrading it.'}

        # Check max level
        max_level = item_config.get('max_level', 1)
        if current_level >= max_level:
            return {'success': False, 'error': 'Already at max level'}

        # Get next level stats (includes cost)
        next_stats = get_upgrade_stats(category, item_key, next_level)
        if not next_stats:
            return {'success': False, 'error': 'No upgrade available'}

        # Per-level upgrade prereqs (#1436). next_stats['level_requires'] is
        # {building_key: required_level}. Enforced for infrastructure paths
        # only — equipment upgrades don't currently use this field.
        level_requires = next_stats.get('level_requires') or {}
        if level_requires and category == 'infrastructure':
            from utilities.upgrades_utils import get_all_infrastructure_levels
            from config_infrastructure import INFRASTRUCTURE_CATALOG
            current_levels = get_all_infrastructure_levels(user_id) or {}
            missing = []
            for req_key, req_lvl in level_requires.items():
                have = int(current_levels.get(req_key, 0))
                if have < req_lvl:
                    pretty = INFRASTRUCTURE_CATALOG.get(req_key, {}).get('name', req_key)
                    missing.append(f'{pretty} Lv{req_lvl} (have Lv{have})')
            if missing:
                return {
                    'success': False,
                    'error': 'Cannot upgrade yet — missing prerequisites: ' + ', '.join(missing),
                    'missing_prereqs': missing,
                }

        cost_display = next_stats.get('cost', 0)
        build_time_days = next_stats.get('build_time_days', 0)

        # Check balance (FAST: uses DB cache, not blockchain)
        total_balance, wallet_info, primary_wallet = get_fast_balance_and_wallet_info(user_id)
        if total_balance < cost_display:
            return {
                'success': False,
                'error': f'Insufficient shards. Need {cost_display:.0f}, have {total_balance:.0f}',
                'cost': cost_display,
                'balance': total_balance
            }

        # Deduct cost immediately, blockchain tx fires in background
        tx_hash = None
        if cost_display > 0 and primary_wallet:
            cost_eth = display_to_eth(cost_display)

            # Immediate DB balance deduction
            from utilities.postgres.wallets import update_sepolia_wallet_balance
            new_balance_eth = float(primary_wallet.get('current_balance_eth', 0)) - cost_eth
            update_sepolia_wallet_balance(primary_wallet.get('wallet_address'), new_balance_eth)

            # Background blockchain tx + transaction logging
            from utilities.depot_utils import background_blockchain_tx
            background_blockchain_tx(
                wallet_address=primary_wallet.get('wallet_address'),
                wallet_private_key=primary_wallet.get('wallet_private_key'),
                amount_eth=cost_eth,
                reason=f"Upgrade: {item_config['name']} to {next_stats.get('name', f'Lv{next_level}')}",
                user_id=user_id, purchase_type='upgrade_purchase',
                item_details={
                    'category': category, 'item_key': item_key,
                    'item_name': item_config['name'],
                    'from_level': current_level, 'to_level': next_level,
                    'level_name': next_stats.get('name', f'Level {next_level}'),
                    'cost_shards': cost_display
                }
            )

        # Calculate ready_at based on build time (apply build speed bonuses)
        ready_at = None
        if build_time_days > 0:
            effects = get_user_upgrade_effects(user_id)
            build_mult = effects.get('build_time_mult', 1.0)
            adjusted_days = max(0.01, build_time_days * build_mult)  # Floor: ~15 min
            ready_at = datetime.now(timezone.utc) + timedelta(days=adjusted_days)

        # Update database with build timer
        with db_cursor(commit=True) as cur:
            if build_time_days > 0:
                # Start build timer - set pending_level and ready_at, keep current level
                cur.execute("""
                    INSERT INTO pilgrim.player_upgrades
                    (user_id, category, item_key, level, pending_level, ready_at, upgraded_at, tx_hash)
                    VALUES (%s, %s, %s, %s, %s, %s, NOW(), %s)
                    ON CONFLICT (user_id, category, item_key)
                    DO UPDATE SET pending_level = %s, ready_at = %s, upgraded_at = NOW(), tx_hash = %s
                """, (
                    user_id, category, item_key, current_level, next_level, ready_at, tx_hash,
                    next_level, ready_at, tx_hash
                ))
                logger.info(f"⏱️ User {user_id} started upgrade {category}/{item_key} to Lv{next_level} (ready in {build_time_days} days)")
                from utilities.postgres.activity import log_activity
                log_activity(user_id, 'upgrade', 'upgrade_started',
                             f"Upgrading: {item_key.replace('_', ' ').title()} Lv{next_level}",
                             amount=cost_display, detail=f"{category} · {build_time_days}d build",
                             tx_hash=tx_hash or '', source_table='player_upgrades',
                             metadata={'category': category, 'item_key': item_key, 'from_level': current_level, 'to_level': next_level})
            else:
                # Instant upgrade (build_time_days = 0)
                cur.execute("""
                    INSERT INTO pilgrim.player_upgrades
                    (user_id, category, item_key, level, pending_level, ready_at, upgraded_at, tx_hash)
                    VALUES (%s, %s, %s, %s, NULL, NULL, NOW(), %s)
                    ON CONFLICT (user_id, category, item_key)
                    DO UPDATE SET level = %s, pending_level = NULL, ready_at = NULL, upgraded_at = NOW(), tx_hash = %s
                """, (user_id, category, item_key, next_level, tx_hash, next_level, tx_hash))
                logger.info(f"✅ User {user_id} instantly upgraded {category}/{item_key} to Lv{next_level}")
                from utilities.postgres.activity import log_activity
                log_activity(user_id, 'upgrade', 'upgrade_complete',
                             f"Upgraded: {item_key.replace('_', ' ').title()} Lv{next_level}",
                             amount=cost_display, detail=category, tx_hash=tx_hash or '',
                             source_table='player_upgrades',
                             metadata={'category': category, 'item_key': item_key, 'from_level': current_level, 'to_level': next_level})

        # First-Reveal: Check if image needs generation (for build timer, do this in background)
        is_first_reveal = False
        try:
            if category == 'infrastructure':
                from utilities.upgrade_image_utils import maybe_generate_infrastructure_image
                image_result = maybe_generate_infrastructure_image(item_key, next_level, user_id)
            else:
                from utilities.upgrade_image_utils import maybe_generate_upgrade_image
                image_result = maybe_generate_upgrade_image(category, item_key, next_level, user_id)
            is_first_reveal = image_result.get('is_first_reveal', False)
            if is_first_reveal:
                logger.info(f"First Reveal! User {user_id} discovered {category}/{item_key} level {next_level}")
        except Exception as img_err:
            logger.warning(f"Image generation check failed (non-blocking): {img_err}")

        return {
            'success': True,
            'category': category,
            'item_key': item_key,
            'old_level': current_level,
            'new_level': next_level,
            'cost': cost_display,
            'stats': next_stats,
            'item_name': item_config['name'],
            'level_name': next_stats.get('name', f'Level {next_level}'),
            'is_first_reveal': is_first_reveal,
            'build_time_days': build_time_days,
            'ready_at': ready_at.isoformat() if ready_at else None,
            'is_building': build_time_days > 0
        }

    except Exception as e:
        logger.error(f"Failed to perform upgrade: {e}")
        return {'success': False, 'error': str(e)}
