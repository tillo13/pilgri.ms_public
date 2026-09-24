#!/usr/bin/env python3
"""One-time backfill: populate pilgrim.activity_events from existing source tables.

Usage: python tools/backfill_activity.py [--dry-run]

Uses batch INSERT for speed (~5 seconds vs ~10 minutes for row-by-row).
"""
import sys
import os
import json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utilities.postgres.core import db_cursor, _fetchall, json_serial
from utilities.postgres.activity import ensure_activity_table
from utilities.postgres.shop import _format_depot_activity

DRY_RUN = '--dry-run' in sys.argv
rows_to_insert = []
counts = {}


def _add(user_id, category, event_type, title, amount=0, detail='', tx_hash='',
         image_url='', metadata=None, source_table=None, source_id=None, created_at=None):
    """Buffer a row for batch insert."""
    counts[category] = counts.get(category, 0) + 1
    if DRY_RUN:
        return
    rows_to_insert.append((
        user_id, category, event_type, title[:200], float(amount or 0),
        detail or '', tx_hash or '', image_url or '',
        json.dumps(metadata or {}, default=json_serial),
        source_table, source_id, created_at
    ))


def backfill():
    ensure_activity_table()

    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) as cnt FROM pilgrim.activity_events")
        existing = cur.fetchone()['cnt']
    if existing > 0 and not DRY_RUN:
        print(f"WARNING: activity_events already has {existing} rows. Skipping to avoid duplicates.")
        print("  To re-run, first: TRUNCATE pilgrim.activity_events;")
        return

    with db_cursor() as cur:
        # 1. Depot transactions
        cur.execute("SELECT id, user_id, purchase_type, amount_eth, item_details, tx_hash, created_at FROM pilgrim.depot_transactions ORDER BY created_at")
        for r in _fetchall(cur):
            raw = r.get('item_details')
            details = raw if isinstance(raw, dict) else (json.loads(raw) if isinstance(raw, str) else {}) if raw else {}
            title, cat, detail = _format_depot_activity(r.get('purchase_type', 'purchase'), details)
            _add(r['user_id'], cat, r.get('purchase_type', 'purchase'), title,
                 amount=float(r['amount_eth']) * 10000000 if r.get('amount_eth') else 0,
                 detail=detail, tx_hash=r.get('tx_hash', ''),
                 source_table='depot_transactions', source_id=r['id'], created_at=r['created_at'])

        # 2. Infrastructure builds
        from utilities.infrastructure_utils import INFRASTRUCTURE_CATALOG
        cur.execute("SELECT id, user_id, structure_type, structure_name, cost_sepolia, status, created_at FROM pilgrim.colony_infrastructure ORDER BY created_at")
        for r in _fetchall(cur):
            cat_def = INFRASTRUCTURE_CATALOG.get(r.get('structure_type', ''), {})
            _add(r['user_id'], 'infrastructure', 'infrastructure_build',
                 r.get('structure_name') or r.get('structure_type', 'Building').replace('_', ' ').title(),
                 amount=float(r['cost_sepolia']) * 10000000 if r.get('cost_sepolia') else 0,
                 image_url=cat_def.get('image_url', ''),
                 source_table='colony_infrastructure', source_id=r['id'], created_at=r['created_at'],
                 metadata={'structure_type': r.get('structure_type'), 'status': r.get('status')})

        # 3. Expeditions
        cur.execute("""
            SELECT e.id, e.user_id, e.destination_name, e.fuel_cost_eth, e.vehicle_type,
                   e.distance_km, e.sepolia_earned, e.status, e.created_at,
                   COUNT(ed.id) as discovery_count
            FROM pilgrim.expeditions e
            LEFT JOIN pilgrim.expedition_discoveries ed ON ed.expedition_id = e.id
            GROUP BY e.id ORDER BY e.created_at
        """)
        for r in _fetchall(cur):
            is_complete = r.get('status') == 'complete'
            _add(r['user_id'], 'expedition', 'expedition_launch', f"Expedition to {r['destination_name']}",
                 amount=float(r['fuel_cost_eth']) * 10000000 if r.get('fuel_cost_eth') else 0,
                 detail=r.get('vehicle_type', ''),
                 source_table='expeditions', source_id=r['id'], created_at=r['created_at'],
                 metadata={'expedition_id': r['id'], 'destination': r['destination_name'],
                           'distance_km': float(r.get('distance_km') or 0),
                           'shards_earned': float(r.get('sepolia_earned') or 0) if is_complete else 0,
                           'discovery_count': r.get('discovery_count') or 0, 'is_complete': is_complete,
                           'vehicle_type': r.get('vehicle_type', '')})

        # 4. Expedition discoveries (claimed only)
        cur.execute("""
            SELECT ed.id, e.user_id, di.item_name, di.rarity, di.image_url,
                   ed.base_value, ed.enhanced_value, ed.claimed_at, ed.created_at
            FROM pilgrim.expedition_discoveries ed
            JOIN pilgrim.expeditions e ON ed.expedition_id = e.id
            LEFT JOIN pilgrim.discovery_items di ON di.id = ed.discovery_item_id
            WHERE ed.claimed_at IS NOT NULL ORDER BY ed.claimed_at
        """)
        for r in _fetchall(cur):
            _add(r['user_id'], 'discovery', 'discovery_claimed',
                 r.get('item_name') or f"Discovery #{r.get('id','')}",
                 amount=float(r.get('enhanced_value') or r.get('base_value') or 0),
                 detail=(r.get('rarity') or 'common').title(),
                 image_url=r.get('image_url', ''),
                 source_table='expedition_discoveries', source_id=r['id'],
                 created_at=r.get('claimed_at') or r['created_at'])

        # 5. Landmark discoveries
        cur.execute("SELECT user_id, landmark_name, landmark_type, distance_km, sepolia_earned, discovered_at FROM pilgrim.landmark_discoveries ORDER BY discovered_at")
        for r in _fetchall(cur):
            _add(r['user_id'], 'landmark', 'landmark_discovery', f"Discovered: {r['landmark_name']}",
                 amount=float(r['sepolia_earned']) * 10000000 if r.get('sepolia_earned') else 0,
                 detail=f"{r.get('landmark_type', '')} · {r.get('distance_km', 0):.0f} km",
                 source_table='landmark_discoveries', created_at=r['discovered_at'],
                 metadata={'distance_km': float(r.get('distance_km') or 0), 'landmark_type': r.get('landmark_type', '')})

        # 6. Site claims
        cur.execute("SELECT id, site_type, user_id, claim_rank, claim_tier, discovery_name, tx_hash, claimed_at FROM pilgrim.site_claims ORDER BY claimed_at")
        for r in _fetchall(cur):
            _add(r['user_id'], 'claim', f"claim_{r.get('site_type', 'origin')}",
                 f"{(r.get('site_type') or 'Site').title()} Claim #{r.get('claim_rank', '')}",
                 detail=r.get('discovery_name', ''), tx_hash=r.get('tx_hash', ''),
                 source_table='site_claims', source_id=r['id'], created_at=r['claimed_at'])

        # 7. Tech research
        try:
            cur.execute("SELECT user_id, branch, tech_key, sp_cost, status, research_started_at FROM pilgrim.player_techs WHERE research_started_at IS NOT NULL ORDER BY research_started_at")
            for r in _fetchall(cur):
                _add(r['user_id'], 'research', 'tech_research_start',
                     f"Research: {r['tech_key'].replace('_', ' ').title()}",
                     amount=r.get('sp_cost', 0), detail=f"{r.get('branch', '')} branch",
                     source_table='player_techs', created_at=r['research_started_at'],
                     metadata={'branch': r.get('branch'), 'tech_key': r.get('tech_key'), 'status': r.get('status')})
        except Exception as e:
            print(f"  Skipping player_techs: {e}")

        # 8. Trail missions (completed)
        try:
            cur.execute("SELECT id, user_id, crew_member, destination_name, trip_count_added, xp_gained, completed_at FROM pilgrim.crew_missions WHERE completed_at IS NOT NULL ORDER BY completed_at")
            for r in _fetchall(cur):
                member = (r.get('crew_member') or 'Crew').replace('_', ' ').title()
                _add(r['user_id'], 'trail', 'trail_mission_complete',
                     f"Trail: {r.get('destination_name', 'Unknown')}",
                     detail=f"{member} +{r.get('xp_gained', 0)} XP",
                     source_table='crew_missions', source_id=r['id'], created_at=r['completed_at'])
        except Exception as e:
            print(f"  Skipping crew_missions: {e}")

        # 9. Media (replicate assets)
        try:
            cur.execute("SELECT id, user_id, asset_type, commander_name, gcs_url, created_at FROM pilgrim.replicate_assets WHERE is_deleted = false ORDER BY created_at")
            type_labels = {'character_image': 'Captain Portrait', 'edited_image': 'Captain Edit', 'character_video': 'Captain Video'}
            for r in _fetchall(cur):
                label = type_labels.get(r.get('asset_type'), 'Media')
                name = r.get('commander_name') or ''
                _add(r['user_id'], 'media', r.get('asset_type', 'media'),
                     f"{label}: {name}" if name else label,
                     image_url=r.get('gcs_url', ''),
                     source_table='replicate_assets', source_id=r['id'], created_at=r['created_at'])
        except Exception as e:
            print(f"  Skipping replicate_assets: {e}")

        # 10. ARIA snapshots
        try:
            cur.execute("SELECT user_id, category, item_key, caption, gcs_url, created_at FROM pilgrim.generated_images WHERE is_active = true ORDER BY created_at")
            for r in _fetchall(cur):
                caption = r.get('caption') or (r.get('item_key') or 'snapshot').replace('_', ' ').title()
                _add(r['user_id'], 'media', 'aria_snapshot', f"ARIA Snapshot: {caption}",
                     image_url=r.get('gcs_url', ''),
                     source_table='generated_images', created_at=r['created_at'])
        except Exception as e:
            print(f"  Skipping generated_images: {e}")

        # 11. ARIA bonds (bonded only)
        try:
            cur.execute("SELECT id, user_id_1, user_id_2, landmark_name, bonded_at FROM pilgrim.aria_bonds WHERE status = 'bonded' ORDER BY bonded_at")
            for r in _fetchall(cur):
                for uid in (r['user_id_1'], r['user_id_2']):
                    _add(uid, 'discovery', 'aria_bond', f"ARIA Bond: {r.get('landmark_name', 'Unknown')}",
                         detail='Landmark entanglement',
                         source_table='aria_bonds', source_id=r['id'], created_at=r['bonded_at'])
        except Exception as e:
            print(f"  Skipping aria_bonds: {e}")

        # 12. Player upgrades
        try:
            cur.execute("SELECT user_id, category, item_key, level, tx_hash, upgraded_at FROM pilgrim.player_upgrades WHERE upgraded_at IS NOT NULL ORDER BY upgraded_at")
            for r in _fetchall(cur):
                _add(r['user_id'], 'upgrade', 'equipment_upgrade',
                     f"Upgraded: {r.get('item_key', 'item').replace('_', ' ').title()} Lv{r.get('level', 1)}",
                     detail=r.get('category', ''), tx_hash=r.get('tx_hash', ''),
                     source_table='player_upgrades', created_at=r['upgraded_at'],
                     metadata={'category': r.get('category'), 'item_key': r.get('item_key'), 'level': r.get('level')})
        except Exception as e:
            print(f"  Skipping player_upgrades: {e}")

        # 13. Echo sites
        try:
            cur.execute("SELECT id, spawned_by_user_id, site_code, nearby_landmark, created_at FROM pilgrim.echo_sites ORDER BY created_at")
            for r in _fetchall(cur):
                if r.get('spawned_by_user_id'):
                    _add(r['spawned_by_user_id'], 'discovery', 'echo_site_spawn',
                         f"Echo Site Spawned: {r.get('site_code', '')}",
                         detail=r.get('nearby_landmark', ''),
                         source_table='echo_sites', source_id=r['id'], created_at=r['created_at'])
        except Exception as e:
            print(f"  Skipping echo_sites: {e}")

        # 14. Puzzle solvers
        try:
            cur.execute("""
                SELECT ps.user_id, ps.solve_rank, ps.reward_name, ps.solved_at, sp.puzzle_name
                FROM pilgrim.puzzle_solvers ps
                LEFT JOIN pilgrim.signal_puzzles sp ON sp.id = ps.puzzle_id
                ORDER BY ps.solved_at
            """)
            for r in _fetchall(cur):
                _add(r['user_id'], 'discovery', 'puzzle_solved',
                     f"Decoded: {r.get('puzzle_name', 'Puzzle')}",
                     detail=f"Rank #{r.get('solve_rank', '?')}",
                     source_table='puzzle_solvers', created_at=r.get('solved_at'))
        except Exception as e:
            print(f"  Skipping puzzle_solvers: {e}")

    # Batch INSERT in chunks of 200 (avoids SSL payload limits on remote DB)
    if rows_to_insert:
        from psycopg2.extras import execute_values
        chunk_size = 200
        for i in range(0, len(rows_to_insert), chunk_size):
            chunk = rows_to_insert[i:i + chunk_size]
            with db_cursor(commit=True) as cur:
                execute_values(cur, """
                    INSERT INTO pilgrim.activity_events
                    (user_id, category, event_type, title, amount, detail, tx_hash,
                     image_url, metadata, source_table, source_id, created_at)
                    VALUES %s
                """, chunk)
            print(f"  Inserted {min(i + chunk_size, len(rows_to_insert))}/{len(rows_to_insert)}...")

    total = sum(counts.values())
    print(f"\n{'[DRY RUN] ' if DRY_RUN else ''}Backfill complete: {total} events")
    for cat, n in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {cat}: {n}")


if __name__ == '__main__':
    print("Activity Events Backfill" + (" (DRY RUN)" if DRY_RUN else ""))
    print("=" * 40)
    backfill()
