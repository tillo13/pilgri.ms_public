"""One-shot backfill: reconstruct scene_actors metadata for existing
aria_snapshot rows in pilgrim.generated_images so the album modal can render
the chip row on snapshots saved BEFORE the 2026-05-16 scene_actors deploy.

URL-pattern-driven so it handles both orchestrator (claude_dynamic) and
generator (template-driven) outputs.

  captain   → URL contains '/characters/'   → name from users.commander_name
  scientist → URL contains '/scientists/'   → name from users.scientist_key + COLONY_SCIENTISTS
  aria      → URL contains 'concept_aria_rock' OR '/aria/'  → name 'ARIA'
  discovery → URL contains '/discoveries/'  → best-effort lookup pilgrim.discoveries by gcs_url
  vehicle   → URL contains '/vehicles/' OR matches a user_owned_vehicle    → best-effort lookup

Usage:
    python -m tools.backfill_aria_scene_actors            # dry run
    python -m tools.backfill_aria_scene_actors --apply    # commit
"""

import json
import sys
from utilities.postgres.core import db_cursor

DRY_RUN = '--apply' not in sys.argv


def _classify(url: str) -> str:
    if not url:
        return 'unknown'
    u = url.lower()
    if 'concept_aria_rock' in u or '/aria/' in u or 'aria_selfie' in u:
        return 'aria'
    if '/characters/' in u:
        return 'captain'
    if '/scientists/' in u or '/default_leaders/' in u:
        return 'scientist'
    if '/discoveries/' in u or '/discovery_items/' in u:
        return 'discovery'
    if '/vehicles/' in u or '/rovers/' in u or '/shop_items/' in u or '/upgrades/' in u:
        return 'vehicle'
    if '/test_generation/' in u:
        return 'unknown'  # old test renders, ignore
    return 'unknown'


def main():
    from config import COLONY_SCIENTISTS

    with db_cursor() as cur:
        cur.execute("""
            SELECT g.id, g.user_id, g.source_image_url, g.metadata,
                   u.captain_name, u.scientist_key
            FROM pilgrim.generated_images g
            LEFT JOIN pilgrim.users u ON u.id = g.user_id
            WHERE g.category = 'aria_snapshot'
              AND g.source_image_url IS NOT NULL
              AND NOT (g.metadata ? 'scene_actors')
            ORDER BY g.id
        """)
        rows = cur.fetchall()
    print(f'Found {len(rows)} aria_snapshots needing backfill')
    print(f'Mode: {"DRY RUN (pass --apply to commit)" if DRY_RUN else "APPLY"}')
    print()

    # Pre-load discovery name lookup by image_url (one query, not N+1)
    with db_cursor() as cur:
        cur.execute("SELECT image_url, item_name FROM pilgrim.discovery_items WHERE image_url IS NOT NULL")
        discovery_name_by_url = {r['image_url']: r['item_name'] for r in cur.fetchall()}
    print(f'  pre-loaded {len(discovery_name_by_url)} discovery URL → name mappings')

    # Vehicle name lookup: discover the right table at query time
    vehicle_by_url = {}
    with db_cursor() as cur:
        cur.execute("""SELECT table_name FROM information_schema.tables
                       WHERE table_schema='pilgrim' AND table_name ILIKE '%vehicle%' LIMIT 5""")
        for r in cur.fetchall():
            print(f'  found vehicle table: pilgrim.{r["table_name"]}')
    # We'll fall back to URL pattern detection for vehicles since we don't have an authoritative lookup
    print(f'  vehicle lookup: {len(vehicle_by_url)} pre-loaded (using fallback "Vehicle" label)')
    print()

    updated = 0
    skipped = 0
    type_counts = {'captain': 0, 'scientist': 0, 'aria': 0, 'discovery': 0, 'vehicle': 0, 'unknown': 0}

    for r in rows:
        urls = [u.strip() for u in (r['source_image_url'] or '').split(',') if u.strip()]
        if not urls:
            skipped += 1
            continue

        scientist_name = None
        if r['scientist_key'] and r['scientist_key'] in COLONY_SCIENTISTS:
            scientist_name = COLONY_SCIENTISTS[r['scientist_key']].get('name')

        actors = []
        for url in urls:
            t = _classify(url)
            type_counts[t] = type_counts.get(t, 0) + 1
            if t == 'captain':
                actors.append({'type': 'captain',
                               'name': r['captain_name'] or 'Captain',
                               'image_url': url})
            elif t == 'aria':
                actors.append({'type': 'aria', 'name': 'ARIA', 'image_url': url})
            elif t == 'scientist':
                # default_leaders URLs encode the scientist name in the filename
                # (e.g. leader12_lilla.png → "Lilla"). Use that if our scientist_key
                # lookup didn't apply or returned nothing.
                fallback_name = None
                if '/default_leaders/' in url.lower():
                    import re as _re
                    m = _re.search(r'leader\d+_([a-z]+)\.', url, _re.IGNORECASE)
                    if m:
                        fallback_name = 'Dr. ' + m.group(1).title()
                actors.append({'type': 'scientist',
                               'name': scientist_name or fallback_name or 'Scientist',
                               'image_url': url})
            elif t == 'discovery':
                actors.append({'type': 'discovery',
                               'name': discovery_name_by_url.get(url) or 'Discovery',
                               'image_url': url})
            elif t == 'vehicle':
                # Vehicle names from shop_items / upgrades filenames
                # (e.g. rover_basic_*, vehicles_rover_lv2_*). Extract type segment.
                import re as _re
                fname = url.rsplit('/', 1)[-1] if '/' in url else url
                # Strip _lvN, _NNNN timestamp suffixes
                cleaned = _re.sub(r'_\d{6,}\.png$', '', fname)
                cleaned = _re.sub(r'(?:_lv\d+)?$', '', cleaned)
                # Drop a leading "vehicles_" prefix
                cleaned = _re.sub(r'^vehicles_', '', cleaned)
                veh_name = cleaned.replace('_', ' ').title() if cleaned else 'Vehicle'
                actors.append({'type': 'vehicle',
                               'name': vehicle_by_url.get(url) or veh_name,
                               'image_url': url})
            # 'unknown' → silently drop; can't classify safely

        if not actors:
            skipped += 1
            continue

        if not DRY_RUN:
            with db_cursor(commit=True) as cur:
                cur.execute("""UPDATE pilgrim.generated_images
                               SET metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb
                               WHERE id = %s""",
                            (json.dumps({'scene_actors': actors}), r['id']))
        updated += 1
        if updated <= 5 or updated % 50 == 0:
            print(f'  [#{r["id"]} u{r["user_id"]}] {len(actors)} actors: {[a["type"]+":"+a["name"] for a in actors]}')

    print()
    print(f'═══ SUMMARY ═══')
    print(f'  Updated:  {updated}')
    print(f'  Skipped:  {skipped}')
    print(f'  URL classification breakdown: {type_counts}')
    if DRY_RUN:
        print()
        print(f'  ⚠️  DRY RUN — no DB writes. Re-run with --apply to commit.')


if __name__ == '__main__':
    main()
