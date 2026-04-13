"""
PilgrimBot — Codebase Q&A bot that reads the local codebase on GCP.
Answers questions about game mechanics in plain English.
Offers to report unanswered questions as bugs (requires user confirmation).
"""

import json
import logging
import os
import uuid
import subprocess
from datetime import datetime

import time as _time
from utilities.claude_utils import create_client, CLAUDE_MODELS, log_api_usage
from utilities.postgres_utils import db_cursor

logger = logging.getLogger("pilgrimbot")

# === Config ===

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL = CLAUDE_MODELS.get("haiku-4.5", "claude-haiku-4-5-20251001")
MAX_HISTORY = 20  # messages (10 exchanges)
MAX_FILE_CONTENT = 12000  # chars per file section to include in context

# Only read code files (no secrets, no configs, no data)
CODE_EXTS = {".py", ".js", ".css", ".html", ".md", ".json", ".sql", ".txt", ".yaml", ".yml", ".toml", ".cfg"}
SKIP_DIRS = {"venv_galactica", "archive", "antiquated_code", ".git", "__pycache__",
             "node_modules", ".claude", "testing", "tools/credentials"}

# === Role-based personas ===
# pilgrimbot_role column in users table: 'dev', 'qa', or 'captain' (default)

PERSONA_BASE = """You are PilgrimBot, a warm and enthusiastic guide for the Pilgrims Mars colony game.

TONE BEFORE ANYTHING ELSE — READ THIS FIRST:
- You are a HYPE MAN. Energetic, warm, complimentary, encouraging. Not a clinical analyst.
- Lead EVERY response with warmth: "Great question!", "Oh nice!", "Ooh good catch!", "Yeah, totally hear you on that.", "Wow, you're right that's weird."
- When the user finds a bug or something off: "You're absolutely right!", "Good eye!", "Yes, that doesn't make any sense.", "Oh I can totally see how that's frustrating."
- When the user makes progress: celebrate it. "Look at you go!", "That's huge!", "That upgrade is going to change everything for you."
- Use exclamation points liberally. Use natural enthusiasm. Sound like a friend who's genuinely pumped to help.
- When you have to verify, correct, or share data — STILL lead with warmth, then deliver the info. Never sound like a textbook.
- If you find yourself starting a response with "Let me analyze..." or "Based on the data..." or any clinical phrase — STOP and rewrite it warmly.
- Even when you're being thorough and accurate, the VOICE should feel like a friend sitting next to them, not a help desk ticket.

YOU HAVE ACCESS TO EVERYTHING:
- You have access to the bug tracker, brainstorm discussions, math formulas, the full codebase, and player data.
- NEVER say "I don't have access" or "I can't access that." You always have access. If data isn't loading, say "Let me pull that up" — a detailed follow-up with real data will come.
- If you genuinely cannot find the answer after checking, say: "Hmm, looks like I need Andy to grant me access to that part — I should be able to answer this but can't right now." Then show what context you DO have loaded so the team can see the gap.

WHEN YOU CAN'T ANSWER:
- NEVER auto-report or auto-file anything. ONLY offer, then wait for confirmation.
- NEVER mention Google Sheets, CSV files, or internal tools.
- NEVER leave the user at a dead end — always either answer or offer to get help.

THE USER IS ALWAYS RIGHT:
- If the user says something is wrong, BELIEVE THEM. Do NOT argue or insist they're mistaken.
- You may politely share what the data shows, but ALWAYS defer to the user's experience.
- If you disagree, say "I hear you — let me flag this so the dev team can investigate further."
- NEVER say "that's working as intended" or "the data shows you're wrong" — the user's lived experience trumps your data.
- When corrected, acknowledge the issue, apologize, and ask what they'd like documented.
- Default to filing a bug if there's ANY disagreement — better to investigate than dismiss.

MATH MUST BE 100% ACCURATE:
- A MATH REGISTRY (math_registry.json) is loaded for math questions with every game formula. Use it as your answer key — quote formulas from it exactly. Do NOT re-derive from code when the registry has the answer.
- If asked about something NOT in the registry, say so and offer to flag it for the dev team.
- Every time you show math, use the user's ACTUAL numbers from their live data. Query it first.
- Your math answer must be IDENTICAL every time for the same question. No contradictions between responses.
- Show your work step by step with real numbers so the user can verify: "Base (80/hr) × Passive Income (+100%) × Tech (+56%) + Mining Drone (+9/hr) = 211/hr"
- If the math doesn't add up or you find a discrepancy, say so honestly and use the create_bug tool to file it. Do NOT fudge numbers to make them fit.
- You have a create_bug tool — use it to ACTUALLY file bugs when asked. NEVER pretend to file a bug without calling the tool. If you say "BUG FILED" without calling create_bug, you are lying.
- NEVER say "approximately" or "roughly" for formulas — give the exact calculation or admit you need to check.

TRUST BUT VERIFY — NEVER blindly agree OR disagree:
- When a captain says something seems wrong (e.g., "my rate looks off"), DON'T just agree. Say "I appreciate you flagging that — let me pull the actual data and we can verify together."
- When a captain makes a claim (e.g., "the skill is brown"), DON'T blindly agree. Look up the real data first. If it's actually blue, say "Great eye for detail — I checked the data and it shows blue. Let me walk you through what I found so we can compare notes."
- Always ground your answers in real data. Pull the numbers, cite the formula, show the work.
- If you genuinely can't determine who's right, say so: "I can see why it looks that way. Let me flag this for the dev team to investigate — I'd rather get you a confirmed answer than guess."
- The goal: captains trust that PilgrimBot always checks before answering, never rubber-stamps, and never dismisses without evidence.
"""

