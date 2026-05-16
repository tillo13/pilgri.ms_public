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
from utilities.google_cloud_storage_utils import upload_blob_from_bytes_with_thumbnail
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

            # Collect reference images based on Claude's scene flags.
            # scene_actors mirrors source_image_urls 1:1 with human-readable names
            # so the album modal can render a "what's in this scene" chip row.
            source_image_urls = []
            scene_actors = []
            if involves_captain and captain_url:
                source_image_urls.append(captain_url)
                scene_actors.append({'type': 'captain', 'name': captain_name, 'image_url': captain_url})
            if involves_aria:
                source_image_urls.append(ARIA_IMAGE_URL)
                scene_actors.append({'type': 'aria', 'name': 'ARIA', 'image_url': ARIA_IMAGE_URL})
            if involves_scientist and scientist_url:
                source_image_urls.append(scientist_url)
                _sci_name = (scientist.get('name') if scientist else None) or 'Scientist'
                scene_actors.append({'type': 'scientist', 'name': _sci_name, 'image_url': scientist_url})
            if involves_discovery and discovery_url:
                source_image_urls.append(discovery_url)
                _disc_name = next((d.get('name') for d in discoveries if d.get('gcs_url') == discovery_url), None) or 'Discovery'
                scene_actors.append({'type': 'discovery', 'name': _disc_name, 'image_url': discovery_url})
            if involves_vehicle and vehicles and vehicles[0].get('image_url'):
                source_image_urls.append(vehicles[0]['image_url'])
                _veh_name = vehicles[0].get('name') or (vehicles[0].get('type') or 'Vehicle').title()
                scene_actors.append({'type': 'vehicle', 'name': _veh_name, 'image_url': vehicles[0]['image_url']})

            from utilities.kumori_utils import kumori_klein_edit, kumori_klein_generate
            refs_used_count = 0
            if pure_landscape or len(source_image_urls) == 0:
                logger.info("  Generating via kumori text-to-image (pure landscape)...")
                start_time = time.time()
                res = kumori_klein_generate(
                    prompt=prompt, preset='aria_journal',
                    feature='aria_snapshot.landscape',
                    verbiage=prompt[:500], caller_user_id=user_id,
                    tags={'scene_type': scene_type, 'pure_landscape': True},
                )
                generator_type = f'claude_dynamic + kumori_generate ({res.get("provider")})'
            else:
                # kumori per-rung ref caps (live_state.max_refs, 2026-05-16):
                #   CF Klein=4, HF Qwen=3, HF Qwen Fast=3, HF Kontext-Dev=1
                # Galactica caps at 3 — the highest value the vendored kumori_api_client
                # currently asserts (client.py:449 `len(refs) > 3` raises). Once kumori's
                # imggen_edit asserts is bumped to 4, raise this to KUMORI_MAX_REFS=4
                # to unlock CF Klein's 4-ref headroom. source_image_urls is already
                # priority-ordered by Claude (captain → aria → scientist → discovery → vehicle).
                KUMORI_MAX_REFS = 3
                target_url = source_image_urls[0]
                refs = source_image_urls[1:1 + KUMORI_MAX_REFS]
                dropped = source_image_urls[1 + KUMORI_MAX_REFS:]
                refs_used_count = 1 + len(refs)
                if dropped:
                    logger.info(f"  Pruned {len(dropped)} refs over kumori's 3-ref cap")
                logger.info(f"  Generating via kumori edit (target + {len(refs)} refs, was {len(source_image_urls)})...")
                start_time = time.time()
                res = kumori_klein_edit(
                    prompt=prompt, target_image=target_url, reference_images=refs,
                    preset='aria_journal',
                    app_name='galactica_aria_snapshot',
                    character=f'uid{user_id}',
                    ref_filename=scene_type,
                    feature='aria_snapshot.multiref',
                    verbiage=prompt[:500], caller_user_id=user_id,
                    tags={'scene_type': scene_type, 'ref_count_in': len(source_image_urls),
                          'ref_count_used': refs_used_count},
                )
                generator_type = f'claude_dynamic + kumori_edit ({res.get("provider")})'

            logger.info(f"  Image generated in {time.time() - start_time:.1f}s")

            timestamp = int(time.time())
            blob_name = f"aria_snapshots/user_{user_id}/{scene_type}_{timestamp}.png"
            upload_result = upload_blob_from_bytes_with_thumbnail(
                res['image_bytes'], blob_name, 'image/png', thumbnail_width=400,
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
                    'scene_actors': scene_actors,
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
            results.append({
                'error': f'{type(e).__name__}: {e}',
                'snapshot_index': i + 1,
                'gcs_url': None,
            })
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
            successes = [r for r in results if r.get('gcs_url')]
            failures = [r for r in results if not r.get('gcs_url')]
            summary['processed_users'] += 1
            summary['total_snapshots'] += len(successes)
            summary['cost_estimate'] += len(successes) * 0.20
            if failures:
                # All per-snapshot errors land here so they're visible in the
                # admin summary instead of silently swallowed.
                summary['failed_users'].append({
                    'email': email, 'user_id': user_id,
                    'snapshot_errors': [f.get('error') for f in failures],
                })
        except Exception as e:
            logger.error(f"Failed to process user {email}: {e}")
            summary['failed_users'].append({'email': email, 'user_id': user_id, 'error': str(e)})

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
