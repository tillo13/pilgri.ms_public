"""
Tech Tree System for Pilgrims
==============================
Handles research progression: check eligibility, start research,
auto-complete on timer, calculate effects.

Scientific Value (SV) comes from the sum of discovery base_scientific_value
minus SV already spent on research (tracked in player_techs.sp_cost).
"""
import logging
import threading
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from config import (
    TECH_CATALOG, SCIENTIST_BRANCHES, SCIENTIST_SECONDARY_BRANCHES,
    get_scientist_branch_bonuses, TECH_MIGRATION_MAP
)
from utilities.postgres.core import db_cursor

logger = logging.getLogger(__name__)
_schema_ensured = False


def ensure_player_techs_table():
    """Create player_techs table if not exists, with branch_level tracking."""
    global _schema_ensured
    if _schema_ensured:
        return
    _schema_ensured = True
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS pilgrim.player_techs (
                    user_id INTEGER REFERENCES pilgrim.users(id),
                    branch VARCHAR(50) NOT NULL,
                    tech_key VARCHAR(50) NOT NULL,
                    branch_level INTEGER DEFAULT 1,
                    status VARCHAR(20) DEFAULT 'locked',
                    research_started_at TIMESTAMP,
                    research_duration_seconds INTEGER,
                    completed_at TIMESTAMP,
                    sp_cost INTEGER,
                    tx_hash VARCHAR(255),
                    PRIMARY KEY (user_id, branch, tech_key, branch_level)
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_player_techs_user
                ON pilgrim.player_techs(user_id)
            """)
            # Add branch_level column if table existed without it
            cur.execute("""
                ALTER TABLE pilgrim.player_techs
                ADD COLUMN IF NOT EXISTS branch_level INTEGER DEFAULT 1
            """)
            # Create unique constraint for ON CONFLICT to work (handles migration from old PK)
            cur.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_player_techs_unique
                ON pilgrim.player_techs(user_id, branch, tech_key, branch_level)
            """)
    except Exception as e:
        logger.error(f"Failed to create player_techs table: {e}")


def _get_user_completed_techs(user_id: int, branch_level: int = None) -> Dict[str, list]:
    """
    Get completed tech keys grouped by branch.
    If branch_level specified, only return completions at that level.
    """
    ensure_player_techs_table()
    with db_cursor() as cur:
        if branch_level:
            cur.execute("""
                SELECT branch, tech_key FROM pilgrim.player_techs
                WHERE user_id = %s AND status = 'completed' AND branch_level = %s
            """, (user_id, branch_level))
        else:
            cur.execute("""
                SELECT branch, tech_key, COALESCE(branch_level, 1) as branch_level
                FROM pilgrim.player_techs
                WHERE user_id = %s AND status = 'completed'
            """, (user_id,))
        rows = cur.fetchall()
    result = {}
    for row in rows:
        branch = row['branch']
        if branch not in result:
            result[branch] = []
        result[branch].append(row['tech_key'])
    return result


def _get_active_research(user_id: int) -> Optional[Dict]:
    """Get current researching tech, if any. Per-request memoized."""
    from utilities.postgres.core import request_memo
    return request_memo(('_get_active_research', user_id), lambda: _get_active_research_uncached(user_id))


def _get_active_research_uncached(user_id: int) -> Optional[Dict]:
    ensure_player_techs_table()
    with db_cursor() as cur:
        cur.execute("""
            SELECT branch, tech_key, COALESCE(branch_level, 1) as branch_level,
                   research_started_at, research_duration_seconds, sp_cost
            FROM pilgrim.player_techs
            WHERE user_id = %s AND status = 'researching'
        """, (user_id,))
        return cur.fetchone()


def _auto_complete_research(user_id: int) -> Optional[Dict]:
    """Check if active research timer has elapsed. If so, mark completed."""
    row = _get_active_research(user_id)
    if not row:
        return None

    started = row['research_started_at']
    duration = row['research_duration_seconds']
    now = datetime.now(timezone.utc)

    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)

    elapsed = (now - started).total_seconds()
    if elapsed < duration:
        return None

    branch_level = row['branch_level']

    # Complete it
    with db_cursor(commit=True) as cur:
        cur.execute("""
            UPDATE pilgrim.player_techs
            SET status = 'completed', completed_at = NOW()
            WHERE user_id = %s AND branch = %s AND tech_key = %s AND branch_level = %s
        """, (user_id, row['branch'], row['tech_key'], branch_level))

    # Background blockchain tx
    def do_blockchain():
        try:
            from utilities.sepolia_utils import MarsAsteroidMiner
            from utilities.postgres.wallets import get_user_primary_sepolia_wallet
            wallet = get_user_primary_sepolia_wallet(user_id)
            if not wallet:
                return
            miner = MarsAsteroidMiner()
            tech = _get_tech_config(row['branch'], row['tech_key'], branch_level)
            tech_name = tech.get('name', row['tech_key']) if tech else row['tech_key']
            result = miner.send_sepolia_reward_fast(
                to_address=wallet['wallet_address'],
                amount_eth=0.0000001,
                message=f"TECH_COMPLETE:{row['branch']}/{tech_name}",
                context="tech_complete"
            )
            if result and result.get('tx_hash'):
                from utilities.postgres.wallets import update_sepolia_wallet_balance
                update_sepolia_wallet_balance(
                    wallet['wallet_address'],
                    wallet.get('current_balance_eth', 0) + 0.0000001
                )
                with db_cursor(commit=True) as cur2:
                    cur2.execute("""
                        UPDATE pilgrim.player_techs SET tx_hash = %s
                        WHERE user_id = %s AND branch = %s AND tech_key = %s AND branch_level = %s
                    """, (result['tx_hash'], user_id, row['branch'], row['tech_key'], branch_level))
        except Exception as e:
            logger.error(f"Tech blockchain tx failed: {e}")

    thread = threading.Thread(target=do_blockchain)
    thread.start()

    logger.info(f"Tech auto-completed: user={user_id}, {row['branch']}/{row['tech_key']} @ level {branch_level}")

    # Check if branch leveled up (all 5 techs done at current level)
    branch_leveled_up = False
    completed_at_level = _get_completed_techs_at_level(user_id, row['branch'], branch_level)
    if len(completed_at_level) >= 5 and branch_level < 10:
        branch_leveled_up = True
        logger.info(f"🎉 Branch level up! User {user_id} {row['branch']} → Level {branch_level + 1}")
        # Generate new icons for next level via Kontext (background)
        try:
            from utilities.upgrade_image_utils import generate_tech_branch_icons
            thread = threading.Thread(
                target=generate_tech_branch_icons,
                args=(row['branch'], branch_level + 1, user_id),
            )
            thread.start()
        except Exception as img_err:
            logger.warning(f"Tech icon generation failed (non-blocking): {img_err}")

    return {
        'branch': row['branch'],
        'tech_key': row['tech_key'],
        'branch_level': branch_level,
        'branch_leveled_up': branch_leveled_up,
    }


