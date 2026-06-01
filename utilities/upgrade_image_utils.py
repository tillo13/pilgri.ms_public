"""
Upgrade Image Generation - First-Reveal System
===============================================

When a player upgrades to a level that has no image (image_url: ''),
this utility generates the image on-demand using Kontext progression.

The first player to trigger generation gets "first reveal" credit.
All subsequent players see the already-generated image.

Usage in upgrades_utils.py:
    from utilities.upgrade_image_utils import maybe_generate_upgrade_image

    # In perform_upgrade(), after successful upgrade:
    image_result = maybe_generate_upgrade_image(category, item_key, new_level)
    if image_result.get('is_first_reveal'):
        # This player discovered the image first!
"""

import logging
import threading
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Track in-progress generations to avoid duplicates
_generation_in_progress = set()


def get_level_image_url(category: str, item_key: str, level: int) -> str:
    """Get the current image_url for a specific level from config.

    Tech branches (#1489): config holds only the tech's BASE icon (its single
    TECH_CATALOG image_url), which anchors level 1. Per-level art (Lv2+) lives in
    the DB, so return the base only at level<=1 — this lets get_best_available_image's
    walk-back prefer a stored higher level and fall back to the base anchor. Without
    this, every tech_* ladder failed "no base image" before reaching the pool.
    """
    if category.startswith('tech_'):
        from config_tech import TECH_CATALOG
        branch = category[len('tech_'):]
        tech = TECH_CATALOG.get(branch, {}).get('techs', {}).get(item_key, {})
        return tech.get('image_url', '') if level <= 1 else ''

    from config_upgrades import UPGRADE_CATALOG

    cat_data = UPGRADE_CATALOG.get(category, {})
    item_data = cat_data.get(item_key, {})
    levels = item_data.get('levels', {})
    level_data = levels.get(level, {})

    return level_data.get('image_url', '')


def get_best_available_image(category: str, item_key: str, level: int) -> str:
    """Find best available image at or below level. Checks DB first, then config."""
    for lv in range(level, 0, -1):
        stored = get_stored_image_url(category, item_key, lv)
        if stored:
            return stored
        if category == 'infrastructure':
            config_url = get_infrastructure_level_image_url(item_key, lv)
        else:
            config_url = get_level_image_url(category, item_key, lv)
        if config_url and config_url.strip():
            return config_url
    return ''


def get_previous_level_image_url(category: str, item_key: str, level: int) -> str:
    """Get the image_url for the previous level (input for Kontext). Checks DB first."""
    if level <= 1:
        return ''
    return get_best_available_image(category, item_key, level - 1)


def needs_image_generation(category: str, item_key: str, level: int) -> bool:
    """Check if this level needs an image generated."""
    current_url = get_level_image_url(category, item_key, level)
    return not current_url or current_url.strip() == ''


def get_kontext_prompt_for_level(category: str, item_key: str, level: int) -> str:
    """
    Generate the Kontext edit prompt for upgrading to this level.
    Uses clean prompts - no numbers, no specific names (causes text in images).
    """
    # "Mars-forged upgrade" progression (generic, works for any item type).
    # The arc: light field bolt-ons early -> chunky Martian rock armor mid ->
    # glowing Sepolia crystals + "grown from geology" at the top. Each entry is
    # ADDITIVE only — bolted on by the hands of Mars tools — never a redraw.
    # Tuned 2026-05-26 from the live drone Lv3->4 "E" comparison (bug #1489):
    # the wrapper below is what preserves the rendered-3D look and stops the
    # model flattening to 2D / restyling / adding smoke or damage.
    # DISCRETE per-level features — each level bolts on a NEW, nameable part and
    # gets visibly bulkier, so adjacent levels are clearly different (not just
    # "more texture"). Reworked 2026-05-26 after wave-3 showed within-band
    # adjacent levels looked identical when the step was only "add more rock"
    # (bug #1489). Escalates: hardware -> rock armor -> basalt -> Sepolia crystals.
    PROGRESSION = {
        2: "Bolt ONE small new antenna or sensor mast onto the top, plus light red dust weathering. Otherwise unchanged — a small distinct new part.",
        3: "Add side-mounted hardware boxes and a few exposed cables/hoses running along the body. Slightly bulkier than before.",
        4: "Rivet CHUNKY reddish Martian rock plates onto the legs/base — the first heavy rock armor. Noticeably bulkier and more rugged.",
        5: "Bolt a bulky Martian rock-armor shell section over the main body and add an exhaust vent. Clearly bigger and more reinforced than before.",
        6: "Wrap most of the body in heavy stacked stone plating with thick reinforcement; the whole machine looks substantially bulkier and armored.",
        7: "Add jagged protruding basalt rock spikes and ridges over the armor — oversized, fortified, battle-hardened. Even bulkier silhouette.",
        8: "Embed several glowing blue-purple Sepolia crystal shards into the rock joints and seams; first clear crystal accents with a faint inner glow.",
        9: "Grow large glowing blue-purple Sepolia crystal clusters out of the rock armor, pulsing with energy. Bulky and clearly crystal-powered.",
        10: "Add a MASSIVE central glowing blue-purple Sepolia crystal core with crystals radiating across the rock-fused body. Looks grown from Mars geology — ancient, powerful, the bulkiest form.",
    }

    material_change = PROGRESSION.get(level, "Bolt on a distinct new Martian rock feature, bulkier and more reinforced than before.")

    return f"""Keep this EXACT same object and its rendered 3D cartoon video-game art style — same soft shading, same bold dark outlines, same camera angle, same base silhouette and pose, same red Mars terrain background. Do NOT flatten to 2D, do NOT redraw, do NOT restyle.
ADDITIVE upgrade only, hand-built in the field with Martian tools — add a DISTINCT NEW part this level so it looks clearly different and BULKIER than the previous version. Do NOT merely re-texture or recolor; physically bolt on new mass: {material_change}
The added rock, crystals, and parts are deliberately attached and reinforcing — NOT broken, crumbling, falling off, or damaged. No smoke, no fire, no debris.
Isolated on red Martian terrain, vibrant reds and oranges, video game asset style."""


