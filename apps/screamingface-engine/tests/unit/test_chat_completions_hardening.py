"""Hardening of POST /v1/chat/completions after the design review of U4.

Review F1 (an unexpected error keeps the OpenAI envelope), F2 (nothing holds the input record
during the wait, CC-S35), F3 (a large body is parsed off the event loop), F7 (one log line per
request, prd §4 Observability) and F9 (a read time limit for a request that holds a parse place).
"""

from __future__ import annotations

import asyncio
import gc
import hashlib
import json
import logging
import re
import threading
import weakref
from collections.abc import AsyncIterator
from typing import Any

import pytest
from _chat_app import (
    EMAIL,
    TRACE_ID,
    TRACEPARENT,
    ChatApp,
    answered,
    asgi_call,
    asgi_scope,
    body,
    body_then,
    chat_app,
    cost_frame,
    error,
    padded,
    post,
    result_frame,
    stored_bytes,
    terminated_frame,
)

from screamingface_engine.artifacts.ports import RemoteStream
from screamingface_engine.rest import chat_body
from screamingface_engine.rest.chat_body import ParseGate
from url4.streaming.protocol.signals import ResultArtifact

pytestmark = pytest.mark.asyncio

ROUTE_LOGGERS = "screamingface_engine.rest.chat"
LINE_LOGGER = "screamingface_engine.rest.chat_observe"
MARKER = "sk-live-chat-marker-5d1c"
ARTIFACT = ResultArtifact(id="cd" * 32, size_bytes=10, sha256="cd" * 32)
TRACED = {**EMAIL, "traceparent": TRACEPARENT}


def _outcomes(ca: ChatApp, outcome: str) -> float | None:
    return ca.app.state.metrics.registry.get_sample_value(
        "screamingface_engine_chat_requests_total", {"outcome": outcome}
    )


def _errors(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        r for r in caplog.records if r.name.startswith(ROUTE_LOGGERS) and r.levelno >= logging.ERROR
    ]


def _assert_internal_error(resp: Any) -> None:
    assert resp.status_code == 500
    assert error(resp)["code"] == "internal_error"
    assert error(resp)["message"] == "the request failed"
    assert error(resp)["type"] == "server_error"
    assert resp.headers["x-should-retry"] == "false"
    assert resp.headers["content-type"].startswith("application/json")


