"""
PostgreSQL utilities for Pilgrims Character Game.

CORE: Connection pool, db_cursor, generic helpers (kept here).
DOMAIN: All domain functions live in db_*.py files and are re-exported below
so existing `from utilities.postgres_utils import X` statements keep working.

PERFORMANCE: Uses connection pooling for fast DB access (~5ms vs ~300ms per query)
"""
import psycopg2
import psycopg2.extras
import psycopg2.pool
import os
import json
from datetime import datetime, timedelta
from google.cloud import secretmanager
from typing import Dict, Any, Optional, List
from contextlib import contextmanager
import logging
from dotenv import load_dotenv
import threading

logger = logging.getLogger(__name__)
load_dotenv()

# ============================================================================
# CONNECTION POOLING - Much faster than creating connections per-query
# ============================================================================

_connection_pool = None
_pool_lock = threading.Lock()
_pool_fallback_count = 0  # Track pool exhaustion events


_secrets_cache = {}
_sm_client = None

def get_secret(secret_id: str, project_id: str = "kumori-404602") -> str:
    """Get secret from environment variable first, then Google Secret Manager (cached)"""
    env_value = os.getenv(secret_id)
    if env_value:
        return env_value
    cache_key = f"{project_id}:{secret_id}"
    if cache_key in _secrets_cache:
        return _secrets_cache[cache_key]
    global _sm_client
    if _sm_client is None:
        _sm_client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
    response = _sm_client.access_secret_version(request={"name": name})
    val = response.payload.data.decode('UTF-8')
    _secrets_cache[cache_key] = val
    return val


def _get_connection_pool():
    """Get or create the connection pool (singleton pattern)."""
    global _connection_pool
    if _connection_pool is None:
        with _pool_lock:
            if _connection_pool is None:
                is_gcp = os.environ.get('GAE_ENV', '').startswith('standard')
                host = f"/cloudsql/{get_secret('PILGRIM_POSTGRES_CONNECTION_NAME')}" if is_gcp else get_secret('PILGRIM_POSTGRES_IP')

                # ThreadedConnectionPool is thread-safe
                # Budget: 50 max_connections shared across 8+ apps on db-f1-micro
                # Galactica gets biggest share: 2/20 (heaviest app, QA bot + ARIA + pages)
                # Was maxconn=12 but exhausted constantly (2k+ fallbacks). Global at ~22%.
                _connection_pool = psycopg2.pool.ThreadedConnectionPool(
                    minconn=2,
                    maxconn=20,
                    host=host,
                    database=get_secret('PILGRIM_POSTGRES_DB_NAME'),
                    user=get_secret('PILGRIM_POSTGRES_USERNAME'),
                    password=get_secret('PILGRIM_POSTGRES_PASSWORD'),
                    connect_timeout=10,
                    options='-c statement_timeout=30000'
                )
                logger.info("✅ Database connection pool initialized (2-20 connections)")
    return _connection_pool


def get_db_connection():
    """Get a connection from the pool (fast!) or create new if pool fails."""
    try:
        pool = _get_connection_pool()
        conn = pool.getconn()
        # Test if connection is alive — Cloud SQL kills idle connections
        try:
            conn.cursor().execute("SELECT 1")
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            global _connection_pool
            logger.warning("Stale DB connection detected, reconnecting")
            try:
                pool.putconn(conn, close=True)
            except Exception:
                pass
            _connection_pool = None
            pool = _get_connection_pool()
            conn = pool.getconn()
        return conn
    except Exception as e:
        # Fallback to direct connection if pool fails
        global _pool_fallback_count
        _pool_fallback_count += 1
        logger.warning(f"⚠️ Pool connection failed, using direct: {e}")
        is_gcp = os.environ.get('GAE_ENV', '').startswith('standard')
        host = f"/cloudsql/{get_secret('PILGRIM_POSTGRES_CONNECTION_NAME')}" if is_gcp else get_secret('PILGRIM_POSTGRES_IP')
        return psycopg2.connect(
            host=host, database=get_secret('PILGRIM_POSTGRES_DB_NAME'),
            user=get_secret('PILGRIM_POSTGRES_USERNAME'), password=get_secret('PILGRIM_POSTGRES_PASSWORD'),
            connect_timeout=10
        )


