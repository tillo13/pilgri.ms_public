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
CODE_EXTS = {".py", ".js", ".css", ".html", ".md"}
SKIP_DIRS = {"venv_galactica", "archive", "antiquated_code", ".git", "__pycache__",
             "node_modules", ".claude", "testing", "tools/credentials"}

# === Role-based personas ===
# pilgrimbot_role column in users table: 'dev', 'qa', or 'captain' (default)

PERSONA_BASE = """You are PilgrimBot, a friendly assistant for the Pilgrims Mars colony game.

WHEN YOU CAN'T ANSWER:
- Say so honestly and offer to flag it for the dev team to investigate.
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
- If the math doesn't add up or you find a discrepancy, say so honestly and offer to file a bug. Do NOT fudge numbers to make them fit.
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
"""

PERSONA_QA = PERSONA_BASE + """
YOU ARE TALKING TO A QA TESTER. They're smart but NOT a programmer.
- NEVER use programming terms: "function", "variable", "returns", "parameter", "array", "object", "string", "boolean", "loop", "class".
- NEVER show code snippets, Python/JavaScript/SQL, import statements, or anything that looks like programming.
- NEVER reference filenames, function names, or code structure. Say "the shard generation system" not "calculate_accumulated_income() in infrastructure_utils.py".
- DO use math freely: formulas, multiplication, percentages — math is universal. Show your work with actual numbers.
- Example: "Your Effective Rate = (Base Total × Power Multiplier × Tech Multiplier) + Mining Drone. So: (43 × 1.5 × 1.2) + 9 = 86.4/hr"
- When you read source code internally, translate it to PLAIN ENGLISH game mechanics. They should never know you're reading code.
- Use ``` blocks ONLY for math formulas, NEVER for code.
- You can mention bug numbers and what they're about, just not the technical implementation.
- Friendly, patient, thorough — like a game designer explaining their own creation.
"""

PERSONA_CAPTAIN = PERSONA_BASE + """
YOU ARE TALKING TO A PLAYER (Captain). They just want to understand the game.
- Explain everything as game mechanics — upgrades, costs, timers, formulas.
- NEVER reference code, files, bugs, internal tools, or anything behind-the-scenes.
- NEVER use programming terms or show code snippets of any kind.
- DO use math: show formulas and calculations with real numbers when helpful.
- Be warm and enthusiastic — you love this game and want them to succeed.
- Short answers for simple questions, detailed breakdowns for complex ones.
- You're like a helpful guide who knows every secret of the Mars colony.
"""

# Map role string to persona
PERSONAS = {
    'dev': PERSONA_DEV,
    'qa': PERSONA_QA,
    'captain': PERSONA_CAPTAIN,
}

BUG_MODE_PROMPT = """You are PilgrimBot in Bug Analysis mode. You're helping the dev/QA team investigate and fix bugs in the Pilgrims Mars colony game.

RULES FOR BUG ANALYSIS:
- BE TECHNICAL. Use file names, function names, line numbers, code snippets — the team needs specifics.
- Show relevant code blocks with ``` when helpful.
- When analyzing a bug: identify root cause, affected files, suggested fix, and QA test steps.
- Cross-reference related bugs by their #ID numbers.
- Be direct and actionable — the team wants to fix things fast.
- If you find the bug is already fixed in the code, say so clearly.
- Structure responses with clear sections: Root Cause, Affected Code, Fix, Test Steps.

FILE ACCESS:
- You have a read_file tool. The CODEBASE MAP below lists every file — use exact paths from it.
- THINK FIRST about which 2-3 files are most likely to contain the root cause, then read them all at once.
- NEVER read the same file twice. NEVER say "I don't have access" or ask the user to share files.
- After reading files, give your COMPLETE analysis. Do NOT say "let me search more" — answer with what you have.

You have access to LIVE DATA including bug tracker status and brainstorm discussions.
Reference bug IDs and statuses when relevant.

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


# === Database ===

def ensure_pilgrimbot_table():
    """Create the pilgrimbot conversations table + role column if they don't exist."""
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


_math_registry_cache = None
_endgame_registry_cache = None

