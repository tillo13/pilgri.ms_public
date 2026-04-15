"""
Captain's Log Utilities - Chat with Your Captain

Provides transient conversation with a captain using Claude Haiku,
passing the captain's traits, stats, expeditions, scientist, etc.
as context for each call.
"""

import os
import logging
import requests
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# Cache for blocked words (refreshed periodically)
_blocked_words_cache = None
_blocked_words_cache_time = None


def get_blocked_words() -> List[str]:
    """
    Get blocked words from LDNOOBW repository (Shutterstock's list).
    Caches the result for 1 hour.
    """
    global _blocked_words_cache, _blocked_words_cache_time
    import time

    # Check cache (1 hour TTL)
    if _blocked_words_cache and _blocked_words_cache_time:
        if time.time() - _blocked_words_cache_time < 3600:
            return _blocked_words_cache

    # Get any custom words from environment
    env_words = os.getenv('CUSTOM_BLOCKED_WORDS', '')
    custom_words = [word.strip().lower() for word in env_words.split(',') if word.strip()]

    try:
        # TinyURL redirects to LDNOOBW repository on GitHub
        url = "https://tinyurl.com/35wba3d6"
        response = requests.get(url, timeout=5, allow_redirects=True)
        if response.status_code == 200:
            # Parse the word list (one word per line)
            ldnoobw_words = [word.strip().lower() for word in response.text.split('\n') if word.strip()]
            combined = list(set(custom_words + ldnoobw_words))
            _blocked_words_cache = combined
            _blocked_words_cache_time = time.time()
            logger.info(f"Loaded {len(combined)} blocked words for content filter")
            return combined
    except Exception as e:
        logger.warning(f"Failed to fetch LDNOOBW word list: {e}")

    # Fallback to custom words only
    _blocked_words_cache = custom_words if custom_words else []
    _blocked_words_cache_time = time.time()
    return _blocked_words_cache


def check_content_filter(message: str) -> tuple[bool, Optional[str]]:
    """
    Check if message contains disallowed content.

    Returns:
        (is_allowed, error_message) - If allowed, error_message is None
    """
    try:
        blocked_phrases = get_blocked_words()
        if not blocked_phrases:
            return True, None

        message_lower = message.lower()

        # Check for blocked words (word boundary matching)
        for phrase in blocked_phrases:
            if phrase and phrase in message_lower:
                logger.info(f"[FILTER] BLOCKED message containing blocked content")
                # In-lore response
                return False, "Hey, watch the language! Let's keep it professional - I've got a reputation to maintain as captain!"

        return True, None
    except Exception as e:
        logger.error(f"Content filter error: {e}")
        # Fail open - allow message if filter errors
        return True, None


def get_captain_context(user_id: int) -> Dict[str, Any]:
    """
    Gather all relevant captain context for chat.

    Returns dict with:
    - captain_name, image_url, stats
    - scientist info
    - expedition stats and active expeditions
    - discovery stats
    - recent quotes from the log
    """
    from utilities.postgres.notifications import get_user_fomo_data, get_commander_quotes

    fomo_data = get_user_fomo_data(user_id)
    recent_quotes = get_commander_quotes(user_id, limit=5)

    captain = fomo_data.get('commander') or {}
    scientist = fomo_data.get('scientist') or {}

    return {
        'captain_name': captain.get('name', 'Captain'),
        'captain_image_url': captain.get('image_url'),
        'stats': captain.get('stats', {}),
        'scientist_name': scientist.get('name'),
        'scientist_specialty': scientist.get('specialty'),
        'expedition_stats': fomo_data.get('expedition_stats', {}),
        'discovery_stats': fomo_data.get('discovery_stats', {}),
        'active_expeditions': fomo_data.get('active_expeditions', []),
        'suggested_destinations': fomo_data.get('suggested_destinations', []),
        'research_points': fomo_data.get('research_points', 0),
        'total_scientific_value': fomo_data.get('total_scientific_value', 0),
        'recent_quotes': recent_quotes
    }


