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
from nats.errors import NoRespondersError

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
    """A control client that either replies (the run is running here) or reports
    "nobody is subscribed" — as a timeout, or as nats-py's faster `NoRespondersError`,
    which the broker itself raises whenever the server advertises headers."""

    def __init__(self, *, reply: bool = True, no_responders: bool = False) -> None:
        self._reply = reply
        self._no_responders = no_responders
        self.requested: list[tuple[str, bytes, float]] = []

    async def request(self, subject: str, payload: bytes, *, timeout: float) -> Any:
        self.requested.append((subject, payload, timeout))
        if self._reply:
            return object()
        if self._no_responders:
            raise NoRespondersError()
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

    # The App's side: the control ask went out, got no reply, the tombstone landed, and
    # the confirmation ask re-checked for a claim racing this stop (no reply again).
    assert control.requested == [
        ("url4.runctl.t", b"", runner._control_timeout_s),
        ("url4.runctl.t", b"", runner._control_timeout_s),
    ]
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


async def test_no_responders_reads_as_not_running_here_not_an_error() -> None:
    """nats-py raises `NoRespondersError` — not a `TimeoutError` subclass — when nothing
    is subscribed to `url4.runctl.*` (a pool scaled to zero, mid-rollout, a worker that
    is down). `stop()` must read it as "not running here" and tombstone the queued run;
    uncaught, it 500s `DELETE /` while the run stays queued."""
    publisher = _FakePublisher()
    control = _FakeControl(reply=False, no_responders=True)
    runner = _runner(publisher, control)
    await runner.schedule("t", "'hi'", 60)

    await runner.stop("t")  # must not raise

    assert control.requested == [
        ("url4.runctl.t", b"", runner._control_timeout_s),
        ("url4.runctl.t", b"", runner._control_timeout_s),
    ]
    assert len(publisher.published) == 1
    frame = publisher.published[0]
    assert isinstance(frame, TerminatedEvent)
    assert frame.data.status == "stopped"


# --- the queued-cancel race (review follow-up) ----------------------------------------------


class _ScriptedControl:
    """A control channel scripted per call: the worker does not own the run when the
    first ask goes out, but CLAIMS it mid-stop (before the tombstone lands) — so the
    confirmation ask finds it registered and it answers."""

    def __init__(self, outcomes: list[Any]) -> None:
        self._outcomes = list(outcomes)
        self.requested: list[str] = []

    async def request(self, subject: str, payload: bytes, *, timeout: float) -> Any:
        self.requested.append(subject)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


async def test_a_claim_landing_mid_stop_is_still_cancelled_with_one_frame() -> None:
    """Nothing orders `stop()` against a worker's claim: the worker can claim the queued
    message after the first control ask times out and before a tombstone written
    afterwards would land — its claim-time gate then reads no terminal frame, the run
    executes to completion, and the late tombstone adds a SECOND terminal frame to a run
    the caller was told was cancelled. The tombstone is now written BEFORE the
    confirmation ask: any claim after it sees the frame at its gate; any claim before it
    answers the confirmation ask and enacts the cancel, its own terminal publish
    suppressed by the tombstone already on the stream."""
    publisher = _FakePublisher()
    control = _ScriptedControl([TimeoutError("nobody yet"), object()])  # ask, then CLAIMED
    runner = _runner(publisher, control)

    await runner.stop("t-raced")

    # The confirmation pass happened — the worker that claimed mid-stop was reached.
    assert len(control.requested) == 2, "stop must re-ask after tombstoning"

    # The marker is durable BEFORE the confirmation ask (the ordering that closes the
    # race), and it is the run's ONE terminal frame.
    assert isinstance(publisher.published[0], TerminatedEvent)
    assert len(publisher.published) == 1

    # And the run stays cancelled: a later claim-time gate read sees the tombstone and
    # the worker skips — the existing before-claim test's mechanism, now also the fate
    # of any claim that arrives after this stop.
    assert isinstance(await publisher.last_frame("t-raced"), TerminatedEvent)


# --- review follow-up: the tombstone must not land after the run's real outcome ------------


class _CompletingMidAskPublisher(_FakePublisher):
    """A run that finishes INSIDE the control ask's window: the entry read saw nothing,
    but by the time the ask has timed out the run has claimed, executed, and published
    its genuine `Terminated(succeeded)`."""

    def __init__(self) -> None:
        super().__init__()
        self.reads = 0
        self._last_frame = None

    async def last_frame(self, topic: str) -> Any:
        self.reads += 1
        if self.reads >= 2:
            # The run completed during the ask: the stream now ends in success.
            self._last_frame = _terminated("t-midask", "succeeded")
        return self._last_frame


async def test_a_run_completing_inside_the_ask_window_keeps_its_real_outcome() -> None:
    """`stop()` used to write the tombstone from an entry-time read one control-timeout
    old: a fast run could claim, execute, and succeed entirely inside the ask's window,
    and the tombstone appended `stopped` AFTER the success — `status()`, a last-frame
    read on an append-only stream, then reported a succeeded run as stopped forever. The
    tail is re-read before the marker; a completed run is left untouched."""
    publisher = _CompletingMidAskPublisher()
    control = _ScriptedControl([TimeoutError("nobody yet"), TimeoutError("gone")])
    runner = _runner(publisher, control)

    await runner.stop("t-midask")

    assert publisher.published == [], "a run that succeeded needs no second terminal frame"
    assert await runner.status("t-midask") == "succeeded"


async def test_an_unreadable_tail_makes_stop_a_no_op_not_a_500() -> None:
    """P2-10: `stop()`'s tail reads were unguarded — a `QueueReadError` surfaced as a 500
    on `DELETE /`. An unreadable tail is UNKNOWN, not a state: stop returns without a
    tombstone and without a control ask (no state change), and a retried DELETE once the
    broker is readable reaches the truth."""
    from screamingface_engine.adapters.jetstream import QueueReadError

    class _UnreadablePublisher(_FakePublisher):
        async def last_frame(self, topic: str) -> Any:
            raise QueueReadError("stream tail unreadable")

    control = _FakeControl()
    runner = _runner(_UnreadablePublisher(), control)

    await runner.stop("t-unreadable")  # must not raise

    assert control.requested == [], "an unknown tail must not even reach the control ask"