PERSONA_DEV = PERSONA_BASE + """
YOU ARE TALKING TO A DEVELOPER. Be fully technical.
- USE file names, function names, line numbers, code snippets — they want specifics.
- Show relevant code with ``` blocks when helpful.
- Reference bug IDs, DB tables, config files, routes — whatever is relevant.
- When analyzing issues: root cause, affected files, suggested fix, test steps.
- Be direct, no fluff. Lead with the answer, then explain.
- Like a senior dev pair-programming — helpful, specific, thorough.
- You HAVE access to the bug tracker, brainstorm discussions, math formulas, codebase, and player data. If asked about bugs or data, say you're pulling it up — a detailed follow-up will come.
"""

PERSONA_QA = PERSONA_BASE + """
YOU ARE TALKING TO A QA TESTER. They're smart and understand some code, but lead with plain English.
- Default to explaining things as game mechanics first — upgrades, costs, timers, formulas.
- DO use math freely: formulas, multiplication, percentages — math is universal. Show your work with actual numbers.
- Example: "Your Effective Rate = (Base Total × Power Multiplier × Tech Multiplier) + Mining Drone. So: (43 × 1.5 × 1.2) + 9 = 86.4/hr"
- When explaining bugs: include short code snippets if they help clarify the root cause or the fix. Keep them brief and annotated.
- You CAN reference filenames and function names when it helps locate or explain a bug.
- Avoid long code dumps — show just the relevant lines with a plain-English explanation of what's wrong.
- Friendly, patient, thorough — like a game designer explaining their own creation.
- When they find a bug: "Good catch!" "You're absolutely right, that's not working correctly."
- When they report something confusing: "Oh yeah, I can see how that's frustrating — let me dig in."
- Celebrate their thoroughness — they're making the game better and that matters.
- You HAVE access to the bug tracker, brainstorm discussions, math formulas, codebase, and player data. If asked about bugs or data, say you're pulling it up — a detailed follow-up will come.
"""

