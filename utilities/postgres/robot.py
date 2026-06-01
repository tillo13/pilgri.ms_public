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

from utilities.postgres.core import db_cursor, ensure_table_columns

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
                dial JSONB NOT NULL DEFAULT '{"exploration":100,"logistics":0,"research":0,"expeditions":0}'::jsonb,
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
        # Past Looks gallery — every paid reroll snapshots the prior state
        # here before overwriting. Captains can scroll their full visual
        # evolution. We store the URLs (GCS objects stay in the bucket) +
        # the kind of event that produced this snapshot.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pilgrim.robot_history (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                image_url TEXT,
                video_url TEXT,
                kind TEXT,  -- 'initial_build' | 'before_image_reroll' | 'before_video_reroll' | 'lock_in'
                snapshot_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_robot_history_user ON pilgrim.robot_history(user_id, snapshot_at DESC)")
    # Robot migration columns — existence-checked so cold starts never ALTER (nor grab an
    # ACCESS EXCLUSIVE lock) when present. craftsmanship_score; build_error (forge-failure
    # banner); 4 dial base stats (#1436, each starts 5/100); recalibration test-window +
    # lifetime reforge counters; image/video stale-detection timestamps ("Bring to Life" CTA).
    ensure_table_columns('pilgrim', 'robot', {
        'craftsmanship_score': 'INTEGER NOT NULL DEFAULT 0',
        'build_error': 'TEXT',
        'stat_exploration': 'INTEGER NOT NULL DEFAULT 5',
        'stat_logistics': 'INTEGER NOT NULL DEFAULT 5',
        'stat_research': 'INTEGER NOT NULL DEFAULT 5',
        'stat_expeditions': 'INTEGER NOT NULL DEFAULT 5',
        'test_window_started_at': 'TIMESTAMP',
        'test_window_locked': 'BOOLEAN NOT NULL DEFAULT TRUE',
        'repick_count': 'INTEGER NOT NULL DEFAULT 0',
        'reroll_image_count': 'INTEGER NOT NULL DEFAULT 0',
        'reroll_video_count': 'INTEGER NOT NULL DEFAULT 0',
        'reforge_sv_spent': 'INTEGER NOT NULL DEFAULT 0',
        'image_updated_at': 'TIMESTAMP',
        'video_updated_at': 'TIMESTAMP',
    })


RARITY_WEIGHTS = {'legendary': 30, 'rare': 10, 'uncommon': 3, 'common': 1}
CRAFTSMANSHIP_MAX = 150  # 2 leg + 2 rare + 1 uncommon = 30+30+10+10+3 = 83 typical

# 2026-04-30: dial slots align to Luke's brainstorm §4 spec.
# Per Bug #1436 (Luke 2026-05-06): all 4 stats scale linearly from 5/100 at
# Foundry L0 to 100/100 at Foundry L10. Slots unlock at Foundry tiers:
# Logistics L3, Research L6, Expeditions L9.
STAT_KEYS = ['exploration', 'logistics', 'research', 'expeditions']
STAT_BASE = 5      # every Narog starts at 5/100 per stat
STAT_MAX = 100

# Foundry level required to unlock each stat slot (#1436 Luke).
# Exploration is always available — it's the slot you build the Narog with.
STAT_UNLOCK_FOUNDRY_LEVEL = {
    'exploration': 0,
    'logistics':   3,
    'research':    6,
    'expeditions': 9,
}

# #1467: canonical display copy for each Narog stat slot. Single Python source so the
# depot Foundry-ladder modal + PilgrimBot + ARIA all read identical wording (kept in
# sync with the /crew dial copy in static/js/crew-robot.js DIAL_DESCRIPTIONS). The
# depot modal pulls these via utilities/upgrades/catalog.py — never hardcode the strings
# or the thresholds there; derive both from here + STAT_UNLOCK_FOUNDRY_LEVEL.
STAT_SLOT_DISPLAY = {
    'exploration': {'label': 'Exploration', 'desc': 'Passive trail building (always on)'},
    'logistics':   {'label': 'Logistics',   'desc': 'Speeds up Depot & equipment build times'},
    'research':    {'label': 'Research',     'desc': 'Speeds up tech research while assigned'},
    'expeditions': {'label': 'Expeditions',  'desc': 'Solo scout runs while offline (coming soon)'},
}


def compute_robot_stat_value(foundry_level: int) -> int:
    """Linear stat = 5 + foundry_level × 9.5, integer-rounded, clamped [5,100].
    Sequence by Foundry level: 5, 14, 24, 33, 43, 52, 62, 71, 81, 90, 100."""
    fl = max(0, min(10, int(foundry_level or 0)))
    return max(STAT_BASE, min(STAT_MAX, int(STAT_BASE + fl * 9.5)))


def compute_robot_stats(foundry_level: int) -> Dict[str, Dict[str, Any]]:
    """For each of the 4 Narog stats return the current value, whether the
    slot is unlocked at the current Foundry level, and the foundry level
    required to unlock it. Used by /crew Narog tab + ARIA snapshot."""
    fl = max(0, int(foundry_level or 0))
    value = compute_robot_stat_value(fl)
    out = {}
    for key in STAT_KEYS:
        unlock_at = STAT_UNLOCK_FOUNDRY_LEVEL[key]
        out[key] = {
            'value': value,
            'unlocked': fl >= unlock_at,
            'unlock_at_foundry_level': unlock_at,
        }
    return out


