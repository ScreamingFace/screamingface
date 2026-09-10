from __future__ import annotations

import copy
from typing import NoReturn

import httpx
import pytest
from _model_parameter_fixtures import DETAILS as _DETAILS
from _model_parameter_fixtures import SUMMARY as _SUMMARY
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


def _summary(model: str) -> dict[str, object]:
    provider = model.split("/", 1)[0]
    return {
        **_SUMMARY,
        "id": model,
        "owned_by": provider,
        "parameter_contract_url": f"/v1/model-parameters?model={model}",
    }


def _details(model: str) -> dict[str, object]:
    value = copy.deepcopy(_DETAILS)
    provider, upstream = model.split("/", 1)
    value["model"] = {
        "id": model,
        "gateway_provider": provider,
        "upstream_id": upstream,
    }
    return value


class _ReachedTransport:
    called = False

    def run(self, candidate: object, on_event: object) -> NoReturn:
        self.called = True
        raise RuntimeError("execution reached")

    def cancel_active(self) -> None:
        pass

    def close(self) -> None:
        pass


class _ForbiddenTransport:
    called = False

    def run(self, candidate: object, on_event: object) -> NoReturn:
        self.called = True
        raise AssertionError("parameter preflight must fail before execution")

    def cancel_active(self) -> None:
        pass

    def close(self) -> None:
        pass


class _AsyncForbiddenTransport:
    called = False

    async def run(self, candidate: object, on_event: object) -> NoReturn:
        self.called = True
        raise AssertionError("parameter preflight must fail before execution")

    async def cancel_active(self) -> None:
        pass

    async def close(self) -> None:
        pass


class _AsyncReachedTransport:
    called = False

    async def run(self, candidate: object, on_event: object) -> NoReturn:
        self.called = True
        raise RuntimeError("execution reached")

    async def cancel_active(self) -> None:
        pass

    async def close(self) -> None:
        pass


