"""aigateway emits spans, and they join the caller's trace (OME-1132).

Phase 2's last unit. The engine's exporter (`OME-1130`) turns its frames into spans; aigateway
is a separate service, so without this a trace stops at the engine.

THE PROPERTY MOST OF THIS FILE DEFENDS: **the span's trace id is the same id the middleware
bound and every log line carries.** OTel's own `TraceContextTextMapPropagator` would agree with
`adopt_or_mint_trace_id` on a well-formed traceparent and diverge on a malformed or absent one,
because each mints its own replacement — and an operator who greps `trace_id=` out of the logs
would then find no matching trace. `middleware/call_id.py` names that failure exactly: "two ids
for one call is worse than none, because both look right." So the divergent cases get tests,
not just the agreeing one.

No collector and no network: OTel's own `InMemorySpanExporter` with a `SimpleSpanProcessor`,
which is the real SDK path a live exporter sits behind.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanContext

from aigateway import tracing
from aigateway.call_context import call_scope
from aigateway.w3c_trace import parse_traceparent

TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"
PARENT = "00f067aa0ba902b7"


@pytest.fixture
def exporter(monkeypatch) -> InMemorySpanExporter:
    """A real SDK provider with the module's own id generator, exporting in memory.

    `_BoundIdGenerator` is the piece under test in half these cases, so it is wired exactly as
    `install` wires it rather than stubbed.
    """
    memory = InMemorySpanExporter()
    provider = TracerProvider(
        resource=Resource.create({"service.name": "aigateway"}),
        id_generator=tracing._BoundIdGenerator(),
    )
    provider.add_span_processor(SimpleSpanProcessor(memory))
    monkeypatch.setattr(trace, "_TRACER_PROVIDER", provider, raising=False)
    monkeypatch.setattr(trace, "_TRACER_PROVIDER_SET_ONCE", _AlreadySet(), raising=False)
    return memory


class _AlreadySet:
    """Lets the test swap the global provider, which OTel otherwise allows only once."""

    def do_once(self, _func) -> bool:  # noqa: ANN001 - matches OTel's Once surface
        return False


def only(exporter: InMemorySpanExporter) -> ReadableSpan:
    spans = exporter.get_finished_spans()
    assert len(spans) == 1, f"expected exactly one span, got {[s.name for s in spans]}"
    return spans[0]


def hexid(value: int, width: int) -> str:
    return format(value, f"0{width}x")


def context_of(span: ReadableSpan) -> SpanContext:
    """The span's context, narrowed. `ReadableSpan.context` is Optional for spans that were
    never started; every span these tests read has been."""
    assert span.context is not None
    return span.context


def attributes_of(span: ReadableSpan) -> Mapping[str, Any]:
    assert span.attributes is not None
    return span.attributes


# --- the trace id agreement (the load-bearing property) ----------------------------------------


def test_the_span_joins_the_bound_trace_id(exporter) -> None:
    with call_scope("call-1", trace_id=TRACE), tracing.server_span("POST /x", parent_span_id=None):
        pass

    assert hexid(context_of(only(exporter)).trace_id, 32) == TRACE


def test_the_span_joins_the_bound_id_even_when_the_caller_sent_NOTHING(exporter) -> None:
    """The divergence case. With no inbound traceparent the middleware MINTS an id; OTel's
    propagator would have minted a different one, and the logs and the trace would name the
    same request by two ids."""
    minted = "1" * 32

    with call_scope("call-1", trace_id=minted), tracing.server_span("POST /x", parent_span_id=None):
        pass

    assert hexid(context_of(only(exporter)).trace_id, 32) == minted


def test_the_span_joins_the_bound_id_when_the_caller_sent_GARBAGE(exporter) -> None:
    """`adopt_or_mint_trace_id` REPLACES an unparseable value rather than repairing it, so the
    bound id is one the caller never chose. The span must follow the middleware, not the
    header."""
    assert parse_traceparent("not-a-traceparent") is None
    replaced = "2" * 32

    with call_scope("c", trace_id=replaced), tracing.server_span("POST /x", parent_span_id=None):
        pass

    assert hexid(context_of(only(exporter)).trace_id, 32) == replaced


# --- the parent edge ---------------------------------------------------------------------------


def test_a_well_formed_caller_span_id_becomes_the_parent(exporter) -> None:
    """What actually attaches aigateway to the engine node that called it — without this the
    waterfall shows two unconnected roots under one trace."""
    with call_scope("c", trace_id=TRACE), tracing.server_span("POST /x", parent_span_id=PARENT):
        pass

    span = only(exporter)
    assert span.parent is not None
    assert hexid(span.parent.span_id, 16) == PARENT
    assert span.parent.trace_id == context_of(span).trace_id


def test_no_caller_span_id_yields_a_ROOT_not_a_fabricated_parent(exporter) -> None:
    """A span pointing at an id nobody emitted renders as a gap in the waterfall. An honest
    root is better than an invented edge — the same refusal the engine's mapper makes."""
    with call_scope("c", trace_id=TRACE), tracing.server_span("POST /x", parent_span_id=None):
        pass

    assert only(exporter).parent is None


