"""The request body cap (OME-1542).

# FEATURE: image and file input across the gateway (OME-1529) — bodies are now megabytes long.
# STORY: as a gateway operator, a caller cannot make the gateway hold an unbounded body in memory;
# as a benchmark author whose Case trips the cap, the 413 tells me the limit.
# INVARIANT: the cap is enforced on the bytes actually delivered, so a missing, lying or chunked
# Content-Length cannot bypass it, and the app is never handed more than the limit.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from starlette.types import Message, Receive, Scope, Send

from aigateway.middleware.body_cap import BodyCapMiddleware, RequestBodyTooLarge


def _scope(path: str = "/v1/chat/completions", headers: list[tuple[bytes, bytes]] | None = None):
    return {
        "type": "http",
        "method": "POST",
        "path": path,
        "headers": headers or [],
    }


class _Recorder:
    """An inner app that reads the whole body, then answers 200 with the byte count."""

    def __init__(self) -> None:
        self.called = False
        self.received = 0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        self.called = True
        more = True
        while more:
            message = await receive()
            self.received += len(message.get("body", b""))
            more = message.get("more_body", False)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": str(self.received).encode()})


def _run(
    app: Any, scope: Scope, chunks: list[bytes]
) -> tuple[int, dict[str, Any] | bytes, list[Message]]:
    pending = list(chunks)
    sent: list[Message] = []

    async def receive() -> Message:
        if not pending:
            return {"type": "http.disconnect"}
        body = pending.pop(0)
        return {"type": "http.request", "body": body, "more_body": bool(pending)}

    async def send(message: Message) -> None:
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    raw = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    try:
        return status, json.loads(raw), sent
    except ValueError:
        return status, raw, sent


def test_a_declared_length_over_the_limit_is_refused_without_reading() -> None:
    inner = _Recorder()
    app = BodyCapMiddleware(inner, max_bytes=10)

    status, body, _ = _run(app, _scope(headers=[(b"content-length", b"11")]), [b"x" * 11])

    assert status == 413
    assert inner.called is False
    assert isinstance(body, dict)
    assert body["detail"]["code"] == "request_too_large"
    assert body["detail"]["limit_bytes"] == 10


def test_a_chunked_body_over_the_limit_is_refused_and_the_app_never_sees_past_it() -> None:
    inner = _Recorder()
    app = BodyCapMiddleware(inner, max_bytes=10)

    # no Content-Length at all: 4 chunks of 3 bytes = 12 bytes
    status, _, _ = _run(app, _scope(), [b"abc", b"def", b"ghi", b"jkl"])

    assert status == 413
    # INVARIANT: the chunk that would cross the limit is never handed to the app.
    assert inner.received <= 10


def test_a_lying_content_length_cannot_bypass_the_cap() -> None:
    inner = _Recorder()
    app = BodyCapMiddleware(inner, max_bytes=10)

    status, _, _ = _run(app, _scope(headers=[(b"content-length", b"5")]), [b"x" * 5, b"y" * 15])

    assert status == 413
    assert inner.received <= 10


def test_a_body_of_exactly_the_limit_passes() -> None:
    inner = _Recorder()
    app = BodyCapMiddleware(inner, max_bytes=10)

    status, body, _ = _run(app, _scope(headers=[(b"content-length", b"10")]), [b"x" * 6, b"y" * 4])

    assert status == 200
    assert body == 10


def test_an_unparsable_content_length_is_counted_not_trusted() -> None:
    inner = _Recorder()
    app = BodyCapMiddleware(inner, max_bytes=10)

    status, _, _ = _run(app, _scope(headers=[(b"content-length", b"nope")]), [b"x" * 11])

    assert status == 413


def test_the_413_names_the_limit_in_bytes_and_mebibytes() -> None:
    app = BodyCapMiddleware(_Recorder(), max_bytes=8 * 1024 * 1024)

    status, body, _ = _run(
        app, _scope(headers=[(b"content-length", str(9 * 1024 * 1024).encode())]), [b""]
    )

    assert status == 413
    assert isinstance(body, dict)
    message = body["detail"]["message"]
    assert "8388608 bytes" in message
    assert "8 MiB" in message


def test_a_downstream_layer_that_swallows_the_refusal_still_answers_413() -> None:
    async def swallowing(scope: Scope, receive: Receive, send: Send) -> None:
        try:
            while (await receive()).get("more_body", False):
                pass
        except RequestBodyTooLarge:
            pass  # a careless route: carries on as if the body were fine
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    app = BodyCapMiddleware(swallowing, max_bytes=4)

    status, body, sent = _run(app, _scope(), [b"abc", b"def"])

    # INVARIANT: fail closed — the caller gets the 413, never the 200 built on a truncated body.
    assert status == 413
    assert sum(1 for m in sent if m["type"] == "http.response.start") == 1
    assert isinstance(body, dict)
    assert body["detail"]["code"] == "request_too_large"


def test_a_refusal_raised_through_the_app_is_answered_by_the_middleware() -> None:
    async def propagating(scope: Scope, receive: Receive, send: Send) -> None:
        while (await receive()).get("more_body", False):
            pass

    app = BodyCapMiddleware(propagating, max_bytes=4)

    status, _, _ = _run(app, _scope(), [b"abc", b"def"])

    assert status == 413


def test_a_path_with_its_own_limit_uses_it() -> None:
    inner = _Recorder()
    app = BodyCapMiddleware(inner, max_bytes=10, path_limits={"/upload": 100})

    status, body, _ = _run(app, _scope(path="/upload"), [b"x" * 50])
    assert status == 200
    assert body == 50

    status, _, _ = _run(app, _scope(path="/upload"), [b"x" * 101])
    assert status == 413


def test_non_http_scopes_pass_through_untouched() -> None:
    seen: list[str] = []

    async def lifespan_app(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append(scope["type"])

    app = BodyCapMiddleware(lifespan_app, max_bytes=1)

    async def receive() -> Message:
        return {"type": "lifespan.startup"}

    async def send(_message: Message) -> None:
        return None

    asyncio.run(app({"type": "lifespan"}, receive, send))
    assert seen == ["lifespan"]


def test_the_refusal_is_an_http_413() -> None:
    exc = RequestBodyTooLarge(10)
    assert exc.status_code == 413
    assert exc.limit == 10
    assert "10 bytes" in str(exc.detail)


def test_reading_again_after_the_refusal_keeps_refusing() -> None:
    attempts: list[str] = []

    async def retrying(scope: Scope, receive: Receive, send: Send) -> None:
        for _ in range(2):
            try:
                while (await receive()).get("more_body", False):
                    pass
            except RequestBodyTooLarge:
                attempts.append("refused")

    app = BodyCapMiddleware(retrying, max_bytes=4)

    status, _, _ = _run(app, _scope(), [b"abc", b"def", b"ghi"])

    # INVARIANT: no read after the overflow ever returns more of the body.
    assert attempts == ["refused", "refused"]
    assert status == 413


def test_an_overflow_after_the_response_started_is_not_masked() -> None:
    async def answers_first(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        while (await receive()).get("more_body", False):
            pass

    app = BodyCapMiddleware(answers_first, max_bytes=4)

    # WHY: a started response cannot be replaced; the refusal propagates so the server aborts it.
    with pytest.raises(RequestBodyTooLarge):
        _run(app, _scope(), [b"abc", b"def"])
