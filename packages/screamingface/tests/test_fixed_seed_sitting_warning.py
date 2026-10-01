"""A run seed plus a call that sets its own seed warns, then the run goes on (OME-1289, U1).

WHY: the engine lets a call that sets its own ``seed`` keep it, and applies the run's ambient seed
(``answer_seed``, one "sitting" of OME-1038) only to calls without one. So ``sf.samples()`` members
and any ``sf.Model(params={"seed": ...})`` send the SAME requests in every sitting, and a mean and
CI across sittings is falsely tight. The decision (user, 2026-10-01) is to warn, not refuse.

The engine handler below follows ``test_samples_preflight.py`` and is copied, not imported, so that
module stays free to change.
"""

from __future__ import annotations

import copy
import warnings
from typing import Any, NoReturn

import httpx
import pytest
from _model_parameter_fixtures import DETAILS as _DETAILS
from _model_parameter_fixtures import SUMMARY as _SUMMARY
from _reducer_fixtures import FixtureVote, fixture_operators, operators_response
from url4 import RelExpr, expr, render, src, text

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate

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
_SEED_ROW = {
    "request_path": "seed",
    "schema": {"type": "integer"},
    "provider": {
        "support": "supported",
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


def _details() -> dict[str, object]:
    value: dict[str, Any] = copy.deepcopy(_DETAILS)
    provider, upstream = _MODEL.split("/", 1)
    value["model"] = {"id": _MODEL, "gateway_provider": provider, "upstream_id": upstream}
    value["parameters"]["seed"] = _SEED_ROW
    return value


def _handler(request: httpx.Request) -> httpx.Response:
    response = httpx.Response(404)
    if request.url.path == "/v1/benchmarks/fixture":
        response = httpx.Response(200, json=_BENCHMARK)
    elif request.url.path == "/v1/operators":
        response = operators_response()
    elif request.url.path == "/v1/models":
        summary = {**_SUMMARY, "id": _MODEL, "owned_by": "provider"}
        summary["parameter_contract_url"] = f"/v1/model-parameters?model={_MODEL}"
        response = httpx.Response(200, json={"object": "list", "data": [summary]})
    elif request.url.path == "/v1/model-parameters":
        response = httpx.Response(200, json=_details())
    return response


class _ReachedTransport:
    called = False

    def run(self, candidate: object, on_event: object) -> NoReturn:
        self.called = True
        raise RuntimeError("execution reached")

    def cancel_active(self) -> None:
        pass

    def close(self) -> None:
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


def _samples_fusion() -> sf.Recipe:
    return sf.Fusion(sf.samples(_MODEL, 3), synthesizer=FixtureVote())


def _unseeded_fusion() -> sf.Recipe:
    return sf.Fusion(
        [
            sf.Model(_MODEL, params={"temperature": 0.2}),
            sf.Model(_MODEL, params={"temperature": 0.7}),
        ],
        synthesizer=FixtureVote(),
    )


def _seeded_operation_ids(recipe: sf.Recipe) -> list[str]:
    compiled = compile_candidate(recipe, operators=fixture_operators())
    return [item.operation_id for item in compiled.parameter_assignments if "seed" in item.params]


def _sync_client() -> tuple[sf.Client, _ReachedTransport]:
    transport = _ReachedTransport()
    client = sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_handler),
        run_transport=transport,
    )
    return client, transport


def _async_client() -> tuple[sf.AsyncClient, _AsyncReachedTransport]:
    transport = _AsyncReachedTransport()
    client = sf.AsyncClient(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_handler),
        run_transport=transport,
    )
    return client, transport


def _run_sync(
    candidates: sf.Recipe | list[sf.Recipe], answer_seed: int | None
) -> tuple[list[warnings.WarningMessage], _ReachedTransport]:
    client, transport = _sync_client()
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        # WHY both: one Candidate re-raises the transport error; several are wrapped together.
        with client, pytest.raises((RuntimeError, sf.ExecutionError)):
            client.evaluate(candidates, benchmark="fixture", answer_seed=answer_seed)
    fixed = [w for w in recorded if issubclass(w.category, sf.FixedSeedSittingWarning)]
    return fixed, transport


def test_samples_with_a_run_seed_warn_once_naming_the_seeded_operations() -> None:
    recipe = _samples_fusion()

    fixed, transport = _run_sync(recipe, answer_seed=7)

    assert len(fixed) == 1
    message = str(fixed[0].message)
    assert "7" in message
    operation_ids = _seeded_operation_ids(recipe)
    assert len(operation_ids) == 3
    for operation_id in operation_ids:
        assert operation_id in message
    assert "same request in every sitting" in message
    assert "seeds=" in message
    assert isinstance(fixed[0].message, sf.EvaluationWarning)
    assert fixed[0].filename == __file__
    # WHY: a warning, not a refusal; the run reached the transport.
    assert transport.called is True


def test_a_plain_model_with_its_own_seed_warns() -> None:
    fixed, transport = _run_sync(sf.Model(_MODEL, params={"seed": 7}), answer_seed=7)

    assert len(fixed) == 1
    assert transport.called is True


def test_no_warning_without_a_run_seed() -> None:
    fixed, transport = _run_sync([_samples_fusion(), sf.Model(_MODEL, params={"seed": 7})], None)

    assert fixed == []
    assert transport.called is True


def test_no_warning_when_no_call_sets_a_seed() -> None:
    client, transport = _sync_client()
    with warnings.catch_warnings():
        warnings.simplefilter("error", sf.FixedSeedSittingWarning)
        with client, pytest.raises(RuntimeError, match="execution reached"):
            client.evaluate(_unseeded_fusion(), benchmark="fixture", answer_seed=7)

    assert transport.called is True


def test_one_warning_for_each_candidate_that_has_a_seeded_call() -> None:
    plain = sf.Model(_MODEL, name="plain")
    seeded = sf.Model(_MODEL, name="seeded", params={"seed": 7})

    fixed, _transport = _run_sync([plain, seeded, _samples_fusion()], answer_seed=7)

    assert len(fixed) == 2
    assert any("seeded" in str(w.message) for w in fixed)
    assert all("'plain'" not in str(w.message) for w in fixed)


@pytest.mark.asyncio
async def test_async_samples_with_a_run_seed_warn_once() -> None:
    recipe = _samples_fusion()
    client, transport = _async_client()

    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        with pytest.raises(RuntimeError, match="execution reached"):
            await client.evaluate(recipe, benchmark="fixture", answer_seed=7)
    await client.aclose()

    fixed = [w for w in recorded if issubclass(w.category, sf.FixedSeedSittingWarning)]
    assert len(fixed) == 1
    for operation_id in _seeded_operation_ids(recipe):
        assert operation_id in str(fixed[0].message)
    assert fixed[0].filename == __file__
    assert transport.called is True


@pytest.mark.asyncio
async def test_async_no_warning_without_a_run_seed() -> None:
    client, transport = _async_client()

    with warnings.catch_warnings():
        warnings.simplefilter("error", sf.FixedSeedSittingWarning)
        with pytest.raises(RuntimeError, match="execution reached"):
            await client.evaluate(_samples_fusion(), benchmark="fixture")
    await client.aclose()

    assert transport.called is True