def _get_tech_config(branch: str, tech_key: str, branch_level: int = 1) -> Optional[Dict]:
    """
    Get tech config from TECH_CATALOG.

    Uses 'techs' structure: branch_data['techs'][tech_key]
    Returns config with costs/effects scaled to branch_level.
    """
    from config_tech import get_tech_level_stats
    branch_data = TECH_CATALOG.get(branch)
    if not branch_data:
        return None

    techs = branch_data.get('techs', {})
    tech_data = techs.get(tech_key)
    if not tech_data:
        return None

    # Return scaled stats for this branch level
    return get_tech_level_stats(branch, tech_key, branch_level)


def _get_user_branch_levels(user_id: int) -> Dict[str, int]:
    """
    Get user's current branch level per branch (1-10).

    Branch level advances when ALL 5 techs are completed at current level.
    Level 1 = starting. Complete 5 techs → Level 2. Repeat up to Level 10.

    Returns: {'exploration': 1, 'vehicles': 2, 'power': 1, 'extraction': 1}
    """
    ensure_player_techs_table()
    branch_levels = {branch: 1 for branch in TECH_CATALOG.keys()}

    with db_cursor() as cur:
        # Get completed tech counts per branch per level
        cur.execute("""
            SELECT branch, COALESCE(branch_level, 1) as level, COUNT(DISTINCT tech_key) as tech_count
            FROM pilgrim.player_techs
            WHERE user_id = %s AND status = 'completed'
            GROUP BY branch, COALESCE(branch_level, 1)
            ORDER BY branch, level
        """, (user_id,))
        rows = cur.fetchall()

    # Build completions map: branch → {level: count}
    branch_completions = {}
    for row in rows:
        branch = row['branch']
        level = row['level'] or 1
        count = row['tech_count']
        if branch not in branch_completions:
            branch_completions[branch] = {}
        branch_completions[branch][level] = count

    # For each branch, find highest level where all 5 techs are done
    for branch, level_counts in branch_completions.items():
        if branch not in branch_levels:
            continue
        current_level = 1
        # Advance level for each complete 5-tech cycle
        while level_counts.get(current_level, 0) >= 5:
            current_level += 1
            if current_level > 10:
                current_level = 10
                break
        branch_levels[branch] = current_level

    return branch_levels


def _get_completed_techs_at_level(user_id: int, branch: str, branch_level: int) -> list:
    """Get list of tech_keys completed at a specific branch level. Per-request memoized."""
    from utilities.postgres.core import request_memo
    return request_memo(
        ('_get_completed_techs_at_level', user_id, branch, branch_level),
        lambda: _get_completed_techs_at_level_uncached(user_id, branch, branch_level),
    )


def _get_completed_techs_at_level_uncached(user_id: int, branch: str, branch_level: int) -> list:
    ensure_player_techs_table()
    with db_cursor() as cur:
        cur.execute("""
            SELECT tech_key FROM pilgrim.player_techs
            WHERE user_id = %s AND branch = %s AND status = 'completed'
            AND COALESCE(branch_level, 1) = %s
        """, (user_id, branch, branch_level))
        rows = cur.fetchall()
    return [row['tech_key'] for row in rows]


# Backward compat alias
def _get_user_tech_levels(user_id: int) -> Dict[str, int]:
    """Alias for _get_user_branch_levels for backward compatibility."""
    return _get_user_branch_levels(user_id)


def _get_branch_effects(user_id: int, branch: str) -> Dict[str, Any]:
    """
    Get cumulative effects from all completed techs in a branch across all levels.
    Effects scale based on which branch_level each tech was completed at.
    """
    from config_tech import scale_effects
    effects = {}
    branch_data = TECH_CATALOG.get(branch)
    if not branch_data:
        return effects

    techs_config = branch_data.get('techs', {})

    with db_cursor() as cur:
        cur.execute("""
            SELECT tech_key, COALESCE(branch_level, 1) as branch_level
            FROM pilgrim.player_techs
            WHERE user_id = %s AND branch = %s AND status = 'completed'
        """, (user_id, branch))
        rows = cur.fetchall()

    for row in rows:
        tech_key = row['tech_key']
        completed_level = row['branch_level']
        tech_data = techs_config.get(tech_key)
        if not tech_data:
            continue

        base_effects = tech_data.get('effects', {})
        scaled = scale_effects(base_effects, completed_level)

        # Merge effects
        for key, value in scaled.items():
            if key not in effects:
                effects[key] = value
            elif key.endswith('_mult'):
                effects[key] = effects[key] * value
            elif isinstance(value, (int, float)):
                effects[key] = effects[key] + value
            elif isinstance(value, bool):
                effects[key] = effects[key] or value

    return effects


