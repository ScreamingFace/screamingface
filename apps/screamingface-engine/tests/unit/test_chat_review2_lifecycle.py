"""Lifecycle of POST /v1/chat/completions after review 2: the stop of a run and the input write.

RR-S1 to RR-S5 of prd/review-round-2.md. A start is one attempt of its topic, so a cancel during
the schedule calls the bound stop. The delete waits for the input write. A cancelled wait leaves
no coroutine that was never awaited.
"""

from __future__ import annotations

import asyncio
import gc
import json
import threading
import warnings
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

from screamingface_engine.rest.chat_drain import ChatDrain
from screamingface_engine.rest.chat_wait import RunWait, wait_for_run
from screamingface_engine.testing import InMemoryEventStream

pytestmark = pytest.mark.asyncio


def _raw_call(ca: ChatApp, gone: asyncio.Event) -> asyncio.Future[Any]:
    """Starts one raw ASGI chat request on the App; its answer is dropped."""
    raw = json.dumps(body()).encode()
    return asyncio.ensure_future(asgi_call(ca.app, asgi_scope(len(raw)), body_then(raw, gone)))


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


async def test_cancel_during_schedule_calls_the_bound_stop() -> None:
    """RR-1 / RR-S1, RR-S2: a cancel while the schedule call waits stops the run with the bound
    stop, and the start was one open attempt of its topic."""
    gate = asyncio.Event()
    ca = chat_app(None, chat_max_wait_s=30.0, schedule_gate=gate)
    gone = asyncio.Event()
    call = _raw_call(ca, gone)
    try:
        await _until(lambda: bool(ca.runner.attempted))
        assert ca.runner.attempted
        topic = ca.runner.attempted[0]
        assert ca.runner.in_attempt == [True]
        call.cancel()
        with pytest.raises(asyncio.CancelledError):
            await call
        await _until(lambda: ca.runner.bound_stops == [topic] and ca.objects.objects == {})
        assert ca.runner.bound_stops == [topic]
        assert ca.objects.objects == {}
        assert ca.runner.plain_stops == []
        assert ca.runner.open_attempts == set()
    finally:
        gate.set()
        await _settle(call)


async def test_unknown_publish_calls_the_bound_stop() -> None:
    """RR-2 / RR-S2: a schedule that ends queue_unavailable is stopped with the bound stop."""
    ca = chat_app(None, queue_down=True)
    resp = await post(ca.app, body())
    assert resp.status_code == 503
    assert error(resp)["code"] == "queue_unavailable"
    assert ca.runner.bound_stops == [ca.runner.attempted[0]]
    assert ca.runner.plain_stops == []
    assert ca.objects.objects == {}


async def test_refused_schedule_calls_no_stop() -> None:
    """RR-3 / RR-S3: a schedule that queued nothing calls no stop of either kind."""
    ca = chat_app(full=True)
    resp = await post(ca.app, body())
    assert resp.status_code == 429
    assert ca.runner.bound_stops == []
    assert ca.runner.plain_stops == []
    assert ca.runner.stopped == []


async def test_a_finished_run_calls_no_stop_of_either_kind() -> None:
    """RR-3 / RR-S1: a run that answers is not stopped."""
    ca = chat_app(answered())
    resp = await post(ca.app, body())
    assert resp.status_code == 200
    assert ca.runner.bound_stops == []
    assert ca.runner.plain_stops == []


async def test_a_timed_out_run_is_stopped_with_the_bound_stop() -> None:
    """RR-2 / RR-S2: a run that ends in the time limit is stopped with the bound stop."""
    ca = chat_app(None, chat_max_wait_s=0.2)
    resp = await post(ca.app, body())
    assert resp.status_code == 504
    assert ca.runner.bound_stops == [ca.runner.scheduled[0]["topic"]]
    assert ca.runner.plain_stops == []


def _slow_ingest(
    real: Callable[..., Any],
    started: threading.Event,
    release: threading.Event,
    finished: threading.Event,
) -> Callable[..., Any]:
    """An ingest that signals its start, waits for `release`, then writes through `real`."""

    def slow(*args: Any, **kwargs: Any) -> Any:
        started.set()
        release.wait(5.0)
        result = real(*args, **kwargs)
        finished.set()
        return result

    return slow


async def test_cancel_during_input_write_leaves_no_blob(monkeypatch: pytest.MonkeyPatch) -> None:
    """RR-4 / RR-S4: a request cancelled while the store write runs leaves no blob once the
    cleanup has ended, and the run is not scheduled."""
    ca = chat_app(answered())
    store = ca.app.state.chat_input_store
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    slow = _slow_ingest(store.ingest, started, release, finished)
    monkeypatch.setattr(store, "ingest", slow)
    gone = asyncio.Event()
    call = _raw_call(ca, gone)
    try:
        await _until(started.is_set)
        assert started.is_set()
        call.cancel()
        await asyncio.gather(call, return_exceptions=True)
        assert call.cancelled()
        release.set()
        await _until(finished.is_set)
        await asyncio.sleep(0.2)
        assert ca.objects.objects == {}
        assert ca.runner.attempted == []
    finally:
        release.set()
        await _settle(call)


async def test_failed_input_write_still_cleans(monkeypatch: pytest.MonkeyPatch) -> None:
    """RR-5 / RR-S4: a failed input write is 503 chat_unavailable, and the cleanup still deletes."""
    ca = chat_app(answered())
    store = ca.app.state.chat_input_store

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise OSError("disk")

    deletes: list[int] = []
    real_delete = store.delete

    def counted_delete(*args: Any, **kwargs: Any) -> Any:
        deletes.append(1)
        return real_delete(*args, **kwargs)

    monkeypatch.setattr(store, "ingest", broken)
    monkeypatch.setattr(store, "delete", counted_delete)
    resp = await post(ca.app, body())
    assert resp.status_code == 503
    assert error(resp)["code"] == "chat_unavailable"
    assert len(deletes) == 1
    assert ca.runner.attempted == []
    assert ca.runner.bound_stops == []
    assert ca.runner.plain_stops == []


async def test_cancelled_wait_leaves_no_unawaited_coroutine() -> None:
    """RR-21 / RR-S5: a wait cancelled before its first step reports no never-awaited coroutine."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        wait = RunWait(InMemoryEventStream(), "topic-x", 5.0, ChatDrain())
        wait.cancel()
        await wait.close()
        del wait

        async def receive() -> dict[str, Any]:
            await asyncio.Event().wait()
            return {}

        task = asyncio.ensure_future(
            wait_for_run(InMemoryEventStream(), "topic-y", 5.0, receive, ChatDrain())
        )
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        del task
        gc.collect()
    assert not [w for w in caught if "never awaited" in str(w.message)]
