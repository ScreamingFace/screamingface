"""Every fallback of the cap read says why, at DEBUG, without the body (#1745 review).

When `GET /v1/limits` fails, the Client runs 8 Candidates at once. Without a log line, a user on a
current Engine behind a proxy that drops the route sees "only 8 run at once" and no cause.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable

import httpx
import pytest

from screamingface._engine.limits import (
    DEFAULT_CALLER_INFLIGHT_CAP,
    caller_inflight_cap_async,
    caller_inflight_cap_sync,
)

BASE_URL = "http://engine.test"
LOGGER = "screamingface._engine.limits"
SECRET = "caller-private-body-text"

Handler = Callable[[httpx.Request], httpx.Response]


def _answer(status: int, body: bytes) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=body, request=request)

    return handler


def _connect_error(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError(SECRET, request=request)


FALLBACKS = [
    pytest.param(_answer(404, SECRET.encode()), "HTTP 404", id="404"),
    pytest.param(
        _answer(200, SECRET.encode()),
        "not JSON with a positive integer caller_inflight_cap, HTTP 200",
        id="not-json",
    ),
    pytest.param(
        _answer(200, json.dumps({"caller_inflight_cap": 0, "note": SECRET}).encode()),
        "not JSON with a positive integer caller_inflight_cap, HTTP 200",
        id="bad-value",
    ),
    pytest.param(_connect_error, "request failed: ConnectError", id="transport-error"),
]


def _debug_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        r.getMessage() for r in caplog.records if r.name == LOGGER and r.levelno == logging.DEBUG
    ]


@pytest.mark.parametrize(("handler", "cause"), FALLBACKS)
def test_a_sync_fallback_logs_its_cause_once(
    handler: Handler, cause: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    with httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(handler)) as http:
        assert caller_inflight_cap_sync(http) == DEFAULT_CALLER_INFLIGHT_CAP

    lines = _debug_lines(caplog)
    assert len(lines) == 1
    assert cause in lines[0]
    assert "/v1/limits" in lines[0]
    assert f"at most {DEFAULT_CALLER_INFLIGHT_CAP} Candidates" in lines[0]
    assert SECRET not in lines[0], "the log line must never carry the body or error text"


@pytest.mark.asyncio
@pytest.mark.parametrize(("handler", "cause"), FALLBACKS)
async def test_an_async_fallback_logs_its_cause_once(
    handler: Handler, cause: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    async with httpx.AsyncClient(base_url=BASE_URL, transport=httpx.MockTransport(handler)) as http:
        assert await caller_inflight_cap_async(http) == DEFAULT_CALLER_INFLIGHT_CAP

    lines = _debug_lines(caplog)
    assert len(lines) == 1
    assert cause in lines[0]
    assert SECRET not in lines[0]


def test_a_read_cap_logs_nothing(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    handler = _answer(200, json.dumps({"caller_inflight_cap": 24}).encode())
    with httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(handler)) as http:
        assert caller_inflight_cap_sync(http) == 24

    assert _debug_lines(caplog) == []
