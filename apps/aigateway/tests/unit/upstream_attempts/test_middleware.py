"""The attempt-header middleware on its own (contract C7, test-plan §4 item 9).

# FEATURE: Router Recipe extension Unit 5.1 — every non-streaming `POST /v1/chat/completions` and
# `POST /v1/classifications` answer carries `X-AIGW-Upstream-Attempts`, success or error.
# INVARIANT: the counter is bound before the inner app runs and only mutated after, so sends made
# in a task that a `BaseHTTPMiddleware` starts still reach the header.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from aigateway.core.upstream_attempts import record_send
from aigateway.middleware.upstream_attempts import UpstreamAttemptsMiddleware

HEADER = "x-aigw-upstream-attempts"
CHAT = "/v1/chat/completions"
CLASSIFY = "/v1/classifications"


async def _send(n: int) -> None:
    request = httpx.Request("POST", "https://provider.example/v1/chat/completions")
    for _ in range(n):
        await record_send(request)


class _TaskBoundary(BaseHTTPMiddleware):
    """Like the auth-disabled guard: the inner app runs in a task this layer starts."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        return await call_next(request)


def _app() -> FastAPI:
    app = FastAPI()

    @app.post(CHAT)
    async def chat(request: Request) -> Any:
        body = json.loads(await request.body() or b"{}")
        sends = int(body.get("sends", 0))
        # WHY a separate task: the counter must survive one more task boundary below the route.
        await asyncio.create_task(_send(sends))
        if body.get("stream"):

            async def events() -> AsyncIterator[bytes]:
                yield b"data: {}\n\n"

            return StreamingResponse(events(), media_type="text/event-stream")
        if body.get("fail"):
            raise HTTPException(status_code=502, detail={"code": "provider_error"})
        if body.get("crash"):
            raise RuntimeError("unhandled")
        return JSONResponse({"ok": True})

    @app.post(CLASSIFY)
    async def classify(request: Request) -> Any:
        await _send(int(json.loads(await request.body())["sends"]))
        return JSONResponse({"ok": True})

    @app.post("/v1/other")
    async def other() -> Any:
        await _send(1)
        return JSONResponse({"ok": True})

    @app.get(CHAT)
    async def chat_get() -> Any:
        return JSONResponse({"ok": True})

    app.add_middleware(_TaskBoundary)
    app.add_middleware(UpstreamAttemptsMiddleware)
    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(_app(), raise_server_exceptions=False)


@pytest.mark.parametrize("path", [CHAT, CLASSIFY])
@pytest.mark.parametrize("sends", [0, 1, 2])
def test_the_header_counts_sends_across_task_boundaries(
    client: TestClient, path: str, sends: int
) -> None:
    response = client.post(path, json={"sends": sends})

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert response.headers[HEADER] == str(sends)


def test_a_handled_error_carries_the_count(client: TestClient) -> None:
    response = client.post(CHAT, json={"sends": 1, "fail": True})

    assert response.status_code == 502
    assert response.json() == {"detail": {"code": "provider_error"}}
    assert response.headers[HEADER] == "1"


def test_an_unhandled_error_never_reaches_the_middleware_with_a_count(client: TestClient) -> None:
    # WHY absent: Starlette's outermost server-error layer answers it, outside user middleware.
    response = client.post(CHAT, json={"sends": 1, "crash": True})

    assert response.status_code == 500
    assert HEADER not in response.headers


def test_a_streaming_answer_is_unchanged(client: TestClient) -> None:
    response = client.post(CHAT, json={"sends": 1, "stream": True})

    assert response.headers["content-type"].startswith("text/event-stream")
    assert HEADER not in response.headers


def test_other_routes_and_methods_carry_no_header(client: TestClient) -> None:
    assert HEADER not in client.post("/v1/other").headers
    assert HEADER not in client.get(CHAT).headers


def test_a_root_path_is_stripped_before_matching() -> None:
    client = TestClient(_app(), root_path="/gw")

    response = client.post(f"/gw{CHAT}", json={"sends": 2})

    assert response.status_code == 200
    assert response.headers[HEADER] == "2"


def _answer_headers(path: str, root_path: str = "") -> dict[bytes, bytes]:
    """The response-start headers the middleware sends for a POST to `path` with no send."""

    async def app_probe(scope: Any, receive: Any, send: Any) -> None:
        del scope, receive
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = UpstreamAttemptsMiddleware(app_probe)
    messages: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Any) -> None:
        messages.append(message)

    scope = {"type": "http", "method": "POST", "path": path, "root_path": root_path, "headers": []}
    asyncio.run(middleware(scope, receive, send))
    return dict(messages[0]["headers"])


def test_a_prefix_that_is_not_a_whole_segment_is_not_stripped() -> None:
    assert HEADER.encode() not in _answer_headers(f"/gwx{CHAT}", root_path="/gw")


REPLAY_CHAT = "/v1/frozen-copies/c0py/chat/completions"
# WHY listed before its route exists: Unit 6 (C9) adds classification replay, and its answers
# must carry the header from the first release that serves them.
REPLAY_CLASSIFY = "/v1/frozen-copies/c0py/classifications"


@pytest.mark.parametrize(
    ("path", "root_path"),
    [
        (CHAT, ""),
        (CLASSIFY, ""),
        (REPLAY_CHAT, ""),
        (REPLAY_CLASSIFY, ""),
        (f"/gw{REPLAY_CLASSIFY}", "/gw"),
    ],
)
def test_the_live_and_replay_call_paths_are_counted(path: str, root_path: str) -> None:
    assert _answer_headers(path, root_path)[HEADER.encode()] == b"0"


@pytest.mark.parametrize(
    "path",
    [
        "/v1/frozen-copies",
        "/v1/frozen-copies/c0py/seal",
        "/v1/frozen-copies/c0py/tool-results/lookup",
        "/v1/frozen-copies//chat/completions",
        "/v1/frozen-copies/a/b/chat/completions",
        f"{REPLAY_CHAT}/more",
        f"{REPLAY_CLASSIFY}/",
        f"{CHAT}/",
        f"/v2{CHAT.removeprefix('/v1')}",
    ],
)
def test_no_other_path_is_counted(path: str) -> None:
    assert HEADER.encode() not in _answer_headers(path)


def test_an_upstream_header_of_the_same_name_is_replaced() -> None:
    app = FastAPI()

    @app.post(CHAT)
    async def chat() -> Any:
        return JSONResponse({"ok": True}, headers={HEADER: "99"})

    app.add_middleware(UpstreamAttemptsMiddleware)

    response = TestClient(app).post(CHAT, json={})

    assert response.headers.get_list(HEADER) == ["0"]
