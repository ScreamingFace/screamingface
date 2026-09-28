"""OME-1042: authoritative access is checked before any Candidate dispatch."""

from copy import deepcopy
from dataclasses import replace
from typing import Any

import httpx
import pytest
from _model_parameter_fixtures import DETAILS
from test_model_parameter_preflight import _BENCHMARK, _summary

import screamingface as sf

_MODEL = "provider/first"
_OTHER = "other/second"


class _Dispatched(RuntimeError):
    pass


class _Run:
    calls = 0

    def run(self, candidate: object, on_event: object) -> Any:
        self.calls += 1
        raise _Dispatched("execution reached")

    def close(self) -> None:
        pass

    def cancel_active(self) -> None:
        pass


class _AsyncRun:
    calls = 0

    async def run(self, candidate: object, on_event: object) -> Any:
        self.calls += 1
        raise _Dispatched("execution reached")

    async def close(self) -> None:
        pass

    async def cancel_active(self) -> None:
        pass


class _Engine:
    def __init__(self, access: dict[str, object], failure: object = None):
        self.access = access
        self.url = "https://hosted.example"
        self.listed = tuple(access)
        self.failure = failure
        self.requests: list[str] = []
        self.details: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request.url.path)
        if request.url.path == "/v1/benchmarks/fixture":
            return httpx.Response(200, json=_BENCHMARK)
        if request.url.path == "/v1/models":
            return httpx.Response(
                200, json={"object": "list", "data": [_summary(model) for model in self.listed]}
            )
        assert request.url.path == "/v1/model-parameters"
        model = request.url.params["model"]
        self.details.append(model)
        if isinstance(self.failure, Exception):
            raise self.failure
        body: dict[str, Any] = deepcopy(DETAILS)
        provider, upstream = model.split("/", 1)
        body["model"] = {"id": model, "gateway_provider": provider, "upstream_id": upstream}
        if self.access[model] is not ...:
            body["context"]["execution_access"] = self.access[model]
        return (
            httpx.Response(self.failure, json={"detail": "discovery failed"})
            if isinstance(self.failure, int)
            else httpx.Response(200, json=body)
        )


async def _evaluate(mode: str, engine: _Engine, recipe: Any, events: list[Any], runs: Any) -> None:
    options = {
        "engine_url": engine.url,
        "http_transport": httpx.MockTransport(engine),
        "run_transport": runs,
    }
    if mode == "sync":
        with sf.Client(**options) as client:
            client.evaluate(recipe, benchmark="fixture", progress=False, on_event=events.append)
    else:
        async with sf.AsyncClient(**options) as client:
            await client.evaluate(
                recipe, benchmark="fixture", progress=False, on_event=events.append
            )


@pytest.mark.parametrize("access", ["configured", "missing", ...])
def test_discovery_exposes_access_without_enforcing_it(access: object) -> None:
    engine = _Engine({_MODEL: access})
    with sf.Client(
        engine_url="https://hosted.example", http_transport=httpx.MockTransport(engine)
    ) as c:
        details = c.models.get(_MODEL)
    assert details.execution_access == (None if access is ... else access)
    assert engine.details == [_MODEL]


@pytest.mark.parametrize("access", [None, True, 1, {}, [], "unknown", ""])
def test_malformed_access_is_a_discovery_error(access: object) -> None:
    engine = _Engine({_MODEL: access})
    with sf.Client(
        engine_url="https://hosted.example", http_transport=httpx.MockTransport(engine)
    ) as c:
        with pytest.raises(sf.PlanningError, match="execution_access"):
            c.models.get(_MODEL)


def test_model_details_rejects_invalid_access_when_constructed_directly() -> None:
    engine = _Engine({_MODEL: ...})
    with sf.Client(
        engine_url="https://hosted.example", http_transport=httpx.MockTransport(engine)
    ) as c:
        details = c.models.get(_MODEL)
    invalid: Any = []
    with pytest.raises(ValueError, match="execution_access"):
        replace(details, execution_access=invalid)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("shape", ["plain", "partial", "fusion"])
