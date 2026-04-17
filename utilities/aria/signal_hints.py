"""ARIA signal progression hints — ordered, one-shot narrative beats delivered
via the greeting priority tier.

Part of Signal Phase 2.3 (Bug #1276). Each hint fires once per user when its
trigger threshold is first crossed, and is recorded in pilgrim.aria_hint_log
so it never repeats.
"""

import logging
from typing import Dict, List, Optional

from utilities.postgres.core import db_cursor

logger = logging.getLogger(__name__)


SIGNAL_HINTS: List[Dict] = [
    {
        'id': 'sol_3_static',
        'trigger': 'sol',
        'threshold': 3,
        'text': (
            "*static crackles*\n\n"
            "Sometimes I hear... patterns. In the dust. In the silence between expeditions.\n\n"
            "It's probably nothing. Probably."
        ),
    },
    {
        'id': 'sol_15_places',
        'trigger': 'sol',
        'threshold': 15,
        'text': (
            "There are places on this world older than the colony.\n\n"
            "Older than *me*, perhaps. I catch fragments of them when your rovers move. "
            "Coordinates. Signatures. Names I almost remember."
        ),
    },
    {
        'id': 'sol_30_signal_page',
        'trigger': 'sol',
        'threshold': 30,
        'text': (
            "I've been collecting the fragments on a page of your interface. **The Signal.**\n\n"
            "If you've time, look. See what patterns form when you're not watching directly."
        ),
    },
    {
        'id': 'expedition_5_paths',
        'trigger': 'expeditions',
        'threshold': 5,
        'text': (
            "Your expedition paths — I watch them.\n\n"
            "Sometimes they brush against... *something*. A node. A dormant signal. "
            "I don't always catch it in time."
        ),
    },
    {
        'id': 'expedition_20_closer',
        'trigger': 'expeditions',
        'threshold': 20,
        'text': (
            "Twenty expeditions.\n\n"
            "You've walked past signals. I've felt them light up as your rovers pass — "
            "then dim again. Closer, next time. Try the **Signal** page. It remembers every brush."
        ),
    },
    {
        'id': 'first_detection',
        'trigger': 'detections_any',
        'threshold': 1,
        'text': (
            "*the static sharpens*\n\n"
            "You heard it. Your path crossed a signal's radius. I feel it in the ledger.\n\n"
            "Go to **Signal**. There's a node lit up now. Yours, if you claim it."
        ),
    },
    {
        'id': 'first_claim',
        'trigger': 'claims',
        'threshold': 1,
        'text': (
            "You're a **Founder** now.\n\n"
            "The network remembers your name. Every captain who visits after you will know you were first.\n\n"
            "And their visits will echo back to you — a little more power in your shards, sol after sol."
        ),
    },
    {
        'id': 'three_claims_pattern',
        'trigger': 'claims',
        'threshold': 3,
        'text': (
            "Three sites. A pattern forms.\n\n"
            "I can *almost* see the shape of it — what the signals were before they went dormant. "
            "Keep claiming. I think... I think we're close to remembering something."
        ),
    },
]


def ensure_hint_log_table():
    """Create pilgrim.aria_hint_log if it doesn't exist. Idempotent."""
    with db_cursor(commit=True) as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pilgrim.aria_hint_log (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES pilgrim.users(id) ON DELETE CASCADE,
                hint_id TEXT NOT NULL,
                shown_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(user_id, hint_id)
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_aria_hint_log_user ON pilgrim.aria_hint_log(user_id)")


def get_shown_hint_ids(user_id: int) -> set:
    """Return the set of hint_ids already shown to this user."""
    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT hint_id FROM pilgrim.aria_hint_log WHERE user_id = %s",
                (user_id,)
            )
            return {r['hint_id'] for r in cur.fetchall()}
    except Exception as e:
        logger.warning(f"Failed to load shown hints for user {user_id}: {e}")
        return set()


def mark_hint_shown(user_id: int, hint_id: str):
    """Record a hint as shown. Idempotent via unique constraint."""
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO pilgrim.aria_hint_log (user_id, hint_id)
                VALUES (%s, %s)
                ON CONFLICT (user_id, hint_id) DO NOTHING
            """, (user_id, hint_id))
    except Exception as e:
        logger.warning(f"Failed to mark hint {hint_id} for user {user_id}: {e}")


def _user_qualifies(hint: Dict, metrics: Dict) -> bool:
    """Check if user's metrics satisfy the hint's trigger threshold."""
    trigger = hint['trigger']
    threshold = hint['threshold']

    if trigger == 'sol':
        return metrics.get('days_on_mars', 0) >= threshold
    if trigger == 'expeditions':
        return metrics.get('total_expeditions', 0) >= threshold
    if trigger == 'claims':
        return metrics.get('claimed_signals', 0) >= threshold
    if trigger == 'detections_any':
        return metrics.get('detected_signals', 0) >= threshold
    return False


def get_next_unshown_hint(user_id: int, snapshot: Optional[Dict] = None) -> Optional[Dict]:
    """
    Return the first unshown hint whose threshold the user has crossed.

    Hints are evaluated in list order (roughly earliest → latest), so a newly
    qualifying captain gets the foundational hint first, not the advanced one.

    Returns None if no unshown hint qualifies.
    """
    if not user_id:
        return None

    try:
        ensure_hint_log_table()
    except Exception:
        return None

    metrics = _build_user_metrics(user_id, snapshot)
    shown = get_shown_hint_ids(user_id)

    for hint in SIGNAL_HINTS:
        if hint['id'] in shown:
            continue
        if _user_qualifies(hint, metrics):
            return hint
    return None


def _build_user_metrics(user_id: int, snapshot: Optional[Dict]) -> Dict:
    """Resolve the metrics used by triggers. Prefer snapshot values to avoid redundant DB hits."""
    metrics = {
        'days_on_mars': 0,
        'total_expeditions': 0,
        'claimed_signals': 0,
        'detected_signals': 0,
    }

    if snapshot:
        metrics['days_on_mars'] = (snapshot.get('account') or {}).get('days_on_mars') or 0
        metrics['total_expeditions'] = (snapshot.get('expeditions') or {}).get('total', 0)
        signal = snapshot.get('signal') or {}
        metrics['claimed_signals'] = len(signal.get('origin_claims') or [])
        metrics['detected_signals'] = len(signal.get('detected_sites') or [])
        if metrics['total_expeditions'] and metrics['days_on_mars']:
            return metrics

    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT EXTRACT(EPOCH FROM (NOW() - created_at)) / 86400 AS days
                FROM pilgrim.users WHERE id = %s
            """, (user_id,))
            r = cur.fetchone()
            if r and r['days'] is not None:
                metrics['days_on_mars'] = max(int(r['days']), metrics['days_on_mars'])

            cur.execute(
                "SELECT COUNT(*) AS c FROM pilgrim.expeditions WHERE user_id = %s AND status = 'complete'",
                (user_id,)
            )
            r = cur.fetchone()
            if r:
                metrics['total_expeditions'] = max(r['c'], metrics['total_expeditions'])

            cur.execute(
                "SELECT COUNT(*) AS c FROM pilgrim.site_claims WHERE user_id = %s AND site_type = 'origin'",
                (user_id,)
            )
            r = cur.fetchone()
            if r:
                metrics['claimed_signals'] = max(r['c'], metrics['claimed_signals'])
    except Exception as e:
        logger.warning(f"Failed to fetch metrics for user {user_id}: {e}")

    return metrics