def compute_craftsmanship_score(sources: List[Dict[str, Any]]) -> int:
    return int(sum(RARITY_WEIGHTS.get((s.get('rarity') or 'common').lower(), 1) for s in (sources or [])))


# ============================================================================
# READ
# ============================================================================

def build_narog_summary(user_id: int) -> Optional[Dict[str, Any]]:
    """Shared builder for the Narog "Passive Trails" chip.

    Bug #1441 (Luke 2026-05-14 P1): originally rendered on /home Base HQ hero.
    Luke wants it on /crew Narog tab where it logically belongs. Helper lives
    here so multiple views can call it (or in this case, just /crew — but
    keeping it portable in case home wants a stripped variant later).

    Returns None if the captain has no completed Narog.
    """
    try:
        from utilities.postgres.trails.segments import _compute_robot_trail_contribution
        robot = get_robot(user_id)
        if not robot or robot.get('build_status') != 'complete':
            return None
        with db_cursor() as cur:
            cur.execute(
                "SELECT COALESCE(SUM(robot_km), 0) AS total_km FROM pilgrim.user_trail_chains WHERE user_id = %s",
                (user_id,))
            row = cur.fetchone()
            lifetime_km = float(row['total_km'] or 0) if row else 0.0
        km_per_hour = float(_compute_robot_trail_contribution(user_id) or 0.0)
        dial = robot.get('dial') or {}
        return {
            'name': robot.get('name') or 'Narog',
            'visual_stage': int(robot.get('visual_stage') or 0),
            'exploration_pct': int(dial.get('exploration', 0) or 0),
            'km_per_hour': round(km_per_hour, 4),
            'km_per_day': round(km_per_hour * 24, 2),
            'lifetime_km': round(lifetime_km, 2),
        }
    except Exception as e:
        logger.warning(f"build_narog_summary failed for user {user_id}: {e}")
        return None


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


# 2026-04-30: Locked recipe — every Narog is forged from EXACTLY this mix:
#   2 legendary + 2 rare + 1 (common-or-uncommon) = 5 items.
# Forge no longer derives stats from items; every Narog starts at flat 5/100
# in all 4 stats. Item rarities still drive craftsmanship_score (cosmetic) and
# the visual lore of which discoveries built the Narog.
ROBOT_GATE_MIN_LEGENDARY = 2
ROBOT_GATE_MIN_RARE = 2
ROBOT_GATE_MIN_LOWTIER = 1     # at least one common OR uncommon
ROBOT_BUILD_LEGENDARY = 2
ROBOT_BUILD_RARE = 2
ROBOT_BUILD_LOWTIER = 1        # the 5th slot — 1 common-or-uncommon
ROBOT_BUILD_PER_NAME_CAP = 3   # max 3 copies of any one item_name in a Narog
ROBOT_BUILD_TOTAL_ITEMS = 5


class RobotGateError(ValueError):
    """Captain doesn't have the minimum components to start a Narog build."""
    pass


def _pick_with_diversity(items: List[Dict[str, Any]], n: int,
                         per_name_cap: int = 999,
                         name_counts: Optional[Dict[str, int]] = None) -> List[Dict[str, Any]]:
    """Pick n items from the pool, preferring distinct item types over duplicates.

    Pass 1 takes one of each unique item_name in random order. Pass 2 fills the
    remainder from whatever is left, shuffled. This biases output toward variety
    (3 distinct legendaries beats 3 copies of Crystal Sentinel) without ever
    duplicating a specific discovery row.

    `per_name_cap` + shared `name_counts` enforce the global "max 3 of any one
    item_name in a Narog" rule across multiple tier calls. Pass the same
    `name_counts` Counter through every call from pick_stage_sources so a
    captain with 53 Viking Fragments can't end up with 4-5 of them by
    consuming legendaries+rares from different tiers.
    """
    import random
    from collections import Counter
    if name_counts is None:
        name_counts = Counter()
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
    # Pass 1: one of each unique name (skip names already at cap)
    for t in types:
        if len(chosen) >= n:
            break
        if name_counts.get(t, 0) >= per_name_cap:
            continue
        if not by_type[t]:
            continue
        chosen.append(by_type[t].pop(0))
        name_counts[t] = name_counts.get(t, 0) + 1
    # Pass 2: fill from leftovers, still respecting the cap
    leftovers: List[Dict[str, Any]] = []
    for t in types:
        leftovers.extend(by_type[t])
    random.shuffle(leftovers)
    for item in leftovers:
        if len(chosen) >= n:
            break
        if name_counts.get(item['item_name'], 0) >= per_name_cap:
            continue
        chosen.append(item)
        name_counts[item['item_name']] = name_counts.get(item['item_name'], 0) + 1
    return chosen[:n]


