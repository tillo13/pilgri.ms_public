"""Bug tracker database operations.

Replaces Google Sheets bug tracking with PostgreSQL.
Four tables: bugs, bug_history (audit), bug_ideas (parking lot), bug_comments (threads).
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional
from utilities.postgres.core import db_cursor, _fetchone, _fetchall

logger = logging.getLogger(__name__)

_schema_ensured = False


def _serialize_row(row):
    """Convert datetime fields to ISO strings for JSON serialization."""
    if not row:
        return row
    d = dict(row)
    for k, v in d.items():
        if isinstance(v, datetime):
            # Append Z so browser knows it's UTC (DB stores naive UTC timestamps)
            d[k] = v.isoformat() + 'Z'
    return d


def _serialize_rows(rows):
    return [_serialize_row(r) for r in rows]


def ensure_bug_tables():
    """Create bug tracker tables if they don't exist. Cached after first call."""
    global _schema_ensured
    if _schema_ensured:
        return
    _schema_ensured = True
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS pilgrim.bugs (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(200) NOT NULL,
                    description TEXT DEFAULT '',
                    to_validate TEXT DEFAULT '',
                    dev_addressed TIMESTAMP,
                    type VARCHAR(20) DEFAULT 'Bug',
                    priority VARCHAR(4) DEFAULT 'P3',
                    status VARCHAR(30) DEFAULT 'New',
                    qa_approved BOOLEAN DEFAULT FALSE,
                    source VARCHAR(20) DEFAULT 'QA',
                    screenshot_url TEXT,
                    screenshot_2_url TEXT,
                    screenshot_3_url TEXT,
                    qa_notes TEXT DEFAULT '',
                    extra_notes TEXT DEFAULT '',
                    parent_bug_id INTEGER REFERENCES pilgrim.bugs(id),
                    completed_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_bugs_status ON pilgrim.bugs(status)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_bugs_priority ON pilgrim.bugs(priority)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_bugs_completed ON pilgrim.bugs(completed_at) WHERE completed_at IS NOT NULL")
            # Migration: add screenshot_3_url column if missing
            cur.execute("ALTER TABLE pilgrim.bugs ADD COLUMN IF NOT EXISTS screenshot_3_url TEXT")

            cur.execute("""
                CREATE TABLE IF NOT EXISTS pilgrim.bug_history (
                    id SERIAL PRIMARY KEY,
                    bug_id INTEGER NOT NULL REFERENCES pilgrim.bugs(id),
                    changed_by VARCHAR(50) NOT NULL,
                    field_name VARCHAR(50) NOT NULL,
                    old_value TEXT,
                    new_value TEXT,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_bug_history_bug ON pilgrim.bug_history(bug_id)")

            # Migration: move ideas from bug_ideas into bugs table with status='Parking Lot'
            cur.execute("SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_schema='pilgrim' AND table_name='bug_ideas') as ex")
            if cur.fetchone()['ex']:
                # Check if any un-migrated ideas remain
                cur.execute("SELECT COUNT(*) as cnt FROM pilgrim.bug_ideas WHERE promoted_to_bug_id IS NULL AND status != 'Promoted'")
                unmigrated = cur.fetchone()['cnt']
                if unmigrated > 0:
                    cur.execute("""
                        INSERT INTO pilgrim.bugs (name, description, type, priority, status, source, extra_notes, created_at)
                        SELECT name, description, COALESCE(NULLIF(category,''), 'Feature'), 'P5', 'Parking Lot', 'Idea',
                               notes, created_at
                        FROM pilgrim.bug_ideas
                        WHERE promoted_to_bug_id IS NULL AND status != 'Promoted'
                    """)
                    logger.info(f"Migrated {unmigrated} ideas from bug_ideas to bugs table")
                # Drop the old table
                cur.execute("DROP TABLE IF EXISTS pilgrim.bug_ideas CASCADE")

            cur.execute("""
                CREATE TABLE IF NOT EXISTS pilgrim.bug_comments (
                    id SERIAL PRIMARY KEY,
                    bug_id INTEGER NOT NULL REFERENCES pilgrim.bugs(id),
                    author VARCHAR(50) NOT NULL,
                    body TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_bug_comments_bug ON pilgrim.bug_comments(bug_id)")
    except Exception as e:
        logger.error(f"Failed to ensure bug tables: {e}")


# =============================================================================
# BUGS — CRUD
# =============================================================================

def create_bug(name, description='', type='Bug', priority='P3', source='CLI',
               status='Backlog', to_validate='', qa_notes='', extra_notes=''):
    """Create a new bug. Returns the new bug dict or None."""
    ensure_bug_tables()
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO pilgrim.bugs (name, description, type, priority, source,
                    status, to_validate, qa_notes, extra_notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
            """, (name, description, type, priority, source,
                  status, to_validate, qa_notes, extra_notes))
            return _serialize_row(_fetchone(cur))
    except Exception as e:
        logger.error(f"Failed to create bug: {e}")
        return None


def get_bug_by_id(bug_id):
    """Get a single bug by ID."""
    ensure_bug_tables()
    try:
        with db_cursor() as cur:
            cur.execute("SELECT * FROM pilgrim.bugs WHERE id = %s", (bug_id,))
            return _serialize_row(_fetchone(cur))
    except Exception as e:
        logger.error(f"Failed to get bug {bug_id}: {e}")
        return None


def get_bug_by_name(name_search):
    """Fuzzy search by name, returns first match."""
    ensure_bug_tables()
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT * FROM pilgrim.bugs
                WHERE name ILIKE %s
                ORDER BY completed_at IS NOT NULL, created_at DESC
                LIMIT 1
            """, (f'%{name_search}%',))
            return _serialize_row(_fetchone(cur))
    except Exception as e:
        logger.error(f"Failed to find bug '{name_search}': {e}")
        return None


def get_active_bugs(priority=None, status=None, search=None):
    """Get active bugs (not completed). Optional filters."""
    ensure_bug_tables()
    try:
        conditions = ["completed_at IS NULL", "status != 'Parking Lot'"]
        params = []
        if priority:
            conditions.append("priority = %s")
            params.append(priority)
        if status:
            conditions.append("status = %s")
            params.append(status)
        if search:
            conditions.append("(name ILIKE %s OR description ILIKE %s)")
            params.extend([f'%{search}%', f'%{search}%'])

        where = " AND ".join(conditions)
        with db_cursor() as cur:
            cur.execute(f"""
                SELECT * FROM pilgrim.bugs
                WHERE {where}
                ORDER BY
                    CASE status
                        WHEN 'Awaiting QA' THEN 1
                        WHEN 'Ready For Dev' THEN 2
                        WHEN 'ReOpen' THEN 3
                        WHEN 'Backlog' THEN 4
                        WHEN 'New' THEN 5
                        -- Legacy statuses
                        WHEN 'In Process' THEN 4
                        WHEN 'In Progress' THEN 4
                        WHEN 'In Review' THEN 1
                        WHEN 'Blocked' THEN 3
                        WHEN 'Todo' THEN 5
                        ELSE 6
                    END,
                    CASE priority
                        WHEN 'P1' THEN 1 WHEN 'P2' THEN 2
                        WHEN 'P3' THEN 3 WHEN 'P4' THEN 4
                        WHEN 'P5' THEN 5 ELSE 6
                    END,
                    created_at DESC
            """, tuple(params))
            return _serialize_rows(_fetchall(cur))
    except Exception as e:
        logger.error(f"Failed to get active bugs: {e}")
        return []


def get_completed_bugs(limit=50, search=None):
    """Get completed bugs, newest first."""
    ensure_bug_tables()
    try:
        conditions = ["completed_at IS NOT NULL"]
        params = []
        if search:
            conditions.append("(name ILIKE %s OR description ILIKE %s)")
            params.extend([f'%{search}%', f'%{search}%'])
        params.append(limit)

        where = " AND ".join(conditions)
        with db_cursor() as cur:
            cur.execute(f"""
                SELECT * FROM pilgrim.bugs
                WHERE {where}
                ORDER BY completed_at DESC
                LIMIT %s
            """, tuple(params))
            return _serialize_rows(_fetchall(cur))
    except Exception as e:
        logger.error(f"Failed to get completed bugs: {e}")
        return []


def update_bug(bug_id, changed_by, **fields):
    """Update bug fields and log changes to bug_history.

    Usage: update_bug(42, 'PilgrimBot', status='AWAITING_QA', to_validate='TEST: ...')
    """
    ensure_bug_tables()
    if not fields:
        return False
    try:
        with db_cursor(commit=True) as cur:
            # Fetch current values
            cur.execute("SELECT * FROM pilgrim.bugs WHERE id = %s", (bug_id,))
            old = _fetchone(cur)
            if not old:
                return False

            # Log each changed field
            for field, new_val in fields.items():
                old_val = str(old.get(field, '') or '')
                new_str = str(new_val) if new_val is not None else ''
                if old_val != new_str:
                    cur.execute("""
                        INSERT INTO pilgrim.bug_history
                            (bug_id, changed_by, field_name, old_value, new_value)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (bug_id, changed_by, field, old_val, new_str))

            # Build dynamic UPDATE
            set_parts = [f"{k} = %s" for k in fields]
            set_parts.append("updated_at = NOW()")
            vals = list(fields.values()) + [bug_id]
            cur.execute(
                f"UPDATE pilgrim.bugs SET {', '.join(set_parts)} WHERE id = %s",
                tuple(vals)
            )
            return True
    except Exception as e:
        logger.error(f"Failed to update bug {bug_id}: {e}")
        return False


def complete_bug(bug_id, changed_by):
    """Mark bug as completed. Checks qa_approved first."""
    bug = get_bug_by_id(bug_id)
    if not bug:
        return False, "Bug not found"
    if not bug.get('qa_approved'):
        return False, "QA approval required before completing"
    return update_bug(bug_id, changed_by,
                      status='Done', completed_at=datetime.utcnow()), None


def reopen_bug(bug_id, changed_by):
    """Reopen a completed bug."""
    return update_bug(bug_id, changed_by,
                      completed_at=None, status='New', qa_approved=False), None


def search_bugs(keyword):
    """Search across ALL bugs (active + completed) by name or description."""
    ensure_bug_tables()
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT * FROM pilgrim.bugs
                WHERE name ILIKE %s OR description ILIKE %s
                ORDER BY completed_at IS NOT NULL, updated_at DESC
                LIMIT 50
            """, (f'%{keyword}%', f'%{keyword}%'))
            return _serialize_rows(_fetchall(cur))
    except Exception as e:
        logger.error(f"Failed to search bugs: {e}")
        return []


def get_bug_history(bug_id):
    """Get full audit trail for a bug."""
    ensure_bug_tables()
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT * FROM pilgrim.bug_history
                WHERE bug_id = %s
                ORDER BY created_at DESC
            """, (bug_id,))
            return _serialize_rows(_fetchall(cur))
    except Exception as e:
        logger.error(f"Failed to get bug history: {e}")
        return []


def get_bug_stats():
    """Get counts and velocity metrics for dashboard."""
    ensure_bug_tables()
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT
                    -- Core counts
                    COUNT(*) FILTER (WHERE completed_at IS NULL) AS active_count,
                    COUNT(*) FILTER (WHERE completed_at IS NOT NULL) AS completed_count,
                    COUNT(*) FILTER (WHERE completed_at IS NULL AND status = 'Awaiting QA') AS awaiting_qa,
                    COUNT(*) FILTER (WHERE completed_at IS NULL AND priority = 'P1') AS p1_count,
                    COUNT(*) FILTER (WHERE completed_at IS NULL AND priority = 'P2') AS p2_count,

                    -- Dev metrics
                    COUNT(*) FILTER (WHERE completed_at >= NOW() - INTERVAL '7 days') AS closed_this_week,
                    COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '7 days') AS filed_this_week,
                    COUNT(*) FILTER (WHERE completed_at >= NOW() - INTERVAL '30 days') AS closed_this_month,
                    ROUND(EXTRACT(EPOCH FROM AVG(
                        CASE WHEN completed_at > created_at THEN completed_at - created_at END
                    ) FILTER (WHERE completed_at IS NOT NULL AND completed_at > created_at)) / 3600) AS avg_close_hours,
                    EXTRACT(DAY FROM NOW() - MIN(created_at) FILTER (WHERE completed_at IS NULL))::int AS oldest_open_days,
                    COUNT(*) FILTER (WHERE completed_at IS NULL AND status IN ('Ready For Dev', 'In Progress')) AS dev_queue,
                    COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '7 days' AND priority = 'P1') AS p1_filed_this_week,

                    -- QA metrics
                    COUNT(*) FILTER (WHERE completed_at IS NULL AND status = 'Awaiting QA') AS qa_queue,
                    COUNT(*) FILTER (WHERE qa_approved = true AND completed_at >= NOW() - INTERVAL '7 days') AS qa_passed_this_week,
                    COUNT(*) FILTER (WHERE status = 'ReOpen') AS reopened_count,
                    COUNT(*) FILTER (WHERE status = 'ReOpen' AND created_at >= NOW() - INTERVAL '30 days') AS reopened_this_month,
                    COUNT(*) FILTER (WHERE completed_at IS NULL AND status = 'New') AS new_untriaged,
                    COUNT(*) FILTER (WHERE completed_at IS NULL AND status = 'Backlog') AS backlog_count
                FROM pilgrim.bugs
                WHERE status != 'Parking Lot'
            """)
            return _fetchone(cur)
    except Exception as e:
        logger.error(f"Failed to get bug stats: {e}")
        return {}


# =============================================================================
# SCREENSHOTS — GCS upload
# =============================================================================

def upload_bug_screenshot(bug_id, file_data, filename, content_type='image/png',
                          field='screenshot_url'):
    """Upload screenshot to GCS and save URL to bug record.

    Args:
        bug_id: Bug ID to attach screenshot to
        file_data: Raw file bytes
        filename: Original filename (for extension)
        content_type: MIME type
        field: 'screenshot_url', 'screenshot_2_url', or 'screenshot_3_url'
    Returns:
        GCS public URL or None
    """
    from google.cloud import storage as gcs_storage

    try:
        ext = filename.rsplit('.', 1)[-1] if '.' in filename else 'png'
        ts = int(datetime.utcnow().timestamp())
        blob_name = f"bugs/{bug_id}_{ts}.{ext}"

        client = gcs_storage.Client(project="galactica-character-game")
        bucket = client.bucket("galactica-pilgrim-assets")
        blob = bucket.blob(blob_name)
        blob.cache_control = 'public, max-age=604800'
        blob.upload_from_string(file_data, content_type=content_type, timeout=60)

        public_url = f"https://storage.googleapis.com/galactica-pilgrim-assets/{blob_name}"

        update_bug(bug_id, 'system', **{field: public_url})
        logger.info(f"Screenshot uploaded for bug {bug_id}: {public_url}")
        return public_url
    except Exception as e:
        logger.error(f"Failed to upload screenshot for bug {bug_id}: {e}")
        return None


# =============================================================================
# IDEAS (Parking Lot) — stored in bugs table with status='Parking Lot'
# =============================================================================

def get_ideas(category=None):
    """Get all parking lot ideas (bugs with status='Parking Lot')."""
    ensure_bug_tables()
    try:
        if category:
            sql = "SELECT * FROM pilgrim.bugs WHERE status = 'Parking Lot' AND type = %s ORDER BY created_at DESC"
            params = (category,)
        else:
            sql = "SELECT * FROM pilgrim.bugs WHERE status = 'Parking Lot' ORDER BY created_at DESC"
            params = ()
        with db_cursor() as cur:
            cur.execute(sql, params)
            rows = _serialize_rows(_fetchall(cur))
            # Map bug fields to legacy idea fields for frontend compat
            for r in rows:
                r['category'] = r.get('type', 'Feature')
                r['notes'] = r.get('extra_notes', '') or ''
            return rows
    except Exception as e:
        logger.error(f"Failed to get ideas: {e}")
        return []


def create_idea(name, description='', category='Feature'):
    """Create a new idea in the parking lot (stored as a bug with status='Parking Lot')."""
    ensure_bug_tables()
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO pilgrim.bugs (name, description, type, priority, status, source)
                VALUES (%s, %s, %s, 'P5', 'Parking Lot', 'Idea')
                RETURNING *
            """, (name, description, category))
            row = _serialize_row(_fetchone(cur))
            if row:
                row['category'] = row.get('type', 'Feature')
                row['notes'] = row.get('extra_notes', '') or ''
            return row
    except Exception as e:
        logger.error(f"Failed to create idea: {e}")
        return None


def add_idea_note(idea_id, note_text):
    """Append a timestamped note to a parking lot idea."""
    ensure_bug_tables()
    try:
        ts = datetime.utcnow().strftime('%Y-%m-%d %H:%M')
        entry = f'{ts}: {note_text}'
        with db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE pilgrim.bugs
                SET extra_notes = CASE WHEN COALESCE(extra_notes, '') = '' THEN %s ELSE extra_notes || '|' || %s END,
                    updated_at = NOW()
                WHERE id = %s AND status = 'Parking Lot'
            """, (entry, entry, idea_id))
            return True
    except Exception as e:
        logger.error(f"Failed to add note to idea {idea_id}: {e}")
        return False


def promote_idea(idea_id, priority='P3'):
    """Promote a parking lot idea to active bug. Just changes status and priority."""
    ensure_bug_tables()
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE pilgrim.bugs
                SET status = 'New', priority = %s, source = 'Promoted', updated_at = NOW()
                WHERE id = %s AND status = 'Parking Lot'
                RETURNING *
            """, (priority, idea_id))
            bug = _fetchone(cur)
            if not bug:
                return None
            return _serialize_row(bug)
    except Exception as e:
        logger.error(f"Failed to promote idea {idea_id}: {e}")
        return None


# =============================================================================
# COMMENTS — per-bug discussion thread
# =============================================================================

def get_bug_comments(bug_id):
    """Get all comments for a bug, oldest first."""
    ensure_bug_tables()
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT * FROM pilgrim.bug_comments
                WHERE bug_id = %s ORDER BY created_at DESC
            """, (bug_id,))
            return _serialize_rows(_fetchall(cur))
    except Exception as e:
        logger.error(f"Failed to get comments for bug {bug_id}: {e}")
        return []


