"""The streamed answer of POST /v1/chat/completions (prd/streaming.md, unit U5).

ST-5, ST-6, ST-7, ST-9 and ST-11, the time limit (ST-S7), the drain (ST-S12), the usage chunk
(ST-S3) and the observation of a streamed request (prd/chat-completion.md §3.4).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

import pytest
from _chat_app import (
    MODEL,
    TRACE_ID,
    ChatApp,
    Script,
    answered,
    chat_app,
    cost_frame,
    ended,
    error,
    post,
    result_frame,
    terminated_frame,
)
from _chat_stream import (
    body_items,
    data_payloads,
    encoded,
    keep_alives,
    media_type,
    response_start,
    scheduled_topic,
    sent_payloads,
    start_stream,
    stream_body,
    wait_until,
)

from screamingface_engine.rest import chat_completions

pytestmark = pytest.mark.asyncio

LINE_LOGGER = "screamingface_engine.rest.chat_observe"
DONE = "[DONE]"


def _sample(ca: ChatApp, name: str, labels: dict[str, str] | None = None) -> float | None:
    return ca.app.state.metrics.registry.get_sample_value(name, labels or {})


def _outcomes(ca: ChatApp, outcome: str) -> float | None:
    return _sample(ca, "screamingface_engine_chat_requests_total", {"outcome": outcome})


def _chunks(payloads: list[dict[str, Any] | str]) -> list[dict[str, Any]]:
    return [p for p in payloads if isinstance(p, dict)]


async def _publish_answer(ca: ChatApp, topic: str) -> None:
    for frame in (cost_frame(topic), result_frame(topic), terminated_frame(topic)):
        await ca.stream.publish(topic, frame)


async def _streamed(script: Script, **extra: Any) -> tuple[ChatApp, Any]:
    ca = chat_app(script)
    resp = await post(ca.app, stream_body(**extra))
    return ca, resp


async def test_stream_sends_keep_alive_comments_until_result() -> None:
    """ST-5 / ST-S1: 200 text/event-stream at once, keep-alives while the run works, then the
    answer chunks and [DONE]."""
    ca = chat_app(None, chat_keepalive_s=0.01)
    call, sent = start_stream(ca, encoded(stream_body()), asyncio.Event())
    topic = await scheduled_topic(ca)
    await wait_until(lambda: keep_alives(sent) >= 2, what="two keep-alive comments")

    start = response_start(sent)
    assert start is not None
    assert start["status"] == 200
    headers = {k.decode(): v.decode() for k, v in start["headers"]}
    assert media_type(headers["content-type"]) == "text/event-stream"
    assert _chunks(sent_payloads(sent)) == []

    await _publish_answer(ca, topic)
    await asyncio.wait_for(call, 5.0)

    payloads = sent_payloads(sent)
    first = next(i for i, p in enumerate(payloads) if p != "keep-alive")
    assert first >= 2
    content, finish, done = payloads[first:]
    assert isinstance(content, dict) and isinstance(finish, dict)
    assert content["choices"][0]["delta"] == {"role": "assistant", "content": "Paris"}
    assert finish["choices"][0]["delta"] == {}
    assert finish["choices"][0]["finish_reason"] == "stop"
    assert done == DONE


async def test_no_keep_alive_after_first_data_chunk() -> None:
    """ST-11 / ST-S10: no comment line comes after the first data chunk."""
    ca = chat_app(None, chat_keepalive_s=0.001)
    call, sent = start_stream(ca, encoded(stream_body()), asyncio.Event())
    topic = await scheduled_topic(ca)
    await wait_until(lambda: keep_alives(sent) >= 1, what="a keep-alive comment")
    await _publish_answer(ca, topic)
    await asyncio.wait_for(call, 5.0)

    payloads = sent_payloads(sent)
    first = next(i for i, p in enumerate(payloads) if isinstance(p, dict))
    assert "keep-alive" not in payloads[first:]
    assert payloads[-1] == DONE


@pytest.mark.parametrize(
    "flags, model, headers, messages, status, code",
    [
        ({}, MODEL, None, [], 400, "invalid_request"),
        ({}, MODEL, {}, None, 401, "identity_required"),
        ({}, "prov/unknown", None, None, 404, "model_not_found"),
        ({"full": True}, MODEL, None, None, 429, "overloaded"),
    ],
)
async def test_validation_error_with_stream_true_is_json_error_not_stream(
    flags: dict[str, Any],
    model: str,
    headers: dict[str, str] | None,
    messages: list[dict[str, Any]] | None,
    status: int,
    code: str,
) -> None:
    """ST-6 / ST-S5: an error before the stream starts is the JSON envelope with its status."""
    ca = chat_app(answered(), **flags)
    resp = await post(ca.app, stream_body(model=model, messages=messages), headers=headers)

    assert resp.status_code == status
    assert resp.headers["content-type"].startswith("application/json")
    assert "text/event-stream" not in resp.headers["content-type"]
    assert error(resp)["code"] == code
    assert "x-should-retry" in resp.headers
    assert ca.runner.scheduled == []


async def test_failure_after_start_sends_error_event_and_no_done() -> None:
    """ST-7 / ST-S6: a failed run after the 200 is one error event and no [DONE]."""
    ca, resp = await _streamed(ended("failed", "fail_closed"))

    assert resp.status_code == 200
    assert media_type(resp.headers["content-type"]) == "text/event-stream"
    payloads = data_payloads(resp.content)
    assert len(payloads) == 1
    event = payloads[0]
    assert isinstance(event, dict)
    assert set(event) == {"error"}
    assert set(event["error"]) == {"message", "type", "code", "should_retry"}
    assert event["error"]["code"] == "fail_closed"
    assert event["error"]["type"] == "invalid_request_error"
    assert DONE not in payloads
    assert ca.objects.objects == {}
    assert ca.runner.stopped == []


async def test_time_limit_during_stream_stops_run_and_sends_timeout_event() -> None:
    """ST-S7: the time limit stops the run and sends the error event `timeout`."""
    ca = chat_app(None, chat_max_wait_s=0.2, chat_keepalive_s=0.05)
    resp = await post(ca.app, stream_body())

    assert resp.status_code == 200
    payloads = data_payloads(resp.content)
    last = payloads[-1]
    assert isinstance(last, dict)
    assert last["error"]["code"] == "timeout"
    assert last["error"]["type"] == "server_error"
    assert last["error"]["should_retry"] is False
    assert "retry_after" not in last["error"]
    assert DONE not in payloads
    assert ca.runner.scheduled[0]["topic"] in ca.runner.stopped
    assert ca.objects.objects == {}


async def test_drain_during_stream_sends_server_restarting_event() -> None:
    """ST-S12: the App drain sends the error event `server_restarting` and stops the run."""
    ca = chat_app(None, chat_max_wait_s=30.0, chat_keepalive_s=0.01)
    call, sent = start_stream(ca, encoded(stream_body()), asyncio.Event())
    topic = await scheduled_topic(ca)
    await wait_until(lambda: keep_alives(sent) >= 1, what="a keep-alive comment")
    ca.app.state.chat_drain.request()
    await asyncio.wait_for(call, 5.0)

    last = sent_payloads(sent)[-1]
    assert isinstance(last, dict)
    assert last["error"]["code"] == "server_restarting"
    # SE-2 (SDK model inference): the drain is retryable, after the same 5 s as the plain 503.
    assert last["error"]["should_retry"] is True
    assert last["error"]["retry_after"] == 5
    assert DONE not in sent_payloads(sent)
    assert topic in ca.runner.stopped
    assert ca.objects.objects == {}


async def test_drain_before_stream_is_json_503_with_retry_after() -> None:
    """A drain before the stream starts is the plain 503 `server_restarting`, with Retry-After;
    an error event after the start has no headers."""
    ca = chat_app(answered())
    ca.app.state.chat_drain.request()
    resp = await post(ca.app, stream_body())
    assert resp.status_code == 503
    assert resp.headers["content-type"].startswith("application/json")
    assert error(resp)["code"] == "server_restarting"
    assert resp.headers["x-should-retry"] == "true"
    assert resp.headers["retry-after"] == "5"
    assert ca.runner.scheduled == []


async def test_response_headers_disable_proxy_buffering() -> None:
    """ST-9 / ST-S9: the proxy headers, and each frame is its own body message (one flush)."""
    _, resp = await _streamed(answered())
    assert media_type(resp.headers["content-type"]) == "text/event-stream"
    assert resp.headers["cache-control"] == "no-cache"
    assert resp.headers["x-accel-buffering"] == "no"

    ca = chat_app(answered())
    call, sent = start_stream(ca, encoded(stream_body()), asyncio.Event())
    await asyncio.wait_for(call, 5.0)
    items = body_items(sent)
    assert len(items) == len(sent_payloads(sent)) == 3
    for item in items:
        assert item.endswith(b"\n\n")
        assert item.count(b"\n\n") == 1


async def test_include_usage_stream_ends_with_usage_chunk_from_root_frame() -> None:
    """ST-S3: the usage chunk has no choices, the usage and the screamingface object."""
    _, resp = await _streamed(answered(), stream_options={"include_usage": True})
    payloads = data_payloads(resp.content)
    assert payloads[-1] == DONE
    chunks = _chunks(payloads)
    tail = chunks[-1]
    assert tail["choices"] == []
    assert tail["usage"]["prompt_tokens"] == 30
    assert tail["usage"]["completion_tokens"] == 12
    assert tail["usage"]["total_tokens"] == 42
    assert tail["screamingface"]["cost_usd"] == "0.003"
    assert tail["screamingface"]["trace_id"] == TRACE_ID
    assert len({c["id"] for c in chunks}) == 1
    assert chunks[0]["id"].startswith("chatcmpl-")
    assert len({c["created"] for c in chunks}) == 1
    assert {c["model"] for c in chunks} == {MODEL}


async def test_stream_without_include_usage_has_no_usage_chunk() -> None:
    _, resp = await _streamed(answered())
    payloads = data_payloads(resp.content)
    assert payloads[-1] == DONE
    chunks = _chunks(payloads)
    assert all("usage" not in c for c in chunks)
    assert all(c["choices"] != [] for c in chunks)
    assert "screamingface" in chunks[-1]


@pytest.mark.parametrize(
    "script, outcome",
    [(answered(), "ok"), (ended("failed", "fail_closed"), "fail_closed")],
)
async def test_streamed_request_is_observed_once_with_its_true_outcome(
    script: Script, outcome: str, caplog: pytest.LogCaptureFixture
) -> None:
    """§3.4: a streamed request is counted, timed and logged once, at the end of its stream."""
    caplog.set_level(logging.INFO)
    ca, resp = await _streamed(script)
    assert resp.status_code == 200

    assert _outcomes(ca, outcome) == 1.0
    count = _sample(ca, "screamingface_engine_chat_request_duration_seconds_count")
    assert count == 1.0
    lines = [r for r in caplog.records if r.name == LINE_LOGGER]
    assert len(lines) == 1
    assert lines[0].levelno == logging.INFO
    assert f"outcome={outcome} status=200" in lines[0].getMessage()


async def test_streamed_duration_is_measured_to_the_end_of_the_stream() -> None:
    ca = chat_app(None, chat_keepalive_s=0.02)
    call, sent = start_stream(ca, encoded(stream_body()), asyncio.Event())
    topic = await scheduled_topic(ca)
    await wait_until(lambda: keep_alives(sent) >= 3, what="three keep-alive comments")
    await _publish_answer(ca, topic)
    await asyncio.wait_for(call, 5.0)

    assert _outcomes(ca, "ok") == 1.0
    total = _sample(ca, "screamingface_engine_chat_request_duration_seconds_sum")
    assert total is not None
    assert total >= 0.04


async def test_an_unexpected_error_after_start_sends_internal_error_event(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An error that no stage expected ends a started stream with the `internal_error` event;
    one ERROR line names only the class."""
    ca = chat_app(None)
    marker = "scan detail sk-live-stream-marker"

    async def broken(topic: str, from_sequence: int | None = None) -> AsyncIterator[Any]:
        raise RuntimeError(marker)
        yield

    monkeypatch.setattr(ca.stream, "subscribe", broken)
    caplog.set_level(logging.DEBUG)
    resp = await post(ca.app, stream_body())

    assert resp.status_code == 200
    payloads = data_payloads(resp.content)
    assert len(payloads) == 1
    event = payloads[0]
    assert isinstance(event, dict)
    assert event["error"]["code"] == "internal_error"
    assert event["error"]["type"] == "server_error"
    assert ca.runner.stopped == [ca.runner.scheduled[0]["topic"]]
    assert ca.objects.objects == {}
    assert _outcomes(ca, "internal_error") == 1.0
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1
    assert "RuntimeError" in errors[0].getMessage()
    assert marker not in caplog.text


async def test_stream_path_never_starts_the_receive_watcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One reader of receive(): the streamed path never calls the U4 wait with its watcher."""

    async def watcher(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the streamed path started the receive() watcher")

    monkeypatch.setattr(chat_completions, "wait_for_run", watcher)
    _, resp = await _streamed(answered())
    assert resp.status_code == 200
    assert data_payloads(resp.content)[-1] == DONE
