"""The total body cap, enforced before anything parses the body.

The cases that matter are the ones a route dependency cannot cover: a body that never reaches a
handler at all, and a chunked body whose size is not knowable in advance.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.types import Message, Receive, Scope, Send

from report_intake.core.body_limit import BodyLimitMiddleware
from report_intake.core.problem import PROBLEM_MEDIA_TYPE

_CAP = 1024


def _post_scope() -> Scope:
    return {"type": "http", "method": "POST", "path": "/echo", "headers": []}


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = FastAPI()
    app.add_middleware(BodyLimitMiddleware, max_bytes=_CAP)

    @app.post("/echo")
    async def echo(request: Request) -> dict[str, int]:
        return {"bytes": len(await request.body())}

    @app.get("/echo")
    async def echo_get() -> dict[str, str]:
        return {"status": "ok"}

    with TestClient(app) as test_client:
        yield test_client


def _chunks(total: int, size: int = 256) -> Iterator[bytes]:
    """A body with no `Content-Length`: httpx sends an iterable as `Transfer-Encoding: chunked`."""
    sent = 0
    while sent < total:
        chunk = min(size, total - sent)
        sent += chunk
        yield b"x" * chunk


def test_a_body_over_the_cap_is_refused_with_the_cap_named_in_the_detail(
    client: TestClient,
) -> None:
    response = client.post("/echo", content=b"x" * (_CAP + 1))

    assert response.status_code == 413
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    assert str(_CAP) in response.json()["detail"]


def test_a_body_exactly_at_the_cap_is_allowed_through(client: TestClient) -> None:
    """Off-by-one in the safe direction is still a bug: the cap is a limit, not a threshold one
    byte below it."""
    response = client.post("/echo", content=b"x" * _CAP)

    assert response.status_code == 200
    assert response.json() == {"bytes": _CAP}


def test_an_oversized_body_never_reaches_the_handler(client: TestClient) -> None:
    """The point of doing this pre-routing: the refusal happens without the body being read, so
    the cap bounds work rather than merely reporting on it."""
    response = client.post("/echo", content=b"x" * (_CAP * 10))

    assert response.status_code == 413


def test_a_chunked_body_that_grows_past_the_cap_is_refused(client: TestClient) -> None:
    """No `Content-Length` to check, so this is the path that has to count as it reads — and it
    is the path an attacker picks."""
    response = client.post("/echo", content=_chunks(_CAP * 4))

    assert response.status_code == 413


def test_a_chunked_body_under_the_cap_is_replayed_to_the_handler_intact(
    client: TestClient,
) -> None:
    """Counting means buffering, and a buffer that is not handed back is a request body that
    silently arrives empty."""
    response = client.post("/echo", content=_chunks(_CAP - 1))

    assert response.status_code == 200
    assert response.json() == {"bytes": _CAP - 1}


def test_a_lying_content_length_header_is_treated_as_absent(client: TestClient) -> None:
    """A header that is not an integer is a framing problem, not a report problem; answering it
    with this service's 413 would blame the wrong thing, so the counting path decides instead."""
    response = client.post("/echo", content=b"x" * 8, headers={"content-length": "not-a-number"})

    assert response.status_code == 200


def test_a_request_with_no_body_at_all_is_untouched(client: TestClient) -> None:
    response = client.get("/echo")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_a_client_that_disconnects_mid_body_is_not_handed_on_as_a_complete_request() -> None:
    """A partial body replayed to the app looks to it like a whole one, which is how a truncated
    report becomes a stored report."""
    reached: list[str] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        reached.append(scope["path"])

    messages: list[Message] = [
        {"type": "http.request", "body": b"partial", "more_body": True},
        {"type": "http.disconnect"},
    ]

    async def receive() -> Message:
        return messages.pop(0)

    async def send(message: Message) -> None:
        raise AssertionError(f"nothing should be sent to a disconnected client: {message}")

    await BodyLimitMiddleware(app, max_bytes=_CAP)(_post_scope(), receive, send)

    assert reached == []


@pytest.mark.asyncio
async def test_a_replayed_body_reports_the_stream_closed_once_it_is_delivered() -> None:
    """A `receive` that hands the same chunk out forever hangs any handler that reads to the end
    of the stream."""
    seen: list[Message] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append(await receive())
        seen.append(await receive())

    async def receive() -> Message:
        return {"type": "http.request", "body": b"hello", "more_body": False}

    async def send(message: Message) -> None:
        return None

    await BodyLimitMiddleware(app, max_bytes=_CAP)(_post_scope(), receive, send)

    assert seen[0]["body"] == b"hello"
    assert seen[1]["type"] == "http.disconnect"


@pytest.mark.asyncio
async def test_a_websocket_scope_is_passed_straight_through() -> None:
    """The middleware is mounted on the whole app; a scope with no `method` must not raise."""
    reached: list[str] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        reached.append(scope["type"])

    async def receive() -> Message:  # pragma: no cover - never called
        raise AssertionError("a passed-through scope must not be read")

    async def send(message: Message) -> None:  # pragma: no cover - never called
        raise AssertionError("a passed-through scope must not be written")

    websocket_scope: Scope = {"type": "websocket", "path": "/ws"}
    await BodyLimitMiddleware(app, max_bytes=_CAP)(websocket_scope, receive, send)

    assert reached == ["websocket"]
