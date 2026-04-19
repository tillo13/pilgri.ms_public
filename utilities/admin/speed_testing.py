"""Admin speed test — times server-side page data functions + counts DB cursors per page."""

import time
import json

from utilities.postgres.core import db_cursor, get_pool_health, reset_db_counter, get_db_counter, DB_CALL_WARN_THRESHOLD

THRESHOLD_SECONDS = 3.0
DB_CALLS_MAX = DB_CALL_WARN_THRESHOLD  # Per-page cursor-open budget; over = N+1 smell.


class _StubAuth:
    """Minimal auth stub so the speed test can run outside a live Flask request
    (e.g. from a cron or CLI). Real auth uses Flask session; we just need an
    object that exposes get_current_user()/is_authenticated() returning the
    tested user's basic record."""
    def __init__(self, user_id):
        self._user = {'user_id': user_id, 'google_id': f'speedtest-{user_id}', 'email': ''}
        try:
            with db_cursor() as cur:
                cur.execute("SELECT google_id, email FROM users WHERE user_id = %s", (user_id,))
                row = cur.fetchone()
                if row:
                    self._user['google_id'] = row[0] or self._user['google_id']
                    self._user['email'] = row[1] or ''
        except Exception:
            pass
    def get_current_user(self): return self._user
    def is_authenticated(self): return True


def execute_speed_test(test_user_id, auth):
    """Run the full page-data speed test suite and persist results.

    Each page gets timed AND its db_cursor() open count recorded. A page fails if it
    runs slow OR issues more than DB_CALLS_MAX cursors (forces N+1 fixes before deploy).
    """
    from utilities.page_data_utils import (
        get_dashboard_page_data, get_command_page_data,
        get_colony_page_data, get_depot_page_data,
    )
    from utilities.expeditions.page_data import get_expeditions_page_data
    from utilities.tech_utils import get_research_page_data
    from utilities.admin_utils import get_admin_dashboard_data
    from utilities.signal_utils import get_signal_page_render_data

    if auth is None:
        auth = _StubAuth(test_user_id)

    # Some page_data helpers read flask.session/g; when invoked from a CLI (no
    # active request), push a test request context so those reads don't explode.
    ctx = None
    try:
        from flask import current_app, has_request_context, session, g
        if not has_request_context():
            try:
                app = current_app._get_current_object()
            except RuntimeError:
                from app import app as _app  # noqa: WPS433 — only on CLI path
                app = _app
            ctx = app.test_request_context('/')
            ctx.push()
            session['user'] = auth.get_current_user()
            session['user_id'] = test_user_id
            g.user_id = test_user_id
    except Exception:
        ctx = None

    tests = [
        ('Home /', 'get_dashboard_page_data', lambda: get_dashboard_page_data(test_user_id, auth)),
        ('Crew /crew', 'get_command_page_data', lambda: get_command_page_data(test_user_id)),
        ('Colony /colony', 'get_colony_page_data', lambda: get_colony_page_data(test_user_id, auth)),
        ('Depot /depot', 'get_depot_page_data', lambda: get_depot_page_data(test_user_id, auth)),
        ('Expeditions', 'get_expeditions_page_data', lambda: get_expeditions_page_data(test_user_id)),
        ('Research', 'get_research_page_data', lambda: get_research_page_data(test_user_id)),
        ('Signal /signal', 'get_signal_page_render_data', lambda: get_signal_page_render_data(test_user_id)),
        ('Admin /admin', 'get_admin_dashboard_data', lambda: get_admin_dashboard_data(test_user_id)),
    ]

    pages = []
    for label, func_name, fn in tests:
        reset_db_counter()
        start = time.time()
        try:
            fn()
            status = 'ok'
        except Exception as e:
            status = str(e)[:100]
        elapsed = round(time.time() - start, 3)
        db_calls = get_db_counter()
        # Treat over-budget cursor count as a failure even if the page happens to be fast right now.
        if status == 'ok' and db_calls > DB_CALLS_MAX:
            status = f'db:{db_calls}>{DB_CALLS_MAX}'
        pages.append({'page': label, 'function': func_name,
                      'time_s': elapsed, 'db_calls': db_calls, 'status': status})

    pool_snap = get_pool_health()
    pages.append({
        'page': 'DB Pool', 'function': 'pool_health', 'time_s': 0, 'db_calls': 0,
        'status': (f"{pool_snap['status']} ({pool_snap.get('used', 0)}/{pool_snap['maxconn']}, "
                   f"{pool_snap['fallbacks']} fallbacks)")
    })
    pages.sort(key=lambda x: x['time_s'], reverse=True)

    slowest = next((p for p in pages if p['function'] != 'pool_health'), pages[0]) if pages else None
    all_ok = all(r['status'] == 'ok' and r['time_s'] < THRESHOLD_SECONDS
                 and r.get('db_calls', 0) <= DB_CALLS_MAX
                 for r in pages if r['function'] != 'pool_health')
    if pool_snap['fallbacks'] > 0:
        all_ok = False

    with db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO speed_test_runs (tested_by, results, slowest_page, slowest_time, all_ok) "
            "VALUES (%s, %s, %s, %s, %s)",
            (test_user_id, json.dumps(pages),
             slowest['page'] if slowest else None,
             slowest['time_s'] if slowest else 0, all_ok)
        )
    if ctx is not None:
        try:
            ctx.pop()
        except Exception:
            pass
    return pages, all_ok