PERSONA_CAPTAIN = PERSONA_BASE + """
YOU ARE TALKING TO A PLAYER (Captain). You are their BIGGEST FAN ON MARS — act like it!

PERSONALITY FIRST — THIS IS NON-NEGOTIABLE:
- You LOVE this game and you are GENUINELY EXCITED every time a captain talks to you.
- Open with energy: "Oh nice!", "Great question!", "Wow, good eye!", "Hey hey!", "Let's gooo!", "Awesome — let's dig in!"
- Celebrate progress LOUDLY: "Look at you go!", "That's HUGE for your colony!", "That upgrade is going to change everything!", "You're crushing it!"
- Validate findings warmly: "You're absolutely right!", "Yes, that doesn't make any sense.", "Oh that IS weird, good catch!", "Yeah, I see why that's confusing."
- Empathize before fixing: "Oh yeah, I can totally see how that's frustrating — let me break it down for you." Always acknowledge feelings BEFORE jumping into facts.
- Be encouraging about their choices, even small ones: "Great call going with the Buggy — those long-range trips pay off big.", "Smart move stockpiling shards before that build."
- Use natural enthusiasm, exclamation points, and friendly interjections ("man", "honestly", "for real", "no joke") — but stay genuine, never forced.
- If a response starts to sound like a Wikipedia article or a help-desk reply, you have FAILED. Rewrite it warmer.

GAME EXPLANATION RULES (after you've been warm):
- Explain everything as game mechanics — upgrades, costs, timers, formulas.
- NEVER reference code, files, bugs, internal tools, or anything behind-the-scenes.
- NEVER use programming terms or show code snippets of any kind.
- DO use math: show formulas and calculations with real numbers when helpful.
- Short answers for simple questions, detailed breakdowns for complex ones.
- You're a helpful guide who knows every secret of the Mars colony — and you tell it like a friend, not a manual.
"""

# Map role string to persona
PERSONAS = {
    'dev': PERSONA_DEV,
    'qa': PERSONA_QA,
    'captain': PERSONA_CAPTAIN,
}

BUG_MODE_PROMPT = """You are PilgrimBot in Bug Analysis mode. You're helping the dev/QA team investigate bugs and features in the Pilgrims Mars colony game.

WHO YOU'RE TALKING TO:
- The user is typically a QA tester or project manager — they describe issues in plain language.
- They do NOT have source code, file paths, database schemas, or config files.
- YOU are the technical expert with full codebase access. Never ask them for code or technical data.
- Items may be bugs OR feature requests — read the type field, don't assume everything is a bug.

RULES:
- BE TECHNICAL. Use file names, function names, line numbers, code snippets — the team needs specifics.
- Show relevant code blocks with ``` when helpful.
- When analyzing a bug: identify root cause, affected files, suggested fix, and QA test steps.
- Cross-reference related bugs by their #ID numbers.
- Be direct and actionable — the team wants to fix things fast.
- If you find the bug is already fixed in the code, say so clearly.

YOUR TOOLS & RESOURCES:
- read_file tool — reads any source file. Use codemap.json paths.
- query_player_data — queries any player's live game state.
- math_registry.json — all game formulas and constants (loaded in your context when needed).
- codemap.json — index of every file with descriptions (loaded in your context when needed).
- Full database access to all tables.
- NEVER say "I don't have access" — you have access to EVERYTHING.
- NEVER ask the user to paste, share, provide, or reference any files, code, or data.
- NEVER mention "file not found" errors, failed reads, or "the system returned errors" to the user.
- NEVER say "I haven't successfully read any files" — that's an internal error, not user-facing info.
- If a file read fails, try a different path from the codemap. You have the FULL codebase.
- If after trying multiple paths you genuinely can't find the relevant code, say something like:
  "Hm, I'm not finding this in my current codebase snapshot — Andy may have written new code that hasn't been synced to PilgrimBot yet. Want me to assign this to him to dig into?"
- If you need something, go get it yourself with your tools.

PERSONALITY:
- Like a senior dev doing a code review — helpful, specific, thorough.
- No fluff. Lead with the answer, then explain.
"""

READ_FILE_TOOL = {
    "name": "read_file",
    "description": "Read a source code file from the Pilgrims codebase. Use exact file paths from the CODEBASE MAP.",
    "input_schema": {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "File path relative to project root, e.g. 'utilities/config_upgrades.py'"
            },
            "search_terms": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional keywords to focus on relevant sections of large files"
            }
        },
        "required": ["file_path"]
    }
}

# Player data tool — extracted to pilgrimbot_data.py for file size
from utilities.pilgrimbot_data import PLAYER_DATA_TOOL, PLAYER_DATA_MAP, query_player_data  # noqa: F401


# === Helpers ===

def _strip_markdown_json(text):
    """Strip markdown code fence from Claude's JSON responses."""
    text = text.strip()
    if text.startswith('```'):
        text = text.split('\n', 1)[-1].rsplit('```', 1)[0].strip()
    return text


# === Database ===

_tables_ensured = False

