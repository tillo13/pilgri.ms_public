"""PilgrimBot chat action detection — parses the user message, runs live ops actions,
and returns context text to prepend to Claude's prompt."""

import re


POOL_TRIGGERS = (
    'pool health', 'pool status', 'db health', 'db pool', 'connection pool',
    'check pool', 'check connections', 'db connections',
)
SPEED_TRIGGERS = (
    'run speed test', 'run the speed', 'check the speed', 'test the speed',
    'test site speed', 'speed check', 'how fast is the site', 'run a speed',
    'site performance', 'check performance', 'test performance',
)
BUG_CREATE_TRIGGERS = (
    'create a bug', 'log this as a bug', 'file a bug', 'make a bug',
    'log this bug', 'report this bug', 'submit this bug', 'open a bug',
    'file this as a bug', 'turn this into a bug', 'make this a bug',
)
RELATED_TRIGGERS = (
    'relate to any', 'similar bug', 'related bug', 'any other bug',
    'duplicate bug', 'seen this before', 'known issue', 'existing bug',
    'already reported', 'been reported', 'any bugs like',
)
SYNC_TRIGGERS = ('sync balance', 'sync blockchain', 'check balances', 'refresh balances')

BUG_STATUS_MAP = {'new': 'New', 'todo': 'Todo', 'in review': 'In Review',
                  'review': 'In Review', 'dev': 'Todo', 'done': 'Done'}

SEARCH_STOPWORDS = {
    'this', 'that', 'have', 'been', 'does', 'what', 'about',
    'there', 'where', 'which', 'with', 'from', 'your', 'they',
    'just', 'like', 'know', 'think', 'seem', 'also', 'some',
    'relate', 'related', 'similar', 'bugs', 'other', 'existing',
}


def _pool_health_action():
    from utilities.postgres.core import get_pool_health, get_db_connection_stats
    try:
        ph = get_pool_health()
        ds = get_db_connection_stats()
        text = "\n--- DB POOL HEALTH (live) ---\n"
        text += (f"Pool: {ph['status'].upper()} — {ph.get('used', 0)}/{ph['maxconn']} used, "
                 f"{ph.get('available', 0)} available\n")
        text += (f"Fallbacks since boot: {ph['fallbacks']} "
                 f"{'(NONE — healthy!)' if ph['fallbacks'] == 0 else '(pool was exhausted this many times)'}\n")
        if ds and not ds.get('error'):
            text += f"Global DB: {ds['total_used']}/{ds['max_connections']} connections ({ds['pct_used']}% used)\n"
            text += f"States: {ds['by_state']}\n"
        return text
    except Exception as e:
        return f"\n--- Pool health check failed: {e} ---\n"


def _speed_test_action(real_user_id, auth):
    from utilities.admin.speed_testing import execute_speed_test
    try:
        pages, all_ok = execute_speed_test(real_user_id, auth)
        text = "\n--- FRESH SPEED TEST RESULTS (just ran & saved to DB) ---\n"
        text += f"All pages OK: {all_ok}\n"
        for p in pages:
            text += f"  {p['page']}: {p['time_s']}s {'OK' if p['status'] == 'ok' else p['status']}\n"
        return text
    except Exception as e:
        return f"\n--- Speed test failed: {e} ---\n"


def _bug_status_action(msg_lower):
    m = re.search(
        r'(?:mark|set|move|change|update)\s+(?:bug\s*)?#?(\d+)\s+(?:to|as)\s+(new|todo|in review|review|done|dev)',
        msg_lower,
    )
    pass_to_dev = False
    if not m:
        m = re.search(r'pass\s+(?:bug\s*)?#?(\d+)\s+to\s+dev', msg_lower)
        pass_to_dev = bool(m)
    if not m:
        return ""
    try:
        from utilities.postgres.bugs import get_bug_by_id, update_bug
        action_bug_id = int(m.group(1))
        new_status = 'Todo' if pass_to_dev else BUG_STATUS_MAP.get(m.group(2).strip(), 'Todo')
        bug = get_bug_by_id(action_bug_id)
        if not bug:
            return f"\n--- Bug #{action_bug_id} not found ---\n"
        if new_status == 'Done':
            return f"\n--- Bug #{action_bug_id}: Only Luke (QA) can mark bugs as Done. Status unchanged. ---\n"
        update_bug(action_bug_id, 'PilgrimBot', status=new_status)
        return f"\n--- Bug #{action_bug_id} status changed: {bug['status']} → {new_status} ---\n"
    except Exception as e:
        return f"\n--- Bug update failed: {e} ---\n"


def _create_bug_action(chat_id, real_user_id):
    try:
        from utilities.pilgrimbot_utils import create_bug_from_conversation
        result = create_bug_from_conversation(chat_id, real_user_id)
        if result.get('success'):
            return (f"\n--- BUG CREATED: #{result['bug_id']} — {result['title']} ---\n"
                    f"Link: /admin/bugs?open={result['bug_id']}\n"
                    f"Related bug discovery is running in the background.\n")
        return f"\n--- Bug creation failed: {result.get('error', 'unknown')} ---\n"
    except Exception as e:
        return f"\n--- Bug creation failed: {e} ---\n"


def _related_bugs_action(chat_id, real_user_id):
    try:
        from utilities.pilgrimbot_utils import get_chat_history
        from utilities.postgres.bugs import search_bugs
        history = get_chat_history(real_user_id, chat_id, limit=10)
        recent_text = ' '.join(m['content'][:200] for m in history[-6:])
        words = [w.lower().strip("?.,!()\"'") for w in recent_text.split()
                 if len(w) > 4 and w.lower().strip("?.,!()\"'") not in SEARCH_STOPWORDS]
        unique = list(dict.fromkeys(words))
        all_results = {}
        for keyword in unique[:4]:
            for b in search_bugs(keyword):
                all_results.setdefault(b['id'], b)
        if not all_results:
            return "\n--- No matching bugs found in the tracker ---\n"
        text = f"\n--- BUG SEARCH RESULTS ({len(all_results)} matches) ---\n"
        for b in list(all_results.values())[:10]:
            text += (f"  #{b['id']}: {b['name']} ({b['status']}/{b['priority']}) — "
                     f"{(b.get('description') or '')[:100]}\n")
        return text
    except Exception as e:
        return f"\n--- Bug search failed: {e} ---\n"


def _sync_balances_action():
    from utilities.admin_utils import handle_admin_sync_balances
    try:
        result = handle_admin_sync_balances()
        return ("\n--- BALANCE SYNC COMPLETE ---\n"
                f"Synced: {result.get('synced', '?')} users | Errors: {result.get('errors', 0)}\n")
    except Exception as e:
        return f"\n--- Balance sync failed: {e} ---\n"


def detect_and_execute_actions(message: str, chat_id, real_user_id, auth) -> str:
    """Inspect a chat message for admin action triggers, run them, return aggregated context text."""
    msg_lower = message.lower()
    context = ""
    if any(t in msg_lower for t in POOL_TRIGGERS):
        context += _pool_health_action()
    if any(t in msg_lower for t in SPEED_TRIGGERS):
        context += _speed_test_action(real_user_id, auth)
    context += _bug_status_action(msg_lower)
    if any(t in msg_lower for t in BUG_CREATE_TRIGGERS) and chat_id:
        context += _create_bug_action(chat_id, real_user_id)
    if any(t in msg_lower for t in RELATED_TRIGGERS) and chat_id:
        context += _related_bugs_action(chat_id, real_user_id)
    if any(t in msg_lower for t in SYNC_TRIGGERS):
        context += _sync_balances_action()
    return context