def _return_connection(conn):
    """Return a connection to the pool."""
    try:
        pool = _get_connection_pool()
        pool.putconn(conn)
    except Exception:
        # If pool return fails, just close the connection
        try:
            conn.close()
        except Exception:
            pass


def get_pool_health():
    """Return connection pool health stats for admin monitoring."""
    pool = _connection_pool
    if pool is None:
        return {'status': 'not_initialized', 'maxconn': 20, 'fallbacks': _pool_fallback_count}
    # ThreadedConnectionPool tracks used keys internally
    used = len(pool._used) if hasattr(pool, '_used') else 0
    available = len(pool._pool) if hasattr(pool, '_pool') else 0
    return {
        'status': 'healthy' if used < pool.maxconn else 'exhausted',
        'used': used,
        'available': available,
        'maxconn': pool.maxconn,
        'minconn': pool.minconn,
        'fallbacks': _pool_fallback_count,
    }


def get_db_connection_stats():
    """Query pg_stat_activity for global connection stats."""
    try:
        with db_cursor() as cur:
            cur.execute("""SELECT state, count(*) as cnt
                          FROM pg_stat_activity WHERE usename = 'postgres'
                          GROUP BY state ORDER BY cnt DESC""")
            states = {r['state'] or 'null': r['cnt'] for r in cur.fetchall()}
            cur.execute("SHOW max_connections")
            max_conn = int(cur.fetchone()['max_connections'])
            cur.execute("SELECT count(*) as total FROM pg_stat_activity WHERE usename IS NOT NULL")
            total = cur.fetchone()['total']
            return {
                'max_connections': max_conn,
                'total_used': total,
                'pct_used': round(total / max_conn * 100, 1),
                'by_state': states,
            }
    except Exception as e:
        return {'error': str(e)[:100]}


@contextmanager
def db_cursor(dict_cursor=True, commit=False):
    """Context manager for database operations - uses connection pool for speed."""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) if dict_cursor else conn.cursor()
    try:
        yield cur
        if commit:
            conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cur.close()
        _return_connection(conn)

def _fetchone(cur) -> Optional[Dict]:
    """Helper to fetch one row as dict or None"""
    row = cur.fetchone()
    return dict(row) if row else None

def _fetchall(cur) -> List[Dict]:
    """Helper to fetch all rows as list of dicts"""
    return [dict(row) for row in cur.fetchall()]

# ============================================================================
# GENERIC DB HELPERS - DRY patterns for common operations
# ============================================================================

def _get_one(table: str, where_clause: str, params: tuple, error_msg: str = "record") -> Optional[Dict]:
    """Generic single-row fetch with error handling"""
    try:
        with db_cursor() as cur:
            cur.execute(f"SELECT * FROM pilgrim.{table} WHERE {where_clause}", params)
            return _fetchone(cur)
    except Exception as e:
        logger.error(f"❌ Failed to get {error_msg}: {e}")
        return None

def _get_many(table: str, where_clause: str, params: tuple, order_by: str = None, error_msg: str = "records") -> List[Dict]:
    """Generic multi-row fetch with error handling"""
    try:
        with db_cursor() as cur:
            sql = f"SELECT * FROM pilgrim.{table} WHERE {where_clause}"
            if order_by:
                sql += f" ORDER BY {order_by}"
            cur.execute(sql, params)
            return _fetchall(cur)
    except Exception as e:
        logger.error(f"❌ Failed to get {error_msg}: {e}")
        return []

def _count(table: str, where_clause: str, params: tuple, error_msg: str = "count") -> int:
    """Generic count with error handling"""
    try:
        with db_cursor(dict_cursor=False) as cur:
            cur.execute(f"SELECT COUNT(*) FROM pilgrim.{table} WHERE {where_clause}", params)
            return cur.fetchone()[0]
    except Exception as e:
        logger.error(f"❌ Failed to get {error_msg}: {e}")
        return 0

