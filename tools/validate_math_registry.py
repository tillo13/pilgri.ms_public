"""Validate math_registry.json constants against actual source code.

Checks that key numeric constants in the registry match the real values
in Python source files. Warns (does not block) if any have drifted.

Usage:
    python tools/validate_math_registry.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

REGISTRY_PATH = os.path.join(os.path.dirname(__file__), '..', 'math_registry.json')


def validate():
    """Returns list of (constant_name, expected, actual) mismatches."""
    if not os.path.exists(REGISTRY_PATH):
        return [("math_registry.json", "exists", "MISSING")]

    with open(REGISTRY_PATH) as f:
        registry = json.load(f)

    constants = registry.get('constants', {})
    mismatches = []

    # Check expedition constants
    try:
        from utilities.expedition_utils import BASE_SPEED_KM_PER_HOUR, BASE_COST_PER_KM, LIFE_SUPPORT_PER_DAY, EVA_HOURS_PER_DAY
        checks = {
            'BASE_SPEED_KM_PER_HOUR': (BASE_SPEED_KM_PER_HOUR, constants.get('BASE_SPEED_KM_PER_HOUR', {}).get('value')),
            'BASE_COST_PER_KM': (BASE_COST_PER_KM, constants.get('BASE_COST_PER_KM', {}).get('value')),
            'LIFE_SUPPORT_PER_DAY': (LIFE_SUPPORT_PER_DAY, constants.get('LIFE_SUPPORT_PER_DAY', {}).get('value')),
            'EVA_HOURS_PER_DAY': (EVA_HOURS_PER_DAY, constants.get('EVA_HOURS_PER_DAY', {}).get('value')),
        }
        for name, (actual, expected) in checks.items():
            if expected is not None and actual != expected:
                mismatches.append((name, expected, actual))
    except ImportError as e:
        mismatches.append(("expedition_utils import", "success", str(e)))

    # Check discovery constants (EXTRACTION_SV_BONUS_RATE is module-level, PAYOUT_MULTIPLIERS is local)
    try:
        from utilities.discovery_utils import EXTRACTION_SV_BONUS_RATE
        if EXTRACTION_SV_BONUS_RATE != constants.get('EXTRACTION_SV_BONUS_RATE', {}).get('value'):
            mismatches.append(('EXTRACTION_SV_BONUS_RATE', constants['EXTRACTION_SV_BONUS_RATE']['value'], EXTRACTION_SV_BONUS_RATE))
    except ImportError as e:
        mismatches.append(("discovery_utils import", "success", str(e)))

    # Check crew XP
    try:
        reg_xp = constants.get('CREW_XP_PER_MISSION', {}).get('value')
        if reg_xp is not None:
            # XP is hardcoded as 5 in db_trails.py — just verify registry says 5
            if reg_xp != 5:
                mismatches.append(('CREW_XP_PER_MISSION', reg_xp, 5))
    except Exception:
        pass

    return mismatches


if __name__ == '__main__':
    mismatches = validate()
    if mismatches:
        print("math_registry.json validation WARNINGS:")
        for name, expected, actual in mismatches:
            print(f"  {name}: registry says {expected}, code says {actual}")
        sys.exit(1)
    else:
        print("math_registry.json: all constants match source code")
        sys.exit(0)