def generate_upgrade_image_background(
    category: str,
    item_key: str,
    level: int,
    previous_image_url: str
) -> Optional[str]:
    """
    Generate upgrade image using Kontext (runs in background thread).
    Returns the new GCS URL or None on failure.
    """
    # kumori free-tier edit cascade (HF Qwen → CF Klein), same path as the
    # ARIA album. Replaces the paid Replicate Flux Kontext call. See
    # utilities/kumori_utils.py::kumori_klein_edit.
    from utilities.kumori_utils import kumori_klein_edit
    from utilities.google_cloud_storage_utils import upload_blob_from_bytes
    import time

    generation_key = f"{category}_{item_key}_{level}"

    # Prevent duplicate generations
    if generation_key in _generation_in_progress:
        logger.info(f"Image generation already in progress for {generation_key}")
        return None

    _generation_in_progress.add(generation_key)

    try:
        logger.info(f"🎨 First-Reveal: Generating image for {category}/{item_key} level {level}")

        prompt = get_kontext_prompt_for_level(category, item_key, level)

        # Generate with kumori's free edit cascade — upgrade art is square 1024².
        res = kumori_klein_edit(
            prompt=prompt, target_image=previous_image_url,
            preset='square_hero',
            app_name='galactica_upgrade_image',
            character=f'{category}_{item_key}',
            ref_filename=f'lv{level}',
            feature='upgrade_image.kontext',
            verbiage=prompt[:500],
            tags={'category': category, 'item_key': item_key, 'level': level},
        )

        # Save to GCS
        timestamp = int(time.time())
        blob_name = f"upgrades/{category}_{item_key}_lv{level}_{timestamp}.png"
        gcs_url = upload_blob_from_bytes(res['image_bytes'], blob_name, 'image/png')

        logger.info(f"✅ First-Reveal complete via {res.get('provider')}: {gcs_url}")

        # Update config (in-memory) - the URL will persist to config file
        # For now, store in a separate tracking table
        _store_generated_image_url(category, item_key, level, gcs_url)

        return gcs_url

    except Exception as e:
        logger.error(f"❌ First-Reveal generation failed: {e}")
        return None
    finally:
        _generation_in_progress.discard(generation_key)


def _store_generated_image_url(category: str, item_key: str, level: int, gcs_url: str):
    """Store the generated image URL in the database."""
    from utilities.postgres.core import db_cursor

    try:
        with db_cursor(commit=True) as cur:
            # Create table if not exists
            cur.execute("""
                CREATE TABLE IF NOT EXISTS pilgrim.upgrade_images (
                    category VARCHAR(50) NOT NULL,
                    item_key VARCHAR(50) NOT NULL,
                    level INTEGER NOT NULL,
                    image_url TEXT NOT NULL,
                    generated_at TIMESTAMP DEFAULT NOW(),
                    first_reveal_user_id INTEGER,
                    PRIMARY KEY (category, item_key, level)
                )
            """)

            # Insert or update
            cur.execute("""
                INSERT INTO pilgrim.upgrade_images (category, item_key, level, image_url)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (category, item_key, level)
                DO UPDATE SET image_url = %s, generated_at = NOW()
            """, (category, item_key, level, gcs_url, gcs_url))

        logger.info(f"Stored generated image URL in DB: {category}/{item_key} lv{level}")
    except Exception as e:
        logger.error(f"Failed to store image URL: {e}")