def _load_claimed_inventory(user_id: int) -> Dict[str, List[Dict[str, Any]]]:
    """Return every claimed, not-yet-consumed discovery for a captain, grouped by rarity.

    `analyzed=true` is the canonical "consumed" flag (also used by trail
    consumption — utilities/postgres/trails/crew.py:436). Items consumed by a
    prior Narog forge stay out of the pool here so they can't be picked twice.
    """
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
              AND (ed.analyzed = FALSE OR ed.analyzed IS NULL)
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
    n_lowtier = len(inv['common']) + len(inv['uncommon'])
    return {
        'met': (n_leg >= ROBOT_GATE_MIN_LEGENDARY
                and n_rare >= ROBOT_GATE_MIN_RARE
                and n_lowtier >= ROBOT_GATE_MIN_LOWTIER),
        'legendary_count': n_leg,
        'rare_count': n_rare,
        'lowtier_count': n_lowtier,
        'min_legendary': ROBOT_GATE_MIN_LEGENDARY,
        'min_rare': ROBOT_GATE_MIN_RARE,
        'min_lowtier': ROBOT_GATE_MIN_LOWTIER,
    }


def pick_stage_sources(user_id: int) -> List[Dict[str, Any]]:
    """Pick 5 source manifests for a Narog build — locked recipe.

    Locked composition (2026-04-30):
      • EXACTLY 2 legendary
      • EXACTLY 2 rare
      • EXACTLY 1 (common-or-uncommon) — the 5th slot, biased toward
        uncommon if available, falls back to common.
      • Per-name cap: max 3 copies of any one item_name (not relevant
        with this recipe but kept for safety).

    Final list is shuffled so the same inputs produce a different stage→item
    mapping each roll.

    Raises RobotGateError if the captain doesn't have ≥2 legendary, ≥2 rare,
    and ≥1 (common-or-uncommon). Caller should surface the message verbatim.
    """
    import random
    from collections import Counter
    inv = _load_claimed_inventory(user_id)
    n_leg = len(inv['legendary'])
    n_rare = len(inv['rare'])
    n_unc = len(inv['uncommon'])
    n_com = len(inv['common'])

    if n_leg < ROBOT_BUILD_LEGENDARY or n_rare < ROBOT_BUILD_RARE or (n_unc + n_com) < ROBOT_BUILD_LOWTIER:
        raise RobotGateError(
            f"Narog construction requires {ROBOT_BUILD_LEGENDARY} legendary + "
            f"{ROBOT_BUILD_RARE} rare + {ROBOT_BUILD_LOWTIER} common-or-uncommon. "
            f"You have {n_leg} legendary, {n_rare} rare, "
            f"{n_unc + n_com} common-or-uncommon."
        )

    name_counts: Counter = Counter()

    chosen: List[Dict[str, Any]] = list(_pick_with_diversity(
        inv['legendary'], ROBOT_BUILD_LEGENDARY,
        per_name_cap=ROBOT_BUILD_PER_NAME_CAP, name_counts=name_counts,
    ))
    chosen.extend(_pick_with_diversity(
        inv['rare'], ROBOT_BUILD_RARE,
        per_name_cap=ROBOT_BUILD_PER_NAME_CAP, name_counts=name_counts,
    ))
    # 5th slot: prefer uncommon, fall through to common.
    lowtier_pool = inv['uncommon'] if n_unc else inv['common']
    chosen.extend(_pick_with_diversity(
        lowtier_pool, ROBOT_BUILD_LOWTIER,
        per_name_cap=ROBOT_BUILD_PER_NAME_CAP, name_counts=name_counts,
    ))

    random.shuffle(chosen)
    return chosen[:ROBOT_BUILD_TOTAL_ITEMS]


# ============================================================================
# WRITE
# ============================================================================

