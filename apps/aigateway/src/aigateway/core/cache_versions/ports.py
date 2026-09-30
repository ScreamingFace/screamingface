"""The capture ports and value types (OME-1307, GW-capture).

FEATURE: OME-1307 (E14) - one traced chat call becomes one capture record that a sink stores.

INVARIANT: this module is a LEAF. It imports no Tortoise and nothing from ``plugins`` or ``routes``,
so the chat route and later units depend on the port and never on the adapter (contract C11 row 4).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal, Protocol, get_args

CaptureOutcome = Literal["hit", "stored", "unstored", "bypass", "version_hit", "error"]
CAPTURE_OUTCOMES: Final[frozenset[str]] = frozenset(get_args(CaptureOutcome))
# INVARIANT (CV-D8): only these outcomes keep the served body inline in the index row.
INLINE_OUTCOMES: Final[frozenset[str]] = frozenset({"unstored", "bypass", "version_hit"})


@dataclass(frozen=True, slots=True)
class CaptureKey:
    """The capture key of one call: the global cache key hash and its canonical material."""

    key_hash: str  # 64 lowercase hex; equals the global cache key for the same body
    material: str  # the canonical key material (prompt text). Never logged. Never in a repr.

    def __repr__(self) -> str:
        # INVARIANT: the material holds the prompt verbatim, so a repr shows a hash prefix only.
        return f"CaptureKey(key_hash={self.key_hash[:12]}…)"


@dataclass(frozen=True, slots=True)
class CaptureRecord:
    account_id: str
    trace_id: str  # 32 lowercase hex
    outcome: CaptureOutcome
    key_hash: str | None  # None only when the call has no capture key
    request_material: str | None  # None exactly when key_hash is None
    response_json: str | None  # compact JSON text; set only for INLINE_OUTCOMES with a key


class CaptureSink(Protocol):
    async def record(self, record: CaptureRecord) -> None:
        """Store one record. May raise; the route helper owns the never-raise rule."""
        ...
