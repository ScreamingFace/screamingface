"""The ONE canonical form every cache key in this app hashes through (OME-1044).

FEATURE: more than one cache lane now keys requests — the OME-305 global chat cache and
the OME-1043 Tavily retrieval cache. Both must turn their key material into bytes the
SAME way, or the two lanes silently disagree about what a given request keys to.

WHY this is a module and not four inlined `json.dumps` options: a second spelling of the
canonical form is not a style question, it is a defect that cannot be seen. The
out-of-repo DRACO backfill tool hand-rolled this form, escaped U+2028 where the gateway
did not, and every row it wrote was keyed to a hash nothing would ever look up — no
exception, no red test, just a cache that never hit.

INVARIANT: every exported entry point runs the json-safety guard. There is deliberately
no way to reach the formatter without it, because the guard is what stops two DIFFERENT
requests from collapsing onto one entry (see `_require_json_safe`).

AIDEV-NOTE: this module has no dependency on anything else in the package — that is the
point. A lane, or an out-of-repo tool that needs to compute a key, imports this and
nothing else. Keep it that way; if it ever needs a sibling import, the shared rule has
leaked back into one of its consumers.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from typing import Any, Final

__all__ = ["CanonicalizationError", "canonical_digest", "canonical_material"]

# Bounded recursion: a JSON body cannot be cyclic, but a provider projection is
# ordinary Python and could hand back something self-referential. Cap the walk so
# a buggy plugin costs a bypass instead of a recursion crash on the request path.
_MAX_DEPTH: Final = 64


class CanonicalizationError(ValueError):
    """Key material cannot be canonicalized to one deterministic byte string."""


def _canonical_json(value: Any) -> str:
    # INVARIANT: the exact canonical form (OME-305 plan §2.5). ``sort_keys`` makes object
    # key order irrelevant while arrays keep theirs; ``separators`` removes
    # insignificant whitespace; ``ensure_ascii=False`` keeps prompt text byte-exact
    # rather than escaping it; ``allow_nan=False`` refuses the non-JSON literals.
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _require_json_safe(value: Any, *, depth: int) -> None:
    """Reject anything ``json.dumps`` would coerce, reorder or refuse.

    WHY this exists on top of ``allow_nan=False``: ``json.dumps`` silently COERCES
    a non-string object key, so ``{1: "a"}`` and ``{"1": "a"}`` would canonicalize
    to the same bytes and share one cache entry. A wrong hit is the one failure
    mode this cache may never have, so anything ambiguous is refused instead.
    """
    if depth > _MAX_DEPTH:
        raise CanonicalizationError("key material is nested too deeply")
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CanonicalizationError("key material holds a non-finite number")
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _require_json_safe(item, depth=depth + 1)
        return
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise CanonicalizationError("key material holds a non-string object key")
            _require_json_safe(nested, depth=depth + 1)
        return
    # Type NAME only — never the value, which could be prompt text or a secret.
    raise CanonicalizationError(f"key material holds an unsupported type: {type(value).__name__}")


def canonical_material(mapping: Mapping[str, Any]) -> str:
    """The exact byte string a lane's key material hashes to.

    INVARIANT: in-memory only. Never logged, never persisted, never returned to a
    caller — it contains caller text verbatim. Public for tests and diagnostics, which
    is why it is guarded rather than hidden.

    Raises:
        CanonicalizationError: the mapping is not representable as one deterministic
            byte string.
    """
    _require_json_safe(mapping, depth=0)
    return _canonical_json(mapping)


def canonical_digest(mapping: Mapping[str, Any]) -> str:
    """The cache-key hash for one lane's already-assembled key mapping.

    This is the entry point a lane should use. The lane owns its own closed member set
    and passes it in; this function owns the bytes.

    INVARIANT: returns the DIGEST only, so the verbatim material cannot escape through
    this path.

    Raises:
        CanonicalizationError: as `canonical_material`.
    """
    return _sha256(canonical_material(mapping))
