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
from decimal import Decimal
from google.cloud import secretmanager
from typing import Dict, Optional, List
from contextlib import contextmanager
import logging
from dotenv import load_dotenv
import threading
from collections import deque
from time import perf_counter as _perf_counter

logger = logging.getLogger(__name__)
load_dotenv()

# ============================================================================
# CONNECTION POOLING - Much faster than creating connections per-query
# ============================================================================

_connection_pool = None
_pool_lock = threading.Lock()
_pool_semaphore = None    # checkout gate; _FairGate(maxconn)
_permit_lock = threading.Lock()
_permits = {}             # id(conn) -> True for conns holding a permit

# Two DISTINCT counters. They used to be one, which is why maxconn was raised
# 12->20 on a signal that never meant what it said: a Cloud SQL socket drop and a
# genuinely full pool both incremented `_pool_fallback_count`. 30d of App Engine
# logs (2026-08-21) showed 4 fallbacks, all 4 "server closed the connection
# unexpectedly"/"Connection refused" in one 3-minute window, and ZERO real
# exhaustion events. Keep these apart so the next capacity decision has a signal.
_pool_fallback_count = 0     # pool/Cloud SQL UNREACHABLE -> direct connect
_pool_starvation_count = 0   # pool genuinely FULL -> waited POOL_WAIT_SECS, then raised

# Wait for a slot instead of instantly opening an uncapped direct connection.
POOL_WAIT_SECS = 10
POOL_WAIT_WARN_MS = 500
DEFAULT_MAXCONN = 8


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


class _FairGate:
    """FIFO checkout gate for pool slots.

    Not a threading.BoundedSemaphore: that lets a thread which just released a
    slot immediately re-acquire it ahead of threads already queued (barging).
    Measured 2026-08-21 with 24 threads against 8 slots — 8 hot threads cycled
    through all their work while the other 16 waited out the full 10s timeout and
    raised, despite slots freeing constantly. Under gthread that is a handful of
    busy endpoints starving everything else into 500s.

    Here a freed slot is handed directly to the longest-waiting thread, and a new
    arrival cannot jump a non-empty queue.
    """

    def __init__(self, size):
        self.size = size
        self._lock = threading.Lock()
        self._free = size
        self._waiters = deque()

    @property
    def free(self):
        with self._lock:
            return self._free

    def acquire(self, timeout):
        with self._lock:
            if self._free > 0 and not self._waiters:
                self._free -= 1
                return True
            ev = threading.Event()
            self._waiters.append(ev)
        if ev.wait(timeout):
            return True  # release() handed us the slot directly
        with self._lock:
            try:
                self._waiters.remove(ev)
            except ValueError:
                # Raced: release() handed us the slot between the timeout firing
                # and this lock. Take it rather than dropping it on the floor.
                return True
        return False

    def release(self):
        with self._lock:
            if self._waiters:
                # Transfer the slot; _free stays put because it never came back.
                self._waiters.popleft().set()
                return
            if self._free < self.size:
                self._free += 1


def _app_identity() -> str:
    """Per-app label for pg_stat_activity.application_name.

    Mirrors kumori/utilities/postgres_utils/connection.py::_app_identity, whose
    docstring names this module as the app that must adopt the same pattern for
    fleet-wide by_app attribution. Truncated to Postgres's 63-char limit.
    """
    project = (os.environ.get('GOOGLE_CLOUD_PROJECT')
               or os.environ.get('GAE_APPLICATION', '').replace('s~', '')
               or 'galactica')
    return project[:63]


