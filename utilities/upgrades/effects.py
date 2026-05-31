"""Cumulative upgrade effects aggregator.

Merges player_upgrades + infrastructure effects + tech tree + captain
logistics into one flat effects dict used by expedition / build math.
"""

import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


def get_user_upgrade_effects(user_id: int) -> Dict[str, Any]:
    from utilities.postgres.core import request_memo
    return request_memo(('get_user_upgrade_effects', user_id), lambda: _get_user_upgrade_effects_uncached(user_id))


def _get_user_upgrade_effects_uncached(user_id: int) -> Dict[str, Any]:
    """
    Calculate all cumulative effects from user's upgrades AND infrastructure.
    Reads from player_upgrades table + UPGRADE_CATALOG.

    Returns a dict of effect_name -> total_value

    Example output:
    {
        'expedition_speed_mult': 2.0,  # From rover level
        'cargo_slots': 8,              # From rover
        'discovery_chance_bonus': 0.35,  # From scanner
        'rare_chance_bonus': 0.10,
        'life_support_cost_mult': 0.85,
        'fuel_cost_mult': 0.8,  # From water_extractor infrastructure
        ...
    }
    """
    from utilities.upgrades.state import get_all_user_upgrades, get_upgrade_stats

    # Initialize with defaults (unified from both upgrade and shop systems)
    effects = {
        # Vehicle/expedition effects
        'expedition_speed_mult': 1.0,
        'cargo_slots': 0,
        'fuel_cost_mult': 1.0,
        'max_range_km': 0,
        'vehicle_range_mult': 1.0,
        'signal_detection_enabled': False,

        # Discovery effects
        'discovery_chance_bonus': 0.0,
        'rare_chance_bonus': 0.0,
        'legendary_chance_bonus': 0.0,
        'discovery_value_mult': 1.0,
        'bio_discovery_value_mult': 1.0,

        # Expedition cost effects
        'life_support_cost_mult': 1.0,

        # Passive income effects
        'passive_income_mult': 1.0,
        'passive_income_base': 0,

        # Captain stat bonuses
        'stat_exploration_bonus': 0,
        'stat_leadership_bonus': 0,
        'stat_strategy_bonus': 0,
        'stat_logistics_bonus': 0,
        'stat_charisma_bonus': 0,

        # Build speed (lower = faster, like cost mults)
        'build_time_mult': 1.0,

        # Boolean flags
        'dust_storm_immune': False,

        # Storage capacity (discovery limit) - default 300, Storage Bunker adds more
        'storage_capacity': 300,
    }

    # Get all user upgrades from new unified system
    user_upgrades = get_all_user_upgrades(user_id)

    # Apply upgrade effects from UPGRADE_CATALOG
    for category, items in user_upgrades.items():
        # Bug #1442 follow-up (exposed by Part A fix): infrastructure level
        # rows live in pilgrim.player_upgrades with category="infrastructure",
        # so get_all_user_upgrades returns them here alongside vehicles/scanners/
        # etc. The dedicated infra phase below (line 130+) is the canonical source
        # for building effects — processing them here too produced a hidden double-
        # count (1.33 × 1.33 instead of 1.33) once Part A switched the cross-layer
        # rule from max to multiply. Skip them here so the math matches the
        # documented "max(upgrades) × max(infra)" rule.
        if category == 'infrastructure':
            continue
        for item_key, level in items.items():
            if level == 0:
                continue  # Not unlocked

            stats = get_upgrade_stats(category, item_key, level)
            if not stats:
                continue

            # Apply each stat from the level config
            for key, value in stats.items():
                if key in ['name', 'cost', 'image_url', 'build_time_days']:
                    continue  # Skip non-effect fields

                # Map capacity (from Storage Bunker) to storage_capacity
                if key == 'capacity':
                    effects['storage_capacity'] = max(effects.get('storage_capacity', 300), value)
                    continue

                if key not in effects:
                    effects[key] = value
                    continue

                current = effects[key]

                # Multiplicative effects - take the best value
                if key.endswith('_mult'):
                    if 'cost' in key:
                        # Cost mults: lower is better
                        effects[key] = min(current, value)
                    else:
                        # Other mults: higher is better
                        effects[key] = max(current, value)

                # Additive - stack
                elif key.endswith('_bonus') or key.endswith('_base') or key in ['cargo', 'cargo_slots', 'max_range_km']:
                    effects[key] = current + value

                # Boolean flags - OR together
                elif isinstance(value, bool):
                    effects[key] = current or value

    # Map 'cargo' to 'cargo_slots' for backward compat
    if 'cargo' in effects and effects['cargo'] > 0:
        effects['cargo_slots'] = effects.get('cargo_slots', 0) + effects['cargo']

    # Apply infrastructure effects
    try:
        from utilities.infrastructure_utils import get_user_infrastructure_effects
        infra_effects = get_user_infrastructure_effects(user_id)

        for key, value in infra_effects.items():
            if key not in effects:
                effects[key] = value
                continue

            current = effects[key]

            if key.endswith('_mult'):
                if 'cost' in key:
                    effects[key] = current * value  # Stack cost reductions
                else:
                    # Bug #1442 Part A (Luke 2026-05-12 "Option A works for me"):
                    # the breakdown-popup footer documents
                    #     Final = max(upgrades) × max(infra) × tech × bond
                    # but this line was max(max(upgrades), max(infra)) — so when a
                    # _mult key existed in BOTH an upgrade and a building the
                    # infra contribution was silently masked. Tech and bond
                    # already multiplied across layers (lines 169 + later); only
                    # the upgrades→infra hop was broken. Fix aligns code with the
                    # documented intent. Game-balance: BUFF for any captain with
                    # both an upgrade and a building hitting the same key (Luke's
                    # screenshot example: Discovery Value 1.4× → 1.694×).
                    effects[key] = current * value
            elif key.endswith('_bonus'):
                effects[key] = current + value
            elif isinstance(value, bool):
                effects[key] = current or value

    except ImportError:
        pass

    # Apply tech tree effects (research bonuses)
    try:
        from utilities.tech_utils import get_tech_effects
        tech_effects = get_tech_effects(user_id)

        for key, value in tech_effects.items():
            if key not in effects:
                effects[key] = value
                continue

            current = effects[key]
            if key.endswith('_mult'):
                if 'cost' in key:
                    effects[key] = current * value
                else:
                    effects[key] = current * value
            elif key.endswith('_bonus') or key.endswith('_base') or key in ['cargo_slots']:
                effects[key] = current + value
            elif isinstance(value, bool):
                effects[key] = current or value
    except ImportError:
        pass

    # Captain Logistics stat → build speed bonus
    try:
        from utilities.postgres.assets import get_commander_stats
        stats = get_commander_stats(user_id)
        if stats:
            logistics = stats.get('logistics', 0) or 0
            # Logistics 0 = no bonus, 50 = 10% faster, 100 = 20% faster
            logistics_build_mult = max(0.5, 1.0 - logistics / 500.0)
            effects['build_time_mult'] = effects.get('build_time_mult', 1.0) * logistics_build_mult
    except Exception:
        pass

    # Scientist Engineering stat → build speed bonus (stacks with Logistics)
    # Per bug #1270 section 4 (Luke 2026-04-12): use Scientist ENG as a passive build-speed lever.
    # Direct lookup — avoids get_user_scientist()'s ensure_scientist_column() DDL round-trip on every effects read.
    try:
        from config import COLONY_SCIENTISTS
        from utilities.postgres.core import db_cursor
        with db_cursor() as cur:
            cur.execute("SELECT scientist_key FROM pilgrim.users WHERE id = %s", (user_id,))
            row = cur.fetchone()
        key = row.get('scientist_key') if row else None
        if key and key in COLONY_SCIENTISTS:
            engineering = COLONY_SCIENTISTS[key].get('stats', {}).get('engineering', 0) or 0
            # ENG 0 = no bonus, 50 = 10% faster, 100 = 20% faster (floor 50%, matches Logistics shape)
            eng_build_mult = max(0.5, 1.0 - engineering / 500.0)
            effects['build_time_mult'] = effects.get('build_time_mult', 1.0) * eng_build_mult
    except Exception:
        pass

    # Phase 4b (#1270 section 4 point 3): Maintenance Drone passive build-speed bonus.
    # Goes outside the upgrade aggregator above because that block uses max() for non-cost
    # _mult keys, which is wrong for build_time_mult (lower is faster). Multiplies
    # into the chain — stacks with Logistics × ENG.
    try:
        from utilities.upgrades_utils import get_user_upgrade_level
        from config_upgrades import UPGRADE_CATALOG
        maint_lv = get_user_upgrade_level(user_id, 'maintenance', 'maintenance')
        if maint_lv >= 1:
            cfg = UPGRADE_CATALOG.get('maintenance', {}).get('maintenance', {}).get('levels', {}).get(maint_lv, {})
            m = cfg.get('build_time_mult', 1.0) or 1.0
            if m != 1.0:
                effects['build_time_mult'] = effects.get('build_time_mult', 1.0) * m
    except Exception:
        pass

    # Bug #1402: ARIA Fragment Bond bonuses. Captain picks up to 3 unique +5% bonuses
    # across A–F (SV, expedition speed, build speed, shards, vehicle range, discovery).
    # SV and shards mults are NOT applied here — they live in income.py against the
    # accumulated income calc. Discovery is additive; the rest are multiplicative.
    try:
        from utilities.aria.bond_bonuses import get_user_bond_effects
        bond_eff = get_user_bond_effects(user_id)
        for key, value in bond_eff.items():
            if key in ('sv_mult', 'shards_mult'):
                # Income-side multipliers — surfaced in effects dict for callers that want them,
                # but income.py reads them directly from get_user_bond_effects to avoid coupling.
                effects[key] = effects.get(key, 1.0) * value
            elif key == 'discovery_chance_bonus':
                effects[key] = effects.get(key, 0.0) + value
            elif key == 'build_time_mult':
                effects[key] = effects.get(key, 1.0) * value  # lower = faster
            elif key.endswith('_mult'):
                effects[key] = effects.get(key, 1.0) * value
    except Exception as e:
        logger.warning(f"bond effect aggregation failed user={user_id}: {e}")

    # #1492: Narog "logistics" dial → live Depot/equipment build-speed bonus.
    # Stacks with Logistics stat × Scientist ENG × Maintenance Drone × ARIA bond
    # (independent lever, per Luke robot-crew §5). Identity 1.0 unless a COMPLETE
    # Narog has logistics allocated, so it's safe to multiply unconditionally.
    # NEW builds pick this up here; in-progress builds are rescaled on dial change
    # by recompute_in_progress_for_dial() (robot_dial.py).
    try:
        from utilities.postgres.robot_dial import get_robot_dial_multipliers
        dial_mult = get_robot_dial_multipliers(user_id).get('build_time_mult', 1.0)
        if dial_mult != 1.0:
            effects['build_time_mult'] = effects.get('build_time_mult', 1.0) * dial_mult
    except Exception:
        pass

    return effects
