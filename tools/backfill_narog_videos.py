"""Match each historical Narog still in robot_history with the closest
videos/user{user_id}_{epoch}.mp4 file within ±5 minutes, then update the
history row's video_url. Pairs assume the video was rendered shortly AFTER
the image (Wan runs against an existing image), so we prefer matches in
the [-1min, +5min] window and pick the absolute closest within that range.

Idempotent — only updates rows where video_url IS NULL.
"""
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utilities.postgres.core import db_cursor

GCS_BUCKET = 'galactica-pilgrim-assets'
GCS_PREFIX = f'https://storage.googleapis.com/{GCS_BUCKET}/'

VIDEO_RE = re.compile(r'/videos/user(\d+)_(\d+)\.mp4$')

WINDOW_BEFORE_SEC = 60      # video can't be more than 1 min BEFORE the image (paranoid; rarely useful)
WINDOW_AFTER_SEC = 300      # video should be within 5 min after


def list_user_videos(user_id: int) -> list[tuple[int, str]]:
    """Returns list of (epoch_seconds, https_url), sorted by epoch."""
    cmd = ['gcloud', 'storage', 'ls', f'gs://{GCS_BUCKET}/videos/user{user_id}_*.mp4']
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    out = (proc.stdout or '') + (proc.stderr or '')
    items = []
    for line in out.strip().split('\n'):
        line = line.strip()
        m = VIDEO_RE.search(line)
        if not m:
            continue
        if int(m.group(1)) != user_id:
            continue
        epoch = int(m.group(2))
        url = line.replace(f'gs://{GCS_BUCKET}/', GCS_PREFIX) if line.startswith('gs://') else line
        items.append((epoch, url))
    items.sort()
    return items


def find_video_for(image_ts: datetime, videos: list[tuple[int, str]]) -> str | None:
    """Closest video within [-WINDOW_BEFORE, +WINDOW_AFTER]. Returns None if
    no video within the window."""
    image_epoch = int(image_ts.replace(tzinfo=timezone.utc).timestamp())
    best = None
    best_dt = None
    for vt, url in videos:
        delta = vt - image_epoch
        if delta < -WINDOW_BEFORE_SEC or delta > WINDOW_AFTER_SEC:
            continue
        # Prefer the closest absolute delta
        adt = abs(delta)
        if best is None or adt < best_dt:
            best = url
            best_dt = adt
    return best


def backfill_user(user_id: int) -> dict:
    videos = list_user_videos(user_id)
    if not videos:
        return {'user_id': user_id, 'matched': 0, 'rows': 0, 'reason': 'no videos in bucket'}

    matched = 0
    rows = 0
    with db_cursor() as cur:
        cur.execute("""
            SELECT id, image_url, snapshot_at
            FROM pilgrim.robot_history
            WHERE user_id = %s AND image_url IS NOT NULL AND video_url IS NULL
        """, (user_id,))
        targets = cur.fetchall() or []

    rows = len(targets)
    with db_cursor(commit=True) as cur:
        for r in targets:
            video_url = find_video_for(r['snapshot_at'], videos)
            if not video_url:
                continue
            cur.execute(
                "UPDATE pilgrim.robot_history SET video_url = %s WHERE id = %s",
                (video_url, r['id']),
            )
            matched += 1
    return {'user_id': user_id, 'matched': matched, 'rows': rows}


if __name__ == '__main__':
    for uid in (45, 112):
        result = backfill_user(uid)
        print(f"user {result['user_id']}: matched {result['matched']}/{result['rows']} history rows with videos")
