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
from utilities.postgres_utils import db_cursor

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
    """Get current researching tech, if any."""
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
            from utilities.postgres_utils import get_user_primary_sepolia_wallet
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
                with db_cursor(commit=True) as cur2:
                    cur2.execute("""
                        UPDATE pilgrim.player_techs SET tx_hash = %s
                        WHERE user_id = %s AND branch = %s AND tech_key = %s AND branch_level = %s
                    """, (result['tx_hash'], user_id, row['branch'], row['tech_key'], branch_level))
        except Exception as e:
            logger.error(f"Tech blockchain tx failed: {e}")

    thread = threading.Thread(target=do_blockchain, daemon=True)
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
                daemon=True
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
    """Get list of tech_keys completed at a specific branch level."""
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
    """Check if user has active research_station infrastructure."""
    with db_cursor() as cur:
        cur.execute("""
            SELECT id FROM pilgrim.colony_infrastructure
            WHERE user_id = %s AND structure_type = 'research_station' AND status = 'active'
        """, (user_id,))
        return cur.fetchone() is not None


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
        from utilities.postgres_utils import get_passive_sv
        total_sv += int(get_passive_sv(user_id))

        # SV already spent on research
        cur.execute("""
            SELECT COALESCE(SUM(sp_cost), 0) as spent
            FROM pilgrim.player_techs
            WHERE user_id = %s AND status IN ('researching', 'completed')
        """, (user_id,))
        spent = int(cur.fetchone()['spent'])

    return max(0, total_sv - spent)


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
    adjusted_duration = int(base_seconds / speed_mult)

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
    from utilities.db_activity import log_activity
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
    """
    Calculate cumulative effects from all completed tech research.
    Called by get_user_upgrade_effects() to merge into the pipeline.

    Aggregates effects from all branches, scaling by the branch_level
    each tech was completed at.
    """
    effects = {}

    for branch in TECH_CATALOG.keys():
        branch_effects = _get_branch_effects(user_id, branch)
        for key, value in branch_effects.items():
            if key not in effects:
                effects[key] = value
            elif key.endswith('_mult'):
                effects[key] = effects[key] * value
            elif isinstance(value, (int, float)):
                effects[key] = effects[key] + value
            elif isinstance(value, bool):
                effects[key] = effects[key] or value

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
            adjusted_duration = int(base_seconds / speed_mult)

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
    }
