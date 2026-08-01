"""
Expedition Speedrun / Replay Tool

Replays an expedition's discovery generation using CURRENT code, producing a full
report of what SHOULD have been found. Can run in dry-run mode (no DB changes)
or apply mode (replaces old discoveries with new ones).

Usage:
    # Dry run — see what expedition #159 would generate now
    python -m utilities.speedrun_expedition --expedition 159

    # Dry run for multiple expeditions
    python -m utilities.speedrun_expedition --expedition 159 170 172

    # Dry run for a user's ALL in-flight/complete expeditions
    python -m utilities.speedrun_expedition --user 112

    # Apply — actually replace discoveries in DB (requires --apply flag)
    python -m utilities.speedrun_expedition --expedition 159 --apply

    # Custom parameters (test any hypothetical trip)
    python -m utilities.speedrun_expedition --custom --distance 3500 --vehicle buggy --user 112

Output: JSON report saved to tools/speedrun_results/<expedition_id>_<timestamp>.json
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utilities.postgres.core import db_cursor
from utilities.discovery_utils import generate_expedition_discoveries
from utilities.postgres.expeditions import get_discovery_items_catalog, create_expedition_discoveries
from utilities.postgres.map import get_nearest_mars_landmarks

logger = logging.getLogger(__name__)

RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools', 'speedrun_results')


def load_expedition_context(expedition_id: int) -> dict:
    """Load all context needed to replay an expedition from DB."""
    with db_cursor() as cur:
        cur.execute("SELECT * FROM pilgrim.expeditions WHERE id = %s", (expedition_id,))
        exp = cur.fetchone()
        if not exp:
            raise ValueError(f"Expedition #{expedition_id} not found")

        user_id = exp['user_id']

        # User base coords
        cur.execute("SELECT home_mars_lat, home_mars_lon FROM pilgrim.users WHERE id = %s", (user_id,))
        user = cur.fetchone()
        base_lat = float(user['home_mars_lat'])
        base_lon = float(user['home_mars_lon'])

        # Scientist stats
        from utilities.postgres.users import get_user_scientist
        scientist = get_user_scientist(user_id)
        sci_stats = scientist.get('stats', {}) if scientist else {}

        # Upgrade effects (equipment bonuses)
        from utilities.upgrades_utils import get_user_upgrade_effects
        upgrade_effects = get_user_upgrade_effects(user_id)

        # Completed expedition count (for progressive rarity)
        cur.execute("SELECT count(*) as cnt FROM pilgrim.expeditions WHERE user_id = %s AND status = 'complete'",
                    (user_id,))
        expedition_count = cur.fetchone()['cnt']

        # Existing discoveries
        cur.execute("SELECT * FROM pilgrim.expedition_discoveries WHERE expedition_id = %s ORDER BY found_at_km",
                    (expedition_id,))
        existing_discoveries = [dict(r) for r in cur.fetchall()]

        # Travel time from expedition pricing (reconstruct from departed_at / arrives_at)
        travel_hours = 0
        if exp.get('departed_at') and exp.get('arrives_at'):
            delta = exp['arrives_at'] - exp['departed_at']
            # max(0): a corrupted row with arrives_at < departed_at otherwise feeds a
            # negative travel time into calculate_discovery_checkpoints, which divides by it.
            travel_hours = max(0.0, delta.total_seconds() / 3600)
        travel_time_seconds = int(travel_hours * 3600)

        # Cargo capacity: stored on expedition + engineering bonus already applied at launch
        cargo_capacity = exp.get('cargo_capacity', 5)
        # Re-add engineering bonus if it wasn't included at launch
        eng_stat = sci_stats.get('engineering', 0)
        # Don't double-add — cargo_capacity on the expedition record already includes eng bonus

    return {
        'expedition_id': expedition_id,
        'user_id': user_id,
        'destination_name': exp['destination_name'],
        'destination_type': exp.get('destination_type', ''),
        'distance_km': float(exp['distance_km']),
        'vehicle_type': exp.get('vehicle_type', 'rover'),
        'cargo_capacity': cargo_capacity,
        'status': exp['status'],
        'departed_at': str(exp.get('departed_at', '')),
        'completed_at': str(exp.get('completed_at', '')),
        'travel_time_seconds': travel_time_seconds,
        'commander_stats': {
            'exploration': exp.get('commander_exploration', 50),
            'leadership': exp.get('commander_leadership', 50),
            'strategy': exp.get('commander_strategy', 50),
            'logistics': exp.get('commander_logistics', 50),
            'charisma': exp.get('commander_charisma', 50),
        },
        'scientist_stats': sci_stats,
        'scientist_name': scientist.get('name', 'Unknown') if scientist else 'None',
        'base_lat': base_lat,
        'base_lon': base_lon,
        'destination_lat': float(exp.get('destination_lat', 0)),
        'destination_lon': float(exp.get('destination_lon', 0)),
        'upgrade_effects': upgrade_effects,
        'expedition_count': expedition_count,
        'existing_discoveries': existing_discoveries,
        'existing_discovery_count': len(existing_discoveries),
        'sepolia_earned': float(exp.get('sepolia_earned') or 0),
    }


def replay_expedition(context: dict, seed_override: int = None) -> dict:
    """Replay discovery generation for an expedition. Returns full report."""
    start_time = time.time()

    expedition_id = context['expedition_id']
    distance_km = context['distance_km']

    # Load catalog and landmarks
    all_items = get_discovery_items_catalog()
    nearby_features = get_nearest_mars_landmarks(context['base_lat'], context['base_lon'], limit=20)

    expedition_data = {
        'distance_km': distance_km,
        'commander_stats': context['commander_stats'],
        'scientist_stats': context['scientist_stats'],
        'base_lat': context['base_lat'],
        'base_lon': context['base_lon'],
        'destination_lat': context['destination_lat'],
        'destination_lon': context['destination_lon'],
        'equipment_effects': context['upgrade_effects'],
    }

    # Use a different seed to avoid generating identical results to original
    replay_seed = seed_override if seed_override is not None else expedition_id + 100000

    discoveries = generate_expedition_discoveries(
        expedition_id=replay_seed,
        expedition_data=expedition_data,
        available_items=all_items,
        nearby_features=nearby_features,
        travel_time_seconds=context['travel_time_seconds'],
        user_expedition_count=context['expedition_count'],
        cargo_capacity=context['cargo_capacity'],
    )

    elapsed = time.time() - start_time

    # Enrich discoveries with item names and SV
    item_lookup = {item['id']: item for item in all_items}
    enriched = []
    for d in discoveries:
        item = item_lookup.get(d['discovery_item_id'], {})
        enriched.append({
            'discovery_item_id': d['discovery_item_id'],
            'item_name': item.get('item_name', f'Item #{d["discovery_item_id"]}'),
            'rarity': item.get('rarity', 'unknown'),
            'found_at_km': d['found_at_km'],
            'nearby_feature': d['nearby_feature'],
            'base_value': d['base_value'],
            'enhanced_value': d['enhanced_value'],
            'base_scientific_value': int(item.get('base_scientific_value', 0)),
            'weight_kg': d.get('weight_kg', 1.0),
        })

    # Calculate totals
    total_enhanced = sum(d['enhanced_value'] for d in enriched)
    total_sv_from_discoveries = sum(d['base_scientific_value'] for d in enriched)
    rarity_breakdown = {}
    for d in enriched:
        rarity_breakdown[d['rarity']] = rarity_breakdown.get(d['rarity'], 0) + 1

    # Distance-based SV (shown in haul modal)
    if distance_km <= 200:
        sv_from_distance = 100 + int(distance_km * 0.5)
    elif distance_km <= 500:
        sv_from_distance = 200 + int((distance_km - 200) * 1.0)
    elif distance_km <= 1500:
        sv_from_distance = 500 + int((distance_km - 500) * 0.5)
    else:
        sv_from_distance = 1000 + int((distance_km - 1500) * 0.4)
    sv_from_distance = max(100, min(sv_from_distance, 2000))

    # Shards from expedition itself (already earned, stored as ETH)
    shards_earned = int(context['sepolia_earned'] * 10_000_000)

    # Compare with existing — including SV
    existing_value = sum(d.get('enhanced_value', 0) for d in context['existing_discoveries'])
    # Calculate old SV from existing discoveries
    existing_sv = 0
    for d in context['existing_discoveries']:
        old_item = item_lookup.get(d.get('discovery_item_id'), {})
        existing_sv += int(old_item.get('base_scientific_value', 0))

    return {
        'meta': {
            'tool': 'speedrun_expedition',
            'version': '1.0',
            'generated_at': datetime.utcnow().isoformat() + 'Z',
            'elapsed_seconds': round(elapsed, 3),
            'replay_seed': replay_seed,
        },
        'expedition': {
            'id': context['expedition_id'],
            'user_id': context['user_id'],
            'destination': context['destination_name'],
            'destination_type': context['destination_type'],
            'distance_km': distance_km,
            'vehicle_type': context['vehicle_type'],
            'cargo_capacity': context['cargo_capacity'],
            'status': context['status'],
            'departed_at': context['departed_at'],
            'completed_at': context['completed_at'],
            'travel_time_hours': round(context['travel_time_seconds'] / 3600, 1),
        },
        'captain': {
            'stats': context['commander_stats'],
        },
        'scientist': {
            'name': context['scientist_name'],
            'stats': context['scientist_stats'],
        },
        'upgrade_effects_snapshot': {
            k: v for k, v in context['upgrade_effects'].items()
            if k in ('discovery_chance_bonus', 'rare_chance_bonus', 'legendary_chance_bonus',
                     'discovery_value_mult', 'cargo_capacity_mult', 'storage_capacity')
        },
        'comparison': {
            'old_discovery_count': context['existing_discovery_count'],
            'old_total_value': existing_value,
            'old_total_sv': existing_sv,
            'new_discovery_count': len(enriched),
            'new_total_value': total_enhanced,
            'new_total_sv': total_sv_from_discoveries,
            'improvement_count': len(enriched) - context['existing_discovery_count'],
            'improvement_value': total_enhanced - existing_value,
            'improvement_sv': total_sv_from_discoveries - existing_sv,
        },
        'results': {
            'discovery_count': len(enriched),
            'rarity_breakdown': rarity_breakdown,
            'total_enhanced_value': total_enhanced,
            'total_sv_from_discoveries': total_sv_from_discoveries,
            'sv_from_distance': sv_from_distance,
            'shards_earned_from_expedition': shards_earned,
            'discoveries': enriched,
        },
    }


def apply_replay(expedition_id: int, report: dict) -> dict:
    """Apply replayed discoveries to DB — replaces old discoveries with new ones."""
    discoveries = report['results']['discoveries']
    new_count = len(discoveries)

    with db_cursor(commit=True) as cur:
        # Delete old discoveries
        cur.execute("DELETE FROM pilgrim.expedition_discoveries WHERE expedition_id = %s", (expedition_id,))
        old_deleted = cur.rowcount

        # Insert new discoveries
        for d in discoveries:
            cur.execute("""
                INSERT INTO pilgrim.expedition_discoveries
                (expedition_id, discovery_item_id, found_at_km, found_at_coordinates, nearby_feature,
                 base_value, enhanced_value, quantity, unlocked_at, claimed_by_user)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 1, NOW(), false)
            """, (expedition_id, d['discovery_item_id'], d['found_at_km'],
                  json.dumps({'lat': 0, 'lon': 0}), d['nearby_feature'],
                  d['base_value'], d['enhanced_value']))

        # Update discovery count on expedition
        cur.execute("UPDATE pilgrim.expeditions SET discovery_count = %s WHERE id = %s",
                    (new_count, expedition_id))

    return {
        'applied': True,
        'expedition_id': expedition_id,
        'old_discoveries_deleted': old_deleted,
        'new_discoveries_inserted': new_count,
        'applied_at': datetime.utcnow().isoformat() + 'Z',
    }


def save_report(report: dict, expedition_id: int) -> str:
    """Save report JSON to tools/speedrun_results/."""
    os.makedirs(RESULTS_DIR, exist_ok=True)
    ts = int(time.time())
    filename = f'expedition_{expedition_id}_{ts}.json'
    filepath = os.path.join(RESULTS_DIR, filename)
    with open(filepath, 'w') as f:
        json.dump(report, f, indent=2, default=str)
    return filepath


def print_report(report: dict):
    """Pretty-print a speedrun report to console."""
    exp = report['expedition']
    comp = report['comparison']
    res = report['results']

    print(f"\n{'='*60}")
    print(f"  SPEEDRUN REPORT — Expedition #{exp['id']}")
    print(f"{'='*60}")
    print(f"  Destination:  {exp['destination']} ({exp['destination_type']})")
    print(f"  Distance:     {exp['distance_km']:,.1f} km")
    print(f"  Vehicle:      {exp['vehicle_type']} (cargo: {exp['cargo_capacity']})")
    print(f"  Travel Time:  {exp['travel_time_hours']:.1f} hours ({exp['travel_time_hours']/24:.1f} days)")
    print(f"  Status:       {exp['status']}")

    captain = report['captain']['stats']
    print(f"\n  Captain Stats: EXP={captain['exploration']} LEAD={captain['leadership']} STRAT={captain['strategy']}")
    sci = report['scientist']
    print(f"  Scientist:    {sci['name']} (analysis={sci['stats'].get('analysis',0)}, geology={sci['stats'].get('geology',0)}, eng={sci['stats'].get('engineering',0)})")

    print(f"\n  {'─'*56}")
    print(f"  COMPARISON: Old vs New")
    print(f"  {'─'*56}")
    print(f"  Old discoveries:  {comp['old_discovery_count']:>4}  (value: {comp['old_total_value']:>8,}  SV: {comp['old_total_sv']:>6,})")
    print(f"  New discoveries:  {comp['new_discovery_count']:>4}  (value: {comp['new_total_value']:>8,}  SV: {comp['new_total_sv']:>6,})")
    print(f"  Improvement:      +{comp['improvement_count']:>3} items, +{comp['improvement_value']:>7,} value, +{comp['improvement_sv']:>5,} SV")

    print(f"\n  Rarity: {res['rarity_breakdown']}")
    print(f"  Shards from expedition: {res['shards_earned_from_expedition']:,}")
    print(f"  SV from discoveries: {res['total_sv_from_discoveries']:,} (feeds tech tree)")
    print(f"  SV from distance: {res['sv_from_distance']:,} (haul modal display)")

    print(f"\n  {'─'*56}")
    print(f"  DISCOVERIES ({res['discovery_count']})")
    print(f"  {'─'*56}")
    for i, d in enumerate(res['discoveries'], 1):
        rarity_tag = d['rarity'][0].upper()
        print(f"  {i:>2}. [{rarity_tag}] {d['item_name']:<30} val={d['enhanced_value']:>6,}  SV={d['base_scientific_value']:>4}  @{d['found_at_km']:>8,.1f}km  near {d['nearby_feature']}")

    print(f"\n  Generated in {report['meta']['elapsed_seconds']}s")
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description='Expedition Speedrun — replay discovery generation')
    parser.add_argument('--expedition', '-e', type=int, nargs='+', help='Expedition ID(s) to replay')
    parser.add_argument('--user', '-u', type=int, help='Replay all active/recent expeditions for a user')
    parser.add_argument('--apply', action='store_true', help='Actually write new discoveries to DB (default: dry run)')
    parser.add_argument('--quiet', '-q', action='store_true', help='Skip console output, just save JSON')
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)

    expedition_ids = []

    if args.expedition:
        expedition_ids = args.expedition
    elif args.user:
        with db_cursor() as cur:
            cur.execute("""SELECT id FROM pilgrim.expeditions
                          WHERE user_id = %s AND status IN ('traveling', 'complete')
                          ORDER BY departed_at DESC LIMIT 20""", (args.user,))
            expedition_ids = [r['id'] for r in cur.fetchall()]
        print(f"Found {len(expedition_ids)} expeditions for user {args.user}")
    else:
        parser.print_help()
        return

    all_reports = []
    for eid in expedition_ids:
        try:
            context = load_expedition_context(eid)
            report = replay_expedition(context)

            if not args.quiet:
                print_report(report)

            filepath = save_report(report, eid)
            print(f"  Report saved: {filepath}")

            if args.apply:
                result = apply_replay(eid, report)
                report['apply_result'] = result
                print(f"  ✅ APPLIED: Replaced {result['old_discoveries_deleted']} old → {result['new_discoveries_inserted']} new discoveries")
                # Re-save with apply result
                save_report(report, eid)
            else:
                print(f"  (dry run — use --apply to write to DB)")

            all_reports.append(report)
        except Exception as e:
            print(f"  ❌ Failed to replay expedition #{eid}: {e}")
            import traceback
            traceback.print_exc()

    # Summary
    if len(all_reports) > 1:
        print(f"\n{'='*60}")
        print(f"  SUMMARY — {len(all_reports)} expeditions replayed")
        print(f"{'='*60}")
        total_old = sum(r['comparison']['old_discovery_count'] for r in all_reports)
        total_new = sum(r['comparison']['new_discovery_count'] for r in all_reports)
        total_old_val = sum(r['comparison']['old_total_value'] for r in all_reports)
        total_new_val = sum(r['comparison']['new_total_value'] for r in all_reports)
        total_old_sv = sum(r['comparison']['old_total_sv'] for r in all_reports)
        total_new_sv = sum(r['comparison']['new_total_sv'] for r in all_reports)
        print(f"  Total old: {total_old} discoveries ({total_old_val:,} value, {total_old_sv:,} SV)")
        print(f"  Total new: {total_new} discoveries ({total_new_val:,} value, {total_new_sv:,} SV)")
        print(f"  Net gain:  +{total_new - total_old} discoveries (+{total_new_val - total_old_val:,} value, +{total_new_sv - total_old_sv:,} SV)")


if __name__ == '__main__':
    main()
