"""ARIA Fragment Bond bonuses — per Luke's #1402 spec (2026-04-19).

After each ARIA bond, the captain picks ONE bonus from a 6-slot menu (A–F).
Max 3 picks per captain across all their bonds. No duplicates. Permanent.

Bonus effects (each +5%):
  A — SV gain
  B — Expedition speed
  C — Depot build speed (faster = lower build_time_mult)
  D — Shard hourly rate
  E — Max vehicle range
  F — Discovery rate

Storage: pilgrim.aria_bond_bonuses(user_id, bond_id, bonus_type) with
UNIQUE(user_id, bond_id) and UNIQUE(user_id, bonus_type).
"""

import logging
from typing import Dict, List, Optional

from utilities.postgres.core import db_cursor

logger = logging.getLogger(__name__)


# Bonus definitions — single source of truth for both UI labels and effect application.
BOND_BONUSES = {
    'A': {
        'code': 'A', 'name': 'SV Bonus',
        'description': '+5% Science Value gain on every claim',
        'effect_key': 'sv_mult', 'effect_value': 1.05,
        'icon': '🔬',
    },
    'B': {
        'code': 'B', 'name': 'Expedition Speed',
        'description': '+5% expedition speed (vehicles travel faster)',
        'effect_key': 'expedition_speed_mult', 'effect_value': 1.05,
        'icon': '🚀',
    },
    'C': {
        'code': 'C', 'name': 'Depot Build Speed',
        'description': '+5% faster building / upgrade construction',
        'effect_key': 'build_time_mult', 'effect_value': 0.95,  # lower = faster
        'icon': '🏗️',
    },
    'D': {
        'code': 'D', 'name': 'Shard Hourly Bonus',
        'description': '+5% shard generation per hour',
        'effect_key': 'shards_mult', 'effect_value': 1.05,
        'icon': '💎',
    },
    'E': {
        'code': 'E', 'name': 'Vehicle Range',
        'description': '+5% maximum vehicle range on expeditions',
        'effect_key': 'vehicle_range_mult', 'effect_value': 1.05,
        'icon': '🛞',
    },
    'F': {
        'code': 'F', 'name': 'Discovery Rate',
        'description': '+5% chance to find rarer discoveries',
        'effect_key': 'discovery_chance_bonus', 'effect_value': 0.05,  # additive bonus
        'icon': '🔍',
    },
}

MAX_BONUSES_PER_CAPTAIN = 3


_SCHEMA_ENSURED = False