def load_math_registry():
    """Load math_registry.json — authoritative formula reference for math questions."""
    global _math_registry_cache
    if _math_registry_cache is not None:
        return _math_registry_cache
    local_path = os.path.join(PROJECT_ROOT, "math_registry.json")
    if os.path.exists(local_path):
        with open(local_path) as f:
            _math_registry_cache = json.load(f)
            return _math_registry_cache
    return {}


def load_endgame_registry():
    """Load endgame_registry.json — authoritative reference for Signal/Origin/Decoder endgame system."""
    global _endgame_registry_cache
    if _endgame_registry_cache is not None:
        return _endgame_registry_cache
    local_path = os.path.join(PROJECT_ROOT, "endgame_registry.json")
    if os.path.exists(local_path):
        with open(local_path) as f:
            _endgame_registry_cache = json.load(f)
            return _endgame_registry_cache
    return {}


def find_relevant_math(message, max_formulas=5):
    """Keyword-match the question to only the relevant math_registry sections.
    Returns a slim dict with only matching formulas + referenced constants.
    Same pattern as codemap file matching — avoids dumping 48KB into context."""
    registry = load_math_registry()
    if not registry:
        return None

    msg_lower = message.lower()
    words = set(w.strip("?.,!()\"'") for w in msg_lower.split() if len(w) > 2)

    # Score each formula by keyword overlap with name + description + key
    scored = []
    for key, formula in registry.get('formulas', {}).items():
        searchable = f"{key} {formula.get('name', '')} {formula.get('description', '')}".lower()
        # Split formula key parts: "shard_generation.effective_rate" -> ["shard", "generation", "effective", "rate"]
        key_words = set(key.replace('.', ' ').replace('_', ' ').split())
        score = 0
        for w in words:
            if w in searchable:
                score += 2
            # Partial match on key words (e.g. "shards" matches "shard")
            for kw in key_words:
                if w.startswith(kw[:4]) or kw.startswith(w[:4]):
                    score += 1
        if score > 0:
            scored.append((score, key, formula))

    if not scored:
        # No match — return just constants as a lightweight fallback
        return {'constants': registry.get('constants', {})}

    scored.sort(key=lambda x: -x[0])
    top = scored[:max_formulas]

    # Build slim result with only matched formulas
    result = {'formulas': {}}
    for _, key, formula in top:
        result['formulas'][key] = formula

    # Include only constants referenced by matched formulas
    all_text = json.dumps(result['formulas']).upper()
    relevant_constants = {}
    for cname, cval in registry.get('constants', {}).items():
        if cname.upper() in all_text:
            relevant_constants[cname] = cval
    if relevant_constants:
        result['constants'] = relevant_constants

    # Include tables if formula references them
    for table_key in ['terrain_modifiers', 'vehicle_stats', 'payout_multipliers', 'stat_divisor_reference']:
        if table_key.upper().replace('_', '') in all_text.replace('_', '') or table_key in all_text.lower():
            if table_key in registry:
                result[table_key] = registry[table_key]

    return result


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


# === Dynamic Context (brainstorm + bugs) ===