def test_the_server_span_is_kind_SERVER(exporter) -> None:
    with call_scope("c", trace_id=TRACE), tracing.server_span("POST /x", parent_span_id=None):
        pass

    assert only(exporter).kind is trace.SpanKind.SERVER


# --- the provider span -------------------------------------------------------------------


def test_the_provider_call_is_a_child_of_the_server_span(exporter) -> None:
    """ "Which provider was slow" is only answerable if the provider span sits UNDER the
    request span rather than beside it."""
    with call_scope("c", trace_id=TRACE), tracing.server_span("POST /x", parent_span_id=None):
        with tracing.provider_span("openrouter"):
            pass

    spans = {s.name: s for s in exporter.get_finished_spans()}
    provider = spans["chat.completions openrouter"]
    server = spans["POST /x"]
    assert provider.parent is not None
    assert provider.parent.span_id == context_of(server).span_id
    assert provider.kind is trace.SpanKind.CLIENT


def test_the_provider_span_names_the_provider_conventionally(exporter) -> None:
    with call_scope("c", trace_id=TRACE), tracing.provider_span("anthropic"):
        pass

    assert attributes_of(only(exporter))[tracing.PROVIDER_ATTRIBUTE] == "anthropic"


# --- what a failure may say ---------------------------------------------------------------


def test_a_failed_provider_call_records_the_exception_CLASS_and_nothing_else(exporter) -> None:
    """SECURITY. `routes/chat_dispatch.py` refuses `str(exc)` because it serializes raw
    LiteLLM/provider text — and any secret inside it. A span attribute is the same exposure
    with a different name, and it travels to a backend searched by people who never saw the
    response.
    """
    secret = "sk-live-DO-NOT-LEAK"

    with pytest.raises(RuntimeError):
        with call_scope("c", trace_id=TRACE), tracing.provider_span("openrouter"):
            raise RuntimeError(f"provider said: {secret}")

    span = only(exporter)
    assert attributes_of(span)[tracing.ERROR_TYPE_ATTRIBUTE] == "RuntimeError"
    assert span.status.status_code is trace.StatusCode.ERROR

    # WHY the events are walked field by field rather than `repr`'d: `Event.__repr__` is the
    # default `<... object at 0x...>`, so a `repr(span.events)` check reads as thorough and
    # detects NOTHING. This test passed against `record_exception=True` — the very leak it
    # exists to catch — until a mutation run exposed it.
    rendered = [repr(dict(span.attributes or {})), repr(span.status.description)]
    for event in span.events:
        rendered.append(event.name)
        rendered.append(repr(dict(event.attributes or {})))
    haystack = " ".join(rendered)

    assert secret not in haystack, f"provider text reached the span: {haystack}"
    assert "provider said" not in haystack, f"provider text reached the span: {haystack}"


