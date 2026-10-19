"""Process-level once-guard for schema-ensure functions.

The shared Cloud SQL db-f1-micro is hit by every kumori app. A function that
runs CREATE TABLE/INDEX IF NOT EXISTS on every call re-fires the DDL (and the
AccessExclusiveLock request that comes with IF NOT EXISTS) on every cache miss
and cold instance start — head-of-line blocking the whole shared instance.

@ensure_once makes the wrapped function run AT MOST ONCE per process. After the
first successful call its result is cached and returned for free. Thread-safe
via a double-checked lock so concurrent cold-boot callers don't all run the DDL.

Enforced by the db-speed-first deploy lint (~/.claude/skills/db-speed-first).
"""
import functools
import threading


def ensure_once(fn):
    lock = threading.Lock()
    state = {"done": False, "result": None}

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if state["done"]:
            return state["result"]
        with lock:
            if state["done"]:
                return state["result"]
            state["result"] = fn(*args, **kwargs)
            state["done"] = True
            return state["result"]

    return wrapper