def _get_connection_pool():
    """Get or create the connection pool (singleton pattern)."""
    global _connection_pool
    if _connection_pool is None:
        with _pool_lock:
            if _connection_pool is None:
                is_gcp = os.environ.get('GAE_ENV', '').startswith('standard')
                host = f"/cloudsql/{get_secret('PILGRIM_POSTGRES_CONNECTION_NAME')}" if is_gcp else get_secret('PILGRIM_POSTGRES_IP')

                # ThreadedConnectionPool is thread-safe.
                # Budget: 50 max_connections (3 superuser-reserved -> 47 usable)
                # shared across 20+ apps on the kumori instance.
                #
                # maxconn=8, was 20 (2026-08-21). The pool is PER PROCESS and
                # app.yaml runs `gunicorn -w 1 --threads 4`, so request-serving
                # concurrency is 4 threads; 8 leaves headroom for the background
                # daemon threads (chain writes, image gen, notifications) without
                # letting one instance claim 20 slots. At max_instances:3 the old
                # ceiling was 3x20=60 against 47 usable -- galactica alone could
                # oversubscribe the whole instance.
                _connection_pool = psycopg2.pool.ThreadedConnectionPool(
                    minconn=2,
                    maxconn=DEFAULT_MAXCONN,
                    host=host,
                    database=get_secret('PILGRIM_POSTGRES_DB_NAME'),
                    user=get_secret('PILGRIM_POSTGRES_USERNAME'),
                    password=get_secret('PILGRIM_POSTGRES_PASSWORD'),
                    connect_timeout=10,
                    # TCP keepalives: let the OS hold idle pooled conns open and
                    # detect drops at the socket layer, cutting how often Cloud SQL
                    # silently reaps one (19 "Stale DB connection" events in 30d).
                    keepalives=1,
                    keepalives_idle=30,
                    keepalives_interval=10,
                    keepalives_count=3,
                    # Every galactica connection is attributed to the role
                    # `pilgrim_app`, which is shared with the deploy tool and named
                    # after a different app -- so a connection audit cannot tell
                    # galactica apart without tracing secret names. Labelling the
                    # connection fixes attribution without a role rename.
                    application_name=_app_identity(),
                    # statement_timeout caps a single query; the idle-in-transaction
                    # timeout reaps a stuck txn server-side so it can't pin a slot.
                    options=('-c statement_timeout=30000 '
                             '-c idle_in_transaction_session_timeout=60000')
                )
                global _pool_semaphore
                _pool_semaphore = _FairGate(_connection_pool.maxconn)
                logger.info("✅ Database connection pool initialized (2-8 connections, app=%s)",
                            _app_identity())
    return _connection_pool


def _checkout_live(pool):
    """Take a connection from the pool, discarding any the server has dropped.

    A pooled conn can die server-side (Cloud SQL idle reaping, instance recycle)
    while sitting idle, and psycopg2 never validates on getconn(). Discard dead
    ones individually and let the pool mint a replacement.

    This replaces the previous stale path, which rebuilt the ENTIRE pool
    (`_connection_pool = None`) on the first dead connection. That orphaned the old
    pool with its idle sockets still open -- closeall() was never called anywhere --
    and it wrote the global outside `_pool_lock`, so two threads detecting staleness
    together could build two pools and leak one whole.
    """
    for _ in range(pool.maxconn):
        conn = pool.getconn()
        if getattr(conn, 'closed', 0):
            pool.putconn(conn, close=True)
            continue
        try:
            # Probe in autocommit so the SELECT opens no transaction and needs no
            # ROLLBACK to clean up — one round trip per checkout instead of two.
            # (psycopg2's autocommit setter is client-side; it does not talk to the
            # server.) The old code left the probe cursor open AND never rolled
            # back, so every connection was handed out idle-in-transaction and
            # stayed that way for its whole life.
            conn.autocommit = True
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.close()
            conn.autocommit = False
        except psycopg2.Error:
            logger.warning("Stale DB connection discarded, taking another")
            pool.putconn(conn, close=True)
            continue
        return conn
    # Every slot was stale (rare) — take one last fresh connection.
    return pool.getconn()