def test_the_exception_still_propagates(exporter) -> None:
    """The span must observe, never swallow — a caller that stopped seeing provider failures
    because tracing was enabled would be a catastrophic regression."""
    with pytest.raises(ValueError):
        with call_scope("c", trace_id=TRACE), tracing.provider_span("p"):
            raise ValueError("boom")


# --- off by default ---------------------------------------------------------------------------


def test_no_endpoint_configured_means_tracing_is_not_installed() -> None:
    assert tracing.install({}) is False


def test_a_blank_endpoint_reads_as_off() -> None:
    assert tracing.install({"OTEL_EXPORTER_OTLP_ENDPOINT": "   "}) is False


def test_either_endpoint_variable_turns_it_on() -> None:
    """OTel's contract lets a deployment set only the signal-specific variable; reading just
    the generic one would leave such a deployment silently un-traced."""
    assert tracing.otlp_configured({"OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "http://c:4318"})
    assert tracing.otlp_configured({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://c:4318"})


def test_the_span_helpers_are_no_ops_when_tracing_is_off() -> None:
    """Every request goes through `server_span`, so with tracing off it must cost nothing and
    — far more importantly — must not raise."""
    with call_scope("c", trace_id=TRACE), tracing.server_span("POST /x", parent_span_id=PARENT):
        pass
    with tracing.provider_span("openrouter"):
        pass


# --- spans are NOT gated by the taxonomy kill-switch (D1) -------------------------------------


@pytest.mark.asyncio
async def test_the_middleware_emits_a_span_with_no_taxonomy_plugin_involved(exporter) -> None:
    """`AIGW_TAXONOMY_ENABLED` must NOT gate spans, and this is what proves it: the span comes
    out of the middleware, driven with a bare ASGI app and no plugin anywhere in the call.

    The ticket asks for this decision to be made explicitly. It is the same call the codebase
    already made for the ids — `middleware/call_id.py` exists BECAUSE they used to live in
    `plugins/taxonomy/session.py`, so turning off usage accounting silently deleted the
    gateway's only correlation mechanism. Spans are correlation.
    """
    from aigateway.middleware.call_id import CallIdMiddleware

    async def app(scope, receive, send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/v1/chat/completions",
        "headers": [(b"traceparent", f"00-{TRACE}-{PARENT}-01".encode())],
    }
    sent: list = []

    async def receive():  # pragma: no cover - never awaited by this app
        return {"type": "http.request"}

    async def send(message) -> None:
        sent.append(message)

    await CallIdMiddleware(app)(scope, receive, send)

    span = only(exporter)
    assert span.name == "POST /v1/chat/completions"
    assert hexid(context_of(span).trace_id, 32) == TRACE
    assert span.parent is not None and hexid(span.parent.span_id, 16) == PARENT


def test_the_tracing_module_does_not_consult_the_taxonomy_settings() -> None:
    """The structural half of D1: a future edit that gates spans on the accounting flag has to
    introduce the reference here, and this fails when it does."""
    from pathlib import Path

    source = Path(tracing.__file__).read_text(encoding="utf-8")

    # The docstring MENTIONS the flag to explain why it is ignored, so this checks for the
    # ways it could be READ, not for the word.
    assert "TaxonomyPluginSettings" not in source
    assert "taxonomy_enabled" not in source
    assert "from aigateway.plugins" not in source


def test_a_broken_exporter_config_does_not_stop_the_gateway(monkeypatch) -> None:
    """An AI gateway that refuses to boot because a collector address was wrong is a far worse
    outage than missing spans."""
    import aigateway.tracing as module

    monkeypatch.setattr(module, "DEFAULT_SERVICE_NAME", property(lambda _: 1 / 0), raising=False)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "://not-a-url")

    # Whatever happens inside, it must not escape.
    tracing.install({"OTEL_EXPORTER_OTLP_ENDPOINT": "://not-a-url"})
