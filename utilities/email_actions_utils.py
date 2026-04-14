"""
Email Action System - Let players interact with the game via email links

CONCEPT:
- Generate secure, time-limited action tokens
- Embed in email as clickable links
- Player clicks link, action executes, redirects to game
- No login required for simple actions

SECURITY:
- Tokens are signed with HMAC (using Flask secret key)
- Include user_id, action, expiry in payload
- Tokens expire after 24-48 hours
- One-time use (marked as used after execution)
- WHITELIST: Currently only enabled for test accounts

SUPPORTED ACTIONS:
1. claim_sepolia - Harvest pending Sepolia from infrastructure
2. claim_discoveries - Claim all unclaimed expedition discoveries
3. quick_expedition - Start a pre-configured short expedition
4. collect_idle - Claim idle discoveries

URL FORMAT:
https://pilgri.ms/action/{token}

TOKEN STRUCTURE (base64 encoded, HMAC signed):
{
    "user_id": 123,
    "action": "claim_sepolia",
    "created_at": "2025-01-04T12:00:00Z",
    "expires_at": "2025-01-05T12:00:00Z",
    "nonce": "abc123"  # prevents replay
}

EMAIL INTEGRATION:
Emails include buttons like:
- [Claim 847 Sepolia Now] -> /action/{token}
- [Claim 3 Discoveries] -> /action/{token}

FLOW:
1. Notification email generated with action tokens
2. User clicks link in email
3. /action/{token} endpoint:
   a. Validates token (signature, expiry, not used)
   b. Executes action
   c. Marks token as used
   d. Redirects to relevant game page with success message
4. User lands in game, already logged in via session or sees results
"""

import hmac
import hashlib
import base64
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from functools import wraps

logger = logging.getLogger(__name__)

# Token expiry durations
TOKEN_EXPIRY_HOURS = {
    'claim_sepolia': 48,
    'claim_discoveries': 48,
    'quick_expedition': 24,
    'collect_idle': 72,
}

# Default expiry
DEFAULT_EXPIRY_HOURS = 48


def generate_action_token(user_id: int, action: str, secret_key: str, extra_data: Dict = None) -> str:
    """
    Generate a secure, time-limited action token.

    Args:
        user_id: The user this action is for
        action: The action type (claim_sepolia, claim_discoveries, etc.)
        secret_key: Flask app secret key for signing
        extra_data: Optional additional data to include

    Returns:
        URL-safe base64 encoded token
    """
    import secrets

    expiry_hours = TOKEN_EXPIRY_HOURS.get(action, DEFAULT_EXPIRY_HOURS)

    payload = {
        'user_id': user_id,
        'action': action,
        'created_at': datetime.utcnow().isoformat(),
        'expires_at': (datetime.utcnow() + timedelta(hours=expiry_hours)).isoformat(),
        'nonce': secrets.token_hex(8),
    }

    if extra_data:
        payload['data'] = extra_data

    # Encode payload
    payload_json = json.dumps(payload, sort_keys=True)
    payload_bytes = payload_json.encode('utf-8')
    payload_b64 = base64.urlsafe_b64encode(payload_bytes).decode('utf-8')

    # Sign with HMAC
    signature = hmac.new(
        secret_key.encode('utf-8'),
        payload_bytes,
        hashlib.sha256
    ).hexdigest()

    # Combine: payload.signature
    token = f"{payload_b64}.{signature}"

    return token


