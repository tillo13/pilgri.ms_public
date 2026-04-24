"""PilgrimBot context planner + surgical context loader."""

import json
import logging
import time as _time

from utilities.claude_utils import create_client, CLAUDE_MODELS, log_api_usage
from utilities.anthropic_logger import new_client  # canonical chain proof (noqa: F401)

from utilities.pilgrimbot.storage import _strip_markdown_json
from utilities.pilgrimbot.file_reader import read_local_file

logger = logging.getLogger("pilgrimbot")

MODEL = CLAUDE_MODELS.get("haiku-4.5", "claude-haiku-4-5-20251001")


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
    # Local imports to avoid cycles and keep module load cheap
    from utilities.pilgrimbot_context import (
        load_codemap, load_math_registry, load_endgame_registry,
        find_relevant_math, load_dynamic_context, get_staleness_warning,
    )
    from utilities.pilgrimbot_data import query_player_data

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
                from utilities.postgres.bugs import get_bug_by_id, get_bug_comments, get_bug_history
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
            from utilities.postgres.brainstorm import get_comments_for_page
            for page_key in brainstorm_keys[:3]:
                comments = get_comments_for_page(page_key)
                if comments:
                    extra += f"\n--- Brainstorm: {page_key} ({len(comments)} comments) ---\n"
                    for c in comments[-10:]:
                        extra += f"[{c.get('author_name', 'anon')}]: {str(c.get('comment_text', ''))[:200]}\n"
                    loaded.append(f"brainstorm:{page_key}")
        except Exception as e:
            logger.warning(f"Brainstorm context failed: {e}")

    # Prepend staleness warning if code/math context was loaded and registries are old
    if extra and any(l.startswith(('code:', 'math:')) for l in loaded):
        warning = get_staleness_warning()
        if warning:
            extra = f"\n\n{warning}" + extra

    return extra, loaded