def _get_tech_image(branch: str, tech_key: str, branch_level: int, tech_data: dict) -> str:
    """Get tech image: check DB for level 2+ generated images, fall back to config."""
    if branch_level > 1:
        from utilities.upgrade_image_utils import get_tech_image_from_db
        db_url = get_tech_image_from_db(branch, tech_key, branch_level)
        if db_url:
            return db_url
    return tech_data.get('image_url', '')


def _has_research_station(user_id: int) -> bool:
    """Check if user has active research_station infrastructure.
    Reads from the per-request memoized infrastructure list instead of a fresh query."""
    from utilities.postgres.shop import get_user_infrastructure
    for b in get_user_infrastructure(user_id):
        if b.get('structure_type') == 'research_station' and b.get('status') == 'active':
            return True
    return False


def _check_tech_available(user_id: int, branch: str, tech_key: str) -> tuple:
    """
    Check if a tech can be researched at current branch level.
    Validates: research station, no active research, tier prerequisites, SV cost.
    Returns (can_start: bool, error: str)
    """
    branch_levels = _get_user_branch_levels(user_id)
    current_level = branch_levels.get(branch, 1)

    tech = _get_tech_config(branch, tech_key, current_level)
    if not tech:
        return False, 'Technology not found'

    if not _has_research_station(user_id):
        return False, 'Research Station required'

    # Check no other research in progress
    active = _get_active_research(user_id)
    if active:
        return False, 'Another research is in progress'

    # Check if already completed at current level
    completed_at_level = _get_completed_techs_at_level(user_id, branch, current_level)
    if tech_key in completed_at_level:
        return False, 'Already researched at this level'

    # Check tier prerequisites (T1 before T2, T2 before T3)
    branch_data = TECH_CATALOG.get(branch, {})
    tech_data = branch_data.get('techs', {}).get(tech_key, {})
    requires = tech_data.get('requires', [])
    for req_tech in requires:
        if req_tech not in completed_at_level:
            req_name = branch_data.get('techs', {}).get(req_tech, {}).get('name', req_tech)
            return False, f'Requires {req_name} first'

    # Check SV cost
    scientist_key = _get_user_scientist_key(user_id)
    bonuses = get_scientist_branch_bonuses(scientist_key) if scientist_key else {}
    branch_bonus = bonuses.get(branch, {})
    cost_mult = branch_bonus.get('cost_mult', 1.0)
    base_cost = tech.get('cost_sv', 4000)
    adjusted_cost = int(base_cost * cost_mult)

    available_sv = _get_available_sv(user_id)
    if available_sv < adjusted_cost:
        return False, f'Need {adjusted_cost} SV (have {available_sv})'

    return True, ''


def _get_user_scientist_key(user_id: int) -> Optional[str]:
    """Get user's scientist_key from DB."""
    with db_cursor() as cur:
        cur.execute("SELECT scientist_key FROM pilgrim.users WHERE id = %s", (user_id,))
        row = cur.fetchone()
    return row['scientist_key'] if row else None


