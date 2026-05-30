#!/usr/bin/env python3
"""
Generate a PROOF ladder (no persist) of an upgrade/infra item across levels, then
build a montage so Andy can eyeball the per-level progression in Chrome BEFORE we
commit any art to the DB. This is the #1489 workflow gate:

    generate -> Chrome montage -> Andy approves -> persist (separately)

It chains each level off the previous one's image via the locked get_kontext_prompt_for_level
prompt and the FREE kumori edit cascade. Nothing is written to pilgrim.upgrade_images or
linked in the DB — outputs land in /tmp only. Bounded retry rides kumori.ai's transient
SSL/503 blips (the #1489 plan mandates this).

Usage:
    python tools/gen_proof_ladder.py --category vehicles --item drone            # Lv1..10
    python tools/gen_proof_ladder.py --category vehicles --item drone --to 10 --from 1
    python tools/gen_proof_ladder.py --category infrastructure --item solar_array --from 7 --to 9
"""
import sys
import os
import argparse
import logging
import time
import urllib.request
from io import BytesIO

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def _init_kumori():
    from utilities.kumori_utils import init_kumori
    from utilities.google_auth_utils import get_secret
    init_kumori(
        get_secret_fn=lambda name: get_secret(name, project_id='kumori-404602'),
        api_key_name='PILGRIMS_KUMORI_API_KEY',
    )


def _pool_status(label):
    """Print the REAL kumori budget — the Cloudflare 10K-neuron/day shared pool, not
    an image count. (#1489: the "~90 images/day" was always an estimate; the actual
    constraint is neurons, which vary per call by model + output size.) live_state comes
    from a real-time inference probe and is authoritative; cf_neurons_today (CF GraphQL)
    lags hours during a burst, so treat it as a floor."""
    try:
        from utilities.kumori_api_client import imggen_usage
        cf = (imggen_usage(limit=1) or {}).get('cf_reconciliation', {}) or {}
        used = cf.get('cf_neurons_today') or 0
        print(f"[neuron pool {label}] CF ~{used:.0f}/10000 ({used/100:.0f}%+, LAGS hrs) | "
              f"live_state={cf.get('live_state')} | resets in {cf.get('reset_in_human')}")
    except Exception as e:
        print(f"[neuron pool {label}] unavailable: {str(e)[:80]}")


def _load_bytes(src):
    if src.startswith(('http://', 'https://')):
        return urllib.request.urlopen(src, timeout=30).read()
    with open(src, 'rb') as f:
        return f.read()


def main():
    ap = argparse.ArgumentParser(description='Proof-ladder generator (no persist) + montage')
    ap.add_argument('--category', required=True)
    ap.add_argument('--item', required=True)
    ap.add_argument('--from', dest='from_lv', type=int, default=1, help='base anchor level (not regenerated)')
    ap.add_argument('--to', dest='to_lv', type=int, default=10)
    args = ap.parse_args()

    from utilities.upgrade_image_utils import get_best_available_image, get_kontext_prompt_for_level
    from utilities.kumori_utils import kumori_klein_edit, KumoriAPIError
    from PIL import Image, ImageDraw

    _init_kumori()
    _pool_status("before")

    outdir = f"/tmp/proof_ladder/{args.category}_{args.item}"
    os.makedirs(outdir, exist_ok=True)

    # Anchor: the from-level image (kept, not regenerated).
    base_url = get_best_available_image(args.category, args.item, args.from_lv)
    if not base_url:
        print(f"ERROR: no base image for {args.category}/{args.item} Lv{args.from_lv}")
        return 1
    levels = {args.from_lv: _load_bytes(base_url)}
    with open(f"{outdir}/lv{args.from_lv}.png", 'wb') as f:
        f.write(levels[args.from_lv])
    print(f"anchor Lv{args.from_lv}: {base_url}")

    prev_path = f"{outdir}/lv{args.from_lv}.png"
    for lv in range(args.from_lv + 1, args.to_lv + 1):
        prompt = get_kontext_prompt_for_level(args.category, args.item, lv)
        print(f"\n[Lv{lv}] {prompt[:110]}...")
        res = None
        for attempt in range(1, 6):
            try:
                res = kumori_klein_edit(
                    prompt=prompt, target_image=prev_path, preset='square_hero',
                    app_name='galactica_proof_ladder', character=f'{args.category}_{args.item}',
                    ref_filename=f'lv{lv}', feature='upgrade_image.proof', verbiage=prompt[:500],
                    tags={'category': args.category, 'item_key': args.item, 'level': lv, 'proof': True},
                )
                break
            except KumoriAPIError as e:
                print(f"    attempt {attempt} failed ({str(e)[:80]}), retrying in 12s..." if attempt < 5
                      else f"    attempt {attempt} failed; giving up on Lv{lv}")
                if attempt < 5:
                    time.sleep(12)
        if not res:
            print(f"    Lv{lv} FAILED after 5 attempts — stopping ladder here.")
            break
        levels[lv] = res['image_bytes']
        path = f"{outdir}/lv{lv}.png"
        with open(path, 'wb') as f:
            f.write(res['image_bytes'])
        print(f"    -> Lv{lv} OK via {res.get('provider')} ({len(res['image_bytes'])//1024}KB)")
        prev_path = path
        time.sleep(1)

    # Montage: scaled tiles in a grid with level labels.
    keys = sorted(levels)
    tile = 280
    cols = min(5, len(keys))
    rows = (len(keys) + cols - 1) // cols
    canvas = Image.new('RGB', (cols * tile, rows * (tile + 24)), (18, 12, 10))
    draw = ImageDraw.Draw(canvas)
    for i, lv in enumerate(keys):
        im = Image.open(BytesIO(levels[lv])).convert('RGB').resize((tile, tile), Image.LANCZOS)
        x, y = (i % cols) * tile, (i // cols) * (tile + 24)
        canvas.paste(im, (x, y + 24))
        draw.text((x + 6, y + 6), f"Lv{lv}", fill=(255, 220, 120))
    montage = f"{outdir}/montage.png"
    canvas.save(montage)
    print(f"\nMONTAGE: {montage}  ({len(keys)} levels: {keys})")
    print("Proof only — nothing persisted to the DB.")
    _pool_status("after")
    return 0


if __name__ == '__main__':
    sys.exit(main())
