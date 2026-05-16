"""ARIA chat route handlers — streaming/sync wrappers called directly from app.py routes.

Extracted from utilities/aria_utils.py (Pass B of the ARIA split).
"""

import logging
from typing import Dict, Any, Optional

from utilities.aria.chat import get_aria_response, stream_aria_response
from utilities.aria.conversation import save_aria_message, get_aria_conversation_history
from utilities.aria.animations import check_for_aria_animation, record_aria_animation
from utilities.aria.config import ARIA_ANIMATIONS

logger = logging.getLogger(__name__)

def _build_aria_user_context(user_id, is_authenticated, page_context, referrer=None):
    """Build the user context dict for ARIA chat."""
    context = {
        'commander_name': None,
        'balance': 0,
        'total_discoveries': 0,
        'total_expeditions': 0,
        'scientist_name': None,
        'current_page': page_context.get('page') or (referrer.split('/')[-1] if referrer else None),
        'page_url': page_context.get('url', ''),
        'page_specific_context': page_context.get('context', ''),
        'is_new_visitor': not is_authenticated
    }

    if not is_authenticated or not user_id:
        return context

    try:
        from utilities.postgres.assets import get_user_commander
        from utilities.postgres.users import get_user_scientist
        from utilities.postgres.core import db_cursor
        from utilities.depot_utils import get_fast_balance_and_wallet_info

        commander = get_user_commander(user_id)
        if commander:
            context['commander_name'] = commander.get('name', 'Commander')

        balance, _, _ = get_fast_balance_and_wallet_info(user_id)
        context['balance'] = balance or 0

        scientist = get_user_scientist(user_id)
        if scientist:
            context['scientist_name'] = scientist.get('name')

        with db_cursor() as cur:
            cur.execute("SELECT COUNT(*) as cnt FROM pilgrim.expeditions WHERE user_id = %s AND status = 'complete'", (user_id,))
            result = cur.fetchone()
            context['total_expeditions'] = result['cnt'] if result else 0

            cur.execute("""
                SELECT COUNT(*) as cnt FROM pilgrim.expedition_discoveries ed
                JOIN pilgrim.expeditions e ON ed.expedition_id = e.id
                WHERE e.user_id = %s AND ed.claimed_by_user = false
            """, (user_id,))
            result = cur.fetchone()
            context['total_discoveries'] = result['cnt'] if result else 0
    except Exception as e:
        logger.warning(f"Error building ARIA context: {e}")

    return context


def handle_aria_chat_request(data: Dict, user_id: Optional[int], is_authenticated: bool, referrer: Optional[str]) -> Dict[str, Any]:
    """Validate input, load snapshot+context, return streaming generator or sync result.

    Returns one of:
      {'error': str}                          — validation failed
      {'mode': 'stream', 'generator': gen}    — caller wraps in SSE Response
      {'mode': 'sync',   'result': dict}      — caller jsonifies
    """
    message = (data.get('message') or '').strip()
    if not message:
        return {'error': 'No message provided'}

    aria_snapshot = None
    if is_authenticated and user_id:
        try:
            from utilities.aria.snapshot import load_colony_snapshot
            aria_snapshot = load_colony_snapshot(user_id)
        except Exception as e:
            logger.warning(f"Failed to load ARIA snapshot: {e}")

    user_context = _build_aria_user_context(user_id, is_authenticated,
                                             data.get('page_context', {}), referrer)
    history = data.get('history', [])

    if data.get('stream', False):
        gen = handle_aria_chat_streaming(message, history, user_context,
                                          user_id, is_authenticated, aria_snapshot)
        return {'mode': 'stream', 'generator': gen}

    result = handle_aria_chat_sync(message, history, user_context,
                                    user_id, is_authenticated, aria_snapshot)
    return {'mode': 'sync', 'result': result}