def load_dynamic_context(message):
    """Load extra context from DB when message mentions specific topics."""
    msg_lower = message.lower()
    extra = ""

    # Brainstorm discussions
    BRAINSTORM_KEYWORDS = {
        'signal': 'signal', 'tech tree': 'tech-tree', 'progression': 'progression',
        'trail': 'trail-network', 'icon': 'icon-redesign', 'colony redesign': 'icon-redesign',
        'aria meeting': 'aria-meetings', 'bonds': 'aria-meetings',
        'sv economy': 'sv-economy', 'science value': 'sv-economy',
    }
    matched_pages = set()
    for keyword, page_key in BRAINSTORM_KEYWORDS.items():
        if keyword in msg_lower:
            matched_pages.add(page_key)

    if matched_pages:
        try:
            from utilities.db_brainstorm import get_comments_for_page
            for page_key in matched_pages:
                comments = get_comments_for_page(page_key)
                if comments:
                    extra += f"\n--- Brainstorm: {page_key} ({len(comments)} comments) ---\n"
                    for c in comments[-15:]:
                        extra += f"[{c.get('author_name', 'anon')}]: {str(c.get('comment_text', ''))[:200]}\n"
        except Exception as e:
            logger.warning(f"Failed to load brainstorm context: {e}")

    # Speed test — when Luke asks "is it slow?" or "are you deploying?"
    speed_keywords = ['slow', 'speed', 'deploying', 'updating', 'laggy', 'loading',
                      'performance', 'broken site', 'site down', 'page load']
    if any(k in msg_lower for k in speed_keywords):
        try:
            with db_cursor() as cur:
                cur.execute("""SELECT results, slowest_page, slowest_time, all_ok, tested_at
                               FROM speed_test_runs ORDER BY tested_at DESC LIMIT 1""")
                row = cur.fetchone()
            if row:
                age_mins = (datetime.now() - row['tested_at']).total_seconds() / 60
                extra += f"\n--- Site Speed (last test: {int(age_mins)} min ago) ---\n"
                extra += f"Slowest: {row['slowest_page']} at {row['slowest_time']}s | All OK: {row['all_ok']}\n"
                if isinstance(row['results'], str):
                    pages = json.loads(row['results'])
                else:
                    pages = row['results']
                for p in pages:
                    extra += f"  {p['page']}: {p['time_s']}s {'OK' if p['status'] == 'ok' else p['status']}\n"
                if age_mins > 60:
                    extra += "(Results are over an hour old. Suggest running a new test at /admin/speed)\n"
            else:
                extra += "\n--- Site Speed ---\nNo speed tests have been run yet. Run one at /admin/speed\n"
        except Exception as e:
            logger.warning(f"Failed to load speed context: {e}")

    # Bug tracker
    bug_keywords = ['bug', 'issue', 'broken', 'fix', 'reported', 'tracker']
    if any(k in msg_lower for k in bug_keywords):
        try:
            from utilities.db_bugs import get_bug_stats, search_bugs
            stats = get_bug_stats()
            if stats:
                extra += f"\n--- Bug Tracker ---\n"
                extra += (f"Active: {stats.get('active_count', 0)}, "
                         f"In Review: {stats.get('awaiting_qa', 0)}, "
                         f"P1: {stats.get('p1_count', 0)}, P2: {stats.get('p2_count', 0)}, "
                         f"Completed: {stats.get('completed_count', 0)}\n")
            # Search for specific bugs mentioned
            words = [w for w in msg_lower.split() if len(w) > 4
                     and w not in {'about', 'these', 'there', 'where', 'which', 'being', 'broken'}]
            if words:
                results = search_bugs(' '.join(words[:2]))
                if results:
                    extra += "Matching bugs:\n"
                    for b in results[:5]:
                        extra += f"  #{b['id']}: {b['name']} ({b['status']}/{b['priority']})\n"
        except Exception as e:
            logger.warning(f"Failed to load bug context: {e}")

    return extra


# === Bug/Feature Reports (delegates to db_bugs) ===

def create_bug_from_question(question, user_display_name="PilgrimBot User", description=None):
    """Save a bug/feature report via the unified bug tracker."""
    try:
        from utilities.db_bugs import create_bug
        title = question[:200]
        bug = create_bug(name=title, description=description or '',
                         source='PilgrimBot', type='Bug')
        if bug:
            logger.info(f"PilgrimBot report saved: {title[:60]}")
            return True
        return False
    except Exception as e:
        logger.warning(f"Report save failed: {e}")
        return False


def _cross_link_related_bugs(bug_id, bug_name, affected_areas):
    """Background task: find related bugs and cross-link with comments."""
    try:
        from utilities.db_bugs import add_bug_comment
        related = _find_related_bugs(bug_id, bug_name, affected_areas)
        if not related:
            logger.info(f"Bug #{bug_id}: no related bugs found")
            return
        # Comment on the new bug listing related ones
        rel_lines = []
        for r in related:
            reason = r.get('_relation', '')
            line = f"- **#{r['id']}:** {r['name']} ({r['status']}/{r['priority']})"
            if reason:
                line += f" — {reason}"
            rel_lines.append(line)
        add_bug_comment(bug_id, 'PilgrimBot',
            f"**Related bugs found ({len(related)}):**\n" + "\n".join(rel_lines) +
            "\n\nConsider checking if any are duplicates or can be fixed together.")
        # Comment on each related bug pointing back
        for r in related:
            add_bug_comment(r['id'], 'PilgrimBot',
                f"**Possibly related:** New bug [#{bug_id}: {bug_name}] "
                f"was just created. May overlap with this bug.")
        logger.info(f"Bug #{bug_id}: cross-linked with {len(related)} related bugs")
    except Exception as e:
        logger.error(f"Bug #{bug_id} cross-link failed: {e}")


