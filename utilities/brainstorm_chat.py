"""Generic brainstorm chat used by tech tree and trail brainstorm pages.

Extracted from utilities/claude_utils.py (Round 5 refactor).
"""

import os
import time
import logging

from utilities.anthropic_logger import new_client

from utilities.anthropic.client import _get_anthropic_api_key
from utilities.anthropic.pricing import log_api_usage

logger = logging.getLogger("claude_utils")


def brainstorm_chat(message, context, history, user_id=None):
    """Generic brainstorm chat with Claude. Used by tech tree and trail brainstorm pages."""
    api_key = _get_anthropic_api_key()

    client = new_client()

    # Enrich context with endgame registry for signal/endgame-related pages
    enriched_context = context
    msg_lower = (message + ' ' + context).lower()
    endgame_triggers = ['signal', 'origin', 'decoder', 'endgame', 'end game', 'founder',
                        'lost signal', 'blockchain', 'puzzle', 'hitchhiker', 'three act',
                        'node', 'ledger']
    if any(t in msg_lower for t in endgame_triggers):
        try:
            import json as _json
            registry_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'endgame_registry.json')
            if os.path.exists(registry_path):
                with open(registry_path) as f:
                    endgame = _json.load(f)
                enriched_context += f"\n\nENDGAME REGISTRY (authoritative reference — use as answer key for all Signal/Origin/Decoder questions):\n{_json.dumps(endgame)}"
        except Exception:
            pass

    # Add bug/feature creation guidance to all brainstorm chats
    enriched_context += """

BUG/FEATURE TRACKING:
When brainstorming surfaces a concrete bug, feature request, or action item:
- Clearly label it as **[BUG]** or **[FEATURE]** with a short title
- Suggest the user create it in the bug tracker: "This could be filed as a bug/feature — want me to suggest the details?"
- Include priority suggestion (P1=critical, P2=important, P3=nice-to-have, P4=someday, P5=idea)
- Reference the brainstorm page URL so the bug links back to the discussion context
- The bug tracker lives at /admin/bugs — bugs can be created via the CLI tool 'pb' or the admin UI"""

    messages = [{"role": msg['role'], "content": msg['content']} for msg in history[-10:]]
    messages.append({"role": "user", "content": message})

    _start = time.time()
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        system=enriched_context,
        messages=messages
    )
    _elapsed = time.time() - _start

    log_api_usage(
        model="claude-sonnet-4-20250514",
        usage=response.usage,
        feature='brainstorm_chat',
        duration_ms=int(_elapsed * 1000),
        user_id=str(user_id) if user_id else "system:galactica_brainstorm",
    )

    return response.content[0].text
