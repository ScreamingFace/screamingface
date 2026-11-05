"""The operator catalog client: decode, cache, revalidate, and refuse (OME-1289, SL-8/9/14)."""

from __future__ import annotations

import copy
from collections.abc import Callable

import httpx
import pytest
from _reducer_fixtures import (
    OPERATOR_WIRE,
    operators_response,
    reducer_fusion,
)
from test_client_run import _engine, _ReplayTransport

import screamingface as sf
from screamingface._engine.catalog import AsyncOperatorCatalogResource, OperatorCatalogResource
from screamingface._evaluation.operators import decode_operator_catalog

_BASE = "https://engine.example"


def _wire(**changes: object) -> dict[str, object]:
    wire = copy.deepcopy(OPERATOR_WIRE)
    wire.update(changes)
    return wire


def _row(**changes: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": "last_number@1",
        "name": "last_number",
        "version": 1,
        "stage": "extract",
        "args_schema": {},
        "summary": "Last number token.",
    }
    row.update(changes)
    return row


def _bad_wires() -> dict[str, object]:
    return {
        "root not an object": [],
        "object not list": _wire(object="catalog"),
        "data not a list": _wire(data={}),
        "row not an object": _wire(data=["last_number@1"]),
        "id mismatch": _wire(data=[_row(id="last_number@2")]),
        "name malformed": _wire(data=[_row(name="Last Number", id="Last Number@1")]),
        "bool version": _wire(data=[_row(version=True, id="last_number@True")]),
        "zero version": _wire(data=[_row(version=0, id="last_number@0")]),
        "unknown stage": _wire(data=[_row(stage="fold")]),
        "duplicate id": _wire(data=[_row(), _row()]),
        "args_schema not an object": _wire(data=[_row(args_schema=[])]),
        "blank summary": _wire(data=[_row(summary="  ")]),
    }


@pytest.mark.parametrize("case", sorted(_bad_wires()))
def test_operator_catalog_decode_rejects_bad_wire(case: str) -> None:
    with pytest.raises(sf.PlanningError, match="SF Engine operator catalog") as caught:
        decode_operator_catalog(_bad_wires()[case])

    assert caught.value.code == "invalid_catalogue"
    assert caught.value.permanent is True


def test_operator_catalog_decode_ignores_extra_keys_and_order() -> None:
    wire = _wire(data=[_row(id="b@1", name="b", extra=1), _row(id="a@1", name="a")], more=True)

    catalog = decode_operator_catalog(wire)

    assert [entry.id for entry in catalog.entries] == ["b@1", "a@1"]


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class _Engine:
    """A scripted `/v1/operators`: pops one response per request and records each."""

    def __init__(self, *responses: httpx.Response) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.responses.pop(0)


def _sync(
    engine: Callable[[httpx.Request], httpx.Response], clock: _Clock
) -> OperatorCatalogResource:
    http = httpx.Client(base_url=_BASE, transport=httpx.MockTransport(engine))
    return OperatorCatalogResource(http, clock=clock)


def _async(
    engine: Callable[[httpx.Request], httpx.Response], clock: _Clock
) -> AsyncOperatorCatalogResource:
    http = httpx.AsyncClient(base_url=_BASE, transport=httpx.MockTransport(engine))
    return AsyncOperatorCatalogResource(http, clock=clock)


def test_catalog_is_fetched_once_per_client_and_revalidated_with_etag() -> None:
    clock = _Clock()
    engine = _Engine(
        operators_response(),
        httpx.Response(304, headers={"Cache-Control": "public, max-age=300, must-revalidate"}),
        operators_response(etag='"v2"'),
    )
    resource = _sync(engine, clock)

    first = resource.load()
    assert len(engine.requests) == 1
    assert "if-none-match" not in engine.requests[0].headers
    assert engine.requests[0].url.path == "/v1/operators"

    clock.now = 10
    assert resource.load() is first
    assert len(engine.requests) == 1

    clock.now = 301
    assert resource.load() is first
    assert engine.requests[1].headers["if-none-match"] == '"v1"'

    clock.now = 602
    replaced = resource.load()
    assert replaced is not first
    assert engine.requests[2].headers["if-none-match"] == '"v1"'
    clock.now = 903
    engine.responses.append(httpx.Response(304))
    assert resource.load() is replaced
    assert engine.requests[3].headers["if-none-match"] == '"v2"'


def test_catalog_without_cache_control_revalidates_every_time() -> None:
    engine = _Engine(
        httpx.Response(200, json=OPERATOR_WIRE, headers={"ETag": '"v1"'}),
        httpx.Response(304),
    )
    resource = _sync(engine, _Clock())

    first = resource.load()
    assert resource.load() is first

    assert len(engine.requests) == 2


def test_catalog_without_etag_sends_no_conditional_header() -> None:
    engine = _Engine(
        httpx.Response(200, json=OPERATOR_WIRE),
        httpx.Response(200, json=OPERATOR_WIRE),
    )
    resource = _sync(engine, _Clock())

    resource.load()
    resource.load()

    assert "if-none-match" not in engine.requests[1].headers


class _FlakyEngine(_Engine):
    """Serves the scripted responses, then loses the network."""

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if not self.responses:
            self.requests.append(request)
            raise httpx.ConnectError("refused", request=request)
        return super().__call__(request)


