"""The publisher proxy that ships a run's spans to a tracing backend (OME-1130).

MOUNT POINT. `OME-1130` specifies "the engine control-plane relay, never the runner". That
subscription does not exist: `stream_for(topic)` creates ONE JetStream stream per run, so
nothing in the control plane sees all runs — only `ws/bridge.py` subscribes, and only for runs
somebody is watching. Exporting from there would reproduce the "absent because not exercised"
ambiguity that cost a real diagnosis in `OME-940`. The owner resolved the fork in favour of a
PUBLISHER PROXY: the run's own publisher, wrapped, which sees every frame of every run whether
or not a client is attached.

INVARIANT — THE RELAY MAY NEVER FAIL OR ALTER A RUN. It sits on the one path every frame
travels, so a downed collector, an unmapped frame, or a bug in this module must degrade
telemetry and nothing else. Every call into the sink is therefore wrapped, and the frame
reaches the inner publisher whatever happened. `Exception` is caught deliberately broadly here:
the specific-exceptions rule exists so failures surface, and this is the one place where a
surfaced failure is strictly worse than a swallowed one — the alternative to swallowing is
turning a telemetry outage into a fleet of failed runs.

LAYERING: this module defines the PORT (:class:`SpanSink`) and imports no transport. The OTel
adapter lives in :mod:`screamingface_engine.tracing.otlp` and is wired by the composition root,
so the engine's `opentelemetry` import stays confined to one module and the relay's whole
behaviour is testable with a fake.
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Mapping
from datetime import datetime
from typing import Protocol

from screamingface_engine.tracing.span_tree import Span, identity_of, span_from_frame
from url4.streaming.interfaces import EventPublisher
from url4.streaming.protocol import OutboundFrame, SpanEvent, StartedEvent, TerminatedEvent

logger = logging.getLogger(__name__)

ROOT_SPAN_NAME = "url4.run"
"""The synthetic root's span name — what an operator sees at the top of the waterfall."""

