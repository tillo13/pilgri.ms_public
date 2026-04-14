"""Admin speed test — times server-side page data functions and saves results to DB."""

import time
import json

from utilities.postgres.core import db_cursor, get_pool_health

THRESHOLD_SECONDS = 3.0


def execute_speed_test(test_user_id, auth):
    """Run the full page-data speed test suite and persist results.

    Returns (pages, all_ok) where pages is the sorted list of {page, function, time_s, status}
    and all_ok is True if every non-pool page ran under THRESHOLD_SECONDS with no errors and
    no pool fallbacks occurred.
    """
    from utilities.page_data_utils import (
        get_dashboard_page_data, get_command_page_data,
        get_colony_page_data, get_depot_page_data,
    )
    from utilities.expeditions.page_data import get_expeditions_page_data
    from utilities.tech_utils import get_research_page_data
    from utilities.admin_utils import get_admin_dashboard_data

    tests = [
        ('Home /', 'get_dashboard_page_data', lambda: get_dashboard_page_data(test_user_id, auth)),
        ('Crew /crew', 'get_command_page_data', lambda: get_command_page_data(test_user_id)),
        ('Colony /colony', 'get_colony_page_data', lambda: get_colony_page_data(test_user_id, auth)),
        ('Depot /depot', 'get_depot_page_data', lambda: get_depot_page_data(test_user_id, auth)),
        ('Expeditions', 'get_expeditions_page_data', lambda: get_expeditions_page_data(test_user_id)),
        ('Research', 'get_research_page_data', lambda: get_research_page_data(test_user_id)),
        ('Admin /admin', 'get_admin_dashboard_data', lambda: get_admin_dashboard_data(test_user_id)),
    ]

    pages = []
    for label, func_name, fn in tests:
        start = time.time()
        try:
            fn()
            status = 'ok'
        except Exception as e:
            status = str(e)[:100]
        pages.append({'page': label, 'function': func_name,
                      'time_s': round(time.time() - start, 3), 'status': status})

    pool_snap = get_pool_health()
    pages.append({
        'page': 'DB Pool', 'function': 'pool_health', 'time_s': 0,
        'status': (f"{pool_snap['status']} ({pool_snap.get('used', 0)}/{pool_snap['maxconn']}, "
                   f"{pool_snap['fallbacks']} fallbacks)")
    })
    pages.sort(key=lambda x: x['time_s'], reverse=True)

    slowest = next((p for p in pages if p['function'] != 'pool_health'), pages[0]) if pages else None
    all_ok = all(r['status'] == 'ok' and r['time_s'] < THRESHOLD_SECONDS
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
    return pages, all_ok
