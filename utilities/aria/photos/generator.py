"""ARIA snapshot generators — Kontext edit, Nano Banana Pro, and the
per-user "generate one now" entry point used by the manual CLI tool.

The daily cron path lives in orchestrator.py and uses Claude-generated
prompts instead of the hardcoded templates here.
"""

import logging
import random
import time

from utilities.google_cloud_storage_utils import upload_blob_from_bytes

from utilities.aria.photos.data import (
    get_user_by_email,
    get_user_captain,
    get_recent_discoveries,
    get_recent_expeditions,
    get_user_rover_image,
    get_user_infrastructure,
)
from utilities.aria.photos.prompts import (
    SNAPSHOT_PROMPTS,
    NANO_BANANA_PROMPTS,
    TIME_OF_DAY,
    RARITY_COLORS,
    ARIA_IMAGE_URL,
    ARIA_SELFIE_URL,
    calculate_sol_number,
    get_current_mars_time,
)
from utilities.aria.photos.storage import save_generated_image

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Source image resolution
# ---------------------------------------------------------------------------

def get_source_image(source_type, user_data):
    """Resolve a single reference image URL for a given source tag."""
    if source_type == 'captain':
        captain = user_data.get('captain')
        if captain and captain.get('gcs_url'):
            return captain['gcs_url']
        return None

    if source_type == 'aria':
        return ARIA_IMAGE_URL

    if source_type == 'aria_selfie':
        return ARIA_SELFIE_URL

    if source_type == 'discovery':
        for disc in user_data.get('discoveries', []) or []:
            if disc.get('gcs_url'):
                return disc['gcs_url']
        return None

    if source_type == 'rover':
        return user_data.get('rover_image')

    return None


def get_source_images(source_types, user_data):
    """Resolve multiple reference image URLs (Nano Banana Pro multi-char scenes)."""
    images = []
    for source_type in source_types:
        url = get_source_image(source_type, user_data)
        if url:
            images.append(url)
    return images


# ---------------------------------------------------------------------------
# Context builders
# ---------------------------------------------------------------------------

def _base_context(user_data):
    captain = user_data.get('captain') or {}
    tod = get_current_mars_time()
    time_context = TIME_OF_DAY[tod]
    return tod, {
        'captain_name': captain.get('commander_name', 'The Captain') if captain else 'The Captain',
        'time_lighting': time_context['time_lighting'],
        'sky_desc': time_context['sky_desc'],
        'sol_number': calculate_sol_number(user_data.get('created_at')),
    }


def _add_discovery_context(context, discoveries, prefer_rarity=False):
    if not discoveries:
        context.update({
            'destination': 'the frontier',
            'rarity': 'rare',
            'rarity_color': 'bright blue',
            'item_type': 'artifact',
            'discovery_name': 'the unknown',
            'value': 5000,
            'total_discoveries': 0,
        })
        return

    if prefer_rarity:
        rarity_order = {'legendary': 0, 'rare': 1, 'uncommon': 2, 'common': 3}
        disc = sorted(discoveries, key=lambda d: rarity_order.get(d.get('rarity', 'common'), 3))[0]
    else:
        disc = discoveries[0]

    rarity = disc.get('rarity', 'common')
    context.update({
        'destination': disc.get('destination_name', 'an uncharted region'),
        'rarity': rarity,
        'rarity_color': RARITY_COLORS.get(rarity, 'subtle'),
        'item_type': disc.get('item_type', 'artifact'),
        'discovery_name': disc.get('name', 'mysterious artifact'),
        'value': int(disc.get('enhanced_value', 0) * 10000000),
        'total_discoveries': len(discoveries),
    })


def _add_expedition_context(context, expeditions, include_hours=False):
    if expeditions:
        exp = expeditions[0]
        context['distance_km'] = exp.get('distance_km', 50)
        context['expedition_destination'] = exp.get('destination_name', 'distant region')
        context['total_expeditions'] = len(expeditions)
        if include_hours:
            context['hours'] = max(1, int((exp.get('distance_km', 50) or 50) / 10))
    else:
        context['distance_km'] = 75 if include_hours else 50
        context['expedition_destination'] = 'unexplored territory'
        context['total_expeditions'] = 0
        if include_hours:
            context['hours'] = 8