async def test_missing_access_stops_before_any_dispatch_or_events(mode: str, shape: str) -> None:
    # STORY: even the default parameter-free evaluation must fail at the call site.
    recipe: Any = sf.Model(_MODEL)
    access: dict[str, object] = {_MODEL: "missing"}
    if shape != "plain":
        access = {_MODEL: "configured", _OTHER: "missing"}
        recipe = [sf.Model(_MODEL), sf.Model(_OTHER)]
    if shape == "fusion":
        recipe = sf.Fusion([sf.Model(_MODEL), sf.Model(_MODEL, name="repeat")], synthesizer=_OTHER)
    engine = _Engine(access)
    runs = _Run() if mode == "sync" else _AsyncRun()
    events: list[Any] = []
    with pytest.raises(sf.ProviderConnectionError) as caught:
        await _evaluate(mode, engine, recipe, events, runs)
    missing = _MODEL if shape == "plain" else _OTHER
    assert caught.value.provider == missing.split("/", 1)[0]
    assert caught.value.code == "provider_not_connected"
    assert caught.value.details == {"model": missing, "provider": missing.split("/", 1)[0]}
    assert "sf.connect" in (caught.value.hint or "")
    assert "hosted" in (caught.value.hint or "")
    assert runs.calls == 0
    assert events == []
    assert len(engine.details) == len(set(engine.details))


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("access", ["configured", ...])
@pytest.mark.parametrize("engine_url", ["https://hosted.example", "http://127.0.0.1:9100"])
@pytest.mark.parametrize("model", [_MODEL, "gemini-cli/gemini-model"])
async def test_configured_or_legacy_access_reaches_execution(
    mode: str, access: object, engine_url: str, model: str
) -> None:
    engine = _Engine({model: access})
    engine.url = engine_url
    runs = _Run() if mode == "sync" else _AsyncRun()
    with pytest.raises(_Dispatched):
        await _evaluate(mode, engine, sf.Model(model), [], runs)
    assert runs.calls == 1
    assert engine.details == [model]
    assert engine.requests == ["/v1/benchmarks/fixture", "/v1/models", "/v1/model-parameters"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("status,error", [(401, sf.AuthenticationError), (503, sf.PlanningError)])
async def test_discovery_errors_keep_their_types(
    mode: str, status: int, error: type[Exception]
) -> None:
    engine = _Engine({_MODEL: "missing"}, failure=status)
    runs = _Run() if mode == "sync" else _AsyncRun()
    with pytest.raises(error):
        await _evaluate(mode, engine, sf.Model(_MODEL), [], runs)
    assert runs.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["sync", "async"])
async def test_admission_probe_is_reused_by_access_preflight(mode: str) -> None:
    engine = _Engine({_MODEL: "configured"})
    engine.listed = ()
    runs = _Run() if mode == "sync" else _AsyncRun()
    with pytest.raises(_Dispatched):
        await _evaluate(mode, engine, sf.Model(_MODEL), [], runs)
    assert engine.details == [_MODEL]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["sync", "async"])
async def test_transport_failure_is_not_reclassified_as_missing_access(mode: str) -> None:
    engine = _Engine({_MODEL: "missing"}, failure=httpx.ConnectError("offline"))
    runs = _Run() if mode == "sync" else _AsyncRun()
    with pytest.raises(sf.EngineUnavailableError):
        await _evaluate(mode, engine, sf.Model(_MODEL), [], runs)
    assert runs.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("listed", [True, False])
@pytest.mark.parametrize("access", ["missing", "configured"])
async def test_seeded_access_preflight_reuses_details_and_rejects_before_dispatch(
    mode: str, listed: bool, access: str
) -> None:
    # INVARIANT: semantic rebase must retain both access and seed gates, including
    # the admission-probe path. This fixture intentionally has no seed parameter.
    engine = _Engine({_MODEL: access})
    engine.listed = (_MODEL,) if listed else ()
    events: list[Any] = []
    runs = _Run() if mode == "sync" else _AsyncRun()
    options = {
        "engine_url": engine.url,
        "http_transport": httpx.MockTransport(engine),
        "run_transport": runs,
    }
    expected = sf.ProviderConnectionError if access == "missing" else sf.PlanningError
    with pytest.raises(expected) as caught:
        if mode == "sync":
            with sf.Client(**options) as client:
                client.evaluate(
                    sf.Model(_MODEL),
                    benchmark="fixture",
                    answer_seed=7,
                    progress=False,
                    on_event=events.append,
                )
        else:
            async with sf.AsyncClient(**options) as client:
                await client.evaluate(
                    sf.Model(_MODEL),
                    benchmark="fixture",
                    answer_seed=7,
                    progress=False,
                    on_event=events.append,
                )
    assert caught.value.code == (
        "provider_not_connected" if access == "missing" else "unsupported_model_parameter"
    )
    assert engine.details == [_MODEL]
    assert runs.calls == 0
    assert events == []
