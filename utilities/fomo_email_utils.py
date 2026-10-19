"""Back-compat shim — real code lives in utilities/email/fomo.py and sibling utilities.

Round 8 (2026-04-15): email code consolidated under utilities/email/.
Round 12 (2026-04-15): moved user-lookup helpers → utilities/postgres/users,
video helper → utilities/video_utils, action-link helper inlined.

This file stays behind as an explicit re-export so existing callers keep working.
New code should import from the real homes directly.
"""
from utilities.email.fomo import (
    send_welcome_back_email,
    generate_fomo_email_data,
    send_fomo_email_to_user,
    calculate_days_away,
    get_fomo_greeting,
    get_fomo_closing,
    EMAIL_ASSETS,
    FOMO_GREETING_PHRASES,
    FOMO_CLOSING_PHRASES,
)
from utilities.postgres.users import (
    get_user_by_id,
    get_user_by_email,
    get_all_users,
)
from utilities.video_utils import get_user_video_data


def generate_action_links(user_id: int, secret_key: str) -> dict:
    """Back-compat wrapper. New code: call generate_action_url directly from utilities.email.actions."""
    from utilities.email.actions import generate_action_url
    return {
        'claim_discoveries': generate_action_url(user_id, 'claim_discoveries', secret_key),
        'claim_sepolia': generate_action_url(user_id, 'claim_sepolia', secret_key),
    }


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