# ---------------------------------------------------------------------------
# Flux Kontext single-image generation
# ---------------------------------------------------------------------------

def generate_snapshot(user_id, snapshot_type, user_data, flux, dry_run=False):
    """Generate a snapshot by editing an existing image with Flux Kontext.

    Returns dict with gcs_url, caption, snapshot_type, source_image.
    """
    if snapshot_type not in SNAPSHOT_PROMPTS:
        raise ValueError(f"Unknown snapshot type: {snapshot_type}")

    template = SNAPSHOT_PROMPTS[snapshot_type]
    source_image_url = get_source_image(template['source'], user_data)
    if not source_image_url:
        raise ValueError(f"No {template['source']} image available for user")

    tod, context = _base_context(user_data)
    _add_discovery_context(context, user_data.get('discoveries') or [])
    _add_expedition_context(context, user_data.get('expeditions') or [], include_hours=True)

    prompt = template['prompt_template'].format(**context)
    caption = random.choice(template['captions']).format(**context)

    logger.info("=" * 60)
    logger.info(f"SNAPSHOT TYPE: {snapshot_type}")
    logger.info(f"SOURCE IMAGE: {source_image_url[:80]}...")
    logger.info("=" * 60)
    logger.info(f"KONTEXT EDIT PROMPT:\n{prompt}\n")
    logger.info(f"ARIA CAPTION: {caption}")

    if dry_run:
        logger.info("DRY RUN - Skipping image generation")
        return {
            'gcs_url': None,
            'caption': caption,
            'snapshot_type': snapshot_type,
            'source_image': source_image_url,
            'prompt': prompt,
        }

    logger.info("Generating image via kumori (HF→CF cascade)...")
    start_time = time.time()
    from utilities.kumori_utils import kumori_klein_edit
    res = kumori_klein_edit(
        prompt=prompt, target_image=source_image_url,
        app_name='galactica_aria_snapshot',
        character=f'uid{user_id}',
        ref_filename=snapshot_type,
        feature='aria_snapshot.kontext',
        verbiage=prompt[:500], caller_user_id=user_id,
        tags={'snapshot_type': snapshot_type},
    )
    logger.info(f"Image generated in {time.time() - start_time:.1f}s via {res['provider']}")

    timestamp = int(time.time())
    blob_name = f"aria_snapshots/user_{user_id}/{snapshot_type}_{timestamp}.png"
    gcs_url = upload_blob_from_bytes(res['image_bytes'], blob_name, 'image/png')
    if not gcs_url:
        raise Exception("Failed to upload to GCS")
    logger.info(f"Uploaded to GCS: {gcs_url}")

    save_generated_image(
        user_id=user_id,
        category='aria_snapshot',
        subcategory=snapshot_type,
        gcs_url=gcs_url,
        gcs_blob_name=blob_name,
        source_image_url=source_image_url,
        prompt_used=prompt,
        caption=caption,
        metadata={
            'time_of_day': tod,
            'mars_sol': context.get('sol_number'),
            'context': {k: v for k, v in context.items() if isinstance(v, (str, int, float))},
        },
    )

    return {
        'gcs_url': gcs_url,
        'caption': caption,
        'snapshot_type': snapshot_type,
        'source_image': source_image_url,
    }


# ---------------------------------------------------------------------------
# Nano Banana Pro multi-reference generation
# ---------------------------------------------------------------------------

