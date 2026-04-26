"""Daily ARIA snapshot orchestrator — the cron entry point.

Uses Claude to generate fresh per-user prompts from live colony data (not
hardcoded templates). Picks the right generator based on whether the scene
has reference images:

- pure_landscape / no refs → Flux Pro text-to-image
- has refs → Nano Banana Pro (character consistency)
"""

import json
import logging
import random
import time

from config import FLUX_MODEL
from utilities.claude_utils import generate_aria_snapshot_prompt
from utilities.google_cloud_storage_utils import upload_blob_from_url_with_thumbnail
from utilities.postgres.core import db_cursor

from utilities.aria.photos.data import (
    get_active_users_for_snapshots,
    get_active_expeditions,
    get_expedition_stats,
    get_recent_discoveries,
    get_recent_events,
    get_recent_expeditions,
    get_recent_purchases,
    get_user_balance,
    get_user_captain,
    get_user_infrastructure,
    get_user_upgrades,
)
from utilities.aria.photos.prompts import (
    ARIA_IMAGE_URL,
    calculate_sol_number,
    get_current_mars_time,
)
from utilities.aria.photos.storage import save_generated_image

logger = logging.getLogger(__name__)


def generate_daily_snapshots_for_user(user_id, email, flux, dry_run=False, num_snapshots=1, forced_category=None):
    """Generate `num_snapshots` snapshots for one user using Claude-generated prompts.

    Claude invents the scene fresh each time based on:
    - actual recent discoveries, expeditions, purchases
    - real Mars sol + time of day
    - captain stats, crew missions, scientist, vehicles, building queue
    - last-24h events

    Returns a list of result dicts (one per successful snapshot).
    """
    results = []

    captain = get_user_captain(user_id)
    discoveries = get_recent_discoveries(user_id, limit=10)
    expeditions = get_recent_expeditions(user_id, limit=5)
    active_expeditions = get_active_expeditions(user_id)
    infrastructure = get_user_infrastructure(user_id)
    recent_purchases = get_recent_purchases(user_id)
    upgrades = get_user_upgrades(user_id)
    stats = get_expedition_stats(user_id)
    balance = get_user_balance(user_id)
    events = get_recent_events(user_id)

    from utilities.postgres.users import get_user_scientist
    from utilities.postgres.trails import get_crew_mission_status
    from utilities.postgres.shop import get_building_upgrades
    from utilities.upgrades_utils import get_user_owned_vehicles

    scientist = get_user_scientist(user_id)
    crew_missions = get_crew_mission_status(user_id)

    building_raw = get_building_upgrades(user_id)
    building_items = (
        [{'name': b.get('item_id', 'unknown'), 'ready_at': str(b.get('ready_at', ''))} for b in building_raw]
        if building_raw else []
    )

    vehicles = get_user_owned_vehicles(user_id)

    if not captain or not captain.get('gcs_url'):
        logger.warning(f"User {email} has no captain image, skipping")
        return results

    captain_name = captain.get('commander_name', 'Unknown')
    captain_url = captain.get('gcs_url')

    scientist_url = scientist.get('image_url') if scientist else None
    discovery_urls = [d.get('gcs_url') for d in discoveries if d.get('gcs_url')]
    discovery_url = random.choice(discovery_urls) if discovery_urls else None

    logger.info("  Reference images available:")
    logger.info(f"    Captain: {bool(captain_url)}")
    logger.info(f"    Scientist: {bool(scientist_url)}")
    logger.info(f"    Discovery: {len(discovery_urls)} images")

    mars_time = get_current_mars_time()
    with db_cursor() as cur:
        cur.execute("SELECT created_at FROM pilgrim.users WHERE id = %s", (user_id,))
        user_row = cur.fetchone()
    mars_sol = calculate_sol_number(user_row['created_at'] if user_row else None)

    user_context = {
        'captain_name': captain_name,
        'captain_stats': {
            'leadership': captain.get('commander_leadership', 5),
            'strategy': captain.get('commander_strategy', 5),
            'exploration': captain.get('commander_exploration', 5),
            'logistics': captain.get('commander_logistics', 5),
            'charisma': captain.get('commander_charisma', 5),
        },
        'recent_discoveries': [dict(d) for d in discoveries] if discoveries else [],
        'recent_expeditions': [dict(e) for e in expeditions] if expeditions else [],
        'active_expeditions': [dict(e) for e in active_expeditions] if active_expeditions else [],
        'infrastructure': [dict(i) for i in infrastructure] if infrastructure else [],
        'recent_purchases': [dict(p) for p in recent_purchases] if recent_purchases else [],
        'upgrades': upgrades or {},
        'total_expeditions': stats.get('total_expeditions', 0) if stats else 0,
        'total_discoveries': stats.get('total_discoveries', 0) if stats else 0,
        'shard_balance': balance,
        'mars_sol': mars_sol,
        'mars_time': mars_time,
        'last_24h_events': events,
        'scientist': {
            'name': scientist.get('name') if scientist else None,
            'specialty': scientist.get('specialty') if scientist else None,
        } if scientist else None,
        'crew_missions': {
            'captain': crew_missions.get('captain') if crew_missions else None,
            'scientist': crew_missions.get('scientist') if crew_missions else None,
            'aria': crew_missions.get('aria') if crew_missions else None,
        } if crew_missions else None,
        'building_items': building_items,
        'vehicles': [
            {'type': v.get('vehicle_type'), 'name': v.get('name'), 'level': v.get('level')}
            for v in (vehicles or [])
        ],
    }

    logger.info(f"Generating {num_snapshots} daily snapshots for {captain_name} ({email})")
    logger.info(f"  Mars Sol: {mars_sol}, Time: {mars_time}")
    logger.info(f"  Total expeditions: {user_context['total_expeditions']}, discoveries: {user_context['total_discoveries']}")
    logger.info(f"  Recent events: {len(events)}")

    for i in range(num_snapshots):
        try:
            logger.info(f"\n  [{i + 1}/{num_snapshots}] Asking Claude to generate unique prompt...")

            # Retry Claude up to 3 times on JSON parse errors
            prompt_data = None
            for attempt in range(3):
                try:
                    prompt_data = generate_aria_snapshot_prompt(user_context, forced_category=forced_category)
                    break
                except (json.JSONDecodeError, ValueError) as retry_err:
                    if attempt < 2:
                        logger.warning(f"  ⚠ Claude prompt attempt {attempt + 1} failed: {retry_err}, retrying...")
                        time.sleep(2)
                    else:
                        raise
            if not prompt_data:
                raise ValueError("Failed to generate prompt after 3 attempts")

            scene_type = prompt_data.get('scene_type', 'daily_scene')
            prompt = prompt_data['prompt']
            caption = prompt_data['caption']
            involves_captain = prompt_data.get('involves_captain', True)
            involves_aria = prompt_data.get('involves_aria', True)
            involves_scientist = prompt_data.get('involves_scientist', False)
            involves_discovery = prompt_data.get('involves_discovery', False)
            involves_vehicle = prompt_data.get('involves_vehicle', False)
            pure_landscape = prompt_data.get('pure_landscape', False)

            logger.info(f"  Scene type: {scene_type}")
            logger.info(
                f"  Involves: captain={involves_captain}, ARIA={involves_aria}, "
                f"scientist={involves_scientist}, discovery={involves_discovery}, vehicle={involves_vehicle}"
            )
            logger.info(f"  Pure landscape: {pure_landscape}")
            logger.info(f"  Caption: {caption[:80]}...")

            if dry_run:
                logger.info(f"  DRY RUN - Prompt:\n{prompt[:500]}...")
                results.append({
                    'gcs_url': None,
                    'caption': caption,
                    'snapshot_type': scene_type,
                    'prompt': prompt,
                    'involves_captain': involves_captain,
                    'involves_aria': involves_aria,
                })
                continue

            # Collect reference images based on Claude's scene flags
            source_image_urls = []
            if involves_captain and captain_url:
                source_image_urls.append(captain_url)
            if involves_aria:
                source_image_urls.append(ARIA_IMAGE_URL)
            if involves_scientist and scientist_url:
                source_image_urls.append(scientist_url)
            if involves_discovery and discovery_url:
                source_image_urls.append(discovery_url)
            if involves_vehicle and vehicles and vehicles[0].get('image_url'):
                source_image_urls.append(vehicles[0]['image_url'])

            if pure_landscape or len(source_image_urls) == 0:
                logger.info("  Generating with Flux Pro (pure landscape, no reference images)...")
                start_time = time.time()
                from utilities.replicate_utils import _killswitched_run
                result = _killswitched_run(flux.client, FLUX_MODEL,
                                            {'prompt': prompt, 'aspect_ratio': '4:3'},
                                            feature='aria_snapshot')
                replicate_url = result[0] if isinstance(result, list) else str(result)
                generator_type = 'claude_dynamic + flux_pro'
            else:
                logger.info(f"  Generating with Nano Banana Pro ({len(source_image_urls)} reference images)...")
                logger.info(f"    Images: {[url[:50] + '...' for url in source_image_urls]}")
                start_time = time.time()
                replicate_url = flux.nano_banana_edit(
                    prompt=prompt,
                    image_urls=source_image_urls,
                    resolution="2K",
                    aspect_ratio="4:3",
                )
                generator_type = 'claude_dynamic + nano_banana_pro'

            logger.info(f"  Image generated in {time.time() - start_time:.1f}s")

            timestamp = int(time.time())
            blob_name = f"aria_snapshots/user_{user_id}/{scene_type}_{timestamp}.png"
            upload_result = upload_blob_from_url_with_thumbnail(
                replicate_url, blob_name, 'image/png', thumbnail_width=400,
            )
            if not upload_result:
                raise Exception("Failed to upload to GCS")

            gcs_url = upload_result['url']
            thumbnail_url = upload_result.get('thumbnail_url')

            logger.info(f"  ✓ Uploaded: {gcs_url[:60]}...")
            if thumbnail_url:
                logger.info(f"  ✓ Thumbnail: {thumbnail_url[:60]}...")

            save_generated_image(
                user_id=user_id,
                category='aria_snapshot',
                subcategory=scene_type,
                gcs_url=gcs_url,
                gcs_blob_name=blob_name,
                source_image_url=','.join(source_image_urls) if source_image_urls else None,
                prompt_used=prompt,
                caption=caption,
                thumbnail_url=thumbnail_url,
                metadata={
                    'time_of_day': mars_time,
                    'mars_sol': mars_sol,
                    'generator': generator_type,
                    'involves_captain': involves_captain,
                    'involves_aria': involves_aria,
                    'involves_scientist': involves_scientist,
                    'involves_discovery': involves_discovery,
                    'involves_vehicle': involves_vehicle,
                    'pure_landscape': pure_landscape,
                    'reference_image_count': len(source_image_urls),
                },
            )

            results.append({
                'gcs_url': gcs_url,
                'thumbnail_url': thumbnail_url,
                'caption': caption,
                'snapshot_type': scene_type,
                'source_images': source_image_urls,
            })

            logger.info(f"  ✓ [{i + 1}/{num_snapshots}] {scene_type} complete")
            time.sleep(2)

        except Exception as e:
            logger.error(f"  ✗ Failed to generate snapshot {i + 1}: {e}")
            import traceback
            traceback.print_exc()
            continue

    return results


