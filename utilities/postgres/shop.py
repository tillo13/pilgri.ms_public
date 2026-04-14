"""Shop, transactions, infrastructure, upgrades, and action token database operations."""

import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List

from utilities.postgres.core import db_cursor, _fetchone, _fetchall, _get_one, _update, json_serial

logger = logging.getLogger(__name__)


# ============================================================================
# SCHEMA MIGRATIONS (infrastructure-related)
# ============================================================================

def ensure_dust_covered_column() -> bool:
    """Ensure the dust_covered column exists in colony_infrastructure table"""
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'pilgrim' AND table_name = 'colony_infrastructure' AND column_name = 'dust_covered'
                    ) THEN
                        ALTER TABLE pilgrim.colony_infrastructure ADD COLUMN dust_covered BOOLEAN DEFAULT FALSE;
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'pilgrim' AND table_name = 'colony_infrastructure' AND column_name = 'dust_covered_at'
                    ) THEN
                        ALTER TABLE pilgrim.colony_infrastructure ADD COLUMN dust_covered_at TIMESTAMP;
                    END IF;
                END $$;
            """)
            return True
    except Exception as e:
        logger.error(f"❌ Failed to ensure dust_covered column: {e}")
        return False


def set_infrastructure_dust_covered(user_id: int, structure_type: str, is_covered: bool) -> bool:
    """Set dust_covered status for a user's infrastructure"""
    try:
        ensure_dust_covered_column()
        with db_cursor(commit=True) as cur:
            if is_covered:
                cur.execute("""
                    UPDATE pilgrim.colony_infrastructure
                    SET dust_covered = TRUE, dust_covered_at = NOW(), updated_at = NOW()
                    WHERE user_id = %s AND structure_type = %s AND status = 'active'
                """, (user_id, structure_type))
            else:
                cur.execute("""
                    UPDATE pilgrim.colony_infrastructure
                    SET dust_covered = FALSE, dust_covered_at = NULL, updated_at = NOW()
                    WHERE user_id = %s AND structure_type = %s AND status = 'active'
                """, (user_id, structure_type))
            logger.info(f"{'🌫️' if is_covered else '✨'} Set dust_covered={is_covered} for user {user_id} structure {structure_type}")
            return True
    except Exception as e:
        logger.error(f"❌ Failed to set dust_covered: {e}")
        return False


# ============================================================================
# TRANSACTIONS
# ============================================================================

def create_depot_transaction(user_id: int, wallet_address: str, purchase_type: str, amount_eth: float, tx_hash: str,
                              block_number: int = None, block_timestamp=None, gas_used: int = None,
                              tx_fee_eth: float = None, etherscan_url: str = None, item_details: dict = None,
                              related_asset_id: int = None) -> Optional[int]:
    """Save depot purchase transaction"""
    try:
        with db_cursor(commit=True) as cur:
            item_details_json = json.dumps(item_details, default=json_serial) if item_details else None
            cur.execute("""
                INSERT INTO pilgrim.depot_transactions
                (user_id, wallet_address, purchase_type, amount_eth, tx_hash, block_number,
                 block_timestamp, gas_used, tx_fee_eth, etherscan_url, item_details, related_asset_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
            """, (user_id, wallet_address, purchase_type, amount_eth, tx_hash, block_number,
                  block_timestamp, gas_used, tx_fee_eth, etherscan_url, item_details_json, related_asset_id))
            result = cur.fetchone()
            transaction_id = result['id'] if result else None
            logger.info(f"✅ Transaction saved (ID: {transaction_id}, type: {purchase_type})")
            # Log to unified activity
            from utilities.postgres.activity import log_activity
            title, cat, detail = _format_depot_activity(purchase_type, item_details or {})
            log_activity(user_id, cat, purchase_type, title, amount=float(amount_eth) * 10000000 if amount_eth else 0,
                         detail=detail, tx_hash=tx_hash or '', source_table='depot_transactions', source_id=transaction_id)
            return transaction_id
    except Exception as e:
        logger.error(f"❌ Failed to save transaction: {e}")
        return None


