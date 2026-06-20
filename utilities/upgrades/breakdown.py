"""Per-source contribution breakdown for the Active Bonus chips on /expeditions.

Mirrors `get_user_upgrade_effects` (effects.py) but emits one row per source
(upgrade level / building level / completed tech / bond pick) instead of merging
into a flat dict. The UI uses this to show captains exactly where each +N% came
from when they click a bonus chip.

Effect keys surfaced (must match the chips in templates/expeditions.html):
    expedition_speed_mult, vehicle_range_mult, expedition_range_mult,
    discovery_chance_bonus, rare_chance_bonus, legendary_chance_bonus,
    discovery_value_mult, bio_discovery_value_mult,
    fuel_cost_mult, life_support_cost_mult,
    cargo_slots, signal_detection_enabled, dust_storm_immune
"""

import logging
from typing import Dict, List, Any

logger = logging.getLogger(__name__)


# Effect keys we expose to the chips. Each entry: (display label, op tag).
# op tag drives the merge-rule blurb shown in the modal footer:
#   'max_then_mult' — within upgrade/infra/tech-branch use max(), then × across layers
#   'mult'          — every contribution multiplies (cost reductions stack)
#   'add'           — every contribution adds
#   'or'            — boolean OR
SURFACED_KEYS = {
    'expedition_speed_mult':   ('Speed',                   'max_then_mult'),
    'vehicle_range_mult':      ('Vehicle Range',           'max_then_mult'),
    'expedition_range_mult':   ('Launch Pad Range',        'max_then_mult'),
    'discovery_chance_bonus':  ('Discovery (Common)',      'add'),
    'rare_chance_bonus':       ('Rare Discovery',          'add'),
    'legendary_chance_bonus':  ('Legendary Chance',        'add'),
    'discovery_value_mult':    ('Discovery Value',         'max_then_mult'),
    'bio_discovery_value_mult':('Bio Discovery Value',     'max_then_mult'),
    'fuel_cost_mult':          ('Fuel Cost',               'mult'),
    'life_support_cost_mult':  ('Life Support Cost',       'mult'),
    'cargo_slots':             ('Cargo Slots',             'add'),
    'signal_detection_enabled':('Signal Detection',        'or'),
    'dust_storm_immune':       ('Dust Storm Immune',       'or'),
    # Bug #1461 (Luke 2026-05-12): Lab summary chips include these keys too,
    # so the breakdown popup needs to surface them or clicks on those chips
    # would render "no contributions tracked". Op tags match the aggregator's
    # actual rules in utilities/upgrades/effects.py + tech_utils.py.
    'cargo_capacity_mult':     ('Cargo Capacity',          'max_then_mult'),
    'passive_income_mult':     ('Passive Income',          'max_then_mult'),
    'night_generation_mult':   ('Night Generation',        'max_then_mult'),
    'all_generation_mult':     ('All Generation',          'max_then_mult'),
    'extraction_bonus':        ('Extraction Yield',        'add'),
    'rare_value_mult':         ('Rare Discovery Value',    'max_then_mult'),
    'legendary_value_mult':    ('Legendary Discovery Value','max_then_mult'),
    # Bug #1507 (Luke): the Depot "Build Time" breakout chip opens this popup.
    # 'mult' op — every lever stacks ×, lower = faster (same rule as cost mults).
    # Rows come from effects.build_time_levers (walk 5 below), not a catalog
    # re-walk, so they multiply to the served build_time_mult exactly.
    'build_time_mult':         ('Build Time',              'mult'),
}


def _row(layer: str, source: str, key: str, value: Any) -> Dict[str, Any]:
    return {'layer': layer, 'source': source, 'key': key, 'value': value}


