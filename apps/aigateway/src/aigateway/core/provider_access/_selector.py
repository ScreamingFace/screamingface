"""`Selector` — the one interpretation point for the `X-Profile` header (OME-1200, spec §3.6).

# INVARIANT: absent, blank and whitespace-only headers all mean the implicit default and are
# NOT explicit; anything else is the stripped value and explicit. The Stage D sunset policy is
# applied HERE, at the parse step, so no implementation ever consults it.
# AIDEV-NOTE: routes still build the string (`(header or "default").strip() or "default"`) and
# the shims re-parse it; A2 moves the parse to the route boundary and deletes that string.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ._types import SelectorUnsupported

DEFAULT_SELECTOR_NAME = "default"


class SelectorPolicy(Enum):
    """HONOUR is the compatibility-window default; REJECT_EXPLICIT is the Stage D sunset."""

    HONOUR = "honour"
    REJECT_EXPLICIT = "reject_explicit"


@dataclass(frozen=True)
class Selector:
    """Which stored target the caller asked for: a name, and whether they said it."""

    name: str
    explicit: bool

    @property
    def is_default(self) -> bool:
        return self.name == DEFAULT_SELECTOR_NAME

    @classmethod
    def from_header(
        cls, raw: str | None, *, policy: SelectorPolicy = SelectorPolicy.HONOUR
    ) -> Selector:
        stripped = (raw or "").strip()
        if not stripped:
            return cls(DEFAULT_SELECTOR_NAME, explicit=False)
        if policy is SelectorPolicy.REJECT_EXPLICIT:
            # WHY a literal `default` is refused too: admitting it needs the D4 equivalence proof
            # (spec §3.6) — an owner decision, not an implementation default.
            raise SelectorUnsupported(stripped)
        return cls(stripped, explicit=True)
