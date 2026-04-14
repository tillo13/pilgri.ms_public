"""User management database operations: CRUD, auth, session hydration, scientist, research, escalation."""

import json
import logging
from typing import Dict, Any, Optional, List

from utilities.postgres.core import db_cursor, _fetchone, _fetchall, _get_one, _update

logger = logging.getLogger(__name__)


# ============================================================================
# SCHEMA MIGRATIONS (user-related)
# ============================================================================

def ensure_scientist_column() -> bool:
    """Ensure the scientist_key column exists in users table"""
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'pilgrim' AND table_name = 'users' AND column_name = 'scientist_key'
                    ) THEN
                        ALTER TABLE pilgrim.users ADD COLUMN scientist_key VARCHAR(50);
                    END IF;
                END $$;
            """)
            return True
    except Exception as e:
        logger.error(f"❌ Failed to ensure scientist column: {e}")
        return False


def ensure_passive_sv_column() -> bool:
    """Ensure the passive_sv_generated column exists in users table"""
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'pilgrim' AND table_name = 'users' AND column_name = 'passive_sv_generated'
                    ) THEN
                        ALTER TABLE pilgrim.users ADD COLUMN passive_sv_generated REAL DEFAULT 0;
                    END IF;
                END $$;
            """)
            return True
    except Exception as e:
        logger.error(f"Failed to ensure passive_sv_generated column: {e}")
        return False


# ============================================================================
# USER CRUD
# ============================================================================

def add_passive_sv(user_id: int, amount: float) -> bool:
    """Add passive Science Value to user's accumulated total."""
    try:
        ensure_passive_sv_column()
        with db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE pilgrim.users
                SET passive_sv_generated = COALESCE(passive_sv_generated, 0) + %s, updated_at = NOW()
                WHERE id = %s
            """, (amount, user_id))
            return True
    except Exception as e:
        logger.error(f"Failed to add passive SV for user {user_id}: {e}")
        return False


def get_passive_sv(user_id: int) -> float:
    """Get user's accumulated passive Science Value."""
    try:
        ensure_passive_sv_column()
        with db_cursor() as cur:
            cur.execute("SELECT COALESCE(passive_sv_generated, 0) as sv FROM pilgrim.users WHERE id = %s", (user_id,))
            row = cur.fetchone()
            return float(row['sv']) if row else 0.0
    except Exception:
        return 0.0


def assign_scientist_to_user(user_id: int, scientist_key: str = None) -> Optional[str]:
    """Assign a scientist to a user. If no key provided, assign randomly."""
    from config import COLONY_SCIENTISTS, get_random_scientist
    try:
        ensure_scientist_column()
        if not scientist_key:
            scientist = get_random_scientist()
            scientist_key = scientist['key']

        with db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE pilgrim.users SET scientist_key = %s, updated_at = NOW()
                WHERE id = %s AND scientist_key IS NULL
            """, (scientist_key, user_id))
            if cur.rowcount > 0:
                logger.info(f"✅ Assigned scientist '{scientist_key}' to user {user_id}")
            return scientist_key
    except Exception as e:
        logger.error(f"❌ Failed to assign scientist: {e}")
        return None


def reassign_scientist(user_id: int, new_scientist_key: str) -> dict:
    """Reassign a user's scientist. Returns success/error dict."""
    from config import COLONY_SCIENTISTS
    if new_scientist_key not in COLONY_SCIENTISTS:
        return {'success': False, 'error': 'Unknown scientist'}
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("UPDATE pilgrim.users SET scientist_key = %s, updated_at = NOW() WHERE id = %s",
                        (new_scientist_key, user_id))
            logger.info(f"🔬 Reassigned scientist to '{new_scientist_key}' for user {user_id}")
            return {'success': True, 'scientist_key': new_scientist_key}
    except Exception as e:
        logger.error(f"❌ Failed to reassign scientist: {e}")
        return {'success': False, 'error': str(e)}


