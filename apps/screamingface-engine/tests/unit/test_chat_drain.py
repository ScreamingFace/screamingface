"""Tests for the chat drain: the stop-signal request that wakes every waiting chat handler.

CC-S37.
"""

import asyncio
import threading

import pytest

from screamingface_engine.rest.chat_drain import ChatDrain, request_all_drains

pytestmark = pytest.mark.asyncio


def test_a_new_drain_is_not_requested() -> None:
    assert ChatDrain().requested is False


async def test_request_wakes_a_waiter() -> None:
    drain = ChatDrain()
    task = asyncio.ensure_future(drain.wait())
    await asyncio.sleep(0)
    drain.request()
    await asyncio.wait_for(task, 1.0)
    assert drain.requested


async def test_request_from_another_thread_wakes_the_waiter() -> None:
    drain = ChatDrain()
    task = asyncio.ensure_future(drain.wait())
    await asyncio.sleep(0)
    thread = threading.Thread(target=drain.request)
    thread.start()
    thread.join(1.0)
    await asyncio.wait_for(task, 1.0)


async def test_request_before_any_waiter_makes_wait_return_at_once() -> None:
    drain = ChatDrain()
    drain.request()
    await asyncio.wait_for(drain.wait(), 0.5)


async def test_request_all_drains_reaches_every_live_drain() -> None:
    a, b = ChatDrain(), ChatDrain()
    count = request_all_drains()
    assert a.requested and b.requested and count >= 2


async def test_request_is_idempotent() -> None:
    drain = ChatDrain()
    task = asyncio.ensure_future(drain.wait())
    await asyncio.sleep(0)
    drain.request()
    drain.request()
    await asyncio.wait_for(task, 1.0)