def _pick_nano_caption(template, context, discoveries, expeditions, infrastructure):
    contextual = template.get('contextual_captions', {})
    caption_template = None
    if contextual:
        if discoveries and 'has_discoveries' in contextual:
            caption_template = contextual['has_discoveries']
        elif expeditions and context.get('distance_km', 0) > 100 and 'long_expedition' in contextual:
            caption_template = contextual['long_expedition']
        elif expeditions and 'has_expedition' in contextual:
            caption_template = contextual['has_expedition']
        elif context.get('total_expeditions', 0) >= 5 and 'many_expeditions' in contextual:
            caption_template = contextual['many_expeditions']
        elif infrastructure and 'has_infrastructure' in contextual:
            caption_template = contextual['has_infrastructure']

    # Even with contextual, 30% chance roll to a standard caption for variety.
    if not caption_template or random.random() < 0.3:
        caption_template = random.choice(template['captions'])
    return caption_template.format(**context)


def generate_nano_banana_snapshot(user_id, snapshot_type, user_data, flux, dry_run=False):
    """Multi-character snapshot via Nano Banana Pro.

    Combines multiple reference images (captain + ARIA, etc.) with character
    consistency. ~$0.20/image.
    """
    if snapshot_type not in NANO_BANANA_PROMPTS:
        raise ValueError(f"Unknown Nano Banana snapshot type: {snapshot_type}")

    template = NANO_BANANA_PROMPTS[snapshot_type]
    source_image_urls = get_source_images(template['sources'], user_data)
    if not source_image_urls:
        raise ValueError(f"No source images available for {template['sources']}")

    tod, context = _base_context(user_data)
    discoveries = user_data.get('discoveries') or []
    expeditions = user_data.get('expeditions') or []
    infrastructure = user_data.get('infrastructure') or []

    _add_discovery_context(context, discoveries, prefer_rarity=True)
    _add_expedition_context(context, expeditions)
    context['has_infrastructure'] = bool(infrastructure)
    context['structure_count'] = len(infrastructure)

    prompt = template['prompt_template'].format(**context)
    caption = _pick_nano_caption(template, context, discoveries, expeditions, infrastructure)

    logger.info("=" * 60)
    logger.info(f"NANO BANANA PRO SNAPSHOT: {snapshot_type}")
    logger.info(f"SOURCE IMAGES: {len(source_image_urls)}")
    for i, url in enumerate(source_image_urls):
        logger.info(f"  [{i + 1}] {url[:80]}...")
    logger.info("=" * 60)
    logger.info(f"PROMPT:\n{prompt[:500]}...\n")
    logger.info(f"ARIA CAPTION: {caption}")

    if dry_run:
        logger.info("DRY RUN - Skipping image generation")
        return {
            'gcs_url': None,
            'caption': caption,
            'snapshot_type': snapshot_type,
            'source_images': source_image_urls,
            'prompt': prompt,
        }

    # Per-rung ref caps: CF Klein=4, HF Qwen=3, HF Kontext-Dev=1.
    # Capped at 3 — kumori_api_client.client.py:449 asserts `len(refs) > 3` raises.
    # Bump to 4 once kumori-side assertion is relaxed (see commit notes).
    KUMORI_MAX_REFS = 3
    target_url = source_image_urls[0]
    refs = source_image_urls[1:1 + KUMORI_MAX_REFS]
    dropped = source_image_urls[1 + KUMORI_MAX_REFS:]
    if dropped:
        logger.info(f"Pruned {len(dropped)} refs over kumori's {KUMORI_MAX_REFS}-ref cap: {[u[:50] for u in dropped]}")

    logger.info(f"Generating via kumori (target + {len(refs)} refs, was {len(source_image_urls)} total)...")
    start_time = time.time()
    from utilities.kumori_utils import kumori_klein_edit
    res = kumori_klein_edit(
        prompt=prompt, target_image=target_url, reference_images=refs,
        app_name='galactica_aria_snapshot',
        character=f'uid{user_id}',
        ref_filename=snapshot_type,
        feature='aria_snapshot.multiref',
        verbiage=prompt[:500], caller_user_id=user_id,
        tags={'snapshot_type': snapshot_type, 'ref_count_in': len(source_image_urls),
              'ref_count_used': 1 + len(refs)},
    )
    logger.info(f"Image generated in {time.time() - start_time:.1f}s via {res['provider']}")

    timestamp = int(time.time())
    blob_name = f"aria_snapshots/user_{user_id}/{snapshot_type}_{timestamp}.png"
    gcs_url = upload_blob_from_bytes(res['image_bytes'], blob_name, 'image/png')
    if not gcs_url:
        raise Exception("Failed to upload to GCS")
    logger.info(f"Uploaded to GCS: {gcs_url}")

    save_generated_image(
        user_id=user_id,
        category='aria_snapshot',
        subcategory=snapshot_type,
        gcs_url=gcs_url,
        gcs_blob_name=blob_name,
        source_image_url=','.join(source_image_urls),
        prompt_used=prompt,
        caption=caption,
        metadata={
            'time_of_day': tod,
            'mars_sol': context.get('sol_number'),
            'generator': 'nano_banana_pro',
            'source_count': len(source_image_urls),
            'context': {k: v for k, v in context.items() if isinstance(v, (str, int, float))},
        },
    )

    return {
        'gcs_url': gcs_url,
        'caption': caption,
        'snapshot_type': snapshot_type,
        'source_images': source_image_urls,
    }