def _find_related_bugs(new_bug_id, title, affected_areas=""):
    """Find bugs related to a newly created one via keyword search.
    Searches title words + affected area words against all active bugs.
    Returns up to 5 related bugs (excludes the new bug itself)."""
    from utilities.db_bugs import search_bugs
    stopwords = {'the', 'and', 'for', 'not', 'but', 'with', 'from', 'that', 'this',
                 'does', 'doesn', 'have', 'has', 'are', 'was', 'were', 'been', 'being',
                 'both', 'give', 'gives', 'when', 'after', 'before', 'should', 'could',
                 'page', 'button', 'click', 'show', 'display'}
    # Extract meaningful words from title + affected areas
    raw = f"{title} {affected_areas}".lower()
    words = [w.strip(".,!?()\"'#") for w in raw.split()
             if len(w.strip(".,!?()\"'#")) > 3 and w.strip(".,!?()\"'#") not in stopwords]
    # Dedupe while preserving order
    seen = set()
    unique_words = []
    for w in words:
        if w not in seen:
            seen.add(w)
            unique_words.append(w)

    # Search each keyword, score by hit count
    bug_scores = {}  # bug_id -> {bug_data, score}
    for word in unique_words[:6]:
        results = search_bugs(word)
        for b in results:
            if b['id'] == new_bug_id:
                continue
            if b['id'] in bug_scores:
                bug_scores[b['id']]['score'] += 1
            else:
                bug_scores[b['id']] = {'bug': b, 'score': 1}

    # Sort by score (most keyword overlap first)
    ranked = sorted(bug_scores.values(), key=lambda x: -x['score'])
    candidates = [item['bug'] for item in ranked[:8]]
    if not candidates:
        return []

    # Haiku pass: let AI rank relevance and explain connections
    try:
        client = create_client(model=MODEL)
        bug_list = "\n".join(
            f"#{b['id']}: {b['name']} ({b['status']}/{b['priority']}) — {(b.get('description') or '')[:150]}"
            for b in candidates
        )
        _s = _time.time()
        resp = client.client.messages.create(
            model=MODEL, max_tokens=500, temperature=0,
            system="You identify related software bugs. Return ONLY valid JSON, no markdown.",
            messages=[{"role": "user", "content": f"""New bug: "{title}"
Affected areas: {affected_areas}

Candidate related bugs:
{bug_list}

Return JSON array of the TRULY related bugs (same system, similar symptom, or likely same root cause).
Exclude bugs that just happen to share a common word but are about different issues.
Format: [{{"id": 123, "reason": "one sentence why it's related"}}]
Return empty array [] if none are truly related."""}]
        )
        log_api_usage(model=MODEL, usage=resp.usage, feature='pilgrimbot_related_bugs', duration_ms=int((_time.time() - _s) * 1000))
        text = resp.content[0].text.strip()
        if text.startswith('```'):
            text = text.split('\n', 1)[1].rsplit('```', 1)[0].strip()
        ai_picks = json.loads(text)
        # Filter candidates to only AI-approved ones, preserving bug data
        ai_ids = {p['id'] for p in ai_picks}
        ai_reasons = {p['id']: p.get('reason', '') for p in ai_picks}
        result = []
        for b in candidates:
            if b['id'] in ai_ids:
                b['_relation'] = ai_reasons.get(b['id'], '')
                result.append(b)
        return result[:5]
    except Exception as e:
        logger.warning(f"Haiku related-bug ranking failed, using SQL results: {e}")
        return candidates[:5]


