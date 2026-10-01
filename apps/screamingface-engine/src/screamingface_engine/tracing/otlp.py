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
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.sdk.util.instrumentation import InstrumentationScope
from opentelemetry.trace import SpanContext, SpanKind, TraceFlags
from opentelemetry.trace.status import Status, StatusCode

from screamingface_engine.tracing.relay import OTLP_ENDPOINT_VARS, otlp_configured
from screamingface_engine.tracing.span_tree import Span

logger = logging.getLogger(__name__)

FLUSH_TIMEOUT_MS = 5_000
"""How long a FINISHED run will block trying to hand its spans over, in milliseconds.

WHY a bound of our own: the question at `close()` is "how long is it worth holding a completed
run open to save its spans?", and the SDK does not answer it. In opentelemetry-sdk 1.44
`force_flush` ignores its `timeout_millis` (upstream opentelemetry-python#4568) and pays the
exporter's whole retry budget, 10 s by default, once per queued batch: 21.6 s for 1100 spans
against an unreachable collector, measured. `OtlpSpanSink.close` enforces this bound itself.
5 s clears a healthy collector carrying a queued batch by a wide margin.

AIDEV-NOTE: this is a deliberate trade, not a tuned number. Raising it trades run latency for
span retention on a slow collector; lowering it does the reverse. Argue about it here, in one
place, rather than at the call site (OME-1213 ledger D2)."""

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


class CountingSpanExporter(SpanExporter):
    """Delegates to the real exporter and counts every span the collector did not take.

    WHY it exists (OME-1213): the SDK loses this answer twice. `BatchSpanProcessor` discards
    `export()`'s result, and in opentelemetry-sdk 1.44 `force_flush` returns True whatever
    happened (upstream opentelemetry-python#4568). So a 401, a 404 or a dead port reads as a
    clean flush, and the exporter's own verdict is the only record of the loss.

    INVARIANT: `undelivered` only grows, and only inside `export`, which the processor calls
    under its export lock, so there is one writer at a time. `close()` reads it once the drain
    thread has finished.
    """

    def __init__(self, inner: SpanExporter) -> None:
        self._inner = inner
        self.undelivered = 0

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        try:
            result = self._inner.export(spans)
        except Exception:
            # The processor logs and swallows this; counting it first is what makes it audible.
            self.undelivered += len(spans)
            raise
        if result is not SpanExportResult.SUCCESS:
            self.undelivered += len(spans)
        return result

    def shutdown(self) -> None:
        self._inner.shutdown()

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return self._inner.force_flush(timeout_millis)


@dataclass
class _Drain:
    """One `close()`'s flush-then-shutdown, run on its own thread so the caller can stop waiting."""

    processor: SpanProcessor
    timeout_ms: int
    flushed: bool = False
    error: Exception | None = None

    def run(self) -> None:
        try:
            try:
                # The timeout is still passed, so an SDK that honours it (#4568 fixed) does.
                self.flushed = self.processor.force_flush(timeout_millis=self.timeout_ms)
            finally:
                # WHY `finally`: a raising flush used to leak the exporter thread on exactly the
                # runs already going wrong.
                self.processor.shutdown()
        except Exception as exc:
            # WHY caught: an exception cannot cross a thread by itself. `close()` re-raises it on
            # the caller's thread, where the relay logs and swallows it (OME-1130 ledger D4).
            self.error = exc


