"""ARIA first-contact cinematic data — one-shot bond-reveal and replay."""

import logging
from types import SimpleNamespace

from utilities.postgres.core import db_cursor

logger = logging.getLogger(__name__)


def check_pending_first_contact(path: str, method: str, is_authenticated: bool, flask_session) -> bool:
    """Before-request hook logic: returns True if caller should redirect to /aria-first-contact.

    Mutates session to cache "all shown" when no pending bond exists.
    """
    if not is_authenticated or method != 'GET':
        return False
    if path.startswith(('/static/', '/api/', '/admin/', '/aria-first-contact', '/auth')):
        return False
    if flask_session.get('_fc_shown_all'):
        return False
    user_id = flask_session.get('user_id')
    if not user_id:
        return False
    try:
        from utilities.aria.bonds import get_pending_first_contact
        if get_pending_first_contact(user_id):
            return True
        flask_session['_fc_shown_all'] = True
        flask_session.modified = True
    except Exception as e:
        logger.warning(f"First contact check failed: {e}")
    return False


def _build_render_payload(bond, bond_number, sol, replay=False, viewer_user_id=None):
    """Shared render-kwargs for the first-contact template.

    #1392: the revelation dialogue is TIERED by how many bonds the viewer already has
    (the "another me?" shock only lands the first time). personal_count = the viewer's
    bonds minus this one; admin preview (no viewer) falls back to the global ordinal.
    """
    from utilities.aria.bonds import _get_commander_name, get_user_bond_count, get_bond_revelation
    captain_1 = _get_commander_name(bond['user_id_1']) or f"Captain {bond['user_id_1']}"
    captain_2 = _get_commander_name(bond['user_id_2']) or f"Captain {bond['user_id_2']}"
    if viewer_user_id is not None:
        personal_count = max(0, get_user_bond_count(viewer_user_id) - 1)
    else:
        personal_count = max(0, (bond_number or 1) - 1)
    revelation = get_bond_revelation(personal_count)
    return {
        'bond': SimpleNamespace(**bond),
        'captain_1': captain_1,
        'captain_2': captain_2,
        'bond_number': bond_number,
        'sol': sol,
        'replay': replay,
        'revelation_lines': revelation['lines'],
        'personal_bond_count': personal_count,
    }


def _bond_number(bond_id):
    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) as count FROM pilgrim.aria_bonds WHERE id <= %s", (bond_id,))
        return cur.fetchone()['count']


def build_first_contact_render_data(user_id, session):
    """Prepare render data for the cinematic, completing the bond as a side effect.

    Returns (payload_dict, 'redirect') where exactly one is truthy:
      - payload: pass to render_template('aria_first_contact.html', **payload)
      - redirect: caller should redirect to the named endpoint ('home')
    """
    from utilities.aria.bonds import get_pending_first_contact, _complete_bond
    from utilities.mars_environment_utils import get_mars_sol_number

    bond = get_pending_first_contact(user_id)
    if not bond:
        session['_fc_shown'] = True
        session.modified = True
        return None, 'home'

    # Complete bond immediately on cinematic load — don't wait for button click.
    try:
        _complete_bond(bond['id'])
        logger.info(f"Bond #{bond['id']} completed on cinematic load for user {user_id}")
    except Exception as e:
        logger.warning(f"Bond completion on load failed (may already be bonded): {e}")

    # Mark first_contact_shown for this user (DB per-bond, session tracks "all shown").
    field = 'first_contact_shown_user_1' if user_id == bond['user_id_1'] else 'first_contact_shown_user_2'
    with db_cursor(commit=True) as cur:
        cur.execute(f"UPDATE pilgrim.aria_bonds SET {field} = TRUE WHERE id = %s", (bond['id'],))
    session.pop('_fc_shown_all', None)
    session.pop('_fc_shown', None)
    session.modified = True

    return _build_render_payload(bond, _bond_number(bond['id']), get_mars_sol_number(), viewer_user_id=user_id), None


def build_admin_preview_render_data():
    """Admin preview of bond #3 — loads data without completing the bond.
    Returns (payload_dict_or_None, error_message_or_None)."""
    from utilities.mars_environment_utils import get_mars_sol_number

    with db_cursor() as cur:
        cur.execute("SELECT * FROM pilgrim.aria_bonds WHERE id = 3")
        bond = cur.fetchone()
    if not bond:
        return None, "No bond #3 found"
    return _build_render_payload(bond, _bond_number(bond['id']), get_mars_sol_number()), None


def complete_bond_from_cinematic(user_id, bond_id, flask_session):
    """Complete an ARIA bond after the First Contact cinematic.
    Marks first_contact_shown for the viewer and invokes the bond-complete flow.
    """
    from utilities.aria.bonds import _complete_bond

    if not bond_id:
        return {'success': False, 'error': 'Missing bond_id'}

    with db_cursor(commit=True) as cur:
        cur.execute("SELECT user_id_1, user_id_2 FROM pilgrim.aria_bonds WHERE id = %s", (bond_id,))
        bond = cur.fetchone()
        if not bond:
            return {'success': False, 'error': 'Bond not found'}
        if user_id not in (bond['user_id_1'], bond['user_id_2']):
            return {'success': False, 'error': 'Unauthorized'}

        field = 'first_contact_shown_user_1' if user_id == bond['user_id_1'] else 'first_contact_shown_user_2'
        cur.execute(f"UPDATE pilgrim.aria_bonds SET {field} = TRUE WHERE id = %s", (bond_id,))

    result = _complete_bond(bond_id)
    flask_session['_fc_shown'] = True
    flask_session.modified = True
    return result


def build_replay_render_data(user_id):
    """Prepare render data for replay of an existing bond, or 'home' to redirect."""
    from utilities.mars_environment_utils import get_mars_sol_number

    with db_cursor() as cur:
        cur.execute("""
            SELECT * FROM pilgrim.aria_bonds
            WHERE (user_id_1 = %s OR user_id_2 = %s)
            ORDER BY created_at DESC LIMIT 1
        """, (user_id, user_id))
        bond = cur.fetchone()
    if not bond:
        return None, 'home'

    sol = get_mars_sol_number(bond.get('bonded_at') or bond['created_at'])
    return _build_render_payload(bond, _bond_number(bond['id']), sol, replay=True, viewer_user_id=user_id), None
