"""An exception that escapes every route is logged once, sanitized, and attributable (OME-939).

Before this, an unhandled exception outside the chat route became Starlette's plain-text 500:
no aigateway log line, no `gateway_call_id`, nothing an operator could tie back to a request.

The property that makes this easy to build wrong: Starlette runs an `Exception` handler from
`ServerErrorMiddleware`, which is OUTSIDE `CallIdMiddleware`. By then the call scope has unwound,
so a handler that just calls `logger.error` emits a line with NO id — exactly the defect this
fixes, reintroduced one layer out. These tests therefore drive the real app stack and assert on
the id the record actually carries, not on what the handler was told.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from aigateway.call_context import record_call_id, record_trace_id
from aigateway.unhandled_errors import unhandled_exception_handler

PROVIDER_TEXT = "upstream said: sk-live-SECRET and the user's prompt"
"""Text that must never reach a log line or a response — stands in for provider/prompt content."""


class _CapturingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def captured() -> Iterator[_CapturingHandler]:
    # WHY on the `aigateway` logger and not caplog's root handler: `logs.configure` turns
    # propagation off for the app tree, so the root never sees these records.
    handler = _CapturingHandler()
    logger = logging.getLogger("aigateway")
    logger.addHandler(handler)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)


@pytest.fixture
def boom_client(client: TestClient) -> TestClient:
    async def boom() -> None:
        raise RuntimeError(PROVIDER_TEXT)

    async def accounted() -> None:
        raise HTTPException(status_code=409, detail={"code": "conflict", "message": "nope"})

    client.app.add_api_route("/__test__/boom", boom, methods=["GET"])  # type: ignore[attr-defined]
    client.app.add_api_route("/__test__/accounted", accounted, methods=["GET"])  # type: ignore[attr-defined]
    # WHY a second client over the same app: the fixture's client re-raises server exceptions
    # into the test, which is the opposite of observing what a real caller receives.
    return TestClient(client.app, raise_server_exceptions=False, client=("10.1.2.3", 50000))


def _errors(handler: _CapturingHandler) -> list[logging.LogRecord]:
    return [r for r in handler.records if r.levelno >= logging.ERROR]


def test_an_unhandled_exception_returns_a_structured_500_naming_the_call(boom_client) -> None:
    response = boom_client.get("/__test__/boom")

    assert response.status_code == 500
    detail = response.json()["detail"]
    assert detail["code"] == "gateway_internal_error"
    assert detail["gateway_call_id"].startswith("call_")
    # The streaming-safe correlation channel is kept even though this response bypassed the
    # middleware's send wrapper.
    assert response.headers["x-aigw-trace-id"]
    assert PROVIDER_TEXT not in response.text


def test_it_logs_exactly_one_sanitized_record_carrying_the_call_id(boom_client, captured) -> None:
    response = boom_client.get("/__test__/boom")

    errors = _errors(captured)
    assert len(errors) == 1
    record = errors[0]
    # INVARIANT: the record's OWN stamped id — what the formatter renders — matches the body.
    assert record_call_id(record) == response.json()["detail"]["gateway_call_id"]
    assert record_trace_id(record) == response.headers["x-aigw-trace-id"]
    message = record.getMessage()
    assert "type=RuntimeError" in message
    assert "status_code=500" in message
    assert "path=/__test__/boom" in message
    # INVARIANT: class-name-only posture — no provider text, no traceback.
    assert PROVIDER_TEXT not in message
    assert record.exc_info is None
    assert record.exc_text is None


def test_an_accounted_http_exception_is_not_rewrapped(boom_client, captured) -> None:
    response = boom_client.get("/__test__/accounted")

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "conflict", "message": "nope"}}
    assert _errors(captured) == []


@pytest.mark.asyncio
async def test_without_published_ids_the_500_is_still_structured(captured) -> None:
    request = Request({"type": "http", "method": "GET", "path": "/x", "headers": []})

    response = await unhandled_exception_handler(request, ValueError(PROVIDER_TEXT))

    assert response.status_code == 500
    assert b"gateway_call_id" not in response.body
    assert b'"code":"gateway_internal_error"' in response.body
    assert "x-aigw-trace-id" not in response.headers
    [record] = _errors(captured)
    assert record_call_id(record) is None
    assert "type=ValueError" in record.getMessage()
