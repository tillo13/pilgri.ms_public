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
import os
import threading
import time
from datetime import datetime
from typing import Dict, Any, Optional

from utilities.postgres.core import db_cursor
from utilities.postgres.robot import (
    ROBOT_STAGES,
    PLACEHOLDER_STAGE_IMAGE,
    STAGE_PLACEHOLDER_IMAGES,
    log_stage,
    _stub_advance_one_stage,
    broadcast_stage_async,
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
_STYLE_SUFFIX = (
    "Cartoon video game item with bold outlines and stylized proportions, "
    "isolated on red Martian terrain, vibrant reds and oranges reflecting "
    "Mars atmosphere, video game asset style. The robot fills the center of "
    "the frame as the only subject; the ground is empty Martian sand."
)

# One-shot forge prompt — rendered ONCE at stage 5 with silhouette + cairn +
# every captain's item as refs. Replaces the 5-stage Kontext chain (which
# produced near-identical polished clones). See testing/test_narog_flux2_oneshot.py
# for the iteration history that landed on this prompt.
ONESHOT_FORGE_PROMPT = (
    "A single makeshift scrap-robot character standing on flat rust-red "
    "Martian sand with an empty horizon. This is not a polished mech — "
    "it is a crude junkyard golem spackled together out of Mars dirt, "
    "caked clay, loose rocks, and scavenged artifacts, held on with "
    "bundles of exposed open wires, dangling cables, rusted bolts, "
    "little improvised gadgets, small blinking modules, and wet clay "
    "mortar oozing between the seams. "
    "Image 1 only sets the overall humanoid stance and limb layout — "
    "do not copy its clean finish; the final robot should look rougher, "
    "dirtier, cruder, and distinctly asymmetric. "
    "Treat every one of the remaining reference images as raw salvage "
    "this robot has bolted onto itself at odd angles. "
    "Vary the placement wildly: oversize one piece, bury another half "
    "into the torso, stick one sideways off a shoulder, jut one out of "
    "the back like a spine, wedge one into a hip or thigh. Pieces should "
    "be off-center, tilted, mismatched in scale, some way too big, some "
    "half-buried in clay, some wired on with tangled loops of open "
    "cable and patched-in gadgets. No two pieces should sit "
    "symmetrically. "
    "Every salvaged element ends up visibly fused onto the body — not "
    "on the ground, not floating beside it — but clearly bolted, "
    "wired, or mudded on rather than smoothly integrated, with loose "
    "cable ends and tiny exposed gadgets visible around each joint. "
    "Keep the robot's face and both eyes fully visible and unobstructed "
    "— never place any artifact, crystal, or rock slab on, over, or "
    "across the eyes, face, or forehead; route bulky pieces to the "
    "torso, limbs, shoulders, crown, or back of the head instead. "
    "The surface is rough and earthen: cracked red clay, dusty rock, "
    "exposed rebar, chipped paint, streaks of Martian dirt, uneven "
    "patchwork. One shoulder bulkier than the other, one leg thicker, "
    "limbs slightly mismatched. Improvised, lopsided, one-of-a-kind. "
    "Bold black cartoon outlines, chunky stylized proportions, vibrant "
    "Martian reds and oranges, subtle glowing accents where crystalline "
    "pieces poke through the dirt. Gritty hand-built video-game "
    "character-asset style, flat lighting, square 1:1 framing."
)

CAIRN_REF = (
    "https://storage.googleapis.com/galactica-pilgrim-assets/"
    "ui/icons/robot_stage_frame.png"
)


STAGE_PROMPT_TEMPLATES = {
    1: (
        "Keep this humanoid robot's overall silhouette and pose. Fuse the "
        "following artifact directly INTO the robot's CHEST as a glowing "
        "centerpiece — it replaces the current chest plate and becomes the "
        "robot's defining feature. The robot's chest IS made of {source}. "
        + _STYLE_SUFFIX
    ),
    2: (
        "Embed this artifact directly into the robot's CHEST PLATE as the "
        "centerpiece of newly added hull plating — pressure-rated panels "
        "shaped from compressed Martian clay wrap around and hold it. The "
        "artifact is mounted ON the robot's torso, fused into the armor. "
        "The plating's central medallion IS {source}. " + _STYLE_SUFFIX
    ),
    3: (
        "The robot's reactor core glows at the center of its chest — the "
        "core itself IS the embedded artifact, crystalline and pulsing "
        "through the clay plating. Power conduits trace from the chest core "
        "down the limbs. The reactor IS {source}, mounted inside the torso. "
        + _STYLE_SUFFIX
    ),
    4: (
        "Mount this artifact as the robot's HEAD or EYE cluster — fused "
        "directly into the face, forming glowing lenses or a single central "
        "eye backlit cyan. The robot's head IS shaped from {source}. "
        + _STYLE_SUFFIX
    ),
    5: (
        "Final assembly — the robot stands in a heroic pose, awakened and "
        "complete. Mount this artifact as a SHOULDER EMBLEM or CROWN on the "
        "robot itself, glowing Sepolia eyes, Mars mission glyphs painted on "
        "the chest. The robot's shoulder crest IS {source}. " + _STYLE_SUFFIX
    ),
}


# Per-item visual descriptors so each discovery PHYSICALLY shows up on the
# Narog in a way the captain can recognize. Keyword-matched against item_name
# (lowercased). Fallback is a generic "recovered fragment".
ITEM_VISUAL_DESCRIPTORS = {
    'quantum crystal':  "a prismatic violet-and-cyan crystal lattice pulsing with inner light",
    'quantum obelisk':  "a monolithic black basalt slab carved with glowing geometric runes",
    'crystal sentinel': "a faceted aqua-crystal gemstone shaped like a watchful eye",
    'viking fragment':  "a weathered iron-red metallic shard etched with runic script",
    'ripple stone':     "a concentric-ringed pale stone that glows softly where touched",
    'depth reading':    "a dark pressure-scarred rock veined with silver filaments",
    'echo shard':       "a hollow resonant crystal shard that refracts twin images",
}

# Rarity controls how PROMINENTLY the item appears on the Narog. Higher rarity
# = more dominant visual feature. Lower = subtle accent.
RARITY_PROMINENCE = {
    'legendary': "dominating the robot's silhouette as its defining feature, large and unmistakable on the robot's body",
    'rare':      "clearly fused into the robot's plating as a bold accent of the robot itself",
    'uncommon':  "integrated into the robot's armor as a recognizable detail of its body",
    'common':    "a faint trace etched into the robot's material",
}


def _describe_item(source: Dict[str, Any]) -> str:
    """Produce a vivid visual descriptor for Kontext, specific to this item."""
    item = (source.get('item_name') or 'recovered fragment').strip()
    key = item.lower()
    descriptor = ITEM_VISUAL_DESCRIPTORS.get(key)
    if not descriptor:
        # Partial match fallback — try any substring hit
        for k, v in ITEM_VISUAL_DESCRIPTORS.items():
            if k in key or key in k:
                descriptor = v
                break
    if not descriptor:
        descriptor = f"a distinctive {item}"
    return descriptor


def _format_source_phrase(source: Dict[str, Any]) -> str:
    """Collapse a stage source manifest into a rich visual phrase for Kontext."""
    rarity = (source.get('rarity') or 'common').lower()
    prominence = RARITY_PROMINENCE.get(rarity, RARITY_PROMINENCE['common'])
    descriptor = _describe_item(source)
    item_name = source.get('item_name') or 'fragment'
    landmark = source.get('landmark_name') or 'an unknown site'
    return (
        f"{descriptor} — the {rarity} {item_name} recovered at {landmark} — "
        f"{prominence}"
    )


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

def _get_seed_image_url(user_id: int, stage_idx: int, source: Optional[Dict[str, Any]] = None) -> str:
    """
    Resolve the 'input image' for this stage's Kontext edit.

    Stage 1 always seeds from the SAME base robot silhouette
    (`robot_placeholder_stage.png`). Each captain's unique discoveries are
    introduced via the Kontext prompt, which fuses the item into the robot's
    body. The chain then progressively layers each subsequent item on top of
    the prior stage's output.

    Stages 2-5 always use the prior stage's already-uploaded GCS image.
    """
    if stage_idx <= 1:
        return PLACEHOLDER_STAGE_IMAGE

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


def _build_base_manifest(stage_idx: int, source: Dict[str, Any]) -> Dict[str, Any]:
    stage = ROBOT_STAGES[stage_idx - 1]
    return {
        'stage_idx': stage_idx,
        'stage_key': stage['key'],
        'stage_label': stage['label'],
        'item_name': source.get('item_name'),
        'rarity': source.get('rarity'),
        'item_image_url': source.get('item_image_url'),
        'landmark_name': source.get('landmark_name'),
        'lat': source.get('lat'),
        'lon': source.get('lon'),
        'discovery_id': source.get('discovery_id'),
        'recovered_at': source.get('recovered_at'),
        'assembled_at': datetime.utcnow().isoformat() + 'Z',
    }


def _gather_prior_item_urls(user_id: int, up_to_stage: int) -> list:
    """Pull item_image_url from stage_log rows 1..up_to_stage-1 for the
    final-stage oneshot forge. Order-preserving dedupe."""
    urls = []
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT source_manifest
                FROM pilgrim.robot_stage_log
                WHERE user_id = %s AND stage_idx BETWEEN 1 AND %s
                ORDER BY stage_idx
            """, (user_id, up_to_stage - 1))
            for row in cur.fetchall() or []:
                mf = row.get('source_manifest') or {}
                u = mf.get('item_image_url')
                if u:
                    urls.append(u)
    except Exception as e:
        logger.warning(f"_gather_prior_item_urls user={user_id}: {e}")
    seen = set()
    return [u for u in urls if not (u in seen or seen.add(u))]


def _log_placeholder_stage(user_id: int, stage_idx: int,
                           source: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Log one stage's placeholder icon — no Flux call. Used for the fake
    progression that plays while the real oneshot forge runs in parallel.

    Inserts the row with tx_hash=NULL/data_hex=NULL, then fires the real
    Sepolia broadcast in a daemon thread. The chain write UPDATEs the row
    on success; on failure the row stays with NULL hashes (the manifest
    modal then renders "Sepolia broadcast pending" instead of a fabricated
    placeholder).
    """
    tag = f"[robot user={user_id} placeholder stage={stage_idx}]"
    stage = ROBOT_STAGES[stage_idx - 1]
    placeholder_img = STAGE_PLACEHOLDER_IMAGES.get(
        stage['key'], PLACEHOLDER_STAGE_IMAGE
    )
    manifest = _build_base_manifest(stage_idx, source)
    manifest['kind'] = 'placeholder'
    try:
        result = log_stage(
            user_id=user_id,
            stage_idx=stage_idx,
            source_manifest=manifest,
            image_url=placeholder_img,
            data_hex=None,
            tx_hash=None,
        )
        # Fire real Sepolia broadcast for stages 1-4. Stage 5 broadcasts
        # from _full_build_worker after the oneshot forge image is uploaded
        # so the on-chain payload references the real GCS URL.
        broadcast_stage_async(user_id, stage_idx, manifest)
        return result
    except Exception as e:
        logger.exception(f"{tag} log_stage failed: {e}")
        return None


def _run_oneshot_forge(user_id: int, sources: list) -> Optional[str]:
    """Fire ONE Flux 2 Pro call with silhouette + cairn + every captured
    item as refs. Returns the GCS URL of the forged Narog, or None on
    failure. No game-specific text in the prompt — Flux can't render
    names/locations correctly, so we leave them out."""
    tag = f"[robot user={user_id} oneshot]"
    try:
        from utilities.replicate_utils import FluxGenerator
        from utilities.google_cloud_storage_utils import upload_blob_from_url
    except ImportError as e:
        logger.exception(f"{tag} imports failed: {e}")
        return None

    item_urls = []
    for s in sources:
        u = s.get('item_image_url')
        if u and u not in item_urls:
            item_urls.append(u)
    # Flux 2 Pro accepts up to 8 input_images.
    refs = [PLACEHOLDER_STAGE_IMAGE, CAIRN_REF] + item_urls[:6]
    refs = [r for r in refs if r]
    logger.info(f"{tag} 🤖 oneshot refs={len(refs)}")

    try:
        flux = FluxGenerator()
        replicate_url = flux.flux2_pro_edit(ONESHOT_FORGE_PROMPT, image_urls=refs)
    except Exception as e:
        logger.exception(f"{tag} Flux2 call raised: {e}")
        return None
    if not replicate_url:
        logger.error(f"{tag} Flux2 returned empty URL")
        return None
    logger.info(f"{tag} Flux2 ok -> {str(replicate_url)[:80]}")

    ts = datetime.utcnow().strftime('%Y%m%d%H%M%S')
    blob_name = f"robots/{user_id}/narog_{ts}.png"
    try:
        gcs_url = upload_blob_from_url(replicate_url, blob_name, content_type='image/png')
    except Exception as e:
        logger.exception(f"{tag} GCS upload raised: {e}")
        return None
    return gcs_url


def _run_stage(user_id: int, stage_idx: int, source: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Legacy per-stage entry point. Kept so external callers keep working,
    but internally short-circuits: stages 1–4 log a placeholder icon and
    stage 5 runs the oneshot forge (using this captain's full sources list
    via robot.stage_sources)."""
    if stage_idx < 5:
        return _log_placeholder_stage(user_id, stage_idx, source)

    tag = f"[robot user={user_id} stage=5]"
    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT stage_sources FROM pilgrim.robot WHERE user_id = %s",
                (user_id,),
            )
            row = cur.fetchone()
            sources = (row and row.get('stage_sources')) or [source]
    except Exception as e:
        logger.warning(f"{tag} stage_sources fetch failed, using single source: {e}")
        sources = [source]

    gcs_url = _run_oneshot_forge(user_id, sources)
    if not gcs_url:
        return None

    stage = ROBOT_STAGES[4]
    manifest = _build_base_manifest(5, source)
    manifest['kind'] = 'oneshot_flux2'
    manifest['gcs_url'] = gcs_url
    try:
        result = log_stage(
            user_id=user_id,
            stage_idx=5,
            source_manifest=manifest,
            image_url=gcs_url,
            data_hex=None,
            tx_hash=None,
        )
        broadcast_stage_async(user_id, 5, manifest)
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


_FAKE_STAGE_INTERVAL_SECONDS = 7


def _full_build_worker(user_id: int, sources: list) -> None:
    """Theater vs reality: ONE real Flux 2 Pro call happens in a child thread,
    while the main thread fakes stages 1–4 by logging placeholder icons at a
    steady cadence so the UI poller sees visual_stage tick up. When the Flux
    call finishes, stage 5 gets logged with the real GCS URL.

    Production semantics:
      - Each stage row is logged with tx_hash=NULL and a real Sepolia
        broadcast fires in a daemon thread (writes back tx_hash on success).
      - If the oneshot forge returns None, pilgrim.robot.build_error is set
        and build_status stays 'in_progress'. The captain sees a red banner
        + Retry button instead of a silent placeholder Narog.
      - On stage-5 success, kick off the awakening video auto-generation so
        the captain doesn't have to click anything.
    """
    tag = f"[robot user={user_id} full-build]"
    result_holder: Dict[str, Optional[str]] = {'url': None, 'error': None}

    def _forge():
        try:
            result_holder['url'] = _run_oneshot_forge(user_id, sources)
            if not result_holder['url']:
                result_holder['error'] = "Flux 2 Pro forge returned no image"
        except Exception as e:
            logger.exception(f"{tag} forge thread crash: {e}")
            result_holder['error'] = f"Forge thread crashed: {e}"

    forge_thread = threading.Thread(
        target=_forge,
        name=f"robot-forge-flux-{user_id}",
        daemon=True,
    )
    forge_thread.start()

    try:
        # Fake stages 1–4 at a steady cadence so the poller advances.
        # Each placeholder log triggers its own real Sepolia broadcast.
        for stage_idx in range(1, 5):
            if stage_idx - 1 >= len(sources):
                logger.error(f"{tag} missing source for stage {stage_idx}")
                continue
            source = sources[stage_idx - 1]
            _log_placeholder_stage(user_id, stage_idx, source)
            time.sleep(_FAKE_STAGE_INTERVAL_SECONDS)

        # Wait for the real Flux call to finish (may already be done).
        forge_thread.join()
        gcs_url = result_holder['url']

        stage5_source = sources[4] if len(sources) >= 5 else (sources[-1] if sources else {})

        if not gcs_url:
            err = result_holder['error'] or "Forge returned no image"
            logger.error(f"{tag} oneshot forge failed — setting build_error: {err}")
            try:
                with db_cursor(commit=True) as cur:
                    cur.execute("""
                        UPDATE pilgrim.robot
                        SET build_error = %s, updated_at = NOW()
                        WHERE user_id = %s
                    """, (err, user_id))
            except Exception as ex:
                logger.exception(f"{tag} failed to set build_error: {ex}")
            return

        manifest = _build_base_manifest(5, stage5_source)
        manifest['kind'] = 'oneshot_flux2'
        manifest['gcs_url'] = gcs_url
        try:
            log_stage(
                user_id=user_id,
                stage_idx=5,
                source_manifest=manifest,
                image_url=gcs_url,
                data_hex=None,
                tx_hash=None,
            )
            # Real Sepolia tx for stage 5 (after the GCS image lands so the
            # on-chain payload references the final URL).
            broadcast_stage_async(user_id, 5, manifest)
        except Exception as e:
            logger.exception(f"{tag} stage 5 log_stage failed: {e}")
            try:
                with db_cursor(commit=True) as cur:
                    cur.execute("""
                        UPDATE pilgrim.robot
                        SET build_error = %s, updated_at = NOW()
                        WHERE user_id = %s
                    """, (f"Stage 5 log_stage failed: {e}", user_id))
            except Exception:
                pass
            return

        # Awakening video auto-fires from the frontend: when the captain hits
        # the page with build_status='complete' AND video_url IS NULL, the JS
        # calls /api/robot/generate_video on first paint (see static/js/crew-
        # robot.js:autoStartVideoGen). No daemon-thread call needed here —
        # avoids the Flask current_app context issue from background threads.
        logger.info(f"{tag} stage 5 complete; frontend will auto-fire video gen")
    except Exception as e:
        logger.exception(f"{tag} crash: {e}")
    finally:
        with _IN_FLIGHT_LOCK:
            _IN_FLIGHT.discard((user_id, 'full'))


def start_background_full_build(user_id: int, sources: list) -> bool:
    """Spawn a single daemon thread that drives the whole build to completion.
    Replaces the per-stage tick-and-respawn loop."""
    key = (user_id, 'full')
    with _IN_FLIGHT_LOCK:
        if key in _IN_FLIGHT:
            return False
        _IN_FLIGHT.add(key)
    t = threading.Thread(
        target=_full_build_worker,
        args=(user_id, sources),
        name=f"robot-forge-{user_id}",
        daemon=True,
    )
    t.start()
    return True


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
