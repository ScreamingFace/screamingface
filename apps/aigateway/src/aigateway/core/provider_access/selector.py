"""`Selector` — the one interpretation point for the `X-Profile` header (OME-1200, spec §3.6).

# INVARIANT: absent, blank and whitespace-only headers all mean the implicit default and are
# NOT explicit; any other value is refused here, at the parse step, so no implementation ever
# sees a named selector (Stage D sunset; the compatibility-window policy retired in the OME-1138
# close-out, L4a).
# WHY HTTP routes reach this parser through ``selector_from_request``: it inspects every repeated
# header field, so a blank first field cannot hide a named later one.
"""

from __future__ import annotations

from dataclasses import dataclass

from .types import SelectorUnsupported

DEFAULT_SELECTOR_NAME = "default"


@dataclass(frozen=True)
class Selector:
    """Which stored target the caller asked for — since the Stage D sunset, only the default.

    # WHY the value stays: it is the port's resolve argument, so the port signature and its
    # consumers are unchanged; `from_header` is the only way a request produces one.
    """

    name: str
    explicit: bool

    @property
    def is_default(self) -> bool:
        return self.name == DEFAULT_SELECTOR_NAME

    @classmethod
    def from_header(cls, raw: str | None) -> Selector:
        if (raw or "").strip():
            # WHY a literal `default` is refused too: admitting it needs the D4 equivalence proof
            # (spec §3.6) — an owner decision, not an implementation default.
            raise SelectorUnsupported()
        return cls(DEFAULT_SELECTOR_NAME, explicit=False)