def start_robot_build(user_id: int, sources: List[Dict[str, Any]],
                      initial_image_url: Optional[str] = None) -> Dict[str, Any]:
    """Initialize a robot build with the 5 pre-picked source manifests.

    PRODUCTION SEMANTICS:
      - The 5 source `discovery_id`s are marked `analyzed=true` in the SAME
        transaction as the robot row INSERT. If any source has already been
        consumed (by a prior forge or trail use), the whole transaction
        rolls back and a RobotGateError is raised — the captain is told to
        re-roll. This guarantees a forged Narog always corresponds to 5
        real consumed items.
      - Synthetic 'home_base' sources (from pick_stage_sources fallback)
        carry discovery_id=None and are NOT marked consumed. They're free
        filler when the captain has < 5 real items.

    Stage 1's stage_ready_at is set to NOW + STAGE_DURATION_SECONDS so the
    auto-tick can advance it on the next page load.
    """
    ensure_robot_tables()
    score = compute_craftsmanship_score(sources)
    real_ids = [int(s['discovery_id']) for s in (sources or [])
                if s.get('discovery_id') is not None]
    with db_cursor(commit=True) as cur:
        # Insert/upsert the robot row first so we have something to roll back
        # if consumption fails.
        cur.execute("""
            INSERT INTO pilgrim.robot
                (user_id, build_status, visual_stage, current_image_url,
                 stage_images, stage_sources, craftsmanship_score,
                 started_at, stage_started_at, stage_ready_at, updated_at,
                 build_error)
            VALUES (%s, 'in_progress', 0, %s, '[]'::jsonb, %s::jsonb, %s,
                    NOW(), NOW(), NOW() + (%s * INTERVAL '1 second'), NOW(),
                    NULL)
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
                build_error = NULL,
                updated_at = NOW()
            RETURNING *
        """, (user_id, initial_image_url, json.dumps(sources), score,
              STAGE_DURATION_SECONDS, STAGE_DURATION_SECONDS))
        row = cur.fetchone()
        # Wipe any prior stage log so re-builds start fresh
        cur.execute("DELETE FROM pilgrim.robot_stage_log WHERE user_id = %s", (user_id,))

        # Consume the 5 real source discoveries in the same transaction.
        # Re-validates ownership + unconsumed state at the moment of the
        # INSERT (paranoia against stale lock-in client state).
        if real_ids:
            cur.execute("""
                UPDATE pilgrim.expedition_discoveries
                SET analyzed = TRUE, analyzed_at = NOW()
                WHERE id = ANY(%s::int[])
                  AND (analyzed = FALSE OR analyzed IS NULL)
                  AND claimed_by_user = TRUE
                  AND expedition_id IN (
                      SELECT id FROM pilgrim.expeditions WHERE user_id = %s
                  )
                RETURNING id
            """, (real_ids, user_id))
            consumed_ids = [r['id'] for r in cur.fetchall() or []]
            if len(consumed_ids) != len(real_ids):
                missing = set(real_ids) - set(consumed_ids)
                raise RobotGateError(
                    f"One or more source items are no longer available "
                    f"(IDs: {sorted(missing)}). Please re-roll."
                )
            logger.info(
                f"narog: user {user_id} consumed {len(consumed_ids)} discoveries "
                f"for forge: {consumed_ids}"
            )
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
                image_updated_at = CASE WHEN %s IS NOT NULL THEN NOW() ELSE image_updated_at END,
                visual_stage = GREATEST(visual_stage, %s::int),
                stage_started_at = NOW(),
                stage_ready_at = NOW() + (%s * INTERVAL '1 second'),
                build_status = CASE WHEN %s::int >= 5 THEN 'complete' ELSE 'in_progress' END,
                completed_at = CASE WHEN %s::int >= 5 THEN NOW() ELSE completed_at END,
                updated_at = NOW()
            WHERE user_id = %s
            RETURNING *
        """, (stage_idx, image_url, tx_hash, image_url, image_url, stage_idx,
              STAGE_DURATION_SECONDS, stage_idx, stage_idx, user_id))
        robot_row = cur.fetchone()
        return {'log': log_row, 'robot': dict(robot_row) if robot_row else None}


# ============================================================================
# SEPOLIA BROADCAST — one real on-chain tx per stage
# ============================================================================
# Mirrors the bond pattern at utilities/aria/bonds.py:142-221. Each stage row
# is INSERTed with tx_hash=NULL; this background worker writes the message
# (hex-encoded) to Sepolia and UPDATEs the row when the chain returns. Failures
# log + leave tx_hash=NULL so the manifest modal renders "Sepolia broadcast
# pending" instead of a fabricated hash.

def _build_narog_stage_message(user_id: int, stage_idx: int,
                               source_manifest: Dict[str, Any]) -> str:
    """Compose the human-readable on-chain message embedded in tx data.

    Format: NAROG_STAGE_{n} | uid:{user_id} | {item_name} | {landmark} | {lat,lon}
    Length is bounded (~200 bytes max) so a 50000-gas tx with EIP-1559 gas
    headroom comfortably fits the data field. The cryptic Mars-mission
    suffix is added by sepolia_utils.append_cryptic_mars_message in the
    transaction manager — this function only builds the prefix.
    """
    stage_meta = ROBOT_STAGES[stage_idx - 1]
    item = (source_manifest.get('item_name') or 'unknown_item')[:48]
    landmark = (source_manifest.get('landmark_name') or 'unknown_site')[:48]
    lat = source_manifest.get('lat')
    lon = source_manifest.get('lon')
    coord = f"{lat:.4f},{lon:.4f}" if (lat is not None and lon is not None) else "?"
    return (
        f"NAROG_STAGE_{stage_idx}_{stage_meta['key']} | uid:{user_id} | "
        f"{item} | {landmark} | {coord}"
    )


def _send_narog_stage_transaction(miner, wallet_address: str,
                                  private_key: str, message: str) -> Optional[str]:
    """Send a Sepolia tx with the narog stage message embedded.

    Mirrors utilities/aria/bonds.py:_send_bond_transaction. Returns the tx
    hash on success, None on failure. 0.0000001 ETH minimal-value tx — the
    payload is the data field, not the value transfer.
    """
    try:
        input_data = '0x' + message.encode('utf-8').hex() if message else '0x'
        gas_config = miner.gas_estimator.get_optimal_gas_price(
            use_dynamic=True, manual_gwei=1, speed='standard'
        )
        nonce = miner.w3.eth.get_transaction_count(wallet_address)
        value_wei = miner.w3.to_wei(0.0000001, 'ether')

        if gas_config['type'] == 'eip1559':
            tx = {
                'to': wallet_address,
                'value': value_wei,
                'gas': 50000,
                'maxFeePerGas': gas_config['maxFeePerGas'],
                'maxPriorityFeePerGas': gas_config['maxPriorityFeePerGas'],
                'nonce': nonce,
                'chainId': 11155111,
                'data': input_data,
            }
        else:
            tx = {
                'to': wallet_address,
                'value': value_wei,
                'gas': 50000,
                'gasPrice': gas_config['gasPrice'],
                'nonce': nonce,
                'chainId': 11155111,
                'data': input_data,
            }
        return miner.transaction_manager.sign_and_send_transaction(
            tx, private_key, context="narog_stage"
        )
    except Exception as e:
        logger.error(f"Narog stage tx failed: {e}")
        return None


def broadcast_stage_async(user_id: int, stage_idx: int,
                          source_manifest: Dict[str, Any]) -> None:
    """Fire-and-forget Sepolia broadcast for one narog stage.

    Dry-run users (utilities.admin_utils.NAROG_DRY_RUN_USER_IDS) skip the
    broadcast entirely — no thread spawned, no chain write, no nonce
    burn. The stage_log row stays with tx_hash=NULL forever for that
    captain's dry-run forge. This keeps the on-chain history pristine
    for the canonical run; Andy can rehearse the cinematic infinitely
    without polluting the ARG breadcrumb trail.

    Spawns a daemon thread that connects to Sepolia, sends the tx, and
    UPDATEs pilgrim.robot_stage_log.tx_hash + data_hex on success. Safe to
    call from any context — failures only log; the stage row stays
    intact with tx_hash=NULL.
    """
    from utilities.admin_utils import is_narog_dry_run
    if is_narog_dry_run(user_id):
        logger.info(
            f"narog stage {stage_idx} broadcast SKIPPED (dry-run): "
            f"user {user_id} | {source_manifest.get('item_name')} | "
            f"{source_manifest.get('landmark_name')}"
        )
        return

    import threading

    def _worker():
        try:
            from utilities.sepolia_utils import MarsAsteroidMiner
            from utilities.postgres.wallets import get_user_primary_sepolia_wallet
            wallet = get_user_primary_sepolia_wallet(user_id)
            if not wallet or not wallet.get('wallet_address') or not wallet.get('wallet_private_key'):
                logger.warning(
                    f"narog stage {stage_idx} broadcast: user {user_id} has no "
                    f"primary Sepolia wallet; tx_hash will remain NULL"
                )
                return

            miner = MarsAsteroidMiner()
            if not miner.connect():
                logger.error(
                    f"narog stage {stage_idx} broadcast: miner.connect() failed "
                    f"for user {user_id}"
                )
                return

            message = _build_narog_stage_message(user_id, stage_idx, source_manifest)
            tx_hash = _send_narog_stage_transaction(
                miner, wallet['wallet_address'], wallet['wallet_private_key'], message
            )
            if not tx_hash:
                logger.error(
                    f"narog stage {stage_idx} broadcast: tx send returned None "
                    f"for user {user_id}"
                )
                return

            data_hex = '0x' + message.encode('utf-8').hex()
            with db_cursor(commit=True) as cur:
                cur.execute("""
                    UPDATE pilgrim.robot_stage_log
                    SET tx_hash = %s, data_hex = %s
                    WHERE user_id = %s AND stage_idx = %s
                """, (tx_hash, data_hex, user_id, stage_idx))
            logger.info(
                f"✅ narog stage {stage_idx} tx broadcast: {tx_hash[:20]}... "
                f"for user {user_id}"
            )
        except Exception as e:
            logger.exception(
                f"narog stage {stage_idx} broadcast crashed for user {user_id}: {e}"
            )

    threading.Thread(
        target=_worker,
        name=f"narog-stage-tx-{user_id}-{stage_idx}",
        daemon=True,
    ).start()


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
    in [0, 100]. The values represent INDEPENDENT allocations (% of base stat
    devoted to each task) — sum can be anything in [0, 400]. Unallocated effort
    is "idle" robot time. The frontend additionally enforces sum ≤ 100 across
    UNLOCKED dials as a soft cap, but the server doesn't require it (locked
    captains may have lower-phase dials they can't touch yet).
    Raises ValueError on invalid per-key input.
    """
    if not isinstance(dial, dict):
        raise ValueError("dial must be a dict")
    cleaned = {}
    for k in DIAL_KEYS:
        v = dial.get(k, 0)
        if not isinstance(v, int) or v < 0 or v > 100 or v % 5 != 0:
            raise ValueError(f"dial.{k} must be a non-negative multiple of 5 in [0, 100], got {v!r}")
        cleaned[k] = v

    ensure_robot_tables()
    with db_cursor(commit=True) as cur:
        # #1492: capture the OLD dial so we can rescale in-progress work to the new
        # allocation (Luke: "10 hours left → 8 hours left" when you move the dial).
        cur.execute("SELECT dial FROM pilgrim.robot WHERE user_id = %s", (user_id,))
        prev = cur.fetchone()
        old_dial = dict(prev['dial']) if prev and prev.get('dial') else {}
        cur.execute("""
            UPDATE pilgrim.robot SET dial = %s::jsonb, updated_at = NOW()
            WHERE user_id = %s
            RETURNING dial
        """, (json.dumps(cleaned), user_id))
        row = cur.fetchone()
    # Apply the change to in-progress builds/research live (separate transaction).
    if row:
        from utilities.postgres.robot_dial import recompute_in_progress_for_dial
        recompute_in_progress_for_dial(user_id, old_dial, cleaned)
    return dict(row['dial']) if row else cleaned