def get_stored_image_url(category: str, item_key: str, level: int) -> Optional[str]:
    """Get the stored image URL from database. Per-request memoized via the full image map — so repeat
    calls across get_best_available_image walk-back loops cost zero DB round-trips after the first."""
    image_map = get_all_stored_images()
    return image_map.get((category, item_key, int(level)))


def get_all_stored_images() -> Dict[tuple, str]:
    """Bulk-fetch every stored upgrade image as {(category, item_key, level): url}.
    Per-request memoized — one DB call per Flask request regardless of caller count."""
    from utilities.postgres.core import db_cursor, request_memo

    def _load():
        out: Dict[tuple, str] = {}
        try:
            with db_cursor() as cur:
                cur.execute("SELECT category, item_key, level, image_url FROM pilgrim.upgrade_images")
                for row in cur.fetchall():
                    if row['image_url']:
                        out[(row['category'], row['item_key'], int(row['level']))] = row['image_url']
        except Exception as e:
            logger.error(f"get_all_stored_images failed: {e}")
        return out

    return request_memo(('get_all_stored_images',), _load)


def get_best_available_image_from_map(category: str, item_key: str, level: int, image_map: Dict[tuple, str]) -> str:
    """Same walk-back logic as get_best_available_image but uses a pre-fetched image_map (zero DB calls)."""
    for lv in range(level, 0, -1):
        stored = image_map.get((category, item_key, lv))
        if stored:
            return stored
        if category == 'infrastructure':
            config_url = get_infrastructure_level_image_url(item_key, lv)
        else:
            config_url = get_level_image_url(category, item_key, lv)
        if config_url and config_url.strip():
            return config_url
    return ''


def maybe_generate_upgrade_image(
    category: str,
    item_key: str,
    level: int,
    user_id: int = None
) -> Dict[str, Any]:
    """
    Check if image generation is needed and trigger it if so.

    Returns:
        {
            'needs_generation': bool,
            'is_first_reveal': bool,
            'image_url': str or None,
            'generation_started': bool
        }
    """
    # First check if we have a stored URL in DB (from previous generation)
    stored_url = get_stored_image_url(category, item_key, level)
    if stored_url:
        return {
            'needs_generation': False,
            'is_first_reveal': False,
            'image_url': stored_url,
            'generation_started': False
        }

    # Check if config has an image
    config_url = get_level_image_url(category, item_key, level)
    if config_url and config_url.strip():
        return {
            'needs_generation': False,
            'is_first_reveal': False,
            'image_url': config_url,
            'generation_started': False
        }

    # Need to generate! Get the previous level's image as input
    previous_url = get_previous_level_image_url(category, item_key, level)
    if not previous_url:
        # Can't generate without a source image
        logger.warning(f"No source image for {category}/{item_key} level {level}")
        return {
            'needs_generation': True,
            'is_first_reveal': False,
            'image_url': None,
            'generation_started': False,
            'error': 'No source image available'
        }

    # Mark this user as the first reveal discoverer
    if user_id:
        _mark_first_reveal(category, item_key, level, user_id)

    # Start background generation
    thread = threading.Thread(
        target=generate_upgrade_image_background,
        args=(category, item_key, level, previous_url),
    )
    thread.start()

    return {
        'needs_generation': True,
        'is_first_reveal': True,
        'image_url': None,  # Will be available after generation completes
        'generation_started': True
    }


def _mark_first_reveal(category: str, item_key: str, level: int, user_id: int):
    """Mark a user as the first to reveal this upgrade level."""
    from utilities.postgres.core import db_cursor

    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO pilgrim.upgrade_images (category, item_key, level, image_url, first_reveal_user_id)
                VALUES (%s, %s, %s, '', %s)
                ON CONFLICT (category, item_key, level) DO NOTHING
            """, (category, item_key, level, user_id))
    except Exception as e:
        logger.warning(f"Failed to mark first reveal: {e}")


def is_first_reveal_user(category: str, item_key: str, level: int, user_id: int) -> bool:
    """Check if this user was the first to reveal this upgrade level."""
    from utilities.postgres.core import db_cursor

    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT first_reveal_user_id FROM pilgrim.upgrade_images
                WHERE category = %s AND item_key = %s AND level = %s
            """, (category, item_key, level))
            row = cur.fetchone()
            return row and row['first_reveal_user_id'] == user_id
    except:
        return False


# ============================================================================
# TECH TREE IMAGE GENERATION (per-tech, per-branch-level)
# ============================================================================

def get_tech_image_from_db(branch: str, tech_key: str, branch_level: int) -> Optional[str]:
    """Get stored tech image from DB for a specific tech at a branch level."""
    return get_stored_image_url(f"tech_{branch}", tech_key, branch_level)