def generate_daily_snapshots(dry_run=False, limit=None):
    """Cron entry point — generate daily snapshots for all active users.

    Returns a summary dict with processed/failed counts and cost estimate.
    """
    from utilities.replicate_utils import FluxGenerator

    logger.info("=" * 60)
    logger.info("DAILY SNAPSHOT GENERATION")
    logger.info(f"Dry run: {dry_run}")
    logger.info("=" * 60)

    users = get_active_users_for_snapshots()
    total_users = len(users)
    if limit:
        users = users[:limit]
    logger.info(f"Found {total_users} active users, processing {len(users)}")

    flux = None if dry_run else FluxGenerator()

    summary = {
        'total_users': total_users,
        'processed_users': 0,
        'total_snapshots': 0,
        'failed_users': [],
        'cost_estimate': 0,  # ~$0.20 per image
    }

    for user in users:
        user_id = user['id']
        email = user['email']
        try:
            results = generate_daily_snapshots_for_user(user_id, email, flux, dry_run)
            summary['processed_users'] += 1
            summary['total_snapshots'] += len(results)
            summary['cost_estimate'] += len(results) * 0.20
        except Exception as e:
            logger.error(f"Failed to process user {email}: {e}")
            summary['failed_users'].append({'email': email, 'error': str(e)})

        # Pause to avoid pinning the App Engine instance.
        if not dry_run:
            time.sleep(10)

    logger.info("=" * 60)
    logger.info("DAILY SNAPSHOT GENERATION COMPLETE")
    logger.info(f"Processed: {summary['processed_users']}/{total_users} users")
    logger.info(f"Generated: {summary['total_snapshots']} snapshots")
    logger.info(f"Est. cost: ${summary['cost_estimate']:.2f}")
    if summary['failed_users']:
        logger.info(f"Failed: {len(summary['failed_users'])} users")
    logger.info("=" * 60)

    return summary
