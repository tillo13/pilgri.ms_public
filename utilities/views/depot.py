"""Depot page + claimed discoveries view data."""

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def get_depot_page_data(user_id, auth):
    """Get all data needed for colony/depot page."""
    from utilities.depot_utils import get_fast_balance_and_wallet_info, get_commander_and_stats, get_pricing_info, OPERATIONS_FEE_BUFFER_DISPLAY
    from utilities.postgres.assets import get_user_replicate_assets

    total_balance, wallet_info, _ = get_fast_balance_and_wallet_info(user_id)  # FAST: no blockchain
    images = get_user_replicate_assets(user_id, asset_type='character_image', limit=1)

    # PREFETCH: get_user_infrastructure is UPDATE+commit+SELECT — call ONCE, pass through everywhere.
    from utilities.postgres.shop import get_user_infrastructure as _get_user_infra
    user_structures = _get_user_infra(user_id)

    # Get shop catalog with availability info (excluding items now in UPGRADE_CATALOG)
    # ALL shop items have been migrated to the unified 10-level upgrade system
    MIGRATED_TO_UPGRADES = {
        # Vehicles (now in UPGRADE_CATALOG as rover/drone/buggy paths)
        'rover_basic', 'rover_enhanced', 'rover_advanced', 'rover_elite',
        # Equipment (now scanner/life_support/cargo paths)
        'scanner_basic', 'scanner_deep', 'scanner_quantum',
        'life_support_basic', 'life_support_advanced',
        'cargo_bay', 'cargo_refrigerated',
        # Power (now generator path)
        'solar_tier2', 'solar_tier3', 'nuclear_rtg', 'fusion_reactor',
        # Research (now research path)
        'research_lab', 'research_advanced',
        # Gear (now suit path)
        'suit_exploration', 'suit_command', 'suit_logistics',
        # Automation (now automation path)
        'mining_drone', 'maintenance_drone',
    }
    # =========================================================================
    # DEPRECATED: Legacy shop_catalog disabled - all items now in upgrade_catalog
    # Existing player purchases still work via get_user_upgrade_effects()
    # =========================================================================
    shop_catalog = {}

    # Get upgrade catalog (vehicles, equipment, storage, etc.)
    try:
        from utilities.upgrades.catalog import get_upgrade_catalog_for_user
        upgrade_catalog = get_upgrade_catalog_for_user(user_id, _prefetch_structures=user_structures, _prefetch_balance=total_balance)
    except ImportError:
        upgrade_catalog = {}

    # Get captain stats for display
    commander, stats = get_commander_and_stats(user_id)

    # Get upgrade cap info and active builds for UI (reuse prefetched infra_levels for cap)
    try:
        from utilities.upgrades_utils import count_concurrent_upgrades, get_user_upgrade_cap, get_active_builds
        from utilities.upgrades.catalog import get_all_infrastructure_levels
        _infra_levels = get_all_infrastructure_levels(user_id, structures=user_structures)
        concurrent_upgrades = count_concurrent_upgrades(user_id)
        upgrade_cap = get_user_upgrade_cap(user_id, _prefetch_infra_levels=_infra_levels)
        active_builds = get_active_builds(user_id)  # NEW system (player_upgrades)
    except ImportError:
        concurrent_upgrades = 0
        upgrade_cap = 3
        active_builds = []

    # Add infrastructure builds to active_builds (reuse prefetched user_structures)
    from utilities.infrastructure_utils import INFRASTRUCTURE_CATALOG
    for infra in user_structures:
        if infra.get('status') == 'building' and infra.get('ready_at'):
            ready_at = infra['ready_at']
            if hasattr(ready_at, 'tzinfo') and ready_at.tzinfo is None:
                ready_at = ready_at.replace(tzinfo=timezone.utc)
            secs = max(0, int((ready_at - datetime.now(timezone.utc)).total_seconds()))
            cat = INFRASTRUCTURE_CATALOG.get(infra['structure_type'], {})
            active_builds.append({
                'name': cat.get('name', infra['structure_type'].replace('_', ' ').title()),
                'category': 'infrastructure',
                'item_key': infra['structure_type'],
                'target_level': infra.get('level', 1),
                'seconds_remaining': secs,
                'ready_at_str': infra['ready_at'].strftime('%b %d, %Y at %I:%M %p'),
            })
    # Sort all builds by seconds remaining (soonest first)
    active_builds.sort(key=lambda b: b['seconds_remaining'])

    # Bug #1270 Phase 4: surface Shard Rush eligibility + cost on each active build.
    # Compute rush_pct ONCE from infrastructure levels (avoid N+1 per build).
    try:
        from utilities.upgrades.shard_rush import (
            calculate_rush_cost_pct, _upgrade_base_cost, _infrastructure_base_cost,
            RUSH_THRESHOLD_HOURS,
        )
        rush_pct = calculate_rush_cost_pct(user_id)
        for b in active_builds:
            remaining_hours = b.get('seconds_remaining', 0) / 3600.0
            if remaining_hours <= 0 or remaining_hours >= RUSH_THRESHOLD_HOURS:
                b['rush_eligible'] = False
                b['rush_cost'] = 0
                b['rush_pct'] = rush_pct
                continue
            # Bug #1427: infrastructure upgrades Lv2+ live in INFRASTRUCTURE_CATALOG, NOT
            # UPGRADE_CATALOG. The previous condition only routed Lv1 builds to the right
            # catalog; everything else (including Xeno Lab Lv3→Lv4) silently returned cost=0
            # → rush_eligible=False → no button. Now ALL infrastructure rows use the
            # infrastructure catalog regardless of target level.
            if b.get('category') == 'infrastructure':
                base_cost = _infrastructure_base_cost(b['item_key'], b.get('target_level', 1))
            else:
                base_cost = _upgrade_base_cost(b['category'], b['item_key'], b.get('target_level', 1))
            b['rush_eligible'] = base_cost > 0
            b['rush_cost'] = int(round(base_cost * rush_pct))
            b['rush_pct'] = rush_pct
    except Exception as e:
        logger.warning(f"Shard rush enrichment failed: {e}")

    # Discovery-based range multiplier (for vehicle effective range display)
    from utilities.postgres.expeditions import get_user_discovered_landmarks
    discovered = get_user_discovered_landmarks(user_id)
    depot_discovery_count = len(discovered) if discovered else 0
    depot_fog_radius = min(1000, 300 + depot_discovery_count * 50)
    depot_range_mult = round(depot_fog_radius / 300.0, 2)

    # Build speed bonus from Logistics stat + upgrades
    try:
        from utilities.upgrades_utils import get_user_upgrade_effects
        build_time_mult = get_user_upgrade_effects(user_id).get('build_time_mult', 1.0)
    except Exception:
        build_time_mult = 1.0

    # Bug #1397: recent build completions for the depot landing modal. 24h
    # window (not 7d) — Luke reported a week-old build showing up because
    # historical upgraded_at values predate the build-complete fix and sort
    # arbitrarily. WYWA briefing still uses its own 7d window.
    from datetime import timedelta
    from utilities.build_completions import get_recent_build_completions
    recent_completions = get_recent_build_completions(
        user_id,
        since_dt=datetime.now(timezone.utc) - timedelta(hours=24),
        limit=5,
    )

    return {
        'user': auth.get_current_user(), 'current_balance': total_balance, 'wallet_info': wallet_info,
        'pricing': get_pricing_info(user_id), 'has_commander': len(images) > 0,
        'commander': images[0] if images else None,
        'stats': stats,
        'shop_catalog': shop_catalog,
        'upgrade_catalog': upgrade_catalog,
        'building_items': [],
        'operations_fee': OPERATIONS_FEE_BUFFER_DISPLAY,
        'concurrent_upgrades': concurrent_upgrades,
        'upgrade_cap': upgrade_cap,
        'active_builds': active_builds,
        'discovery_count': depot_discovery_count,
        'range_mult': depot_range_mult,
        'build_time_mult': round(build_time_mult, 3),
        'recent_completions': recent_completions,
    }


