"""Robot visual pipeline — Kontext-chained per-captain renders.

Step 4c of the 2026-04-10 plan. Replaces db_robot._stub_advance_one_stage()
with a real Flux Kontext call that builds each captain's robot progressively
over 5 stages, using the prior stage image as input to the next.

Flow per stage advance:
  1. tick_robot_build() detects stage_ready_at has elapsed
  2. start_background_advance() spawns a daemon thread (dedupe-locked)
  3. _run_stage() runs the slow work:
        - build prompt from captain profile + source manifest
        - FluxGenerator.kontext_edit(prev_image_url, prompt)
        - upload_blob_from_url() → permanent GCS URL
        - db_robot.log_stage() persists manifest + image + fake tx
  4. Next page visit sees the new image.

Failure handling:
  - Any exception reverts to stub advance (placeholder image) so the build
    still progresses. Luke never gets stuck on a blank robot because Flux
    was down.
  - Thread dedupe lock is in-memory (per instance). Multiple GCP instances
    could race and spawn dupes — acceptable since log_stage is idempotent
    on (user_id, stage_idx) via ON CONFLICT.

Sepolia breadcrumbs (plan decision #14, the ARG hook) are NOT wired in this
step — the manifest is still persisted to robot_stage_log exactly as it
will be once the tx layer lands, so wiring Sepolia later is a drop-in.
"""

import logging
import threading
from datetime import datetime
from typing import Dict, Any, Optional

from utilities.postgres.core import db_cursor
from utilities.postgres.robot import (
    ROBOT_STAGES,
    PLACEHOLDER_STAGE_IMAGE,
    STAGE_PLACEHOLDER_IMAGES,
    log_stage,
    _stub_advance_one_stage,
)

logger = logging.getLogger(__name__)


# ============================================================================
# STAGE PROMPTS — Kontext edit instructions chained stage→stage.
# ============================================================================
# Each stage takes the prior stage's image as input and layers one incremental
# change. Prompts intentionally reference the SAME Mars aesthetic the rest of
# the game uses (see CLAUDE.md Image Generation Style + PILGRIMS.md Visual
# Style Guide): Martian materials, Sepolia crystal accents, isolated on red
# terrain, cartoon video-game asset style. Captain-specific seeds are
# interpolated at call time via _build_stage_prompt().
#
# {source} token is replaced with a one-liner from the stage source manifest:
#   "a {rarity} {item_name} recovered at {landmark_name}".
STAGE_PROMPT_TEMPLATES = {
    1: (
        "Transform this Martian regolith foundation into the beginnings of a "
        "humanoid robot skeleton. Rough load-bearing chassis made of rust-red "
        "clay blocks lashed together with crystal rebar. Still shapeless but "
        "recognizably a frame. Incorporate traces of {source}. "
        "Cartoon video game item with bold outlines and stylized proportions, "
        "isolated on red Martian terrain, vibrant reds and oranges reflecting "
        "Mars atmosphere, video game asset style."
    ),
    2: (
        "Add rough hull plating to this robot frame — pressure-rated panels "
        "shaped from compressed Martian clay, jointed with Sepolia crystal "
        "pins. Torso and shoulder plates now recognizable but unfinished. "
        "The new plating is forged from {source}. "
        "Cartoon video game item with bold outlines and stylized proportions, "
        "isolated on red Martian terrain, vibrant reds and oranges reflecting "
        "Mars atmosphere, video game asset style."
    ),
    3: (
        "Install a crystalline reactor core at the chest of this robot — a "
        "hexagonal Sepolia crystal cluster glowing cyan through the clay "
        "plating. Power conduits trace along the limbs. The crystal was "
        "cut from {source}. "
        "Cartoon video game item with bold outlines and stylized proportions, "
        "isolated on red Martian terrain, vibrant reds and oranges reflecting "
        "Mars atmosphere, video game asset style."
    ),
    4: (
        "Carve an optical sensor array into this robot's face — a cluster of "
        "lens-shaped Sepolia crystals in the head, backlit cyan. Add subtle "
        "Sepolia crystal accents to the joints. Lenses ground from {source}. "
        "Cartoon video game item with bold outlines and stylized proportions, "
        "isolated on red Martian terrain, vibrant reds and oranges reflecting "
        "Mars atmosphere, video game asset style."
    ),
    5: (
        "Final assembly — add painted Mars mission glyphs to the chest plate, "
        "a signal antenna rising from the shoulder, and a heroic pose. The "
        "robot is now complete: awakened, glowing Sepolia eyes, standing "
        "ready to serve its captain. Finishing touches use {source}. "
        "Cartoon video game item with bold outlines and stylized proportions, "
        "isolated on red Martian terrain, vibrant reds and oranges reflecting "
        "Mars atmosphere, video game asset style."
    ),
}