def ensure_pilgrimbot_table():
    """Create the pilgrimbot conversations table + role column if they don't exist.
    Uses a module-level flag so schema checks only run once per process."""
    global _tables_ensured
    if _tables_ensured:
        return
    _tables_ensured = True
    with db_cursor(commit=True) as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pilgrim.pilgrimbot_conversations (
                id SERIAL PRIMARY KEY,
                user_id INTEGER,
                chat_id UUID NOT NULL,
                title VARCHAR(200),
                role VARCHAR(20) NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_pilgrimbot_user_chat
            ON pilgrim.pilgrimbot_conversations(user_id, chat_id)
        """)
        # Add pilgrimbot_role to users table (dev/qa/captain)
        cur.execute("""
            ALTER TABLE pilgrim.users ADD COLUMN IF NOT EXISTS
            pilgrimbot_role VARCHAR(20) DEFAULT 'captain'
        """)
        # Soft-delete column for hiding conversations
        cur.execute("""
            ALTER TABLE pilgrim.pilgrimbot_conversations ADD COLUMN IF NOT EXISTS
            hidden BOOLEAN DEFAULT FALSE
        """)
        # PilgrimBot call logging — tracks every API call for performance analysis
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pilgrim.pilgrimbot_calls (
                id SERIAL PRIMARY KEY,
                user_id INTEGER,
                chat_id UUID,
                phase VARCHAR(20) NOT NULL,
                model VARCHAR(80),
                prompt_size_chars INTEGER,
                context_loaded JSONB DEFAULT '[]',
                duration_ms INTEGER,
                success BOOLEAN DEFAULT TRUE,
                error_message TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_pilgrimbot_calls_user
            ON pilgrim.pilgrimbot_calls(user_id, created_at DESC)
        """)


def get_user_role(user_id):
    """Get user's PilgrimBot persona role (dev/qa/captain)."""
    with db_cursor() as cur:
        cur.execute("SELECT pilgrimbot_role FROM pilgrim.users WHERE id = %s", (user_id,))
        row = cur.fetchone()
    return (row['pilgrimbot_role'] if row and row['pilgrimbot_role'] else 'captain')


def set_user_role(user_id, role):
    """Set user's PilgrimBot persona role. Returns True on success."""
    if role not in ('dev', 'qa', 'captain'):
        return False
    with db_cursor(commit=True) as cur:
        cur.execute("UPDATE pilgrim.users SET pilgrimbot_role = %s WHERE id = %s", (role, user_id))
    return True


def save_message(user_id, chat_id, role, content, title=None):
    """Save a message to the database."""
    with db_cursor(commit=True) as cur:
        cur.execute("""
            INSERT INTO pilgrim.pilgrimbot_conversations
            (user_id, chat_id, role, content, title)
            VALUES (%s, %s, %s, %s, %s)
        """, (user_id, str(chat_id), role, content, title))


def get_chat_history(user_id, chat_id, limit=MAX_HISTORY):
    """Load conversation history for a specific chat. Uses subquery to fetch only last N rows."""
    with db_cursor() as cur:
        cur.execute("""
            SELECT role, content, created_at FROM (
                SELECT role, content, created_at FROM pilgrim.pilgrimbot_conversations
                WHERE user_id = %s AND chat_id = %s
                ORDER BY created_at DESC
                LIMIT %s
            ) sub ORDER BY created_at ASC
        """, (user_id, str(chat_id), limit))
        rows = cur.fetchall()
    return [{"role": r['role'], "content": r['content'],
             "created_at": r['created_at'].isoformat() if r.get('created_at') else None}
            for r in rows]


def get_user_chats(user_id):
    """List all chat threads for a user, most recent first."""
    ensure_pilgrimbot_table()
    with db_cursor() as cur:
        cur.execute("""
            SELECT chat_id, MAX(title) AS title,
                   MIN(created_at) AS started,
                   MAX(created_at) AS last_message,
                   COUNT(*) AS message_count
            FROM pilgrim.pilgrimbot_conversations
            WHERE user_id = %s AND (hidden IS NOT TRUE)
            GROUP BY chat_id
            ORDER BY MAX(created_at) DESC
            LIMIT 50
        """, (user_id,))
        rows = cur.fetchall()
    return [{
        "chat_id": str(r['chat_id']),
        "title": r['title'] or "Untitled chat",
        "started": r['started'].isoformat() if r.get('started') else None,
        "last_message": r['last_message'].isoformat() if r.get('last_message') else None,
        "message_count": r['message_count'],
    } for r in rows]