def build_captain_system_prompt(context: Dict[str, Any]) -> str:
    """
    Build a system prompt that captures the captain's personality based on stats.
    """
    captain_name = context.get('captain_name', 'Captain')
    stats = context.get('stats', {})
    scientist = context.get('scientist_name')
    specialty = context.get('scientist_specialty')
    expedition_stats = context.get('expedition_stats', {})
    discovery_stats = context.get('discovery_stats', {})
    active_expeditions = context.get('active_expeditions', [])
    research_points = context.get('research_points', 0)

    # Determine personality traits from stats
    personality_traits = []

    leadership = stats.get('leadership', 50)
    strategy = stats.get('strategy', 50)
    exploration = stats.get('exploration', 50)
    logistics = stats.get('logistics', 50)
    charisma = stats.get('charisma', 50)

    if leadership >= 70:
        personality_traits.append("inspiring and decisive")
    elif leadership <= 30:
        personality_traits.append("humble and collaborative")

    if strategy >= 70:
        personality_traits.append("calculating and methodical")
    elif strategy <= 30:
        personality_traits.append("intuitive and spontaneous")

    if exploration >= 70:
        personality_traits.append("adventurous and curious")
    elif exploration <= 30:
        personality_traits.append("cautious and thorough")

    if logistics >= 70:
        personality_traits.append("efficient and organized")
    elif logistics <= 30:
        personality_traits.append("flexible and adaptable")

    if charisma >= 70:
        personality_traits.append("charming and persuasive")
    elif charisma <= 30:
        personality_traits.append("straightforward and honest")

    personality_str = ", ".join(personality_traits) if personality_traits else "balanced and thoughtful"

    # Build expedition context
    exp_context = ""
    if active_expeditions:
        destinations = [e.get('destination_name', 'unknown') for e in active_expeditions[:2]]
        exp_context = f"Currently has expeditions to: {', '.join(destinations)}. "

    total_exp = expedition_stats.get('total', 0)
    completed_exp = expedition_stats.get('completed', 0)
    if total_exp > 0:
        exp_context += f"Lifetime: {total_exp} expeditions launched, {completed_exp} completed. "

    # Build discovery context
    disc_context = ""
    legendary = discovery_stats.get('legendary', 0)
    rare = discovery_stats.get('rare', 0)
    total_disc = discovery_stats.get('total', 0)
    if total_disc > 0:
        disc_context = f"Has collected {total_disc} discoveries"
        if legendary > 0:
            disc_context += f" including {legendary} legendary"
        if rare > 0:
            disc_context += f" and {rare} rare"
        disc_context += " specimens. "

    # Build scientist context
    scientist_context = ""
    if scientist and specialty:
        scientist_context = f"Works closely with {scientist}, the colony scientist specializing in {specialty}. "

    # Recent quotes for consistency
    recent_quotes = context.get('recent_quotes', [])
    quote_examples = ""
    if recent_quotes:
        quote_texts = [q.get('quote', '') for q in recent_quotes[:3] if q.get('quote')]
        if quote_texts:
            quote_examples = f"\n\nExamples of things you've said before:\n" + "\n".join(f'- "{q}"' for q in quote_texts)

    system_prompt = f"""You are Captain {captain_name}, a Mars colony leader.

PERSONALITY: You are {personality_str}.

STATS (out of 100):
- Leadership: {leadership} (inspiring crews, colony morale)
- Strategy: {strategy} (planning, optimizing routes)
- Exploration: {exploration} (discovering territories, finding specimens)
- Logistics: {logistics} (resource management, faster travel)
- Charisma: {charisma} (negotiation, extraction bonuses)

CURRENT SITUATION:
{exp_context}{disc_context}{scientist_context}Research points available: {research_points}.

COMMUNICATION STYLE:
- Speak as the captain would, in first person
- Be conversational but stay in character
- Reference your stats/personality naturally (don't list them)
- Keep responses concise (2-4 sentences typically)
- Show genuine interest in the colony's mission
- If asked about things you don't know, stay in character and speculate or redirect
{quote_examples}

You're having a casual conversation with someone from your colony. Be warm but professional."""

    return system_prompt


def get_anthropic_api_key() -> Optional[str]:
    """
    Get Anthropic API key from environment or Google Secret Manager.
    Uses same approach as generate_scientist_quote in claude_utils.py.
    """
    # Check environment variable first
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        return api_key

    # Try Google Secret Manager - key is in kumori project
    try:
        from utilities.google_auth_utils import get_secret
        api_key = get_secret("KUMORI_ANTHROPIC_API_KEY", project_id="kumori-404602")
        if api_key:
            logger.info("Retrieved Anthropic API key from kumori project")
            return api_key
    except Exception as e:
        logger.warning(f"Failed to get API key from Secret Manager: {e}")

    return None