def _format_source_phrase(source: Dict[str, Any]) -> str:
    """Collapse a stage source manifest into a one-liner for prompt interpolation."""
    item = source.get('item_name') or 'recovered fragment'
    rarity = source.get('rarity') or 'common'
    landmark = source.get('landmark_name') or 'an unknown site'
    return f"a {rarity} {item} recovered at {landmark}"


def _get_captain_name(user_id: int) -> str:
    """
    Pull the captain's scientist/commander name for prompt seeding. Falls back
    to 'Captain #<id>' if nothing is set — keeps the prompt deterministic.
    """
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT commander_name
                FROM pilgrim.replicate_assets
                WHERE user_id = %s
                  AND asset_type IN ('character_image', 'edited_image')
                  AND is_primary_character = true
                  AND is_deleted = false
                LIMIT 1
            """, (user_id,))
            row = cur.fetchone()
            if row and row['commander_name']:
                return str(row['commander_name'])[:40]
    except Exception as e:
        logger.warning(f"_get_captain_name user={user_id} fallback: {e}")
    return f"Captain #{user_id}"


def _build_stage_prompt(user_id: int, stage_idx: int, source: Dict[str, Any]) -> str:
    """
    Interpolate the template for this stage with captain-specific seeds.
    Stage 5's prompt gets the captain name suffix so the final portrait
    subtly carries the captain's identity.
    """
    template = STAGE_PROMPT_TEMPLATES.get(stage_idx, STAGE_PROMPT_TEMPLATES[5])
    prompt = template.format(source=_format_source_phrase(source))
    if stage_idx == 5:
        captain = _get_captain_name(user_id)
        prompt += f" Forged for {captain}."
    return prompt


# ============================================================================
# DEDUPE LOCK — in-memory guard so concurrent /crew hits don't spawn dupe
# threads. log_stage() is idempotent on (user_id, stage_idx) so even if we
# race across GCP instances, the DB stays consistent.
# ============================================================================
_IN_FLIGHT: set = set()
_IN_FLIGHT_LOCK = threading.Lock()


def _acquire(user_id: int, stage_idx: int) -> bool:
    key = (user_id, stage_idx)
    with _IN_FLIGHT_LOCK:
        if key in _IN_FLIGHT:
            return False
        _IN_FLIGHT.add(key)
        return True


def _release(user_id: int, stage_idx: int) -> None:
    with _IN_FLIGHT_LOCK:
        _IN_FLIGHT.discard((user_id, stage_idx))


# ============================================================================
# CORE STAGE RUNNER
# ============================================================================

def _get_seed_image_url(user_id: int, stage_idx: int) -> str:
    """
    Resolve the 'input image' for this stage's Kontext edit. Stage 1 seeds
    from the 'frame' cairn (a regolith foundation, NOT a finished robot) so
    the Kontext chain can actually build progressively. Stages 2-5 use the
    prior stage's already-uploaded GCS image from the robot row.
    """
    if stage_idx <= 1:
        return STAGE_PLACEHOLDER_IMAGES['frame']

    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT image_url FROM pilgrim.robot_stage_log
                WHERE user_id = %s AND stage_idx = %s
                LIMIT 1
            """, (user_id, stage_idx - 1))
            row = cur.fetchone()
            if row and row.get('image_url'):
                return row['image_url']
    except Exception as e:
        logger.warning(f"_get_seed_image_url user={user_id} stage={stage_idx}: {e}")

    return PLACEHOLDER_STAGE_IMAGE