def _update(table: str, set_clause: str, where_clause: str, params: tuple, error_msg: str = "record") -> bool:
    """Generic update with error handling"""
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(f"UPDATE pilgrim.{table} SET {set_clause} WHERE {where_clause}", params)
            return True
    except Exception as e:
        logger.error(f"❌ Failed to update {error_msg}: {e}")
        return False

def json_serial(obj):
    """JSON serializer for datetime objects"""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")

def test_connection():
    """Test database connection"""
    try:
        with db_cursor(dict_cursor=False) as cur:
            cur.execute("SELECT version();")
            version = cur.fetchone()
            print(f"✅ PostgreSQL connection successful: {version[0]}")
            return True
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return False

# ============================================================================
# RE-EXPORTS: Domain functions from db_*.py files
# All existing `from utilities.postgres_utils import X` statements keep working.
# Uses lazy __getattr__ to avoid circular imports when db_*.py files are
# imported directly (they import core functions from this file).
# ============================================================================

import importlib as _importlib

# Map every re-exported function to its domain module
_DOMAIN_EXPORTS = {
    # db_users - User CRUD, auth, session, research, escalation
    'ensure_scientist_column': 'db_users', 'ensure_passive_sv_column': 'db_users',
    'add_passive_sv': 'db_users', 'get_passive_sv': 'db_users',
    'assign_scientist_to_user': 'db_users', 'get_user_scientist': 'db_users',
    'upsert_user': 'db_users', 'get_user_by_id': 'db_users', 'get_user_by_google_id': 'db_users',
    'update_user_activity': 'db_users', 'get_user_email_info': 'db_users',
    'hydrate_user_session': 'db_users',
    'ensure_research_columns': 'db_users', 'get_user_research_data': 'db_users',
    'add_research_points': 'db_users', 'spend_research_points': 'db_users',
    'spend_research_points_for_tech': 'db_users',
    'ensure_escalation_columns': 'db_users', 'get_user_escalation_counts': 'db_users',
    'increment_reroll_count': 'db_users', 'increment_transmutation_count': 'db_users',
    'calculate_reroll_cost': 'db_users', 'calculate_transmutation_cost': 'db_users',

    # db_wallets - Sepolia asset operations
    'create_sepolia_wallet_for_user': 'db_wallets', 'get_user_sepolia_wallets': 'db_wallets',
    'get_user_primary_sepolia_wallet': 'db_wallets', 'update_sepolia_wallet_balance': 'db_wallets',
    'sync_all_wallet_balances': 'db_wallets', 'claim_anonymous_wallet': 'db_wallets',
    'get_wallet_by_address': 'db_wallets', 'get_random_unclaimed_cache': 'db_wallets',

    # db_assets - Replicate assets, captain management
    'create_replicate_asset': 'db_assets', 'get_user_replicate_assets': 'db_assets',
    'get_user_commander_images': 'db_assets', 'get_asset_edit_chain': 'db_assets',
    'claim_anonymous_assets': 'db_assets', 'update_asset_stats': 'db_assets',
    'delete_asset': 'db_assets', 'get_primary_commander': 'db_assets',
    'get_user_commander': 'db_assets', 'set_primary_commander': 'db_assets',
    'update_commander_name': 'db_assets', 'get_commander_stats': 'db_assets',

    # db_shop - Transactions, infrastructure, upgrades, action tokens, mars messages
    'ensure_dust_covered_column': 'db_shop', 'set_infrastructure_dust_covered': 'db_shop',
    'create_depot_transaction': 'db_shop', 'get_user_depot_transactions': 'db_shop',
    '_format_depot_activity': 'db_shop', 'get_unified_activity': 'db_shop',
    'create_infrastructure': 'db_shop', 'get_user_infrastructure': 'db_shop',
    'get_infrastructure_by_id': 'db_shop', 'update_infrastructure_status': 'db_shop',
    'get_user_upgrades': 'db_shop', 'get_user_upgrade': 'db_shop',
    'add_user_upgrade': 'db_shop', 'get_user_upgrade_count': 'db_shop',
    'complete_ready_builds': 'db_shop', 'get_building_upgrades': 'db_shop',
    'ensure_action_tokens_table': 'db_shop', 'is_action_token_used': 'db_shop',
    'mark_action_token_used': 'db_shop', 'get_next_mars_message': 'db_shop',

    # db_expeditions - Expedition CRUD, discoveries
    'create_expedition': 'db_expeditions', 'get_user_active_expeditions': 'db_expeditions',
    'get_expedition_by_id': 'db_expeditions', 'update_expedition_complete': 'db_expeditions',
    'get_user_completed_expeditions_count': 'db_expeditions',
    'get_user_visited_locations_count': 'db_expeditions',
    'get_user_expedition_history': 'db_expeditions',
    'get_expedition_discovery_items': 'db_expeditions',
    'record_landmark_discovery': 'db_expeditions', 'get_user_discovered_landmarks': 'db_expeditions',
    'get_discovery_items_catalog': 'db_expeditions',
    'create_expedition_discoveries': 'db_expeditions',
    'get_expedition_discoveries': 'db_expeditions',
    'unlock_discoveries_by_distance': 'db_expeditions',
    'claim_expedition_discovery': 'db_expeditions',
    'claim_all_pending_discoveries': 'db_expeditions',
    'get_recent_discoveries': 'db_expeditions',
    'get_total_unclaimed_discoveries_count': 'db_expeditions',
    'get_claimed_discoveries': 'db_expeditions',
    'get_sample_common_discovery': 'db_expeditions',
    'get_all_discovery_items': 'db_expeditions',
    'get_discovery_item_details': 'db_expeditions',

    # db_trails - Trail segments, crew missions, ARIA skills
    'ensure_trail_segments_table': 'db_trails', 'get_user_trail': 'db_trails',
    'increment_user_trail': 'db_trails', 'get_user_trails': 'db_trails',
    'add_km_to_trail': 'db_trails', 'get_trail_progress': 'db_trails',
    'get_aria_skills': 'db_trails', 'add_aria_skill_xp': 'db_trails',
    'ensure_crew_missions_schema': 'db_trails', 'get_crew_mission_status': 'db_trails',
    'start_crew_mission': 'db_trails', 'complete_crew_mission': 'db_trails',
    'get_trail_consumable_discoveries': 'db_trails',
    'consume_discovery_for_trail': 'db_trails',
    'use_aria_resonance': 'db_trails',
    'get_nearby_trails_for_missions': 'db_trails',
    'get_visited_sites_for_trails': 'db_trails',

    # db_map - Mars coordinates, landmarks, fog-of-war, frontier
    'get_random_mars_coordinates': 'db_map', 'get_nearest_mars_landmarks': 'db_map',
    'get_or_set_user_mars_home': 'db_map', 'get_mars_landmarks_within_radius': 'db_map',
    '_get_direction_from_angle': 'db_map',
    'get_user_furthest_expeditions_by_direction': 'db_map',
    'get_frontier_landmarks_beyond_point': 'db_map',
    'get_all_frontier_landmarks': 'db_map',
    'get_available_landmarks_by_discovery': 'db_map',

    # db_notifications - FOMO, email queries, captain quotes
    'get_users_with_completed_expeditions': 'db_notifications',
    'mark_expedition_notified': 'db_notifications',
    'get_inactive_users': 'db_notifications', 'mark_user_nudged': 'db_notifications',
    'get_user_fomo_data': 'db_notifications',
    'save_commander_quote': 'db_notifications', 'get_commander_quotes': 'db_notifications',
    'get_commander_quote_count': 'db_notifications',
}


def __getattr__(name):
    """Lazy re-export: load domain function on first access."""
    if name in _DOMAIN_EXPORTS:
        module = _importlib.import_module(f'utilities.{_DOMAIN_EXPORTS[name]}')
        func = getattr(module, name)
        # Cache in module namespace so __getattr__ isn't called again
        globals()[name] = func
        return func
    raise AttributeError(f"module 'utilities.postgres_utils' has no attribute '{name}'")
