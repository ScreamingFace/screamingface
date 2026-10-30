"""The state a test seeds a stored credential in (OME-1138 Stage E, E5c).

# FEATURE: Stage E history cleanup — the gateway no longer ships the Profile model, so the tests
# that seed "a stored credential named `name` in `state`" name that state themselves. On the real
# app the seed is an effective Connection in the status the state maps to (`migrated_pair_seed.py`);
# on the port fake it is the fake's own record (`provider_access_fake.py`).
# INVARIANT: the values are the ones the retired `ProfileState` carried, so an observation that
# reports a state (`credential_state()`) still compares equal to the same strings.
"""

from __future__ import annotations

from enum import Enum


# WHY the str mixin over `StrEnum`: it keeps the exact `str()`/`format()` behaviour of the enum it
# replaces, so no seeded value renders differently.
class SeedState(str, Enum):  # noqa: UP042
    PENDING = "pending"
    AUTHENTICATED = "authenticated"
    ERROR = "error"


__all__ = ["SeedState"]