def test_a_stale_catalog_is_never_served_when_revalidation_cannot_reach_the_engine() -> None:
    clock = _Clock()
    resource = _sync(_FlakyEngine(operators_response()), clock)
    resource.load()

    clock.now = 301
    with pytest.raises(sf.EngineUnavailableError) as caught:
        resource.load()

    assert caught.value.engine_url == _BASE


@pytest.mark.asyncio
async def test_async_stale_catalog_is_never_served_when_the_engine_is_unreachable() -> None:
    clock = _Clock()
    resource = _async(_FlakyEngine(operators_response()), clock)
    await resource.load()

    clock.now = 301
    with pytest.raises(sf.EngineUnavailableError) as caught:
        await resource.load()

    assert caught.value.engine_url == _BASE


def _refusals() -> dict[str, tuple[httpx.Response, type[Exception], dict[str, object]]]:
    return {
        "304 without a cache": (
            httpx.Response(304),
            sf.PlanningError,
            {"code": "engine_contract_error", "permanent": True, "status": 304},
        ),
        "unauthorized": (
            httpx.Response(401),
            sf.AuthenticationError,
            {"status": 401},
        ),
        "server error": (
            httpx.Response(500),
            sf.PlanningError,
            {"code": "engine_contract_error", "permanent": False, "status": 500},
        ),
        "not json": (
            httpx.Response(200, content=b"<html>"),
            sf.PlanningError,
            {"code": "invalid_catalogue", "permanent": True},
        ),
        "malformed catalog": (
            httpx.Response(200, json={"object": "list", "data": [{}]}),
            sf.PlanningError,
            {"code": "invalid_catalogue", "permanent": True},
        ),
    }


def _assert_refusal(caught: BaseException, expected: dict[str, object]) -> None:
    for name, value in expected.items():
        assert getattr(caught, name) == value


@pytest.mark.parametrize("case", sorted(_refusals()))
def test_catalog_refusals_are_typed(case: str) -> None:
    response, error, expected = _refusals()[case]
    resource = _sync(_Engine(response), _Clock())

    with pytest.raises(error) as caught:
        resource.load()

    _assert_refusal(caught.value, expected)


def test_a_missing_catalog_route_is_a_capability_error() -> None:
    resource = _sync(_Engine(httpx.Response(404)), _Clock())

    with pytest.raises(sf.EngineCapabilityError) as caught:
        resource.load()

    assert caught.value.code == "engine_capability_missing"
    assert caught.value.status == 404
    assert caught.value.permanent is True
    assert caught.value.details == {"path": "/v1/operators"}
    assert caught.value.hint is not None
    assert "GET /v1/operators" in caught.value.hint


@pytest.mark.asyncio
async def test_async_catalog_is_cached_and_revalidated() -> None:
    clock = _Clock()
    engine = _Engine(
        operators_response(),
        httpx.Response(304, headers={"Cache-Control": "public, max-age=300, must-revalidate"}),
    )
    resource = _async(engine, clock)

    first = await resource.load()
    clock.now = 10
    assert await resource.load() is first
    clock.now = 301
    assert await resource.load() is first

    assert len(engine.requests) == 2
    assert engine.requests[1].headers["if-none-match"] == '"v1"'


def _operators_engine(paths: list[str]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/v1/operators":
            return operators_response()
        return _engine(request)

    return handler


def test_client_fetches_the_catalog_once_for_repeated_reducer_evaluations() -> None:
    paths: list[str] = []
    transport = _ReplayTransport()
    client = sf.Client(
        engine_url=_BASE,
        http_transport=httpx.MockTransport(_operators_engine(paths)),
        run_transport=transport,
    )

    with client:
        client.evaluate(reducer_fusion(), benchmark="draco", progress=False)
        client.evaluate(reducer_fusion(extract="boxed"), benchmark="draco", progress=False)

    assert paths.count("/v1/operators") == 1
    assert transport.candidate is not None
    assert "ensemble/combine/v1" in transport.candidate.url4
    assert transport.candidate.models == ("provider/a", "provider/b", "provider/c")


def _plain_fusion() -> sf.Recipe:
    return sf.Fanout([sf.Model("provider/opus"), sf.Model("provider/judge")]) >> sf.Synthesize(
        "provider/opus"
    )


def test_engine_without_catalog_raises_capability_error_only_for_reducers() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return _engine(request)

    transport = _ReplayTransport()
    client = sf.Client(
        engine_url=_BASE, http_transport=httpx.MockTransport(handler), run_transport=transport
    )

    with client:
        with pytest.raises(sf.EngineCapabilityError) as caught:
            client.evaluate(reducer_fusion(), benchmark="draco", progress=False)
        assert transport.candidate is None
        asked = paths.count("/v1/operators")
        client.evaluate(_plain_fusion(), benchmark="draco", progress=False)
        assert paths.count("/v1/operators") == asked

    assert caught.value.code == "engine_capability_missing"
    assert caught.value.status == 404
    assert isinstance(caught.value, sf.PlanningError)
    assert caught.value.message == "this SF Engine does not support reducers"
    assert asked == 1
    assert transport.candidate is not None


def test_unknown_operator_through_a_client_fails_before_the_run_starts() -> None:
    transport = _ReplayTransport()
    client = sf.Client(
        engine_url=_BASE,
        http_transport=httpx.MockTransport(_operators_engine([])),
        run_transport=transport,
    )

    with client, pytest.raises(ValueError, match="'last_numbr'"):
        client.evaluate(reducer_fusion(extract="last_numbr"), benchmark="draco", progress=False)

    assert transport.candidate is None
