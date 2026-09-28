"""aigateway as an OTel service — spans, not just correlated log lines (OME-1132).

Phase 1 made one `trace_id` greppable across the engine and `sf-aigw`. That is not enough for a
trace view: a shared id in two log lines draws no edge in a service map, produces no latency
breakdown, and cannot answer "which provider call was slow". This emits real spans so aigateway
appears as its own service in the tree the engine's exporter (`OME-1130`) starts.

THE SUBTLE REQUIREMENT — the span's trace id must be the id the middleware ALREADY BOUND.
OTel ships `TraceContextTextMapPropagator` to extract a parent from headers, and using it here
would be a bug. `CallIdMiddleware` computes `adopt_or_mint_trace_id(inbound)`; the propagator
would agree with it on a well-formed traceparent and DIVERGE on a malformed or absent one,
because each mints its own replacement. One request would then carry two different ids — the
failure `middleware/call_id.py` names exactly: *"two ids for one call is worse than none,
because both look right."* So the propagator is not used, and :class:`_BoundIdGenerator` hands
OTel the id already in the call context, which makes the agreement structural.

NOT GATED BY `AIGW_TAXONOMY_ENABLED`. That flag is an observability kill-switch: flipping it
removes `call_` from logs, body and headers at once. `middleware/call_id.py` exists BECAUSE the
correlation ids used to live inside that plugin, so disabling usage accounting silently deleted
the gateway's only correlation mechanism. Spans are correlation. Gating them on an accounting
flag would re-commit the mistake that middleware was written to undo.

SECURITY — span attributes NEVER carry provider text. `routes/chat_dispatch.py` refuses
`str(exc)` because it serializes raw LiteLLM/provider text, and any secret embedded in it, into
places it must not reach. A span attribute is the same exposure with a different name, and it
travels to a third system searched by people who never saw the response. Failures are recorded
as the exception CLASS NAME only.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.id_generator import RandomIdGenerator

from aigateway.call_context import current_trace_id
from aigateway.w3c_trace import new_trace_id

logger = logging.getLogger(__name__)

DEFAULT_SERVICE_NAME = "aigateway"
"""Used when the deployment sets no `OTEL_SERVICE_NAME`. A service reporting itself as OTel's
default `unknown_service` is indistinguishable from every other unconfigured service, which
defeats the point of emitting the spans."""

OTLP_ENDPOINT_VARS = ("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "OTEL_EXPORTER_OTLP_ENDPOINT")
"""Both halves of OTel's endpoint contract. Reading only the generic one would leave a
deployment that set just the signal-specific variable silently un-traced."""

PROVIDER_ATTRIBUTE = "gen_ai.provider.name"
ERROR_TYPE_ATTRIBUTE = "error.type"
"""OTel's conventional name for a failure's CLASS. Conventional precisely because it is the
half that is safe to record — `error.message` is the half this gateway must never fill."""

_TRACER_NAME = "aigateway.tracing"


def otlp_configured(env: Mapping[str, str]) -> bool:
    """Whether this deployment asked for span export at all.

    A blank value counts as unset: a chart rendering `OTEL_EXPORTER_OTLP_ENDPOINT: ""` for an
    unconfigured environment must read as "off", not as "export to the empty string".

    AIDEV-NOTE: unlike the engine's equivalent, this module imports the OTel SDK at module
    level. The engine defers it because its exporter is mounted in a SHORT-LIVED run process
    where ~62 ms of import is paid per run; aigateway is a long-running server that boots once,
    so the same deferral would buy nothing and cost the ability to subclass `RandomIdGenerator`
    properly. Different cost profile, different answer — not an inconsistency.
    """
    return any(env.get(name, "").strip() for name in OTLP_ENDPOINT_VARS)


def install(env: Mapping[str, str]) -> bool:
    """Install the global tracer provider. Returns whether tracing is now on.

    INVARIANT: never raises. A misconfigured exporter must not stop the gateway from serving —
    it is an AI gateway first and a telemetry source second, and a process that refuses to boot
    because a collector address was wrong is a far worse outage than missing spans.
    """
    if not otlp_configured(env):
        return False
    try:
        resource = Resource.create(
            {"service.name": env.get("OTEL_SERVICE_NAME") or DEFAULT_SERVICE_NAME}
        )
        provider = TracerProvider(resource=resource, id_generator=_BoundIdGenerator())
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        trace.set_tracer_provider(provider)
    except Exception:
        logger.warning("span export is configured but could not be started", exc_info=True)
        return False
    logger.info(
        "otlp span export enabled service=%s",
        env.get("OTEL_SERVICE_NAME") or DEFAULT_SERVICE_NAME,
    )
    return True


@contextmanager
def server_span(name: str, *, parent_span_id: str | None) -> Iterator[None]:
    """The span for one inbound HTTP request.

    `parent_span_id` is the id off the caller's traceparent, already validated by
    `w3c_trace.parse_traceparent`, or None when the caller sent nothing usable. None yields a
    ROOT span rather than a child of a fabricated parent — a span pointing at an id nobody
    emitted renders as a gap in the waterfall and is worse than an honest root.
    """
    with _span(name, kind="server", parent_span_id=parent_span_id):
        yield


@contextmanager
def provider_span(provider: str) -> Iterator[None]:
    """The span for one dispatch to a provider — the answer to "which call was slow".

    It covers the WHOLE dispatch: waiting for the per-provider concurrency slot, every overload
    retry, and the provider's own time. That is deliberate. `_dispatch_with_backpressure` holds
    the slot across retries, so the wall-clock the caller actually experienced includes queueing
    and backoff; timing only the final attempt would show a fast span for a call somebody waited
    seconds on. The per-attempt breakdown already exists in the accounting record.

    INVARIANT: a failure records the exception CLASS NAME and nothing else. See the module
    SECURITY note — `str(exc)` here would leak raw provider text into the tracing backend.
    """
    with _span(
        f"chat.completions {provider}",
        kind="client",
        attributes={PROVIDER_ATTRIBUTE: provider},
    ):
        yield


@contextmanager
def _span(
    name: str,
    *,
    kind: str,
    parent_span_id: str | None = None,
    attributes: Mapping[str, str] | None = None,
) -> Iterator[None]:
    """One span, or nothing at all when tracing is off.

    INVARIANT: never raises and never alters control flow. Everything here is a side effect on
    a request that must succeed or fail on its own merits; an exception escaping this would
    turn a telemetry fault into a failed API call.
    """
    if isinstance(trace.get_tracer_provider(), trace.NoOpTracerProvider):
        # Not installed: do not pay for span objects that go nowhere. Every request passes
        # through here, so the off path must be as close to free as a function call gets.
        yield
        return

    tracer = trace.get_tracer(_TRACER_NAME)
    context = _parent_context(parent_span_id)
    span_kind = trace.SpanKind.SERVER if kind == "server" else trace.SpanKind.CLIENT
    # SECURITY — `record_exception=False` is LOAD-BEARING, not tidiness. OTel defaults it to
    # TRUE, which attaches the exception's `str()` AND its traceback to the span as an event.
    # For this gateway that is raw LiteLLM/provider text — the exact payload
    # `routes/chat_dispatch.py` refuses to put in a response — shipped to a tracing backend
    # searched by people who never saw the request. A test asserts a secret in a provider
    # exception does not reach the span; it FAILED before this argument existed.
    #
    # `set_status_on_exception=False` for the same reason: it records the message as the
    # status DESCRIPTION. The status is set explicitly below, with no description.
    with tracer.start_as_current_span(
        name,
        context=context,
        kind=span_kind,
        attributes=dict(attributes or {}),
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        try:
            yield
        except Exception as exc:
            # CLASS NAME ONLY. Never `str(exc)`, never `record_exception` (which attaches the
            # message AND the traceback) — both would carry raw provider text.
            span.set_attribute(ERROR_TYPE_ATTRIBUTE, type(exc).__name__)
            span.set_status(trace.Status(trace.StatusCode.ERROR))
            raise


def _parent_context(parent_span_id: str | None) -> Context | None:
    """The remote parent to hang this span off, or None for a root.

    Built from the ids the middleware already validated rather than by running OTel's
    propagator over the headers again — see the module docstring for why that distinction is
    load-bearing rather than stylistic.
    """
    if parent_span_id is None:
        return None
    trace_id = current_trace_id()
    if trace_id is None:
        return None
    parent = trace.SpanContext(
        trace_id=int(trace_id, 16),
        span_id=int(parent_span_id, 16),
        is_remote=True,
        trace_flags=trace.TraceFlags(trace.TraceFlags.SAMPLED),
    )
    return trace.set_span_in_context(trace.NonRecordingSpan(parent))


class _BoundIdGenerator(RandomIdGenerator):
    """Hands OTel the trace id the request is ALREADY bound to.

    WHY this exists rather than letting the SDK mint: the id in every log line comes from
    `call_context`, and an independently minted span trace id would mean an operator who greps
    a `trace_id=` out of the logs finds no matching trace, and vice versa. That is not a
    cosmetic mismatch — it silently breaks the join between the two halves of the observability
    story this phase exists to connect.

    Falls back to a fresh id outside a request (a background task, a boot-time span), because
    returning a null id would produce a span the backend rejects.

    Subclasses `RandomIdGenerator` rather than duck-typing the interface: the SDK also calls
    `is_trace_id_random()`, and a hand-rolled generator missing it raises at span creation —
    inside a request, at runtime, which is the worst place to find an interface mismatch. It
    did exactly that here before this line existed.
    """

    def generate_trace_id(self) -> int:
        return int(current_trace_id() or new_trace_id(), 16)


__all__ = [
    "DEFAULT_SERVICE_NAME",
    "ERROR_TYPE_ATTRIBUTE",
    "OTLP_ENDPOINT_VARS",
    "PROVIDER_ATTRIBUTE",
    "install",
    "otlp_configured",
    "provider_span",
    "server_span",
]
