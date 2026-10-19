"""Conversation summary generator for shared-chat onboarding.

Extracted from utilities/claude_utils.py (Round 5 refactor).
"""

import logging
from typing import List, Dict

from utilities.anthropic.convenience import create_client

logger = logging.getLogger("claude_utils")


def generate_conversation_summary(messages: List[Dict], api_key: str = None) -> str:
    """Generate a summary of the conversation using Claude"""
    try:
        if not messages or len(messages) < 2:
            return "This conversation is just getting started."

        recent_messages = messages[-20:] if len(messages) > 20 else messages

        conversation_text = "\n".join([
            f"{msg['role']}: {msg['content'][:500]}"
            for msg in recent_messages
        ])

        summary_prompt = f"""Please provide a brief, helpful summary of this conversation to give context to someone joining it:

{conversation_text}

Provide a 2-3 sentence summary that captures:
1. The main topic or question being discussed
2. Key points or conclusions reached
3. The current state of the conversation

Keep it concise and welcoming for new participants."""

        client = create_client(api_key)
        summary = client.generate_text(
            summary_prompt, max_tokens=200, temperature=0.7,
            user_id="system:galactica_conversation_summary",
            feature="conversation_summary",
        )

        return summary

    except Exception as e:
        logger.error(f"Error generating conversation summary: {e}")
        return "This is an ongoing conversation. Feel free to read through and join in!"
