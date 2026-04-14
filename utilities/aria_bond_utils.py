"""utilities.aria_bond_utils — thin re-export shim.

Bond detection, fragment processing, and bond-display helpers moved to
utilities/aria/bonds.py in the ARIA consolidation pass. This shim preserves
every `from utilities.aria_bond_utils import X` caller. Do not add new logic
here — add it to utilities/aria/bonds.py.
"""
# noqa: F401,F403 — re-exports intentionally shadow direct imports.
from utilities.aria.bonds import *  # noqa

# Explicit re-exports for underscore-prefixed names (star-imports skip these).
from utilities.aria.bonds import (  # noqa: F401
    _complete_bond,
    _create_bond,
    _generate_bond_image_async,
    _get_commander_name,
    _send_bond_transaction,
)