def validate_action_token(token: str, secret_key: str) -> Tuple[bool, Optional[Dict], Optional[str]]:
    """
    Validate an action token.

    Returns:
        (is_valid, payload, error_message)
    """
    try:
        # Split token
        parts = token.split('.')
        if len(parts) != 2:
            return False, None, "Invalid token format"

        payload_b64, provided_signature = parts

        # Decode payload
        payload_bytes = base64.urlsafe_b64decode(payload_b64.encode('utf-8'))
        payload = json.loads(payload_bytes.decode('utf-8'))

        # Verify signature
        expected_signature = hmac.new(
            secret_key.encode('utf-8'),
            payload_bytes,
            hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(provided_signature, expected_signature):
            return False, None, "Invalid signature"

        # Check expiry
        expires_at = datetime.fromisoformat(payload['expires_at'])
        if datetime.utcnow() > expires_at:
            return False, None, "Token expired"

        return True, payload, None

    except Exception as e:
        logger.error(f"Token validation error: {e}")
        return False, None, f"Validation error: {str(e)}"


def generate_action_url(user_id: int, action: str, secret_key: str, base_url: str = "https://pilgri.ms") -> str:
    """Generate a complete action URL for email embedding."""
    token = generate_action_token(user_id, action, secret_key)
    return f"{base_url}/action/{token}"


# ============================================================================
# ACTION HANDLERS - Execute the actual game actions
# ============================================================================

def execute_claim_sepolia(user_id: int) -> Dict:
    """
    Claim all pending Sepolia from infrastructure.

    This returns IMMEDIATELY with a success message and kicks off
    the blockchain transaction in a background thread. Users don't
    need to wait for blockchain confirmation.
    """
    import threading

    try:
        from utilities.infrastructure_utils import calculate_accumulated_income, claim_accumulated_income

        # Get pending amount (fast - no blockchain)
        calc = calculate_accumulated_income(user_id)
        pending_amount = calc.get('total_accumulated', 0)

        if not calc.get('can_claim') or pending_amount < 0.1:
            return {
                'success': True,
                'action': 'claim_sepolia',
                'amount': 0,
                'message': "No Sepolia to harvest right now (minimum: 0.1 Shards).",
                'processing': False
            }

        # Get user's name for personalized message
        from utilities.postgres.users import get_user_email_info
        user_info = get_user_email_info(user_id)
        user_name = user_info.get('given_name') or user_info.get('name') if user_info else None
        if not user_name:
            user_name = "Commander"

        # Start blockchain transaction in background thread
        def process_claim():
            try:
                result = claim_accumulated_income(user_id)
                if result.get('success'):
                    logger.info(f"✅ Background claim completed for user {user_id}: {result.get('amount_claimed', 0):.1f} Sepolia")
                else:
                    logger.error(f"❌ Background claim failed for user {user_id}: {result.get('error')}")
            except Exception as e:
                logger.error(f"❌ Background claim exception for user {user_id}: {e}")

        thread = threading.Thread(target=process_claim)
        thread.start()

        # Return immediately with success message
        return {
            'success': True,
            'action': 'claim_sepolia',
            'amount': pending_amount,
            'user_name': user_name,
            'message': f"Got it, {user_name}! Your base is harvesting {pending_amount:.1f} Sepolia shards now.",
            'processing': True
        }

    except Exception as e:
        logger.error(f"Failed to initiate Sepolia claim for user {user_id}: {e}")
        return {'success': False, 'error': str(e)}


def execute_claim_discoveries(user_id: int) -> Dict:
    """
    Claim all unclaimed expedition discoveries.
    Returns result dict with preview of top discoveries.
    """
    try:
        from utilities.postgres.expeditions import claim_all_pending_discoveries, get_recent_discoveries

        # Get preview of discoveries BEFORE claiming (top 3 for display)
        preview_discoveries = get_recent_discoveries(user_id, limit=3)

        result = claim_all_pending_discoveries(user_id)
        count = result.get('claimed_count', 0)
        value = result.get('total_value', 0)

        if count > 0:
            return {
                'success': True,
                'action': 'claim_discoveries',
                'count': count,
                'total_value': value,
                'message': f"Claimed {count} discoveries worth {value:.1f} Sepolia!",
                'discoveries': preview_discoveries
            }
        else:
            return {
                'success': True,
                'action': 'claim_discoveries',
                'count': 0,
                'total_value': 0,
                'message': "No unclaimed discoveries right now.",
                'discoveries': []
            }
    except Exception as e:
        logger.error(f"Failed to claim discoveries for user {user_id}: {e}")
        return {'success': False, 'error': str(e)}


def execute_collect_idle(user_id: int) -> Dict:
    """
    Collect idle discoveries (placeholder - idle system not fully implemented).
    Returns result dict.
    """
    # For now, just return a placeholder message
    return {
        'success': True,
        'action': 'collect_idle',
        'count': 0,
        'items': [],
        'message': "Idle discovery collection coming soon!"
    }


# Map action names to handlers
ACTION_HANDLERS = {
    'claim_sepolia': execute_claim_sepolia,
    'claim_discoveries': execute_claim_discoveries,
    'collect_idle': execute_collect_idle,
}


def execute_action(action: str, user_id: int, extra_data: Dict = None) -> Dict:
    """
    Execute an action for a user.

    Args:
        action: The action type
        user_id: The user to execute for
        extra_data: Optional additional data from token

    Returns:
        Result dict with success status and message
    """
    handler = ACTION_HANDLERS.get(action)
    if not handler:
        return {'success': False, 'error': f"Unknown action: {action}"}

    return handler(user_id)


# ============================================================================
# USED TOKEN TRACKING - Prevent replay attacks
# ============================================================================

def mark_token_used(token_nonce: str, user_id: int, action: str) -> bool:
    """Mark a token as used in the database."""
    from utilities.postgres.shop import mark_action_token_used
    return mark_action_token_used(token_nonce, user_id, action)


def is_token_used(token_nonce: str) -> bool:
    """Check if a token has already been used."""
    from utilities.postgres.shop import is_action_token_used
    return is_action_token_used(token_nonce)


def handle_email_action_token(token: str, secret_key: str) -> Tuple[Dict, int]:
    """Full email-action flow: validate token, guard replay, execute, mark used.
    Returns (template_context, http_status) — caller just renders the template.
    """
    import logging
    logger = logging.getLogger(__name__)

    from utilities.postgres.shop import ensure_action_tokens_table
    ensure_action_tokens_table()

    valid, payload, error = validate_action_token(token, secret_key)
    if not valid:
        logger.warning(f"❌ Invalid email action token: {error}")
        return {
            'success': False,
            'message': f"Invalid or expired link: {error}",
            'action': None,
        }, 400

    user_id = payload['user_id']
    action = payload['action']
    nonce = payload['nonce']

    if is_token_used(nonce):
        logger.warning(f"❌ Email action token already used: {nonce[:8]}...")
        return {
            'success': False,
            'message': "This link has already been used.",
            'action': action,
        }, 400

    logger.info(f"📧 Executing email action: {action} for user {user_id}")
    result = execute_action(action, user_id)
    mark_token_used(nonce, user_id, action)

    if result.get('success'):
        logger.info(f"✅ Email action success: {result.get('message')}")
        return {
            'success': True,
            'message': result.get('message', 'Action completed!'),
            'action': action,
            'result': result,
        }, 200

    logger.error(f"❌ Email action failed: {result.get('error')}")
    return {
        'success': False,
        'message': f"Action failed: {result.get('error', 'Unknown error')}",
        'action': action,
    }, 500


# ============================================================================
# EMAIL HELPERS - Generate action buttons for emails
# ============================================================================

def generate_email_action_buttons(user_id: int, secret_key: str, pending_data: Dict) -> str:
    """
    Generate HTML/text action buttons for email based on what's pending.

    Args:
        user_id: The user
        secret_key: For token generation
        pending_data: Dict with pending_sepolia, pending_discoveries, etc.

    Returns:
        Text block with action links
    """
    buttons = []
    base_url = "https://pilgri.ms"

    if pending_data.get('pending_sepolia', 0) > 0:
        url = generate_action_url(user_id, 'claim_sepolia', secret_key, base_url)
        amount = pending_data['pending_sepolia']
        buttons.append(f"[CLAIM {amount:.0f} SEPOLIA] {url}")

    if pending_data.get('pending_discoveries', 0) > 0:
        url = generate_action_url(user_id, 'claim_discoveries', secret_key, base_url)
        count = pending_data['pending_discoveries']
        buttons.append(f"[CLAIM {count} DISCOVERIES] {url}")

    if pending_data.get('idle_discoveries', 0) > 0:
        url = generate_action_url(user_id, 'collect_idle', secret_key, base_url)
        count = pending_data['idle_discoveries']
        buttons.append(f"[COLLECT {count} IDLE FINDS] {url}")

    if not buttons:
        return ""

    return "\n\nQUICK ACTIONS (no login required):\n" + "\n".join(buttons) + "\n"
