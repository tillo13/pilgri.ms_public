#!/usr/bin/env python3
"""
Persist an APPROVED proof ladder (from tools/gen_proof_ladder.py) to GCS + the
upgrade_images DB table. Run ONLY after Andy has eyeballed the montage and approved.

Uploads /tmp/proof_ladder/<category>_<item>/lv{from+1..to}.png to GCS and upserts the
URLs into pilgrim.upgrade_images (PRIMARY KEY category,item_key,level — old art is
overwritten in the DB but old GCS files remain = reversible). The anchor (from level)
is skipped — it's the un-regenerated base.

Usage:
    python tools/persist_proof_ladder.py --category vehicles --item drone --from 1 --to 10
"""
import sys
import os
import argparse
import logging
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def main():
    ap = argparse.ArgumentParser(description='Persist an approved proof ladder to GCS + DB')
    ap.add_argument('--category', required=True)
    ap.add_argument('--item', required=True)
    ap.add_argument('--from', dest='from_lv', type=int, default=1)
    ap.add_argument('--to', dest='to_lv', type=int, default=10)
    args = ap.parse_args()

    from utilities.google_cloud_storage_utils import upload_blob_from_bytes
    from utilities.upgrade_image_utils import _store_generated_image_url

    outdir = f"/tmp/proof_ladder/{args.category}_{args.item}"
    if not os.path.isdir(outdir):
        print(f"ERROR: no proof ladder at {outdir} — run tools/gen_proof_ladder.py first")
        return 1

    persisted = 0
    for lv in range(args.from_lv + 1, args.to_lv + 1):  # skip the anchor (from_lv)
        path = f"{outdir}/lv{lv}.png"
        if not os.path.exists(path):
            print(f"  Lv{lv}: missing {path} — skipping")
            continue
        with open(path, 'rb') as f:
            data = f.read()
        blob = f"upgrades/{args.category}_{args.item}_lv{lv}_{int(time.time())}.png"
        url = upload_blob_from_bytes(data, blob, 'image/png')
        _store_generated_image_url(args.category, args.item, lv, url)
        print(f"  persisted {args.category}/{args.item} Lv{lv} -> {url}")
        persisted += 1
        time.sleep(0.3)

    print(f"\nDone — persisted {persisted} levels for {args.category}/{args.item}.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