def handle_aria_chat_streaming(message, history, user_context, user_id, is_authenticated, aria_snapshot):
    """Handle streaming ARIA chat. Returns a generator yielding SSE chunks."""
    import json as json_lib
    import random as rng

    captain_name = user_context.get('commander_name', 'Guest')
    logger.info(f"ARIA [{captain_name}] says: {message}")

    test_animation = 'test123' in message.lower()

    # Load DB conversation history for authenticated users
    if is_authenticated and user_id:
        db_history = get_aria_conversation_history(user_id, limit=20)
        if db_history:
            history = db_history

    def generate():
        full_response = []
        stop_chunk = None

        # Check for animation FIRST
        if test_animation:
            animation_url = rng.choice(list(ARIA_ANIMATIONS.values()))
            yield f"data: {json_lib.dumps({'type': 'animation', 'url': animation_url})}\n\n"
        elif is_authenticated and user_id:
            animation_url = check_for_aria_animation(user_id, message)
            if animation_url:
                yield f"data: {json_lib.dumps({'type': 'animation', 'url': animation_url})}\n\n"
                record_aria_animation(user_id, animation_url)

        for chunk in stream_aria_response(
            user_message=message,
            conversation_history=history,
            user_context=user_context,
            user_id=user_id if is_authenticated else None,
            snapshot=aria_snapshot
        ):
            if chunk.startswith('data: '):
                try:
                    data_json = json_lib.loads(chunk[6:].strip())
                    if data_json.get('type') == 'delta' and data_json.get('text'):
                        full_response.append(data_json['text'])
                    elif data_json.get('type') == 'stop':
                        stop_chunk = chunk
                        continue
                except Exception:
                    pass
            yield chunk

        # Save messages to DB for authenticated users
        if is_authenticated and user_id and full_response:
            aria_response = ''.join(full_response)
            save_aria_message(user_id, 'user', message)
            save_aria_message(user_id, 'assistant', aria_response)
            logger.info(f"ARIA replies to [{captain_name}]: {aria_response[:200]}{'...' if len(aria_response) > 200 else ''}")

        if stop_chunk:
            yield stop_chunk

    return generate()


def handle_aria_chat_sync(message, history, user_context, user_id, is_authenticated, aria_snapshot):
    """Handle non-streaming ARIA chat. Returns a response dict."""
    if is_authenticated and user_id:
        db_history = get_aria_conversation_history(user_id, limit=20)
        if db_history:
            history = db_history

    response = get_aria_response(
        user_message=message,
        conversation_history=history,
        user_context=user_context,
        user_id=user_id if is_authenticated else None,
        snapshot=aria_snapshot
    )

    if is_authenticated and user_id:
        save_aria_message(user_id, 'user', message)
        save_aria_message(user_id, 'assistant', response)

    return {'success': True, 'response': response}


def get_aria_album_data(user_id):
    """Fetch all ARIA photo journal snapshots for a user."""
    import json as json_lib
    from utilities.postgres.core import db_cursor

    snapshots = []
    with db_cursor() as cur:
        cur.execute("""
            SELECT id, subcategory as type, gcs_url as image_url, caption,
                   metadata, created_at
            FROM pilgrim.generated_images
            WHERE user_id = %s AND category = 'aria_snapshot' AND is_active = true
            ORDER BY created_at DESC
            LIMIT 100
        """, (user_id,))
        for snap in cur.fetchall():
            metadata = snap.get('metadata') or {}
            if isinstance(metadata, str):
                try:
                    metadata = json_lib.loads(metadata)
                except Exception:
                    metadata = {}
            thumbnail_url = metadata.get('thumbnail_url')

            created = snap.get('created_at')
            earth_date = created.strftime('%b %d, %Y') if created else None
            earth_time = None  # Sol badge is the time reference, Earth clock is irrelevant
            # Calculate sol from created_at (not stored metadata) so epoch changes apply retroactively
            from utilities.mars_environment_utils import get_mars_sol_number
            mars_sol = get_mars_sol_number(created) if created else metadata.get('mars_sol')

            snapshots.append({
                'id': snap['id'],
                'type': snap['type'],
                'image_url': snap['image_url'],
                'thumbnail_url': thumbnail_url or snap['image_url'],
                'caption': snap['caption'],
                'created_at': earth_date,
                'mars_sol': mars_sol,
                'earth_date': earth_date,
                'earth_time': earth_time,
                'scene_actors': metadata.get('scene_actors') or [],
            })
    return snapshots
