"""The W3C trace context of one chat call (contracts C2.1, P8).

FEATURE: SDK model inference. Each chat call sends a new ``traceparent``, so a reply and an error
have a ``trace_id`` that support can find in the Engine logs.

WHY here: ``main`` removed ``_engine/trace.py`` (9c49b846f) when the evaluation client stopped
using it. The chat call is now its only user, so the helper lives next to the call.

INVARIANT: the value has the shape that ``url4.streaming.trace`` accepts: version ``00``, a
32-hex trace id, a 16-hex span id and the flags ``01``, all lowercase. The SDK does not depend on
``url4`` or an OTel SDK, so the format is written here and a test pins it.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass

_VERSION = "00"
# AIDEV-NOTE: 01 (sampled) is the flag that url4 sets on each trace; do not change it here.
_SAMPLED = "01"
_TRACE_ID_BYTES = 16
_SPAN_ID_BYTES = 8


@dataclass(frozen=True, slots=True)
class TraceContext:
    """The trace identity of one try of a chat call."""

    trace_id: str
    span_id: str

    @property
    def traceparent(self) -> str:
        return f"{_VERSION}-{self.trace_id}-{self.span_id}-{_SAMPLED}"

    def headers(self) -> dict[str, str]:
        """The trace header of the request."""
        return {"traceparent": self.traceparent}


def new_trace_context() -> TraceContext:
    """A new trace identity (random ids from ``secrets``)."""
    return TraceContext(
        trace_id=secrets.token_hex(_TRACE_ID_BYTES),
        span_id=secrets.token_hex(_SPAN_ID_BYTES),
    )


__all__ = ["TraceContext", "new_trace_context"]