def get_user_depot_transactions(user_id: int, limit: int = 10) -> List[Dict]:
    """Get recent depot transactions for user"""
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT id, user_id, wallet_address, purchase_type, amount_eth, item_details, tx_hash, etherscan_url, related_asset_id, created_at
                FROM pilgrim.depot_transactions WHERE user_id = %s ORDER BY created_at DESC LIMIT %s
            """, (user_id, limit))
            return _fetchall(cur)
    except Exception as e:
        logger.error(f"❌ Failed to get transactions: {e}")
        return []


def _format_depot_activity(purchase_type: str, details: dict) -> tuple:
    """Format depot transaction into rich activity display. Returns: (title, category, detail_text)"""
    title = purchase_type.replace('_', ' ').title()
    category = 'purchase'
    detail_text = ''

    if purchase_type == 'discovery_analysis':
        item_name = details.get('item_name', 'Discovery')
        rarity = details.get('rarity', 'common').title()
        quantity = details.get('quantity_analyzed', 1)
        shards = details.get('shards_extracted', 0)
        sv_bonus = details.get('sv_bonus', 0)  # Bug #1135
        if details.get('bulk_extraction'):
            by_rarity = details.get('by_rarity', {}) or {}
            title = "Sharded: Bulk Extraction"
            rarity = f"{by_rarity.get('common', 0)}c+{by_rarity.get('uncommon', 0)}u"
        else:
            title = f"Sharded: {item_name}"
        category = 'sharding'
        sv_str = f" + {sv_bonus} SV" if sv_bonus else ""
        detail_text = f"{rarity} · {quantity}x → {shards:.0f} shards{sv_str}"
    elif purchase_type == 'infrastructure_income':
        hours = details.get('hours_accumulated', 0)
        structures = details.get('structures', [])
        struct_names = ', '.join([s.replace('_', ' ').title() for s in structures[:2]])
        title = "Infrastructure Income"
        category = 'income'
        detail_text = f"{struct_names} · {hours:.1f}h"
    elif purchase_type == 'infrastructure_purchase':
        structure = details.get('structure_type', details.get('structure_name', 'Building'))
        title = f"Built: {structure.replace('_', ' ').title()}"
        category = 'infrastructure'
    elif purchase_type == 'infrastructure_completion':
        structure = details.get('structure_type', details.get('structure_name', 'Building'))
        title = f"Completed: {structure.replace('_', ' ').title()}"
        category = 'infrastructure'
    elif purchase_type == 'shop_upgrade':
        item_name = details.get('item_name', details.get('item_key', 'Equipment'))
        title = f"Equipped: {item_name.replace('_', ' ').title()}"
        category = 'equipment'
    elif purchase_type == 'expedition_launch':
        destination = details.get('destination_name', 'Mars')
        vehicle = details.get('vehicle_type', 'Rover')
        title = f"Expedition: {destination}"
        category = 'expedition'
        detail_text = vehicle.replace('_', ' ').title()
    elif purchase_type == 'expedition_discovery':
        item_name = details.get('item_name', 'Discovery')
        title = f"Found: {item_name}"
        category = 'discovery'
    elif purchase_type == 'shard_infusion':
        title = "Shard Infusion"
        category = 'upgrade'
        stats_changed = details.get('stats_changed', {})
        if stats_changed:
            boosts = [f"+{v} {k}" for k, v in stats_changed.items() if v > 0]
            detail_text = ', '.join(boosts[:3]) if boosts else 'Stats boosted'
    elif purchase_type == 'character_modification':
        title = "Captain Modification"
        category = 'modification'
    elif purchase_type == 'video_generation':
        title = "Video Generated"
        category = 'media'
    elif purchase_type == 'transmutation':
        from_item = details.get('from_item', 'Item')
        to_item = details.get('to_item', 'New Item')
        title = f"Transmuted: {from_item}"
        category = 'transmutation'
        detail_text = f"→ {to_item}"
    elif details.get('raw'):
        title = str(details['raw']).replace('_', ' ').title()

    return title, category, detail_text


def get_unified_activity(user_id: int, limit: int = 500) -> List[Dict]:
    """Get unified activity log from activity_events table (single source of truth)."""
    from utilities.postgres.activity import get_activity
    rows = get_activity(user_id, limit=limit)
    return [{
        'category': r['category'], 'title': r['title'], 'detail': r.get('detail', ''),
        'amount': float(r.get('amount') or 0), 'tx_hash': r.get('tx_hash', ''),
        'timestamp': r.get('timestamp', ''), 'image_url': r.get('image_url', ''),
        'status': (r.get('metadata') or {}).get('status', ''),
        **(r.get('metadata') or {})
    } for r in rows]


# ============================================================================
# INFRASTRUCTURE
# ============================================================================

def create_infrastructure(user_id, structure_type, structure_name, latitude, longitude,
                          cost_sepolia, build_duration, generates_resource, generation_rate, ready_at=None):
    """Create infrastructure record"""
    try:
        logger.info(f"📦 Creating infrastructure: user={user_id}, type={structure_type}, name={structure_name}")
        logger.info(f"   lat={latitude}, lon={longitude}, cost={cost_sepolia}, duration={build_duration}")
        logger.info(f"   generates={generates_resource}, rate={generation_rate}, ready_at={ready_at}")
        with db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO pilgrim.colony_infrastructure
                (user_id, structure_type, structure_name, latitude, longitude, cost_sepolia, build_duration_seconds,
                 generates_resource, generation_rate, status, build_started_at, ready_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'building', NOW(), %s) RETURNING id
            """, (user_id, structure_type, structure_name, latitude, longitude, cost_sepolia, build_duration,
                  generates_resource, generation_rate, ready_at))
            result = cur.fetchone()
            infra_id = result['id'] if result else None
            logger.info(f"✅ Infrastructure created with ID: {infra_id}")
            from utilities.postgres.activity import log_activity
            log_activity(user_id, 'infrastructure', 'infrastructure_build',
                         f"Building: {structure_name or structure_type.replace('_', ' ').title()}",
                         amount=float(cost_sepolia) * 10000000 if cost_sepolia else 0,
                         source_table='colony_infrastructure', source_id=infra_id,
                         metadata={'structure_type': structure_type, 'build_duration': build_duration})
            return infra_id
    except Exception as e:
        logger.error(f"❌ Failed to create infrastructure: {type(e).__name__}: {e}")
        import traceback
        logger.error(f"   Traceback: {traceback.format_exc()}")
        return None