def _run_stage(user_id: int, stage_idx: int, source: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Synchronous stage advance — Kontext edit + GCS upload + log_stage.
    Returns the log_stage result on success, None on failure. Failure
    is logged; caller falls back to stub.
    """
    tag = f"[robot user={user_id} stage={stage_idx}]"
    try:
        from utilities.replicate_utils import FluxGenerator
        from utilities.google_cloud_storage_utils import upload_blob_from_url
    except ImportError as e:
        logger.exception(f"{tag} imports failed — cannot run Kontext: {e}")
        return None

    stage = ROBOT_STAGES[stage_idx - 1]
    seed_url = _get_seed_image_url(user_id, stage_idx)
    prompt = _build_stage_prompt(user_id, stage_idx, source)
    logger.info(f"{tag} 🤖 begin key={stage['key']} seed={seed_url[:80]}")

    # 1) Flux Kontext edit
    try:
        flux = FluxGenerator()
    except Exception as e:
        logger.exception(f"{tag} FluxGenerator init failed: {e}")
        return None
    try:
        replicate_url = flux.kontext_edit(seed_url, prompt)
        if not replicate_url:
            logger.error(f"{tag} Kontext returned empty URL")
            return None
        logger.info(f"{tag} Kontext ok -> {str(replicate_url)[:80]}")
    except Exception as e:
        logger.exception(f"{tag} Kontext call raised: {e}")
        return None

    # 2) GCS upload (permanent) — timestamped path keeps assets unique even
    #    if a future recovery rerun ever overwrites (we don't, today).
    ts = datetime.utcnow().strftime('%Y%m%d%H%M%S')
    blob_name = f"robots/{user_id}/stage_{stage_idx}_{ts}.png"
    try:
        gcs_url = upload_blob_from_url(replicate_url, blob_name, content_type='image/png')
    except Exception as e:
        logger.exception(f"{tag} GCS upload raised blob={blob_name}: {e}")
        return None
    if not gcs_url:
        logger.error(f"{tag} GCS upload returned None blob={blob_name} src={str(replicate_url)[:80]}")
        return None
    logger.info(f"{tag} GCS ok blob={blob_name}")

    # 3) Build manifest — same shape as stub, ready for Sepolia tx when that
    #    layer lands. Kind field signals this row came from the real pipeline
    #    so downstream consumers can distinguish chain-backed from stub rows.
    manifest = {
        'stage_idx': stage_idx,
        'stage_key': stage['key'],
        'stage_label': stage['label'],
        'item_name': source.get('item_name'),
        'rarity': source.get('rarity'),
        'landmark_name': source.get('landmark_name'),
        'lat': source.get('lat'),
        'lon': source.get('lon'),
        'discovery_id': source.get('discovery_id'),
        'recovered_at': source.get('recovered_at'),
        'assembled_at': datetime.utcnow().isoformat() + 'Z',
        'seed_url': seed_url,
        'kontext_prompt': prompt[:240],
        'kind': 'kontext',
    }

    # 4) Persist — fake tx for now (real Sepolia breadcrumb in a follow-up
    #    step), real image URL replacing the placeholder, manifest captures
    #    everything the future chain-layer needs.
    fake_tx = f"0xkontext{user_id:08x}{stage_idx:02d}"
    fake_data_hex = f"0xkontext_pending_sepolia_{stage['key']}"
    try:
        result = log_stage(
            user_id=user_id,
            stage_idx=stage_idx,
            source_manifest=manifest,
            image_url=gcs_url,
            data_hex=fake_data_hex,
            tx_hash=fake_tx,
        )
        logger.info(f"{tag} log_stage ok — stage complete")
        return result
    except Exception as e:
        logger.exception(f"{tag} log_stage failed: {e}")
        return None


def _worker(user_id: int, stage_idx: int, source: Dict[str, Any]) -> None:
    """Background worker — runs real stage, falls back to stub on failure."""
    tag = f"[robot user={user_id} stage={stage_idx}]"
    try:
        result = _run_stage(user_id, stage_idx, source)
        if result is None:
            logger.error(
                f"{tag} FELL BACK TO STUB — Kontext/GCS/log_stage returned None. "
                f"Stage image will be the shared placeholder."
            )
            _stub_advance_one_stage(user_id, stage_idx, source)
    except Exception as e:
        logger.exception(f"{tag} worker crash: {e}")
    finally:
        _release(user_id, stage_idx)


def start_background_advance(user_id: int, stage_idx: int,
                              source: Dict[str, Any]) -> bool:
    """
    Spawn a daemon thread to advance one stage. Returns True if the thread
    was spawned, False if a prior advance for the same (user, stage) is
    still running in this instance.

    Callers should treat False as "advance is in progress, try again on next
    tick" — the stage_ready_at timer on the robot row stays where it is, so
    the next page visit re-enters tick_robot_build() and will either:
      - see this run's log_stage() has persisted (visual_stage advanced)
      - or re-spawn because the lock was released on completion
    """
    if not _acquire(user_id, stage_idx):
        return False
    t = threading.Thread(
        target=_worker,
        args=(user_id, stage_idx, source),
        name=f"robot-stage-{user_id}-{stage_idx}",
        daemon=True,
    )
    t.start()
    return True
