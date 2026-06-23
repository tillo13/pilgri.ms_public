"""ARIA chat — sync `get_aria_response` and streaming `stream_aria_response`.

Extracted from utilities/aria_utils.py (Pass B of the ARIA split).
"""

import logging
import os
from typing import Dict, Any, Optional, List

from utilities.claude_utils import create_client, CLAUDE_MODELS, log_api_usage
from utilities.aria.prompts import get_aria_system_prompt

logger = logging.getLogger(__name__)

def get_aria_response(
    user_message: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    user_context: Optional[Dict[str, Any]] = None,
    api_key: Optional[str] = None,
    user_id: Optional[int] = None,
    snapshot: Optional[Dict[str, Any]] = None
) -> str:
    """
    Get a response from ARIA for a user message.

    Args:
        user_message: The captain's message to ARIA
        conversation_history: Optional list of previous messages
            Each message: {'role': 'user'|'assistant', 'content': str}
        user_context: Optional dict with user's current state
        api_key: Optional Anthropic API key (uses env var or secrets if not provided)
        user_id: Optional user ID for loading conversation memory from database
        snapshot: Optional v1.3 colony snapshot for comprehensive knowledge

    Returns:
        ARIA's response string
    """
    try:
        # Build system prompt with user context and memory (v1.3: includes snapshot)
        system_prompt = get_aria_system_prompt(user_context, user_id=user_id, snapshot=snapshot)

        # Build messages list
        messages = []

        # Add conversation history if provided (limit to last 10 exchanges)
        if conversation_history:
            for msg in conversation_history[-20:]:  # Last 20 messages (10 exchanges)
                if msg.get('role') in ['user', 'assistant'] and msg.get('content'):
                    messages.append({
                        'role': msg['role'],
                        'content': msg['content']
                    })

        # Add current message
        messages.append({
            'role': 'user',
            'content': user_message
        })

        # Route over the FREE kumori LLM catalog (no Anthropic key needed).
        # Multi-turn variant keeps conversation history. pilgrimbot + the rarely
        # used streaming path stay on Claude; this sync path is the cost driver.
        from utilities.kumori_utils import kumori_llm_chat_messages
        response, backend, _attempts, _dbg = kumori_llm_chat_messages(
            system=system_prompt,
            messages=messages,
            max_tokens=500,    # Enough room for complete responses
            temperature=0.8,   # Some personality variation
        )
        if not response:
            logger.error("ARIA free-LLM call returned empty across all backends")
            return "Dust storm interference. Please try again, Captain."
        logger.debug(f"ARIA replied via free backend: {backend}")
        return response

    except Exception as e:
        logger.error(f"Error getting ARIA response: {e}")
        return "Dust storm interference. Please try again, Captain."


def stream_aria_response(
    user_message: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    user_context: Optional[Dict[str, Any]] = None,
    api_key: Optional[str] = None,
    user_id: Optional[int] = None,
    snapshot: Optional[Dict[str, Any]] = None
):
    """
    Stream a response from ARIA for a user message (SSE format).

    Args:
        user_message: The captain's message to ARIA
        conversation_history: Optional list of previous messages
        user_context: Optional dict with user's current state
        api_key: Optional Anthropic API key
        user_id: Optional user ID for loading conversation memory from database
        snapshot: Optional v1.3 colony snapshot for comprehensive knowledge

    Yields:
        SSE-formatted strings: "data: {...}\n\n"
    """
    import json

    try:
        # Get API key
        if not api_key:
            api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            try:
                from utilities.google_auth_utils import get_secret
                api_key = get_secret("KUMORI_ANTHROPIC_API_KEY", project_id="kumori-404602")
            except Exception:
                pass

        if not api_key:
            logger.error("No Anthropic API key available for ARIA")
            yield f"data: {json.dumps({'type': 'error', 'error': 'Connection issues'})}\n\n"
            return

        # Build system prompt with user context and memory (v1.3: includes snapshot)
        system_prompt = get_aria_system_prompt(user_context, user_id=user_id, snapshot=snapshot)

        # Build messages list
        messages = []

        # Add conversation history if provided (limit to last 10 exchanges)
        if conversation_history:
            for msg in conversation_history[-20:]:  # Last 20 messages (10 exchanges)
                if msg.get('role') in ['user', 'assistant'] and msg.get('content'):
                    messages.append({
                        'role': msg['role'],
                        'content': msg['content']
                    })

        # Add current message
        messages.append({
            'role': 'user',
            'content': user_message
        })

        # Use Haiku 4.5 for fast responses that follow instructions well
        client = create_client(
            api_key=api_key,
            model=CLAUDE_MODELS.get("haiku-4.5", "claude-haiku-4-5-20251001")
        )

        # Signal start
        yield f"data: {json.dumps({'type': 'start'})}\n\n"

        # Stream the response
        for event in client.stream_chat(
            messages=messages,
            system=system_prompt,
            max_tokens=500,  # Enough room for complete responses
            temperature=0.8,
            user_id=str(user_id) if user_id else "system:galactica_aria",
            feature="aria_stream",
        ):
            if event.get('type') == 'delta' and event.get('text'):
                yield f"data: {json.dumps({'type': 'delta', 'text': event['text']})}\n\n"
            elif event.get('type') == 'stop':
                yield f"data: {json.dumps({'type': 'stop'})}\n\n"
                break
            elif event.get('type') == 'error':
                yield f"data: {json.dumps({'type': 'error', 'error': event.get('error', 'Unknown error')})}\n\n"
                break

    except Exception as e:
        logger.error(f"Error streaming ARIA response: {e}")
        yield f"data: {json.dumps({'type': 'error', 'error': 'Dust storm interference'})}\n\n"


# =============================================================================
# ARIA'S GREETING MESSAGES
# =============================================================================

