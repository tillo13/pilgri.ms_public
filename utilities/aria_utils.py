"""utilities.aria_utils — thin re-export shim.

ARIA was split into utilities/aria/* across Pass A (config + snapshot) and Pass B
(prompts, chat, greetings, conversation, relationship, animations, handlers).
This shim preserves every existing `from utilities.aria_utils import X` caller.
Do not add new logic here — add it to the appropriate submodule.
"""
# noqa: F401,F403 throughout — re-exports intentionally shadow direct imports.
from utilities.aria.config import *  # noqa
from utilities.aria.conversation import *  # noqa
from utilities.aria.relationship import *  # noqa
from utilities.aria.snapshot import *  # noqa
from utilities.aria.prompts import *  # noqa
from utilities.aria.chat import *  # noqa
from utilities.aria.greetings import *  # noqa
from utilities.aria.animations import *  # noqa
from utilities.aria.handlers import *  # noqa

# Explicit re-export for underscore-prefixed names (star-imports skip these).
from utilities.aria.handlers import _build_aria_user_context  # noqa: F401
