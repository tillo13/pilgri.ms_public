"""Robot construction database operations.

The captain's robot is built in 5 visual stages from real items the captain
recovered on expeditions. Each stage logs to the Sepolia testnet with a
cryptic source manifest the community can decode (see plan decision #14).

Tables:
- pilgrim.robot              one row per user, current build state + dial
- pilgrim.robot_stage_log    append-only per-stage history with tx hashes
"""

import logging
import json
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

from utilities.postgres.core import db_cursor

logger = logging.getLogger(__name__)

_robot_schema_ensured = False

# Constants moved to utilities/postgres/config.py (shared DRY source). Re-exported
# here so existing `from utilities.postgres.config import ROBOT_STAGES` callers work.
from utilities.postgres.config import (  # noqa: F401
    ROBOT_STAGES,
    STAGE_DURATION_SECONDS,
    PLACEHOLDER_STAGE_IMAGE,
    STAGE_PLACEHOLDER_IMAGES,
    DEFAULT_DIAL,
    DIAL_KEYS,
)


def ensure_robot_tables():
    """Create robot tables if they don't exist. Idempotent + cached."""
    global _robot_schema_ensured
    if _robot_schema_ensured:
        return
    _robot_schema_ensured = True

    with db_cursor(commit=True) as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pilgrim.robot (
                user_id INTEGER PRIMARY KEY,
                name TEXT,
                build_status TEXT NOT NULL DEFAULT 'not_started',
                visual_stage INTEGER NOT NULL DEFAULT 0,
                current_image_url TEXT,
                stage_images JSONB NOT NULL DEFAULT '[]'::jsonb,
                stage_sources JSONB NOT NULL DEFAULT '[]'::jsonb,
                dial JSONB NOT NULL DEFAULT '{"mining":25,"exploration":25,"science":25,"combat":25}'::jsonb,
                started_at TIMESTAMP,
                stage_started_at TIMESTAMP,
                stage_ready_at TIMESTAMP,
                completed_at TIMESTAMP,
                cinematic_played BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pilgrim.robot_stage_log (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                stage_idx INTEGER NOT NULL,
                stage_key TEXT NOT NULL,
                stage_label TEXT NOT NULL,
                source_manifest JSONB NOT NULL,
                data_hex TEXT,
                tx_hash TEXT,
                image_url TEXT,
                logged_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE(user_id, stage_idx)
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_robot_stage_log_user ON pilgrim.robot_stage_log(user_id)")
        cur.execute("""
            ALTER TABLE pilgrim.robot
            ADD COLUMN IF NOT EXISTS craftsmanship_score INTEGER NOT NULL DEFAULT 0
        """)


RARITY_WEIGHTS = {'legendary': 30, 'rare': 10, 'uncommon': 3, 'common': 1}
CRAFTSMANSHIP_MAX = 150  # 5 legendaries = theoretical ceiling

# Keyword → stat mapping. An item_name that matches multiple keywords splits
# its weight across all matched stats. No match → splits evenly across all 4.
STAT_KEYWORDS = {
    'science':     ['crystal', 'quantum', 'core', 'reactor', 'lattice', 'signal'],
    'mining':      ['obelisk', 'fragment', 'shard', 'ore', 'stone', 'pillar', 'regolith'],
    'exploration': ['optic', 'lens', 'beacon', 'map', 'compass', 'eye', 'viking'],
    'combat':      ['sentinel', 'guardian', 'blade', 'armor', 'shell', 'spike', 'claw'],
}
STAT_KEYS = ['combat', 'mining', 'science', 'exploration']


def _item_stat_bias(item_name: str) -> Dict[str, float]:
    """Return unit-weight distribution across STAT_KEYS for an item name."""
    name = (item_name or '').lower()
    matched = [k for k, kws in STAT_KEYWORDS.items() if any(kw in name for kw in kws)]
    if not matched:
        return {k: 0.25 for k in STAT_KEYS}
    share = 1.0 / len(matched)
    return {k: (share if k in matched else 0.0) for k in STAT_KEYS}


def compute_craftsmanship_score(sources: List[Dict[str, Any]]) -> int:
    return int(sum(RARITY_WEIGHTS.get((s.get('rarity') or 'common').lower(), 1) for s in (sources or [])))


def compute_stat_profile(sources: List[Dict[str, Any]]) -> Dict[str, int]:
    """Return integer-percent profile across STAT_KEYS, summing to 100."""
    raw = {k: 0.0 for k in STAT_KEYS}
    for s in (sources or []):
        w = RARITY_WEIGHTS.get((s.get('rarity') or 'common').lower(), 1)
        bias = _item_stat_bias(s.get('item_name', ''))
        for k in STAT_KEYS:
            raw[k] += w * bias[k]
    total = sum(raw.values()) or 1.0
    pct = {k: raw[k] / total * 100 for k in STAT_KEYS}
    # Round to ints, fix rounding drift so sum == 100
    rounded = {k: int(round(v)) for k, v in pct.items()}
    drift = 100 - sum(rounded.values())
    if drift != 0:
        # Adjust the stat with the largest fractional remainder
        frac = sorted(STAT_KEYS, key=lambda k: (pct[k] - rounded[k]), reverse=(drift > 0))
        rounded[frac[0]] += drift
    return rounded


# ============================================================================
# READ
# ============================================================================

def get_robot(user_id: int) -> Optional[Dict[str, Any]]:
    """Return the captain's robot row, or None if they haven't started one."""
    try:
        ensure_robot_tables()
        with db_cursor() as cur:
            cur.execute("SELECT * FROM pilgrim.robot WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"get_robot failed for user {user_id}: {e}")
        return None


def get_stage_log(user_id: int) -> List[Dict[str, Any]]:
    """Return all logged stages for a captain in order."""
    try:
        ensure_robot_tables()
        with db_cursor() as cur:
            cur.execute("""
                SELECT id, stage_idx, stage_key, stage_label, source_manifest,
                       data_hex, tx_hash, image_url, logged_at
                FROM pilgrim.robot_stage_log
                WHERE user_id = %s
                ORDER BY stage_idx ASC
            """, (user_id,))
            return [dict(r) for r in cur.fetchall() or []]
    except Exception as e:
        logger.error(f"get_stage_log failed for user {user_id}: {e}")
        return []


# ============================================================================
# SOURCING — pick 5 real items the captain recovered to "build" the robot
# ============================================================================

def _resolve_coords(coords_jsonb, dest_lat, dest_lon):
    """Pick lat/lon from found_at_coordinates jsonb, falling back to expedition
    destination when the jsonb is missing or has 0/0 sentinel values."""
    lat = lon = None
    if isinstance(coords_jsonb, dict):
        lat = coords_jsonb.get('lat')
        lon = coords_jsonb.get('lon')
    if (lat in (None, 0)) and dest_lat is not None:
        lat = float(dest_lat)
    if (lon in (None, 0)) and dest_lon is not None:
        lon = float(dest_lon)
    return lat, lon


ROBOT_GATE_MIN_LEGENDARY = 1
ROBOT_GATE_MIN_RARE = 2
ROBOT_BUILD_MAX_LEGENDARY = 3
ROBOT_BUILD_MAX_RARE = 4
ROBOT_BUILD_TOTAL_ITEMS = 5


class RobotGateError(ValueError):
    """Captain doesn't have the minimum components to start a Narog build."""
    pass


def _pick_with_diversity(items: List[Dict[str, Any]], n: int) -> List[Dict[str, Any]]:
    """Pick n items from the pool, preferring distinct item types over duplicates.

    Pass 1 takes one of each unique item_name in random order. Pass 2 fills the
    remainder from whatever is left, shuffled. This biases output toward variety
    (3 distinct legendaries beats 3 copies of Crystal Sentinel) without ever
    duplicating a specific discovery row.
    """
    import random
    if n <= 0 or not items:
        return []
    by_type: Dict[str, List[Dict[str, Any]]] = {}
    for item in items:
        by_type.setdefault(item['item_name'], []).append(item)
    for t in by_type:
        random.shuffle(by_type[t])
    types = list(by_type.keys())
    random.shuffle(types)
    chosen: List[Dict[str, Any]] = []
    for t in types:
        if len(chosen) >= n:
            break
        chosen.append(by_type[t].pop(0))
    leftovers: List[Dict[str, Any]] = []
    for t in types:
        leftovers.extend(by_type[t])
    random.shuffle(leftovers)
    for item in leftovers:
        if len(chosen) >= n:
            break
        chosen.append(item)
    return chosen[:n]


def _load_claimed_inventory(user_id: int) -> Dict[str, List[Dict[str, Any]]]:
    """Return every claimed, not-yet-consumed discovery for a captain, grouped by rarity."""
    inv: Dict[str, List[Dict[str, Any]]] = {
        'legendary': [], 'rare': [], 'uncommon': [], 'common': []
    }
    with db_cursor() as cur:
        cur.execute("""
            SELECT ed.id AS discovery_id,
                   di.item_name,
                   COALESCE(di.rarity, 'common') AS rarity,
                   di.image_url AS item_image_url,
                   ed.found_at_coordinates AS coords,
                   e.destination_name AS landmark_name,
                   e.destination_lat AS landmark_lat,
                   e.destination_lon AS landmark_lon,
                   e.completed_at AS recovered_at
            FROM pilgrim.expedition_discoveries ed
            JOIN pilgrim.expeditions e ON e.id = ed.expedition_id
            LEFT JOIN pilgrim.discovery_items di ON di.id = ed.discovery_item_id
            WHERE e.user_id = %s
              AND ed.claimed_by_user = TRUE
              AND di.item_name IS NOT NULL
            ORDER BY ed.id DESC
        """, (user_id,))
        for r in cur.fetchall() or []:
            rarity = r['rarity'] or 'common'
            lat, lon = _resolve_coords(r['coords'], r['landmark_lat'], r['landmark_lon'])
            inv.setdefault(rarity, []).append({
                'kind': 'discovery',
                'discovery_id': r['discovery_id'],
                'item_name': r['item_name'] or 'Unknown Fragment',
                'rarity': rarity,
                'item_image_url': r['item_image_url'],
                'landmark_name': r['landmark_name'] or 'Unknown Site',
                'lat': lat,
                'lon': lon,
                'recovered_at': r['recovered_at'].isoformat() if r['recovered_at'] else None,
            })
    return inv


def check_robot_gate(user_id: int) -> Dict[str, Any]:
    """Inventory summary + gate-met flag. Used by the preview endpoint and the UI
    to explain what's missing without throwing."""
    inv = _load_claimed_inventory(user_id)
    n_leg = len(inv['legendary'])
    n_rare = len(inv['rare'])
    return {
        'met': n_leg >= ROBOT_GATE_MIN_LEGENDARY and n_rare >= ROBOT_GATE_MIN_RARE,
        'legendary_count': n_leg,
        'rare_count': n_rare,
        'min_legendary': ROBOT_GATE_MIN_LEGENDARY,
        'min_rare': ROBOT_GATE_MIN_RARE,
    }


def pick_stage_sources(user_id: int) -> List[Dict[str, Any]]:
    """Pick 5 source manifests for a Narog build using the randomized v2 algorithm.

    Composition: 1-3 legendaries (randomized, capped at inventory) + 2-4 rares
    (randomized, capped, such that total ≤ 5). Remainder filled with uncommons
    then commons from the captain's claimed inventory; finally padded with a
    synthetic home-base stub if the captain literally has nothing else.

    Diversity bias inside each tier (see _pick_with_diversity). Final list is
    shuffled so the same inputs produce a different stage→item mapping each roll.

    Raises RobotGateError if the gate isn't met. Caller should surface the
    message verbatim to the captain.
    """
    import random
    inv = _load_claimed_inventory(user_id)
    n_leg_avail = len(inv['legendary'])
    n_rare_avail = len(inv['rare'])
    if n_leg_avail < ROBOT_GATE_MIN_LEGENDARY or n_rare_avail < ROBOT_GATE_MIN_RARE:
        raise RobotGateError(
            f"Narog construction requires at least {ROBOT_GATE_MIN_LEGENDARY} "
            f"legendary and {ROBOT_GATE_MIN_RARE} rare discoveries. "
            f"You have {n_leg_avail} legendary and {n_rare_avail} rare."
        )

    n_legendary = random.randint(
        ROBOT_GATE_MIN_LEGENDARY,
        min(ROBOT_BUILD_MAX_LEGENDARY, n_leg_avail),
    )
    unique_rare_types = len({it['item_name'] for it in inv['rare']})
    rare_upper = min(ROBOT_BUILD_MAX_RARE, n_rare_avail, ROBOT_BUILD_TOTAL_ITEMS - n_legendary)
    rare_upper = max(ROBOT_GATE_MIN_RARE, min(rare_upper, unique_rare_types or ROBOT_GATE_MIN_RARE))
    n_rare = random.randint(ROBOT_GATE_MIN_RARE, max(ROBOT_GATE_MIN_RARE, rare_upper))
    n_fill = max(0, ROBOT_BUILD_TOTAL_ITEMS - n_legendary - n_rare)

    chosen: List[Dict[str, Any]] = []
    chosen.extend(_pick_with_diversity(inv['legendary'], n_legendary))
    chosen.extend(_pick_with_diversity(inv['rare'], n_rare))
    fill_pool = list(inv.get('uncommon', [])) + list(inv.get('common', []))
    chosen.extend(_pick_with_diversity(fill_pool, n_fill))

    while len(chosen) < ROBOT_BUILD_TOTAL_ITEMS:
        chosen.append({
            'kind': 'home_base',
            'discovery_id': None,
            'item_name': 'Salvaged habitat strut',
            'rarity': 'common',
            'landmark_name': 'Home Base',
            'lat': 18.65,
            'lon': 77.43,
            'recovered_at': None,
        })

    random.shuffle(chosen)
    return chosen[:ROBOT_BUILD_TOTAL_ITEMS]


# ============================================================================
# WRITE
# ============================================================================

def start_robot_build(user_id: int, sources: List[Dict[str, Any]],
                      initial_image_url: Optional[str] = None) -> Dict[str, Any]:
    """Initialize a robot build with the 5 pre-picked source manifests.
    Stage 1's stage_ready_at is set to NOW + STAGE_DURATION_SECONDS so the
    auto-tick can advance it on the next page load."""
    ensure_robot_tables()
    score = compute_craftsmanship_score(sources)
    with db_cursor(commit=True) as cur:
        cur.execute("""
            INSERT INTO pilgrim.robot
                (user_id, build_status, visual_stage, current_image_url,
                 stage_images, stage_sources, craftsmanship_score,
                 started_at, stage_started_at, stage_ready_at, updated_at)
            VALUES (%s, 'in_progress', 0, %s, '[]'::jsonb, %s::jsonb, %s,
                    NOW(), NOW(), NOW() + (%s * INTERVAL '1 second'), NOW())
            ON CONFLICT (user_id) DO UPDATE SET
                build_status = 'in_progress',
                visual_stage = 0,
                current_image_url = EXCLUDED.current_image_url,
                stage_images = '[]'::jsonb,
                stage_sources = EXCLUDED.stage_sources,
                craftsmanship_score = EXCLUDED.craftsmanship_score,
                started_at = NOW(),
                stage_started_at = NOW(),
                stage_ready_at = NOW() + (%s * INTERVAL '1 second'),
                completed_at = NULL,
                cinematic_played = FALSE,
                updated_at = NOW()
            RETURNING *
        """, (user_id, initial_image_url, json.dumps(sources), score,
              STAGE_DURATION_SECONDS, STAGE_DURATION_SECONDS))
        row = cur.fetchone()
        # Wipe any prior stage log so re-builds start fresh
        cur.execute("DELETE FROM pilgrim.robot_stage_log WHERE user_id = %s", (user_id,))
        return dict(row)


def log_stage(user_id: int, stage_idx: int, source_manifest: Dict[str, Any],
              image_url: Optional[str], data_hex: Optional[str],
              tx_hash: Optional[str]) -> Dict[str, Any]:
    """
    Append a completed stage to the log AND advance the robot row.

    `source_manifest` is the full dict that gets hex-encoded into the Sepolia
    tx data field — preserved verbatim so the ARG sleuth can verify breadcrumbs
    against the on-chain payload.
    """
    if stage_idx < 1 or stage_idx > 5:
        raise ValueError(f"stage_idx must be 1..5, got {stage_idx}")
    stage = ROBOT_STAGES[stage_idx - 1]

    ensure_robot_tables()
    with db_cursor(commit=True) as cur:
        # 1) append to log (idempotent on user_id+stage_idx)
        cur.execute("""
            INSERT INTO pilgrim.robot_stage_log
                (user_id, stage_idx, stage_key, stage_label,
                 source_manifest, data_hex, tx_hash, image_url)
            VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s)
            ON CONFLICT (user_id, stage_idx) DO UPDATE SET
                source_manifest = EXCLUDED.source_manifest,
                data_hex = EXCLUDED.data_hex,
                tx_hash = EXCLUDED.tx_hash,
                image_url = EXCLUDED.image_url,
                logged_at = NOW()
            RETURNING *
        """, (user_id, stage_idx, stage['key'], stage['label'],
              json.dumps(source_manifest), data_hex, tx_hash, image_url))
        log_row = dict(cur.fetchone())

        # 2) push the new image into the robot row's stage_images list +
        #    advance visual_stage if this stage is the next one in sequence.
        #    stage_ready_at gets pushed forward by STAGE_DURATION_SECONDS
        #    so the next tick fires when the next stage's timer elapses.
        cur.execute("""
            UPDATE pilgrim.robot
            SET stage_images = COALESCE(stage_images, '[]'::jsonb) ||
                               jsonb_build_array(jsonb_build_object(
                                   'stage_idx', %s::int,
                                   'image_url', %s::text,
                                   'tx_hash', %s::text
                               )),
                current_image_url = COALESCE(%s, current_image_url),
                visual_stage = GREATEST(visual_stage, %s::int),
                stage_started_at = NOW(),
                stage_ready_at = NOW() + (%s * INTERVAL '1 second'),
                build_status = CASE WHEN %s::int >= 5 THEN 'complete' ELSE 'in_progress' END,
                completed_at = CASE WHEN %s::int >= 5 THEN NOW() ELSE completed_at END,
                updated_at = NOW()
            WHERE user_id = %s
            RETURNING *
        """, (stage_idx, image_url, tx_hash, image_url, stage_idx,
              STAGE_DURATION_SECONDS, stage_idx, stage_idx, user_id))
        robot_row = cur.fetchone()
        return {'log': log_row, 'robot': dict(robot_row) if robot_row else None}


def set_robot_name(user_id: int, name: str) -> bool:
    """Set or rename the captain's robot. Names are trimmed and capped at 64 chars."""
    name = (name or '').strip()[:64]
    if not name:
        return False
    ensure_robot_tables()
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE pilgrim.robot SET name = %s, updated_at = NOW() WHERE user_id = %s
            """, (name, user_id))
            return cur.rowcount > 0
    except Exception as e:
        logger.error(f"set_robot_name failed for user {user_id}: {e}")
        return False


def set_robot_dial(user_id: int, dial: Dict[str, int]) -> Dict[str, Any]:
    """
    Update the robot's role dial. Each value must be a non-negative multiple of 5
    and the four values must sum to 100. Raises ValueError on invalid input.
    """
    if not isinstance(dial, dict):
        raise ValueError("dial must be a dict")
    cleaned = {}
    for k in DIAL_KEYS:
        v = dial.get(k, 0)
        if not isinstance(v, int) or v < 0 or v % 5 != 0:
            raise ValueError(f"dial.{k} must be a non-negative multiple of 5, got {v!r}")
        cleaned[k] = v
    if sum(cleaned.values()) != 100:
        raise ValueError(f"dial values must sum to 100, got {sum(cleaned.values())}")

    ensure_robot_tables()
    with db_cursor(commit=True) as cur:
        cur.execute("""
            UPDATE pilgrim.robot SET dial = %s::jsonb, updated_at = NOW()
            WHERE user_id = %s
            RETURNING dial
        """, (json.dumps(cleaned), user_id))
        row = cur.fetchone()
        return dict(row['dial']) if row else cleaned


def mark_cinematic_played(user_id: int) -> None:
    """Flag the build-complete cinematic as already shown so it doesn't replay."""
    ensure_robot_tables()
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE pilgrim.robot SET cinematic_played = TRUE, updated_at = NOW()
                WHERE user_id = %s
            """, (user_id,))
    except Exception as e:
        logger.error(f"mark_cinematic_played failed for user {user_id}: {e}")


def save_name_suggestions(user_id: int, names: list) -> None:
    """Store pre-generated golem name suggestions in the robot row."""
    try:
        import json
        with db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE pilgrim.robot SET name_suggestions = %s, updated_at = NOW()
                WHERE user_id = %s
            """, (json.dumps(names), user_id))
    except Exception as e:
        logger.error(f"save_name_suggestions failed for user {user_id}: {e}")


def start_robot_awakening_video(user_id: int, flux_app_config: dict, flux) -> tuple:
    """Kick off a Wan video animation for the completed robot image.
    Stores progress on the provided app.config dict under 'golem_video_{user_id}'.

    Returns (payload_dict, status_code) for the API route.
    """
    from utilities.replicate_utils import animate_character_video, NAROG_AWAKENING_PROMPT
    import threading

    robot = get_robot(user_id)
    if not robot or robot.get('build_status') != 'complete':
        return {'success': False, 'error': 'Golem must be fully built.'}, 400
    if robot.get('video_url'):
        return {'success': True, 'video_url': robot['video_url'], 'already_exists': True}, 200

    image_url = robot.get('current_image_url')
    if not image_url:
        return {'success': False, 'error': 'No golem image found.'}, 400

    status_key = f'golem_video_{user_id}'
    flux_app_config[status_key] = {'generating': True, 'url': None}

    def _gen():
        try:
            video_url = animate_character_video(
                image_url, flux, user_id=user_id,
                custom_prompt=NAROG_AWAKENING_PROMPT,
            )
            flux_app_config[status_key].update({'url': video_url, 'generating': False})
            with db_cursor(commit=True) as cur:
                cur.execute(
                    "UPDATE pilgrim.robot SET video_url = %s, updated_at = NOW() WHERE user_id = %s",
                    (video_url, user_id))
        except Exception as e:
            logger.error(f"Golem video gen failed: {e}")
            flux_app_config[status_key].update({'url': None, 'generating': False, 'error': str(e)})

    threading.Thread(target=_gen, daemon=True).start()
    return {'success': True, 'status_key': status_key, 'generating': True}, 200


def start_build_with_name_prefetch(user_id: int, cmd_name: Optional[str],
                                   sci_name: Optional[str],
                                   locked_sources: Optional[List[Dict[str, Any]]] = None) -> tuple:
    """Full robot-build kickoff: validate lab level, pick sources, start build,
    fire-and-forget Claude name suggestions. Returns (payload_dict, status_code).
    """
    from utilities.upgrades_utils import get_all_infrastructure_levels

    levels = get_all_infrastructure_levels(user_id) or {}
    if int(levels.get('robotics_lab', 0)) < 1:
        return {
            'success': False,
            'error': 'Robotics Lab required. Build the Robotics Lab in your Colony first.',
        }, 400

    try:
        if locked_sources and len(locked_sources) == 5:
            sources = locked_sources
        else:
            sources = pick_stage_sources(user_id)
    except RobotGateError as e:
        return {'success': False, 'error': str(e)}, 400
    if not sources or len(sources) < 5:
        return {
            'success': False,
            'error': 'Insufficient expedition history to source robot parts.',
        }, 400

    start_robot_build(user_id, sources, initial_image_url=PLACEHOLDER_STAGE_IMAGE)

    import threading

    def _gen_names():
        try:
            from utilities.claude_utils import suggest_golem_names
            names = suggest_golem_names(user_id, cmd_name, sci_name, sources)
            if names:
                save_name_suggestions(user_id, names)
        except Exception as e:
            logger.exception(f"Background golem name gen failed user={user_id}: {e}")

    threading.Thread(target=_gen_names, daemon=True).start()

    return {'success': True, 'data': get_robot_page_data(user_id)}, 200


# ============================================================================
# STUB STAGE ADVANCE — Step 4d ships a working visible loop with placeholder
# images + fake tx hashes. Step 4c will swap _stub_advance_one_stage() for the
# real Sepolia + Kontext implementation. The interface stays identical.
# ============================================================================

def _stub_advance_one_stage(user_id: int, stage_idx: int,
                            source: Dict[str, Any]) -> Dict[str, Any]:
    """
    Stage-advance stub that uses the REAL source manifest from stage_sources
    (so the UI shows real "Forged from {item} recovered at {landmark}" strings)
    but a fake tx_hash + placeholder image until Step 4c lands.

    The full source_manifest is persisted exactly as Step 4c will persist it,
    so swapping in real Sepolia later changes one function — not the schema.
    """
    stage = ROBOT_STAGES[stage_idx - 1]
    fake_tx = f"0xstub{user_id:08x}{stage_idx:02d}"
    fake_data_hex = f"0xstub_pending_real_kontext_{stage['key']}"
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
        'note': 'STUB — real Sepolia tx + Kontext image pending Step 4c',
    }
    return log_stage(
        user_id=user_id,
        stage_idx=stage_idx,
        source_manifest=manifest,
        image_url=PLACEHOLDER_STAGE_IMAGE,
        data_hex=fake_data_hex,
        tx_hash=fake_tx,
    )


def tick_robot_build(user_id: int) -> Dict[str, Any]:
    """
    Auto-advance any stages whose stage_ready_at has elapsed. Idempotent —
    safe to call on every page load. Returns the latest robot row (or None
    if no build exists).

    Step 4c: advancement goes through robot_visuals.start_background_advance()
    which runs Flux Kontext + GCS upload in a daemon thread. Since Kontext
    takes ~30s and the next stage depends on the current stage's image being
    persisted, we spawn AT MOST ONE thread per tick and return. The next
    page visit re-enters this function and either sees the advancement
    completed (log_stage() bumped visual_stage) or finds the lock still
    held and no-ops.

    Fallback chain for resilience: if robot_visuals isn't importable OR the
    thread worker hits an unrecoverable failure, it delegates to the
    synchronous stub so the build never deadlocks on a Flux/network outage.
    """
    robot = get_robot(user_id)
    if not robot or robot.get('build_status') != 'in_progress':
        return robot
    if not (robot.get('stage_ready_at') and robot['stage_ready_at'] <= datetime.utcnow()):
        return robot
    if robot['visual_stage'] >= 5:
        return robot

    sources = robot.get('stage_sources') or []
    next_stage_idx = robot['visual_stage'] + 1
    if next_stage_idx > len(sources):
        logger.error(f"robot tick: user {user_id} missing source for stage {next_stage_idx}")
        return robot
    source = sources[next_stage_idx - 1]

    try:
        from utilities.robot_visuals import start_background_full_build
        start_background_full_build(user_id, sources)
        # Either the worker is running now and will update on completion, or
        # a prior worker is still running — both cases return the current
        # (unchanged) robot row so the UI stays on the old stage until
        # persistence catches up.
        return robot
    except Exception as e:
        logger.warning(f"robot tick: real pipeline unavailable, stub fallback: {e}")
        result = _stub_advance_one_stage(user_id, next_stage_idx, source)
        return result.get('robot') or robot


# ============================================================================
# PAGE DATA — single composer for /crew Robot tab
# ============================================================================

def get_robot_page_data(user_id: int) -> Dict[str, Any]:
    """
    Bundle everything the Robot tab needs in one call. Speed-conscious:

    - No-robot + no-lab path: lab level lookup only (1 cursor open).
    - No-robot + lab unlocked: lab + return CTA. Sources are NOT pre-picked
      — that's an expensive query and the anticipation ("what items will I
      get?") is a feature, not a bug. Sources only get picked on /build click.
    - Active build: tick + lab + log (3 cursor opens).
    - Complete: same as active but is_complete=True.
    """
    ensure_robot_tables()

    # Lab unlock check first — cheap, gates everything else
    lab_unlocked = False
    lab_level = 0
    prereqs = []
    try:
        from utilities.upgrades_utils import get_all_infrastructure_levels
        from utilities.postgres.core import db_cursor as _db_cursor
        levels = get_all_infrastructure_levels(user_id) or {}
        lab_level = int(levels.get('robotics_lab', 0))
        lab_unlocked = lab_level >= 1

        # Build prerequisite status cards for template
        # Pull real building images from infrastructure catalog
        from config_infrastructure import INFRASTRUCTURE_CATALOG
        prereq_defs = [
            {'key': 'research_station', 'name': 'Research Station', 'required_level': 3},
            {'key': 'regolith_forge', 'name': 'Regolith Forge', 'required_level': 3},
            {'key': 'robotics_lab', 'name': 'Robotics Lab', 'required_level': 1},
        ]
        for pd in prereq_defs:
            cat = INFRASTRUCTURE_CATALOG.get(pd['key'], {})
            lv1 = cat.get('levels', {}).get(1, {})
            pd['image_url'] = lv1.get('image_url', '')
        # Get building timers for any structures under construction
        building_timers = {}
        with _db_cursor() as cur:
            cur.execute("""
                SELECT structure_type, status, ready_at
                FROM pilgrim.colony_infrastructure
                WHERE user_id = %s AND structure_type IN ('robotics_lab', 'research_station', 'regolith_forge')
            """, (user_id,))
            for row in cur.fetchall():
                building_timers[row['structure_type']] = {
                    'status': row['status'],
                    'ready_at': row['ready_at'].isoformat() if row.get('ready_at') else None,
                }

        from datetime import datetime
        for pd in prereq_defs:
            current_lvl = int(levels.get(pd['key'], 0))
            bld = building_timers.get(pd['key'], {})
            is_building = bld.get('status') == 'building'
            ready_at = bld.get('ready_at')
            prereqs.append({
                'key': pd['key'], 'name': pd['name'], 'image_url': pd.get('image_url', ''),
                'required_level': pd['required_level'], 'current_level': current_lvl,
                'met': current_lvl >= pd['required_level'],
                'building': is_building, 'ready_at': ready_at,
                'not_started': current_lvl == 0 and not is_building,
            })
    except Exception as e:
        logger.error(f"robot page data: lab level lookup failed: {e}")

    # Auto-advance any ready stages so the page render is up to date.
    # tick_robot_build returns None when no robot exists (1 cursor wasted otherwise).
    robot = tick_robot_build(user_id)

    if not robot:
        # All keys the template + JSON bridge read must be present even on the
        # empty path (Jinja2 |tojson can't serialize Undefined).
        return {
            'has_robot': False,
            'is_complete': False,
            'show_cinematic': False,
            'lab_unlocked': lab_unlocked,
            'lab_level': lab_level,
            'prereqs': prereqs,
            'robot': None,
            'stages': [],
            'stages_meta': ROBOT_STAGES,
            'log': [],
            'seconds_until_next_stage': None,
            'stage_duration_seconds': STAGE_DURATION_SECONDS,
        }

    # Active or complete build
    log = get_stage_log(user_id)
    log_by_idx = {entry['stage_idx']: entry for entry in log}

    # Pair each stage with its source + log entry (or "pending" if not yet built)
    sources = robot.get('stage_sources') or []
    stages_view = []
    for s_meta in ROBOT_STAGES:
        idx = s_meta['idx']
        source = sources[idx - 1] if idx - 1 < len(sources) else None
        log_entry = log_by_idx.get(idx)
        stages_view.append({
            'idx': idx,
            'key': s_meta['key'],
            'label': s_meta['label'],
            'part': s_meta['part'],
            'status': 'complete' if log_entry else (
                'building' if idx == robot['visual_stage'] + 1 else 'pending'
            ),
            'source': source,
            'image_url': (log_entry or {}).get('image_url') or STAGE_PLACEHOLDER_IMAGES.get(s_meta['key'], PLACEHOLDER_STAGE_IMAGE),
            'tx_hash': (log_entry or {}).get('tx_hash'),
        })

    # Countdown for the currently-building stage
    seconds_until_next = None
    if robot.get('build_status') == 'in_progress' and robot.get('stage_ready_at'):
        delta = (robot['stage_ready_at'] - datetime.utcnow()).total_seconds()
        seconds_until_next = max(0, int(delta))

    return {
        'has_robot': True,
        'lab_unlocked': lab_unlocked,
        'lab_level': lab_level,
        'prereqs': prereqs,
        'robot': robot,
        'stages': stages_view,
        'stages_meta': ROBOT_STAGES,
        'log': log,
        'seconds_until_next_stage': seconds_until_next,
        'stage_duration_seconds': STAGE_DURATION_SECONDS,
        'is_complete': robot.get('build_status') == 'complete',
        'show_cinematic': (
            robot.get('build_status') == 'complete'
            and not robot.get('cinematic_played')
        ),
    }
