"""Server-side backstop against runaway client poll loops.

A broken or abusive client must NEVER be able to translate into unbounded DB
load. On 2026-05-29 the Narog recalibration countdown (crew-robot.js) entered a
feedback loop and fetched /api/robot/recalibration_state as fast as the network
allowed, for as long as the tab stayed open. A single captain's stuck tab
saturated the shared db-f1-micro and dragged EVERY page site-wide to 10-17s.

The client bug is fixed at the source, but "trust no single tool ever": this is
the second layer. `throttle_per_user` caps a polled endpoint to at most ONE real
handler execution per `ttl_seconds` per captain. Calls that arrive inside the
window get the last response replayed from memory with ZERO DB work — so even a
client firing 100x/sec costs the database nothing beyond the first hit per
window. Apply it to any cheap GET state endpoint a client polls on a timer.
"""
import time
import threading
from functools import wraps

from flask import g, current_app

# (user_id, view_name) -> (expires_at_monotonic, (body_bytes, status, content_type))
_cache = {}
_lock = threading.Lock()
_PURGE_WHEN_OVER = 2000  # opportunistic cleanup so the dict can't grow forever


def _purge_expired(now):
    """Drop expired entries. Called under _lock when the cache gets large."""
    dead = [k for k, (exp, _) in _cache.items() if exp <= now]
    for k in dead:
        _cache.pop(k, None)


def throttle_per_user(ttl_seconds=2.0):
    """Per-captain, per-view response cache. Inside the TTL the cached response is
    replayed without invoking the wrapped handler (no DB hit). Anonymous requests
    (no g.user_id) are never throttled — they can't be the source of a logged-in
    poll loop and we don't want to cross-contaminate them."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = getattr(g, 'user_id', None)
            if uid is None:
                return fn(*args, **kwargs)
            key = (uid, fn.__name__)
            now = time.monotonic()
            with _lock:
                hit = _cache.get(key)
                if hit and hit[0] > now:
                    body, status, ctype = hit[1]
                    return current_app.response_class(body, status=status, content_type=ctype)
            resp = fn(*args, **kwargs)
            try:
                cached = (resp.get_data(), resp.status_code, resp.content_type)
                with _lock:
                    if len(_cache) > _PURGE_WHEN_OVER:
                        _purge_expired(now)
                    _cache[key] = (now + ttl_seconds, cached)
            except Exception:
                # Non-standard return (tuple, streaming, etc.) — don't cache, just pass through.
                pass
            return resp
        return wrapper
    return deco
