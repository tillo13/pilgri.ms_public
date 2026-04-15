"""PilgrimBot database storage: conversations table, roles, message history, API call logging."""

import json
import logging

from utilities.postgres.core import db_cursor

logger = logging.getLogger("pilgrimbot")

MAX_HISTORY = 20  # messages (10 exchanges)


def get_pilgrimbot_page_data(user_id, flask_session, brainstorm_page, bug_id):
    """Build the render context for the /pilgrimbot page.

    Resolves chats, persisted role (cached in session), and optional
    bug/brainstorm prefill context.
    """
    chats = get_user_chats(user_id) if user_id else []
    pb_role = flask_session.get('_pb_role')
    if not pb_role:
        pb_role = get_user_role(user_id) if user_id else 'captain'
        flask_session['_pb_role'] = pb_role
    from utilities.pilgrimbot_context import build_prefill_context
    combined_context, display_name, _bug, _bp = build_prefill_context(brainstorm_page, bug_id)
    return {
        'chats': chats,
        'pb_role': pb_role,
        'bug_context': combined_context,
        'bug_id': bug_id,
        'bug_name': display_name,
        'brainstorm_page': brainstorm_page,
    }


def upload_pilgrimbot_screenshot(user_id, file_storage):
    """Upload a pasted screenshot for PilgrimBot chat to GCS. Returns response dict.

    Used by POST /api/pilgrimbot/upload. Shape:
      success path: {'success': True, 'url': <https url>}
      failure path: {'success': False, 'error': <str>}
    """
    if not user_id:
        return {'success': False, 'error': 'Not logged in'}
    if not file_storage:
        return {'success': False, 'error': 'No image provided'}
    try:
        import time as _time
        from google.cloud import storage as gcs_storage
        ext = (file_storage.filename.rsplit('.', 1)[-1]
               if file_storage.filename and '.' in file_storage.filename else 'png')
        blob_name = f"pilgrimbot/chat_{user_id}_{int(_time.time())}.{ext}"
        client = gcs_storage.Client(project="galactica-character-game")
        bucket = client.bucket("galactica-pilgrim-assets")
        blob = bucket.blob(blob_name)
        blob.cache_control = 'public, max-age=604800'
        blob.upload_from_string(
            file_storage.read(),
            content_type=file_storage.content_type or 'image/png',
            timeout=60,
        )
        return {
            'success': True,
            'url': f"https://storage.googleapis.com/galactica-pilgrim-assets/{blob_name}",
        }
    except Exception as e:
        logger.error(f"PilgrimBot image upload failed: {e}")
        return {'success': False, 'error': 'Upload failed'}


def _strip_markdown_json(text):
    """Strip markdown code fence from Claude's JSON responses."""
    text = text.strip()
    if text.startswith('```'):
        text = text.split('\n', 1)[-1].rsplit('```', 1)[0].strip()
    return text


# === Database ===

_tables_ensured = False

def ensure_pilgrimbot_table():
    """Create the pilgrimbot conversations table + role column if they don't exist.
    Uses a module-level flag so schema checks only run once per process."""
    global _tables_ensured
    if _tables_ensured:
        return
    _tables_ensured = True
    with db_cursor(commit=True) as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pilgrim.pilgrimbot_conversations (
                id SERIAL PRIMARY KEY,
                user_id INTEGER,
                chat_id UUID NOT NULL,
                title VARCHAR(200),
                role VARCHAR(20) NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_pilgrimbot_user_chat
            ON pilgrim.pilgrimbot_conversations(user_id, chat_id)
        """)
        # Add pilgrimbot_role to users table (dev/qa/captain)
        cur.execute("""
            ALTER TABLE pilgrim.users ADD COLUMN IF NOT EXISTS
            pilgrimbot_role VARCHAR(20) DEFAULT 'captain'
        """)
        # Soft-delete column for hiding conversations
        cur.execute("""
            ALTER TABLE pilgrim.pilgrimbot_conversations ADD COLUMN IF NOT EXISTS
            hidden BOOLEAN DEFAULT FALSE
        """)
        # PilgrimBot call logging — tracks every API call for performance analysis
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pilgrim.pilgrimbot_calls (
                id SERIAL PRIMARY KEY,
                user_id INTEGER,
                chat_id UUID,
                phase VARCHAR(20) NOT NULL,
                model VARCHAR(80),
                prompt_size_chars INTEGER,
                context_loaded JSONB DEFAULT '[]',
                duration_ms INTEGER,
                success BOOLEAN DEFAULT TRUE,
                error_message TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_pilgrimbot_calls_user
            ON pilgrim.pilgrimbot_calls(user_id, created_at DESC)
        """)


