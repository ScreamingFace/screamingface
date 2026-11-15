from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from screamingface._engine.limits import (
    DEFAULT_CALLER_INFLIGHT_CAP,
    caller_inflight_cap_async,
    caller_inflight_cap_sync,
)

BASE_URL = "http://engine.test"

Handler = Callable[[httpx.Request], httpx.Response]


def _answer(status: int, body: bytes) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=body, request=request)

    return handler


def _json_answer(body: object) -> Handler:
    return _answer(200, json.dumps(body).encode())


def _connect_error(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("down", request=request)


def _runtime_error(request: httpx.Request) -> httpx.Response:
    raise RuntimeError("auth flow")


CASES = [
    pytest.param(_json_answer({"caller_inflight_cap": 24}), 24, id="cap-24"),
    pytest.param(_json_answer({"caller_inflight_cap": 1}), 1, id="cap-1"),
    pytest.param(_answer(404, b"{}"), DEFAULT_CALLER_INFLIGHT_CAP, id="404"),
    pytest.param(_answer(500, b"boom"), DEFAULT_CALLER_INFLIGHT_CAP, id="500"),
    pytest.param(_connect_error, DEFAULT_CALLER_INFLIGHT_CAP, id="connect-error"),
    pytest.param(_runtime_error, DEFAULT_CALLER_INFLIGHT_CAP, id="any-exception"),
    pytest.param(_answer(200, b"not json"), DEFAULT_CALLER_INFLIGHT_CAP, id="not-json"),
    pytest.param(_json_answer([24]), DEFAULT_CALLER_INFLIGHT_CAP, id="not-object"),
    pytest.param(_json_answer({"caller_inflight_cap": 0}), DEFAULT_CALLER_INFLIGHT_CAP, id="zero"),
    pytest.param(
        _json_answer({"caller_inflight_cap": -3}), DEFAULT_CALLER_INFLIGHT_CAP, id="negative"
    ),
    pytest.param(
        _json_answer({"caller_inflight_cap": True}), DEFAULT_CALLER_INFLIGHT_CAP, id="bool"
    ),
    pytest.param(
        _json_answer({"caller_inflight_cap": "24"}), DEFAULT_CALLER_INFLIGHT_CAP, id="string"
    ),
    pytest.param(
        _json_answer({"caller_inflight_cap": 24.0}), DEFAULT_CALLER_INFLIGHT_CAP, id="float"
    ),
    pytest.param(
        _json_answer({"caller_inflight_cap": None}), DEFAULT_CALLER_INFLIGHT_CAP, id="null"
    ),
    pytest.param(_json_answer({}), DEFAULT_CALLER_INFLIGHT_CAP, id="missing"),
]


def _recording(handler: Handler, seen: list[httpx.Request]) -> Handler:
    def recorded(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return recorded


def test_default_cap_is_the_pre_ome_1314_fan_out() -> None:
    assert DEFAULT_CALLER_INFLIGHT_CAP == 8


@pytest.mark.parametrize(("handler", "expected"), CASES)
def test_sync_reader_returns_engine_cap_or_default(handler: Handler, expected: int) -> None:
    seen: list[httpx.Request] = []
    transport = httpx.MockTransport(_recording(handler, seen))

    with httpx.Client(base_url=BASE_URL, transport=transport) as http:
        assert caller_inflight_cap_sync(http) == expected

    assert [(request.method, request.url.path) for request in seen] == [("GET", "/v1/limits")]


@pytest.mark.asyncio
@pytest.mark.parametrize(("handler", "expected"), CASES)
async def test_async_reader_returns_engine_cap_or_default(handler: Handler, expected: int) -> None:
    seen: list[httpx.Request] = []
    transport = httpx.MockTransport(_recording(handler, seen))

    async with httpx.AsyncClient(base_url=BASE_URL, transport=transport) as http:
        assert await caller_inflight_cap_async(http) == expected

    assert [(request.method, request.url.path) for request in seen] == [("GET", "/v1/limits")]
