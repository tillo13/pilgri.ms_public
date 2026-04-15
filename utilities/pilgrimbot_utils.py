"""Shim — real code in utilities/pilgrimbot/ package. Kept for caller compat."""

from utilities.pilgrimbot.personas import (
    PERSONA_BASE, PERSONA_DEV, PERSONA_QA, PERSONA_CAPTAIN,
    PERSONAS, BUG_MODE_PROMPT, READ_FILE_TOOL,
)
from utilities.pilgrimbot.storage import (
    MAX_HISTORY, _strip_markdown_json, ensure_pilgrimbot_table,
    get_user_role, set_user_role, save_message, get_chat_history,
    get_user_chats, hide_chat, generate_title, log_pilgrimbot_call,
)
from utilities.pilgrimbot.file_reader import (
    PROJECT_ROOT, CODE_EXTS, SKIP_DIRS, MAX_FILE_CONTENT,
    read_local_file, _find_best_section, _build_codemap_summary,
)
from utilities.pilgrimbot.tool_loop import _execute_tool_loop
from utilities.pilgrimbot.context import (
    _plan_context, _plan_context_fallback, _load_surgical_context,
)
from utilities.pilgrimbot.streaming import (
    MODEL, _SSE_PAD, _sse,
    handle_pilgrimbot_chat_request, handle_chat_streaming,
)

# Pass-through re-exports from pilgrimbot_bugs (preserve existing facade behavior)
from utilities.pilgrimbot_bugs import (  # noqa: F401
    create_bug_from_question, create_bug_from_conversation,
    create_bug_from_response, get_reports,
)

# Pass-through re-export for player data tool (was in original module namespace)
from utilities.pilgrimbot_data import (  # noqa: F401
    PLAYER_DATA_TOOL, PLAYER_DATA_MAP, query_player_data,
)

__all__ = [
    # personas
    "PERSONA_BASE", "PERSONA_DEV", "PERSONA_QA", "PERSONA_CAPTAIN",
    "PERSONAS", "BUG_MODE_PROMPT", "READ_FILE_TOOL",
    # storage
    "MAX_HISTORY", "_strip_markdown_json", "ensure_pilgrimbot_table",
    "get_user_role", "set_user_role", "save_message", "get_chat_history",
    "get_user_chats", "hide_chat", "generate_title", "log_pilgrimbot_call",
    # file_reader
    "PROJECT_ROOT", "CODE_EXTS", "SKIP_DIRS", "MAX_FILE_CONTENT",
    "read_local_file", "_find_best_section", "_build_codemap_summary",
    # tool_loop
    "_execute_tool_loop",
    # context
    "_plan_context", "_plan_context_fallback", "_load_surgical_context",
    # streaming
    "MODEL", "_SSE_PAD", "_sse",
    "handle_pilgrimbot_chat_request", "handle_chat_streaming",
    # bugs re-exports
    "create_bug_from_question", "create_bug_from_conversation",
    "create_bug_from_response", "get_reports",
    # data re-exports
    "PLAYER_DATA_TOOL", "PLAYER_DATA_MAP", "query_player_data",
]