class OtlpSpanSink:
    """Feeds mapped spans to an OTel `SpanProcessor`.

    The processor is injected rather than built here so tests can drive the REAL SDK path with
    an in-memory exporter; :func:`sink_from_env` is the production constructor.
    """

    def __init__(
        self,
        processor: SpanProcessor,
        resource: Resource | None = None,
        *,
        endpoint: str = "",
        delivery: CountingSpanExporter | None = None,
        flush_timeout_ms: int = FLUSH_TIMEOUT_MS,
    ) -> None:
        self._processor = processor
        self._resource = resource if resource is not None else Resource.create()
        # WHY the sink is TOLD its endpoint rather than asking: the exporter keeps it private
        # (`_endpoint`) and reading the environment here would break the one property that makes
        # this adapter testable — that it is handed every collaborator. `sink_from_env` is the
        # composition seam that reads env, so it passes it down (OME-1213 ledger D1).
        self._endpoint = endpoint
        # WHY `delivery` is handed over beside the processor that wraps it: the processor keeps
        # its exporter private, and the exporter's count is the only honest verdict on what
        # reached the collector. None means no count, and then `force_flush`'s answer is all
        # there is.
        self._delivery = delivery
        self._flush_timeout_ms = flush_timeout_ms

    def emit(self, span: Span) -> None:
        self._processor.on_end(_readable(span, self._resource))

    def close(self) -> None:
        """Flush what is queued, then stop the exporter's thread.

        `force_flush` before `shutdown` is the load-bearing order: the run process exits
        immediately after this, and whatever is still queued would otherwise be dropped —
        starting with the root span, which is emitted last (OME-1130 ledger D10).

        WHY the outcome is reported (OME-1213): a silent loss is what made `OME-1190`'s
        unreachable collector invisible for a day in `sf-fusion`. The failure existed only inside
        OTel's internal logger, so at the engine's own log level the run read perfectly clean
        while every span was dropped.

        WHY a thread and a `join`: in opentelemetry-sdk 1.44 `force_flush` ignores its timeout
        and returns True whatever the exporter answered (upstream opentelemetry-python#4568). So
        the bound is enforced HERE, and the verdict comes from `delivery`, the exporter's own
        count of what it failed to hand over.

        INVARIANT: never waits longer than the bound, and never changes the run's outcome. A
        collector outage must not fail a benchmark (OME-1130 ledger D4); it is AUDIBLE, not
        fatal. An exception raised within the bound is re-raised for the relay, which logs it.
        """
        drain = _Drain(self._processor, self._flush_timeout_ms)
        worker = threading.Thread(target=drain.run, name="otlp-span-flush", daemon=True)
        worker.start()
        worker.join(self._flush_timeout_ms / 1000)
        if worker.is_alive():
            # AIDEV-NOTE: abandoned, not cancelled. The daemon thread still owns `shutdown` and
            # runs it once the stalled export returns; as a daemon it never holds the exiting run
            # process open.
            self._warn_dropped(f"the flush did not finish within {self._flush_timeout_ms}ms")
            return
        if drain.error is not None:
            raise drain.error
        undelivered = self._delivery.undelivered if self._delivery is not None else 0
        if undelivered:
            self._warn_dropped(f"the collector did not take {undelivered} span(s)")
        elif not drain.flushed:
            self._warn_dropped("the flush reported failure")

    def _warn_dropped(self, reason: str) -> None:
        logger.warning(
            "otlp span export incomplete: %s — spans were DROPPED endpoint=%s",
            reason,
            self._endpoint,
        )


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
    endpoint = _endpoint(env)
    # WHY "configured" and not "enabled": all that has been checked is that a string is
    # non-blank. Nothing has spoken to the collector, so "enabled" reads as a success report for
    # something never verified. Naming the endpoint is what makes a wrong one findable — notably
    # the SigNoz UI hostname, which answers 200 text/html and discards every span while looking
    # perfectly healthy (see the warning at the config site in values.yaml).
    logger.info(
        "otlp span export configured service=%s endpoint=%s",
        resource.attributes.get("service.name"),
        endpoint,
    )
    # WHY the endpoint is PASSED rather than left to the exporter: left alone, it resolves the
    # address again from `os.environ` by its own rule. Resolving once and handing that value over
    # makes the logged address the posted address by construction, not by agreement.
    delivery = CountingSpanExporter(OTLPSpanExporter(endpoint=endpoint))
    return OtlpSpanSink(
        BatchSpanProcessor(delivery), resource, endpoint=endpoint, delivery=delivery
    )


def _endpoint(env: Mapping[str, str]) -> str:
    """The URL span batches are posted to, resolved the way OTel resolves it.

    The signal-specific variable is a full URL, used verbatim. The generic one is a BASE that
    OTLP/HTTP extends with `/v1/traces` (the SDK's `trace_exporter._append_trace_path`). A blank
    signal-specific variable falls through to the generic one, as in :func:`otlp_configured`.

    INVARIANT: scans `OTLP_ENDPOINT_VARS` in the order :func:`otlp_configured` does, so a
    deployment it calls configured always gets a non-blank URL here. Printing the raw generic
    variable would name a URL nothing posts to, and send a debugging session to the wrong place.
    """
    signal_var, generic_var = OTLP_ENDPOINT_VARS
    if url := env.get(signal_var, "").strip():
        return url
    base = env.get(generic_var, "").strip()
    if not base:
        return ""
    return base + ("v1/traces" if base.endswith("/") else "/v1/traces")


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


__all__ = [
    "DEFAULT_SERVICE_NAME",
    "FLUSH_TIMEOUT_MS",
    "CountingSpanExporter",
    "OtlpSpanSink",
    "sink_from_env",
]
