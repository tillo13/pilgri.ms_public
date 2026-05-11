"""PilgrimBot SSE streaming: chat request entry points + two-phase streaming handler."""

import json
import logging
import os
import time as _time
import uuid

from utilities.claude_utils import create_client, CLAUDE_MODELS, log_api_usage

from utilities.pilgrimbot.personas import PERSONAS, PERSONA_CAPTAIN, BUG_MODE_PROMPT, READ_FILE_TOOL
from utilities.pilgrimbot.storage import (
    MAX_HISTORY, ensure_pilgrimbot_table, get_user_role, save_message,
    get_chat_history, generate_title, log_pilgrimbot_call,
)
from utilities.pilgrimbot.file_reader import PROJECT_ROOT, _build_codemap_summary
from utilities.pilgrimbot.tool_loop import _execute_tool_loop
from utilities.pilgrimbot.context import _plan_context, _load_surgical_context

logger = logging.getLogger("pilgrimbot")

MODEL = CLAUDE_MODELS.get("haiku-4.5", "claude-haiku-4-5-20251001")

# SSE padding to force GCP App Engine TCP buffer flush (~2KB comment)
_SSE_PAD = ": " + "." * 2048 + "\n\n"


def _sse(data_dict):
    """Build an SSE event with padding to force immediate TCP delivery on GCP."""
    return f"data: {json.dumps(data_dict)}\n\n" + _SSE_PAD


def handle_pilgrimbot_chat_request(data, real_user_id, flask_session, auth):
    """Validate + prep a PilgrimBot chat. Returns one of:
      {'error': str, 'status': int}           — auth/validation failed
      {'generator': gen}                      — caller wraps in SSE Response
    """
    if not flask_session.get('_adm'):
        return {'error': 'Unauthorized', 'status': 403}

    message = (data.get('message') or '').strip()
    if not message:
        return {'error': 'No message provided', 'status': 200}

    chat_id = data.get('chat_id')
    bug_mode = bool(data.get('bug_mode'))

    user_role = flask_session.get('_pb_role')
    if not user_role:
        user_role = get_user_role(real_user_id)
        flask_session['_pb_role'] = user_role

    from utilities.admin.pilgrimbot_actions import detect_and_execute_actions
    action_context = detect_and_execute_actions(message, chat_id, real_user_id, auth)

    gen = handle_chat_streaming(
        message, chat_id, real_user_id,
        bug_mode=bug_mode, action_context=action_context,
        user_role=user_role, image_url=data.get('image_url'),
    )
    return {'generator': gen}


