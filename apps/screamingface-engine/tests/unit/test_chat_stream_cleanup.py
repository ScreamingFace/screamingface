"""Cleanup of a streamed POST /v1/chat/completions (prd/streaming.md ST-S8, unit U5).

The run is stopped and the input blob is deleted on each exit of a stream that has no terminal
frame: a disconnect, a disconnect before the body starts, and a cancel of the request task.
Exemplars: test_chat_completions_cleanup.py and test_chat_completions_cancel.py.
"""

from __future__ import annotations

import asyncio
import random

import pytest
from _chat_app import chat_app
from _chat_stream import (
    encoded,
    keep_alives,
    scheduled_topic,
    start_stream,
    stream_body,
    wait_until,
)

pytestmark = pytest.mark.asyncio

RUNS = 50
SEED = 20261118


async def _turns(count: int) -> None:
    for _ in range(count):
        await asyncio.sleep(0)


async def test_asgi_disconnect_during_stream_stops_run_and_deletes_blob() -> None:
    ca = chat_app(None, chat_max_wait_s=30.0, chat_keepalive_s=0.01)
    gone = asyncio.Event()
    call, sent = start_stream(ca, encoded(stream_body()), gone)
    topic = await scheduled_topic(ca)
    await wait_until(lambda: keep_alives(sent) >= 1, what="a keep-alive comment")

    gone.set()
    await asyncio.wait_for(call, 2.0)

    assert topic in ca.runner.stopped
    assert ca.objects.objects == {}
    registry = ca.app.state.metrics.registry
    outcome = registry.get_sample_value(
        "screamingface_engine_chat_requests_total", {"outcome": "client_disconnected"}
    )
    assert outcome == 1.0


async def test_disconnect_before_the_first_chunk_still_runs_cleanup() -> None:
    ca = chat_app(None, chat_max_wait_s=30.0)
    gone = asyncio.Event()
    gone.set()
    call, _ = start_stream(ca, encoded(stream_body()), gone)
    topic = await scheduled_topic(ca)
    await asyncio.wait_for(call, 2.0)

    await wait_until(
        lambda: topic in ca.runner.stopped and ca.objects.objects == {}, what="the cleanup"
    )


async def test_cancel_of_a_streaming_request_runs_its_cleanup() -> None:
    ca = chat_app(None, chat_max_wait_s=30.0, chat_keepalive_s=0.01, stop_delay_s=0.05)
    call, sent = start_stream(ca, encoded(stream_body()), asyncio.Event())
    topic = await scheduled_topic(ca)
    await wait_until(lambda: keep_alives(sent) >= 1, what="a keep-alive comment")

    call.cancel()
    done, _ = await asyncio.wait({call}, timeout=2.0)

    assert done, "the cancel was swallowed and the stream still runs"
    assert call.cancelled()
    await wait_until(
        lambda: topic in ca.runner.stopped and ca.objects.objects == {}, what="the cleanup"
    )


async def test_every_cancel_of_a_streaming_request_runs_its_cleanup() -> None:
    rng = random.Random(SEED)
    ca = chat_app(None, chat_max_wait_s=30.0, chat_keepalive_s=0.005)
    raw = encoded(stream_body())
    for run in range(RUNS):
        call, _ = start_stream(ca, raw, asyncio.Event())
        topic = await scheduled_topic(ca, run)
        await _turns(rng.randint(0, 12))
        if rng.random() < 0.3:
            await asyncio.sleep(rng.uniform(0.0, 0.02))

        call.cancel()
        done, _ = await asyncio.wait({call}, timeout=2.0)

        assert done, f"run {run}: the cancel was swallowed and the stream still runs"
        assert call.cancelled(), f"run {run}: the stream ended without the cancel"
        await wait_until(
            lambda: topic in ca.runner.stopped and ca.objects.objects == {},
            what=f"the cleanup of run {run}",
        )
    assert len(ca.runner.stopped) == RUNS


async def test_no_task_outlives_a_disconnected_stream() -> None:
    before = set(asyncio.all_tasks())
    ca = chat_app(None, chat_max_wait_s=30.0, chat_keepalive_s=0.01)
    gone = asyncio.Event()
    call, sent = start_stream(ca, encoded(stream_body()), gone)
    topic = await scheduled_topic(ca)
    await wait_until(lambda: keep_alives(sent) >= 1, what="a keep-alive comment")

    gone.set()
    await asyncio.wait_for(call, 2.0)

    assert topic in ca.runner.stopped
    await wait_until(lambda: not (asyncio.all_tasks() - before), what="the end of every task")
