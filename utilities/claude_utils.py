"""Shim — real code lives in utilities/anthropic/ and feature-specific modules.

Kept at this path so existing callers (`from utilities.claude_utils import ...`)
keep working. Round 5 refactor split the 1756-LOC monolith into:

- utilities/anthropic/pricing.py  — model catalog, pricing, log_api_usage
- utilities/anthropic/client.py    — ClaudeClient, _get_anthropic_api_key
- utilities/anthropic/convenience.py — create_client, stream_response, chat, etc.
- utilities/aria/prompts.py        — generate_aria_snapshot_narrative/prompt (appended)
- utilities/character_quotes.py    — generate_scientist_quote, generate_commander_quote
- utilities/golem_names.py         — suggest_golem_names
- utilities/brainstorm_chat.py     — brainstorm_chat
- utilities/shared_chat.py         — get_claude_response_for_shared_chat
- utilities/conversation_summary.py — generate_conversation_summary
"""

from utilities.anthropic.pricing import (
    CLAUDE_MODELS,
    MODEL_PRICING,
    CACHE_WRITE_MULTIPLIER,
    CACHE_READ_MULTIPLIER,
    WEB_SEARCH_COST,
    WEB_SEARCH_TOOL_VERSION,
    APP_NAME,
    log_api_usage,
    get_model_pricing,
)
from utilities.anthropic.client import (
    ClaudeClient,
    _get_anthropic_api_key,
)
from utilities.anthropic.convenience import (
    create_client,
    stream_response,
    chat_with_history,
    get_available_models,
    get_latest_model,
    generate_text,
    process_image,
    chat,
)
from utilities.conversation_summary import generate_conversation_summary
from utilities.character_quotes import (
    generate_scientist_quote,
    generate_commander_quote,
)
from utilities.shared_chat import get_claude_response_for_shared_chat
from utilities.aria.prompts import (
    generate_aria_snapshot_narrative,
    generate_aria_snapshot_prompt,
)
from utilities.brainstorm_chat import brainstorm_chat
from utilities.golem_names import suggest_golem_names

__all__ = [
    # pricing
    "CLAUDE_MODELS",
    "MODEL_PRICING",
    "CACHE_WRITE_MULTIPLIER",
    "CACHE_READ_MULTIPLIER",
    "WEB_SEARCH_COST",
    "WEB_SEARCH_TOOL_VERSION",
    "APP_NAME",
    "log_api_usage",
    "get_model_pricing",
    # client
    "ClaudeClient",
    "_get_anthropic_api_key",
    # convenience
    "create_client",
    "stream_response",
    "chat_with_history",
    "get_available_models",
    "get_latest_model",
    "generate_text",
    "process_image",
    "chat",
    # feature modules
    "generate_conversation_summary",
    "generate_scientist_quote",
    "generate_commander_quote",
    "get_claude_response_for_shared_chat",
    "generate_aria_snapshot_narrative",
    "generate_aria_snapshot_prompt",
    "brainstorm_chat",
    "suggest_golem_names",
]
