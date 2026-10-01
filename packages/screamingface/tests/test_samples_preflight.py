"""sf.samples() fails before spend when the model cannot take a seed (OME-1289, SM-3, SM-8).

WHY there is no ValueError path (orchestrator decision D-8, option A): every explicit Model
parameter already goes through preflight, which refuses a missing, disabled or provider-denied
``seed`` row with ``PlanningError(code="unsupported_model_parameter")`` before any request is sent.
The model-details lookup is the preflight's own: one per model per ``evaluate``, no cache across
calls (the preflight needs a fresh ``execution_access`` after ``client.connect``).

The engine handler below follows ``test_unsupported_provider_parameter_preflight.py`` and is
copied, not imported, so that module stays free to change.
"""

from __future__ import annotations

import copy
from typing import Any, NoReturn

import httpx
import pytest
from _model_parameter_fixtures import DETAILS as _DETAILS
from _model_parameter_fixtures import SUMMARY as _SUMMARY
from _reducer_fixtures import FixtureVote, operators_response
from url4 import RelExpr, expr, render, src, text

import screamingface as sf

_BENCHMARK_URL4 = render(
    expr(
        src(
            RelExpr(path="/candidate", context="question", intent=text("$candidate")),
            name="answer",
            weight=0.0,
        ),
        intent=text("$answer"),
    )
)
_BENCHMARK = {
    "schema": "screamingface.benchmark.v1",
    "id": "fixture",
    "title": "Fixture",
    "description": "Fixture Benchmark.",
    "revision": "fixture-revision",
    "case_count": 1,
    "url4": _BENCHMARK_URL4,
}

_MODEL = "provider/opus"


def _summary(model: str) -> dict[str, object]:
    return {
        **_SUMMARY,
        "id": model,
        "owned_by": model.split("/", 1)[0],
        "parameter_contract_url": f"/v1/model-parameters?model={model}",
    }


def _seed_row(support: str) -> dict[str, object]:
    return {
        "request_path": "seed",
        "schema": {"type": "integer"},
        "provider": {
            "support": support,
            "source": "openrouter:models",
            "stale": False,
            "deprecated": False,
        },
        "gateway": {
            "status": "enabled",
            "projection": "direct",
            "cache_behavior": "keyed",
            "applicable_auth_modes": ["api_key"],
        },
    }


def _details(model: str, seed_support: str | None) -> dict[str, object]:
    """The shared fixture contract (which has no ``seed`` row) with ``seed`` added when asked."""
    value: dict[str, Any] = copy.deepcopy(_DETAILS)
    provider, upstream = model.split("/", 1)
    value["model"] = {"id": model, "gateway_provider": provider, "upstream_id": upstream}
    if seed_support is not None:
        value["parameters"]["seed"] = _seed_row(seed_support)
    return value


class _Engine:
    """A mock Engine that records every path it serves."""

    def __init__(self, seed_support: str | None, *, lookup_error: Exception | None = None) -> None:
        self.paths: list[str] = []
        self._seed_support = seed_support
        self._lookup_error = lookup_error

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.paths.append(request.url.path)
        response = httpx.Response(404)
        if request.url.path == "/v1/benchmarks/fixture":
            response = httpx.Response(200, json=_BENCHMARK)
        elif request.url.path == "/v1/operators":
            response = operators_response()
        elif request.url.path == "/v1/models":
            response = httpx.Response(200, json={"object": "list", "data": [_summary(_MODEL)]})
        elif request.url.path == "/v1/model-parameters":
            if self._lookup_error is not None:
                raise self._lookup_error
            response = httpx.Response(200, json=_details(_MODEL, self._seed_support))
        return response

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    @property
    def lookups(self) -> list[str]:
        return [path for path in self.paths if path.startswith("/v1/model-parameters")]


class _ForbiddenTransport:
    called = False

    def run(self, candidate: object, on_event: object) -> NoReturn:
        self.called = True
        raise AssertionError("the seed preflight must refuse before any spend")

    def cancel_active(self) -> None:
        pass

    def close(self) -> None:
        pass


class _AsyncForbiddenTransport:
    called = False

    async def run(self, candidate: object, on_event: object) -> NoReturn:
        self.called = True
        raise AssertionError("the seed preflight must refuse before any spend")

    async def cancel_active(self) -> None:
        pass

    async def close(self) -> None:
        pass


def _candidate() -> sf.Recipe:
    return sf.Fusion(sf.samples(_MODEL, 3), synthesizer=FixtureVote())


@pytest.mark.parametrize(
    ("seed_support", "expected"),
    [("unsupported", "is not supported by the provider"), (None, "is not available")],
)
def test_samples_rejects_model_without_seed_support(
    seed_support: str | None, expected: str
) -> None:
    engine = _Engine(seed_support)
    transport = _ForbiddenTransport()
    client = sf.Client(
        engine_url="https://engine.example",
        http_transport=engine.transport,
        run_transport=transport,
    )

    with client, pytest.raises(sf.PlanningError) as caught:
        client.evaluate(_candidate(), benchmark="fixture")

    assert caught.value.code == "unsupported_model_parameter"
    assert "'seed'" in str(caught.value)
    assert expected in str(caught.value)
    assert transport.called is False
    # One lookup for the model, however many samples it has.
    assert len(engine.lookups) == 1


def test_contract_lookup_failure_raises_engine_unavailable() -> None:
    engine = _Engine("supported", lookup_error=httpx.ConnectError("engine went away"))
    transport = _ForbiddenTransport()
    client = sf.Client(
        engine_url="https://engine.example",
        http_transport=engine.transport,
        run_transport=transport,
    )

    with client, pytest.raises(sf.EngineUnavailableError):
        client.evaluate(_candidate(), benchmark="fixture")

    # WHY: an unreachable contract must never be read as "seed supported".
    assert transport.called is False
    assert engine.lookups == ["/v1/model-parameters"]


@pytest.mark.asyncio
async def test_async_contract_lookup_failure_raises_engine_unavailable() -> None:
    engine = _Engine("supported", lookup_error=httpx.ConnectError("engine went away"))
    transport = _AsyncForbiddenTransport()
    client = sf.AsyncClient(
        engine_url="https://engine.example",
        http_transport=engine.transport,
        run_transport=transport,
    )

    with pytest.raises(sf.EngineUnavailableError):
        await client.evaluate(_candidate(), benchmark="fixture")
    await client.aclose()

    assert transport.called is False
    assert engine.lookups == ["/v1/model-parameters"]


@pytest.mark.asyncio
async def test_async_samples_reject_model_without_seed_support() -> None:
    engine = _Engine("unsupported")
    transport = _AsyncForbiddenTransport()
    client = sf.AsyncClient(
        engine_url="https://engine.example",
        http_transport=engine.transport,
        run_transport=transport,
    )

    with pytest.raises(sf.PlanningError) as caught:
        await client.evaluate(_candidate(), benchmark="fixture")
    await client.aclose()

    assert caught.value.code == "unsupported_model_parameter"
    assert transport.called is False
    assert len(engine.lookups) == 1
