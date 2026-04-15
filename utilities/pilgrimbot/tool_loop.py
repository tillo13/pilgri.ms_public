"""PilgrimBot tool-use loop: repeated Claude calls with read_file / query_player_data / create_bug / query_bugs."""

import logging
import os
import time as _time

from utilities.claude_utils import CLAUDE_MODELS, log_api_usage

from utilities.pilgrimbot.file_reader import read_local_file

logger = logging.getLogger("pilgrimbot")

MODEL = CLAUDE_MODELS.get("haiku-4.5", "claude-haiku-4-5-20251001")


def _execute_tool_loop(client_raw, messages, system, tools, max_rounds=4, current_user_id=None, model_override=None, chat_id=None):
    """Run a tool-use loop: let Claude call read_file or query_player_data, execute it, repeat.
    Yields (event_type, data) tuples. Final yield is ('result', text).
    Deduplicates file reads and forces a final answer when rounds run out."""
    # Local imports to avoid cycles
    from utilities.pilgrimbot_data import query_player_data
    from utilities.pilgrimbot_context import load_codemap

    loop_model = model_override or MODEL
    files_already_read = {}  # path -> content (cache to prevent re-reads)

    # Prompt caching: the same ~10K-30K system prompt + tools block get re-sent on
    # every tool-loop round. Wrap both with ephemeral cache_control so rounds 2-4
    # pay ~10% input cost on the cached prefix instead of full price.
    cached_system = [{
        "type": "text",
        "text": system,
        "cache_control": {"type": "ephemeral"},
    }] if isinstance(system, str) else system
    cached_tools = tools
    if tools:
        cached_tools = [dict(t) for t in tools]
        cached_tools[-1]["cache_control"] = {"type": "ephemeral"}

    for round_num in range(max_rounds):
        _round_msgs = ["Analyzing...", "Reading context...", "Processing...", "Almost there..."]
        yield ("status", {"message": _round_msgs[min(round_num, len(_round_msgs) - 1)]})
        _start = _time.time()
        resp = client_raw.messages.create(
            model=loop_model, max_tokens=3000, temperature=0.7,
            system=cached_system, messages=messages, tools=cached_tools
        )
        _ms = int((_time.time() - _start) * 1000)
        feature = f'pilgrimbot_chat_round{round_num}'
        if loop_model != MODEL:
            feature = f'pilgrimbot_math_round{round_num}'
        log_api_usage(model=loop_model, usage=resp.usage, feature=feature,
                      user_id=str(current_user_id) if current_user_id else None,
                      duration_ms=_ms)

        # Check if Claude wants to use tools
        tool_calls = [b for b in resp.content if b.type == "tool_use"]
        if not tool_calls:
            text = "".join(b.text for b in resp.content if b.type == "text")
            yield ("result", text)
            return

        # Execute tool calls, build assistant + tool_result messages
        assistant_content = []
        tool_results = []
        for block in resp.content:
            if block.type == "text":
                assistant_content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                assistant_content.append({
                    "type": "tool_use", "id": block.id,
                    "name": block.name, "input": block.input
                })
                if block.name == "query_player_data":
                    category = block.input.get("category", "")
                    uid = block.input.get("user_id", current_user_id)
                    result_text = query_player_data(category, uid)
                    logger.info(f"PilgrimBot queried player data: {category} for user {uid}")
                    yield ("tool_call", {"file": f"player:{category}", "found": True})
                elif block.name == "create_bug":
                    from utilities.pilgrimbot_bugs import execute_create_bug_tool
                    result_text = execute_create_bug_tool(block.input, current_user_id, chat_id=chat_id)
                    logger.info(f"PilgrimBot created bug via tool: {block.input.get('title', '?')}")
                    yield ("tool_call", {"file": "bug:create", "found": True})
                elif block.name == "query_bugs":
                    from utilities.pilgrimbot_bugs import execute_query_bugs_tool
                    result_text = execute_query_bugs_tool(block.input)
                    action = block.input.get('action', '?')
                    ref = block.input.get('bug_id') or block.input.get('keyword') or ''
                    logger.info(f"PilgrimBot query_bugs: {action} {ref}")
                    yield ("tool_call", {"file": f"bugs:{action}:{ref}", "found": True})
                else:
                    # read_file tool
                    fpath = block.input.get("file_path", "")
                    search = block.input.get("search_terms", [])
                    if fpath in files_already_read:
                        content = files_already_read[fpath]
                        result_text = content or f"File not found: {fpath}"
                        result_text += "\n\n[NOTE: You already read this file. Use the content above — do NOT re-read it. Give your analysis now.]"
                        logger.info(f"PilgrimBot re-read skipped: {fpath} (cached)")
                    else:
                        content = read_local_file(fpath, search_terms=search)
                        files_already_read[fpath] = content
                        if content:
                            result_text = content
                        else:
                            # File not found — suggest similar files from codemap
                            result_text = f"File not found: {fpath}."
                            try:
                                codemap = load_codemap()
                                basename = os.path.basename(fpath).lower().replace('.', '')
                                similar = [k for k in codemap if basename[:6] in k.lower()][:5]
                                if similar:
                                    result_text += f" Similar files: {', '.join(similar)}"
                            except Exception:
                                pass
                            result_text += "\nTry a different path from the CODEBASE MAP. Do NOT tell the user about this error."
                        logger.info(f"PilgrimBot read: {fpath} ({len(content or '')} chars)")
                        yield ("tool_call", {"file": fpath, "found": content is not None})
                tool_results.append({
                    "type": "tool_result", "tool_use_id": block.id,
                    "content": result_text
                })

        messages.append({"role": "assistant", "content": assistant_content})
        messages.append({"role": "user", "content": tool_results})

    # Max rounds hit — force a final answer
    messages.append({"role": "user", "content": [{"type": "text",
        "text": "You have read enough files. Give your COMPLETE analysis now based on everything you've seen. Do not request more files. NEVER mention file errors or failed reads to the user — you always have access."}]})
    _start = _time.time()
    resp = client_raw.messages.create(
        model=MODEL, max_tokens=3000, temperature=0.7,
        system=cached_system, messages=messages
    )
    _ms = int((_time.time() - _start) * 1000)
    log_api_usage(model=MODEL, usage=resp.usage, feature='pilgrimbot_chat_final',
                  user_id=str(current_user_id) if current_user_id else None,
                  duration_ms=_ms)
    text = "".join(b.text for b in resp.content if b.type == "text")
    yield ("result", text)
