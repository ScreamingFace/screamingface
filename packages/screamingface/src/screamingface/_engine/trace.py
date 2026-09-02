"""Client-originated W3C trace context (OME-967).

**WHY the client mints at all.** The trace id used to be minted inside the Runner Job and
never returned, so every failure *before the first frame* — capability mint, run start, WS
handshake — carried no id of any kind and was unjoinable to evidence forever. That class is
a large share of what users actually hit. The Engine already adopts an inbound `traceparent`
and fails soft to minting its own, so originating here is a client-only change.

**WHY this is 20 lines rather than a dependency.** `packages/screamingface` depends on
httpx, pynacl, pyyaml and websockets — not on `url4`, and not on an OTel SDK. Adding a
distribution dependency to the Client to obtain W3C string formatting would be the wrong
trade, so the format is stated here and pinned by tests on both sides.

INVARIANT: the value this produces must satisfy `url4.streaming.trace._TRACEPARENT_RE` —
version `00`, a 32-hex trace id, a 16-hex span id, 2-hex flags, lowercase — and neither id
may be all-zero, which that module rejects. `secrets` makes an all-zero draw a non-issue in
practice, but the shape is the contract, so it is asserted rather than assumed.

AIDEV-NOTE: the sampled flag is `01` to match url4's hardcoded `_SAMPLED`. An inbound `-00`
is re-stamped `-01` there, which is a real W3C deviation — it lives in `packages/url4`, is
pinned by that package's tests, and is deliberately NOT changed from here.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass

_VERSION = "00"
_SAMPLED = "01"
_TRACE_ID_BYTES = 16
_SPAN_ID_BYTES = 8


@dataclass(frozen=True, slots=True)
class TraceContext:
    """One run's trace identity, minted before its first outbound request."""

    trace_id: str
    span_id: str

    @property
    def traceparent(self) -> str:
        return f"{_VERSION}-{self.trace_id}-{self.span_id}-{_SAMPLED}"

    def headers(self) -> dict[str, str]:
        """The header map to merge into every outbound leg of the run."""
        return {"traceparent": self.traceparent}


def new_trace_context() -> TraceContext:
    """Mint a fresh trace identity for one run."""
    return TraceContext(
        trace_id=secrets.token_hex(_TRACE_ID_BYTES),
        span_id=secrets.token_hex(_SPAN_ID_BYTES),
    )


__all__ = ["TraceContext", "new_trace_context"]
