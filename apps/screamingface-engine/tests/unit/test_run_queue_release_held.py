"""kind K8 finding: a draining worker gives back the deliveries its held pull subscriptions
buffered after their last pull, instead of leaving them unacked for the whole `ack_wait`."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from screamingface_engine.runner_queue import RunQueue


class _Msg:
    def __init__(self, reply: str, status: str | None = None) -> None:
        self.reply = reply
        self.headers = None if status is None else {"Status": status}
        self.naked = False

    async def nak(self) -> None:
        self.naked = True


class _InnerSub:
    def __init__(self, msgs: list[_Msg]) -> None:
        self._pending_queue: asyncio.Queue[Any] = asyncio.Queue()
        for msg in msgs:
            self._pending_queue.put_nowait(msg)


class _PullSub:
    def __init__(self, msgs: list[_Msg]) -> None:
        self._sub = _InnerSub(msgs)
        self.unsubscribed = False

    async def unsubscribe(self) -> None:
        self.unsubscribed = True


@pytest.mark.asyncio
async def test_release_held_naks_buffered_deliveries_and_unsubscribes() -> None:
    queue = RunQueue("nats://unused:4222")
    delivery = _Msg("$JS.ACK.url4-runq.x.1.1.1")
    status_end = _Msg("", status="408")  # a pull request's timeout end: no delivery
    other = _Msg("$JS.ACK.url4-runq.y.1.2.2")
    held = {"a": _PullSub([delivery, status_end]), "b": _PullSub([other])}
    queue._pull_subs.update(held)  # noqa: SLF001
    queue._pull_subs_bound.update({"a": 0.0, "b": 0.0})  # noqa: SLF001

    released = await queue.release_held()

    assert released == 2
    assert delivery.naked and other.naked and not status_end.naked
    assert all(sub.unsubscribed for sub in held.values())
    assert queue._pull_subs == {} and queue._pull_subs_bound == {}  # noqa: SLF001


@pytest.mark.asyncio
async def test_release_held_with_nothing_held_is_a_no_op() -> None:
    assert await RunQueue("nats://unused:4222").release_held() == 0


def test_nats_py_still_keeps_a_subscriptions_buffer_where_release_held_reads_it() -> None:
    """`release_held` reads nats-py's private `Subscription._pending_queue` (no public API). A
    nats-py upgrade that moves it must fail HERE, not as a silent drain-time warning."""
    import inspect

    from nats.aio.subscription import Subscription

    assert "_pending_queue" in inspect.getsource(Subscription.__init__)
