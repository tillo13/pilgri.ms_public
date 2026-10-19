"""Kumori collaborative shared-chat response generator.

Extracted from utilities/claude_utils.py (Round 5 refactor).
"""

import logging
from typing import List, Dict

from utilities.anthropic.convenience import create_client

logger = logging.getLogger("claude_utils")


def get_claude_response_for_shared_chat(recent_messages: List[Dict], new_message: str,
                                       participant_id: str, api_key: str = None) -> str:
    """Get Claude response for shared chat with collaborative context"""
    try:
        system_prompt = f"""You are Kumori, participating in a collaborative shared conversation. Multiple people may be contributing to this discussion. The current message is from {participant_id}.

Be welcoming to all participants, acknowledge when new people join the conversation, and help facilitate meaningful dialogue between everyone involved. Reference previous points made by different participants when relevant."""

        messages = []
        for msg in recent_messages[-15:]:
            role = msg['role']
            content = msg['content']
            participant = msg.get('participant_identifier', 'user')

            if role == 'user':
                content = f"[{participant}]: {content}"

            messages.append({'role': role, 'content': content})

        messages.append({'role': 'user', 'content': f"[{participant_id}]: {new_message}"})

        client = create_client(api_key)
        response = client.chat(
            messages, system=system_prompt, max_tokens=1024, temperature=1.0,
            user_id=f"participant:{participant_id}" if participant_id else "system:galactica_shared_chat",
            feature="shared_chat_response",
        )

        return response

    except Exception as e:
        logger.error(f"Error getting Claude response: {e}")
        return "I'm having trouble responding right now. Please try again."