def add_bug_comment(bug_id, author, body):
    """Add a comment to a bug. Returns the new comment or None.
    Auto-emails users mentioned with @name (matched against pilgrim.users)."""
    ensure_bug_tables()
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO pilgrim.bug_comments (bug_id, author, body)
                VALUES (%s, %s, %s) RETURNING *
            """, (bug_id, author, body))
            comment = _serialize_row(_fetchone(cur))
            # Touch updated_at so "Recently Updated" sort reflects new comments
            cur.execute("UPDATE pilgrim.bugs SET updated_at = NOW() WHERE id = %s", (bug_id,))

        # Send email notifications for @mentions (fire-and-forget)
        if comment:
            import threading
            threading.Thread(target=_notify_mentions, args=(bug_id, author, body)).start()

        return comment
    except Exception as e:
        logger.error(f"Failed to add comment to bug {bug_id}: {e}")
        return None


def _notify_mentions(bug_id, author, body):
    """Find @mentions in comment body, match against users, send email notifications."""
    import re
    mentions = re.findall(r'@(\w+)', body)
    if not mentions:
        return

    try:
        # Look up bug name
        bug = get_bug_by_id(bug_id)
        bug_name = bug['name'] if bug else f'Bug #{bug_id}'

        # Match mentions against users (name, given_name, or email with dots stripped)
        with db_cursor() as cur:
            for mention in mentions:
                mention_lower = mention.lower()
                cur.execute("""
                    SELECT DISTINCT email, name FROM pilgrim.users
                    WHERE LOWER(name) LIKE %s
                       OR LOWER(given_name) LIKE %s
                       OR LOWER(email) LIKE %s
                       OR REPLACE(LOWER(email), '.', '') LIKE %s
                    LIMIT 1
                """, (f'%{mention_lower}%', f'%{mention_lower}%', f'{mention_lower}%', f'{mention_lower}%'))
                row = _fetchone(cur)
                if not row or not row.get('email'):
                    continue

                to_email = row['email']
                from utilities.email.mentions import send_mention_notification
                send_mention_notification(
                    bug_id=bug_id,
                    bug_name=bug_name,
                    to_email=to_email,
                    author=author,
                    comment_body=body,
                )
                logger.info(f"Bug #{bug_id}: sent @mention email to {to_email} for mention @{mention}")

    except Exception as e:
        logger.error(f"Failed to send @mention notifications for bug {bug_id}: {e}")