def reassign_scientist_flow(user_id: int, new_key: str, flask_session) -> dict:
    """Full scientist-swap flow: validate, auto-claim pending shards + SV,
    reassign, log activity, reset SV payout timestamps, clear nav cache.

    Returns the payload to send back to the client.
    """
    from config import COLONY_SCIENTISTS

    new_key = (new_key or '').strip()
    if not new_key or new_key not in COLONY_SCIENTISTS:
        return {'success': False, 'error': 'Invalid scientist'}

    current = get_user_scientist(user_id)
    if current and current.get('key') == new_key:
        return {'success': False, 'error': 'Already your scientist'}

    shards_claimed = 0
    sv_recorded = 0
    try:
        from utilities.infrastructure_utils import claim_accumulated_income
        claim_result = claim_accumulated_income(user_id, flask_session)
        if claim_result.get('success'):
            shards_claimed = claim_result.get('accumulated', 0)
    except Exception:
        pass
    try:
        from utilities.infrastructure_utils import record_science_value
        sv_result = record_science_value(user_id)
        if sv_result.get('success'):
            sv_recorded = sv_result.get('sv_recorded', 0)
    except Exception:
        pass

    result = reassign_scientist(user_id, new_key)
    if result.get('success'):
        from utilities.postgres.activity import log_activity
        new_sci = COLONY_SCIENTISTS[new_key]
        old_name = current.get('name', 'None') if current else 'None'
        log_activity(user_id, 'scientist_reassign', 'reassign',
                     f'{old_name} → {new_sci["name"]}')
        with db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE pilgrim.colony_infrastructure
                SET last_payout_at = NOW(), updated_at = NOW()
                WHERE user_id = %s AND status = 'active'
            """, (user_id,))
        flask_session.pop('_nav', None)
        flask_session.modified = True
        if sv_recorded > 0:
            result['sv_auto_recorded'] = sv_recorded
        if shards_claimed > 0:
            result['shards_auto_claimed'] = shards_claimed
    return result


def get_user_scientist(user_id: int) -> Optional[Dict]:
    """Get the scientist assigned to a user"""
    from config import COLONY_SCIENTISTS
    try:
        ensure_scientist_column()
        with db_cursor() as cur:
            cur.execute("SELECT scientist_key FROM pilgrim.users WHERE id = %s", (user_id,))
            result = cur.fetchone()
            if result and result.get('scientist_key'):
                key = result['scientist_key']
                if key in COLONY_SCIENTISTS:
                    return {'key': key, **COLONY_SCIENTISTS[key]}
            return None
    except Exception as e:
        logger.error(f"❌ Failed to get user scientist: {e}")
        return None


def upsert_user(user_data: Dict[str, Any]) -> Optional[int]:
    """Create or update user record from Google OAuth data"""
    try:
        logger.info(f"🔐 UPSERT USER - google_id: {user_data.get('sub')}, email: {user_data.get('email')}")
        with db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO pilgrim.users
                (google_id, email, name, given_name, family_name, picture,
                 email_verified, locale, first_login, last_login, previous_login, login_count)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW(), NOW(), 1)
                ON CONFLICT (google_id) DO UPDATE SET
                    email = EXCLUDED.email, name = EXCLUDED.name, given_name = EXCLUDED.given_name,
                    family_name = EXCLUDED.family_name, picture = EXCLUDED.picture,
                    email_verified = EXCLUDED.email_verified, locale = EXCLUDED.locale,
                    previous_login = pilgrim.users.last_login,
                    last_login = NOW(), login_count = pilgrim.users.login_count + 1, updated_at = NOW()
                RETURNING id
            """, (user_data.get('sub'), user_data.get('email'), user_data.get('name'),
                  user_data.get('given_name'), user_data.get('family_name'), user_data.get('picture'),
                  user_data.get('email_verified', False), user_data.get('locale')))
            result = cur.fetchone()
            if result is None:
                logger.error(f"❌ UPSERT returned no rows - this should not happen with RETURNING")
                return None
            user_id = result['id']
            logger.info(f"✅ User {user_id} upserted successfully")
            return user_id
    except Exception as e:
        logger.error(f"❌ Failed to upsert user: {type(e).__name__}: {e}")
        import traceback
        logger.error(f"❌ Traceback: {traceback.format_exc()}")
        return None


