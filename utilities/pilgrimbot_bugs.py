"""
PilgrimBot bug creation and cross-linking utilities.
Extracted from pilgrimbot_utils.py for file size management.
"""

import json
import logging
import threading
import time as _time

from utilities.claude_utils import create_client, log_api_usage
from utilities.postgres_utils import db_cursor

logger = logging.getLogger("pilgrimbot")

# Tool definition for Claude to create bugs directly
CREATE_BUG_TOOL = {
    "name": "create_bug",
    "description": "File a new bug in the tracker. Use this when the user asks you to create/file/log a bug, or when you discover an issue worth tracking. Returns the bug ID and link.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Short bug title (under 100 chars)"
            },
            "description": {
                "type": "string",
                "description": "Clear description: what's wrong, expected vs actual behavior"
            },
            "priority": {
                "type": "string",
                "enum": ["P1", "P2", "P3", "P4", "P5"],
                "description": "Priority level. P1=critical, P2=important, P3=normal"
            }
        },
        "required": ["title", "description", "priority"]
    }
}


def execute_create_bug_tool(input_data, user_id, chat_id=None):
    """Execute the create_bug tool call. Returns formatted result string."""
    from utilities.db_bugs import create_bug, add_bug_comment
    title = (input_data.get('title', 'PilgrimBot bug'))[:200]
    description = (input_data.get('description', ''))[:2000]
    priority = input_data.get('priority', 'P3')

    bug = create_bug(name=title, description=description, priority=priority, source='PilgrimBot')
    if not bug:
        return "ERROR: Failed to create bug in database."

    # Add source comment linking to the conversation
    comment = f"**Source:** Filed by PilgrimBot during chat"
    if chat_id:
        comment += f"\n**Chat ID:** `{chat_id}`"
    add_bug_comment(bug['id'], 'PilgrimBot', comment)

    logger.info(f"Bug created via tool: #{bug['id']} - {title}")
    return f"Bug created successfully: #{bug['id']} — {title}\nLink: /admin/bugs?open={bug['id']}"

# Use same model as main pilgrimbot
MODEL = "claude-haiku-4-5-20251001"


def _strip_markdown_json(text):
    """Strip markdown code fence from Claude's JSON responses."""
    text = text.strip()
    if text.startswith('```'):
        text = text.split('\n', 1)[-1].rsplit('```', 1)[0].strip()
    return text


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
        log_api_usage(
            model=MODEL, usage=resp.usage, feature='pilgrimbot_related_bugs',
            duration_ms=int((_time.time() - _s) * 1000),
            user_id="system:galactica_pilgrimbot_bugs",
        )
        text = _strip_markdown_json(resp.content[0].text)
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
    from utilities.pilgrimbot_utils import get_chat_history
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
    log_api_usage(
        model=MODEL, usage=resp.usage, feature='pilgrimbot_create_bug',
        duration_ms=int((_time.time() - _s) * 1000),
        user_id=str(user_id) if user_id else "system:galactica_pilgrimbot_bugs",
    )
    try:
        text = _strip_markdown_json(resp.content[0].text)
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
    threading.Thread(
        target=_cross_link_related_bugs,
        args=(bug['id'], bug['name'], areas),
        daemon=True,
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
    log_api_usage(
        model=MODEL, usage=resp.usage, feature='pilgrimbot_create_bug_from_response',
        duration_ms=int((_time.time() - _s) * 1000),
        user_id=str(user_id) if user_id else "system:galactica_pilgrimbot_bugs",
    )
    try:
        text = _strip_markdown_json(resp.content[0].text)
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
    threading.Thread(
        target=_cross_link_related_bugs,
        args=(bug['id'], bug['name'], parsed.get('description', '')),
        daemon=True,
    ).start()

    logger.info(f"Bug created from single response: #{bug['id']} - {bug['name']}")
    return {'success': True, 'bug_id': bug['id'], 'title': bug['name']}


def get_reports(limit=50):
    """Get PilgrimBot-submitted reports from the bug tracker."""
    try:
        from utilities.db_bugs import get_active_bugs
        return get_active_bugs(search=None)[:limit]
    except Exception as e:
        logger.warning(f"Failed to get reports: {e}")
        return []