def get_claimed_discoveries_data(user_id):
    """Get claimed discoveries with aggregated stats, plus ARIA bonds."""
    from utilities.postgres.expeditions import get_claimed_discoveries

    raw_discoveries = get_claimed_discoveries(user_id)

    # Normalize numeric fields to avoid Decimal serialization issues
    discoveries = []
    for d in raw_discoveries:
        normalized = dict(d)
        normalized['enhanced_value'] = float(d.get('enhanced_value') or 0)
        normalized['weight_kg'] = float(d.get('weight_kg') or 0)
        normalized['quantity'] = int(d.get('quantity') or 1)
        normalized['found_at_km'] = float(d.get('found_at_km') or 0)
        normalized['base_scientific_value'] = int(d.get('base_scientific_value') or 0)
        discoveries.append(normalized)

    # Get ARIA bonds for this user (special artifacts from shared discoveries)
    aria_bonds = []
    try:
        from utilities.aria.bonds import get_user_bonds, _get_commander_name
        bonds = get_user_bonds(user_id)
        for b in bonds:
            if b['status'] == 'bonded':  # Only show completed bonds
                # Determine partner
                partner_id = b['user_id_2'] if b['user_id_1'] == user_id else b['user_id_1']
                partner_name = _get_commander_name(partner_id) or f"Captain {partner_id}"
                my_name = _get_commander_name(user_id) or f"Captain {user_id}"
                sol = int(b['bonded_at'].timestamp() / 86400) if b.get('bonded_at') else '?'

                aria_bonds.append({
                    'id': b['id'],
                    'landmark': b['landmark_name'],
                    'partner_name': partner_name,
                    'my_name': my_name,
                    'sol': sol,
                    'image_url': b.get('bond_image_url'),
                    'bond_tx': b.get('bond_tx_hash'),
                    'bonded_at': b['bonded_at'].isoformat() if b.get('bonded_at') else None
                })
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Could not load ARIA bonds: {e}")

    from utilities.tech_utils import _get_available_sv
    available_sv = _get_available_sv(user_id)

    # Include equipment bonuses so frontend can show accurate extraction previews
    try:
        from utilities.upgrades_utils import get_user_upgrade_effects
        effects = get_user_upgrade_effects(user_id)
        discovery_value_mult = effects.get('discovery_value_mult', 1.0)
        bio_discovery_value_mult = effects.get('bio_discovery_value_mult', 1.0)
    except Exception:
        discovery_value_mult = 1.0
        bio_discovery_value_mult = 1.0

    return {
        'success': True, 'discoveries': discoveries, 'total_count': len(discoveries),
        'total_scientific_value': available_sv,
        'total_weight_kg': sum(d['weight_kg'] * d['quantity'] for d in discoveries),
        'by_rarity': {r: len([d for d in discoveries if d['rarity'] == r]) for r in ['legendary', 'rare', 'uncommon', 'common']},
        'aria_bonds': aria_bonds,
        'discovery_value_mult': discovery_value_mult,
        'bio_discovery_value_mult': bio_discovery_value_mult
    }
