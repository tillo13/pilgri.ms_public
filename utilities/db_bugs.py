"""Bug tracker database operations.

Replaces Google Sheets bug tracking with PostgreSQL.
Four tables: bugs, bug_history (audit), bug_ideas (parking lot), bug_comments (threads).
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional
from utilities.postgres_utils import db_cursor, _fetchone, _fetchall

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

            cur.execute("""
                CREATE TABLE IF NOT EXISTS pilgrim.bug_ideas (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(200) NOT NULL,
                    description TEXT DEFAULT '',
                    category VARCHAR(30) DEFAULT 'Feature',
                    status VARCHAR(30) DEFAULT 'New',
                    notes TEXT DEFAULT '',
                    promoted_to_bug_id INTEGER REFERENCES pilgrim.bugs(id),
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)

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
        conditions = ["completed_at IS NULL"]
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
    """Get counts by status and priority for dashboard."""
    ensure_bug_tables()
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT
                    COUNT(*) FILTER (WHERE completed_at IS NULL) AS active_count,
                    COUNT(*) FILTER (WHERE completed_at IS NOT NULL) AS completed_count,
                    COUNT(*) FILTER (WHERE completed_at IS NULL AND status = 'Awaiting QA') AS awaiting_qa,
                    COUNT(*) FILTER (WHERE completed_at IS NULL AND priority = 'P1') AS p1_count,
                    COUNT(*) FILTER (WHERE completed_at IS NULL AND priority = 'P2') AS p2_count
                FROM pilgrim.bugs
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
        field: 'screenshot_url' or 'screenshot_2_url'
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
# IDEAS (Parking Lot)
# =============================================================================

def get_ideas(category=None):
    """Get all ideas, optionally filtered by category."""
    ensure_bug_tables()
    try:
        if category:
            sql = "SELECT * FROM pilgrim.bug_ideas WHERE category = %s ORDER BY created_at DESC"
            params = (category,)
        else:
            sql = "SELECT * FROM pilgrim.bug_ideas ORDER BY created_at DESC"
            params = ()
        with db_cursor() as cur:
            cur.execute(sql, params)
            return _serialize_rows(_fetchall(cur))
    except Exception as e:
        logger.error(f"Failed to get ideas: {e}")
        return []


def create_idea(name, description='', category='Feature'):
    """Create a new idea in the parking lot."""
    ensure_bug_tables()
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO pilgrim.bug_ideas (name, description, category)
                VALUES (%s, %s, %s)
                RETURNING *
            """, (name, description, category))
            return _serialize_row(_fetchone(cur))
    except Exception as e:
        logger.error(f"Failed to create idea: {e}")
        return None


def add_idea_note(idea_id, note_text):
    """Append a timestamped note to an idea."""
    ensure_bug_tables()
    try:
        ts = datetime.utcnow().strftime('%Y-%m-%d %H:%M')
        with db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE pilgrim.bug_ideas
                SET notes = CASE WHEN notes = '' THEN %s ELSE notes || '|' || %s END
                WHERE id = %s
            """, (f'{ts}: {note_text}', f'{ts}: {note_text}', idea_id))
            return True
    except Exception as e:
        logger.error(f"Failed to add note to idea {idea_id}: {e}")
        return False


def promote_idea(idea_id, priority='P3'):
    """Promote an idea to an active bug. Returns the new bug or None."""
    ensure_bug_tables()
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("SELECT * FROM pilgrim.bug_ideas WHERE id = %s", (idea_id,))
            idea = _fetchone(cur)
            if not idea:
                return None

            cur.execute("""
                INSERT INTO pilgrim.bugs (name, description, type, priority, source)
                VALUES (%s, %s, %s, %s, 'Promoted')
                RETURNING *
            """, (idea['name'], idea['description'], idea['category'], priority))
            bug = _fetchone(cur)

            cur.execute("""
                UPDATE pilgrim.bug_ideas SET promoted_to_bug_id = %s, status = 'Promoted'
                WHERE id = %s
            """, (bug['id'], idea_id))

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
                user_name = row.get('name', mention)
                link = f'https://pilgri.ms/admin/bugs?open={bug_id}'

                subject = f'Bug #{bug_id}: {bug_name}'
                html_body = f"""<div style="font-family:sans-serif;max-width:600px;">
<p><strong>{author}</strong> mentioned you on <a href="{link}">Bug #{bug_id}: {bug_name}</a></p>
<div style="background:#1e1e36;color:#e0e0e0;padding:16px;border-radius:8px;margin:12px 0;white-space:pre-wrap;">{body}</div>
<p><a href="{link}" style="display:inline-block;padding:10px 20px;background:#f97316;color:white;text-decoration:none;border-radius:6px;font-weight:bold;">View Bug</a></p>
</div>"""

                from utilities.gmail_utils import send_simple_email
                send_simple_email(subject, html_body, to_email, is_html=True)
                logger.info(f"Bug #{bug_id}: sent @mention email to {to_email} for mention @{mention}")

    except Exception as e:
        logger.error(f"Failed to send @mention notifications for bug {bug_id}: {e}")
