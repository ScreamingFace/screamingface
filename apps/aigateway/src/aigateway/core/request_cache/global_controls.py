"""OME-305 per-request controls for the global exact-request cache.

FEATURE: one global exact-request cache that is ON by default. An ordinary request
participates, and the control object exists only to OPT OUT.

INVARIANT: the grammar is CLOSED and fail-safe. Exactly two fields are understood
(``use-cache`` and ``attempt``); every other field — unsupported controls and anything
unrecognized — makes the request bypass entirely rather than being ignored. A
caller who asks for a per-request TTL must not silently receive a permanent
global entry instead.

INVARIANT: ``cache`` is removed from the body UNCONDITIONALLY, including when it
is malformed, so a gateway control object can never reach a provider as if it
were a model parameter.

FEATURE (OME-1458): ``attempt`` lets a caller ask the same question several times on purpose.
A Benchmark that gives each Case N Attempts sends Attempt 2..N with ``{"attempt": i}``: the
reply is stored under the request PLUS that number, so Attempt 2 is never served Attempt 1's
reply, and a rerun of the same Attempt is served its own. Attempt 1 is spelled by absence —
``{"attempt": 1}`` is malformed — so one request can never key two entries.

AIDEV-NOTE: the operator gate is separate and unchanged — ``request_cache_enabled``
still defaults to ``False`` in code and is turned on deliberately in hosted
config. This module decides only what the CALLER asked for.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

CONTROL_FIELD: Final = "cache"
USE_CACHE_FIELD: Final = "use-cache"
ATTEMPT_FIELD: Final = "attempt"
UNDERSTOOD_CONTROL_FIELDS: Final[frozenset[str]] = frozenset({USE_CACHE_FIELD, ATTEMPT_FIELD})
# Attempt 1 is the request with no number; the first number a caller may send is 2.
FIRST_NUMBERED_ATTEMPT: Final = 2

# Controls this cache deliberately does not offer. Bypassing is the only honest answer when a
# caller asks for a per-request TTL or one-way read/write behavior.
UNSUPPORTED_CONTROL_FIELDS: Final[frozenset[str]] = frozenset(
    {"ttl", "s-maxage", "no-cache", "no-store"}
)

BYPASS_OPTED_OUT: Final = "opted_out"
BYPASS_MALFORMED_CONTROLS: Final = "malformed_controls"
BYPASS_UNSUPPORTED_CONTROL: Final = "unsupported_control"


@dataclass(frozen=True)
class GlobalCacheControls:
    """What the caller asked of the cache for THIS request.

    ``participate`` means both directions: read the global cache, and store a
    successful response in it. There is no read-only or write-only lane — a caller
    that wants neither opts out, and there is nothing else to express.
    """

    participate: bool
    bypass_reason: str = ""
    # The caller's Attempt number (2 or more), keyed beside the request; None for Attempt 1
    # and for every ordinary request, which key exactly as before (OME-1458).
    attempt: int | None = None


_PARTICIPATE: Final = GlobalCacheControls(participate=True)


def _refuse(reason: str) -> GlobalCacheControls:
    return GlobalCacheControls(participate=False, bypass_reason=reason)


def parse_global_cache_controls(body: dict[str, Any]) -> GlobalCacheControls:
    """Pop and interpret the ``cache`` control object.

    Absent, ``null`` or an empty object all state nothing, so the default applies
    and the request participates.
    """
    raw = body.pop(CONTROL_FIELD, None)
    if raw is None:
        return _PARTICIPATE
    if not isinstance(raw, Mapping):
        return _refuse(BYPASS_MALFORMED_CONTROLS)
    if set(raw) - UNDERSTOOD_CONTROL_FIELDS:
        # INVARIANT: an unsupported field wins over a present ``use-cache: true``.
        # The caller asked for something this cache cannot honor; serving them a
        # global entry anyway would answer a different question than they asked.
        return _refuse(BYPASS_UNSUPPORTED_CONTROL)
    attempt: int | None | GlobalCacheControls = _attempt(raw)
    if isinstance(attempt, GlobalCacheControls):
        return attempt
    requested = raw.get(USE_CACHE_FIELD, True)
    if not isinstance(requested, bool):
        return _refuse(BYPASS_MALFORMED_CONTROLS)
    if not requested:
        return _refuse(BYPASS_OPTED_OUT)
    if attempt is None:
        return _PARTICIPATE
    return GlobalCacheControls(participate=True, attempt=attempt)


def _attempt(raw: Mapping[str, Any]) -> int | None | GlobalCacheControls:
    """The caller's Attempt number, None when absent, or the refusal for a malformed one.

    WHY a whole number of at least 2, and no bool: ``True`` is an ``int`` in Python and
    ``2.0`` hashes like ``2``, so either would let two spellings share or split one entry.
    """

    if ATTEMPT_FIELD not in raw:
        return None
    value: object = raw[ATTEMPT_FIELD]
    if isinstance(value, bool) or not isinstance(value, int) or value < FIRST_NUMBERED_ATTEMPT:
        return _refuse(BYPASS_MALFORMED_CONTROLS)
    return value