def _get_available_sv(user_id: int) -> int:
    """Get available Scientific Value = discovery SV + passive SV - SV spent on research."""
    with db_cursor() as cur:
        # Total SV from ALL claimed discoveries (SV is permanent scientific knowledge —
        # sharding extracts shards but doesn't erase what you learned)
        cur.execute("""
            SELECT COALESCE(SUM(di.base_scientific_value * COALESCE(ed.quantity, 1)), 0) as total_sv
            FROM pilgrim.expedition_discoveries ed
            JOIN pilgrim.expeditions e ON ed.expedition_id = e.id
            JOIN pilgrim.discovery_items di ON ed.discovery_item_id = di.id
            WHERE e.user_id = %s AND ed.claimed_by_user = true
        """, (user_id,))
        total_sv = int(cur.fetchone()['total_sv'])

        # Add passive SV from scientist (Research Station generation)
        from utilities.postgres.users import get_passive_sv
        total_sv += int(get_passive_sv(user_id))

        # SV already spent on research
        cur.execute("""
            SELECT COALESCE(SUM(sp_cost), 0) as spent
            FROM pilgrim.player_techs
            WHERE user_id = %s AND status IN ('researching', 'completed')
        """, (user_id,))
        spent = int(cur.fetchone()['spent'])

    # SV spent on Narog reforge actions (Bug #1438). Stored on pilgrim.robot
    # so the status bar + reforge gate share one balance. Guarded so a
    # pre-migration row (missing column) doesn't 500 every page load — the
    # column lands on first call into utilities.postgres.robot.
    reforge_spent = 0
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT COALESCE(reforge_sv_spent, 0) as reforge_spent
                FROM pilgrim.robot
                WHERE user_id = %s
            """, (user_id,))
            row = cur.fetchone()
            reforge_spent = int(row['reforge_spent']) if row else 0
    except Exception:
        reforge_spent = 0

    return max(0, total_sv - spent - reforge_spent)


def start_research(user_id: int, branch: str, tech_key: str, session) -> Dict[str, Any]:
    """Start researching a technology. Deducts SV, creates timer."""
    can_start, error = _check_tech_available(user_id, branch, tech_key)
    if not can_start:
        return {'success': False, 'error': error}

    # Get current branch level
    branch_levels = _get_user_branch_levels(user_id)
    current_level = branch_levels.get(branch, 1)

    tech = _get_tech_config(branch, tech_key, current_level)
    scientist_key = _get_user_scientist_key(user_id)
    bonuses = get_scientist_branch_bonuses(scientist_key) if scientist_key else {}
    branch_bonus = bonuses.get(branch, {})

    # Calculate adjusted cost and duration
    cost_mult = branch_bonus.get('cost_mult', 1.0)
    speed_mult = branch_bonus.get('speed_mult', 1.0)
    base_cost = tech.get('cost_sv', 4000)
    base_seconds = tech.get('research_time_seconds', 86400)
    adjusted_cost = int(base_cost * cost_mult)
    # #1492: Narog "research" dial speeds research (≤1.0 = faster). Same factor the
    # tech-status preview applies, so the stored duration matches what was shown.
    from utilities.postgres.robot_dial import get_robot_dial_multipliers
    research_dial_mult = get_robot_dial_multipliers(user_id).get('research_time_mult', 1.0)
    adjusted_duration = int(base_seconds / speed_mult * research_dial_mult)

    # Insert research record with branch_level
    ensure_player_techs_table()
    with db_cursor(commit=True) as cur:
        cur.execute("""
            INSERT INTO pilgrim.player_techs
            (user_id, branch, tech_key, branch_level, status, research_started_at, research_duration_seconds, sp_cost)
            VALUES (%s, %s, %s, %s, 'researching', NOW(), %s, %s)
            ON CONFLICT (user_id, branch, tech_key, branch_level)
            DO UPDATE SET status = 'researching', research_started_at = NOW(),
                          research_duration_seconds = EXCLUDED.research_duration_seconds,
                          sp_cost = EXCLUDED.sp_cost
        """, (user_id, branch, tech_key, current_level, adjusted_duration, adjusted_cost))

    # Invalidate session
    if hasattr(session, 'pop'):
        session.pop('_hyd', None)
    if hasattr(session, 'modified'):
        session.modified = True

    bonus_label = branch_bonus.get('label', '')
    logger.info(f"Research started: user={user_id}, {branch}/{tech_key} @ level {current_level}, cost={adjusted_cost}SV")
    from utilities.postgres.activity import log_activity
    log_activity(user_id, 'research', 'tech_research_start',
                 f"Researching: {tech_key.replace('_', ' ').title()} Lv{current_level}",
                 amount=adjusted_cost, detail=f"{branch} branch",
                 source_table='player_techs', metadata={'branch': branch, 'tech_key': tech_key, 'level': current_level})

    return {
        'success': True,
        'branch': branch,
        'tech_key': tech_key,
        'branch_level': current_level,
        'tech_name': tech['name'],
        'sp_cost': adjusted_cost,
        'research_time_seconds': adjusted_duration,
        'scientist_bonus': bonus_label,
    }


def get_research_progress(user_id: int) -> Optional[Dict]:
    """Get active research progress for countdown display."""
    _auto_complete_research(user_id)
    row = _get_active_research(user_id)
    if not row:
        return None

    started = row['research_started_at']
    duration = row['research_duration_seconds']
    branch_level = row['branch_level']
    now = datetime.now(timezone.utc)
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)

    elapsed = (now - started).total_seconds()
    remaining = max(0, duration - elapsed)
    progress = min(100, (elapsed / duration) * 100) if duration > 0 else 100

    tech = _get_tech_config(row['branch'], row['tech_key'], branch_level)
    return {
        'branch': row['branch'],
        'tech_key': row['tech_key'],
        'branch_level': branch_level,
        'tech_name': tech['name'] if tech else row['tech_key'],
        'started_at': started.isoformat(),
        'duration_seconds': duration,
        'elapsed_seconds': int(elapsed),
        'remaining_seconds': int(remaining),
        'progress_pct': round(progress, 1),
    }


def cancel_research(user_id: int, session) -> Dict[str, Any]:
    """Cancel active research. Refunds SV by deleting the player_techs row."""
    active = _get_active_research(user_id)
    if not active:
        return {'success': False, 'error': 'No active research to cancel'}

    branch_level = active['branch_level']
    with db_cursor(commit=True) as cur:
        cur.execute("""
            DELETE FROM pilgrim.player_techs
            WHERE user_id = %s AND branch = %s AND tech_key = %s
            AND branch_level = %s AND status = 'researching'
        """, (user_id, active['branch'], active['tech_key'], branch_level))

    if hasattr(session, 'pop'):
        session.pop('_hyd', None)
    if hasattr(session, 'modified'):
        session.modified = True

    tech = _get_tech_config(active['branch'], active['tech_key'], branch_level)
    refunded = active.get('sp_cost', 0)
    logger.info(f"Research cancelled: user={user_id}, {active['branch']}/{active['tech_key']}, refunded {refunded} SV")
    return {'success': True, 'refunded_sv': refunded, 'tech_name': tech['name'] if tech else active['tech_key']}


def get_tech_effects(user_id: int) -> Dict[str, Any]:
    from utilities.postgres.core import request_memo
    return request_memo(('get_tech_effects', user_id), lambda: _get_tech_effects_uncached(user_id))


def _get_tech_effects_uncached(user_id: int) -> Dict[str, Any]:
    """
    Calculate cumulative effects from all completed tech research.
    Single query across ALL branches (was N+1 per branch).
    """
    with db_cursor() as cur:
        cur.execute("""
            SELECT branch, tech_key, COALESCE(branch_level, 1) as branch_level
            FROM pilgrim.player_techs
            WHERE user_id = %s AND status = 'completed'
        """, (user_id,))
        rows = cur.fetchall()

    return merge_completed_tech_rows(rows)


def merge_completed_tech_rows(rows) -> Dict[str, Any]:
    """Pure merge of completed-tech rows -> cumulative effect dict.

    Each row is a mapping with keys: branch, tech_key, branch_level.
    Kept pure (no DB) so the merge rule below is unit-testable — see the
    'tech effect merge rule' smoke test in tools/smoke_test/local.py.

    Merge rule (revised by bug #1491, Luke 2026-05-28 — supersedes the distinct-tech
    collapse half of #1413):
      1. Per tech: a tech's HIGHEST completed level subsumes its lower levels (no
         level-on-level compounding — the ×14.44-speed bug #1413 killed and Luke
         endorsed). For _mult that's max(); for additive that's max() too (one tech
         counts once).
      2. Within a branch: DISTINCT techs each contribute — non-cost _mult bonuses ADD
         (solar +20% + thermal +30% + fusion +50% → +100%, at branch level → +105%),
         additive sums. The old flat max() collapsed three distinct power income techs
         to just the single highest (+50%); that was never #1413's intent (#1413 was
         about one tech's own levels, not different techs).
      3. Across branches: non-cost _mult branch totals multiply (unchanged from #1413);
         additive sums.
      Cost _mult keys (none in the tech catalog today) keep min within a tech and ×
         within/across branches — never additive.
    """
    from config_tech import scale_effects

    # Accumulate two ways so ONLY non-cost _mult behavior changes (#1491); everything
    # else (additive, cost _mult, bool) keeps its exact pre-#1491 path so #1443 Part 2's
    # deferred additive rule is untouched.
    #   branch_tech_mult[branch][tech_key] = {key: best non-cost _mult across that tech's levels}
    #   branch_other[branch]               = {key: additive SUM of all rows / cost min / bool or}
    branch_tech_mult: Dict[str, Dict[str, Dict[str, float]]] = {}
    branch_other: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        branch = row['branch']
        tech_data = TECH_CATALOG.get(branch, {}).get('techs', {}).get(row['tech_key'])
        if not tech_data:
            continue
        scaled = scale_effects(tech_data.get('effects', {}), row['branch_level'])
        for key, value in scaled.items():
            if key.endswith('_mult') and 'cost' not in key:
                pt = branch_tech_mult.setdefault(branch, {}).setdefault(row['tech_key'], {})
                pt[key] = value if key not in pt else max(pt[key], value)
            else:
                b = branch_other.setdefault(branch, {})
                if key.endswith('_mult'):                 # cost _mult: lower wins (min over rows)
                    b[key] = value if key not in b else min(b[key], value)
                elif isinstance(value, bool):
                    b[key] = b.get(key, False) or value
                elif isinstance(value, (int, float)):     # additive: sum ALL rows (Part 2 deferred — unchanged)
                    b[key] = b.get(key, 0) + value

    # Within a branch: distinct non-cost _mult techs ADD their bonus onto the additive/cost base.
    branch_totals: Dict[str, Dict[str, Any]] = {}
    for branch in set(branch_tech_mult) | set(branch_other):
        bt = dict(branch_other.get(branch, {}))
        for _tech_key, mults in branch_tech_mult.get(branch, {}).items():
            for key, value in mults.items():
                bt[key] = value if key not in bt else bt[key] + (value - 1.0)
        branch_totals[branch] = bt

    # Across branches: _mult branch totals multiply (#1413 unchanged), additive sums, bool ORs.
    effects: Dict[str, Any] = {}
    for bt in branch_totals.values():
        for key, value in bt.items():
            if key not in effects:
                effects[key] = value
            elif key.endswith('_mult'):
                effects[key] = effects[key] * value
            elif isinstance(value, bool):
                effects[key] = effects[key] or value
            elif isinstance(value, (int, float)):
                effects[key] = effects[key] + value

    return effects


def get_user_tech_status(user_id: int) -> Dict[str, Any]:
    """
    Full tech tree state for a user. Auto-completes expired research first.

    Returns branches with 5 techs each, showing status at current branch level.
    """
    from config_tech import get_tech_name_at_level, get_tech_cost_at_level, get_research_time_at_level, scale_effects

    just_completed = _auto_complete_research(user_id)
    has_station = _has_research_station(user_id)
    available_sv = _get_available_sv(user_id)
    scientist_key = _get_user_scientist_key(user_id)
    bonuses = get_scientist_branch_bonuses(scientist_key) if scientist_key else {}
    branch_levels = _get_user_branch_levels(user_id)
    active = _get_active_research(user_id)
    # #1492: Narog "research" dial speeds tech research. Fetched ONCE here (not per
    # tech) so the previewed research_time_seconds matches what start_research stores.
    from utilities.postgres.robot_dial import get_robot_dial_multipliers
    research_dial_mult = get_robot_dial_multipliers(user_id).get('research_time_mult', 1.0)

    branches = {}
    for branch_key, branch_data in TECH_CATALOG.items():
        current_level = branch_levels.get(branch_key, 1)
        branch_bonus = bonuses.get(branch_key, {})
        cost_mult = branch_bonus.get('cost_mult', 1.0)
        speed_mult = branch_bonus.get('speed_mult', 1.0)
        max_branch_level = branch_data.get('max_branch_level', 10)

        # Get completed techs at current branch level
        completed_at_level = _get_completed_techs_at_level(user_id, branch_key, current_level)

        # Build techs dict (5 techs per branch)
        techs = {}
        for tech_key, tech_data in branch_data.get('techs', {}).items():
            # Determine status
            if tech_key in completed_at_level:
                status = 'completed'
            elif active and active['branch'] == branch_key and active['tech_key'] == tech_key:
                status = 'researching'
            else:
                # Check tier prerequisites
                requires = tech_data.get('requires', [])
                prereqs_met = all(req in completed_at_level for req in requires)
                status = 'available' if prereqs_met else 'locked'

            # Calculate costs at current branch level
            base_cost = tech_data.get('base_cost_sv', 4000)
            scaled_cost = get_tech_cost_at_level(base_cost, current_level)
            base_seconds = get_research_time_at_level(current_level)
            adjusted_cost = int(scaled_cost * cost_mult)
            adjusted_duration = int(base_seconds / speed_mult * research_dial_mult)  # #1492 Narog research dial

            # Scale effects based on branch level
            base_effects = tech_data.get('effects', {})
            scaled_effects = scale_effects(base_effects, current_level)

            tech_status = {
                'tech_key': tech_key,
                'name': get_tech_name_at_level(tech_data['name'], current_level),
                'base_name': tech_data['name'],
                'tier': tech_data.get('tier', 1),
                'description': tech_data['description'],
                'effects': scaled_effects,
                'requires': tech_data.get('requires', []),
                'cost_sv': adjusted_cost,
                'cost_sv_original': scaled_cost,
                'research_time_seconds': adjusted_duration,
                'research_time_original': base_seconds,
                'status': status,
                'image_url': _get_tech_image(branch_key, tech_key, current_level, tech_data),
            }

            if status == 'researching' and active:
                started = active['research_started_at']
                now = datetime.now(timezone.utc)
                if started.tzinfo is None:
                    started = started.replace(tzinfo=timezone.utc)
                elapsed = (now - started).total_seconds()
                remaining = max(0, active['research_duration_seconds'] - elapsed)
                progress = min(100, (elapsed / active['research_duration_seconds']) * 100)
                tech_status['progress_pct'] = round(progress, 1)
                tech_status['remaining_seconds'] = int(remaining)

            techs[tech_key] = tech_status

        # Count progress
        completed_count = len(completed_at_level)
        total_techs = len(branch_data.get('techs', {}))

        branches[branch_key] = {
            'name': branch_data['name'],
            'icon': branch_data['icon'],
            'icon_url': branch_data.get('icon_url', ''),
            'description': branch_data['description'],
            'bonus': branch_bonus,
            'branch_level': current_level,
            'max_branch_level': max_branch_level,
            'techs': techs,
            'completed_count': completed_count,
            'total_techs': total_techs,
        }

    return {
        'has_research_station': has_station,
        'research_points': available_sv,
        'scientist_key': scientist_key,
        'scientist_bonuses': bonuses,
        'branches': branches,
        'active_research': get_research_progress(user_id) if active else None,
        'just_completed': just_completed,
    }


# ---------------------------------------------------------------------------
# Lab Summary Box (bug #1286)
# ---------------------------------------------------------------------------
# Canonical mapping from raw effect key → display metadata. Mirrors the if/elif
# chain previously inlined in research.html so we only own one list of labels.
# Icon keys resolve to UI_ICONS at template render time (we pass just the key).
_EFFECT_DISPLAY = {
    'expedition_speed_mult':    {'icon': 'speed_fast',         'label': 'speed',            'fmt': 'mult'},
    'vehicle_range_mult':       {'icon': 'compass_exploration','label': 'range',            'fmt': 'mult'},
    'discovery_chance_bonus':   {'icon': 'magnifier_discovery','label': 'discovery',        'fmt': 'pct_bonus'},
    'rare_chance_bonus':        {'icon': 'rare_sparkle',       'label': 'rare',             'fmt': 'pct_bonus'},
    'legendary_chance_bonus':   {'icon': 'value_diamond',      'label': 'legendary',        'fmt': 'pct_bonus'},
    'dust_storm_resistance':    {'icon': 'tornado_dust',       'label': 'Dust immune',      'fmt': 'immune'},
    'fuel_cost_mult':           {'icon': 'fuel_pump',          'label': 'fuel cost',        'fmt': 'mult'},
    'cargo_capacity_mult':      {'icon': 'cargo_capacity',     'label': 'cargo',            'fmt': 'mult'},
    'passive_income_mult':      {'icon': 'income_coins',       'label': 'income',           'fmt': 'mult'},
    'night_generation_mult':    {'icon': 'night_moon',         'label': 'night gen',        'fmt': 'mult'},
    'all_generation_mult':      {'icon': 'lightning_power',    'label': 'all generation',   'fmt': 'mult'},
    'discovery_value_mult':     {'icon': 'value_diamond',      'label': 'discovery value',  'fmt': 'mult'},
    'extraction_bonus':         {'icon': 'pickaxe_mining',     'label': 'extraction yield', 'fmt': 'pct_bonus'},
    'rare_value_mult':          {'icon': 'rare_sparkle',       'label': 'rare value',       'fmt': 'mult'},
    'legendary_value_mult':     {'icon': 'value_diamond',      'label': 'legendary value',  'fmt': 'mult'},
}


def _format_effects_for_display(effects: Dict[str, Any]) -> list:
    """
    Turn a stacked effects dict (e.g. {'passive_income_mult': 1.56, ...}) into a
    list of {icon, label, value_display} rows for the summary box template. Keys
    not in _EFFECT_DISPLAY are skipped — if a tech adds a new effect it needs a
    row here AND in research.html's per-tech chain (same source of truth).
    """
    rows = []
    for key, value in effects.items():
        meta = _EFFECT_DISPLAY.get(key)
        if not meta:
            continue

        fmt = meta['fmt']
        if fmt == 'mult':
            # A stacked mult of 1.0 means "no effect" — don't clutter the box.
            if abs(float(value) - 1.0) < 0.001:
                continue
            value_display = f"{float(value):.2f}x {meta['label']}"
        elif fmt == 'pct_bonus':
            # Bug #1243 v3 (2026-05-04): Nx multiplier format per spec.
            if float(value) == 0:
                continue
            value_display = f"{1 + float(value):.2f}x {meta['label']}"
        elif fmt == 'immune':
            # dust_storm_resistance is a float, >=1.0 means full immunity.
            if float(value) < 1.0:
                continue
            value_display = meta['label']
        else:
            continue

        rows.append({
            'key': key,
            'icon': meta['icon'],
            'value_display': value_display,
        })
    return rows


def get_tech_summary(user_id: int, branch_levels: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
    """
    Lab Summary Box data (bug #1286). One DB query → all completed techs across
    every branch, grouped and stacked so the top of /research can show exactly
    what the captain has researched AND the resulting cumulative bonuses.

    If `branch_levels` is provided (e.g. from an already-fetched tech_status),
    the per-branch-level lookup is skipped — saves one DB round-trip on the
    /research page where get_user_tech_status has already computed it.

    Returns:
        {
            'total_completed': int,           # distinct (tech_key) completions across branches
            'total_available': int,           # distinct techs in catalog (across all branches)
            'lifetime_completed': int,        # bug #1424 — every (tech_key, branch_level) row
            'lifetime_total': int,            # bug #1424 — sum across branches of techs × max_branch_level
            'branches_started': int,          # branches with >=1 completion
            'branches_total': int,            # branches in catalog (currently 4)
            'branches': [  # ALL branches in catalog order (started + unstarted)
                {
                    'branch_key', 'name', 'icon', 'icon_url',
                    'branch_level', 'completed_count', 'total_techs',
                    'started': bool,
                    'description': str,       # branch tagline (for unstarted hint)
                    'next_tech': {'name': str, 'description': str} | None,  # next available
                    'techs': [{
                        'tech_key', 'name', 'description', 'completed_level',
                        'effects_display': [{'icon','value_display'}...],   # per-tech effects
                    }...],
                    'bonuses': [{'icon', 'value_display'}...],  # stacked in-branch
                },
                ...
            ],
            'global_bonuses': [{'icon','value_display'}...],  # stacked across ALL branches
        }
    """
    from config_tech import scale_effects, get_tech_name_at_level

    # Single query — no per-branch loop, avoids N+1.
    with db_cursor() as cur:
        cur.execute("""
            SELECT branch, tech_key, COALESCE(branch_level, 1) AS branch_level
            FROM pilgrim.player_techs
            WHERE user_id = %s AND status = 'completed'
            ORDER BY branch, branch_level, tech_key
        """, (user_id,))
        rows = cur.fetchall()

    # Group rows by branch key in memory (may be empty for new captains).
    by_branch: Dict[str, list] = {}
    for row in rows:
        by_branch.setdefault(row['branch'], []).append(row)

    # Bug #1443 Part 1 (Luke 2026-05-12 "Ship part 1"): the Lab summary display
    # MUST mirror _get_tech_effects_uncached's aggregation rules so the chips at
    # the top of /research match what the game actually applies. Pre-fix, _merge
    # multiplied _mult across every (tech_key, branch_level) row — producing
    # 18.57× speed when the game itself was using 1.88×. Game path was corrected
    # in #1413 (max-within-branch for _mult); this brings the display in line.
    #
    # Part 2 (additive _bonus keys still summed per same-tech-level rows in BOTH
    # game and display) is a real game-balance change Luke deferred to a separate
    # bug — do not touch additive rules here.
    def _merge_within(dst: dict, add: dict):
        """Per-tech-card stacking: merge one tech's own multi-level rows for the pill
        display. _mult: max() (min() for cost). Additive int/float: sum. Bool: or.
        The branch + global TOTALS no longer use this — they route through the single
        canonical merge_completed_tech_rows() so the chip can't drift from the game.
        """
        for k, v in add.items():
            if k not in dst:
                dst[k] = v
            elif k.endswith('_mult'):
                dst[k] = max(dst[k], v) if 'cost' not in k else min(dst[k], v)
            elif isinstance(v, (int, float)):
                dst[k] = dst[k] + v
            elif isinstance(v, bool):
                dst[k] = dst[k] or v

    if branch_levels is None:
        branch_levels = _get_user_branch_levels(user_id)
    branches_out = []
    total_available = 0
    # Bug #1424: lifetime totals count every (tech_key, branch_level) completion,
    # so the header reads "X/200" in W1 (10 levels × 5 techs × 4 branches) instead
    # of "X/20" (which only reflected distinct techs at the captain's current tier).
    lifetime_completed = 0
    lifetime_total = 0

    # Iterate ALL branches in TECH_CATALOG order — even unstarted ones get a
    # row so the captain can see what they're missing (Luke's QA pattern: never
    # hide the ladder, always show what's next to chase).
    #
    # NB on counting: pilgrim.player_techs has ONE row per (tech_key, branch_level)
    # so when a branch level rises, every previously-completed tech gets a NEW
    # row at the higher level. The canonical _get_branch_effects merges all of
    # those rows (which is how the income calc compounds the bonus per branch
    # level), so we MUST do the same here for the displayed bonuses to match
    # what the rest of the game actually applies. But the COUNT of "researched
    # techs" must be DISTINCT tech_keys — otherwise a Lv4 vehicles captain sees
    # "18/5 techs" which is nonsense. So: merge all rows for the bonus stack,
    # but dedupe by tech_key for the pill list and the count.
    total_distinct_completed = 0
    for branch_key, branch_data in TECH_CATALOG.items():
        techs_config = branch_data.get('techs', {})
        branch_total_techs = len(techs_config)
        total_available += branch_total_techs
        # Bug #1424: per-branch lifetime denominator = techs × max_branch_level
        # (50 in W1: 5 techs × 10 branch levels).
        branch_max_level = branch_data.get('max_branch_level', 10)
        branch_lifetime_total = branch_total_techs * branch_max_level
        lifetime_total += branch_lifetime_total

        branch_rows = by_branch.get(branch_key, [])
        # Bug #1424: row count = every distinct (tech_key, branch_level) the
        # captain has completed in this branch — that's what the header sums.
        branch_lifetime_completed = len(branch_rows)
        lifetime_completed += branch_lifetime_completed
        completed_keys = {r['tech_key'] for r in branch_rows}

        # Group rows by tech_key so we can both (a) merge per-tech effects across
        # every level for an honest per-pill display, and (b) emit one pill per
        # distinct tech.
        rows_by_tech: Dict[str, list] = {}
        for r in branch_rows:
            rows_by_tech.setdefault(r['tech_key'], []).append(r)

        tech_cards = []
        for tech_key, tech_rows in rows_by_tech.items():
            tech_data = techs_config.get(tech_key)
            if not tech_data:
                continue

            # Bug #1443 Part 1: merge same-tech multi-level rows with the
            # within-branch rule (max-_mult, sum-additive) so per-pill chips
            # and the branch total match what the game applies. global_effects
            # is built AFTER the branch loop using the across-branches rule.
            per_tech_effects: Dict[str, Any] = {}
            highest_level = 1
            for r in tech_rows:
                lvl = r['branch_level']
                highest_level = max(highest_level, lvl)
                scaled = scale_effects(tech_data.get('effects', {}), lvl)
                _merge_within(per_tech_effects, scaled)

            tech_cards.append({
                'tech_key': tech_key,
                # Show the tech at its highest reached level (e.g. "Material Science IV").
                'name': get_tech_name_at_level(tech_data['name'], highest_level),
                'description': tech_data.get('description', ''),
                'highest_level': highest_level,
                'level_count': len(tech_rows),
                # Per-tech effect chips compounded across every branch_level the tech
                # was completed at — so tapping a pill shows the same numbers that
                # contributed to the branch total above.
                'effects_display': _format_effects_for_display(per_tech_effects),
            })

        # Stable display order: by tier from the catalog, then by tech_key.
        tier_order = {tk: td.get('tier', 99) for tk, td in techs_config.items()}
        tech_cards.sort(key=lambda c: (tier_order.get(c['tech_key'], 99), c['tech_key']))

        # "Next up" hint — first uncompleted tech in catalog order. Even for
        # unstarted branches we surface tier 1 as the obvious entry point.
        next_tech = None
        for tk, td in techs_config.items():
            if tk not in completed_keys:
                next_tech = {
                    'tech_key': tk,
                    'name': td['name'],
                    'description': td.get('description', ''),
                    'tier': td.get('tier', 1),
                }
                break

        # Bug #1443 Part 1 + #1491: the branch's displayed total IS the canonical
        # merge over that branch's rows — same function the game (get_tech_effects)
        # uses — so the chip and the game value land on the same number.
        branch_effects = merge_completed_tech_rows(branch_rows)

        branches_out.append({
            'branch_key': branch_key,
            'name': branch_data['name'],
            'icon': branch_data.get('icon', ''),
            'icon_url': branch_data.get('icon_url', ''),
            'description': branch_data.get('description', ''),
            'branch_level': branch_levels.get(branch_key, 1),
            # Distinct techs, not row count — see counting note above.
            'completed_count': len(tech_cards),
            'total_techs': branch_total_techs,
            # Bug #1424: lifetime per-branch progress for the header breakdown.
            'lifetime_completed': branch_lifetime_completed,
            'lifetime_total': branch_lifetime_total,
            'started': len(tech_cards) > 0,
            'next_tech': next_tech,
            'techs': tech_cards,
            'bonuses': _format_effects_for_display(branch_effects),
        })
        total_distinct_completed += len(tech_cards)

    branches_started = sum(1 for b in branches_out if b['started'])

    # Global Lab-summary chips: the canonical merge over ALL completed rows — byte-for-byte
    # the same value get_tech_effects() feeds the game, so chip == breakdown modal == game.
    global_effects = merge_completed_tech_rows(rows)

    return {
        'total_completed': total_distinct_completed,
        'total_available': total_available,
        'lifetime_completed': lifetime_completed,
        'lifetime_total': lifetime_total,
        'branches_started': branches_started,
        'branches_total': len(branches_out),
        'branches': branches_out,
        'global_bonuses': _format_effects_for_display(global_effects),
    }


def get_research_page_data(user_id: int) -> Dict[str, Any]:
    """Single call for /research template rendering."""
    from config import COLONY_SCIENTISTS
    tech_status = get_user_tech_status(user_id)
    scientist_key = tech_status.get('scientist_key')
    scientist = COLONY_SCIENTISTS.get(scientist_key, {}) if scientist_key else {}

    # Find primary and secondary branches for scientist
    primary_branch = None
    for branch, scientists in SCIENTIST_BRANCHES.items():
        if scientist_key in scientists:
            primary_branch = branch
            break
    secondary_branch = SCIENTIST_SECONDARY_BRANCHES.get(scientist_key) if scientist_key else None

    return {
        'tech_status': tech_status,
        'scientist': scientist,
        'scientist_key': scientist_key,
        'primary_branch': primary_branch,
        'secondary_branch': secondary_branch,
        'scientist_bonuses': tech_status.get('scientist_bonuses', {}),
        'has_research_station': tech_status['has_research_station'],
        'research_points': tech_status['research_points'],
        'branches': tech_status['branches'],
        'active_research': tech_status.get('active_research'),
        'just_completed': tech_status.get('just_completed'),
        # Bug #1286 — Lab Summary Box: all completed techs + stacked bonuses.
        # Pass branch_levels derived from tech_status to avoid a duplicate DB
        # round-trip into _get_user_branch_levels.
        'tech_summary': get_tech_summary(
            user_id,
            branch_levels={k: v['branch_level'] for k, v in tech_status['branches'].items()},
        ),
    }
