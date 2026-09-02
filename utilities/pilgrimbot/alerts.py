"""PilgrimBot failure alert: one email to Andy the moment a chat dies, debounced.

2026-08-20 → 09-02 PilgrimBot was dark for 13 days (anthropic SDK 1.0 dropped
temperature=). The daily cross-project error digest did carry the TypeError on
08-25 — as 5 of 57 errors, under an 18x HTTP 500 line — and Luke typed "hi, are
you working" into the chat. Nobody saw either. This is the dedicated channel:
subject names the captain and the error, body carries everything needed to act.
"""
import logging
from datetime import datetime, timezone
from importlib.metadata import version as _pkg_version

from utilities.postgres.core import db_cursor

logger = logging.getLogger("pilgrimbot")

ALERT_TO = ['andy.tillo@gmail.com']   # CLAUDE.md email safety: Andy only, never a player
DEBOUNCE_MINUTES = 60
SIGNATURE_CHARS = 120


def _recent_same_failures(error_message, minutes=DEBOUNCE_MINUTES):
    """Failed pilgrimbot_calls rows sharing this error signature inside the window.
    The failing call's own row is already inserted, so 1 == first occurrence."""
    with db_cursor() as cur:
        cur.execute("""
            SELECT count(*) AS n FROM pilgrim.pilgrimbot_calls
            WHERE success = false
              AND created_at > now() - (%s * interval '1 minute')
              AND left(error_message, %s) = left(%s, %s)
        """, (minutes, SIGNATURE_CHARS, error_message, SIGNATURE_CHARS))
        return cur.fetchone()['n']


def _captain_label(user_id):
    try:
        with db_cursor() as cur:
            cur.execute("SELECT captain_name, name, email FROM pilgrim.users WHERE id = %s", (user_id,))
            row = cur.fetchone()
        if row:
            return f"{row['captain_name'] or row['name']} <{row['email']}> (user {user_id})"
    except Exception:
        pass
    return f"user {user_id}"


def _send(subject, body):
    from utilities.email.transport import send_email
    return send_email(subject, body, ALERT_TO, from_name='PilgrimBot')


def _now_pt():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo('America/Los_Angeles')).strftime('%Y-%m-%d %H:%M PT')
    except Exception:
        return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')


def alert_pilgrimbot_failure(user_id, chat_id, question, exc, model, had_partial):
    """Email Andy about a PilgrimBot chat failure. Never raises.
    Returns True if sent; False if debounced (same error already alerted inside
    DEBOUNCE_MINUTES) or the send itself failed."""
    try:
        error_message = str(exc)   # same string log_pilgrimbot_call stored — the debounce key
        if _recent_same_failures(error_message) > 1:
            logger.info("PilgrimBot failure alert debounced — same error already alerted this hour")
            return False
        try:
            sdk = _pkg_version('anthropic')
        except Exception:
            sdk = 'unknown'
        captain = _captain_label(user_id)
        labeled = f"{type(exc).__name__}: {error_message}"
        subject = f"PilgrimBot failed for {captain.split(' <')[0]} — {labeled[:90]}"
        body = (
            f"PilgrimBot chat died at {_now_pt()}.\n\n"
            f"Captain:  {captain}\n"
            f"Chat:     {chat_id}\n"
            f"Model:    {model}\n"
            f"SDK:      anthropic {sdk}\n"
            f"Partial:  {'yes — the phase 1 answer was delivered' if had_partial else 'no — the captain saw only the error line'}\n\n"
            f"Question:\n  {question}\n\n"
            f"Error:\n  {labeled}\n\n"
            f"Repeats of this exact error inside the last {DEBOUNCE_MINUTES} min are not re-sent.\n"
            "Row log: SELECT * FROM pilgrim.pilgrimbot_calls WHERE success = false "
            "ORDER BY created_at DESC LIMIT 20;\n"
        )
        sent = _send(subject, body)
        logger.info(f"PilgrimBot failure alert {'sent' if sent else 'NOT sent'} to {ALERT_TO}")
        return bool(sent)
    except Exception as e:
        logger.warning(f"PilgrimBot failure alert itself failed: {e}")
        return False