def _engine(
    detail_models: list[str],
    models: tuple[str, ...] = ("provider/opus", "provider/synth"),
    benchmark: dict[str, object] = _BENCHMARK,
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/benchmarks/fixture":
            response = httpx.Response(200, json=benchmark)
        elif request.url.path == "/v1/models":
            response = httpx.Response(
                200,
                json={"object": "list", "data": [_summary(model) for model in models]},
            )
        elif request.url.path == "/v1/model-parameters":
            model = request.url.params["model"]
            detail_models.append(model)
            response = httpx.Response(200, json=_details(model))
        else:
            response = httpx.Response(404)
        return response

    return httpx.MockTransport(handler)


def test_parameter_free_evaluation_does_not_fetch_model_details() -> None:
    detail_models: list[str] = []
    transport = _ReachedTransport()
    client = sf.Client(
        engine_url="https://engine.example",
        http_transport=_engine(detail_models),
        run_transport=transport,
    )

    with client, pytest.raises(RuntimeError, match="execution reached"):
        client.evaluate(sf.Model("provider/opus"), benchmark="fixture")

    assert transport.called is True
    assert detail_models == []


def test_valid_explicit_params_fetch_each_distinct_model_once() -> None:
    detail_models: list[str] = []
    transport = _ReachedTransport()
    candidate = sf.Fusion(
        [
            sf.Model("provider/opus", name="first", params={"temperature": 0.2}),
            sf.Model("provider/opus", name="second", params={"temperature": 0.7}),
        ],
        synthesizer="provider/synth",
    )
    client = sf.Client(
        engine_url="https://engine.example",
        http_transport=_engine(detail_models),
        run_transport=transport,
    )

    with client, pytest.raises(RuntimeError, match="execution reached"):
        client.evaluate(candidate, benchmark="fixture")

    assert transport.called is True
    assert detail_models == ["provider/opus"]


def test_repeated_model_route_retains_an_explicit_parameter_assignment() -> None:
    detail_models: list[str] = []
    transport = _ReachedTransport()
    inner = sf.Fusion(
        [sf.Model("provider/opus"), sf.Model("provider/other")],
        name="inner",
        synthesizer="provider/inner-synth",
    )
    candidate = sf.Fusion(
        [
            inner,
            sf.Model("provider/opus", name="explicit-opus", params={"max_tokens": 4096}),
        ],
        name="outer",
        synthesizer="provider/outer-synth",
    )
    client = sf.Client(
        engine_url="https://engine.example",
        http_transport=_engine(
            detail_models,
            models=(
                "provider/opus",
                "provider/other",
                "provider/inner-synth",
                "provider/outer-synth",
            ),
        ),
        run_transport=transport,
    )

    with client, pytest.raises(RuntimeError, match="execution reached"):
        client.evaluate(candidate, benchmark="fixture")

    assert transport.called is True
    assert detail_models == ["provider/opus"]


def test_synthesizer_params_are_preflighted_against_its_model() -> None:
    detail_models: list[str] = []
    transport = _ReachedTransport()
    candidate = sf.Fusion(
        [sf.Model("provider/opus", name="first"), sf.Model("provider/opus", name="second")],
        synthesizer=sf.Model("provider/synth", params={"temperature": 0.4}),
    )
    client = sf.Client(
        engine_url="https://engine.example",
        http_transport=_engine(detail_models),
        run_transport=transport,
    )

    with client, pytest.raises(RuntimeError, match="execution reached"):
        client.evaluate(candidate, benchmark="fixture")

    assert transport.called is True
    assert detail_models == ["provider/synth"]


@pytest.mark.parametrize(
    ("params", "message", "code"),
    [
        (
            {"top_k": 40},
            "Parameter 'top_k' is not available for Model 'provider/opus'",
            "unsupported_model_parameter",
        ),
        (
            {"reasoning_effort": "high"},
            "Parameter 'reasoning_effort' is disabled for Model 'provider/opus'",
            "unsupported_model_parameter",
        ),
        (
            {"temperature": 3.0},
            "Parameter 'temperature' for Model 'provider/opus' must be <= 2",
            "invalid_model_parameter",
        ),
        (
            {"temperature": "hot"},
            "Parameter 'temperature' for Model 'provider/opus' expected number",
            "invalid_model_parameter",
        ),
    ],
)
def test_invalid_explicit_params_fail_before_execution(
    params: dict[str, str | int | float | bool],
    message: str,
    code: str,
) -> None:
    detail_models: list[str] = []
    transport = _ForbiddenTransport()
    client = sf.Client(
        engine_url="https://engine.example",
        http_transport=_engine(detail_models),
        run_transport=transport,
    )

    with client, pytest.raises(sf.PlanningError, match=message) as caught:
        client.evaluate(sf.Model("provider/opus", params=params), benchmark="fixture")

    assert caught.value.code == code
    assert caught.value.permanent is True
    assert transport.called is False
    assert detail_models == ["provider/opus"]


@pytest.mark.asyncio
async def test_async_evaluation_uses_the_same_parameter_preflight() -> None:
    detail_models: list[str] = []
    transport = _AsyncForbiddenTransport()
    client = sf.AsyncClient(
        engine_url="https://engine.example",
        http_transport=_engine(detail_models),
        run_transport=transport,
    )

    with pytest.raises(sf.PlanningError) as caught:
        await client.evaluate(
            sf.Model("provider/opus", params={"temperature": 3.0}),
            benchmark="fixture",
        )
    await client.aclose()

    assert caught.value.code == "invalid_model_parameter"
    assert transport.called is False
    assert detail_models == ["provider/opus"]


def test_later_pipeline_stage_parameters_fail_before_any_paid_execution() -> None:
    detail_models: list[str] = []
    transport = _ForbiddenTransport()
    candidate = sf.Pipeline(
        [
            sf.Model("provider/opus", params={"temperature": 0.2}),
            sf.Model("provider/synth", params={"top_k": 40}),
        ]
    )
    client = sf.Client(
        engine_url="https://engine.example",
        http_transport=_engine(detail_models),
        run_transport=transport,
    )

    with client, pytest.raises(sf.PlanningError, match="top_k") as caught:
        client.evaluate(candidate, benchmark="fixture")

    assert caught.value.code == "unsupported_model_parameter"
    assert transport.called is False
    assert detail_models == ["provider/opus", "provider/synth"]
