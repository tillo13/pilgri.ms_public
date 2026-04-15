"""ARIA conversation persistence — save/retrieve/summarize/clear chat history.

Extracted from utilities/aria_utils.py (Pass B of the ARIA split).
"""

import logging
from typing import Dict, List

logger = logging.getLogger(__name__)

def get_history_payload(user_id, authenticated: bool) -> dict:
    """Build the ARIA history response payload for the /api/aria/history route.

    Returns the last 20 messages if the user is authenticated, otherwise an
    empty-history unauthenticated payload.
    """
    if not authenticated or not user_id:
        return {'success': True, 'history': [], 'authenticated': False}
    return {
        'success': True,
        'history': get_aria_conversation_history(user_id, limit=20),
        'authenticated': True,
    }


def save_aria_message(user_id: int, role: str, content: str) -> bool:
    """
    Save a single ARIA conversation message to the database.

    Args:
        user_id: The user's ID
        role: Either 'user' or 'assistant' (ARIA)
        content: The message content

    Returns:
        True if saved successfully, False otherwise
    """
    from utilities.postgres.core import db_cursor

    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO pilgrim.aria_conversations (user_id, role, content)
                VALUES (%s, %s, %s)
            """, (user_id, role, content))
        return True
    except Exception as e:
        logger.error(f"Failed to save ARIA message for user {user_id}: {e}")
        return False


def get_aria_conversation_history(user_id: int, limit: int = 20) -> List[Dict[str, str]]:
    """
    Retrieve recent ARIA conversation history for a user.

    Args:
        user_id: The user's ID
        limit: Maximum number of messages to retrieve (default 20 = 10 exchanges)

    Returns:
        List of message dicts with 'role' and 'content' keys, oldest first
    """
    from utilities.postgres.core import db_cursor

    try:
        with db_cursor() as cur:
            # Get most recent messages, then reverse to get chronological order
            cur.execute("""
                SELECT role, content
                FROM pilgrim.aria_conversations
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT %s
            """, (user_id, limit))

            rows = cur.fetchall()

            # Reverse to get chronological order (oldest first)
            messages = [{'role': row['role'], 'content': row['content']} for row in reversed(rows)]
            return messages

    except Exception as e:
        logger.error(f"Failed to get ARIA history for user {user_id}: {e}")
        return []


def get_aria_memory_summary(user_id: int) -> str:
    """
    Generate a brief summary of past conversations for ARIA's context.

    This provides ARIA with awareness of what the captain has asked before,
    without including the full conversation history.

    Args:
        user_id: The user's ID

    Returns:
        A summary string to include in ARIA's system prompt
    """
    from utilities.postgres.core import db_cursor

    try:
        with db_cursor() as cur:
            # Get conversation stats
            cur.execute("""
                SELECT
                    COUNT(*) as total_messages,
                    COUNT(DISTINCT DATE(created_at)) as days_chatted,
                    MIN(created_at) as first_chat,
                    MAX(created_at) as last_chat
                FROM pilgrim.aria_conversations
                WHERE user_id = %s
            """, (user_id,))

            stats = cur.fetchone()

            if not stats or stats['total_messages'] == 0:
                return ""

            # Get the last few user messages to understand recent topics
            cur.execute("""
                SELECT content
                FROM pilgrim.aria_conversations
                WHERE user_id = %s AND role = 'user'
                ORDER BY created_at DESC
                LIMIT 5
            """, (user_id,))

            recent_questions = cur.fetchall()

            # Build memory summary
            summary_parts = []

            total_msgs = stats['total_messages']
            days_chatted = stats['days_chatted']

            if total_msgs > 0:
                summary_parts.append(f"You have spoken with this captain {total_msgs} times over {days_chatted} days.")

            if recent_questions:
                topics = [q['content'][:100] for q in recent_questions[:3]]
                summary_parts.append("Recent topics they asked about:")
                for topic in topics:
                    # Truncate long messages
                    if len(topic) > 80:
                        topic = topic[:77] + "..."
                    summary_parts.append(f"  - \"{topic}\"")

            return "\n".join(summary_parts)

    except Exception as e:
        logger.error(f"Failed to get ARIA memory summary for user {user_id}: {e}")
        return ""


def clear_aria_conversation_history(user_id: int) -> bool:
    """
    Clear all ARIA conversation history for a user (the "forget" option).

    Args:
        user_id: The user's ID

    Returns:
        True if cleared successfully, False otherwise
    """
    from utilities.postgres.core import db_cursor

    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                DELETE FROM pilgrim.aria_conversations
                WHERE user_id = %s
            """, (user_id,))

            deleted_count = cur.rowcount
            logger.info(f"Cleared {deleted_count} ARIA messages for user {user_id}")

        return True
    except Exception as e:
        logger.error(f"Failed to clear ARIA history for user {user_id}: {e}")
        return False


def clear_all_aria_conversations() -> dict:
    """Clear ALL ARIA conversation history for ALL users.

    Returns:
        dict with 'success', 'deleted_count', and optionally 'error'
    """
    from utilities.postgres.core import db_cursor

    try:
        with db_cursor(commit=True) as cur:
            cur.execute("DELETE FROM pilgrim.aria_conversations")
            deleted_count = cur.rowcount
            logger.info(f"Cleared ALL ARIA conversations: {deleted_count} messages deleted")

        return {'success': True, 'deleted_count': deleted_count}
    except Exception as e:
        logger.error(f"Failed to clear all ARIA conversations: {e}")
        return {'success': False, 'error': str(e)}


# =============================================================================
# ARIA v1.3 - COLONY AWARENESS SYSTEM
# =============================================================================
# No DB changes - uses existing tables to give ARIA comprehensive knowledge
# of each captain's colony, relationship tier, and spatial awareness.