def get_user_by_id(user_id: int) -> Optional[Dict]:
    """Get basic user info by ID."""
    return _get_one('users', 'id = %s', (user_id,), 'user')


def get_user_by_google_id(google_id: str) -> Optional[Dict]:
    """Get user by Google ID"""
    return _get_one('users', 'google_id = %s', (google_id,), 'user')


def update_user_activity(user_id: int) -> bool:
    """Update last_meaningful_activity_at for a user. Called on purchases, expeditions, claims, harvests, builds."""
    return _update('users', 'last_meaningful_activity_at = NOW()', 'id = %s', (user_id,), f'activity for user {user_id}')


def get_user_email_info(user_id: int) -> Optional[Dict]:
    """Get user's email and name for notifications"""
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT id, email, given_name, name, email_verified
                FROM pilgrim.users WHERE id = %s
            """, (user_id,))
            return _fetchone(cur)
    except Exception as e:
        logger.error(f"❌ Failed to get user email info: {e}")
        return None


# ============================================================================
# SESSION HYDRATION
# ============================================================================

def hydrate_user_session(user_id: int) -> dict:
    """
    SINGLE QUERY HYDRATION: Fetch ALL user data needed for session in ONE query.

    This is the "fast site" pattern - instead of 3-5 separate queries on each
    page load, we fetch everything at once and cache it in the session.

    PERFORMANCE: ~50ms instead of ~300ms for separate queries
    """
    try:
        with db_cursor(dict_cursor=False) as cur:
            cur.execute("""
                SELECT
                    (SELECT current_balance_eth FROM pilgrim.sepolia_assets
                     WHERE user_id = %s AND is_primary_wallet = true LIMIT 1) as balance_eth,
                    (SELECT wallet_address FROM pilgrim.sepolia_assets
                     WHERE user_id = %s AND is_primary_wallet = true LIMIT 1) as wallet_address,
                    (SELECT commander_name FROM pilgrim.replicate_assets
                     WHERE user_id = %s AND asset_type IN ('character_image', 'edited_image')
                     AND is_primary_character = true AND is_deleted = false LIMIT 1) as commander_name,
                    (SELECT COUNT(*) FROM pilgrim.expedition_discoveries ed
                     JOIN pilgrim.expeditions e ON ed.expedition_id = e.id
                     WHERE e.user_id = %s AND ed.claimed_by_user = true) as inventory_count,
                    (SELECT COUNT(*) FROM pilgrim.expeditions
                     WHERE user_id = %s AND status = 'completed') as expeditions_completed,
                    (SELECT COUNT(*) FROM pilgrim.colony_infrastructure
                     WHERE user_id = %s AND status = 'active') as structures_count,
                    (SELECT COALESCE(is_admin, false) FROM pilgrim.users
                     WHERE id = %s) as is_admin,
                    (SELECT first_login FROM pilgrim.users
                     WHERE id = %s) as first_login
            """, (user_id, user_id, user_id, user_id, user_id, user_id, user_id, user_id))
            row = cur.fetchone()

            balance_eth = float(row[0]) if row[0] else 0.0
            balance_display = round(balance_eth * 10000000, 1)
            commander_name = row[2][:20] if row[2] else None

            return {
                'balance': balance_display,
                'wallet_address': row[1],
                'commander_name': commander_name,
                'inventory_count': int(row[3] or 0),
                'expeditions_completed': int(row[4] or 0),
                'structures_count': int(row[5] or 0),
                'is_admin': bool(row[6]) if row[6] else False,
                'first_login': row[7].isoformat() if row[7] else None,
            }
    except Exception as e:
        logger.error(f"❌ Failed to hydrate user session: {e}")
        return {
            'balance': 0,
            'wallet_address': None,
            'commander_name': None,
            'inventory_count': 0,
            'expeditions_completed': 0,
            'structures_count': 0,
            'is_admin': False,
            'first_login': None,
        }


# ============================================================================
# XENOBIOLOGY LAB - RESEARCH POINTS SYSTEM
# ============================================================================

def ensure_research_columns() -> bool:
    """Ensure research_points and stat_bonuses columns exist in users table"""
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'pilgrim' AND table_name = 'users' AND column_name = 'research_points'
                    ) THEN
                        ALTER TABLE pilgrim.users ADD COLUMN research_points INTEGER DEFAULT 0;
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'pilgrim' AND table_name = 'users' AND column_name = 'stat_bonuses'
                    ) THEN
                        ALTER TABLE pilgrim.users ADD COLUMN stat_bonuses JSONB DEFAULT '{"leadership": 0, "strategy": 0, "exploration": 0, "logistics": 0, "charisma": 0}';
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'pilgrim' AND table_name = 'users' AND column_name = 'total_experiments_run'
                    ) THEN
                        ALTER TABLE pilgrim.users ADD COLUMN total_experiments_run INTEGER DEFAULT 0;
                    END IF;
                END $$;
            """)
            return True
    except Exception as e:
        logger.error(f"❌ Failed to ensure research columns: {e}")
        return False


