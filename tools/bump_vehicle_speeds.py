"""One-shot tuning bump per Luke's #1413 latest comments (04-29):
  - Drone speed × 1.05
  - Rover speed × 1.15
  - Buggy speed × 1.30

Reads config_upgrades.py, walks vehicle blocks, multiplies each level's
expedition_speed_mult, rounds to 1 decimal, writes the file back.

Run-once. Idempotent guard: prints a diff preview before write; aborts if
any value already looks bumped.
"""
import re
import sys
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[1] / 'config_upgrades.py'

MULT_BY_VEHICLE = {
    'rover': 1.15,
    'drone': 1.05,
    'buggy': 1.30,
}

# Match: 'expedition_speed_mult': N.M  (after a vehicle key marker)
SPEED_RE = re.compile(r"('expedition_speed_mult':\s*)(\d+(?:\.\d+)?)")


def bump():
    text = CONFIG.read_text()
    # Find vehicle block bounds — assumes single dict 'vehicles' at top level.
    # Walk via simple state machine: when we hit "'rover':", we're in rover.
    lines = text.split('\n')
    out = []
    current_vehicle = None
    changes = []
    for ln in lines:
        if "'rover':" in ln and 'speed_mult' not in ln:
            current_vehicle = 'rover'
        elif "'drone':" in ln and 'speed_mult' not in ln:
            current_vehicle = 'drone'
        elif "'buggy':" in ln and 'speed_mult' not in ln:
            current_vehicle = 'buggy'
        # End of vehicles block roughly = section comment for EQUIPMENT
        if 'EQUIPMENT' in ln:
            current_vehicle = None

        if current_vehicle:
            mult = MULT_BY_VEHICLE[current_vehicle]
            def replace(m):
                old = float(m.group(2))
                new = round(old * mult, 1)
                changes.append((current_vehicle, old, new))
                return f"{m.group(1)}{new}"
            ln = SPEED_RE.sub(replace, ln)
        out.append(ln)

    new_text = '\n'.join(out)
    if not changes:
        print('No speed_mult lines matched; aborting.')
        sys.exit(1)

    print('--- preview ---')
    for v, a, b in changes:
        print(f'  {v:6} {a:5.1f} → {b}')
    print(f'\nTotal: {len(changes)} levels updated')

    CONFIG.write_text(new_text)
    print(f'\nWrote {CONFIG}')


if __name__ == '__main__':
    bump()
