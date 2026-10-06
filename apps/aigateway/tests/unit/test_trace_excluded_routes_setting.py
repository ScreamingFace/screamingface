"""Probe-span exclusion reads `AIGW_TRACE_EXCLUDED_ROUTES`, not the OTel variable (OME-1453).

FEATURE (OME-1217 follow-up): the exclusion list is matched against RESOLVED ROUTE TEMPLATES.
`OTEL_PYTHON_EXCLUDED_URLS` is commonly set cluster-wide with UNANCHORED values for the stock
OTel instrumentors (e.g. `healthz,models`); read here, such a value would silently drop real
gateway routes like `/v1/models`. So the gateway owns its own setting and ignores the OTel one.

# INVARIANT: `OTEL_PYTHON_EXCLUDED_URLS` never removes a gateway span.
# INVARIANT: the setting is read through `Settings` (pydantic-settings), like every `AIGW_*`.
"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from aigateway import tracing
from aigateway.config import Settings
from aigateway.span_exclusion import ENV_VAR, DropExcludedSpans, SpanExclusion


class _AlreadySet:
    def do_once(self, _func) -> bool:  # noqa: ANN001 - matches OTel's Once surface
        return False


@pytest.fixture
def exporter(monkeypatch) -> InMemorySpanExporter:
    """A real SDK provider whose export path goes through the dropper, as `install` wires it."""
    memory = InMemorySpanExporter()
    provider = TracerProvider(
        resource=Resource.create({"service.name": "aigateway"}),
        id_generator=tracing._BoundIdGenerator(),
    )
    provider.add_span_processor(DropExcludedSpans(SimpleSpanProcessor(memory)))
    monkeypatch.setattr(trace, "_TRACER_PROVIDER", provider, raising=False)
    monkeypatch.setattr(trace, "_TRACER_PROVIDER_SET_ONCE", _AlreadySet(), raising=False)
    return memory


def _gateway(request: pytest.FixtureRequest, monkeypatch, **env: str) -> TestClient:
    """The real `create_app` (conftest `client`), built AFTER `env` is in the environment."""
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return request.getfixturevalue("client")


def _names(exporter: InMemorySpanExporter) -> list[str]:
    return [span.name for span in exporter.get_finished_spans()]


# --- the name ---------------------------------------------------------------------------------


def test_the_setting_is_gateway_specific() -> None:
    assert ENV_VAR == "AIGW_TRACE_EXCLUDED_ROUTES"


# --- the gateway ignores the OTel variable -------------------------------------------------------


def test_an_unanchored_otel_value_does_not_drop_a_real_gateway_route(
    exporter, request, monkeypatch
) -> None:
    """The ticket's verify: `healthz,models` set cluster-wide for the OTel instrumentors."""
    client = _gateway(request, monkeypatch, OTEL_PYTHON_EXCLUDED_URLS="healthz,models")

    client.get("/v1/models")
    client.get("/healthz")

    # `/v1/models` survives; the probe is still dropped by the gateway's own default.
    assert _names(exporter) == ["GET /v1/models"]


def test_a_blank_otel_value_does_not_turn_probe_spans_back_on(
    exporter, request, monkeypatch
) -> None:
    client = _gateway(request, monkeypatch, OTEL_PYTHON_EXCLUDED_URLS="")

    client.get("/healthz")

    assert _names(exporter) == []


# --- the gateway honours its own setting ---------------------------------------------------------


def test_the_gateway_honours_its_own_setting(exporter, request, monkeypatch) -> None:
    client = _gateway(request, monkeypatch, AIGW_TRACE_EXCLUDED_ROUTES="^/v1/models$")

    client.get("/v1/models")
    client.get("/healthz")

    # The list REPLACES the default: `/v1/models` dropped, `/healthz` exported again.
    assert _names(exporter) == ["GET /healthz"]


def test_settings_reads_the_variable(monkeypatch) -> None:
    monkeypatch.setenv("AIGW_TRACE_EXCLUDED_ROUTES", "^/healthz$,^/readyz$")

    assert Settings().trace_excluded_routes == "^/healthz$,^/readyz$"


def test_settings_leaves_it_unset_by_default(monkeypatch) -> None:
    monkeypatch.delenv("AIGW_TRACE_EXCLUDED_ROUTES", raising=False)

    assert Settings().trace_excluded_routes is None


def test_settings_ignores_the_otel_variable(monkeypatch) -> None:
    monkeypatch.delenv("AIGW_TRACE_EXCLUDED_ROUTES", raising=False)
    monkeypatch.setenv("OTEL_PYTHON_EXCLUDED_URLS", "models")

    assert Settings().trace_excluded_routes is None


# --- the parser the engine can lift (OME-1218) ---------------------------------------------------


def test_from_setting_unset_means_the_probe_default() -> None:
    exclusion = SpanExclusion.from_setting(None)

    assert exclusion.excludes("/healthz")
    assert not exclusion.excludes("/v1/models")


def test_from_setting_blank_excludes_nothing() -> None:
    assert SpanExclusion.from_setting("  ,  ").pattern is None


def test_from_setting_anchored_entries_match_only_their_route() -> None:
    exclusion = SpanExclusion.from_setting(r"^/healthz$, ^/items/\{item_id\}$")

    assert exclusion.excludes("/healthz")
    assert exclusion.excludes("/items/{item_id}")
    assert not exclusion.excludes("/v1/healthz")
    assert not exclusion.excludes("/items/{item_id}/children")


def test_from_setting_invalid_falls_back_to_the_default_and_warns(caplog) -> None:
    logger = logging.getLogger("aigateway.span_exclusion")
    logger.addHandler(caplog.handler)
    try:
        exclusion = SpanExclusion.from_setting("[unclosed")
    finally:
        logger.removeHandler(caplog.handler)

    assert exclusion.excludes("/healthz")
    assert any(ENV_VAR in record.getMessage() for record in caplog.records)
    assert all("[unclosed" not in record.getMessage() for record in caplog.records)


def test_from_env_ignores_the_otel_variable() -> None:
    exclusion = SpanExclusion.from_env({"OTEL_PYTHON_EXCLUDED_URLS": "models"})

    assert not exclusion.excludes("/v1/models")
    assert exclusion.excludes("/healthz")