def get_user_research_data(user_id: int) -> Optional[Dict]:
    """Get user's research points and stat bonuses"""
    try:
        ensure_research_columns()
        with db_cursor() as cur:
            cur.execute("""
                SELECT research_points, stat_bonuses, total_experiments_run
                FROM pilgrim.users WHERE id = %s
            """, (user_id,))
            result = cur.fetchone()
            if result:
                return {
                    'research_points': result.get('research_points') or 0,
                    'stat_bonuses': result.get('stat_bonuses') or {'leadership': 0, 'strategy': 0, 'exploration': 0, 'logistics': 0, 'charisma': 0},
                    'total_experiments_run': result.get('total_experiments_run') or 0
                }
            return {'research_points': 0, 'stat_bonuses': {'leadership': 0, 'strategy': 0, 'exploration': 0, 'logistics': 0, 'charisma': 0}, 'total_experiments_run': 0}
    except Exception as e:
        logger.error(f"❌ Failed to get research data: {e}")
        return None


def add_research_points(user_id: int, points: int) -> bool:
    """Add research points to user (from running experiments)"""
    try:
        ensure_research_columns()
        with db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE pilgrim.users
                SET research_points = COALESCE(research_points, 0) + %s,
                    total_experiments_run = COALESCE(total_experiments_run, 0) + 1,
                    updated_at = NOW()
                WHERE id = %s
            """, (points, user_id))
            logger.info(f"✅ Added {points} research points to user {user_id}")
            return True
    except Exception as e:
        logger.error(f"❌ Failed to add research points: {e}")
        return False


def spend_research_points(user_id: int, stat_name: str, points_to_spend: int) -> Optional[Dict]:
    """Spend research points to boost a stat. Returns new totals or None on failure."""
    try:
        ensure_research_columns()
        valid_stats = ['leadership', 'strategy', 'exploration', 'logistics', 'charisma']
        if stat_name not in valid_stats:
            logger.error(f"❌ Invalid stat name: {stat_name}")
            return None

        with db_cursor(commit=True) as cur:
            cur.execute("""
                SELECT research_points, stat_bonuses
                FROM pilgrim.users WHERE id = %s
            """, (user_id,))
            result = cur.fetchone()
            if not result:
                return None

            current_points = result.get('research_points') or 0
            bonuses = result.get('stat_bonuses') or {'leadership': 0, 'strategy': 0, 'exploration': 0, 'logistics': 0, 'charisma': 0}

            if current_points < points_to_spend:
                logger.error(f"❌ Not enough research points: have {current_points}, need {points_to_spend}")
                return None

            current_bonus = bonuses.get(stat_name, 0)
            if current_bonus >= 10:
                logger.error(f"❌ Stat {stat_name} already at max bonus of 10")
                return None

            bonuses[stat_name] = current_bonus + 1
            new_points = current_points - points_to_spend

            cur.execute("""
                UPDATE pilgrim.users
                SET research_points = %s, stat_bonuses = %s, updated_at = NOW()
                WHERE id = %s
            """, (new_points, json.dumps(bonuses), user_id))

            logger.info(f"✅ User {user_id} spent {points_to_spend} points on {stat_name}: {current_bonus} -> {bonuses[stat_name]}")
            return {'research_points': new_points, 'stat_bonuses': bonuses}
    except Exception as e:
        logger.error(f"❌ Failed to spend research points: {e}")
        return None


def spend_research_points_for_tech(user_id: int, points_to_spend: int) -> bool:
    """Deduct research points for tech tree research. Atomic with balance check."""
    try:
        ensure_research_columns()
        with db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE pilgrim.users
                SET research_points = research_points - %s, updated_at = NOW()
                WHERE id = %s AND research_points >= %s
            """, (points_to_spend, user_id, points_to_spend))
            success = cur.rowcount > 0
            if success:
                logger.info(f"Tech research: user {user_id} spent {points_to_spend} SP")
            return success
    except Exception as e:
        logger.error(f"Failed to spend research points for tech: {e}")
        return False


