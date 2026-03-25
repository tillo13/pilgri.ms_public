"""
PilgrimBot context loading — registries, file search, and dynamic context.
Extracted from pilgrimbot_utils.py for file size management.
"""

import json
import logging
import os
from datetime import datetime

from utilities.postgres_utils import db_cursor

logger = logging.getLogger("pilgrimbot")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# === Registry Loaders (cached) ===

_codemap_cache = None
_math_registry_cache = None
_endgame_registry_cache = None


def load_codemap():
    """Load codemap.json from the local project. Cached after first load."""
    global _codemap_cache
    if _codemap_cache is not None:
        return _codemap_cache
    local_path = os.path.join(PROJECT_ROOT, "codemap.json")
    if os.path.exists(local_path):
        with open(local_path) as f:
            _codemap_cache = json.load(f)
            return _codemap_cache
    return {}


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


# === Search Functions ===

def find_relevant_math(message, max_formulas=5):
    """Keyword-match the question to only the relevant math_registry sections.
    Returns a slim dict with only matching formulas + referenced constants.
    Same pattern as codemap file matching — avoids dumping 48KB into context."""
    registry = load_math_registry()
    if not registry:
        return None

    msg_lower = message.lower()
    words = set(w.strip("?.,!()\"'") for w in msg_lower.split() if len(w) > 2)

    # Score each formula by keyword overlap with question
    scored_formulas = []
    formulas_raw = registry.get("formulas", {})
    # Handle both dict and list formats
    formula_items = formulas_raw.values() if isinstance(formulas_raw, dict) else formulas_raw
    for f in formula_items:
        if not isinstance(f, dict):
            continue
        # Check name, description, and keywords
        searchable = f"{f.get('name', '')} {f.get('description', '')} {' '.join(f.get('keywords', []))}".lower()
        score = sum(1 for w in words if w in searchable)
        # Boost for exact name/category matches
        if any(w in f.get('name', '').lower() for w in words):
            score += 3
        if score > 0:
            scored_formulas.append((score, f))

    if not scored_formulas:
        return None

    scored_formulas.sort(key=lambda x: -x[0])
    top_formulas = [f for _, f in scored_formulas[:max_formulas]]

    # Collect only the constants referenced by matched formulas
    referenced_constants = set()
    all_constants = registry.get("constants", {})
    for f in top_formulas:
        # Check variable names and formula string for constant references
        variables = f.get("variables", {})
        var_names = variables.keys() if isinstance(variables, dict) else []
        formula_str = f.get("formula", "")
        combined = " ".join(var_names) + " " + formula_str
        for c in all_constants:
            if c.lower() in combined.lower():
                referenced_constants.add(c)

    slim_constants = {k: v for k, v in registry.get("constants", {}).items()
                      if k in referenced_constants}

    return {
        "formulas": top_formulas,
        "constants": slim_constants,
        "meta": f"Matched {len(top_formulas)} of {len(formulas_raw)} formulas"
    }


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


# === Dynamic Context (brainstorm + bugs + speed) ===

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