def get_user_infrastructure(user_id, structure_type=None):
    """Get user's infrastructure with auto-activation"""
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE pilgrim.colony_infrastructure
                SET status = 'active', build_completed_at = COALESCE(build_completed_at, NOW()), updated_at = NOW()
                WHERE user_id = %s AND status = 'building' AND ready_at <= NOW()
            """, (user_id,))
            if cur.rowcount > 0:
                logger.info(f"✅ Auto-activated {cur.rowcount} structure(s) for user {user_id}")
            if structure_type:
                cur.execute("SELECT * FROM pilgrim.colony_infrastructure WHERE user_id = %s AND structure_type = %s ORDER BY created_at DESC", (user_id, structure_type))
            else:
                cur.execute("SELECT * FROM pilgrim.colony_infrastructure WHERE user_id = %s ORDER BY created_at DESC", (user_id,))
            return _fetchall(cur)
    except Exception as e:
        logger.error(f"❌ Failed to get infrastructure: {e}")
        return []


def get_infrastructure_by_id(construction_id):
    """Get single infrastructure by ID"""
    return _get_one('colony_infrastructure', 'id = %s', (construction_id,), 'infrastructure')


def update_infrastructure_status(construction_id, new_status):
    """Update infrastructure status"""
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE pilgrim.colony_infrastructure
                SET status = %s, build_completed_at = CASE WHEN %s = 'active' THEN NOW() ELSE build_completed_at END, updated_at = NOW()
                WHERE id = %s
            """, (new_status, new_status, construction_id))
            return True
    except Exception as e:
        logger.error(f"❌ Failed to update infrastructure: {e}")
        return False


# ============================================================================
# SHOP / UPGRADES
# ============================================================================

def get_user_upgrades(user_id: int, active_only: bool = False) -> List[Dict]:
    """Get all upgrades owned by a user. If active_only=True, only returns completed builds."""
    try:
        with db_cursor() as cur:
            if active_only:
                cur.execute("""
                    SELECT item_id, quantity, purchased_at, tx_hash, status, ready_at
                    FROM pilgrim.user_upgrades
                    WHERE user_id = %s AND status = 'active'
                """, (user_id,))
            else:
                cur.execute("""
                    SELECT item_id, quantity, purchased_at, tx_hash, status, ready_at
                    FROM pilgrim.user_upgrades
                    WHERE user_id = %s
                """, (user_id,))
            return _fetchall(cur)
    except Exception as e:
        logger.error(f"❌ Failed to get user upgrades: {e}")
        return []