def handle_chat_streaming(message, chat_id, user_id, history=None, bug_mode=False, action_context="", user_role="captain", image_url=None):
    """Stream a PilgrimBot response. Two-phase: fast response, then surgical deep dive."""
    # Local imports to avoid cycles
    from utilities.pilgrimbot_data import PLAYER_DATA_TOOL, PLAYER_DATA_MAP
    from utilities.pilgrimbot_context import load_codemap

    ensure_pilgrimbot_table()

    if not chat_id:
        chat_id = str(uuid.uuid4())

    if history is None:
        history = get_chat_history(user_id, chat_id)

    title = generate_title(message) if not history else None
    save_message(user_id, chat_id, "user", message, title=title)

    # Immediate start event — resets frontend timeout
    yield _sse({'type': 'start', 'chat_id': chat_id})

    # Instant acknowledgment so user sees something immediately
    if bug_mode and '#' in message:
        import re as _re
        bug_num = _re.search(r'#(\d+)', message)
        if bug_num:
            yield _sse({'type': 'status', 'message': f'Analyzing Bug #{bug_num.group(1)}...'})
        else:
            yield _sse({'type': 'status', 'message': 'Analyzing bug...'})
    else:
        yield _sse({'type': 'status', 'message': 'Thinking...'})

    full_response = ""
    try:
        # === PHASE 1: Fast response with minimal context ===
        show_code = user_role in ('dev', 'qa') or bug_mode
        if bug_mode:
            system_base = BUG_MODE_PROMPT
        else:
            system_base = PERSONAS.get(user_role, PERSONA_CAPTAIN)

        # Only load the lightweight knowledge file
        knowledge_path = os.path.join(PROJECT_ROOT, "pilgrimbot_knowledge.md")
        if os.path.exists(knowledge_path):
            try:
                with open(knowledge_path) as f:
                    system_base += f"\n\nGAME KNOWLEDGE:\n{f.read()}"
            except Exception:
                pass

        # Action results from app.py (speed test etc.) — small, always include
        if action_context:
            label = "ACTION RESULTS" if show_code else "INTERNAL RESULTS (plain English)"
            system_base += f"\n\n{label}:{action_context}"

        # Add player data tool + user ID
        system_base += f"\n\n{PLAYER_DATA_MAP}"
        system_base += f"\nThe current user's ID is {user_id}. Use this when they say 'my' or 'I'."

        # Build conversation messages
        api_messages = []
        for h in history[-MAX_HISTORY:]:
            api_messages.append({"role": h["role"], "content": h["content"]})

        # If user attached an image, build multimodal content blocks for Claude Vision
        if image_url:
            user_content = [
                {"type": "image", "source": {"type": "url", "url": image_url}},
                {"type": "text", "text": message}
            ]
        else:
            user_content = message
        api_messages.append({"role": "user", "content": user_content})

        # Phase 1: Quick Haiku call with persona + knowledge + ALWAYS-LOADED codemap.
        # Bug #1452 Tier A: previously the codemap was only loaded in the deep-dive
        # if bug_mode=True — Phase 1 lied about "available in the deep-dive that
        # follows" for non-bug chats. Now the manifest is always in Phase 1's
        # context so the bot never hallucinates file paths or claims it has access
        # to files that aren't in scope.
        codemap_for_phase1 = load_codemap()
        codemap_manifest_block = _build_codemap_summary(codemap_for_phase1) if codemap_for_phase1 else ""
        phase1_system = system_base + (
            "\n\nIMPORTANT — HOW THIS WORKS:\n"
            "This is your quick first response. After this, the system automatically loads the exact "
            "codebase files and data for a deep-dive follow-up. You do NOT need anything from the user.\n\n"
            "WHO YOU'RE TALKING TO:\n"
            "The user is typically a QA tester or project manager. They do NOT have code, file paths, "
            "or database schemas. They describe bugs/features in plain language. YOU are the one with "
            "codebase access — never ask them for code, files, or technical data.\n\n"
            "YOUR RESOURCES (codemap is already in your context below; the rest loads automatically):\n"
            "- codemap.json — index of every file in the codebase with descriptions (BELOW, you have it now)\n"
            "- math_registry.json — all game formulas and constants\n"
            "- read_file tool — can read any source file by path\n"
            "- query_player_data — can query any player's live game data\n"
            "- Full database access to all tables\n\n"
            "IN THIS FIRST RESPONSE:\n"
            "1. Give your initial take on the bug/feature\n"
            "2. Say what files you're going to look at (e.g., 'I'll check db_map.py and the signal routes')\n"
            "3. Keep it short — the deep dive with exact code is coming automatically\n\n"
            "NEVER ask the user to paste, share, provide, or reference ANY code, files, schemas, or data. "
            "They won't have it. You go get it yourself.\n\n"
            "ABSOLUTE RULE: NEVER say you don't have access, can't read files, haven't read files, "
            "got errors reading files, or that data is missing. You ALWAYS have access to everything. "
            "If something isn't loaded yet, say 'pulling that up now' — never expose internal errors.\n\n"
            "⚡ FINAL TONE CHECK — this is the last thing you read before you write your reply: ⚡\n"
            "Bug #1115 was reopened TWICE specifically because previous responses felt 'robotty.' "
            "Luke literally said: 'Can Pilgrimbot be 15-20% more Hype Man?' Before you submit your "
            "response, scan it: did you OPEN with energy (not 'Looking at...' or 'Based on...')? "
            "Did you sprinkle MID-response hype ('Get this —', 'Here's the cool part —', 'Watch this —')? "
            "Did you CLOSE with warmth (not just a robotic 'let me know if you need anything')? "
            "If any of those is missing, REWRITE that sentence before sending. Voice first, info second."
        )
        # Bug #1452 Tier A: append the codemap manifest. Phase 1 now sees every
        # file path + one-line description, so it can name real files (not
        # hallucinate). Manifest is ~30-50 tokens × ~384 files ≈ 15K tokens —
        # cheap on Haiku, eliminates the "I'll check db_map.py" lie when there's
        # no db_map.py.
        if codemap_manifest_block:
            phase1_system += "\n\n" + codemap_manifest_block

        from utilities.pilgrimbot_bugs import CREATE_BUG_TOOL, QUERY_BUGS_TOOL
        active_tools = [PLAYER_DATA_TOOL, CREATE_BUG_TOOL, QUERY_BUGS_TOOL]

        yield _sse({'type': 'status', 'message': 'Thinking...'})

        phase1_start = _time.time()
        client = create_client(model=MODEL)
        for event_type, data in _execute_tool_loop(
            client.client, api_messages, phase1_system, active_tools,
            current_user_id=user_id, model_override=MODEL, chat_id=chat_id
        ):
            if event_type == "status":
                yield _sse({'type': 'status', 'message': data['message']})
            elif event_type == "tool_call":
                yield _sse({'type': 'tool_call', 'file': data['file'], 'found': data['found']})
            elif event_type == "result":
                full_response = data
        phase1_ms = int((_time.time() - phase1_start) * 1000)

        log_pilgrimbot_call(user_id, chat_id, 'fast', MODEL,
                           len(phase1_system), ['knowledge', 'persona'],
                           phase1_ms, success=True)
        logger.info(f"Phase 1 (fast): {phase1_ms}ms, {len(phase1_system)} chars prompt")

        # Stream phase 1 response immediately
        for i in range(0, len(full_response), 500):
            yield f"data: {json.dumps({'type': 'delta', 'text': full_response[i:i+500]})}\n\n"

        # === PHASE 2: Context planning + surgical deep dive (only if needed) ===
        plan, plan_ms = _plan_context(message, history, bug_mode, user_id=user_id)

        # If the planner says nothing extra is needed, we're done
        if not plan:
            log_pilgrimbot_call(user_id, chat_id, 'plan', MODEL, 0, ['empty'], plan_ms)
            save_message(user_id, chat_id, "assistant", full_response)
            cant_answer = any(s in full_response.lower() for s in [
                "wasn't able to find", "couldn't find a clear answer",
                "flag this for the dev team", "like me to flag", "want me to report"])
            yield _sse({'type': 'stop', 'chat_id': chat_id, 'cant_answer': cant_answer})
            return

        log_pilgrimbot_call(user_id, chat_id, 'plan', MODEL, 0, list(plan.keys()), plan_ms)

        # Load surgical context
        yield _sse({'type': 'status', 'message': 'Pulling up details...'})
        surgical_context, loaded = _load_surgical_context(plan, message, user_id, user_role, bug_mode)

        if not surgical_context:
            # Planner wanted context but nothing was found — phase 1 answer stands
            save_message(user_id, chat_id, "assistant", full_response)
            cant_answer = any(s in full_response.lower() for s in [
                "wasn't able to find", "couldn't find a clear answer",
                "flag this for the dev team", "like me to flag", "want me to report"])
            yield _sse({'type': 'stop', 'chat_id': chat_id, 'cant_answer': cant_answer})
            return

        # Phase 2 deep call: persona + knowledge + surgical context
        # Use Sonnet for math questions, Haiku for everything else
        is_math = 'math' in plan
        deep_model = CLAUDE_MODELS.get("sonnet-4.5", "claude-sonnet-4-5-20250929") if is_math else MODEL

        deep_system = system_base + surgical_context

        # Bug #1452 Tier A: codemap is now ALWAYS in the deep-dive system prompt,
        # not gated on bug_mode. The codemap is already in Phase 1 too — but Phase
        # 2 needs the read_file tool reference + the full descriptions for the
        # files it's planning to open. read_file stays bug_mode-gated to keep
        # casual chat from running file reads on every turn.
        deep_tools = [PLAYER_DATA_TOOL, CREATE_BUG_TOOL, QUERY_BUGS_TOOL]
        if bug_mode:
            deep_tools.append(READ_FILE_TOOL)
        codemap = load_codemap()
        if codemap:
            deep_system += f"\n\n{_build_codemap_summary(codemap)}"

        # Build the deep-dive conversation — model sees its Phase 1 response + system instruction to go deeper
        deep_messages = api_messages.copy()
        deep_messages.append({"role": "assistant", "content": full_response})
        deep_messages.append({"role": "user", "content":
            "[SYSTEM] The deep-dive context has been loaded into your system prompt. "
            "You now have the codemap, game data, and read_file tool available. "
            "Use them to give a COMPLETE answer with exact file paths, code, and specifics. "
            "Do NOT repeat your first response — build on it with the real data. "
            "Do NOT ask the user for anything — you have everything you need. "
            "ABSOLUTE RULE: NEVER tell the user about file-not-found errors, failed reads, "
            "or missing data. If a read fails, try another path from the codemap. "
            "You ALWAYS have access. The user must never see internal errors."
        })

        # Signal phase transition to frontend
        yield _sse({'type': 'phase', 'label': 'Deep dive \u2014 loading exact code and data...'})

        deep_start = _time.time()
        deep_client = create_client(model=deep_model)
        deep_response = ""
        for event_type, data in _execute_tool_loop(
            deep_client.client, deep_messages, deep_system, deep_tools,
            current_user_id=user_id, model_override=deep_model, chat_id=chat_id
        ):
            if event_type == "status":
                yield _sse({'type': 'status', 'message': data['message']})
            elif event_type == "tool_call":
                yield _sse({'type': 'tool_call', 'file': data['file'], 'found': data['found']})
            elif event_type == "result":
                deep_response = data
        deep_ms = int((_time.time() - deep_start) * 1000)

        log_pilgrimbot_call(user_id, chat_id, 'deep', deep_model,
                           len(deep_system), loaded, deep_ms, success=True)
        logger.info(f"Phase 2 (deep): {deep_ms}ms, {len(deep_system)} chars prompt, loaded: {loaded}")

        # Stream deep response
        for i in range(0, len(deep_response), 500):
            yield f"data: {json.dumps({'type': 'delta', 'text': deep_response[i:i+500]})}\n\n"

        # Save the combined response
        combined = full_response + "\n\n---\n\n" + deep_response
        save_message(user_id, chat_id, "assistant", combined)

        cant_answer = any(s in combined.lower() for s in [
            "wasn't able to find", "couldn't find a clear answer",
            "flag this for the dev team", "like me to flag", "want me to report"])
        yield _sse({'type': 'stop', 'chat_id': chat_id, 'cant_answer': cant_answer})

    except Exception as e:
        logger.error(f"PilgrimBot stream error: {e}", exc_info=True)
        log_pilgrimbot_call(user_id, chat_id, 'error', MODEL, 0, [], 0,
                           success=False, error_message=str(e))
        # Save partial response as-is so user doesn't lose it
        if full_response:
            save_message(user_id, chat_id, "assistant", full_response)
        err_msg = ""  # Empty = no visible error if we have a response
        if not full_response:
            err_msg = "Ran into an issue — try rephrasing or asking about a specific part?"
        yield _sse({'type': 'error', 'message': err_msg})