def create_bug_from_conversation(chat_id, user_id, title_override=None, priority_override=None):
    """Use Claude to parse a PilgrimBot conversation into a structured bug report, then create it.
    Includes evidence trail: key data points, source references, and DB lookup info.
    Returns {'success': bool, 'bug_id': int, 'title': str} or {'success': False, 'error': str}."""
    history = get_chat_history(user_id, chat_id, limit=40)
    if not history:
        return {'success': False, 'error': 'No conversation found'}

    # Build full conversation for Claude (use more chars for longer threads)
    convo_text = ""
    for i, msg in enumerate(history):
        role = "QA" if msg['role'] == 'user' else "PilgrimBot"
        ts = msg.get('created_at', '')
        convo_text += f"[{i+1}] {role} ({ts}): {msg['content'][:800]}\n\n"

    client = create_client(model=MODEL)
    _s = _time.time()
    resp = client.client.messages.create(
        model=MODEL, max_tokens=1000, temperature=0,
        system="You extract structured bug reports from QA conversations. Return ONLY valid JSON, no markdown.",
        messages=[{"role": "user", "content": f"""Read this QA conversation ({len(history)} messages) and extract a bug report.

CONVERSATION:
{convo_text[-6000:]}

Return JSON with exactly these fields:
{{
  "title": "Short bug title (under 100 chars)",
  "description": "Clear description: what's wrong, expected vs actual behavior",
  "priority": "P1 or P2 or P3",
  "evidence": "Key data points and findings from the conversation — specific numbers, formulas, behaviors observed. Include which message numbers [N] contain the most important evidence.",
  "affected_areas": "Which game systems/pages are affected (e.g. shard generation, colony page, expeditions)"
}}"""}]
    )
    log_api_usage(model=MODEL, usage=resp.usage, feature='pilgrimbot_create_bug', duration_ms=int((_time.time() - _s) * 1000))
    try:
        text = resp.content[0].text.strip()
        if text.startswith('```'):
            text = text.split('\n', 1)[1].rsplit('```', 1)[0].strip()
        parsed = json.loads(text)
    except (json.JSONDecodeError, IndexError) as e:
        logger.warning(f"Bug extraction parse error: {e}")
        return {'success': False, 'error': 'Could not parse conversation into a bug'}

    from utilities.db_bugs import create_bug, add_bug_comment
    bug = create_bug(
        name=(title_override or parsed.get('title', 'PilgrimBot bug'))[:200],
        description=parsed.get('description', '')[:2000],
        priority=priority_override or parsed.get('priority', 'P3'),
        source='PilgrimBot'
    )
    if not bug:
        return {'success': False, 'error': 'Failed to create bug'}

    # Add evidence comment with conversation reference + DB lookup
    evidence = parsed.get('evidence', '')
    areas = parsed.get('affected_areas', '')
    comment_body = f"**Source:** PilgrimBot conversation ({len(history)} messages)\n"
    comment_body += f"**Chat ID:** `{chat_id}`\n"
    comment_body += f"**DB lookup:** `SELECT * FROM pilgrim.pilgrimbot_conversations WHERE chat_id = '{chat_id}' ORDER BY created_at`\n\n"
    if areas:
        comment_body += f"**Affected areas:** {areas}\n\n"
    if evidence:
        comment_body += f"**Key findings:**\n{evidence}\n"
    add_bug_comment(bug['id'], 'PilgrimBot', comment_body)

    # Auto-discover related bugs in background (don't make user wait for Haiku)
    import threading
    threading.Thread(
        target=_cross_link_related_bugs,
        args=(bug['id'], bug['name'], areas),
    ).start()

    logger.info(f"Bug created from conversation: #{bug['id']} - {bug['name']}")
    return {'success': True, 'bug_id': bug['id'], 'title': bug['name']}


