#!/usr/bin/env python3
"""
Backfill upgrade images for levels players have already reached.
Generates missing images using Kontext chain from nearest available source.

Usage:
    python tools/backfill_upgrade_images.py --dry-run
    python tools/backfill_upgrade_images.py --category infrastructure
    python tools/backfill_upgrade_images.py --category equipment --item cargo
    python tools/backfill_upgrade_images.py --limit 5
"""

import sys
import os
import argparse
import logging
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utilities.postgres.core import db_cursor
from utilities.upgrade_image_utils import (
    get_stored_image_url, get_level_image_url,
    get_infrastructure_level_image_url, get_best_available_image,
    generate_upgrade_image_background,
)
from config_upgrades import UPGRADE_CATALOG
from config_infrastructure import INFRASTRUCTURE_CATALOG

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def get_player_max_levels():
    """Get the max level reached for each (category, item_key) across all players."""
    with db_cursor() as cur:
        cur.execute("""
            SELECT category, item_key, MAX(GREATEST(level, COALESCE(pending_level, 0))) as max_level
            FROM pilgrim.player_upgrades
            GROUP BY category, item_key
            ORDER BY category, item_key
        """)
        return [dict(row) for row in cur.fetchall()]


def has_image(category, item_key, level):
    """Check if an image exists for this level (DB or config)."""
    stored = get_stored_image_url(category, item_key, level)
    if stored:
        return True
    if category == 'infrastructure':
        config_url = get_infrastructure_level_image_url(item_key, level)
    else:
        config_url = get_level_image_url(category, item_key, level)
    return bool(config_url and config_url.strip())


def find_missing_images(category_filter=None, item_filter=None):
    """Find all levels that need images generated."""
    player_levels = get_player_max_levels()
    missing = []

    for row in player_levels:
        category = row['category']
        item_key = row['item_key']
        max_level = row['max_level']

        if category_filter and category != category_filter:
            continue
        if item_filter and item_key != item_filter:
            continue

        # Check each level from 2 to max_level
        for level in range(2, max_level + 1):
            if not has_image(category, item_key, level):
                source = get_best_available_image(category, item_key, level - 1)
                missing.append({
                    'category': category,
                    'item_key': item_key,
                    'level': level,
                    'has_source': bool(source),
                    'source_url': source[:60] + '...' if source and len(source) > 60 else source,
                })

    return missing


def backfill(category_filter=None, item_filter=None, limit=None, dry_run=False):
    """Generate missing images via Kontext chain."""
    missing = find_missing_images(category_filter, item_filter)

    if not missing:
        print("No missing images found. Everything is up to date.")
        return

    print(f"\nFound {len(missing)} missing images:")
    for m in missing:
        src = 'HAS SOURCE' if m['has_source'] else 'NO SOURCE'
        print(f"  {m['category']}/{m['item_key']} Lv{m['level']} [{src}]")

    if dry_run:
        print(f"\n--dry-run: Would generate {len(missing)} images. Exiting.")
        return

    # Filter to only those with source images
    generable = [m for m in missing if m['has_source']]
    if limit:
        generable = generable[:limit]

    print(f"\nGenerating {len(generable)} images...")

    for i, m in enumerate(generable):
        category = m['category']
        item_key = m['item_key']
        level = m['level']

        # Get fresh source (may have been generated in previous iteration)
        source_url = get_best_available_image(category, item_key, level - 1)
        if not source_url:
            print(f"  [{i+1}/{len(generable)}] SKIP {category}/{item_key} Lv{level} - no source")
            continue

        print(f"  [{i+1}/{len(generable)}] Generating {category}/{item_key} Lv{level}...")

        # Bounded retry — kumori.ai throws chronic transient SSL/503 "all_providers_failed"
        # blips; the #1489 plan requires the batch tool to ride through them (5 tries x 12s).
        # generate_* returns None on BOTH transient failure and quota-exhaustion; for a large
        # run, distinguishing the two for an early quota stop is a future improvement.
        result = None
        for attempt in range(1, 6):
            result = generate_upgrade_image_background(category, item_key, level, source_url)
            if result:
                break
            if attempt < 5:
                print(f"    attempt {attempt} failed (transient kumori error?), retrying in 12s...")
                time.sleep(12)

        if result:
            print(f"    -> {result}")
        else:
            print(f"    -> FAILED after 5 attempts")

        # Rate limiting
        if i < len(generable) - 1:
            time.sleep(2)

    print(f"\nDone! Generated {len(generable)} images.")


def main():
    parser = argparse.ArgumentParser(description='Backfill missing upgrade images')
    parser.add_argument('--category', help='Filter by category (e.g. infrastructure, vehicles)')
    parser.add_argument('--item', help='Filter by item key (e.g. solar_array, rover)')
    parser.add_argument('--limit', type=int, help='Max images to generate')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be generated')
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"Upgrade Image Backfill")
    print(f"{'='*60}")

    # Kumori free-edit client is wired at app boot (app.py); this standalone tool must
    # init it itself or generate_upgrade_image_background() fails "client not initialized".
    # PILGRIMS_KUMORI_API_KEY lives in kumori-404602 Secret Manager (not galactica's project).
    if not args.dry_run:
        from utilities.kumori_utils import init_kumori
        from utilities.google_auth_utils import get_secret
        init_kumori(
            get_secret_fn=lambda name: get_secret(name, project_id='kumori-404602'),
            api_key_name='PILGRIMS_KUMORI_API_KEY',
        )

    backfill(
        category_filter=args.category,
        item_filter=args.item,
        limit=args.limit,
        dry_run=args.dry_run,
    )


if __name__ == '__main__':
    main()
