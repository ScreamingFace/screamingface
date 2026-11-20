"""Support pieces of the streamed route (U5): the keep-alive setting, the stream flags of the body,
the RunWait race, and the answer extraction that the stream and the plain answer share."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any, cast

import pytest
from _chat_app import (
    TRACE_ID,
    asgi_scope,
    body,
    body_then,
    chat_result,
    cost_frame,
    result_frame,
    terminated_frame,
)
from pydantic import ValidationError
from starlette.requests import Request

from screamingface_engine.chat.wire import Usage
from screamingface_engine.config import Settings
from screamingface_engine.rest.chat_answer import completion_id, completion_parts, read_result
from screamingface_engine.rest.chat_body import ParseGate, read_chat_body
from screamingface_engine.rest.chat_drain import ChatDrain
from screamingface_engine.rest.chat_errors import ChatError
from screamingface_engine.rest.chat_frames import RunFrames, WaitEnd
from screamingface_engine.rest.chat_wait import WAIT_ROWS, RunWait
from screamingface_engine.testing import InMemoryEventStream


def test_chat_keepalive_reads_its_env_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("URL4_CLOUD_CHAT_KEEPALIVE_S", "0.5")
    assert Settings(jwt_secret="x" * 32).chat_keepalive_s == 0.5


def test_chat_keepalive_defaults_to_15_s() -> None:
    assert Settings(jwt_secret="x" * 32).chat_keepalive_s == 15.0


def test_chat_keepalive_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        Settings(jwt_secret="x" * 32, chat_keepalive_s=0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "extra, expected",
    [
        ({}, (False, False)),
        ({"stream": True}, (True, False)),
        ({"stream": True, "stream_options": {"include_usage": True}}, (True, True)),
        ({"stream": True, "stream_options": {"include_usage": False}}, (True, False)),
    ],
)
async def test_chat_body_keeps_the_stream_flags(
    extra: dict[str, Any], expected: tuple[bool, bool]
) -> None:
    raw = json.dumps(body(**extra)).encode()
    req = Request(asgi_scope(len(raw)), cast(Any, body_then(raw, asyncio.Event())))
    got = await read_chat_body(req, ParseGate())
    assert (got.stream, got.include_usage) == expected
    record = json.loads(got.take_record())
    assert "stream" not in record
    assert "stream_options" not in record


@pytest.mark.asyncio
async def test_run_wait_returns_none_while_the_run_has_not_ended() -> None:
    wait = RunWait(InMemoryEventStream(), "t1", 5.0, ChatDrain())
    assert await wait.next(0.01) is None
    await wait.close()


@pytest.mark.asyncio
async def test_run_wait_returns_the_frames_after_the_terminal_frame() -> None:
    stream = InMemoryEventStream()
    await stream.publish("t1", cost_frame("t1"))
    await stream.publish("t1", result_frame("t1", chat_result()))
    await stream.publish("t1", terminated_frame("t1"))
    wait = RunWait(stream, "t1", 5.0, ChatDrain())
    frames = await wait.next(1.0)
    await wait.close()
    assert isinstance(frames, RunFrames)
    assert frames.result is not None
    assert frames.root_cost is not None
    assert frames.root_cost.scope == "subtree"
    assert frames.terminated.data.status == "succeeded"


@pytest.mark.asyncio
async def test_run_wait_returns_timeout_when_the_bound_passes() -> None:
    wait = RunWait(InMemoryEventStream(), "t1", 0.05, ChatDrain())
    out: object = None
    for _ in range(200):
        out = await wait.next(0.01)
        if out is not None:
            break
    await wait.close()
    assert out is WaitEnd.TIMEOUT


@pytest.mark.asyncio
async def test_run_wait_returns_drained_when_the_drain_is_requested() -> None:
    drain = ChatDrain()
    wait = RunWait(InMemoryEventStream(), "t1", 5.0, drain)
    assert await wait.next(0.01) is None
    drain.request()
    assert await wait.next(1.0) is WaitEnd.DRAINED
    await wait.close()


class _BrokenStream:
    async def subscribe(self, topic: str, from_sequence: int | None = None) -> AsyncIterator[Any]:
        raise RuntimeError("broken")
        yield


@pytest.mark.asyncio
async def test_run_wait_raises_a_broken_scan() -> None:
    wait = RunWait(cast(Any, _BrokenStream()), "t1", 5.0, ChatDrain())
    with pytest.raises(RuntimeError):
        await wait.next(1.0)
    await wait.close()


@pytest.mark.asyncio
async def test_run_wait_close_leaves_no_task() -> None:
    before = asyncio.all_tasks()
    wait = RunWait(InMemoryEventStream(), "t1", 5.0, ChatDrain())
    await wait.next(0.01)
    await wait.close()
    assert asyncio.all_tasks() <= before


@pytest.mark.asyncio
async def test_run_wait_cancel_is_idempotent() -> None:
    wait = RunWait(InMemoryEventStream(), "t1", 5.0, ChatDrain())
    wait.cancel()
    wait.cancel()
    await wait.close()


def test_wait_rows_are_the_three_wait_ends() -> None:
    assert WAIT_ROWS == {
        WaitEnd.TIMEOUT: (504, "timeout", False),
        WaitEnd.DRAINED: (503, "server_restarting", True),
        WaitEnd.GONE: (499, "client_disconnected", False),
    }


@pytest.mark.asyncio
async def test_read_result_raises_the_terminal_row_of_a_failed_run() -> None:
    frames = RunFrames(
        terminated=terminated_frame("t1", "failed", code="fail_closed"),
        result=None,
        root_cost=None,
    )
    with pytest.raises(ChatError) as caught:
        await read_result(frames, None)
    assert caught.value.status == 422
    assert caught.value.code == "fail_closed"


@pytest.mark.asyncio
async def test_read_result_decodes_an_inline_result() -> None:
    frames = RunFrames(
        terminated=terminated_frame("t1"),
        result=result_frame("t1", chat_result(content="Paris")),
        root_cost=None,
    )
    result = await read_result(frames, None)
    assert result.content == "Paris"


def test_completion_parts_read_usage_cost_and_trace_from_the_root_frame() -> None:
    frames = RunFrames(
        terminated=terminated_frame("t1"),
        result=result_frame("t1", chat_result()),
        root_cost=cost_frame("t1").data,
    )
    usage, info = completion_parts(chat_result(), frames)
    assert usage == Usage(prompt_tokens=30, completion_tokens=12, total_tokens=42)
    assert info.cost_usd == "0.003"
    assert info.trace_id == TRACE_ID
    assert info.status == "answered"


def test_completion_parts_cost_is_null_for_an_unpriced_run() -> None:
    frames = RunFrames(
        terminated=terminated_frame("t1"),
        result=result_frame("t1", chat_result()),
        root_cost=cost_frame("t1", pricing_version="unpriced").data,
    )
    _, info = completion_parts(chat_result(), frames)
    assert info.cost_usd is None


def test_completion_id_is_new_each_time() -> None:
    first, second = completion_id(), completion_id()
    assert first.startswith("chatcmpl-")
    assert first != second