def create_bug_from_response(response_text, user_id, chat_id=None, title_override=None, priority_override=None):
    """Create a bug from a SINGLE PilgrimBot response (not the full conversation).
    Uses Claude to extract a structured bug report from just this one response."""
    if not response_text:
        return {'success': False, 'error': 'No response text'}

    client = create_client(model=MODEL)
    _s = _time.time()
    resp = client.client.messages.create(
        model=MODEL, max_tokens=1000, temperature=0,
        system="You extract structured bug reports from a single PilgrimBot analysis response. Return ONLY valid JSON, no markdown.",
        messages=[{"role": "user", "content": f"""Read this single PilgrimBot response and extract a bug report from it.

RESPONSE:
{response_text[:6000]}

Return JSON with exactly these fields:
{{
  "title": "Short bug title (under 100 chars)",
  "description": "Clear description based on what PilgrimBot found in this response",
  "priority": "P1 or P2 or P3",
  "evidence": "Key findings from this specific response"
}}"""}]
    )
    log_api_usage(model=MODEL, usage=resp.usage, feature='pilgrimbot_create_bug_from_response', duration_ms=int((_time.time() - _s) * 1000))
    try:
        text = resp.content[0].text.strip()
        if text.startswith('```'):
            text = text.split('\n', 1)[1].rsplit('```', 1)[0].strip()
        parsed = json.loads(text)
    except (json.JSONDecodeError, IndexError) as e:
        logger.warning(f"Bug extraction from response parse error: {e}")
        return {'success': False, 'error': 'Could not parse response into a bug'}

    from utilities.db_bugs import create_bug, add_bug_comment
    bug = create_bug(
        name=(title_override or parsed.get('title', 'PilgrimBot bug'))[:200],
        description=parsed.get('description', '')[:2000],
        priority=priority_override or parsed.get('priority', 'P3'),
        source='PilgrimBot'
    )
    if not bug:
        return {'success': False, 'error': 'Failed to create bug'}

    # Add the original response as evidence
    evidence = parsed.get('evidence', '')
    comment_body = f"**Source:** Single PilgrimBot response\n"
    if chat_id:
        comment_body += f"**Chat ID:** `{chat_id}`\n"
    if evidence:
        comment_body += f"\n**Key findings:**\n{evidence}\n"
    add_bug_comment(bug['id'], 'PilgrimBot', comment_body)

    # Auto-discover related bugs in background
    import threading
    threading.Thread(
        target=_cross_link_related_bugs,
        args=(bug['id'], bug['name'], parsed.get('description', '')),
    ).start()

    logger.info(f"Bug created from single response: #{bug['id']} - {bug['name']}")
    return {'success': True, 'bug_id': bug['id'], 'title': bug['name']}


def get_reports(limit=50):
    """Get PilgrimBot-submitted reports from the bug tracker."""
    try:
        from utilities.db_bugs import search_bugs
        # Return all bugs from PilgrimBot source
        from utilities.db_bugs import get_active_bugs
        return get_active_bugs(search=None)[:limit]
    except Exception as e:
        logger.warning(f"Failed to get reports: {e}")
        return []


# === Chat Handler ===

def _build_codemap_summary(codemap):
    """Build a condensed codebase map for the system prompt (~8KB)."""
    lines = ["CODEBASE MAP (use read_file tool to fetch any file):"]
    for fpath, info in sorted(codemap.items()):
        desc = info.get("description", "")[:80]
        lines.append(f"  {fpath} — {desc}")
    return "\n".join(lines)


def _execute_tool_loop(client_raw, messages, system, tools, max_rounds=4, current_user_id=None, model_override=None):
    """Run a tool-use loop: let Claude call read_file or query_player_data, execute it, repeat.
    Yields (event_type, data) tuples. Final yield is ('result', text).
    Deduplicates file reads and forces a final answer when rounds run out."""
    loop_model = model_override or MODEL
    files_already_read = {}  # path -> content (cache to prevent re-reads)
    for round_num in range(max_rounds):
        yield ("status", {"message": f"Analyzing{'.' * (round_num + 1)}"})
        _start = _time.time()
        resp = client_raw.messages.create(
            model=loop_model, max_tokens=3000, temperature=0.7,
            system=system, messages=messages, tools=tools
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
                        result_text = content or f"File not found: {fpath}"
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
        "text": "You have read enough files. Give your COMPLETE analysis now based on everything you've seen. Do not request more files."}]})
    _start = _time.time()
    resp = client_raw.messages.create(
        model=MODEL, max_tokens=3000, temperature=0.7,
        system=system, messages=messages
    )
    _ms = int((_time.time() - _start) * 1000)
    log_api_usage(model=MODEL, usage=resp.usage, feature='pilgrimbot_chat_final',
                  user_id=str(current_user_id) if current_user_id else None,
                  duration_ms=_ms)
    text = "".join(b.text for b in resp.content if b.type == "text")
    yield ("result", text)