def get_db_connection():
    """Get a pooled connection, waiting for a slot if the pool is busy.

    The checkout gate is the point of this function. psycopg2's getconn() raises
    PoolError the instant every slot is checked out, and the old code caught that
    and opened an UNPOOLED direct connection -- so maxconn was never a ceiling,
    just the threshold past which galactica started opening uncapped connections
    against a 47-slot shared instance. Now callers queue for up to POOL_WAIT_SECS
    and a genuinely full pool raises instead of silently widening the footprint.
    """
    global _pool_fallback_count, _pool_starvation_count
    acquired = False
    sem = None
    try:
        pool = _get_connection_pool()
        sem = _pool_semaphore
        if sem is not None:
            t0 = _perf_counter()
            if not sem.acquire(timeout=POOL_WAIT_SECS):
                _pool_starvation_count += 1
                logger.error("DB pool starvation: no slot after %ss (maxconn=%s)",
                             POOL_WAIT_SECS, pool.maxconn)
                raise psycopg2.pool.PoolError(
                    f"connection pool exhausted (waited {POOL_WAIT_SECS}s for a slot)")
            acquired = True
            waited_ms = (_perf_counter() - t0) * 1000
            if waited_ms >= POOL_WAIT_WARN_MS:
                logger.warning("DB pool contention: waited %.0fms for a slot", waited_ms)
        conn = _checkout_live(pool)
        if acquired:
            with _permit_lock:
                _permits[id(conn)] = True
        return conn
    except psycopg2.pool.PoolError:
        # Genuine starvation. Deliberately NOT converted into a direct connection —
        # that is the behaviour this gate exists to stop.
        if acquired and sem is not None:
            _release(sem)
        raise
    except Exception as e:
        # The pool or Cloud SQL is unreachable (socket drop, instance restart).
        # This is the ONLY case that earns an unpooled connection.
        if acquired and sem is not None:
            _release(sem)
        _pool_fallback_count += 1
        logger.warning(f"⚠️ Pool connection failed, using direct: {e}")
        is_gcp = os.environ.get('GAE_ENV', '').startswith('standard')
        host = f"/cloudsql/{get_secret('PILGRIM_POSTGRES_CONNECTION_NAME')}" if is_gcp else get_secret('PILGRIM_POSTGRES_IP')
        return psycopg2.connect(
            host=host, database=get_secret('PILGRIM_POSTGRES_DB_NAME'),
            user=get_secret('PILGRIM_POSTGRES_USERNAME'), password=get_secret('PILGRIM_POSTGRES_PASSWORD'),
            connect_timeout=10, application_name=_app_identity()
        )


def _release(sem):
    """Release a checkout permit."""
    try:
        sem.release()
    except Exception:
        pass


def _return_connection(conn):
    """Return a connection to the pool and free its checkout permit.

    The permit is released on EVERY path, including when the connection came from
    the direct-connect fallback (it holds no permit and is simply closed).
    """
    with _permit_lock:
        held = _permits.pop(id(conn), False) if conn is not None else False
    try:
        pool = _get_connection_pool()
        pool.putconn(conn)
    except Exception:
        # Not a pooled connection (direct fallback), or the pool is gone.
        try:
            conn.close()
        except Exception:
            pass
    finally:
        if held and _pool_semaphore is not None:
            _release(_pool_semaphore)


def get_pool_health():
    """Return connection pool health stats for admin monitoring.

    `fallbacks` and `starvations` are separate on purpose — see the counter
    comments up top. A non-zero `fallbacks` means Cloud SQL was unreachable;
    only `starvations` is evidence that maxconn is too small.
    """
    pool = _connection_pool
    if pool is None:
        return {'status': 'not_initialized', 'maxconn': DEFAULT_MAXCONN,
                'fallbacks': _pool_fallback_count,
                'starvations': _pool_starvation_count}
    used = len(pool._used) if hasattr(pool, '_used') else 0
    available = len(pool._pool) if hasattr(pool, '_pool') else 0
    # Free slots on the checkout gate. Callers queue on this, so it is the number
    # that says whether requests are waiting — `available` only counts idle conns
    # already built. NOTE: a caller that close()s a pooled connection instead of
    # returning it strands both a pool slot and its permit; the two stay consistent
    # with each other, so nothing here can detect it. The invariant is enforced by
    # the pool smoke test instead, and _return_connection is the only sanctioned
    # return path.
    return {
        'status': 'healthy' if used < pool.maxconn else 'exhausted',
        'used': used,
        'available': available,
        'maxconn': pool.maxconn,
        'minconn': pool.minconn,
        'fallbacks': _pool_fallback_count,
        'starvations': _pool_starvation_count,
        'gate_free': _pool_semaphore.free if _pool_semaphore is not None else None,
    }


