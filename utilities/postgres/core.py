"""
utilities.postgres.core — connection pool, cursor, generic helpers.

CORE infrastructure only. No domain logic. Sibling modules (users, expeditions,
trails/, etc.) import `db_cursor` and the `_fetchone/_fetchall/_get_one/_get_many/_update/_count`
helpers from here.
"""
import psycopg2
import psycopg2.extras
import psycopg2.pool
import os
from datetime import datetime
from google.cloud import secretmanager
from typing import Dict, Optional, List
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
        try:
            conn.close()
        except Exception:
            pass


def get_pool_health():
    """Return connection pool health stats for admin monitoring."""
    pool = _connection_pool
    if pool is None:
        return {'status': 'not_initialized', 'maxconn': 20, 'fallbacks': _pool_fallback_count}
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
