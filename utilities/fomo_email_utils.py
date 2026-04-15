"""Back-compat shim — real code lives in utilities/email/fomo.py.

Round 8 (2026-04-15): all email code consolidated under utilities/email/.
This file stays behind as an explicit re-export so existing callers keep
working. New code should import from utilities.email.fomo directly.
"""
from utilities.email.fomo import (
    send_welcome_back_email,
    generate_fomo_email_data,
    send_fomo_email_to_user,
    get_user_video_data,
    get_user_by_id,
    get_user_by_email,
    get_all_users,
    calculate_days_away,
    generate_action_links,
    get_fomo_greeting,
    get_fomo_closing,
    EMAIL_ASSETS,
    FOMO_GREETING_PHRASES,
    FOMO_CLOSING_PHRASES,
)

__all__ = [
    'send_welcome_back_email',
    'generate_fomo_email_data',
    'send_fomo_email_to_user',
    'get_user_video_data',
    'get_user_by_id',
    'get_user_by_email',
    'get_all_users',
    'calculate_days_away',
    'generate_action_links',
    'get_fomo_greeting',
    'get_fomo_closing',
    'EMAIL_ASSETS',
    'FOMO_GREETING_PHRASES',
    'FOMO_CLOSING_PHRASES',
]