OTLP_ENDPOINT_VARS = ("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "OTEL_EXPORTER_OTLP_ENDPOINT")
"""Both halves of OTel's endpoint contract. Reading only the generic one would leave a
deployment that configured just the signal-specific variable silently un-traced — a failure
that produces no error anywhere."""


def otlp_configured(env: Mapping[str, str]) -> bool:
    """Whether a deployment has asked for span export at all.

    Lives HERE, in the port module, rather than in the adapter — because the composition root
    must answer it WITHOUT importing the adapter. `tracing.otlp` pulls the OTel SDK, protobuf
    and `requests`: measured at ~62 ms of a Job's ~227 ms import budget, paid on every run
    including the overwhelming majority that export nothing. `check_layering.py` exists to keep
    a Job's cold start at "the engine + httpx + nats-py"; it checks engine submodules and would
    not have caught a third-party regression of the same shape.

    A blank value counts as unset: a chart rendering `OTEL_EXPORTER_OTLP_ENDPOINT: ""` for an
    unconfigured environment must read as "off", not as "export to the empty string".
    """
    return any(env.get(name, "").strip() for name in OTLP_ENDPOINT_VARS)


class SpanSink(Protocol):
    """Where mapped spans go. The port; :mod:`.otlp` is the only adapter that exists."""

    def emit(self, span: Span) -> None: ...

    def close(self) -> None: ...


class SpanRelay(EventPublisher):
    """Wraps a publisher to export the run's spans, without changing what is published.

    A transparent proxy in the same sense as `run_evidence.TerminalWatch`: every method
    forwards, and the observation is a side effect that cannot be observed by the run.

    `sink` is ``None`` when no OTLP endpoint is configured, which is the default everywhere
    (local runs, tests, any deployment `OME-1131` has not reached). In that state the relay is
    a pure passthrough — the feature is off by construction rather than by a flag someone must
    remember to unset.
    """

    def __init__(self, inner: EventPublisher, sink: SpanSink | None) -> None:
        self._inner = inner
        self._sink = sink
        self._trace_id: str | None = None
        self._root_span_id: str | None = None
        self._started_at: datetime | None = None
        self._closed = False
        self.undecodable = 0
        """Frames whose `traceparent` stated no usable identity — counted, never invented."""
        self.unfinished = 0
        """Spans with no end. OTLP has no way to say "still running" (ledger D11)."""

    def __enter__(self) -> SpanRelay:
        """Use the relay as a context manager so :meth:`close` cannot be forgotten.

        D10's flush is mandatory and its absence is SILENT — every trace simply loses its
        ending. A hand-written `finally` at the composition root would work exactly as well
        right up until somebody edits that function; `with` is the version the language
        enforces.
        """
        return self

    def __exit__(self, *_: object) -> None:
        self.shutdown()

    async def ensure_stream(self, topic: str) -> None:
        await self._inner.ensure_stream(topic)

    async def publish(self, topic: str, event: OutboundFrame) -> None:
        if self._sink is not None:
            self._observe(topic, event)
        await self._inner.publish(topic, event)

    async def flush(self) -> None:
        await self._inner.flush()

    async def close(self) -> None:
        """The WIRE port's close — forwarded, like every other method on the proxy.

        Distinct from :meth:`shutdown`, which is the sink's. They are deliberately not merged:
        this one is `async` and belongs to `EventPublisher`, and a transparent proxy that
        quietly stopped forwarding it would leave the inner publisher's transport open.

        AIDEV-NOTE: the base declares this NON-abstract and `async`, so a sync override
        type-checks in Python and only fails at the `await` — at teardown, in production, on a
        path that runs when something is already going wrong. Pyright caught exactly that here.
        """
        await self._inner.close()

    def shutdown(self) -> None:
        """Flush and shut the SINK down. Idempotent, and safe to call from a ``finally``.

        MANDATORY, not a nicety (ledger D10): the run process is short-lived, and a batching
        exporter drops whatever is still queued at exit — which is the tail of every trace,
        including the root span, since the root is by definition emitted last. Losing it looks
        like "tracing works" while every run is missing its ending.
        """
        if self._closed or self._sink is None:
            return
        self._closed = True
        try:
            self._sink.close()
        except Exception:
            logger.warning("the span sink did not shut down cleanly", exc_info=True)

    # --- observation ---------------------------------------------------------------------

    def _observe(self, topic: str, event: OutboundFrame) -> None:
        """Map one frame and offer it to the sink. INVARIANT: never raises."""
        try:
            if isinstance(event, StartedEvent):
                self._open_root(event)
            elif isinstance(event, SpanEvent):
                self._node(event)
            elif isinstance(event, TerminatedEvent):
                self._close_root(topic, event)
        except Exception:
            # The run is worth more than its telemetry. See the module INVARIANT.
            logger.warning("could not export a span for topic %s", topic, exc_info=True)

    def _open_root(self, event: StartedEvent) -> None:
        """Learn the run's identity from the frame that states it.

        `lifecycle._trace_fields` publishes run-level frames under
        `format_traceparent(trace_id, root_span_id)`, so the `Started` envelope carries the
        root's span id — the id every `url4.parent=` and every Phase 1 gateway `traceparent`
        already references, and which no `SpanEvent` ever carries.
        """
        identity = identity_of(event.traceparent)
        if identity is None:
            self.undecodable += 1
            return
        self._trace_id, self._root_span_id = identity
        self._started_at = event.time

    def _node(self, event: SpanEvent) -> None:
        span = span_from_frame(event)
        if span is None:
            self.undecodable += 1
            return
        if span.end_time is None:
            self.unfinished += 1
            return
        self._emit(span)

    def _close_root(self, topic: str, event: TerminatedEvent) -> None:
        """Materialise the run's own span, now that its end is known.

        Emitted LAST because that is when its end time exists. A run killed hard enough to
        publish no terminal frame therefore contributes no root — the same refusal D11 applies
        to a node, for the same reason: an unbounded span renders as a 56-year one.
        """
        if self._trace_id is None or self._root_span_id is None or self._started_at is None:
            return
        end = event.time
        if end is None:
            self.unfinished += 1
            return
        self._emit(
            Span(
                trace_id=self._trace_id,
                span_id=self._root_span_id,
                parent_span_id=None,
                name=ROOT_SPAN_NAME,
                operation="run",
                start_time=self._started_at,
                end_time=end,
                status=event.data.status,
                attributes={"url4.topic": topic, "url4.run.status": event.data.status},
            )
        )

    def _emit(self, span: Span) -> None:
        """Hand one span to the sink, resolving an implicit parent to the run's root.

        A node with no `url4.parent` on the wire is a CHILD OF THE ROOT, not a root itself
        (`_trace_fields` omits the tracestate in exactly that case). Leaving it parentless
        would render one run as N disconnected traces.
        """
        assert self._sink is not None  # guarded by the caller; keeps the type narrow
        adopts_root = (
            span.is_root_child
            and self._root_span_id is not None
            and span.span_id != self._root_span_id
        )
        if adopts_root:
            span = dataclasses.replace(span, parent_span_id=self._root_span_id)
        self._sink.emit(span)


__all__ = ["OTLP_ENDPOINT_VARS", "ROOT_SPAN_NAME", "SpanRelay", "SpanSink", "otlp_configured"]