def get_db_connection_stats():
    """Query pg_stat_activity for global connection stats."""
    try:
        with db_cursor() as cur:
            # Was `usename = 'postgres'` — a role galactica never connects as
            # (live count: 0), so this breakdown was always empty while the app
            # actually held connections as current_user. Reporting an empty
            # by_state is how a healthy pool can look like a broken one.
            cur.execute("""SELECT state, count(*) as cnt
                          FROM pg_stat_activity WHERE usename = current_user
                          GROUP BY state ORDER BY cnt DESC""")
            states = {r['state'] or 'null': r['cnt'] for r in cur.fetchall()}
            cur.execute("""SELECT coalesce(nullif(application_name,''),'(unlabelled)') AS app,
                                 count(*) AS cnt
                          FROM pg_stat_activity WHERE usename IS NOT NULL
                          GROUP BY 1 ORDER BY cnt DESC""")
            by_app = {r['app']: r['cnt'] for r in cur.fetchall()}
            cur.execute("SHOW max_connections")
            max_conn = int(cur.fetchone()['max_connections'])
            cur.execute("SELECT count(*) as total FROM pg_stat_activity WHERE usename IS NOT NULL")
            total = cur.fetchone()['total']
            return {
                'max_connections': max_conn,
                'total_used': total,
                'pct_used': round(total / max_conn * 100, 1),
                'by_state': states,
                'by_app': by_app,
            }
    except Exception as e:
        return {'error': str(e)[:100]}


# ============================================================================
# PER-REQUEST DB-CALL TELEMETRY
# Counts db_cursor() opens in each Flask request. Logs a warning and records
# to request.db_counter if the count exceeds DB_CALL_WARN_THRESHOLD.
# Reset via reset_db_counter() from a before_request hook; read via get_db_counter().
# ============================================================================

_tls = threading.local()
DB_CALL_WARN_THRESHOLD = 20  # per-request cursor opens; anything above this is a smell


def reset_db_counter():
    _tls.count = 0
    _tls.context = None
    _tls.memo = {}


def request_memo(key: tuple, loader):
    """Per-request cache for read-only helpers. Second call with the same key returns the cached value
    (no DB hit). Reset by reset_db_counter() at the start of each Flask request."""
    memo = getattr(_tls, 'memo', None)
    if memo is None:
        _tls.memo = memo = {}
    if key in memo:
        return memo[key]
    val = loader()
    memo[key] = val
    return val


def set_db_context(label: str):
    """Tag the current request so over-threshold warnings identify the page."""
    _tls.context = label


def get_db_counter() -> int:
    return getattr(_tls, 'count', 0)


@contextmanager
def db_cursor(dict_cursor=True, commit=False):
    """Context manager for database operations - uses connection pool for speed."""
    _tls.count = getattr(_tls, 'count', 0) + 1
    conn = get_db_connection()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) if dict_cursor else conn.cursor()
    except Exception:
        # Cursor creation was outside the try, so a failure here returned neither
        # the connection nor (now) its checkout permit — and a leaked permit
        # shrinks the pool for the life of the process.
        _return_connection(conn)
        raise
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


def ensure_table_columns(schema: str, table: str, coldefs: dict) -> list:
    """Idempotently add only the GENUINELY-MISSING columns to a table.

    Why this exists: the old pattern `ALTER TABLE x ADD COLUMN IF NOT EXISTS ...`
    run on every cold-start instance still requests an ACCESS EXCLUSIVE lock on the
    target table EVEN WHEN the column already exists — so on a hot table (e.g.
    pilgrim.expeditions) under load it blocks and hits the statement timeout,
    spamming the logs with errors despite there being nothing to change.

    This helper SELECTs information_schema first (catalog read — never blocks on the
    target table's locks) and only issues an ALTER for columns that are actually
    absent. Steady state = zero ALTERs = zero lock contention. Returns the list of
    columns it added (empty when all present).

    coldefs: {column_name: "TYPE ... [NOT NULL] [DEFAULT ...]"} — values are trusted
    DDL literals from callers (never user input).
    """
    with db_cursor(commit=True) as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = %s",
            (schema, table))
        have = {r['column_name'] for r in cur.fetchall()}
        added = []
        for col, ddl in coldefs.items():
            if col not in have:
                cur.execute(f"ALTER TABLE {schema}.{table} ADD COLUMN {col} {ddl}")
                added.append(col)
        return added


def json_serial(obj):
    """JSON serializer default for json.dumps — handles the non-JSON-native types that
    flow out of Postgres. datetime -> ISO string; Decimal -> float (NUMERIC/DOUBLE columns
    like distance_km come back as Decimal and would otherwise raise 'not serializable',
    e.g. log_activity metadata for landmark discoveries)."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
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
