"""The pre-cache defaults read of the Profile-backed implementation (OME-1200, op 1).

Relocated from `routes/chat_profile_defaults.py::profile_defaults_for_key`; that module keeps
its name and delegates here through `ProfileBackedProviderAccess.defaults_for`.

# FEATURE: one globally shared exact-request cache, keyed on the EFFECTIVE request (OME-305
# ruling 57) — stored defaults must enter the key, so they are read BEFORE any credential.
"""

from __future__ import annotations

import logging

from ..profile_index import ProfileIndexStore
from ._selector import Selector
from ._types import RequestDefaults

logger = logging.getLogger(__name__)


async def read_defaults(
    index: ProfileIndexStore, account_id: str, provider: str, selector: Selector
) -> RequestDefaults | None:
    """Read ONLY this caller's stored defaults, before any credential is resolved.

    # INVARIANT: never raises, and never inspects the profile's state. `resolve` refuses an
    # absent, PENDING or ERRORED target; put any of those ahead of the cache lookup and a
    # request the cache could have SERVED would be REFUSED instead. So this read also resolves
    # no Connection and consults no chatless allowance — `resolve` still does all of that.
    # INVARIANT: `None` means the index could not be READ — never "no defaults", which is an
    # empty `RequestDefaults`. Carrying on with empty defaults after a failed read would key the
    # bare body and manufacture precisely the wrong-hit class ruling 57 closes.
    """
    try:
        profile = await index.get(account_id, provider, selector.name)
    except Exception:
        # WHY the broad catch: this is a fail-safe boundary, not error handling. The index read
        # decrypts and validates a stored blob, so its failure modes are open-ended, and every
        # one of them must degrade to "do not use the cache" rather than fail a request the
        # provider can serve. Nothing is swallowed: the failure is logged and the return value
        # forces the caller to bypass.
        logger.warning("profile index unreadable before the cache stage; bypassing the cache")
        return None
    return RequestDefaults() if profile is None else profile.defaults