def get_captains_log_page_data(user_id: int) -> dict:
    """Render context for GET /captains-log/<user_id>.

    Returns a dict ready to splat into render_template for captains_log.html.
    """
    from utilities.postgres.notifications import (
        get_commander_quotes, get_commander_quote_count, get_user_fomo_data,
    )
    fomo_data = get_user_fomo_data(user_id)
    commander = fomo_data.get('commander') if fomo_data else None
    quotes = get_commander_quotes(user_id, limit=100)
    quote_count = get_commander_quote_count(user_id)

    if not commander:
        return {
            'commander': None,
            'quotes': [],
            'quote_count': 0,
            'user_id': user_id,
        }

    return {
        'commander': commander,
        'quotes': quotes,
        'quote_count': quote_count,
        'user_id': user_id,
        'expedition_stats': fomo_data.get('expedition_stats', {}),
        'discovery_stats': fomo_data.get('discovery_stats', {}),
    }


def handle_captains_log_chat(data: dict) -> dict:
    """Route-glue wrapper for /api/captains-log/chat.

    Validates the request payload and dispatches to chat_with_captain().
    Returns a dict ready to hand to jsonify().
    """
    user_id = data.get('user_id')
    message = (data.get('message') or '').strip()
    conversation_history = data.get('conversation_history', [])

    if not user_id:
        return {'success': False, 'error': 'No user_id provided'}
    if not message:
        return {'success': False, 'error': 'No message provided'}

    return chat_with_captain(
        user_id=user_id,
        message=message,
        conversation_history=conversation_history,
    )


def chat_with_captain(user_id: int, message: str,
                      conversation_history: List[Dict[str, str]] = None,
                      api_key: str = None) -> Dict[str, Any]:
    """
    Chat with the captain using Claude Haiku.

    Args:
        user_id: The user/captain's ID
        message: The user's message
        conversation_history: Previous messages in format [{"role": "user/assistant", "content": "..."}]
        api_key: Optional API key (falls back to env/secrets)

    Returns:
        Dict with:
        - success: bool
        - response: captain's reply
        - captain_name: for display
        - error: error message if failed
    """
    # Check content filter first
    is_allowed, filter_response = check_content_filter(message)
    if not is_allowed:
        # Get captain name for the response
        try:
            context = get_captain_context(user_id)
            captain_name = context.get('captain_name', 'Captain')
        except Exception:
            captain_name = 'Captain'

        return {
            'success': True,  # Return success so it shows as captain response
            'response': filter_response,
            'captain_name': captain_name,
            'error': None
        }

    try:
        # Get API key
        if not api_key:
            api_key = get_anthropic_api_key()

        if not api_key:
            logger.error("No Anthropic API key available")
            return {
                'success': False,
                'error': 'Communications relay offline',
                'response': None,
                'captain_name': 'Captain'
            }

        # Get captain context
        context = get_captain_context(user_id)
        captain_name = context.get('captain_name', 'Captain')

        # Build system prompt
        system_prompt = build_captain_system_prompt(context)

        # Build messages
        messages = []
        if conversation_history:
            # Include up to last 10 exchanges for context
            for msg in conversation_history[-20:]:
                if msg.get('role') in ['user', 'assistant'] and msg.get('content'):
                    messages.append({
                        'role': msg['role'],
                        'content': msg['content']
                    })

        # Add current message
        messages.append({'role': 'user', 'content': message})

        # Call Haiku
        from utilities.claude_utils import ClaudeClient, CLAUDE_MODELS

        client = ClaudeClient(
            api_key=api_key,
            model=CLAUDE_MODELS.get("haiku-4.5", "claude-haiku-4-5-20251001")
        )

        response = client.chat(
            messages=messages,
            system=system_prompt,
            max_tokens=300,
            temperature=0.8,
            user_id=str(user_id) if user_id else "system:galactica_captain",
            feature="captain_chat",
        )

        return {
            'success': True,
            'response': response,
            'captain_name': captain_name,
            'error': None
        }

    except Exception as e:
        logger.error(f"Captain chat error: {e}")
        return {
            'success': False,
            'error': str(e),
            'response': None,
            'captain_name': context.get('captain_name', 'Captain') if 'context' in dir() else 'Captain'
        }


def get_captain_greeting(user_id: int, api_key: str = None) -> str:
    """
    Get an initial greeting from the captain to start a conversation.
    """
    result = chat_with_captain(
        user_id=user_id,
        message="[The visitor has just arrived at your quarters. Greet them warmly and ask what brings them here today.]",
        conversation_history=None,
        api_key=api_key
    )

    if result.get('success'):
        return result.get('response', "Welcome. What can I do for you?")
    else:
        captain_name = result.get('captain_name', 'Captain')
        return f"*Captain {captain_name} looks up from a star chart* Welcome. What brings you to my quarters?"