def get_user_effect_breakdown(user_id: int) -> Dict[str, List[Dict[str, Any]]]:
    """Return {effect_key: [contribution rows]} for the chip-surfaced keys.

    Each row has:
      layer:  'upgrade' | 'infra' | 'tech' | 'bond'
      source: human label (e.g. 'Olympus Buggy Lv5', 'Comms Array Lv3', 'Tech: Aerobraking Lv2')
      value:  raw contribution value as it would feed into the merge
    """
    out: Dict[str, List[Dict[str, Any]]] = {k: [] for k in SURFACED_KEYS}

    # 1) Player upgrades — UPGRADE_CATALOG levels
    try:
        from utilities.upgrades.state import get_all_user_upgrades, get_upgrade_stats
        for category, items in get_all_user_upgrades(user_id).items():
            # Bug #1442 Part B (Luke 2026-05-12): infrastructure level upgrades
            # are tracked in pilgrim.player_upgrades with category="infrastructure",
            # so get_all_user_upgrades returns them alongside vehicles/scanners/etc.
            # Emitting them here AND in step 2's infra walker double-listed every
            # leveled building under both "Player Upgrades" and "Infrastructure"
            # (e.g. Sepolia Studies Institute appeared twice at ×1.4 on Luke's
            # screenshot). The infra walker is the canonical source for buildings
            # — skip them here so the popup shows distinct sources.
            if category == 'infrastructure':
                continue
            for item_key, level in items.items():
                if not level:
                    continue
                stats = get_upgrade_stats(category, item_key, level) or {}
                name = stats.get('name') or f"{category}/{item_key}"
                source = f"{name} (Lv {level})"
                for k in SURFACED_KEYS:
                    if k == 'build_time_mult':
                        continue  # #1507: owned solely by walk 5 (build_time_levers)
                    if k in stats:
                        out[k].append(_row('upgrade', source, k, stats[k]))
                # 'cargo' is the legacy alias for cargo_slots
                if 'cargo' in stats and stats['cargo']:
                    out['cargo_slots'].append(_row('upgrade', source, 'cargo_slots', stats['cargo']))
    except Exception as e:
        logger.warning(f"breakdown upgrade walk failed user={user_id}: {e}")

    # 2) Infrastructure — INFRASTRUCTURE_CATALOG active buildings
    # Mirror the field-rename mapping in utilities/infrastructure/effects.py
    try:
        from config_infrastructure import INFRASTRUCTURE_CATALOG
        from utilities.postgres.shop import get_user_infrastructure
        from utilities.upgrades_utils import get_all_infrastructure_levels

        structures = get_user_infrastructure(user_id)
        active_types = {s['structure_type'] for s in structures if s['status'] == 'active'}
        levels = get_all_infrastructure_levels(user_id, structures=structures)

        for btype in active_types:
            level = levels.get(btype, 1) or 1
            catalog = INFRASTRUCTURE_CATALOG.get(btype, {})
            ldata = catalog.get('levels', {}).get(level, {}) or {}
            label = ldata.get('name') or catalog.get('name') or btype
            source = f"{label} (Lv {level})"

            for raw_key, value in ldata.items():
                if raw_key in ('name', 'cost', 'build_time_days', 'image_url',
                               'generation_rate', 'science_generation_rate'):
                    continue
                # Field-rename map (must mirror infrastructure/effects.py:49-77)
                if raw_key == 'fuel_cost_reduction':
                    out['fuel_cost_mult'].append(_row('infra', source, 'fuel_cost_mult', 1.0 - value))
                elif raw_key == 'life_support_reduction':
                    out['life_support_cost_mult'].append(_row('infra', source, 'life_support_cost_mult', 1.0 - value))
                elif raw_key == 'discovery_bonus':
                    out['discovery_chance_bonus'].append(_row('infra', source, 'discovery_chance_bonus', value))
                elif raw_key == 'night_generation':
                    # Bug #1461 — infra catalog field renames to night_generation_mult
                    # via infrastructure/effects.py:57-58. Mirror it here so the popup
                    # row aligns with the chip the captain clicked.
                    out['night_generation_mult'].append(_row('infra', source, 'night_generation_mult', value))
                elif raw_key == 'discovery_value_mult':
                    out['discovery_value_mult'].append(_row('infra', source, 'discovery_value_mult', value))
                elif raw_key == 'bio_value_mult':
                    out['bio_discovery_value_mult'].append(_row('infra', source, 'bio_discovery_value_mult', value))
                elif raw_key == 'legendary_discovery_chance':
                    out['legendary_chance_bonus'].append(_row('infra', source, 'legendary_chance_bonus', value))
                elif raw_key == 'dust_storm_immune':
                    out['dust_storm_immune'].append(_row('infra', source, 'dust_storm_immune', value))
                elif raw_key in SURFACED_KEYS and raw_key != 'build_time_mult':
                    # passthrough (vehicle_range_mult, expedition_speed_mult, expedition_range_mult,
                    # signal_detection_enabled, rare_chance_bonus, cargo_slots if any)
                    out[raw_key].append(_row('infra', source, raw_key, value))
    except Exception as e:
        logger.warning(f"breakdown infra walk failed user={user_id}: {e}")

    # 3) Tech tree — completed techs grouped by branch
    # The live aggregator does max() within branch, then × across branches for _mult,
    # additive for _bonus. We emit per-tech rows tagged with branch so the modal can
    # explain that grouping; the merge rule blurb tells the captain what happens.
    try:
        from utilities.postgres.core import db_cursor
        from utilities.tech_utils import TECH_CATALOG
        from config_tech import scale_effects
        with db_cursor() as cur:
            cur.execute("""
                SELECT branch, tech_key, COALESCE(branch_level, 1) AS branch_level
                FROM pilgrim.player_techs
                WHERE user_id = %s AND status = 'completed'
            """, (user_id,))
            rows = cur.fetchall()
        # #1491: for non-cost _mult keys, collapse each tech to its HIGHEST level (one row
        # per distinct tech) so the popup rows sum to the +N% headline — matching the
        # game's "per-tech max, then distinct techs ADD" rule. Pre-fix the modal listed
        # Solar Optimization at branch Lv1 AND Lv2, which don't sum to the total (the
        # #1482 "rows don't match the headline" complaint, in a different chip).
        # Additive keys keep one row PER LEVEL (game sums them per-level — #1443 Part 2,
        # deferred), so their rows still reconcile too.
        rows_by_tech = {}
        for r in rows:
            rows_by_tech.setdefault((r['branch'], r['tech_key']), []).append(r)
        for (branch, tech_key), trows in rows_by_tech.items():
            tech = TECH_CATALOG.get(branch, {}).get('techs', {}).get(tech_key) or {}
            tech_name = tech.get('name') or tech_key
            top = max(trows, key=lambda r: r['branch_level'])
            for r in trows:
                scaled = scale_effects(tech.get('effects', {}), r['branch_level'])
                for k, v in scaled.items():
                    if k not in SURFACED_KEYS or k == 'build_time_mult':
                        continue  # #1507: build_time_mult owned solely by walk 5
                    if k.endswith('_mult') and 'cost' not in k:
                        # one row per tech at its best level (max value across its levels)
                        if r is not top:
                            continue
                        v = max(scale_effects(tech.get('effects', {}), rr['branch_level']).get(k, v) for rr in trows)
                        source = f"Tech: {tech_name} (branch Lv {top['branch_level']})"
                    else:
                        source = f"Tech: {tech_name} (branch Lv {r['branch_level']})"
                    out[k].append(_row('tech', source, k, v))
    except Exception as e:
        logger.warning(f"breakdown tech walk failed user={user_id}: {e}")

    # 4) ARIA Fragment Bond picks
    try:
        from utilities.aria.bond_bonuses import get_user_bond_bonuses, BOND_BONUSES
        for bond_id, code in get_user_bond_bonuses(user_id).items():
            spec = BOND_BONUSES.get(code) or {}
            ek = spec.get('effect_key')
            ev = spec.get('effect_value')
            if ek in SURFACED_KEYS and ek != 'build_time_mult' and ev is not None:
                source = f"ARIA Bond {code}: {spec.get('name', code)}"
                out[ek].append(_row('bond', source, ek, ev))
    except Exception as e:
        logger.warning(f"breakdown bond walk failed user={user_id}: {e}")

    # #20: cross-category synergy bonuses, filed under the chip they affect
    # (Pathfinder → Speed, Yield → Passive Income).
    try:
        from config_upgrades import evaluate_synergies
        from utilities.upgrades.state import get_all_user_upgrades
        for s in evaluate_synergies(get_all_user_upgrades(user_id)):
            dk = s['display_key']
            if s['tiers'] > 0 and dk in SURFACED_KEYS:
                out[dk].append(_row('synergy', f"{s['name']} (tier {s['tiers']})", dk, s['mult']))
    except Exception as e:
        logger.warning(f"breakdown synergy walk failed user={user_id}: {e}")

    # 5) #1507 Build Time levers — reuse the aggregator's single source of truth
    # (effects.build_time_levers) so the Depot breakout rows multiply to the
    # served build_time_mult exactly. Layers: captain / crew / upgrade / bond / narog.
    try:
        from utilities.upgrades.effects import build_time_levers
        for layer, source, mult in build_time_levers(user_id):
            out['build_time_mult'].append(_row(layer, source, 'build_time_mult', mult))
    except Exception as e:
        logger.warning(f"breakdown build_time walk failed user={user_id}: {e}")

    return out
