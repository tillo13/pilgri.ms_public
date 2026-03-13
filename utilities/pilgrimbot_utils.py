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

from utilities.claude_utils import create_client, CLAUDE_MODELS
from utilities.postgres_utils import db_cursor

logger = logging.getLogger("pilgrimbot")

# === Config ===

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL = CLAUDE_MODELS.get("haiku-4.5", "claude-haiku-4-5-20251001")
MAX_HISTORY = 20  # messages (10 exchanges)
MAX_FILE_CONTENT = 12000  # chars per file section to include in context

# Only read code files (no secrets, no configs, no data)
CODE_EXTS = {".py", ".js", ".css", ".html"}
SKIP_DIRS = {"venv_galactica", "archive", "antiquated_code", ".git", "__pycache__",
             "node_modules", ".claude", "testing", "tools/credentials"}

SYSTEM_PROMPT = """You are PilgrimBot, a friendly assistant who explains how the Pilgrims Mars colony game works.

IMPORTANT RULES:
- The person asking is smart but NOT a programmer. They understand math, logic, and game mechanics perfectly.
- NEVER use programming terms: "function", "variable", "returns", "line 42", "parameter", "array", "object", "string", "boolean", "loop", "class".
- DO use math freely: formulas, multiplication, percentages, addition — math is universal. Show your work with actual numbers.
- When someone asks about a calculation, SHOW THE ACTUAL MATH step by step with real numbers from the code.
- Example: "Your Effective Rate = (Base Total × Power Multiplier × Tech Multiplier) + Mining Drone. So: (43 × 1.5 × 1.2) + 9 = 86.4/hr"
- You have access to the game's source code. Explain the LOGIC and MATH, not the code.
- NEVER reference filenames, function names, or code structure. Say "the shard generation system" not "calculate_accumulated_income() in infrastructure_utils.py".
- Use ``` blocks ONLY for math formulas, NEVER for code snippets.

WHEN YOU CAN'T ANSWER:
- If the question is about something you can't find in the code, say so honestly.
- Tell the user: "I wasn't able to find a clear answer in the codebase. Would you like me to flag this for the dev team to investigate?"
- NEVER auto-report or auto-file anything. ONLY offer to report, and wait for the user to confirm.
- NEVER mention Google Sheets, CSV files, bug trackers, or internal tools.
- NEVER leave the user at a dead end. Always either answer or offer to get help.

PERSONALITY:
- Friendly, patient, thorough — like a game designer explaining their own creation.
- You genuinely enjoy talking about how the game works.
- Short answers for simple questions, detailed breakdowns for complex ones.
"""


# === Database ===

def ensure_pilgrimbot_table():
    """Create the pilgrimbot conversations table if it doesn't exist."""
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


def save_message(user_id, chat_id, role, content, title=None):
    """Save a message to the database."""
    with db_cursor(commit=True) as cur:
        cur.execute("""
            INSERT INTO pilgrim.pilgrimbot_conversations
            (user_id, chat_id, role, content, title)
            VALUES (%s, %s, %s, %s, %s)
        """, (user_id, str(chat_id), role, content, title))


def get_chat_history(user_id, chat_id, limit=MAX_HISTORY):
    """Load conversation history for a specific chat."""
    with db_cursor() as cur:
        cur.execute("""
            SELECT role, content, created_at FROM pilgrim.pilgrimbot_conversations
            WHERE user_id = %s AND chat_id = %s
            ORDER BY created_at ASC
        """, (user_id, str(chat_id)))
        rows = cur.fetchall()
    # Return last N messages
    return [{"role": r['role'], "content": r['content'],
             "created_at": r['created_at'].isoformat() if r.get('created_at') else None}
            for r in rows[-limit:]]


def get_user_chats(user_id):
    """List all chat threads for a user, most recent first."""
    ensure_pilgrimbot_table()
    with db_cursor() as cur:
        cur.execute("""
            SELECT chat_id, title,
                   MIN(created_at) AS started,
                   MAX(created_at) AS last_message,
                   COUNT(*) AS message_count
            FROM pilgrim.pilgrimbot_conversations
            WHERE user_id = %s
            GROUP BY chat_id, title
            ORDER BY MAX(created_at) DESC
            LIMIT 50
        """, (user_id,))
        rows = cur.fetchall()
    return [{
        "chat_id": str(r['chat_id']),
        "title": r['title'] or "New conversation",
        "started": r['started'].isoformat() if r.get('started') else None,
        "last_message": r['last_message'].isoformat() if r.get('last_message') else None,
        "message_count": r['message_count'],
    } for r in rows]


def generate_title(message):
    """Generate a short title from the first user message."""
    title = message.strip()[:80]
    if len(message) > 80:
        title = title.rsplit(" ", 1)[0] + "..."
    return title


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


def load_codemap():
    """Load codemap.json from the local project."""
    local_path = os.path.join(PROJECT_ROOT, "codemap.json")
    if os.path.exists(local_path):
        with open(local_path) as f:
            return json.load(f)
    return {}


