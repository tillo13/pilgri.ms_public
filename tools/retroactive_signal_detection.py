"""Retroactive Signal detection — Signal Phase 2.1.

Walks every completed expedition in pilgrim.expeditions and re-evaluates signal
detection using the new path-based (Base → Destination segment) math. When a
previously-destination-only captain would now be detecting an Origin Site, this
writes a 'signal_detection' row to pilgrim.activity_events so the captain sees
it in their feed.

Idempotent: checks for an existing activity_events row with the same
(user_id, source_id=expedition_id, source_table='expeditions', event_type='signal_detection')
before inserting. Safe to re-run.

Usage:
    source venv_galactica/bin/activate
    python -m tools.retroactive_signal_detection                 # dry-run (default)
    python -m tools.retroactive_signal_detection --commit        # actually insert
"""

import argparse
import logging
import sys

from utilities.postgres.core import db_cursor
from utilities.postgres.map import get_or_set_user_mars_home
from utilities.postgres.activity import log_activity
from utilities.mars_math import point_to_path_distance
from utilities.signal.sites import get_all_origin_sites

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


def _fetch_completed_expeditions():
    with db_cursor() as cur:
        cur.execute("""
            SELECT id, user_id, destination_name, destination_lat, destination_lon,
                   completed_at
            FROM pilgrim.expeditions
            WHERE status = 'complete'
              AND destination_lat IS NOT NULL
              AND destination_lon IS NOT NULL
            ORDER BY user_id, completed_at
        """)
        return cur.fetchall()


def _already_logged(user_id: int, expedition_id: int, site_code: str) -> bool:
    """Idempotency check — have we already written this detection?"""
    with db_cursor() as cur:
        cur.execute("""
            SELECT 1 FROM pilgrim.activity_events
            WHERE user_id = %s
              AND source_table = 'expeditions'
              AND source_id = %s
              AND event_type = 'signal_detection'
              AND metadata->>'site_code' = %s
            LIMIT 1
        """, (user_id, expedition_id, site_code))
        return cur.fetchone() is not None


def run(commit: bool = False):
    sites = get_all_origin_sites()
    unclaimed = [s for s in sites if not s['is_claimed']]
    logger.info(f"Loaded {len(sites)} sites ({len(unclaimed)} unclaimed)")

    expeditions = _fetch_completed_expeditions()
    logger.info(f"Scanning {len(expeditions)} completed expeditions\n")

    base_cache: dict = {}
    new_detections = 0
    skipped_existing = 0
    skipped_claimed = 0
    scanned = 0

    for exp in expeditions:
        scanned += 1
        user_id = exp['user_id']
        expedition_id = exp['id']

        if user_id not in base_cache:
            try:
                base = get_or_set_user_mars_home(user_id)
                base_cache[user_id] = (float(base['latitude']), float(base['longitude']))
            except Exception as e:
                logger.warning(f"user {user_id}: could not fetch base coords: {e}")
                base_cache[user_id] = None
        base_coords = base_cache[user_id]
        if not base_coords:
            continue

        base_lat, base_lon = base_coords
        dest_lat = float(exp['destination_lat'])
        dest_lon = float(exp['destination_lon'])

        for site in unclaimed:
            distance = point_to_path_distance(
                site['latitude'], site['longitude'],
                base_lat, base_lon,
                dest_lat, dest_lon,
            )
            if distance > site['unlock_radius_km']:
                continue

            if _already_logged(user_id, expedition_id, site['site_code']):
                skipped_existing += 1
                continue

            title = f"Signal detected: {site['mission_name']}"
            detail = (
                f"Your path to {exp['destination_name']} passed within "
                f"{distance:.1f} km of {site['mission_name']} "
                f"({site['unlock_radius_km']} km radius)."
            )
            meta = {
                'site_code': site['site_code'],
                'site_id': site['id'],
                'mission_name': site['mission_name'],
                'path_distance_km': round(distance, 2),
                'unlock_radius_km': site['unlock_radius_km'],
                'retroactive': True,
            }
            logger.info(
                f"  user={user_id} exp={expedition_id} → {site['site_code']} "
                f"({distance:.1f} km / {site['unlock_radius_km']} km)"
            )
            if commit:
                log_activity(
                    user_id=user_id,
                    category='signal',
                    event_type='signal_detection',
                    title=title,
                    detail=detail,
                    metadata=meta,
                    source_table='expeditions',
                    source_id=expedition_id,
                    created_at=exp['completed_at'],
                )
            new_detections += 1

    # Second pass: also flag expeditions where the destination endpoint was ALREADY
    # within the site radius but we never logged it (covers sites that existed before
    # the activity_events table had signal_detection as an event type).

    logger.info("\n" + "=" * 60)
    logger.info(f"Expeditions scanned:   {scanned}")
    logger.info(f"New detections found:  {new_detections}")
    logger.info(f"Already-logged (skip): {skipped_existing}")
    logger.info(f"Mode: {'COMMIT' if commit else 'DRY-RUN'}")
    if not commit:
        logger.info("\nRe-run with --commit to actually insert activity rows.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--commit', action='store_true',
                        help='Actually insert activity rows. Default is dry-run.')
    args = parser.parse_args()
    run(commit=args.commit)


if __name__ == '__main__':
    main()
