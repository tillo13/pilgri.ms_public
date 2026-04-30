"""One-shot backfill of pilgrim.robot_history from existing GCS narog images.

Lists every narog_*.png in robots/{user_id}/ and inserts a history entry per
file, parsing the timestamp out of the filename (narog_YYYYMMDDHHMMSS.png).
Skips the file currently set as `current_image_url` (that's the live state,
not history). Handles both the old naming scheme (narog_{ts}.png) and the
new one (narog_u{user_id}_{ts}.png).

Run-once. Idempotent — uses INSERT ... WHERE NOT EXISTS so re-runs don't
duplicate. Safe to invoke for any user_id; defaults to 45 + 112.
"""
import re
import sys
import subprocess
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utilities.postgres.core import db_cursor

GCS_BUCKET = 'galactica-pilgrim-assets'
GCS_PREFIX = 'https://storage.googleapis.com/' + GCS_BUCKET + '/'

# narog_20260430143911.png  OR  narog_u112_20260430211718.png
TS_RE = re.compile(r'narog_(?:u\d+_)?(\d{14})\.png$')


def list_user_blobs(user_id: int) -> list[str]:
    """Returns list of (timestamp_str, https_url) for every narog_*.png in
    /robots/{user_id}/, sorted oldest first."""
    cmd = ['gcloud', 'storage', 'ls', f'gs://{GCS_BUCKET}/robots/{user_id}/']
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    out = (proc.stdout or '') + (proc.stderr or '')
    items = []
    for line in out.strip().split('\n'):
        line = line.strip()
        m = TS_RE.search(line)
        if not m:
            continue
        ts = m.group(1)
        # Normalize to https URL
        if line.startswith('gs://'):
            line = line.replace(f'gs://{GCS_BUCKET}/', GCS_PREFIX)
        items.append((ts, line))
    items.sort(key=lambda x: x[0])
    return items


def parse_ts(ts_str: str) -> datetime:
    return datetime.strptime(ts_str, '%Y%m%d%H%M%S')


def backfill_user(user_id: int) -> dict:
    blobs = list_user_blobs(user_id)
    if not blobs:
        return {'user_id': user_id, 'inserted': 0, 'skipped_live': 0, 'duplicate': 0}

    with db_cursor() as cur:
        cur.execute('SELECT current_image_url FROM pilgrim.robot WHERE user_id = %s', (user_id,))
        row = cur.fetchone()
        live_url = row['current_image_url'] if row else None

        cur.execute('SELECT image_url FROM pilgrim.robot_history WHERE user_id = %s', (user_id,))
        already = {r['image_url'] for r in (cur.fetchall() or [])}

    inserted = 0
    skipped_live = 0
    duplicate = 0
    with db_cursor(commit=True) as cur:
        for ts_str, url in blobs:
            if url == live_url:
                skipped_live += 1
                continue
            if url in already:
                duplicate += 1
                continue
            cur.execute(
                """
                INSERT INTO pilgrim.robot_history
                    (user_id, image_url, video_url, kind, snapshot_at)
                VALUES (%s, %s, NULL, %s, %s)
                """,
                (user_id, url, 'historical_image', parse_ts(ts_str)),
            )
            inserted += 1
    return {'user_id': user_id, 'inserted': inserted, 'skipped_live': skipped_live, 'duplicate': duplicate}


if __name__ == '__main__':
    targets = [45, 112]
    for uid in targets:
        result = backfill_user(uid)
        print(f"user {result['user_id']}: inserted={result['inserted']} "
              f"skipped_live={result['skipped_live']} duplicate={result['duplicate']}")
