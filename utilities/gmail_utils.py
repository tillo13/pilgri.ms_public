"""Back-compat shim — real code lives in utilities/email/transport.py.

Round 8 (2026-04-15): all email code consolidated under utilities/email/.
This file stays behind as an explicit re-export so existing callers keep
working. New code should import from utilities.email.transport directly.
"""
from utilities.email.transport import (
    send_email,
    send_simple_email,
    send_expedition_complete_email,
    send_daily_digest_email,
    SENDER_EMAIL,
    _get_gmail_service,
)

__all__ = [
    'send_email',
    'send_simple_email',
    'send_expedition_complete_email',
    'send_daily_digest_email',
    'send_welcome_back_email',
    'SENDER_EMAIL',
    '_get_gmail_service',
]


def send_welcome_back_email(*args, **kwargs):
    """Back-compat wrapper — delegates to utilities.email.fomo."""
    from utilities.email.fomo import send_welcome_back_email as _send_fomo
    return _send_fomo(*args, **kwargs)
