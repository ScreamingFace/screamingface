"""Cancellation through the queue runner (OME-1090): a queued run gets a tombstone, a
running run is reached over the control subject, and an unknown topic is a no-op.

The two cancel paths are the whole point of the unit:

* Queued, unclaimed: `stop()` writes `Terminated(stopped)` to the run's event stream
  immediately. The worker later claims the message, sees the terminal frame, acks, and
  never executes — no message deletion by sequence, and the App never learns the
  message's sequence.
* Running: `stop()` sends a core NATS request/reply on `url4.runctl.<topic>`. Only the
  owning worker replies (and SIGTERMs its child, which ends in the worker's own
  `Terminated(stopped)`); no reply within a short timeout means "not running here", and
  the tombstone above covers the queued case.
"""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from screamingface_engine.adapters.queue_runner import QueueJobRunner
from screamingface_engine.runner_queue import encode_message
from screamingface_engine.worker.supervisor import RunSupervisor
from url4.streaming.protocol import (
    StartedData,
    StartedEvent,
    TerminatedData,
    TerminatedEvent,
    source_for,
)

pytestmark = pytest.mark.asyncio

CAPABILITY_LIFETIME_S = 100.0
T0 = datetime(2026, 9, 2, 9, 0, 0, tzinfo=UTC)


class _FakeClock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


class _FakeQueue:
    def __init__(self) -> None:
        self.published: list[bytes] = []

    async def publish(self, message: bytes) -> None:
        self.published.append(message)

    async def depth(self) -> int:
        return 0


class _FakePublisher:
    def __init__(self, *, last_frame: Any = None, stream_exists: bool = True) -> None:
        self._last_frame = last_frame
        self._stream_exists = stream_exists
        self.published: list[Any] = []
        self.ensured: list[str] = []

    async def last_frame(self, topic: str) -> Any:
        return self._last_frame

    async def stream_exists(self, topic: str) -> bool:
        return self._stream_exists

    async def ensure_stream(self, topic: str) -> None:
        self.ensured.append(topic)

    async def publish(self, topic: str, event: Any) -> None:
        # Mirror the broker: a published frame is the stream's new tail, so a later
        # `last_frame` read sees it — the worker's dedupe check depends on exactly that.
        self._last_frame = event
        self.published.append(event)

    async def flush(self) -> None:
        pass


class _FakeControl:
    """A control client that either replies (the run is running here) or times out."""

    def __init__(self, *, reply: bool = True) -> None:
        self._reply = reply
        self.requested: list[tuple[str, bytes, float]] = []

    async def request(self, subject: str, payload: bytes, *, timeout: float) -> Any:
        self.requested.append((subject, payload, timeout))
        if self._reply:
            return object()
        raise TimeoutError()


def _runner(publisher: _FakePublisher, control: _FakeControl) -> QueueJobRunner:
    return QueueJobRunner(
        queue=_FakeQueue(),
        publisher=publisher,
        control=control,
        clock=_FakeClock(),
        capability_lifetime_s=CAPABILITY_LIFETIME_S,
    )


def _started(topic: str) -> StartedEvent:
    return StartedEvent(
        id="s", source=source_for(topic), subject=topic, data=StartedData(url4="'hi'")
    )


def _terminated(topic: str, status: str) -> TerminatedEvent:
    return TerminatedEvent(
        id="t",
        source=source_for(topic),
        subject=topic,
        data=TerminatedData(status=status),  # type: ignore[arg-type]
    )


class _FakeMsg:
    """A claimed queue message, recording its ack."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.metadata = SimpleNamespace(timestamp=datetime.now(UTC))
        self.acked = False

    async def ack(self) -> None:
        self.acked = True

    async def in_progress(self) -> None:
        pass


def _supervisor(publisher: _FakePublisher) -> RunSupervisor:
    """A supervisor that can never spawn — the cancel-before-claim test must prove it
    never tries to."""

    async def _never_spawn(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("a cancelled run must never be spawned")

    return RunSupervisor(
        publisher=publisher,
        spawn=_never_spawn,
        memory_budget_bytes=1024**3,
        io_capacity=4,
        draining=asyncio.Event(),
        terminating=asyncio.Event(),
        children=set(),
        children_by_topic={},
        cancelled=set(),
    )


# --- cancel-before-claim -------------------------------------------------------------------


async def test_cancel_before_claim_writes_a_tombstone_and_the_worker_skips() -> None:
    """DELETE / on a queued run: the App writes `Terminated(stopped)`; the worker later
    claims the message, sees the terminal frame, acks exactly once, and never executes."""
    publisher = _FakePublisher()
    control = _FakeControl(reply=False)
    runner = _runner(publisher, control)
    await runner.schedule("t", "'hi'", 60)
    await runner.stop("t")

    # The App's side: the control request went out, got no reply, and the tombstone landed.
    assert control.requested == [("url4.runctl.t", b"", runner._control_timeout_s)]
    assert len(publisher.published) == 1
    frame = publisher.published[0]
    assert isinstance(frame, TerminatedEvent)
    assert frame.data.status == "stopped"
    assert frame.source == source_for("t")

    # The worker's side: claim the message, see the tombstone, ack, skip.
    msg = _FakeMsg(encode_message("t", "'hi'", 60))
    await _supervisor(publisher).supervise(msg)
    assert msg.acked
    assert len(publisher.published) == 1, "the worker must add no second frame"


# --- cancel-while-running ------------------------------------------------------------------


async def test_cancel_while_running_reaches_the_owner_and_writes_no_tombstone() -> None:
    """A running run is reached over the control subject; the App writes nothing — the
    owning worker's own `Terminated(stopped)` is the one frame."""
    publisher = _FakePublisher(last_frame=_started("t"))
    control = _FakeControl(reply=True)
    runner = _runner(publisher, control)
    await runner.schedule("t", "'hi'", 60)
    await runner.stop("t")

    assert control.requested == [("url4.runctl.t", b"", runner._control_timeout_s)]
    assert publisher.published == [], "a replied control request must not also tombstone"


# --- idempotency ---------------------------------------------------------------------------


async def test_stop_on_an_unknown_topic_is_a_no_op() -> None:
    """stop() on a topic with no stream and no schedule record stays idempotent — the
    DELETE route's 204 must not hide a stream being created for a run that never was."""
    publisher = _FakePublisher(stream_exists=False)
    runner = _runner(publisher, _FakeControl(reply=False))
    await runner.stop("unknown")
    assert publisher.published == []
    assert publisher.ensured == []


async def test_stop_on_an_already_terminal_run_adds_no_second_frame() -> None:
    """A run that already ended must not receive a second terminal frame."""
    publisher = _FakePublisher(last_frame=_terminated("t", "succeeded"))
    runner = _runner(publisher, _FakeControl(reply=False))
    await runner.stop("t")
    assert publisher.published == []
