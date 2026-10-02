"""The control plane's accept span: the run-submission route, as a span (OME-1218).

FEATURE (OME-1218): before this, `GET /` adopted the inbound `traceparent` and forwarded it
verbatim, emitting nothing of its own. Accept, validate, enqueue and queue wait were invisible,
and a run submitted with no inbound context had `url4.run` as an orphan root.

WHY the run is handed THIS span's id (owner decision 2026-10-01, option 1): `url4.run` becomes
a CHILD of the accept span, so one run is one trace with one root, and queue wait is the gap
between the accept span's end and `url4.run`'s start. The same rule as `OME-1185` one hop
further down: each hop names the span that is actually current, never an ancestor of it.

WHY hand-built ids, as in `tracing.otlp`: the id must be known BEFORE the span ends — it is
rendered into the traceparent the run is scheduled with — and it must be the id the sink later
exports. Minting it here and handing it to the `SpanSink` port gives both by construction.

LAYERING: pure — stdlib, `span_tree.Span` and `url4.streaming.trace`. No OTel (that stays in
`tracing.otlp`) and nothing from the control plane, so this stays a shared leaf.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from screamingface_engine.tracing.relay import SpanSink
from screamingface_engine.tracing.span_tree import AttributeValue, Span, identity_of
from url4.streaming.trace import format_traceparent

logger = logging.getLogger(__name__)

ACCEPT_SPAN_NAME = "url4.accept"
"""What an operator sees at the top of a run's waterfall, directly above `url4.run`."""

_ROUTE = "/"
_METHOD = "GET"


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class AcceptSpan:
    """One submission's server span: opened at handler entry, ended once at enqueue or refusal.

    INVARIANT: ends at most once. The sync path ends it right after enqueue and then holds the
    request for the run's outcome; the handler's exit must not emit a second, longer copy.
    INVARIANT: never raises out of `scheduled`/`refused` — a telemetry fault must not turn an
    accepted run into a 500 (the relay's invariant, at the other end of the same trace).
    """

    sink: SpanSink
    trace_id: str
    span_id: str
    parent_span_id: str | None
    topic: str
    start_time: datetime
    clock: Callable[[], datetime] = field(default=_now, repr=False)
    _ended: bool = field(default=False, repr=False)

    @classmethod
    def open(
        cls,
        sink: SpanSink,
        inbound_traceparent: str | None,
        *,
        topic: str,
        clock: Callable[[], datetime] = _now,
    ) -> AcceptSpan:
        """Start the span: a child of the inbound context when it is usable, else a new root.

        An unusable inbound header (malformed, all-zero) is ABSENT — the W3C "restart" rule the
        route already applies. Adopting its trace id while dropping its parent would join a
        trace on the strength of a header that was not valid.
        """
        identity = identity_of(inbound_traceparent)
        trace_id, parent = identity if identity is not None else (secrets.token_hex(16), None)
        return cls(
            sink=sink,
            trace_id=trace_id,
            span_id=secrets.token_hex(8),
            parent_span_id=parent,
            topic=topic,
            start_time=clock(),
            clock=clock,
        )

    @property
    def traceparent(self) -> str:
        """The traceparent the run is scheduled with: it names THIS span (option 1)."""
        return format_traceparent(self.trace_id, self.span_id)

    def scheduled(self) -> None:
        """The run is enqueued: the accept is over, whatever the run does next."""
        self._end("ok", {"url4.accept.outcome": "scheduled"})

    def refused(self, http_status: int) -> None:
        """The submission was answered with an error before (or instead of) enqueueing.

        WHY a 4xx is not an error status: OTel's HTTP server semconv — a client error is the
        caller's, and marking it here would page on every duplicate submission.
        """
        status = "error" if http_status >= 500 else "ok"
        self._end(
            status,
            {"url4.accept.outcome": "refused", "http.response.status_code": http_status},
        )

    def _end(self, status: str, extra: dict[str, AttributeValue]) -> None:
        if self._ended:
            return
        self._ended = True
        span = Span(
            trace_id=self.trace_id,
            span_id=self.span_id,
            parent_span_id=self.parent_span_id,
            name=ACCEPT_SPAN_NAME,
            operation="accept",
            start_time=self.start_time,
            end_time=self.clock(),
            status=status,
            kind="server",
            attributes={
                "http.request.method": _METHOD,
                "http.route": _ROUTE,
                "url4.topic": self.topic,
                **extra,
            },
        )
        try:
            self.sink.emit(span)
        except Exception:
            # WHY broad: see the class INVARIANT — the submission is worth more than its span.
            logger.warning("could not export the accept span topic=%s", self.topic, exc_info=True)


__all__ = ["ACCEPT_SPAN_NAME", "AcceptSpan"]
