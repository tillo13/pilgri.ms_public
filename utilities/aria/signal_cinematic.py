"""Signal-claim cinematic data — Phase 2.3b.

Mirror of utilities/aria/first_contact.py. Pulls the pending signal_claim expedition,
shapes it into the cinematic template payload, and provides the before_request gate.
One-shot per expedition: cinematic_shown_at on the row prevents re-play.
"""

import logging
from types import SimpleNamespace

logger = logging.getLogger(__name__)


# Approach narrative — ARIA whispers as the captain crests the ridge.
# Modeled on first-contact.js LINES (~9 lines, 2.2s gap).
APPROACH_LINES = [
    {'text': '*signal pattern locking*', 'cls': 'static-crackle', 'sound': 'crackle'},
    {'text': "Captain, we're entering the resonance field."},
    {'text': "I can hear it more clearly now.", 'cls': 'emphasis'},
    {'text': "The signature... it's older than I expected."},
    {'text': "Older than ARIA. Older than the first colony."},
    {'text': "Cresting the ridge. Telemetry's holding."},
    {'text': "Captain — there.", 'cls': 'emphasis', 'sound': 'glitch'},
    {'text': "That's the source."},
    {'text': "Whatever happened here, the world remembered it.", 'cls': 'emphasis'},
]


def check_pending_signal_cinematic(path: str, method: str, is_authenticated: bool, flask_session) -> bool:
    """Before-request hook logic: returns True if caller should redirect to /signal-claim/<id>.

    Mutates session to cache "all shown" when no pending claim cinematic exists.
    """
    if not is_authenticated or method != 'GET':
        return False
    if path.startswith(('/static/', '/api/', '/admin/', '/signal-claim', '/aria-first-contact', '/auth')):
        return False
    if flask_session.get('_sc_shown_all'):
        return False
    user_id = flask_session.get('user_id')
    if not user_id:
        return False
    try:
        from utilities.postgres.expeditions import get_pending_signal_cinematic
        if get_pending_signal_cinematic(user_id):
            return True
        flask_session['_sc_shown_all'] = True
        flask_session.modified = True
    except Exception as e:
        logger.warning(f"Signal cinematic check failed: {e}")
    return False


def get_pending_redirect_id(user_id: int):
    """Helper for the redirect handler — returns the expedition_id to redirect to, or None."""
    try:
        from utilities.postgres.expeditions import get_pending_signal_cinematic
        row = get_pending_signal_cinematic(user_id)
        return row['id'] if row else None
    except Exception as e:
        logger.warning(f"get_pending_redirect_id failed: {e}")
        return None


def _build_cinematic_payload(expedition_row, site_row, captain_name, replay=False):
    """Shared template kwargs for the cinematic page."""
    payload = expedition_row.get('cinematic_payload') or {}
    if isinstance(payload, str):
        # JSONB sometimes deserializes as string; normalize.
        import json
        try:
            payload = json.loads(payload)
        except Exception:
            payload = {}

    outcome = payload.get('outcome') or 'unknown'
    result = payload.get('result') or {}

    return {
        'cinematic': SimpleNamespace(
            expedition_id=expedition_row['id'],
            site_id=site_row['id'] if site_row else None,
            site_code=site_row['site_code'] if site_row else expedition_row.get('destination_name'),
            mission_name=site_row['mission_name'] if site_row else '',
            memory_text=site_row.get('memory_text') if site_row else '',
            legendary_item_name=site_row.get('legendary_item_name') if site_row else None,
            legendary_item_image_url=site_row.get('legendary_item_image_url') if site_row else None,
            outcome=outcome,
            tier=payload.get('tier'),
            founder_name=result.get('founder_display') or result.get('founder_name') or site_row.get('founder_commander_name') if site_row else None,
            sol=payload.get('sol') or result.get('sol'),
            captain_name=captain_name or 'Captain',
        ),
        'approach_lines': APPROACH_LINES,
        'replay': replay,
    }


def _get_site_row(site_id):
    if not site_id:
        return None
    from utilities.postgres.core import db_cursor
    with db_cursor() as cur:
        cur.execute("SELECT * FROM pilgrim.origin_sites WHERE id = %s", (site_id,))
        return cur.fetchone()


def _get_captain_name(user_id):
    try:
        from utilities.signal.handlers import _get_commander_name_for_user
        return _get_commander_name_for_user(user_id) or 'Captain'
    except Exception:
        return 'Captain'


def build_signal_cinematic_render_data(user_id, expedition_id, flask_session):
    """Render data for /signal-claim/<expedition_id>. Marks one-shot.

    Returns (payload, redirect) — exactly one is truthy.
    """
    from utilities.postgres.core import db_cursor
    from utilities.postgres.expeditions import mark_signal_cinematic_shown

    with db_cursor() as cur:
        cur.execute("SELECT * FROM pilgrim.expeditions WHERE id = %s", (expedition_id,))
        expedition = cur.fetchone()

    if not expedition or expedition['user_id'] != user_id:
        return None, 'home'
    if expedition.get('expedition_type') != 'signal_claim':
        return None, 'home'

    site = _get_site_row(expedition.get('signal_site_id'))
    captain = _get_captain_name(user_id)

    # Mark cinematic as shown (one-shot). Replay route uses build_replay_render_data instead.
    mark_signal_cinematic_shown(expedition_id, user_id)
    flask_session.pop('_sc_shown_all', None)
    flask_session.modified = True

    return _build_cinematic_payload(expedition, site, captain), None


def build_signal_cinematic_replay_render_data(user_id, expedition_id):
    """Replay variant — no DB writes, no session mutation."""
    from utilities.postgres.core import db_cursor

    with db_cursor() as cur:
        cur.execute("SELECT * FROM pilgrim.expeditions WHERE id = %s", (expedition_id,))
        expedition = cur.fetchone()

    if not expedition or expedition['user_id'] != user_id:
        return None, 'home'
    if expedition.get('expedition_type') != 'signal_claim':
        return None, 'home'

    site = _get_site_row(expedition.get('signal_site_id'))
    captain = _get_captain_name(user_id)
    return _build_cinematic_payload(expedition, site, captain, replay=True), None


def build_admin_preview_render_data():
    """Admin preview — synthesize a payload from any signal_claim expedition, or fall back
    to the first Origin Site for a "founder outcome" preview without a real expedition.
    """
    from utilities.postgres.core import db_cursor

    with db_cursor() as cur:
        cur.execute("""
            SELECT * FROM pilgrim.expeditions
            WHERE expedition_type = 'signal_claim'
            ORDER BY id DESC LIMIT 1
        """)
        expedition = cur.fetchone()

    if expedition:
        site = _get_site_row(expedition.get('signal_site_id'))
        return _build_cinematic_payload(expedition, site, 'Captain Preview', replay=True), None

    # Synthetic fallback so admins can preview before any signal_claim has run.
    with db_cursor() as cur:
        cur.execute("SELECT * FROM pilgrim.origin_sites ORDER BY id LIMIT 1")
        site = cur.fetchone()
    if not site:
        return None, "No origin sites in DB to preview"

    fake_expedition = {
        'id': 0,
        'user_id': 0,
        'signal_site_id': site['id'],
        'destination_name': site['site_code'],
        'cinematic_payload': {
            'outcome': 'founder', 'tier': 'legendary',
            'result': {'founder_name': 'Captain Preview', 'sol': 0},
        },
    }
    return _build_cinematic_payload(fake_expedition, site, 'Captain Preview', replay=True), None
