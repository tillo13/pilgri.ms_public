"""Seed variable unlock_radius_km per Origin Site — Signal Phase 2.1.

One-shot migration. Idempotent: re-running produces the same end state.

Thematic assignments:
  Easy (85-100km)     — famous "first" successes that should be broadly detectable
  Standard (42-60km)  — the bulk of successful missions
  Hard   (15-25km)    — lost / crashed missions (require tight approach)

Usage:
    source venv_galactica/bin/activate
    python -m tools.seed_signal_radii
"""

from utilities.postgres.core import db_cursor

RADII = {
    'VIKING-1':     100,
    'PATHFINDER':    85,
    'MARS-2':        45,
    'VIKING-2':      55,
    'OPPORTUNITY':   50,
    'SPIRIT':        50,
    'PHOENIX':       55,
    'CURIOSITY':     55,
    'INSIGHT':       50,
    'PERSEVERANCE':  45,
    'ZHURONG':       42,
    'MARS-3':        15,
    'BEAGLE-2':      20,
    'SCHIAPARELLI':  25,
}


def main():
    with db_cursor() as cur:
        cur.execute("SELECT site_code, unlock_radius_km FROM pilgrim.origin_sites")
        before = {r['site_code']: r['unlock_radius_km'] for r in cur.fetchall()}

        missing = [code for code in RADII if code not in before]
        if missing:
            print(f"WARN: sites in seed dict but not in DB: {missing}")

        extra = [code for code in before if code not in RADII]
        if extra:
            print(f"WARN: sites in DB but not in seed dict: {extra}")

        updated = 0
        for site_code, radius in RADII.items():
            if site_code not in before:
                continue
            if before[site_code] == radius:
                continue
            cur.execute(
                "UPDATE pilgrim.origin_sites SET unlock_radius_km = %s WHERE site_code = %s",
                (radius, site_code)
            )
            print(f"  {site_code:15s} {before[site_code]:>4} → {radius}")
            updated += 1

        print(f"\nUpdated {updated} sites. {len(RADII) - updated} already at target.")


if __name__ == '__main__':
    main()
