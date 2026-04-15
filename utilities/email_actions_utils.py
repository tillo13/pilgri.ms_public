"""Back-compat shim — real code lives in utilities/email/actions.py.

Round 8 (2026-04-15): all email code consolidated under utilities/email/.
This file stays behind as an explicit re-export so existing callers keep
working. New code should import from utilities.email.actions directly.
"""
from utilities.email.actions import (
    generate_action_token,
    validate_action_token,
    generate_action_url,
    execute_claim_sepolia,
    execute_claim_discoveries,
    execute_collect_idle,
    execute_action,
    ACTION_HANDLERS,
    mark_token_used,
    is_token_used,
    handle_email_action_token,
    generate_email_action_buttons,
    TOKEN_EXPIRY_HOURS,
    DEFAULT_EXPIRY_HOURS,
)

__all__ = [
    'generate_action_token',
    'validate_action_token',
    'generate_action_url',
    'execute_claim_sepolia',
    'execute_claim_discoveries',
    'execute_collect_idle',
    'execute_action',
    'ACTION_HANDLERS',
    'mark_token_used',
    'is_token_used',
    'handle_email_action_token',
    'generate_email_action_buttons',
    'TOKEN_EXPIRY_HOURS',
    'DEFAULT_EXPIRY_HOURS',
]