def get_user_upgrade(user_id: int, item_id: str) -> Optional[Dict]:
    """Get a specific upgrade for a user"""
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT item_id, quantity, purchased_at, tx_hash, status, ready_at
                FROM pilgrim.user_upgrades
                WHERE user_id = %s AND item_id = %s
            """, (user_id, item_id))
            return _fetchone(cur)
    except Exception as e:
        logger.error(f"❌ Failed to get user upgrade: {e}")
        return None


def add_user_upgrade(user_id: int, item_id: str, tx_hash: str = None) -> bool:
    """Add or increment an upgrade for a user (with build time)"""
    from config import get_shop_item, get_build_time_seconds
    try:
        item = get_shop_item(item_id)
        build_seconds = get_build_time_seconds(item['cost_display']) if item else 259200

        with db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO pilgrim.user_upgrades (user_id, item_id, quantity, tx_hash, status, ready_at)
                VALUES (%s, %s, 1, %s, 'building', NOW() + INTERVAL '%s seconds')
                ON CONFLICT (user_id, item_id)
                DO UPDATE SET quantity = pilgrim.user_upgrades.quantity + 1,
                              purchased_at = NOW(),
                              status = 'building',
                              ready_at = NOW() + INTERVAL '%s seconds'
            """, (user_id, item_id, tx_hash, build_seconds, build_seconds))
            return True
    except Exception as e:
        logger.error(f"❌ Failed to add user upgrade: {e}")
        return False


def get_user_upgrade_count(user_id: int, item_id: str) -> int:
    """Get quantity of a specific upgrade owned by user"""
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT COALESCE(quantity, 0) as qty
                FROM pilgrim.user_upgrades
                WHERE user_id = %s AND item_id = %s
            """, (user_id, item_id))
            result = cur.fetchone()
            return result['qty'] if result else 0
    except Exception as e:
        logger.error(f"❌ Failed to get upgrade count: {e}")
        return 0


def complete_ready_builds(user_id: int) -> List[str]:
    """Mark builds as active if their ready_at time has passed. Returns list of completed item_ids."""
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE pilgrim.user_upgrades
                SET status = 'active'
                WHERE user_id = %s AND status = 'building' AND ready_at <= NOW()
                RETURNING item_id
            """, (user_id,))
            results = cur.fetchall()
            return [r['item_id'] for r in results] if results else []
    except Exception as e:
        logger.error(f"❌ Failed to complete ready builds: {e}")
        return []


def get_building_upgrades(user_id: int) -> List[Dict]:
    """Get all upgrades currently building for a user"""
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT item_id, quantity, purchased_at, ready_at,
                       EXTRACT(EPOCH FROM (ready_at - NOW())) as seconds_remaining
                FROM pilgrim.user_upgrades
                WHERE user_id = %s AND status = 'building' AND ready_at > NOW()
                ORDER BY ready_at
            """, (user_id,))
            return _fetchall(cur)
    except Exception as e:
        logger.error(f"❌ Failed to get building upgrades: {e}")
        return []


# ============================================================================
# EMAIL ACTION TOKENS
# ============================================================================

def ensure_action_tokens_table() -> bool:
    """Create the action tokens table if it doesn't exist"""
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS pilgrim.used_action_tokens (
                    nonce VARCHAR(32) PRIMARY KEY,
                    user_id INTEGER REFERENCES pilgrim.users(id),
                    action VARCHAR(50) NOT NULL,
                    used_at TIMESTAMP DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_action_tokens_used_at
                ON pilgrim.used_action_tokens(used_at)
            """)
            return True
    except Exception as e:
        logger.error(f"❌ Failed to create action tokens table: {e}")
        return False


def is_action_token_used(nonce: str) -> bool:
    """Check if an action token has already been used"""
    try:
        with db_cursor() as cur:
            cur.execute("SELECT 1 FROM pilgrim.used_action_tokens WHERE nonce = %s", (nonce,))
            return cur.fetchone() is not None
    except Exception as e:
        logger.error(f"❌ Failed to check token usage: {e}")
        return True  # Fail closed


def mark_action_token_used(nonce: str, user_id: int, action: str) -> bool:
    """Mark an action token as used"""
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO pilgrim.used_action_tokens (nonce, user_id, action, used_at)
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT (nonce) DO NOTHING
            """, (nonce, user_id, action))
            return True
    except Exception as e:
        logger.error(f"❌ Failed to mark token used: {e}")
        return False


# ============================================================================
# MARS MISSION MESSAGES
# ============================================================================

def get_next_mars_message():
    """Get random Mars mission message with weighted probability"""
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                SELECT id, mission_name, message_text, mission_date, sol_number, orbit_number, usage_count
                FROM pilgrim.mars_mission_messages ORDER BY (usage_count + 1) * RANDOM() LIMIT 1
            """)
            message = cur.fetchone()
            if message:
                cur.execute("UPDATE pilgrim.mars_mission_messages SET usage_count = usage_count + 1, last_used_at = NOW(), updated_at = NOW() WHERE id = %s",
                            (message['id'],))
            return dict(message) if message else None
    except Exception as e:
        logger.error(f"❌ Failed to get Mars message: {e}")
        return None