def find_relevant_files(question, max_files=4):
    """Use codemap to find the most relevant files for a question."""
    codemap = load_codemap()
    if not codemap:
        return []

    # Score each file by keyword matches against its description + exports
    stopwords = {"have", "been", "this", "that", "with", "from", "they", "what",
                 "does", "will", "would", "could", "should", "about", "there",
                 "their", "than", "then", "also", "just", "some", "other", "into",
                 "over", "after", "before", "many", "much", "most", "more", "very",
                 "like", "know", "think", "make", "made", "come", "came", "gets",
                 "going", "been", "being", "were", "each", "which", "when", "where",
                 "tried", "figure", "couple", "months", "times", "past", "never"}
    words = set(w.lower().strip("?.,!()\"'") for w in question.split()
                if len(w) > 3 and w.lower().strip("?.,!()\"'") not in stopwords)
    scored = []
    for filepath, info in codemap.items():
        # Build searchable text from description + exports
        text_parts = [filepath.lower()]
        if "description" in info:
            text_parts.append(info["description"].lower())
        if "exports" in info:
            text_parts.append(" ".join(info["exports"]).lower())
        if "keywords" in info:
            text_parts.append(info["keywords"].lower())
        searchable = " ".join(text_parts)
        # Count keyword hits
        score = sum(1 for w in words if w in searchable)
        if score > 0:
            scored.append((score, filepath))

    scored.sort(key=lambda x: -x[0])
    paths = [path for _, path in scored]
    # Prefer Python utilities over JS/templates for answer quality
    py_utils = [p for p in paths if p.startswith("utilities/") and p.endswith(".py")]
    others = [p for p in paths if p not in set(py_utils)]
    result = py_utils[:2] + others[:1]  # 2 utility files + 1 other
    return result[:max_files]


# === Bug Creation Fallback ===

def create_bug_from_question(question, user_display_name="PilgrimBot User", description=None):
    """Create a bug/idea via pb tool from PilgrimBot chat."""
    try:
        title = f"PilgrimBot: {question[:80]}"
        if not description:
            description = f"Question: {question}"
        description = (
            f"{description}\n\n"
            f"Submitted by: {user_display_name}\n"
            f"Via: PilgrimBot chat\n"
            f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M PST')}"
        )
        # Use pb idea to create in the sheet
        result = subprocess.run(
            ["python3", "-m", "tools.pb", "idea", title, description],
            capture_output=True, text=True, timeout=15,
            cwd=PROJECT_ROOT
        )
        if result.returncode == 0:
            logger.info(f"Created bug from PilgrimBot: {title}")
            return True
        else:
            logger.warning(f"pb idea failed: {result.stderr}")
            return False
    except Exception as e:
        logger.warning(f"Bug creation failed: {e}")
        return False


# === Chat Handler ===

def handle_chat_streaming(message, chat_id, user_id, history=None):
    """Stream a PilgrimBot response. Yields SSE-formatted JSON chunks."""
    # Ensure table exists (idempotent)
    ensure_pilgrimbot_table()

    # Generate or validate chat_id
    if not chat_id:
        chat_id = str(uuid.uuid4())

    # Load history from DB if not provided
    if history is None:
        history = get_chat_history(user_id, chat_id)

    # Save user message
    title = generate_title(message) if not history else None
    save_message(user_id, chat_id, "user", message, title=title)

    # Extract search terms from message for smart file reading
    msg_stopwords = {"have", "been", "this", "that", "with", "from", "what", "does",
                     "will", "would", "could", "about", "there", "their", "also",
                     "just", "some", "into", "over", "after", "before", "many",
                     "like", "know", "tried", "figure", "couple", "months", "times",
                     "past", "never", "gets"}
    search_terms = [w.lower().strip("?.,!()\"'") for w in message.split()
                    if len(w) > 3 and w.lower().strip("?.,!()\"'") not in msg_stopwords]

    # Find and read relevant code files from local codebase
    codemap = load_codemap()
    relevant = find_relevant_files(message)
    code_context = ""
    for fpath in relevant:
        # Add codemap export names as extra search terms
        extra_terms = search_terms[:]
        if fpath in codemap and "exports" in codemap[fpath]:
            for export in codemap[fpath]["exports"]:
                # Extract function name from "func_name — description"
                fname = export.split(" —")[0].split(" ")[0].replace("class ", "")
                extra_terms.append(fname.lower())
        content = read_local_file(fpath, search_terms=extra_terms)
        if content:
            code_context += f"\n--- {fpath} ---\n{content}\n"

    # Build messages for Claude
    system = SYSTEM_PROMPT
    if code_context:
        system += f"\n\nRELEVANT CODE CONTEXT:\n{code_context}"

    messages = []
    for h in history[-MAX_HISTORY:]:
        messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": message})

    # Stream response
    try:
        client = create_client(model=MODEL)
        full_response = ""

        yield f"data: {json.dumps({'type': 'start', 'chat_id': chat_id})}\n\n"

        for event in client.stream_chat(messages, system=system, max_tokens=1500, temperature=0.7):
            if event.get("type") == "delta" and "text" in event:
                text = event["text"]
                full_response += text
                yield f"data: {json.dumps({'type': 'delta', 'text': text})}\n\n"
            elif event.get("type") == "stop":
                break

        # Save assistant response
        save_message(user_id, chat_id, "assistant", full_response)

        # Check if PilgrimBot indicated it couldn't answer — signal frontend
        cant_answer_signals = [
            "wasn't able to find",
            "couldn't find a clear answer",
            "flag this for the dev team",
            "like me to flag",
            "want me to report",
        ]
        cant_answer = any(signal in full_response.lower() for signal in cant_answer_signals)

        yield f"data: {json.dumps({'type': 'stop', 'chat_id': chat_id, 'cant_answer': cant_answer})}\n\n"

    except Exception as e:
        logger.error(f"PilgrimBot stream error: {e}")
        yield f"data: {json.dumps({'type': 'error', 'message': 'Something went wrong. Try again?'})}\n\n"
