"""Cleanup of POST /v1/chat/completions: the stop of the run and the delete of the input blob.

CC-18, CC-19 and CC-41 of prd/chat-completion.md, with the drain of CC-S37. The input blob is
deleted on every exit; the run is stopped on every exit that has no terminal frame.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

import pytest
from _chat_app import (
    ChatApp,
    answered,
    asgi_call,
    asgi_scope,
    body,
    body_then,
    chat_app,
    error,
    post,
)

pytestmark = pytest.mark.asyncio


def _raw_call(ca: ChatApp, gone: asyncio.Event) -> asyncio.Future[Any]:
    """Starts one raw ASGI chat request on the App; its answer is dropped."""
    raw = json.dumps(body()).encode()
    return asyncio.ensure_future(asgi_call(ca.app, asgi_scope(len(raw)), body_then(raw, gone)))


async def _scheduled_topic(ca: ChatApp, bound_s: float = 2.0) -> str:
    """The topic of the first scheduled run; fails when no run is scheduled within `bound_s`."""
    for _ in range(int(bound_s / 0.01)):
        if ca.runner.scheduled:
            return ca.runner.scheduled[0]["topic"]
        await asyncio.sleep(0.01)
    raise AssertionError("the run was never scheduled")


async def _until(check: Callable[[], bool], bound_s: float = 3.0) -> None:
    """Polls `check` until it is true or `bound_s` passes."""
    for _ in range(int(bound_s / 0.01)):
        if check():
            return
        await asyncio.sleep(0.01)


async def _settle(task: asyncio.Future[Any]) -> None:
    """Cancels `task` when it still runs and waits for it to end."""
    if not task.done():
        task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def test_time_limit_stops_run_then_504() -> None:
    """CC-18 / CC-S21: a run that does not end in time is stopped, then 504 `timeout`."""
    ca = chat_app(None, chat_max_wait_s=0.2)
    resp = await post(ca.app, body())
    assert resp.status_code == 504
    assert error(resp)["code"] == "timeout"
    assert error(resp)["type"] == "server_error"
    assert resp.headers["x-should-retry"] == "false"
    topic = ca.runner.scheduled[0]["topic"]
    assert ca.runner.stopped == [topic]
    assert ca.objects.objects == {}
    assert ca.runner.scheduled[0]["deadline_s"] == 5


async def test_client_disconnect_stops_run_and_deletes_blob() -> None:
    """CC-19 / CC-S26: a client that leaves stops the run, and the input blob is deleted."""
    ca = chat_app(None, chat_max_wait_s=30.0)
    gone = asyncio.Event()
    call = _raw_call(ca, gone)
    try:
        topic = await _scheduled_topic(ca)
        gone.set()
        await asyncio.wait_for(call, timeout=3.0)
    finally:
        await _settle(call)
    assert ca.runner.stopped == [topic]
    assert ca.objects.objects == {}


async def test_cleanup_runs_when_the_request_task_is_cancelled() -> None:
    """CC-41: the stop and the delete still run when the request task is cancelled."""
    ca = chat_app(None, chat_max_wait_s=30.0, stop_delay_s=0.05)
    never = asyncio.Event()
    call = _raw_call(ca, never)
    try:
        topic = await _scheduled_topic(ca)
        call.cancel()
        with pytest.raises(asyncio.CancelledError):
            await call
    finally:
        await _settle(call)
    await _until(lambda: ca.runner.stopped == [topic] and ca.objects.objects == {})
    assert ca.runner.stopped == [topic]
    assert ca.objects.objects == {}


async def test_drain_stops_a_waiting_request_and_answers_server_restarting() -> None:
    """CC-S37: the drain stops a waiting request's run and answers 503 `server_restarting`."""
    ca = chat_app(None, chat_max_wait_s=30.0)
    task = asyncio.ensure_future(post(ca.app, body()))
    try:
        topic = await _scheduled_topic(ca)
        ca.app.state.chat_drain.request()
        resp = await asyncio.wait_for(task, 3.0)
    finally:
        await _settle(task)
    assert resp.status_code == 503
    assert error(resp)["code"] == "server_restarting"
    assert resp.headers["x-should-retry"] == "true"
    assert resp.headers["retry-after"] == "5"
    assert ca.runner.stopped == [topic]
    assert ca.objects.objects == {}


async def test_a_finished_run_is_not_stopped_but_its_blob_is_deleted() -> None:
    """A run that ended with a terminal frame is not stopped; its input blob is deleted."""
    ca = chat_app(answered())
    resp = await post(ca.app, body())
    assert resp.status_code == 200
    assert ca.runner.stopped == []
    assert ca.objects.objects == {}
    assert ca.runner.inputs[0] != {}


async def test_a_refused_request_before_the_blob_write_stops_nothing() -> None:
    """A request that the runner refuses stops no run and leaves no input blob."""
    ca = chat_app(full=True)
    resp = await post(ca.app, body())
    assert resp.status_code == 429
    assert ca.runner.stopped == []
    assert ca.objects.objects == {}


async def test_a_stop_that_raises_still_deletes_the_blob_and_answers() -> None:
    """The delete runs after a stop that raises, and the request still answers (CC-S26)."""
    ca = chat_app(None, chat_max_wait_s=0.2, stop_error=RuntimeError("the runner is down"))
    resp = await post(ca.app, body())
    assert resp.status_code == 504
    assert error(resp)["code"] == "timeout"
    assert ca.runner.stopped == [ca.runner.scheduled[0]["topic"]]
    assert ca.objects.objects == {}