def get_user_role(user_id):
    """Get user's PilgrimBot persona role (dev/qa/captain)."""
    with db_cursor() as cur:
        cur.execute("SELECT pilgrimbot_role FROM pilgrim.users WHERE id = %s", (user_id,))
        row = cur.fetchone()
    return (row['pilgrimbot_role'] if row and row['pilgrimbot_role'] else 'captain')


def set_user_role(user_id, role):
    """Set user's PilgrimBot persona role. Returns True on success."""
    if role not in ('dev', 'qa', 'captain'):
        return False
    with db_cursor(commit=True) as cur:
        cur.execute("UPDATE pilgrim.users SET pilgrimbot_role = %s WHERE id = %s", (role, user_id))
    return True


def save_message(user_id, chat_id, role, content, title=None):
    """Save a message to the database."""
    with db_cursor(commit=True) as cur:
        cur.execute("""
            INSERT INTO pilgrim.pilgrimbot_conversations
            (user_id, chat_id, role, content, title)
            VALUES (%s, %s, %s, %s, %s)
        """, (user_id, str(chat_id), role, content, title))


def get_chat_history(user_id, chat_id, limit=MAX_HISTORY):
    """Load conversation history for a specific chat. Uses subquery to fetch only last N rows."""
    with db_cursor() as cur:
        cur.execute("""
            SELECT role, content, created_at FROM (
                SELECT role, content, created_at FROM pilgrim.pilgrimbot_conversations
                WHERE user_id = %s AND chat_id = %s
                ORDER BY created_at DESC
                LIMIT %s
            ) sub ORDER BY created_at ASC
        """, (user_id, str(chat_id), limit))
        rows = cur.fetchall()
    return [{"role": r['role'], "content": r['content'],
             "created_at": r['created_at'].isoformat() if r.get('created_at') else None}
            for r in rows]


def get_user_chats(user_id):
    """List all chat threads for a user, most recent first."""
    ensure_pilgrimbot_table()
    with db_cursor() as cur:
        cur.execute("""
            SELECT chat_id, MAX(title) AS title,
                   MIN(created_at) AS started,
                   MAX(created_at) AS last_message,
                   COUNT(*) AS message_count
            FROM pilgrim.pilgrimbot_conversations
            WHERE user_id = %s AND (hidden IS NOT TRUE)
            GROUP BY chat_id
            ORDER BY MAX(created_at) DESC
            LIMIT 50
        """, (user_id,))
        rows = cur.fetchall()
    return [{
        "chat_id": str(r['chat_id']),
        "title": r['title'] or "Untitled chat",
        "started": r['started'].isoformat() if r.get('started') else None,
        "last_message": r['last_message'].isoformat() if r.get('last_message') else None,
        "message_count": r['message_count'],
    } for r in rows]


def hide_chat(user_id, chat_id):
    """Soft-delete a chat thread by marking all its messages as hidden."""
    with db_cursor(commit=True) as cur:
        cur.execute("""
            UPDATE pilgrim.pilgrimbot_conversations
            SET hidden = TRUE
            WHERE user_id = %s AND chat_id = %s
        """, (user_id, str(chat_id)))
        return cur.rowcount > 0


def generate_title(message):
    """Generate a short title from the first user message.
    For bug mode messages, extract 'Bug #N: Name' instead of verbose context."""
    import re
    bug_match = re.search(r'Bug #(\d+):\s*(.+?)(?:\n|$)', message)
    if bug_match:
        return f"Bug #{bug_match.group(1)}: {bug_match.group(2).strip()}"[:80]
    title = message.strip()[:80]
    if len(message) > 80:
        title = title.rsplit(" ", 1)[0] + "..."
    return title


def log_pilgrimbot_call(user_id, chat_id, phase, model, prompt_size_chars,
                        context_loaded, duration_ms, success=True, error_message=None):
    """Log a PilgrimBot API call for performance tracking."""
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO pilgrim.pilgrimbot_calls
                (user_id, chat_id, phase, model, prompt_size_chars, context_loaded,
                 duration_ms, success, error_message)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (user_id, str(chat_id) if chat_id else None, phase, model,
                  prompt_size_chars, json.dumps(context_loaded),
                  duration_ms, success, error_message))
    except Exception as e:
        logger.warning(f"Failed to log pilgrimbot call: {e}")
