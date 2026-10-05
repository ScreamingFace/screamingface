"""Health-check probes export no server span; real requests are untouched (OME-1217).

`GET /healthz` was 60.2% of aigateway's spans in SigNoz — ROOT spans, burying real requests in
the trace list. Our server spans come from `CallIdMiddleware`, not `FastAPIInstrumentor`, so the
stock OTel knob did nothing until the middleware honoured it.

Owner decision (option A): the span is still BUILT — the route is only known after routing — and
is flagged and DROPPED by a SpanProcessor, so it is never exported.

# INVARIANT: only the span is dropped. The call id is still minted and published, the
# `x-aigw-trace-id` header is still echoed, and the request is still handled.
# INVARIANT: exclusion matches the RESOLVED ROUTE TEMPLATE (`scope["route"]`), not the raw path.

Driven through the real middleware over a real FastAPI app, with the exporter wired through the
same dropper `tracing.install` uses, so the assertions are on what would actually be exported.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from aigateway import tracing
from aigateway.middleware.call_id import CallIdMiddleware
from aigateway.span_exclusion import (
    DEFAULT_EXCLUDED_ROUTES,
    ENV_VAR,
    DropExcludedSpans,
    SpanExclusion,
)

TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"
PARENT = "00f067aa0ba902b7"


class _AlreadySet:
    def do_once(self, _func) -> bool:  # noqa: ANN001 - matches OTel's Once surface
        return False


def _use_provider(monkeypatch, provider: TracerProvider) -> None:
    monkeypatch.setattr(trace, "_TRACER_PROVIDER", provider, raising=False)
    monkeypatch.setattr(trace, "_TRACER_PROVIDER_SET_ONCE", _AlreadySet(), raising=False)


@pytest.fixture
def exporter(monkeypatch) -> InMemorySpanExporter:
    """A real SDK provider, its export path wrapped in the dropper exactly as `install` does."""
    memory = InMemorySpanExporter()
    provider = TracerProvider(
        resource=Resource.create({"service.name": "aigateway"}),
        id_generator=tracing._BoundIdGenerator(),
    )
    provider.add_span_processor(DropExcludedSpans(SimpleSpanProcessor(memory)))
    _use_provider(monkeypatch, provider)
    return memory


def _app(exclusion: SpanExclusion | None = None) -> FastAPI:
    app = FastAPI()

    @app.get("/healthz")
    async def healthz(request: Request) -> dict[str, str]:
        return {"gateway_call_id": request.state.gateway_call_id}

    @app.get("/work")
    async def work(request: Request) -> dict[str, str]:
        return {"gateway_call_id": request.state.gateway_call_id}

    @app.get("/items/{item_id}")
    async def item(item_id: str) -> dict[str, str]:
        return {"item": item_id}

    if exclusion is None:
        app.add_middleware(CallIdMiddleware)
    else:
        app.add_middleware(CallIdMiddleware, exclusion=exclusion)
    return app


@pytest.fixture
def probe_client() -> Iterator[TestClient]:
    with TestClient(_app(SpanExclusion.from_env({}))) as test_client:
        yield test_client


def _names(exporter: InMemorySpanExporter) -> list[str]:
    return [span.name for span in exporter.get_finished_spans()]


# --- the behaviour ---------------------------------------------------------------------------


def test_a_probe_request_exports_no_span_but_keeps_its_call_id(exporter, probe_client) -> None:
    response = probe_client.get("/healthz")

    assert response.status_code == 200
    assert _names(exporter) == []
    # Only the span is dropped: the id is still minted, published and echoed.
    assert response.json()["gateway_call_id"].startswith("call_")
    assert response.headers["x-aigw-trace-id"]


def test_a_real_request_keeps_its_span_name_and_parent(exporter, probe_client) -> None:
    response = probe_client.get("/work", headers={"traceparent": f"00-{TRACE}-{PARENT}-01"})

    assert response.status_code == 200
    [span] = exporter.get_finished_spans()
    assert span.name == "GET /work"
    assert span.parent is not None
    assert format(span.parent.span_id, "016x") == PARENT
    assert span.context is not None and format(span.context.trace_id, "032x") == TRACE
    # The internal flag never reaches an exported span.
    assert span.attributes is not None
    assert all(not key.startswith("aigw.span") for key in span.attributes)


def test_a_query_string_variant_is_dropped(exporter, probe_client) -> None:
    probe_client.get("/healthz?probe=1")

    assert _names(exporter) == []


def test_a_trailing_slash_variant_is_dropped(exporter, probe_client) -> None:
    # Routing resolves no route for `/healthz/` (Starlette answers it without dispatching), so
    # the fallback normalises the path. Still the probe — still dropped.
    probe_client.get("/healthz/", follow_redirects=False)

    assert _names(exporter) == []


def test_an_unknown_path_is_still_exported(exporter, probe_client) -> None:
    probe_client.get("/nope")

    assert _names(exporter) == ["GET /nope"]


def test_exclusion_matches_the_route_template_not_the_raw_path(exporter) -> None:
    exclusion = SpanExclusion.from_env({ENV_VAR: r"^/items/\{item_id\}$"})
    with TestClient(_app(exclusion)) as test_client:
        test_client.get("/items/42")
        test_client.get("/work")
        test_client.get("/healthz")

    # The TEMPLATE excluded `/items/42`; the replaced list no longer names `/healthz`.
    assert _names(exporter) == ["GET /work", "GET /healthz"]


def test_a_probe_that_raises_keeps_its_span(exporter) -> None:
    app = _app(SpanExclusion.from_env({ENV_VAR: "^/boom$"}))

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("x")

    with TestClient(app, raise_server_exceptions=False) as test_client:
        assert test_client.get("/boom").status_code == 500

    # Fails toward MORE telemetry: a failing probe is exactly what an operator wants to see.
    assert _names(exporter) == ["GET /boom"]


def test_the_gateway_app_drops_its_probe_by_default(exporter, client) -> None:
    """The real `create_app` (conftest `client`), with no override of the setting."""
    client.get("/healthz")
    client.get("/v1/models")

    assert _names(exporter) == ["GET /v1/models"]


def test_install_wires_the_dropper_into_the_export_path(monkeypatch) -> None:
    """`install` is what production runs; the fixture above only mirrors it. Prove the mirror."""
    memory = InMemorySpanExporter()
    monkeypatch.setattr(tracing, "OTLPSpanExporter", lambda: memory)
    monkeypatch.setattr(tracing, "BatchSpanProcessor", SimpleSpanProcessor)
    monkeypatch.setattr(trace, "_TRACER_PROVIDER", None, raising=False)
    monkeypatch.setattr(trace, "_TRACER_PROVIDER_SET_ONCE", _AlreadySet(), raising=False)
    monkeypatch.setattr(trace, "set_tracer_provider", lambda p: _use_provider(monkeypatch, p))

    assert tracing.install({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4318"})
    with TestClient(_app(SpanExclusion.from_env({}))) as test_client:
        test_client.get("/healthz")
        test_client.get("/work")

    assert [span.name for span in memory.get_finished_spans()] == ["GET /work"]


# --- the setting -----------------------------------------------------------------------------


def test_unset_means_the_probe_default() -> None:
    exclusion = SpanExclusion.from_env({})

    assert exclusion.excludes("/healthz")
    assert not exclusion.excludes("/v1/chat/completions")
    assert DEFAULT_EXCLUDED_ROUTES == ("^/healthz$",)


def test_set_but_blank_excludes_nothing() -> None:
    assert not SpanExclusion.from_env({ENV_VAR: " , "}).excludes("/healthz")


def test_entries_are_otel_style_regexes_searched_against_the_route() -> None:
    exclusion = SpanExclusion.from_env({ENV_VAR: "healthz, ^/metrics$"})

    assert exclusion.excludes("/healthz")
    assert exclusion.excludes("/metrics")
    assert not exclusion.excludes("/metrics/extra")


def test_an_invalid_pattern_falls_back_to_the_default_and_warns(caplog) -> None:
    logger = logging.getLogger("aigateway.span_exclusion")
    logger.addHandler(caplog.handler)
    try:
        exclusion = SpanExclusion.from_env({ENV_VAR: "(unclosed"})
    finally:
        logger.removeHandler(caplog.handler)

    assert exclusion.excludes("/healthz")
    assert any(ENV_VAR in record.getMessage() for record in caplog.records)
    # The raw value is not reflected into the log.
    assert all("(unclosed" not in record.getMessage() for record in caplog.records)
