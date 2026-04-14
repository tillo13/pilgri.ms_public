"""Unified activity event logging and retrieval.

Single source of truth for all colony events. Write at event-creation time via log_activity(),
read via get_activity(). Replaces the 240-line read-time reconstruction in get_unified_activity().
"""

import json
import logging
from typing import Dict, List, Optional
from utilities.postgres.core import db_cursor, _fetchall, json_serial

logger = logging.getLogger(__name__)

_schema_ensured = False


def ensure_activity_table():
    """Create activity_events table if it doesn't exist. Cached after first call."""
    global _schema_ensured
    if _schema_ensured:
        return
    _schema_ensured = True
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS pilgrim.activity_events (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    category VARCHAR(30) NOT NULL,
                    event_type VARCHAR(50) NOT NULL,
                    title VARCHAR(200) NOT NULL,
                    amount NUMERIC DEFAULT 0,
                    detail TEXT DEFAULT '',
                    tx_hash VARCHAR(100) DEFAULT '',
                    image_url TEXT DEFAULT '',
                    metadata JSONB DEFAULT '{}',
                    source_table VARCHAR(50),
                    source_id INTEGER,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_ae_user_time ON pilgrim.activity_events (user_id, created_at DESC)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_ae_category ON pilgrim.activity_events (user_id, category)")
    except Exception as e:
        logger.error(f"Failed to ensure activity_events table: {e}")


def log_activity(
    user_id: int,
    category: str,
    event_type: str,
    title: str,
    amount: float = 0,
    detail: str = '',
    tx_hash: str = '',
    image_url: str = '',
    metadata: dict = None,
    source_table: str = None,
    source_id: int = None,
    created_at=None
) -> Optional[int]:
    """Log a single activity event. Fire-and-forget: never raises, returns event ID or None."""
    ensure_activity_table()
    try:
        meta_json = json.dumps(metadata or {}, default=json_serial)
        with db_cursor(commit=True) as cur:
            if created_at:
                cur.execute("""
                    INSERT INTO pilgrim.activity_events
                    (user_id, category, event_type, title, amount, detail, tx_hash,
                     image_url, metadata, source_table, source_id, created_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
                """, (user_id, category, event_type, title, amount, detail, tx_hash,
                      image_url, meta_json, source_table, source_id, created_at))
            else:
                cur.execute("""
                    INSERT INTO pilgrim.activity_events
                    (user_id, category, event_type, title, amount, detail, tx_hash,
                     image_url, metadata, source_table, source_id)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
                """, (user_id, category, event_type, title, amount, detail, tx_hash,
                      image_url, meta_json, source_table, source_id))
            row = cur.fetchone()
            return row['id'] if row else None
    except Exception as e:
        logger.error(f"Failed to log activity [{category}/{event_type}] for user {user_id}: {e}")
        return None


def get_activity(user_id: int, limit: int = 500, since=None, category: str = None) -> List[Dict]:
    """Get activity events for a user. Simple SELECT replaces 240-line read-time reconstruction."""
    ensure_activity_table()
    try:
        clauses = ["user_id = %s"]
        params: list = [user_id]
        if since:
            clauses.append("created_at > %s")
            params.append(since)
        if category:
            clauses.append("category = %s")
            params.append(category)
        params.append(limit)
        with db_cursor() as cur:
            cur.execute(f"""
                SELECT category, event_type, title, amount, detail, tx_hash,
                       image_url, metadata, source_table, source_id, created_at
                FROM pilgrim.activity_events
                WHERE {' AND '.join(clauses)}
                ORDER BY created_at DESC LIMIT %s
            """, params)
            rows = _fetchall(cur)
        for r in rows:
            if r.get('created_at'):
                r['timestamp'] = r['created_at'].isoformat()
            if isinstance(r.get('metadata'), str):
                try:
                    r['metadata'] = json.loads(r['metadata'])
                except (json.JSONDecodeError, TypeError):
                    r['metadata'] = {}
        return rows
    except Exception as e:
        logger.error(f"Failed to get activity for user {user_id}: {e}")
        return []