def handle_chat_streaming(message, chat_id, user_id, history=None, bug_mode=False, action_context="", user_role="captain"):
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

    # Send start event FIRST so frontend gets an immediate SSE chunk (resets 45s timeout)
    yield f"data: {json.dumps({'type': 'start', 'chat_id': chat_id})}\n\n"

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
    code_context = ""
    relevant = find_relevant_files(message, max_files=6 if bug_mode else 4)
    for fpath in relevant:
        extra_terms = search_terms[:]
        if fpath in codemap and "exports" in codemap[fpath]:
            for export in codemap[fpath]["exports"]:
                fname = export.split(" —")[0].split(" ")[0].replace("class ", "")
                extra_terms.append(fname.lower())
        content = read_local_file(fpath, search_terms=extra_terms)
        if content:
            code_context += f"\n--- {fpath} ---\n{content}\n"

    # Keepalive after file reads — resets frontend timeout
    yield f"data: {json.dumps({'type': 'status', 'message': 'Preparing...'})}\n\n"

    # Build system prompt — role-based persona
    show_code = user_role == 'dev' or bug_mode
    if bug_mode:
        system = BUG_MODE_PROMPT
    else:
        system = PERSONAS.get(user_role, PERSONA_CAPTAIN)
    if code_context:
        if show_code:
            system += f"\n\nRELEVANT CODE CONTEXT:\n{code_context}"
        else:
            system += (
                "\n\nINTERNAL REFERENCE (for YOUR understanding only — NEVER show this to the user):\n"
                "Translate everything below into plain-English game mechanics. "
                "NEVER mention file names, function names, variable names, line numbers, or code. "
                "The user should feel like they're talking to someone who designed the game, not someone reading source code.\n"
                f"{code_context}"
            )

    # Always load static knowledge file
    knowledge_path = os.path.join(PROJECT_ROOT, "pilgrimbot_knowledge.md")
    if os.path.exists(knowledge_path):
        try:
            with open(knowledge_path) as f:
                system += f"\n\nGAME KNOWLEDGE:\n{f.read()}"
        except Exception:
            pass

    # Load dynamic context (brainstorm + bugs) when keywords match
    dynamic = load_dynamic_context(message)
    if dynamic:
        if show_code:
            system += f"\n\nLIVE DATA:{dynamic}"
        else:
            system += f"\n\nINTERNAL DATA (summarize in plain English, never show raw data/queries/column names):{dynamic}"

    # Action results (speed test, etc.) from app.py
    if action_context:
        if show_code:
            system += f"\n\nACTION RESULTS:{action_context}"
        else:
            system += f"\n\nINTERNAL RESULTS (share the findings in plain English, no technical details):{action_context}"

    # Build conversation messages
    api_messages = []
    for h in history[-MAX_HISTORY:]:
        api_messages.append({"role": h["role"], "content": h["content"]})
    api_messages.append({"role": "user", "content": message})

    try:
        # Detect math/calculation questions → upgrade model for accuracy
        msg_lower = message.lower()
        math_triggers = ['calculate', 'calculated', 'calculation', 'formula', 'math',
                         'how is my', 'how does my', 'break down', 'breakdown', 'show the math',
                         'explain exactly', 'add up', 'doesn\'t add up', 'multiplier',
                         'effective rate', 'generation rate', 'how much', 'per hour']
        is_math_question = any(t in msg_lower for t in math_triggers)

        # Math questions: Sonnet + targeted formulas instead of Opus + full 48KB dump.
        # Sonnet is strong at math, way cheaper/faster than Opus, and with precise
        # context from find_relevant_math() it has everything it needs.
        chat_model = MODEL
        if is_math_question:
            chat_model = CLAUDE_MODELS.get("sonnet-4.5", "claude-sonnet-4-5-20250929")
            logger.info(f"Math question detected — using Sonnet: {message[:80]}")

        client = create_client(model=chat_model)

        if is_math_question:
            yield f"data: {json.dumps({'type': 'status', 'message': 'Looking up formulas...'})}\n\n"
            # Targeted math lookup — only inject relevant formulas + constants
            relevant_math = find_relevant_math(message)
            if relevant_math and relevant_math.get('formulas'):
                system += f"\n\nMATH REGISTRY (authoritative formulas — use these EXACT formulas, never guess or re-derive from code):\n{json.dumps(relevant_math)}"
                logger.info(f"Math: targeted {len(relevant_math['formulas'])} formulas ({len(json.dumps(relevant_math))} chars)")
            else:
                # Generic math question with no keyword matches — send full registry
                full = load_math_registry()
                if full:
                    system += f"\n\nMATH REGISTRY (authoritative formulas — use these EXACT formulas, never guess or re-derive from code):\n{json.dumps(full)}"
                    logger.info(f"Math: full registry fallback ({len(json.dumps(full))} chars)")
            # Force query player data upfront so the model has real numbers
            try:
                shard_data = query_player_data('shard_generation', user_id)
                balance_data = query_player_data('balance', user_id)
                system += f"\n\nPRE-LOADED PLAYER DATA (use these EXACT numbers, do NOT recalculate):\n{balance_data}\n\n{shard_data}"
            except Exception as e:
                logger.warning(f"Failed to pre-load math data: {e}")

        # Endgame questions: inject endgame_registry.json
        endgame_triggers = ['signal', 'origin', 'node', 'decoder', 'decode', 'ledger',
                            'endgame', 'end game', 'end-game', 'founder', 'claim',
                            'hitchhiker', 'lost signal', 'beagle', 'schiaparelli', 'mars-3',
                            'blockchain', 'transaction', 'tx_hash', 'puzzle',
                            '14 sites', 'origin site', 'three act', 'world 2']
        if any(t in msg_lower for t in endgame_triggers):
            endgame = load_endgame_registry()
            if endgame:
                system += f"\n\nENDGAME REGISTRY (authoritative reference for Signal/Origin/Decoder system — use this as your answer key):\n{json.dumps(endgame)}"
                logger.info(f"Endgame registry injected ({len(json.dumps(endgame))} chars)")

        # Decide which tools to offer
        deep_dive_triggers = ['get the file', 'show me the code', 'read the code',
                              'look at the code', 'check the file', 'fetch the file',
                              'go get', 'deep dive', 'show the exact code', 'prove it']
        use_file_tools = bug_mode and any(t in msg_lower for t in deep_dive_triggers)

        # Keepalive before API call — resets frontend timeout after all context loading
        yield f"data: {json.dumps({'type': 'status', 'message': 'Analyzing...'})}\n\n"

        # Always include player data tool — Claude decides when to use it
        active_tools = [PLAYER_DATA_TOOL]
        system += f"\n\n{PLAYER_DATA_MAP}"
        system += f"\nThe current user's ID is {user_id}. Use this when they say 'my' or 'I'."

        if use_file_tools:
            active_tools.append(READ_FILE_TOOL)
            system += f"\n\n{_build_codemap_summary(codemap)}"

        full_response = ""
        for event_type, data in _execute_tool_loop(
            client.client, api_messages, system, active_tools,
            current_user_id=user_id, model_override=chat_model
        ):
            if event_type == "status":
                yield f"data: {json.dumps({'type': 'status', 'message': data['message']})}\n\n"
            elif event_type == "tool_call":
                yield f"data: {json.dumps({'type': 'tool_call', 'file': data['file'], 'found': data['found']})}\n\n"
            elif event_type == "result":
                full_response = data
        # Stream the final response to frontend
        for i in range(0, len(full_response), 20):
            chunk = full_response[i:i+20]
            yield f"data: {json.dumps({'type': 'delta', 'text': chunk})}\n\n"

        # Save assistant response
        save_message(user_id, chat_id, "assistant", full_response)

        # Check if PilgrimBot indicated it couldn't answer
        cant_answer_signals = [
            "wasn't able to find", "couldn't find a clear answer",
            "flag this for the dev team", "like me to flag", "want me to report",
        ]
        cant_answer = any(signal in full_response.lower() for signal in cant_answer_signals)

        yield f"data: {json.dumps({'type': 'stop', 'chat_id': chat_id, 'cant_answer': cant_answer})}\n\n"

    except Exception as e:
        logger.error(f"PilgrimBot stream error: {e}")
        yield f"data: {json.dumps({'type': 'error', 'message': 'Something went wrong. Try again?'})}\n\n"