def ensure_bond_bonus_table():
    """Idempotent migration."""
    global _SCHEMA_ENSURED
    if _SCHEMA_ENSURED:
        return
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS pilgrim.aria_bond_bonuses (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    bond_id INTEGER NOT NULL,
                    bonus_type CHAR(1) NOT NULL CHECK (bonus_type IN ('A','B','C','D','E','F')),
                    chosen_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    UNIQUE(user_id, bond_id),
                    UNIQUE(user_id, bonus_type)
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_bond_bonus_user ON pilgrim.aria_bond_bonuses(user_id)")
        _SCHEMA_ENSURED = True
    except Exception as e:
        logger.error(f"ensure_bond_bonus_table failed: {e}")


def get_user_bond_bonuses(user_id: int) -> Dict[int, str]:
    """Return {bond_id: bonus_type} for everything this captain has picked."""
    ensure_bond_bonus_table()
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT bond_id, bonus_type FROM pilgrim.aria_bond_bonuses
                WHERE user_id = %s
            """, (user_id,))
            return {r['bond_id']: r['bonus_type'] for r in cur.fetchall()}
    except Exception as e:
        logger.error(f"get_user_bond_bonuses failed user={user_id}: {e}")
        return {}


def get_user_bond_effects(user_id: int) -> Dict[str, float]:
    """Return effect overrides this captain has earned from bond picks.

    Returns dict like {'sv_mult': 1.10, 'build_time_mult': 0.95, ...}.
    Only includes keys the captain has actually picked. Caller multiplies/adds these
    into the appropriate effect slot.
    """
    picks = get_user_bond_bonuses(user_id)
    out: Dict[str, float] = {}
    for bonus_type in picks.values():
        spec = BOND_BONUSES.get(bonus_type)
        if not spec:
            continue
        key = spec['effect_key']
        val = spec['effect_value']
        if key == 'discovery_chance_bonus':
            # Additive
            out[key] = out.get(key, 0.0) + val
        elif key == 'build_time_mult':
            # Multiplicative, lower = faster
            out[key] = out.get(key, 1.0) * val
        else:
            # Multiplicative, higher = better
            out[key] = out.get(key, 1.0) * val
    return out


def pick_bond_bonus(user_id: int, bond_id: int, bonus_type: str) -> Dict:
    """Validate and persist a bond-bonus pick.

    Returns dict with success/error. Validates:
    - bond_id is bonded with this user as participant
    - bonus_type is valid (A..F)
    - captain has < MAX_BONUSES_PER_CAPTAIN already picked
    - bonus_type not already used by this captain on another bond
    - this bond doesn't already have a pick from this captain
    """
    ensure_bond_bonus_table()
    if bonus_type not in BOND_BONUSES:
        return {'success': False, 'error': f'Invalid bonus_type {bonus_type!r}'}
    try:
        with db_cursor(commit=True) as cur:
            # Verify bond is bonded + user is a participant
            cur.execute("""
                SELECT id, user_id_1, user_id_2, status, landmark_name
                FROM pilgrim.aria_bonds WHERE id = %s
            """, (bond_id,))
            bond = cur.fetchone()
            if not bond:
                return {'success': False, 'error': 'Bond not found'}
            if user_id not in (bond['user_id_1'], bond['user_id_2']):
                return {'success': False, 'error': 'You are not a participant in this bond'}
            if bond['status'] != 'bonded':
                return {'success': False, 'error': f'Bond not yet completed (status: {bond["status"]})'}

            # Already picked for this bond?
            cur.execute("""
                SELECT bonus_type FROM pilgrim.aria_bond_bonuses
                WHERE user_id = %s AND bond_id = %s
            """, (user_id, bond_id))
            existing = cur.fetchone()
            if existing:
                return {'success': False, 'error': f'You already picked {existing["bonus_type"]} for this bond'}

            # Cap check
            cur.execute("""
                SELECT bonus_type FROM pilgrim.aria_bond_bonuses WHERE user_id = %s
            """, (user_id,))
            picks = [r['bonus_type'] for r in cur.fetchall()]
            if len(picks) >= MAX_BONUSES_PER_CAPTAIN:
                return {'success': False, 'error': f'Max {MAX_BONUSES_PER_CAPTAIN} bond bonuses already chosen'}
            if bonus_type in picks:
                return {'success': False, 'error': f'You already have bonus {bonus_type} from another bond'}

            cur.execute("""
                INSERT INTO pilgrim.aria_bond_bonuses (user_id, bond_id, bonus_type)
                VALUES (%s, %s, %s) RETURNING id, chosen_at
            """, (user_id, bond_id, bonus_type))
            row = cur.fetchone()
            from utilities.postgres.activity import log_activity
            log_activity(user_id, 'aria', 'bond_bonus_chosen',
                         f"Bond bonus chosen: {BOND_BONUSES[bonus_type]['name']}",
                         detail=f"bond #{bond_id} ({bond['landmark_name']})",
                         source_table='aria_bond_bonuses', source_id=row['id'])

        spec = BOND_BONUSES[bonus_type]
        return {
            'success': True,
            'bonus_type': bonus_type,
            'bonus_name': spec['name'],
            'bonus_description': spec['description'],
            'picks_remaining': MAX_BONUSES_PER_CAPTAIN - (len(picks) + 1),
        }
    except Exception as e:
        logger.error(f"pick_bond_bonus failed user={user_id} bond={bond_id} type={bonus_type}: {e}")
        return {'success': False, 'error': str(e)}


def get_bond_bonus_state_for_user(user_id: int) -> Dict:
    """Render-data for the /signal /expeditions ARIA bond UI.

    Returns:
        {
          'picks': {bond_id: {'code': 'A', 'name': '…', 'description': '…'}},
          'picks_count': int,
          'picks_remaining': int (3 - picks_count),
          'unused_bonuses': [list of {code, name, description, icon}],
          'bonuses_catalog': BOND_BONUSES (for picker UI),
          'max_picks': MAX_BONUSES_PER_CAPTAIN,
        }
    """
    picks_raw = get_user_bond_bonuses(user_id)  # {bond_id: 'A'}
    picks: Dict[int, Dict] = {}
    used_codes = set()
    for bond_id, bonus_type in picks_raw.items():
        spec = BOND_BONUSES.get(bonus_type, {})
        picks[bond_id] = {'code': bonus_type, **spec}
        used_codes.add(bonus_type)

    unused = [{'code': k, **v} for k, v in BOND_BONUSES.items() if k not in used_codes]
    return {
        'picks': picks,
        'picks_count': len(picks_raw),
        'picks_remaining': max(0, MAX_BONUSES_PER_CAPTAIN - len(picks_raw)),
        'unused_bonuses': unused,
        'bonuses_catalog': BOND_BONUSES,
        'max_picks': MAX_BONUSES_PER_CAPTAIN,
    }
