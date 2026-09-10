"""The OTLP adapter: a mapped :class:`Span` becomes a real OTel span (OME-1130).

THE ONLY MODULE IN THE ENGINE THAT IMPORTS `opentelemetry`. The port is
:class:`screamingface_engine.tracing.relay.SpanSink`; keeping the import here is what lets the
relay's whole behaviour be tested with no OTel, no collector and no network, and what keeps a
transport change from re-opening the semantics (ledger D1, D8).

WHY spans are built by hand rather than through `tracer.start_span`. The normal SDK path MINTS
ids and takes the parent from the ambient context. Here both are already decided: the run
minted them, the wire published them, the aigateway logged them in Phase 1, and a client is
holding the trace id from its report. Re-minting would produce a technically valid trace that
correlates with nothing anybody has. `ReadableSpan` + `SpanProcessor.on_end` is the documented
seam for exactly this — a bridge from another tracing system — and it is what the OTLP encoder
consumes.

WHY `BatchSpanProcessor` and not a direct `exporter.export(...)`. Export must never fail or slow
a run (ledger D4). The batch processor already owns the hard parts: a background thread, a
bounded queue that DROPS rather than blocks when the collector is slow, and a `force_flush`
/`shutdown` pair. Reimplementing that here would be strictly worse code with the same bugs.

CONFIGURED THE STANDARD WAY (ledger D9). The endpoint, headers and resource all come from
OTel's own env contract — `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_HEADERS`,
`OTEL_SERVICE_NAME`, `OTEL_RESOURCE_ATTRIBUTES` — rather than a vocabulary invented here. That
is deliberate: it makes `OME-1131` a matter of setting standard variables in the chart, with no
new credential scheme to design, and it means an operator's existing OTel knowledge transfers.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime

from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.util.instrumentation import InstrumentationScope
from opentelemetry.trace import SpanContext, SpanKind, TraceFlags
from opentelemetry.trace.status import Status, StatusCode

from screamingface_engine.tracing.relay import otlp_configured
from screamingface_engine.tracing.span_tree import Span

logger = logging.getLogger(__name__)

DEFAULT_SERVICE_NAME = "screamingface-engine"
"""Used only when the deployment sets no `OTEL_SERVICE_NAME`. A service that reports itself as
OTel's default `unknown_service` is indistinguishable from every other unconfigured service in
the backend, which defeats the point of shipping the spans at all."""

_OK_STATUSES = frozenset({"ok", "succeeded"})
"""The non-error vocabulary from BOTH wire types: `SpanData.status` says `ok`,
`TerminatedData.status` says `succeeded`, and this adapter receives spans carrying either
(see :class:`Span`)."""

_KINDS = {"client": SpanKind.CLIENT, "internal": SpanKind.INTERNAL, "server": SpanKind.SERVER}

_SCOPE = InstrumentationScope("screamingface_engine.tracing", "1")


class OtlpSpanSink:
    """Feeds mapped spans to an OTel `SpanProcessor`.

    The processor is injected rather than built here so tests can drive the REAL SDK path with
    an in-memory exporter; :func:`sink_from_env` is the production constructor.
    """

    def __init__(self, processor: SpanProcessor, resource: Resource | None = None) -> None:
        self._processor = processor
        self._resource = resource if resource is not None else Resource.create()

    def emit(self, span: Span) -> None:
        self._processor.on_end(_readable(span, self._resource))

    def close(self) -> None:
        """Flush what is queued, then stop the exporter's thread.

        `force_flush` before `shutdown` is the load-bearing order: the run process exits
        immediately after this, and whatever is still queued would otherwise be dropped —
        starting with the root span, which is emitted last (ledger D10).
        """
        self._processor.force_flush()
        self._processor.shutdown()


def sink_from_env(env: Mapping[str, str]) -> OtlpSpanSink | None:
    """The run's span sink, or ``None`` when no OTLP endpoint is configured.

    ``None`` is the default state everywhere — local runs, tests, and any deployment
    `OME-1131` has not reached — so the feature is off by construction rather than by a flag
    someone has to remember to unset (ledger D9).

    The "is it configured" predicate lives in the PORT module, not here, because the
    composition root must answer it without importing this one — see :func:`otlp_configured`.
    """
    if not otlp_configured(env):
        return None
    resource = Resource.create(
        {"service.name": env.get("OTEL_SERVICE_NAME") or DEFAULT_SERVICE_NAME}
    )
    logger.info("otlp span export enabled service=%s", resource.attributes.get("service.name"))
    return OtlpSpanSink(BatchSpanProcessor(OTLPSpanExporter()), resource)


def _readable(span: Span, resource: Resource) -> ReadableSpan:
    """One domain span -> one `ReadableSpan` the OTLP encoder accepts."""
    context = _context(span.trace_id, span.span_id)
    parent = _context(span.trace_id, span.parent_span_id) if span.parent_span_id else None
    return ReadableSpan(
        name=span.name,
        context=context,
        parent=parent,
        resource=resource,
        attributes={"gen_ai.operation.name": span.operation, **span.attributes},
        kind=_KINDS.get(span.kind, SpanKind.INTERNAL),
        status=_status(span.status),
        start_time=_nanos(span.start_time),
        end_time=_nanos(span.end_time) if span.end_time is not None else None,
        instrumentation_scope=_SCOPE,
    )


def _context(trace_id: str, span_id: str) -> SpanContext:
    """A span context from the WIRE's hex ids.

    INVARIANT: `TraceFlags.SAMPLED` must be set. `BatchSpanProcessor.on_end` opens with
    `if not (span.context and span.context.trace_flags.sampled): return` — an unsampled span is
    dropped by the SDK silently, with no error raised and nothing logged, which presents as
    "the exporter runs and the backend stays empty". `url4.streaming.trace` hardcodes
    `_SAMPLED = "01"`, so every run is nominally sampled and this is faithful, not a shortcut.
    """
    return SpanContext(
        trace_id=int(trace_id, 16),
        span_id=int(span_id, 16),
        is_remote=False,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
    )


def _status(status: str) -> Status:
    """Wire status -> OTel status, keeping the VERBATIM reason on the way through.

    OTel has one non-OK code and the wire has three non-OK run outcomes (`failed`, `stopped`,
    `timed_out`). Flattening them would erase the only place a stopped run is still
    distinguishable from a failed one — `cancelled` is collapsed to `error` before a node span
    is ever published, so the root's description is where that survives (ledger D7).
    """
    if status in _OK_STATUSES:
        return Status(StatusCode.OK)
    return Status(StatusCode.ERROR, description=status)


def _nanos(when: datetime) -> int:
    """OTel timestamps are integer nanoseconds since the epoch."""
    return int(when.timestamp() * 1_000_000_000)


__all__ = ["DEFAULT_SERVICE_NAME", "OtlpSpanSink", "sink_from_env"]