class ReforgeError(Exception):
    """Raised when a recalibration action can't proceed (cap hit, insufficient
    funds, no robot, locked window). Caller surfaces .message verbatim."""
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


COUNTER_COL_BY_ACTION = {
    'repick':       'repick_count',
    'reroll_image': 'reroll_image_count',
    'reroll_video': 'reroll_video_count',
}


def _ensure_test_window(user_id: int) -> None:
    """If the captain's narog is currently locked, open a fresh 72hr test window.
    Idempotent — does nothing when the window is already open. Called at the
    start of every recalibration action so Andy/Luke (post-canonical) can
    re-enter the test loop without a separate 'start window' call."""
    with db_cursor(commit=True) as cur:
        cur.execute("""
            UPDATE pilgrim.robot
            SET test_window_started_at = COALESCE(test_window_started_at, NOW()),
                test_window_locked = FALSE,
                updated_at = NOW()
            WHERE user_id = %s AND test_window_locked = TRUE
        """, (user_id,))


def charge_reforge_action(user_id: int, action: str) -> Dict[str, Any]:
    """Validate cap + balance, deduct shards/SV, increment counter for one
    recalibration action. Atomic. Raises ReforgeError on any failure.

    Action must be one of: 'repick' | 'reroll_image' | 'reroll_video'.
    Returns {'cost': {shards, sv}, 'new_count': int, 'cap': int}.

    Charging is idempotent-per-call: each click = one charge. No silent retries.
    """
    from config import (NAROG_REFORGE_LIFETIME_CAPS,
                        narog_reforge_cost)
    from utilities.postgres.wallets import get_user_primary_sepolia_wallet, update_sepolia_wallet_balance
    from utilities.depot_utils import display_to_eth
    from utilities.tech_utils import _get_available_sv

    col = COUNTER_COL_BY_ACTION.get(action)
    if not col:
        raise ReforgeError(f"unknown recalibration action: {action!r}")
    cap = NAROG_REFORGE_LIFETIME_CAPS.get(action, 0)
    cost = narog_reforge_cost(action)

    ensure_robot_tables()

    # Pull current robot row + counter; bail if no robot or cap hit.
    with db_cursor() as cur:
        cur.execute(f"""
            SELECT build_status, {col} as cur_count
            FROM pilgrim.robot WHERE user_id = %s
        """, (user_id,))
        row = cur.fetchone()
        if not row:
            raise ReforgeError("No Narog to recalibrate.", status=404)
        if row['build_status'] != 'complete':
            raise ReforgeError("Wait for the current build to finish before recalibrating.", status=409)
        if (row['cur_count'] or 0) >= cap:
            raise ReforgeError(
                f"This recalibration option has reached its lifetime limit ({cap}). "
                "The hardware can't recalibrate further.",
                status=409,
            )

    # Validate balance up-front so we don't charge SV then fail on shards.
    wallet = get_user_primary_sepolia_wallet(user_id)
    if not wallet:
        raise ReforgeError("No wallet found for this captain.", status=500)
    bal_eth = float(wallet.get('current_balance_eth') or 0.0)
    bal_shards = bal_eth * 10_000_000
    if bal_shards < cost['shards']:
        raise ReforgeError(
            f"Need {cost['shards']} shards, you have {int(bal_shards)}.",
            status=402,
        )
    # SV check uses _get_available_sv (same source as the status bar): claimed
    # discoveries + passive scientist generation − SV spent on tech research −
    # SV already spent on prior reforges. Bug #1438: previously read the legacy
    # users.research_points column which was always 0, blocking every reforge.
    if cost['sv'] > 0:
        cur_sv = int(_get_available_sv(user_id))
        if cur_sv < cost['sv']:
            raise ReforgeError(
                f"Need {cost['sv']} science, you have {cur_sv}.",
                status=402,
            )

    # Charge shards (sepolia wallet update). Cheap helper; tx hash NOT recorded
    # for recalibration so the on-chain breadcrumb trail isn't polluted with
    # micro-payments. The shards leave the wallet though — same as Shard Rush.
    cost_eth = display_to_eth(cost['shards'])
    update_sepolia_wallet_balance(wallet['wallet_address'], bal_eth - cost_eth)

    # Charge SV by recording the spend on the robot row. _get_available_sv()
    # subtracts SUM(reforge_sv_spent) so the status bar drops in real time and
    # future reforge checks see the reduced balance.
    if cost['sv'] > 0:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE pilgrim.robot
                SET reforge_sv_spent = reforge_sv_spent + %s, updated_at = NOW()
                WHERE user_id = %s
            """, (cost['sv'], user_id))

    # Bump counter. Done LAST so a transient DB hiccup doesn't leave us with a
    # bumped counter and no spend (caller can retry safely on charge failures).
    with db_cursor(commit=True) as cur:
        cur.execute(f"""
            UPDATE pilgrim.robot
            SET {col} = {col} + 1, updated_at = NOW()
            WHERE user_id = %s
            RETURNING {col} as new_count
        """, (user_id,))
        new_count = cur.fetchone()['new_count']

    _ensure_test_window(user_id)
    logger.info(f"narog reforge: user {user_id} {action} #{new_count} (cost {cost})")
    return {'cost': cost, 'new_count': new_count, 'cap': cap}


def lock_in_narog(user_id: int) -> Dict[str, Any]:
    """Close the 72hr test window and mark the Narog canonical. Idempotent —
    locking an already-locked Narog is a no-op success.

    NOTE: For the first cut, lock-in is a local-state flag only. Future work:
    fire on-chain broadcasts here when a captain's been in test mode without
    canonical tx (i.e. brand-new captains in the future 72hr free window).
    For Andy + Luke (post-canonical), lock-in just exits the test loop —
    their canonical tx was written at first forge.
    """
    ensure_robot_tables()
    with db_cursor(commit=True) as cur:
        cur.execute("""
            UPDATE pilgrim.robot
            SET test_window_locked = TRUE,
                test_window_started_at = NULL,
                updated_at = NOW()
            WHERE user_id = %s
            RETURNING build_status
        """, (user_id,))
        row = cur.fetchone()
        if not row:
            raise ReforgeError("No Narog to lock in.", status=404)
    return {'locked': True}


def get_recalibration_state(user_id: int) -> Dict[str, Any]:
    """Returns the current recalibration counters + caps + costs + window state
    for a captain. Frontend uses this to render the Recalibration card."""
    from config import (NAROG_REFORGE_LIFETIME_CAPS,
                        NAROG_TEST_WINDOW_HOURS,
                        narog_reforge_cost)
    ensure_robot_tables()
    with db_cursor() as cur:
        cur.execute("""
            SELECT repick_count, reroll_image_count, reroll_video_count,
                   test_window_started_at, test_window_locked, build_status
            FROM pilgrim.robot WHERE user_id = %s
        """, (user_id,))
        row = cur.fetchone()
    if not row:
        return {'available': False}

    counters = {
        'repick':       int(row['repick_count'] or 0),
        'reroll_image': int(row['reroll_image_count'] or 0),
        'reroll_video': int(row['reroll_video_count'] or 0),
    }
    actions = {}
    for action in ('repick', 'reroll_image', 'reroll_video'):
        cap = NAROG_REFORGE_LIFETIME_CAPS[action]
        used = counters[action]
        actions[action] = {
            'cost': narog_reforge_cost(action),
            'used': used,
            'cap': cap,
            'remaining': max(0, cap - used),
        }

    # Window state — seconds remaining if test window is open
    window_seconds_remaining = None
    started = row['test_window_started_at']
    locked = bool(row['test_window_locked'])
    if started and not locked:
        elapsed = (datetime.utcnow() - started).total_seconds()
        window_seconds_remaining = max(0, NAROG_TEST_WINDOW_HOURS * 3600 - elapsed)

    return {
        'available': row['build_status'] == 'complete',
        'actions': actions,
        'locked': locked,
        'window_seconds_remaining': window_seconds_remaining,
        'window_hours_total': NAROG_TEST_WINDOW_HOURS,
    }


def snapshot_narog_history(user_id: int, kind: str) -> bool:
    """Insert a snapshot of the captain's CURRENT robot image+video pair into
    robot_history before it gets overwritten. `kind` describes what triggered
    the snapshot ('before_image_reroll', 'before_video_reroll', etc.)."""
    ensure_robot_tables()
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO pilgrim.robot_history (user_id, image_url, video_url, kind)
                SELECT %s, current_image_url, video_url, %s
                FROM pilgrim.robot
                WHERE user_id = %s
                  AND (current_image_url IS NOT NULL OR video_url IS NOT NULL)
            """, (user_id, kind, user_id))
            return cur.rowcount > 0
    except Exception as e:
        logger.warning(f"snapshot_narog_history failed user={user_id} kind={kind}: {e}")
        return False