def generate_tech_branch_icons(branch: str, branch_level: int, user_id: int = None):
    """
    Generate new icons for all 5 techs in a branch at a new level.
    Each tech's level 1 image is Kontext-edited to show progression.
    Called when a branch levels up (all 5 techs complete).
    """
    from config_tech import TECH_CATALOG
    from utilities.kumori_utils import kumori_klein_edit
    from utilities.google_cloud_storage_utils import upload_blob_from_bytes
    import time

    branch_data = TECH_CATALOG.get(branch)
    if not branch_data:
        logger.error(f"Unknown branch: {branch}")
        return

    techs = branch_data.get('techs', {})
    category = f"tech_{branch}"

    for tech_key, tech_data in techs.items():
        generation_key = f"tech_{branch}_{tech_key}_{branch_level}"
        if generation_key in _generation_in_progress:
            continue

        # Check if already generated
        existing = get_stored_image_url(category, tech_key, branch_level)
        if existing:
            continue

        source_url = tech_data.get('image_url', '')
        if not source_url:
            logger.warning(f"No source image for {branch}/{tech_key}")
            continue

        _generation_in_progress.add(generation_key)
        try:
            prompt = get_kontext_prompt_for_level(category, tech_key, branch_level)
            res = kumori_klein_edit(
                prompt=prompt, target_image=source_url,
                preset='square_hero',
                app_name='galactica_tech_icon',
                character=f'{branch}_{tech_key}',
                ref_filename=f'lv{branch_level}',
                feature='tech_icon.kontext',
                verbiage=prompt[:500], caller_user_id=user_id,
                tags={'branch': branch, 'tech_key': tech_key, 'level': branch_level},
            )

            timestamp = int(time.time())
            blob_name = f"tech_icons/{branch}_{tech_key}_lv{branch_level}_{timestamp}.png"
            gcs_url = upload_blob_from_bytes(res['image_bytes'], blob_name, 'image/png')

            _store_generated_image_url(category, tech_key, branch_level, gcs_url)

            if user_id:
                _mark_first_reveal(category, tech_key, branch_level, user_id)

            logger.info(f"Tech icon generated: {branch}/{tech_key} lv{branch_level} → {gcs_url}")
        except Exception as e:
            logger.error(f"Tech icon generation failed for {branch}/{tech_key} lv{branch_level}: {e}")
        finally:
            _generation_in_progress.discard(generation_key)


# ============================================================================
# INFRASTRUCTURE IMAGE GENERATION
# ============================================================================

def get_infrastructure_level_image_url(structure_type: str, level: int) -> str:
    """Get the current image_url for an infrastructure building level from config."""
    from config_infrastructure import INFRASTRUCTURE_CATALOG

    building_data = INFRASTRUCTURE_CATALOG.get(structure_type, {})
    levels = building_data.get('levels', {})
    level_data = levels.get(level, {})

    return level_data.get('image_url', '')


def get_previous_infrastructure_level_image_url(structure_type: str, level: int) -> str:
    """Get the image_url for the previous infrastructure level. Checks DB first."""
    if level <= 1:
        return ''
    return get_best_available_image('infrastructure', structure_type, level - 1)


def maybe_generate_infrastructure_image(
    structure_type: str,
    level: int,
    user_id: int = None
) -> Dict[str, Any]:
    """
    Check if infrastructure image generation is needed and trigger it if so.
    Uses the same database table as upgrades (with category='infrastructure').

    Args:
        structure_type: The building type (e.g., 'solar_array', 'refinery')
        level: The building level (1-10)
        user_id: Optional user ID to mark as first revealer

    Returns:
        {
            'needs_generation': bool,
            'is_first_reveal': bool,
            'image_url': str or None,
            'generation_started': bool
        }
    """
    category = "infrastructure"
    item_key = structure_type

    # Check DB for stored image
    stored_url = get_stored_image_url(category, item_key, level)
    if stored_url:
        return {
            'needs_generation': False,
            'is_first_reveal': False,
            'image_url': stored_url,
            'generation_started': False
        }

    # Check config for image
    config_url = get_infrastructure_level_image_url(structure_type, level)
    if config_url and config_url.strip():
        return {
            'needs_generation': False,
            'is_first_reveal': False,
            'image_url': config_url,
            'generation_started': False
        }

    # Need to generate! Get previous level image
    previous_url = get_previous_infrastructure_level_image_url(structure_type, level)
    if not previous_url:
        logger.warning(f"No source image for infrastructure {structure_type} level {level}")
        return {
            'needs_generation': True,
            'is_first_reveal': False,
            'image_url': None,
            'generation_started': False,
            'error': 'No source image available'
        }

    # Mark first reveal
    if user_id:
        _mark_first_reveal(category, item_key, level, user_id)

    # Start background generation
    thread = threading.Thread(
        target=generate_upgrade_image_background,
        args=(category, item_key, level, previous_url),
    )
    thread.start()

    return {
        'needs_generation': True,
        'is_first_reveal': True,
        'image_url': None,
        'generation_started': True
    }