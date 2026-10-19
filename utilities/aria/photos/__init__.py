"""ARIA photo/snapshot generation — Instagram-style images of colony life.

Two modes:
1. Flux Kontext: edit single source image into new scene (~$0.03/image)
2. Nano Banana Pro: combine multiple reference images with character consistency (~$0.20/image)

Plus a Claude-driven daily orchestrator that generates fully unique prompts from live colony data.
"""

from utilities.aria.photos.generator import (
    generate_snapshot,
    generate_nano_banana_snapshot,
    generate_snapshot_for_user,
)
from utilities.aria.photos.orchestrator import (
    generate_daily_snapshots,
    generate_daily_snapshots_for_user,
)
from utilities.aria.photos.prompts import (
    SNAPSHOT_PROMPTS,
    NANO_BANANA_PROMPTS,
    ALL_SNAPSHOT_TYPES,
)


def get_snapshot_narrative_for_user(user_id, caption, snapshot_type):
    """Claude-powered narrative for a snapshot — looks up the captain name
    for personalization and calls the Claude utility."""
    from utilities.claude_utils import generate_aria_snapshot_narrative
    commander_name = None
    if user_id:
        try:
            from utilities.postgres.users import get_user_commander
            commander = get_user_commander(user_id)
            if commander:
                commander_name = commander.get('name')
        except Exception:
            pass
    return generate_aria_snapshot_narrative(
        caption=caption,
        snapshot_type=snapshot_type,
        commander_name=commander_name,
        user_id=user_id,
    )


def delete_snapshot_with_auth(user_id, snapshot_id):
    """Soft-delete a snapshot from the user's photo gallery.

    Returns a response dict matching the route contract:
      {'success': True, 'deleted_id': <id>}  on success
      {'success': False, 'error': <str>}     on failure
    """
    if not user_id:
        return {'success': False, 'error': 'Not logged in'}
    if not snapshot_id:
        return {'success': False, 'error': 'Missing snapshot_id'}

    from utilities.postgres.core import db_cursor
    with db_cursor(commit=True) as cur:
        cur.execute("""
            UPDATE pilgrim.generated_images
            SET is_active = false
            WHERE id = %s AND user_id = %s AND category = 'aria_snapshot'
            RETURNING id
        """, (snapshot_id, user_id))
        result = cur.fetchone()

    if result:
        return {'success': True, 'deleted_id': snapshot_id}
    return {'success': False, 'error': 'Snapshot not found'}


__all__ = [
    "generate_snapshot",
    "generate_nano_banana_snapshot",
    "generate_snapshot_for_user",
    "generate_daily_snapshots",
    "generate_daily_snapshots_for_user",
    "get_snapshot_narrative_for_user",
    "delete_snapshot_with_auth",
    "SNAPSHOT_PROMPTS",
    "NANO_BANANA_PROMPTS",
    "ALL_SNAPSHOT_TYPES",
]