# ---------------------------------------------------------------------------
# Single-user CLI entry point
# ---------------------------------------------------------------------------

def generate_snapshot_for_user(email, snapshot_type=None, dry_run=False, premium=False):
    """Generate one snapshot for a user looked up by email (partial match).

    Auto-selects a sensible snapshot_type if none given. Uses Flux Kontext by
    default; pass premium=True for Nano Banana Pro.
    """
    from utilities.replicate_utils import FluxGenerator

    user = get_user_by_email(email)
    if not user:
        raise ValueError(f"No user found matching email: {email}")

    user_id = user['id']
    logger.info(f"Found user: {user['email']} (ID: {user_id})")

    captain = get_user_captain(user_id)
    user_data = {
        'captain': captain,
        'discoveries': get_recent_discoveries(user_id),
        'expeditions': get_recent_expeditions(user_id),
        'rover_image': get_user_rover_image(user_id),
        'infrastructure': get_user_infrastructure(user_id),
        'created_at': user.get('created_at'),
    }

    captain_name = captain['commander_name'] if captain else 'Unknown Captain'
    logger.info(f"Captain: {captain_name}")
    logger.info(f"Captain image: {captain['gcs_url'][:60] if captain and captain.get('gcs_url') else 'None'}...")
    logger.info(f"Recent discoveries: {len(user_data['discoveries'])}")
    logger.info(f"Recent expeditions: {len(user_data['expeditions'])}")
    logger.info(f"Has rover image: {bool(user_data['rover_image'])}")
    logger.info(f"Premium mode (Nano Banana Pro): {premium}")

    if premium:
        available_types = NANO_BANANA_PROMPTS
        generator_func = generate_nano_banana_snapshot
    else:
        available_types = SNAPSHOT_PROMPTS
        generator_func = generate_snapshot

    if not snapshot_type:
        if premium:
            if captain and captain.get('gcs_url'):
                snapshot_type = 'captain_aria_discovery' if user_data['discoveries'] else 'captain_aria_base'
            else:
                snapshot_type = 'aria_solo_selfie'
        else:
            if captain and captain.get('gcs_url'):
                snapshot_type = 'captain_discovery' if user_data['discoveries'] else 'captain_base'
            else:
                snapshot_type = 'aria_selfie'
        logger.info(f"Auto-selected snapshot type: {snapshot_type}")

    if snapshot_type not in available_types:
        raise ValueError(
            f"Unknown snapshot type '{snapshot_type}' for {'premium' if premium else 'standard'} mode. "
            f"Available: {list(available_types.keys())}"
        )

    flux = None if dry_run else FluxGenerator()
    return generator_func(user_id, snapshot_type, user_data, flux, dry_run)