def hide_chat(user_id, chat_id):
    """Soft-delete a chat thread by marking all its messages as hidden."""
    with db_cursor(commit=True) as cur:
        cur.execute("""
            UPDATE pilgrim.pilgrimbot_conversations
            SET hidden = TRUE
            WHERE user_id = %s AND chat_id = %s
        """, (user_id, str(chat_id)))
        return cur.rowcount > 0


def generate_title(message):
    """Generate a short title from the first user message.
    For bug mode messages, extract 'Bug #N: Name' instead of verbose context."""
    import re
    bug_match = re.search(r'Bug #(\d+):\s*(.+?)(?:\n|$)', message)
    if bug_match:
        return f"Bug #{bug_match.group(1)}: {bug_match.group(2).strip()}"[:80]
    title = message.strip()[:80]
    if len(message) > 80:
        title = title.rsplit(" ", 1)[0] + "..."
    return title


def log_pilgrimbot_call(user_id, chat_id, phase, model, prompt_size_chars,
                        context_loaded, duration_ms, success=True, error_message=None):
    """Log a PilgrimBot API call for performance tracking."""
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO pilgrim.pilgrimbot_calls
                (user_id, chat_id, phase, model, prompt_size_chars, context_loaded,
                 duration_ms, success, error_message)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (user_id, str(chat_id) if chat_id else None, phase, model,
                  prompt_size_chars, json.dumps(context_loaded),
                  duration_ms, success, error_message))
    except Exception as e:
        logger.warning(f"Failed to log pilgrimbot call: {e}")


# === Local Code Reading ===