# ============================================================================
# ESCALATING COSTS - REROLL & TRANSMUTATION TRACKING
# ============================================================================

def ensure_escalation_columns() -> bool:
    """Ensure reroll/transmutation count columns exist in users table"""
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'pilgrim' AND table_name = 'users' AND column_name = 'total_rerolls'
                    ) THEN
                        ALTER TABLE pilgrim.users ADD COLUMN total_rerolls INTEGER DEFAULT 0;
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'pilgrim' AND table_name = 'users' AND column_name = 'total_transmutations'
                    ) THEN
                        ALTER TABLE pilgrim.users ADD COLUMN total_transmutations INTEGER DEFAULT 0;
                    END IF;
                END $$;
            """)
            return True
    except Exception as e:
        logger.error(f"❌ Failed to ensure escalation columns: {e}")
        return False


def get_user_escalation_counts(user_id: int) -> Dict:
    """Get user's reroll and transmutation counts for cost calculation"""
    try:
        ensure_escalation_columns()
        with db_cursor() as cur:
            cur.execute("""
                SELECT total_rerolls, total_transmutations
                FROM pilgrim.users WHERE id = %s
            """, (user_id,))
            result = cur.fetchone()
            if result:
                return {
                    'total_rerolls': result.get('total_rerolls') or 0,
                    'total_transmutations': result.get('total_transmutations') or 0
                }
            return {'total_rerolls': 0, 'total_transmutations': 0}
    except Exception as e:
        logger.error(f"❌ Failed to get escalation counts: {e}")
        return {'total_rerolls': 0, 'total_transmutations': 0}


def increment_reroll_count(user_id: int) -> bool:
    """Increment user's reroll count after a stat reroll"""
    try:
        ensure_escalation_columns()
        with db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE pilgrim.users
                SET total_rerolls = COALESCE(total_rerolls, 0) + 1, updated_at = NOW()
                WHERE id = %s
            """, (user_id,))
            logger.info(f"✅ Incremented reroll count for user {user_id}")
            return True
    except Exception as e:
        logger.error(f"❌ Failed to increment reroll count: {e}")
        return False


def increment_transmutation_count(user_id: int) -> bool:
    """Increment user's transmutation count after creating new captain"""
    try:
        ensure_escalation_columns()
        with db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE pilgrim.users
                SET total_transmutations = COALESCE(total_transmutations, 0) + 1, updated_at = NOW()
                WHERE id = %s
            """, (user_id,))
            logger.info(f"✅ Incremented transmutation count for user {user_id}")
            return True
    except Exception as e:
        logger.error(f"❌ Failed to increment transmutation count: {e}")
        return False


def calculate_reroll_cost(total_rerolls: int) -> int:
    """Calculate reroll cost based on number of previous rerolls. Doubles each time."""
    base_cost = 500
    return base_cost * (2 ** total_rerolls)


def calculate_transmutation_cost(total_transmutations: int) -> int:
    """Calculate transmutation cost based on number of previous transmutations. Doubles each time."""
    base_cost = 1000
    return base_cost * (2 ** total_transmutations)
