"""OME-1770: each account's view of one configured endpoint settles preflight before dispatch.

FEATURE: hosted BYOM, Unit 2. A configured endpoint's model runs only for the accounts the
Gateway grants, and only with that account's own key. The Engine forwards each caller's own view,
so the SDK sees one of three answers for the same model id:

- granted with a key: listed, ``execution_access = configured``; the run reaches execution;
- granted without a key: listed, ``missing``; refused as ``provider_not_connected``;
- not granted: absent from the listing, and the details probe gets the Engine's not-installed
  404; refused as ``model_unavailable``.

WHY one fake Engine per account: the real Engine and Gateway build each view from the caller's
identity, which those apps test. This file proves the SDK half: each view alone starts or stops
the run, for a plain Model and for a Fusion that mixes the endpoint with a subsidized model.

INVARIANT: no refusal dispatches a Candidate or emits an event. A seeded evaluation stops before
dispatch because the endpoint's contract publishes no ``seed`` row.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import httpx
import pytest
from _model_parameter_fixtures import details as _subsidized_details
from test_model_parameter_preflight import _BENCHMARK, _summary

import screamingface as sf

_ENDPOINT = "byom_" + "a" * 32
_BYOM = f"{_ENDPOINT}/model_v1"
_SUBSIDIZED = "anthropic/claude-haiku-4-5"

# The listing row and details contract AI Gateway serves a granted account for a configured
# `openai-chat-basic-v1` target, as the Engine relays them: text messages and `max_tokens` only.
_ROW = {
    "id": _BYOM,
    "object": "model",
    "owned_by": _ENDPOINT,
    "supported_parameters": ["max_tokens"],
    "supported_tools": [],
    "unsupported_parameter_behavior": "reject",
    "parameter_contract_url": f"/v1/model-parameters?model={_ENDPOINT}%2Fmodel_v1",
    "input_modalities": ["text"],
}
_DETAILS = {
    "schema_version": 1,
    "contract_id": "pc_byom_fixture",
    "model": {"id": _BYOM, "gateway_provider": _ENDPOINT, "upstream_id": "model_v1"},
    "context": {
        "scope": "account_profile",
        "auth_mode": "api_key",
        "revision": "ctx_byom_fixture",
        "source_revision": None,
    },
    "freshness": {"observed_at": None, "expires_at": None, "stale": False, "degraded": False},
    "parameters": {
        "max_tokens": {
            "request_path": "max_tokens",
            "schema": {"type": "integer", "minimum": 1},
            "provider": {
                "support": "unknown",
                "source": "none",
                "stale": False,
                "deprecated": None,
            },
            "gateway": {
                "status": "enabled",
                "projection": "direct",
                "cache_behavior": "keyed",
                "applicable_auth_modes": ["api_key"],
            },
        }
    },
    "tools": {},
    "transport": {
        "stream": {
            "provider_support": "unknown",
            "gateway_status": "disabled",
            "reason": "gateway_transport_not_implemented",
        }
    },
}
# The Engine's answer for a private route the caller is not granted: the undeclared-model 404.
_NOT_INSTALLED = {
    "type": "about:blank",
    "title": "Not Found",
    "detail": "the model is not installed on this Engine",
    "status": 404,
}

_GRANTED_WITH_KEY = "configured"
_GRANTED_WITHOUT_KEY = "missing"
_NOT_GRANTED = "not-granted"


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
    """The hosted Engine as ONE account sees it: the subsidized model, plus the endpoint's model
    only when that account is granted it."""

    url = "https://hosted.example"

    def __init__(self, view: str) -> None:
        self.view = view
        self.details: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/benchmarks/fixture":
            return httpx.Response(200, json=_BENCHMARK)
        if request.url.path == "/v1/models":
            return self._listing()
        assert request.url.path == "/v1/model-parameters"
        return self._details(request.url.params["model"])

    def _listing(self) -> httpx.Response:
        rows: list[dict[str, object]] = [_summary(_SUBSIDIZED)]
        if self.view != _NOT_GRANTED:
            rows.append(_ROW)
        return httpx.Response(200, json={"object": "list", "data": rows})

    def _details(self, model: str) -> httpx.Response:
        self.details.append(model)
        if model == _SUBSIDIZED:
            body: dict[str, Any] = _subsidized_details(model)
            body["context"]["execution_access"] = "configured"
            return httpx.Response(200, json=body)
        assert model == _BYOM
        if self.view == _NOT_GRANTED:
            return httpx.Response(404, json=_NOT_INSTALLED)
        details: dict[str, Any] = deepcopy(_DETAILS)
        details["context"]["execution_access"] = self.view
        return httpx.Response(200, json=details)


def _recipe(shape: str) -> Any:
    if shape == "model":
        return sf.Model(_BYOM)
    return sf.Fusion(
        [sf.Model(_BYOM), sf.Model(_SUBSIDIZED)], synthesizer=_SUBSIDIZED, name="mixed"
    )


async def _evaluate(
    mode: str, engine: _Engine, recipe: Any, events: list[Any], runs: Any, **kwargs: Any
) -> None:
    options = {
        "engine_url": engine.url,
        "http_transport": httpx.MockTransport(engine),
        "run_transport": runs,
    }
    if mode == "sync":
        with sf.Client(**options) as client:
            client.evaluate(
                recipe, benchmark="fixture", progress=False, on_event=events.append, **kwargs
            )
    else:
        async with sf.AsyncClient(**options) as client:
            await client.evaluate(
                recipe, benchmark="fixture", progress=False, on_event=events.append, **kwargs
            )


def _runs(mode: str) -> Any:
    return _Run() if mode == "sync" else _AsyncRun()


@pytest.mark.parametrize(
    ("view", "listed", "access"),
    [
        (_GRANTED_WITH_KEY, True, "configured"),
        (_GRANTED_WITHOUT_KEY, True, "missing"),
        (_NOT_GRANTED, False, None),
    ],
)
def test_discovery_shows_each_account_only_its_own_view(
    view: str, listed: bool, access: str | None
) -> None:
    engine = _Engine(view)
    with sf.Client(engine_url=engine.url, http_transport=httpx.MockTransport(engine)) as client:
        ids = {model.id for model in client.models.list()}
        details = client.models.get(_BYOM) if listed else None

    assert (_BYOM in ids) is listed
    assert _SUBSIDIZED in ids
    assert (details.execution_access if details is not None else None) == access


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("shape", ["model", "fusion"])
async def test_a_granted_account_with_a_key_reaches_execution(mode: str, shape: str) -> None:
    """STORY: as a granted researcher with my key attached, my endpoint's model runs alone or
    beside a subsidized model, with no seed."""
    engine = _Engine(_GRANTED_WITH_KEY)
    runs = _runs(mode)

    with pytest.raises(_Dispatched):
        await _evaluate(mode, engine, _recipe(shape), [], runs)

    assert runs.calls == 1
    assert _BYOM in engine.details


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("shape", ["model", "fusion"])
async def test_a_granted_account_without_a_key_stops_before_dispatch(mode: str, shape: str) -> None:
    engine = _Engine(_GRANTED_WITHOUT_KEY)
    runs = _runs(mode)
    events: list[Any] = []

    with pytest.raises(sf.ProviderConnectionError) as caught:
        await _evaluate(mode, engine, _recipe(shape), events, runs)

    assert caught.value.code == "provider_not_connected"
    assert caught.value.details == {"model": _BYOM, "provider": _ENDPOINT}
    assert (runs.calls, events) == (0, [])


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("shape", ["model", "fusion"])
async def test_an_account_not_granted_gets_model_unavailable_before_dispatch(
    mode: str, shape: str
) -> None:
    engine = _Engine(_NOT_GRANTED)
    runs = _runs(mode)
    events: list[Any] = []

    with pytest.raises(sf.PlanningError) as caught:
        await _evaluate(mode, engine, _recipe(shape), events, runs)

    assert caught.value.code == "model_unavailable"
    assert caught.value.details == {"models": [_BYOM]}
    assert (runs.calls, events) == (0, [])


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("shape", ["model", "fusion"])
async def test_a_seeded_evaluation_stops_before_dispatch(mode: str, shape: str) -> None:
    """WHY: the endpoint contract has no `seed` row, so a declared seed has no door to pass."""
    engine = _Engine(_GRANTED_WITH_KEY)
    runs = _runs(mode)
    events: list[Any] = []

    with pytest.raises(sf.PlanningError) as caught:
        await _evaluate(mode, engine, _recipe(shape), events, runs, answer_seed=7)

    assert caught.value.code == "unsupported_model_parameter"
    assert caught.value.details == {"model": _BYOM, "parameter": "seed"}
    assert (runs.calls, events) == (0, [])