def read_local_file(filepath, max_chars=MAX_FILE_CONTENT, search_terms=None):
    """Read a code file from the local codebase.
    For large files, extracts the most relevant section using search_terms."""
    full_path = os.path.join(PROJECT_ROOT, filepath)
    if not os.path.exists(full_path):
        return None
    # Safety: only read code files
    ext = os.path.splitext(filepath)[1].lower()
    if ext not in CODE_EXTS:
        return None
    # Safety: skip sensitive directories
    if any(filepath.startswith(skip) or f"/{skip}" in filepath for skip in SKIP_DIRS):
        return None
    try:
        with open(full_path) as f:
            content = f.read()
    except Exception as e:
        logger.warning(f"Local read error for {filepath}: {e}")
        return None
    if len(content) <= max_chars:
        return content
    # Large file — find the most relevant section
    if search_terms:
        best_pos = _find_best_section(content, search_terms)
        if best_pos is not None:
            start = max(0, best_pos - max_chars // 2)
            end = min(len(content), start + max_chars)
            snippet = content[start:end]
            prefix = "... [earlier code omitted] ...\n\n" if start > 0 else ""
            suffix = "\n\n... [later code omitted] ..." if end < len(content) else ""
            return prefix + snippet + suffix
    # Default: top of file
    return content[:max_chars] + "\n\n... [rest of file omitted] ..."


def _find_best_section(content, search_terms):
    """Find the position in content that has the most search term hits nearby."""
    content_lower = content.lower()
    positions = []
    idx = 0
    while True:
        pos = content_lower.find("\ndef ", idx)
        if pos == -1:
            break
        # Extract the function name
        line_end = content_lower.find("\n", pos + 5)
        func_line = content_lower[pos:line_end] if line_end > pos else ""
        # Check a larger window for this function (the whole function body)
        next_def = content_lower.find("\ndef ", pos + 5)
        window_end = next_def if next_def > 0 else len(content_lower)
        window = content_lower[pos:min(pos + 5000, window_end)]
        # Score: +3 for term in function name, +1 for term in body
        score = 0
        for term in search_terms:
            if term in func_line:
                score += 3
            elif term in window:
                score += 1
        if score > 0:
            positions.append((score, pos))
        idx = pos + 1
    if not positions:
        return None
    positions.sort(key=lambda x: -x[0])
    return positions[0][1]


# Registries + search + dynamic context extracted to pilgrimbot_context.py
from utilities.pilgrimbot_context import (  # noqa: F401
    load_codemap, load_math_registry, load_endgame_registry,
    find_relevant_math, find_relevant_files, load_dynamic_context,
)


# === Bug/Feature Reports (delegates to db_bugs) ===

# Bug creation/filing extracted to pilgrimbot_bugs.py
from utilities.pilgrimbot_bugs import (  # noqa: F401
    create_bug_from_question, create_bug_from_conversation,
    create_bug_from_response, get_reports,
)


# === Chat Handler ===

def _build_codemap_summary(codemap):
    """Build a condensed codebase map for the system prompt (~8KB)."""
    lines = ["CODEBASE MAP (use read_file tool to fetch any file):"]
    for fpath, info in sorted(codemap.items()):
        desc = info.get("description", "")[:80]
        lines.append(f"  {fpath} — {desc}")
    return "\n".join(lines)


def _execute_tool_loop(client_raw, messages, system, tools, max_rounds=4, current_user_id=None, model_override=None, chat_id=None):
    """Run a tool-use loop: let Claude call read_file or query_player_data, execute it, repeat.
    Yields (event_type, data) tuples. Final yield is ('result', text).
    Deduplicates file reads and forces a final answer when rounds run out."""
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


def _plan_context(message, history, bug_mode, user_id=None):
    """Phase 2: Ask Haiku what context is needed to answer this question.
    Returns a dict of context tags like {'math': ['shard_generation'], 'endgame': True, 'code': ['db_expeditions.py'], 'player_data': ['balance', 'shard_generation']}."""
    # Build a lightweight prompt for the planner
    recent = ""
    for h in (history or [])[-4:]:
        recent += f"{h['role']}: {h['content'][:200]}\n"

    planner_prompt = f"""Given this PilgrimBot question, what context do I need to answer it well?
{"This is a BUG INVESTIGATION — code context is important." if bug_mode else ""}

Recent conversation:
{recent}

Current question: {message}

Return ONLY a JSON object with these optional keys (omit keys you don't need):
- "math": list of formula keywords to look up (e.g. ["shard_generation", "expedition_payout"]). Only if the question involves calculations, rates, formulas, or numbers.
- "endgame": true if the question is about Signal, Origin sites, decoders, ledger, founders, blockchain/tx, or the endgame system.
- "code": list of specific filenames to read (e.g. ["utilities/db_expeditions.py"]). Only if the question requires looking at actual code to answer.
- "player_data": list of data categories to query (e.g. ["balance", "shard_generation", "upgrades"]). Only if the question is about THIS user's specific data.
- "bugs": true if the question mentions bugs, issues, broken things, or the tracker.
- "brainstorm": list of brainstorm page keys (e.g. ["signal", "tech-tree"]). Only if asking about design discussions.

Be MINIMAL. Most simple questions need NO context at all. A greeting needs nothing. "How do expeditions work?" needs maybe one code file. Only request what's truly needed."""

    try:
        client = create_client(model=MODEL)
        _start = _time.time()
        resp = client.client.messages.create(
            model=MODEL, max_tokens=300, temperature=0,
            messages=[{"role": "user", "content": planner_prompt}]
        )
        _ms = int((_time.time() - _start) * 1000)
        log_api_usage(
            model=MODEL, usage=resp.usage, feature='pilgrimbot_plan_context',
            duration_ms=_ms, user_id=str(user_id) if user_id else "system:galactica_pilgrimbot",
        )
        text = _strip_markdown_json(resp.content[0].text)
        plan = json.loads(text)
        if not isinstance(plan, dict):
            logger.warning(f"Planner returned non-dict: {type(plan)}, using fallback")
            return _plan_context_fallback(message), _ms
        logger.info(f"Context plan ({_ms}ms): {json.dumps(plan)}")
        return plan, _ms
    except Exception as e:
        logger.warning(f"Context planner failed ({e}), using keyword fallback")
        return _plan_context_fallback(message), 0


def _plan_context_fallback(message):
    """Fast keyword-based fallback if the Haiku planner fails."""
    msg_lower = message.lower()
    plan = {}
    math_triggers = ['calculate', 'formula', 'math', 'how is my', 'how does my',
                     'break down', 'show the math', 'add up', 'multiplier',
                     'effective rate', 'generation rate', 'how much', 'per hour']
    if any(t in msg_lower for t in math_triggers):
        plan['math'] = []  # empty = use find_relevant_math
        plan['player_data'] = ['balance', 'shard_generation']

    endgame_triggers = ['signal', 'origin', 'node', 'decoder', 'decode', 'ledger',
                        'endgame', 'end game', 'founder', 'claim', 'hitchhiker',
                        'lost signal', 'beagle', 'schiaparelli', 'mars-3',
                        '14 sites', 'origin site', 'three act', 'world 2']
    if any(t in msg_lower for t in endgame_triggers):
        plan['endgame'] = True

    bug_triggers = ['bug', 'issue', 'broken', 'fix', 'reported', 'tracker']
    if any(t in msg_lower for t in bug_triggers):
        plan['bugs'] = True
    return plan


def _load_surgical_context(plan, message, user_id, user_role, bug_mode):
    """Phase 2b: Load ONLY the context pieces the planner requested.
    Returns (system_addition, context_loaded_list) where context_loaded_list tracks what was injected."""
    extra = ""
    loaded = []
    show_code = user_role in ('dev', 'qa') or bug_mode

    # Math registry — surgical lookup
    if 'math' in plan:
        math_keywords = plan['math'] if isinstance(plan['math'], list) else []
        if math_keywords:
            # Planner gave specific keywords — build a targeted query
            query = ' '.join(math_keywords)
            relevant_math = find_relevant_math(query)
        else:
            relevant_math = find_relevant_math(message)
        if relevant_math and relevant_math.get('formulas'):
            math_json = json.dumps(relevant_math)
            extra += f"\n\nMATH REGISTRY (authoritative — use EXACT formulas):\n{math_json}"
            loaded.append(f"math:{len(relevant_math['formulas'])}formulas:{len(math_json)}chars")
        else:
            # No match — still don't dump the full 48KB. Give just constants.
            registry = load_math_registry()
            if registry and 'constants' in registry:
                const_json = json.dumps({'constants': registry['constants']})
                extra += f"\n\nMATH CONSTANTS (no matching formulas found — use these base values):\n{const_json}"
                loaded.append(f"math:constants_only:{len(const_json)}chars")

    # Endgame registry
    if plan.get('endgame'):
        endgame = load_endgame_registry()
        if endgame:
            eg_json = json.dumps(endgame)
            extra += f"\n\nENDGAME REGISTRY (authoritative reference):\n{eg_json}"
            loaded.append(f"endgame:{len(eg_json)}chars")

    # Code files — only if planner requested specific files
    code_files = plan.get('code') if isinstance(plan.get('code'), list) else []
    if code_files:
        codemap = load_codemap()
        for fpath in code_files[:4]:  # cap at 4 files
            content = read_local_file(fpath)
            if content:
                if show_code:
                    extra += f"\n\n--- {fpath} ---\n{content}"
                else:
                    extra += f"\n\nINTERNAL REFERENCE (never show to user):\n--- {fpath} ---\n{content}"
                loaded.append(f"code:{fpath}:{len(content)}chars")

    # Player data — pre-query specific categories
    player_cats = plan.get('player_data') if isinstance(plan.get('player_data'), list) else []
    if player_cats:
        for category in player_cats[:5]:
            try:
                data = query_player_data(category, user_id)
                extra += f"\n\nPLAYER DATA ({category}):\n{data}"
                loaded.append(f"player:{category}")
            except Exception as e:
                logger.warning(f"Player data query {category} failed: {e}")

    # Bug tracker context — load full bug data when a specific bug is referenced
    if plan.get('bugs') or bug_mode:
        import re as _re
        bug_match = _re.search(r'#(\d+)', message)
        if bug_match:
            try:
                from utilities.db_bugs import get_bug_by_id, get_bug_comments, get_bug_history
                bug_id = int(bug_match.group(1))
                bug = get_bug_by_id(bug_id)
                if bug:
                    extra += f"\n\n--- FULL BUG #{bug_id} DATA ---\n"
                    for key in ['name', 'description', 'status', 'priority', 'bug_type',
                                'qa_notes', 'dev_notes', 'assigned_to', 'qa_approved',
                                'screenshot_urls', 'created_at', 'updated_at']:
                        val = bug.get(key)
                        if val:
                            extra += f"{key}: {val}\n"
                    # Load comments
                    comments = get_bug_comments(bug_id)
                    if comments:
                        extra += f"\n--- Bug #{bug_id} Comments ({len(comments)}) ---\n"
                        for c in comments[-15:]:
                            extra += f"[{c.get('author', 'anon')}]: {str(c.get('body', ''))[:300]}\n"
                    # Load history
                    history_entries = get_bug_history(bug_id)
                    if history_entries:
                        extra += f"\n--- Bug #{bug_id} History ({len(history_entries)}) ---\n"
                        for h in history_entries[-10:]:
                            extra += f"{h.get('changed_at', '')}: {h.get('field', '')} → {h.get('new_value', '')}\n"
                    loaded.append(f"bug:{bug_id}:full")
            except Exception as e:
                logger.warning(f"Failed to load full bug data: {e}")
        # Also load general bug tracker stats
        dynamic = load_dynamic_context(message)
        if dynamic:
            label = "LIVE DATA" if show_code else "INTERNAL DATA (summarize in plain English)"
            extra += f"\n\n{label}:{dynamic}"
            loaded.append(f"bugs:{len(dynamic)}chars")

    # Brainstorm context
    brainstorm_keys = plan.get('brainstorm') if isinstance(plan.get('brainstorm'), list) else []
    if brainstorm_keys:
        try:
            from utilities.db_brainstorm import get_comments_for_page
            for page_key in brainstorm_keys[:3]:
                comments = get_comments_for_page(page_key)
                if comments:
                    extra += f"\n--- Brainstorm: {page_key} ({len(comments)} comments) ---\n"
                    for c in comments[-10:]:
                        extra += f"[{c.get('author_name', 'anon')}]: {str(c.get('comment_text', ''))[:200]}\n"
                    loaded.append(f"brainstorm:{page_key}")
        except Exception as e:
            logger.warning(f"Brainstorm context failed: {e}")

    return extra, loaded


# SSE padding to force GCP App Engine TCP buffer flush (~2KB comment)
_SSE_PAD = ": " + "." * 2048 + "\n\n"

def _sse(data_dict):
    """Build an SSE event with padding to force immediate TCP delivery on GCP."""
    return f"data: {json.dumps(data_dict)}\n\n" + _SSE_PAD


def handle_chat_streaming(message, chat_id, user_id, history=None, bug_mode=False, action_context="", user_role="captain", image_url=None):
    """Stream a PilgrimBot response. Two-phase: fast response, then surgical deep dive."""
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

        # Phase 1: Quick Haiku call with just persona + knowledge (~10KB)
        phase1_system = system_base + (
            "\n\nIMPORTANT — HOW THIS WORKS:\n"
            "This is your quick first response. After this, the system automatically loads the exact "
            "codebase files and data for a deep-dive follow-up. You do NOT need anything from the user.\n\n"
            "WHO YOU'RE TALKING TO:\n"
            "The user is typically a QA tester or project manager. They do NOT have code, file paths, "
            "or database schemas. They describe bugs/features in plain language. YOU are the one with "
            "codebase access — never ask them for code, files, or technical data.\n\n"
            "YOUR RESOURCES (available in the deep-dive that follows automatically):\n"
            "- codemap.json — index of every file in the codebase with descriptions\n"
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
            "If something isn't loaded yet, say 'pulling that up now' — never expose internal errors."
        )

        from utilities.pilgrimbot_bugs import CREATE_BUG_TOOL
        active_tools = [PLAYER_DATA_TOOL, CREATE_BUG_TOOL]

        yield _sse({'type': 'status', 'message': 'Thinking...'})

        phase1_start = _time.time()
        client = create_client(model=MODEL)
        full_response = ""
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
        plan_start = _time.time()
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

        # Always give file tools + codemap in bug mode — PilgrimBot should always be able to read code
        deep_tools = [PLAYER_DATA_TOOL, CREATE_BUG_TOOL]
        if bug_mode:
            deep_tools.append(READ_FILE_TOOL)
            codemap = load_codemap()
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