async def test_an_unexpected_scan_error_answers_500_internal_error_and_cleans_up(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    ca = chat_app(None)

    async def broken(topic: str, from_sequence: int | None = None) -> AsyncIterator[Any]:
        raise RuntimeError("scan detail " + MARKER)
        yield

    monkeypatch.setattr(ca.stream, "subscribe", broken)
    caplog.set_level(logging.DEBUG)
    resp = await post(ca.app, body(), headers=TRACED)

    _assert_internal_error(resp)
    assert ca.runner.stopped == [ca.runner.scheduled[0]["topic"]]
    assert ca.objects.objects == {}
    assert _outcomes(ca, "internal_error") == 1.0
    errors = _errors(caplog)
    assert len(errors) == 1
    assert "RuntimeError" in errors[0].getMessage()
    assert TRACE_ID in errors[0].getMessage()
    assert errors[0].exc_info is None
    assert MARKER not in caplog.text


async def test_an_artifact_read_that_raises_answers_500_and_deletes_the_blob(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def frames(topic: str) -> list[Any]:
        return [cost_frame(topic), result_frame(topic, artifact=ARTIFACT), terminated_frame(topic)]

    async def chunks() -> AsyncIterator[bytes]:
        yield b"x" * 1_000_000
        raise ValueError("store detail " + MARKER)

    ca = chat_app(frames)
    ca.app.state.artifact_store.content = lambda artifact_id: RemoteStream(
        stream=chunks(), size_bytes=4_000_000
    )
    caplog.set_level(logging.DEBUG)
    resp = await post(ca.app, body(), headers=TRACED)

    _assert_internal_error(resp)
    assert ca.runner.stopped == []
    assert ca.objects.objects == {}
    assert _outcomes(ca, "internal_error") == 1.0
    assert len(_errors(caplog)) == 1
    assert "ValueError" in _errors(caplog)[0].getMessage()
    assert MARKER not in caplog.text


async def test_a_client_that_leaves_during_the_body_read_is_client_disconnected(
    caplog: pytest.LogCaptureFixture,
) -> None:
    ca = chat_app(answered())
    gone = asyncio.Event()
    gone.set()
    receive = body_then(b'{"model": "prov/a", ', gone, more_body=True)
    caplog.set_level(logging.DEBUG)
    await asyncio.wait_for(asgi_call(ca.app, asgi_scope(None), receive), 3.0)

    assert ca.runner.attempted == []
    assert ca.objects.objects == {}
    assert _outcomes(ca, "client_disconnected") == 1.0
    assert _outcomes(ca, "internal_error") is None
    assert _errors(caplog) == []


def _watch_parse(monkeypatch: pytest.MonkeyPatch, ca: ChatApp) -> dict[str, Any]:
    """Keeps a weak reference to the parsed request and the encoded record of the next request;
    the store keeps a copy of the record, so only the route can hold the original."""
    held: dict[str, Any] = {}
    real_input, real_encode = chat_body.chat_input_from_request, chat_body.encode_chat_input

    def chat_input(parsed: Any) -> Any:
        held["parsed"] = weakref.ref(parsed)
        return real_input(parsed)

    def encode(value: Any) -> bytes:
        held["record"] = real_encode(value)
        return held["record"]

    def put(key: str, data: bytes) -> None:
        ca.objects.objects[key] = bytes(bytearray(data))

    monkeypatch.setattr(chat_body, "chat_input_from_request", chat_input)
    monkeypatch.setattr(chat_body, "encode_chat_input", encode)
    monkeypatch.setattr(ca.objects, "put", put)
    return held


async def _until_scheduled(ca: ChatApp) -> None:
    for _ in range(300):
        if ca.runner.scheduled:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("the run was never scheduled")


async def test_nothing_holds_the_record_or_the_parsed_request_after_the_schedule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CC-S35: the parsed objects live only until the blob is written."""
    ca = chat_app(None, chat_max_wait_s=30.0)
    held = _watch_parse(monkeypatch, ca)
    raw = json.dumps(body()).encode()
    gone = asyncio.Event()
    call = asyncio.ensure_future(asgi_call(ca.app, asgi_scope(len(raw)), body_then(raw, gone)))
    try:
        await _until_scheduled(ca)
        gc.collect()
        assert held["parsed"]() is None
        holders = [type(r).__name__ for r in gc.get_referrers(held["record"]) if r is not held]
        assert holders == []
    finally:
        gone.set()
        await asyncio.wait_for(call, 3.0)


async def test_a_large_body_is_parsed_off_the_loop_while_it_holds_its_place(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ca = chat_app(answered())
    gate = ParseGate(places=1, wait_s=0.01)
    ca.app.state.chat_parse_gate = gate
    real = chat_body._checked
    threads: list[int] = []
    started, release = threading.Event(), threading.Event()

    def parse(raw: bytes) -> Any:
        threads.append(threading.get_ident())
        started.set()
        release.wait(2)
        return real(raw)

    monkeypatch.setattr(chat_body, "_checked", parse)
    call = asyncio.ensure_future(post(ca.app, padded(body(), 1_200_000)))
    try:
        assert await asyncio.to_thread(started.wait, 3)
        assert await gate.acquire() is False
    finally:
        release.set()
    assert (await call).status_code == 200
    assert threads[0] != threading.get_ident()

    assert (await post(ca.app, body())).status_code == 200
    assert threads[1] == threading.get_ident()


async def test_one_log_line_per_request_with_its_facts_and_no_content(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """prd §4 Observability: one INFO line per request; never message content or identity."""
    ca = chat_app(answered())
    caplog.set_level(logging.DEBUG)
    messages = [
        {"role": "system", "content": "Be brief " + MARKER},
        {"role": "user", "content": MARKER},
    ]
    raw = json.dumps(body(messages=messages)).encode()
    resp = await post(ca.app, raw, headers=TRACED)
    assert resp.status_code == 200

    lines = [r for r in caplog.records if r.name == LINE_LOGGER]
    assert len(lines) == 1
    assert lines[0].levelno == logging.INFO
    line = lines[0].getMessage()
    digest = hashlib.sha256(stored_bytes(ca.runner.inputs[0])).hexdigest()
    topic = ca.runner.scheduled[0]["topic"]
    for part in (
        "outcome=ok",
        "status=200",
        f"trace_id={TRACE_ID}",
        f"digest=sha256:{digest}",
        f"size={len(raw)}",
        "messages=2",
    ):
        assert part in line
    assert re.search(r"duration_s=\d+\.\d{3}", line)
    # INVARIANT: the topic gives access to the run, so the request line never holds it.
    assert topic not in line
    for record in caplog.records:
        assert MARKER not in record.getMessage()
        assert EMAIL["X-User-Email"] not in record.getMessage()


async def test_a_refused_request_has_its_log_line_too(caplog: pytest.LogCaptureFixture) -> None:
    ca = chat_app(answered())
    caplog.set_level(logging.INFO)
    resp = await post(ca.app, body(), headers={"Content-Type": "application/json"})
    assert resp.status_code == 401
    lines = [r.getMessage() for r in caplog.records if r.name == LINE_LOGGER]
    assert len(lines) == 1
    assert "outcome=identity_required" in lines[0]
    assert "status=401" in lines[0]
    assert "topic" not in lines[0]


async def test_a_slow_body_that_holds_a_place_gives_it_back_and_answers_408(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review F9: the rest of the body must arrive in time once the request holds a place."""
    monkeypatch.setattr(chat_body, "_PARSE_PLACE_READ_TIMEOUT_S", 0.05)
    ca = chat_app(answered())
    gate = ParseGate(places=1, wait_s=0.01)
    ca.app.state.chat_parse_gate = gate
    never = asyncio.Event()
    receive = body_then(b"{" + b" " * 1_100_000, never, more_body=True)

    sent = await asyncio.wait_for(asgi_call(ca.app, asgi_scope(2_000_000), receive), 3.0)

    start = next(m for m in sent if m["type"] == "http.response.start")
    headers = {k.decode(): v.decode() for k, v in start["headers"]}
    envelope = json.loads(b"".join(m.get("body", b"") for m in sent[1:]))["error"]
    assert start["status"] == 408
    assert envelope["code"] == "request_timeout"
    assert envelope["type"] == "invalid_request_error"
    assert headers["x-should-retry"] == "false"
    assert ca.runner.attempted == []
    assert ca.objects.objects == {}
    assert await gate.acquire() is True