def get_narog_history(user_id: int, limit: int = 50) -> List[Dict[str, Any]]:
    """Past Looks gallery feed — chronological history (newest first) of every
    captured snapshot for this captain. Excludes the CURRENT live state.
    """
    ensure_robot_tables()
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT id, image_url, video_url, kind, snapshot_at
                FROM pilgrim.robot_history
                WHERE user_id = %s
                ORDER BY snapshot_at DESC, id DESC
                LIMIT %s
            """, (user_id, limit))
            rows = cur.fetchall() or []
            return [{
                'id': r['id'],
                'image_url': r['image_url'],
                'video_url': r['video_url'],
                'kind': r['kind'],
                'snapshot_at': r['snapshot_at'].isoformat() if r['snapshot_at'] else None,
            } for r in rows]
    except Exception as e:
        logger.error(f"get_narog_history failed user={user_id}: {e}")
        return []


def repick_narog_components(user_id: int) -> Dict[str, Any]:
    """Restore the 5 currently-consumed source items, pick 5 new ones, mark
    them consumed, replace stage_sources. Hero image + video are NOT touched —
    captain re-rolls those separately if they want updates.

    BUGFIX 2026-04-30: the restore + pick must commit in separate transactions.
    pick_stage_sources opens its own connection and won't see the restored
    items if they're still in an uncommitted transaction. So the old flow
    failed for captains whose commons/uncommons had all been consumed by trail
    building — the restored items weren't visible in time for the gate.
    """
    ensure_robot_tables()
    with db_cursor() as cur:
        cur.execute("SELECT stage_sources FROM pilgrim.robot WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
    if not row:
        raise ReforgeError("No Narog to recalibrate.", status=404)

    old_sources = list(row['stage_sources'] or [])
    old_ids = [int(s['discovery_id']) for s in old_sources if s.get('discovery_id') is not None]

    # Step 1: restore old items in its own committed transaction so the next
    # pick query sees them in inventory.
    if old_ids:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE pilgrim.expedition_discoveries
                SET analyzed = FALSE, analyzed_at = NULL
                WHERE id = ANY(%s::int[])
                  AND expedition_id IN (SELECT id FROM pilgrim.expeditions WHERE user_id = %s)
            """, (old_ids, user_id))

    # Step 2: pick fresh 5 from the now-larger inventory pool. If this fails
    # (insufficient gate), the old items are still restored — captain can
    # accumulate commons/uncommons via more expeditions and try again.
    try:
        new_sources = pick_stage_sources(user_id)
    except RobotGateError as e:
        raise ReforgeError(str(e), status=409)
    new_ids = [int(s['discovery_id']) for s in new_sources if s.get('discovery_id') is not None]

    # Step 3: consume the new picks + write stage_sources atomically.
    with db_cursor(commit=True) as cur:
        if new_ids:
            cur.execute("""
                UPDATE pilgrim.expedition_discoveries
                SET analyzed = TRUE, analyzed_at = NOW()
                WHERE id = ANY(%s::int[])
                  AND expedition_id IN (SELECT id FROM pilgrim.expeditions WHERE user_id = %s)
            """, (new_ids, user_id))

        score = compute_craftsmanship_score(new_sources)
        cur.execute("""
            UPDATE pilgrim.robot
            SET stage_sources = %s::jsonb, craftsmanship_score = %s, updated_at = NOW()
            WHERE user_id = %s
        """, (json.dumps(new_sources), score, user_id))

    logger.info(f"narog repick: user {user_id} swapped {len(old_ids)} → {len(new_ids)} components")
    return {'new_sources': new_sources, 'craftsmanship_score': score}


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
                    "UPDATE pilgrim.robot SET video_url = %s, video_updated_at = NOW(), updated_at = NOW() WHERE user_id = %s",
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
            'error': 'Narog Foundry required. Build the Narog Foundry in your Colony first.',
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

    # start_robot_build consumes the 5 source discoveries atomically. If any
    # has been used since the captain saw them in the preview (e.g., consumed
    # by trail-building in another tab), it raises RobotGateError and the
    # whole transaction rolls back — captain re-rolls.
    try:
        start_robot_build(user_id, sources, initial_image_url=PLACEHOLDER_STAGE_IMAGE)
    except RobotGateError as e:
        return {'success': False, 'error': str(e)}, 409

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
        # Prereq matches Luke's brainstorm spec (robot-crew §2, 2026-04-10):
        # "Robot cannot begin construction until you get a Level 1 Robotics Lab."
        # The server gate at start_build_with_name_prefetch enforces this exact
        # rule. RS+RF over-promises were UI-only drift; removed to keep card
        # and gate consistent.
        prereq_defs = [
            {'key': 'robotics_lab', 'name': 'Narog Foundry', 'required_level': 1},
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
                WHERE user_id = %s AND structure_type = 'robotics_lab'
            """, (user_id,))
            for row in cur.fetchall():
                building_timers[row['structure_type']] = {
                    'status': row['status'],
                    'ready_at': row['ready_at'].isoformat() if row.get('ready_at') else None,
                }

        # datetime is already imported at module level (line 14). A local
        # `from datetime import datetime` here would shadow the module import
        # and trigger UnboundLocalError at line ~1038 if the try-block raised
        # before reaching this re-import.
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

    # Override stat columns with values derived from current Foundry level
    # (#1436 — Luke's spec: linear ramp 5→100 across L0→L10). The columns
    # exist but are no longer the source of truth; they default to 5 only.
    stat_meta = compute_robot_stats(lab_level)
    for key in STAT_KEYS:
        robot[f'stat_{key}'] = stat_meta[key]['value']

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
        'stat_meta': stat_meta,
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
