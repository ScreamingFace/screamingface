"""The worker's claim and supervision logic (OME-1089), against fakes.

The worker's contract is mostly about what it does with a claimed message: dedupe,
spawn, heartbeat, classify, ack. The broker behavior (redelivery, ack_wait, the
durable consumer) is pinned by the integration suite; here the queue, the publisher,
and the child process are fakes, so each decision is observable in isolation.
"""

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import nats
import nats.errors
import pytest

from screamingface_engine import job_env
from screamingface_engine.adapters.jetstream import QueueReadError
from screamingface_engine.runner_queue import encode_message
from screamingface_engine.worker.loop import Worker
from screamingface_engine.worker.supervisor import (
    CHILD_EXITED,
    DEADLINE_EXCEEDED,
    KILLED,
    OOM_KILLED,
    QUEUE_EXPIRED,
    WORKER_DRAINING,
)
from url4.streaming.protocol import TerminatedData, TerminatedEvent, source_for

pytestmark = pytest.mark.asyncio


class _FakeMsg:
    """A claimed queue message: records acks and in-progress heartbeats."""

    def __init__(
        self,
        data: bytes,
        *,
        published_at: datetime | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.data = data
        self.metadata = SimpleNamespace(timestamp=published_at or datetime.now(UTC))
        self.headers = headers
        self.acked = False
        self.in_progress_calls = 0

    async def ack(self) -> None:
        self.acked = True

    async def in_progress(self) -> None:
        self.in_progress_calls += 1


class _FakePublisher:
    """The slice of `JetStreamPublisher` the supervisor uses, recording every call."""

    def __init__(self, last_frame: TerminatedEvent | None = None) -> None:
        self._last_frame = last_frame
        self.published: list[Any] = []
        self.ensured: list[str] = []

    async def last_frame(self, topic: str) -> TerminatedEvent | None:
        return self._last_frame

    async def ensure_stream(self, topic: str) -> None:
        self.ensured.append(topic)

    async def publish(self, topic: str, event: Any) -> None:
        self.published.append(event)

    async def flush(self) -> None:
        pass


class _FakeProcess:
    """A controllable child: `wait()` blocks until released, or exits immediately."""

    def __init__(
        self, exit_code: int = 0, *, hang: bool = False, ignores_sigterm: bool = False
    ) -> None:
        self._exit_code = exit_code
        self._hang = hang
        self._ignores_sigterm = ignores_sigterm
        self._released = asyncio.Event()
        self.returncode: int | None = None
        self.stdout = None
        self.stderr = None
        self.terminate_calls = 0
        self.kill_calls = 0

    async def wait(self) -> int:
        if self._hang:
            await self._released.wait()
        self.returncode = self._exit_code
        return self.returncode

    def release(self, code: int | None = None) -> None:
        if code is not None:
            self._exit_code = code
        self._released.set()

    def terminate(self) -> None:
        self.terminate_calls += 1
        if self._ignores_sigterm:
            return
        self.release(-15)

    def kill(self) -> None:
        self.kill_calls += 1
        self.release(-9)


class _FakeQueue:
    """A queue that serves scripted batches, then returns empty after each timeout (an
    empty queue)."""

    def __init__(self, batches: list[list[_FakeMsg]] | None = None) -> None:
        self._batches = list(batches or [])
        self.pull_calls: list[tuple[int, float]] = []

    async def pull(self, batch: int, timeout_s: float) -> list[_FakeMsg]:
        self.pull_calls.append((batch, timeout_s))
        if self._batches:
            return self._batches.pop(0)
        await asyncio.sleep(timeout_s)
        return []


def _worker(
    queue: _FakeQueue,
    publisher: _FakePublisher,
    *,
    slots: int = 2,
    spawn: Any = None,
    **kwargs: Any,
) -> Worker:
    return Worker(
        queue=queue,
        publisher=publisher,
        slots=slots,
        drain_grace_s=kwargs.pop("drain_grace_s", 0.1),
        io_capacity=kwargs.pop("io_capacity", 4),
        memory_budget_bytes=kwargs.pop("memory_budget_bytes", 1024**3),
        spawn=spawn,
        pull_timeout_s=kwargs.pop("pull_timeout_s", 0.1),
        heartbeat_interval_s=kwargs.pop("heartbeat_interval_s", 20.0),
        deadline_margin_s=kwargs.pop("deadline_margin_s", 30.0),
        kill_grace_s=kwargs.pop("kill_grace_s", 0.05),
    )


def _async_proc(proc: _FakeProcess) -> Any:
    """A spawn callable that returns a fixed fake process."""

    async def _spawn(*args: Any, **kwargs: Any) -> _FakeProcess:
        return proc

    return _spawn


async def _wait_until(predicate: Any, timeout_s: float = 2.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.01)


def _message(topic: str, deadline_s: int = 60, grace_s: float = 60.0) -> bytes:
    """A queue message body with a controllable deadline and stream grace, so the hard-wall
    tests do not have to wait out the production defaults."""
    return json.dumps(
        {
            job_env.TOPIC: topic,
            job_env.EXPRESSION: "'hi'",
            job_env.JOB_DEADLINE_S: str(deadline_s),
            job_env.STREAM_GRACE_S: str(grace_s),
        }
    ).encode()


def _terminal(topic: str, status: str = "succeeded") -> TerminatedEvent:
    return TerminatedEvent(
        id="already-there",
        source=source_for(topic),
        subject=topic,
        data=TerminatedData(status=status),  # type: ignore[arg-type]
    )


# --- 1. dedupe: a terminal frame already on the stream means ack and skip ------------------


async def test_a_terminal_frame_already_on_the_stream_acks_without_spawning() -> None:
    """Redelivery, cancel-before-claim, and stale messages are one check: a terminal frame
    on the run's stream means the run is over, so the message is acked and no child is
    ever spawned."""
    topic = "t-dedupe"
    publisher = _FakePublisher(last_frame=_terminal(topic))
    msg = _FakeMsg(encode_message(topic, "'hi'", 60))
    spawned: list[Any] = []

    async def fake_spawn(*args: Any, **kwargs: Any) -> _FakeProcess:
        spawned.append(args)
        return _FakeProcess()

    worker = _worker(_FakeQueue(), publisher, spawn=fake_spawn)
    await worker._supervisor.supervise(msg)

    assert msg.acked
    assert not spawned
    assert not publisher.published


# --- 8. queue-time expiry ------------------------------------------------------------------


async def test_an_expired_capability_is_acked_with_a_queue_expired_frame() -> None:
    """A message whose run's deadline has already elapsed while queued is dropped with a
    named `queue_expired` terminal frame — never executed late."""
    topic = "t-expired"
    publisher = _FakePublisher()
    msg = _FakeMsg(
        encode_message(topic, "'hi'", 60),
        published_at=datetime.now(UTC) - timedelta(seconds=100),
    )
    spawned: list[Any] = []

    async def fake_spawn(*args: Any, **kwargs: Any) -> _FakeProcess:
        spawned.append(args)
        return _FakeProcess()

    worker = _worker(_FakeQueue(), publisher, spawn=fake_spawn)
    await worker._supervisor.supervise(msg)

    assert msg.acked
    assert not spawned
    assert len(publisher.published) == 1
    frame = publisher.published[0]
    assert frame.data.status == "failed"
    assert frame.data.error is not None and frame.data.error.code == QUEUE_EXPIRED
    assert frame.source == source_for(topic)


async def test_a_fresh_message_is_not_expired() -> None:
    """The expiry check must not drop a message that still has time: the safe direction is
    to execute."""
    topic = "t-fresh"
    publisher = _FakePublisher()
    msg = _FakeMsg(encode_message(topic, "'hi'", 60))  # published now
    worker = _worker(_FakeQueue(), publisher, spawn=_async_proc(_FakeProcess()))
    await worker._supervisor.supervise(msg)

    assert not publisher.published
    assert msg.acked


# --- 3. exit classification ----------------------------------------------------------------


async def test_a_clean_exit_adds_nothing_when_the_child_published_its_terminal_frame() -> None:
    """Exit 0 with the child's own terminal frame on the stream: the worker adds nothing —
    a second terminal frame would be a duplicate."""
    topic = "t-clean"
    publisher = _FakePublisher(last_frame=_terminal(topic))
    msg = _FakeMsg(encode_message(topic, "'hi'", 60))
    worker = _worker(_FakeQueue(), publisher, spawn=_async_proc(_FakeProcess(0)))
    await worker._supervisor.supervise(msg)

    assert msg.acked
    assert not publisher.published


async def test_a_clean_exit_adds_nothing_even_when_the_stream_is_gone() -> None:
    """Exit 0 with no terminal frame visible: the child's own teardown reclaimed the stream
    only AFTER publishing its terminal frame, so the worker still adds nothing."""
    topic = "t-clean-reclaimed"
    publisher = _FakePublisher()  # no stream at all
    msg = _FakeMsg(encode_message(topic, "'hi'", 60))
    worker = _worker(_FakeQueue(), publisher, spawn=_async_proc(_FakeProcess(0)))
    await worker._supervisor.supervise(msg)

    assert msg.acked
    assert not publisher.published


async def test_a_nonzero_exit_publishes_a_named_failure() -> None:
    topic = "t-exit3"
    publisher = _FakePublisher()
    msg = _FakeMsg(encode_message(topic, "'hi'", 60))
    worker = _worker(_FakeQueue(), publisher, spawn=_async_proc(_FakeProcess(3)))
    await worker._supervisor.supervise(msg)

    assert msg.acked
    assert len(publisher.published) == 1
    frame = publisher.published[0]
    assert frame.data.status == "failed"
    assert frame.data.error is not None and frame.data.error.code == CHILD_EXITED
    assert "3" in (frame.data.error.message or "")


async def test_a_signal_death_publishes_a_named_failure() -> None:
    topic = "t-signal"
    publisher = _FakePublisher()
    msg = _FakeMsg(encode_message(topic, "'hi'", 60))
    worker = _worker(_FakeQueue(), publisher, spawn=_async_proc(_FakeProcess(-11)))
    await worker._supervisor.supervise(msg)

    assert msg.acked
    frame = publisher.published[0]
    assert frame.data.status == "failed"
    assert frame.data.error is not None and frame.data.error.code == KILLED
    assert "11" in (frame.data.error.message or "")


async def test_exit_137_publishes_an_oom_failure() -> None:
    """137 is the OOMKilled exit: the OS killed the run for its memory, and the client
    must see that name rather than a generic failure."""
    topic = "t-oom"
    publisher = _FakePublisher()
    msg = _FakeMsg(encode_message(topic, "'hi'", 60))
    worker = _worker(_FakeQueue(), publisher, spawn=_async_proc(_FakeProcess(137)))
    await worker._supervisor.supervise(msg)

    assert msg.acked
    frame = publisher.published[0]
    assert frame.data.status == "failed"
    assert frame.data.error is not None and frame.data.error.code == OOM_KILLED


# --- 4. the hard wall ----------------------------------------------------------------------


async def test_a_hung_child_is_sigterm_then_sigkill_and_publishes_a_deadline_frame() -> None:
    """A child hung past `deadline_s + STREAM_GRACE_S + margin` gets SIGTERM, then SIGKILL
    when it ignores that, and the run ends in a named `timed_out` frame."""
    topic = "t-hung"
    publisher = _FakePublisher()
    msg = _FakeMsg(_message(topic, deadline_s=1, grace_s=0))
    proc = _FakeProcess(hang=True, ignores_sigterm=True)
    worker = _worker(
        _FakeQueue(),
        publisher,
        spawn=_async_proc(proc),
        deadline_margin_s=0.05,  # hard wall = 1 + 0 + 0.05
        kill_grace_s=0.05,
    )
    await worker._supervisor.supervise(msg)

    assert proc.terminate_calls == 1
    assert proc.kill_calls == 1
    assert msg.acked
    frame = publisher.published[0]
    assert frame.data.status == "timed_out"
    assert frame.data.error is not None and frame.data.error.code == DEADLINE_EXCEEDED


async def test_a_child_that_dies_on_sigterm_is_not_sigkilled() -> None:
    """The SIGKILL is the backstop, not the norm: a child that honors SIGTERM is killed
    once."""
    topic = "t-hung-obedient"
    publisher = _FakePublisher()
    msg = _FakeMsg(_message(topic, deadline_s=1, grace_s=0))
    proc = _FakeProcess(hang=True)  # honors SIGTERM
    worker = _worker(
        _FakeQueue(),
        publisher,
        spawn=_async_proc(proc),
        deadline_margin_s=0.05,
        kill_grace_s=0.05,
    )
    await worker._supervisor.supervise(msg)

    assert proc.terminate_calls == 1
    assert proc.kill_calls == 0
    assert msg.acked
    assert publisher.published[0].data.status == "timed_out"


# --- 5. heartbeats -------------------------------------------------------------------------


async def test_heartbeats_keep_a_long_childs_message_unacked() -> None:
    """While a child runs, the supervisor extends the message's ack_wait with
    `in_progress()` heartbeats, and the message is not acked until the child exits."""
    topic = "t-long"
    publisher = _FakePublisher()
    msg = _FakeMsg(encode_message(topic, "'hi'", 60))
    proc = _FakeProcess(hang=True)
    worker = _worker(
        _FakeQueue(),
        publisher,
        spawn=_async_proc(proc),
        heartbeat_interval_s=0.01,
    )
    supervise = asyncio.create_task(worker._supervisor.supervise(msg))

    await _wait_until(lambda: msg.in_progress_calls >= 2)
    assert not msg.acked, "a live run must not be acked"

    proc.release(0)
    await supervise
    assert msg.acked


# --- 2. slot accounting --------------------------------------------------------------------


async def test_the_fetch_batch_equals_free_slots_and_never_exceeds_them() -> None:
    """The loop computes the fetch batch from FREE slots: it claims exactly `worker_slots`
    at first, then exactly one per freed slot — never more than the pool can hold, so a
    sibling pull consumer is never starved."""
    queue = _FakeQueue(
        [
            [
                _FakeMsg(encode_message("t1", "'hi'", 60)),
                _FakeMsg(encode_message("t2", "'hi'", 60)),
            ],
            [_FakeMsg(encode_message("t3", "'hi'", 60))],
        ]
    )
    procs: list[_FakeProcess] = []

    async def fake_spawn(*args: Any, **kwargs: Any) -> _FakeProcess:
        proc = _FakeProcess(hang=True)
        procs.append(proc)
        return proc

    worker = _worker(queue, _FakePublisher(), slots=2, spawn=fake_spawn)
    async with asyncio.TaskGroup() as tg:
        claim = tg.create_task(worker._claim_loop(tg))

        await _wait_until(lambda: len(procs) == 2)
        assert queue.pull_calls[0][0] == 2, "the first fetch must claim the whole pool"
        assert len(worker._active) == 2

        procs[0].release(0)  # one run finishes -> one slot frees
        await _wait_until(lambda: len(procs) == 3)
        assert queue.pull_calls[1][0] == 1, "the next fetch must claim exactly the freed slot"
        assert len(worker._active) == 2, "the pool must never exceed worker_slots"

        for proc in procs:
            proc.release(0)
        claim.cancel()


# --- 7. drain ------------------------------------------------------------------------------


async def test_drain_stops_pulling_and_terminates_children_with_a_worker_draining_reason() -> None:
    """On the drain signal the worker stops pulling; in-flight children survive to
    `drain_grace_s`; then they are SIGTERM'd and each run ends in
    `Terminated(stopped)` with a `worker_draining` reason."""
    queue = _FakeQueue([[_FakeMsg(encode_message("t1", "'hi'", 60))]])
    procs: list[_FakeProcess] = []

    async def fake_spawn(*args: Any, **kwargs: Any) -> _FakeProcess:
        proc = _FakeProcess(hang=True)
        procs.append(proc)
        return proc

    publisher = _FakePublisher()
    worker = _worker(queue, publisher, slots=1, spawn=fake_spawn, drain_grace_s=0.2)
    async with asyncio.TaskGroup() as tg:
        claim = tg.create_task(worker._claim_loop(tg))

        await _wait_until(lambda: len(procs) == 1)
        assert len(queue.pull_calls) == 1

        worker._draining.set()
        await asyncio.sleep(0.1)  # inside the drain grace
        assert procs[0].terminate_calls == 0, "a child must survive to the drain grace"
        assert len(queue.pull_calls) == 1, "the worker must stop pulling on the drain signal"

        await _wait_until(lambda: procs[0].terminate_calls == 1)
        await _wait_until(
            lambda: bool(publisher.published) and publisher.published[-1].data.status == "stopped"
        )
        frame = publisher.published[-1]
        assert frame.data.error is not None and frame.data.error.code == WORKER_DRAINING

        await claim
        assert len(queue.pull_calls) == 1


async def test_a_drain_child_that_ignores_sigterm_is_still_acked_not_cancelled() -> None:
    """The drain kill's backstop must reap on a FRESH wait. `wait_for` CANCELS the
    original wait task when it times out, and awaiting the cancelled task re-raises
    `CancelledError` — which would abort `supervise` before the terminal frame and the
    ack, so the run would redeliver and execute twice instead of ending in
    `Terminated(stopped, worker_draining)`."""
    queue = _FakeQueue([[_FakeMsg(encode_message("t-stubborn", "'hi'", 60))]])
    procs: list[_FakeProcess] = []

    async def fake_spawn(*args: Any, **kwargs: Any) -> _FakeProcess:
        proc = _FakeProcess(hang=True, ignores_sigterm=True)
        procs.append(proc)
        return proc

    publisher = _FakePublisher()
    worker = _worker(
        queue, publisher, slots=1, spawn=fake_spawn, drain_grace_s=0.1, kill_grace_s=0.05
    )
    async with asyncio.TaskGroup() as tg:
        claim = tg.create_task(worker._claim_loop(tg))

        await _wait_until(lambda: len(procs) == 1)
        worker._draining.set()
        await _wait_until(lambda: procs[0].terminate_calls == 1)
        await _wait_until(lambda: procs[0].kill_calls == 1, timeout_s=5.0)
        await _wait_until(
            lambda: bool(publisher.published) and publisher.published[-1].data.status == "stopped"
        )
        frame = publisher.published[-1]
        assert frame.data.error is not None and frame.data.error.code == WORKER_DRAINING
        assert procs[0].returncode == -9, "the fresh wait must reap the SIGKILL exit"

        await claim


# --- heartbeat resilience (review follow-up) ------------------------------------------------


class _FlakyMsg(_FakeMsg):
    """A claimed message whose `in_progress()` fails the first N times — a broker blip."""

    def __init__(self, data: bytes, *, failures: int) -> None:
        super().__init__(data)
        self._failures = failures
        self.attempts = 0

    async def in_progress(self) -> None:
        self.attempts += 1
        if self.attempts <= self._failures:
            raise ConnectionError("broker reset")
        await super().in_progress()


async def test_a_transient_heartbeat_failure_does_not_stop_the_heartbeats() -> None:
    """`in_progress()` is a broker RPC; one transient failure (a connection blip) must
    not kill the heartbeat task — a dead heartbeat means the ack_wait runs out and the
    message is redelivered mid-run to a second worker: the exact double-run the
    heartbeat exists to prevent. The loop logs and keeps extending."""
    topic = "t-blip"
    msg = _FlakyMsg(encode_message(topic, "'hi'", 60), failures=1)
    proc = _FakeProcess(hang=True)
    worker = _worker(
        _FakeQueue(), _FakePublisher(), spawn=_async_proc(proc), heartbeat_interval_s=0.01
    )
    supervise = asyncio.create_task(worker._supervisor.supervise(msg))

    await _wait_until(lambda: msg.in_progress_calls >= 3)  # failed once, kept going
    assert not msg.acked, "a live run must not be acked"

    proc.release(0)
    await supervise
    assert msg.acked


async def test_a_dead_heartbeat_task_does_not_break_the_runs_cleanup() -> None:
    """The heartbeat task can FAIL outright (every extension raises). `cancel()` is a
    no-op on an already-finished task, and the cleanup awaited it FIRST — the task's
    own exception blew the finally block open, so every line after it was skipped: the
    child stayed in `_children` forever and a live child was never killed. The reaping
    must be unraisable; the child is released regardless."""
    topic = "t-dead-hb"
    msg = _FlakyMsg(encode_message(topic, "'hi'", 60), failures=10**9)  # always fails
    proc = _FakeProcess(hang=True)
    worker = _worker(
        _FakeQueue(), _FakePublisher(), spawn=_async_proc(proc), heartbeat_interval_s=0.01
    )
    supervise = asyncio.create_task(worker._supervisor.supervise(msg))

    await _wait_until(lambda: msg.attempts >= 1)  # the heartbeat has failed and died
    proc.release(0)
    await supervise  # must NOT re-raise the heartbeat's ConnectionError
    assert msg.acked
    assert proc not in worker._supervisor._children, "a finished run must release its child"


# --- review follow-ups: classification, expiry stamp, blast radius, duplicates ------------


def test_an_unrelated_failure_during_drain_is_not_relabeled_a_drain_stop() -> None:
    """The drain flag is GLOBAL; a child that OOMs or crashes for its OWN reasons during
    the grace window used to be relabeled `stopped/worker_draining`, masking real failures
    during rolling deploys. Only a child the drain actually terminated (`outcome ==
    "draining"`) classifies as a drain-stop."""
    worker = _worker(_FakeQueue(), _FakePublisher())
    worker._draining.set()
    classify = worker._supervisor._classify

    oom = classify("finished", 137)
    assert oom is not None and oom[0] == "failed" and oom[1] == OOM_KILLED

    crash = classify("finished", 1)
    assert crash is not None and crash[0] == "failed" and crash[1] == CHILD_EXITED

    drain_kill = classify("draining", None)
    assert drain_kill is not None
    assert drain_kill[0] == "stopped" and drain_kill[1] == WORKER_DRAINING


async def test_a_child_exit_racing_the_drain_signal_reads_as_draining() -> None:
    """When the drain fires and the child exits in the same scheduling batch, BOTH wait
    tasks complete — and the exit is the drain's doing. Reading that race as a natural
    "finished" hands the classifier a drain kill (rc -15) as the child's own failure."""
    proc = _FakeProcess(exit_code=-15)
    proc.release(-15)  # already gone by the time the drain fires
    worker = _worker(_FakeQueue(), _FakePublisher())
    worker._terminating.set()

    outcome = await worker._supervisor._wait_for_child(proc, hard_wall_s=None)

    assert outcome == "draining"


async def test_a_backlogged_run_expires_from_its_enqueue_stamp_not_its_delivery() -> None:
    """`msg.metadata.timestamp` is the DELIVERY moment (~now at claim time), so a run that
    sat backlogged past its deadline read as age ~0 and the expiry drop never fired. The
    publisher stamps the enqueue wall-clock; the claim gate must measure from THAT."""
    from screamingface_engine.subjects import ENQUEUED_AT_HEADER

    body = _message("topic-backlogged", deadline_s=60)
    msg = _FakeMsg(
        body,
        # Delivery is fresh (the pull just happened); the enqueue stamp is 120s old.
        published_at=datetime.now(UTC),
        headers={ENQUEUED_AT_HEADER: (datetime.now(UTC) - timedelta(seconds=120)).isoformat()},
    )
    publisher = _FakePublisher()
    worker = _worker(_FakeQueue(), publisher, spawn=_async_proc(_FakeProcess()))

    await worker._supervisor.supervise(msg)

    assert msg.acked, "an expired run is acked away, not redelivered"
    assert worker._supervisor._topics_in_flight == set()
    assert all(
        getattr(e.data, "error", None) is not None and e.data.error.code == "queue_expired"
        for e in publisher.published
    ), f"expected a queue_expired frame, got {publisher.published}"
    # And it never forked a child for an expired run.
    assert not worker._supervisor._children


async def test_one_unreadable_dedupe_read_kills_no_runs_and_leaves_the_claim() -> None:
    """The supervisors share one TaskGroup: an error escaping a claim's dedupe read — a
    momentary NATS blip, not a JetStream verdict — cancelled EVERY co-located run. A
    transient read now skips THAT claim only (no ack: the queue redelivers), and the
    healthy sibling runs to completion untouched."""

    from screamingface_engine.adapters.jetstream import QueueReadError

    class _BlipPublisher(_FakePublisher):
        def __init__(self) -> None:
            super().__init__()
            self.blips = 0

        async def last_frame(self, topic: str) -> Any:
            if topic == "topic-blip":
                self.blips += 1
                raise QueueReadError("stream tail unreadable for topic-blip")
            return await super().last_frame(topic)

    publisher = _BlipPublisher()
    healthy = _async_proc(_FakeProcess(exit_code=0, hang=True))
    worker = _worker(_FakeQueue(), publisher, spawn=healthy)
    blip_msg = _FakeMsg(_message("topic-blip"))
    healthy_msg = _FakeMsg(_message("topic-healthy"))

    async with asyncio.TaskGroup() as tg:
        tg.create_task(worker._supervisor.supervise(blip_msg))
        tg.create_task(worker._supervisor.supervise(healthy_msg))
        await _wait_until(lambda: publisher.blips >= 1)
        await _wait_until(lambda: worker._supervisor._children)
        for proc in tuple(worker._supervisor._children):
            # `_children` is typed to the `_ChildProcess` Protocol; `release` belongs to the
            # fake this test injected, so the cast is what tells pyright which one it is.
            cast(_FakeProcess, proc).release(0)

    assert not blip_msg.acked, "an unreadable tail is not 'no terminal frame' — redeliver it"
    assert healthy_msg.acked


async def test_a_duplicate_claim_of_a_running_topic_is_acked_away_without_a_second_child():
    """Redelivery can race an in-flight original (an `ack_wait` shorter than a supervision
    gap). The duplicate used to fork a SECOND child for one topic, racing its sibling to
    the terminal frame. It is now acked away — the original owns the outcome."""
    proc = _FakeProcess(hang=True)
    spawns: list[Any] = []

    async def _spawn(*args: Any, **kwargs: Any) -> Any:
        spawns.append(args)
        return proc

    worker = _worker(_FakeQueue(), _FakePublisher(), spawn=_spawn)
    body = _message("topic-dup")
    original = asyncio.ensure_future(worker._supervisor.supervise(_FakeMsg(body)))

    await _wait_until(lambda: len(spawns) == 1)  # the original is mid-run

    duplicate = _FakeMsg(body)
    await worker._supervisor.supervise(duplicate)

    assert duplicate.acked, "the duplicate is done — acked, not left to redeliver in a loop"
    assert len(spawns) == 1, "no second child for one topic"

    proc.release(0)
    await original
    assert original.done() and not original.cancelled()


def test_the_heartbeat_is_derived_from_the_ack_wait() -> None:
    """The heartbeat must stay at `ack_wait / 3` (capped at the 20s constant) for EVERY
    configuration: slower, and JetStream redelivers a still-running run to a second
    worker — the double execution the heartbeat exists to prevent."""
    from screamingface_engine.worker.supervisor import derived_heartbeat_interval_s

    assert derived_heartbeat_interval_s(60.0) == 20.0
    assert derived_heartbeat_interval_s(30.0) == 10.0
    assert derived_heartbeat_interval_s(15.0) == 5.0
    assert derived_heartbeat_interval_s(3.0) == 1.0
    for ack_wait in (3.0, 9.5, 60.0, 600.0):
        assert derived_heartbeat_interval_s(ack_wait) <= ack_wait / 3.0 + 1e-9


def test_settings_refuse_an_ack_wait_the_heartbeat_cannot_survive(monkeypatch: Any) -> None:
    """Below 3s the derived heartbeat collapses under 1s; refused at startup rather than
    as a mid-flight double execution."""
    from pydantic import ValidationError

    from screamingface_engine.config import Settings

    monkeypatch.setenv("URL4_CLOUD_RUN_QUEUE_ACK_WAIT_S", "2")
    with pytest.raises(ValidationError, match="run_queue_ack_wait_s"):
        Settings()


# --- 8. the review pass-2 cascade and drain cluster (P2-1, N-3, P2-6, N-2) ---------------


async def test_a_supervisors_post_exit_read_failing_does_not_kill_a_siblings_live_child() -> None:
    """P2-1: `_publish_if_needed`'s terminal-frame read runs AFTER the child exited, in a
    supervisor that still has to ack. An unguarded `QueueReadError` escaped into the
    shared TaskGroup and cancelled every co-located supervisor — each sibling's cleanup
    SIGKILLs its live child, so one momentary broker blip at one run's exit killed every
    healthy run on the pod. The read is now guarded: the classified frame is published
    anyway (an unreadable tail is not 'no frame'), the ack still runs, and the sibling
    is untouched."""
    raise_msg = _FakeMsg(encode_message("t-raise", "'hi'", 60))
    sib_msg = _FakeMsg(encode_message("t-sib", "'hi'", 60))
    sib = _FakeProcess(hang=True)

    class _RaisingOnSecondReadPublisher(_FakePublisher):
        """`last_frame` returns None on the first read of a topic and raises on the second
        — the claim-time gate is the first read, the post-exit read is the second, which
        is exactly the failing point P2-1 guards."""

        def __init__(self) -> None:
            super().__init__()
            self._reads: dict[str, int] = {}

        async def last_frame(self, topic: str) -> TerminatedEvent | None:
            n = self._reads.get(topic, 0) + 1
            self._reads[topic] = n
            if n >= 2:
                raise QueueReadError("stream tail unreadable")
            return None

    async def fake_spawn(*args: Any, **kwargs: Any) -> _FakeProcess:
        env = kwargs["env"]
        if env[job_env.TOPIC] == "t-raise":
            return _FakeProcess(exit_code=1)  # exits non-zero; its post-exit read raises
        return sib

    publisher = _RaisingOnSecondReadPublisher()
    queue = _FakeQueue([[raise_msg, sib_msg]])
    worker = _worker(queue, publisher, slots=2, spawn=fake_spawn, drain_grace_s=0.1)
    async with asyncio.TaskGroup() as tg:
        claim = tg.create_task(worker._claim_loop(tg))  # noqa: SLF001
        # The raising run's classified frame is still published (the fix publishes on an
        # unreadable tail rather than losing the run's only account of its death).
        await _wait_until(lambda: bool(publisher.published))
        await asyncio.sleep(0.05)  # a moment for a (wrong) cascade cancellation to land
        assert sib.kill_calls == 0, "a sibling's live child must not be SIGKILLed"
        assert sib.terminate_calls == 0, "a sibling's live child must not be touched at all"
        worker._draining.set()  # noqa: SLF001
        sib.release(0)
        await claim
    assert raise_msg.acked, "the raising run's message must still be acked"
    assert publisher.published[0].data.status == "failed"


async def test_a_broker_error_from_pull_does_not_cancel_in_flight_supervisors() -> None:
    """N-3: a transient broker error from `pull` (including the `ensure_stream` it wraps)
    used to escape the claim loop into the shared TaskGroup, cancelling every co-located
    supervisor and SIGKILLing its live children — the same cascade as P2-1, reached from
    the claim side. The loop now catches it, logs, backs off, and retries."""
    sib_msg = _FakeMsg(encode_message("t-sib", "'hi'", 60))
    sib = _FakeProcess(hang=True)

    async def fake_spawn(*args: Any, **kwargs: Any) -> _FakeProcess:
        return sib

    class _ErroringQueue(_FakeQueue):
        """Serves the scripted batch FIRST, then raises on the next pull — the blip
        lands with the sibling's supervisor LIVE and its child running (V-9: erroring
        on the first pull, before any supervisor existed, left the blast-radius
        assertion nothing to blast)."""

        def __init__(self) -> None:
            super().__init__([[sib_msg]])
            self.pull_count = 0

        async def pull(self, batch: int, timeout_s: float) -> list[_FakeMsg]:
            self.pull_calls.append((batch, timeout_s))
            self.pull_count += 1
            if self.pull_count == 2:
                raise nats.errors.Error("transient broker blip")
            if self._batches:
                return self._batches.pop(0)
            await asyncio.sleep(timeout_s)
            return []

    queue = _ErroringQueue()
    worker = _worker(queue, _FakePublisher(), slots=2, spawn=fake_spawn, drain_grace_s=0.1)
    async with asyncio.TaskGroup() as tg:
        claim = tg.create_task(worker._claim_loop(tg))  # noqa: SLF001
        # Pull 2 is the blip; pull 3 existing at all is the proof the loop SURVIVED it
        # with the sibling still in flight — on unfixed code the exception kills the
        # loop task here and no third pull ever happens.
        await _wait_until(lambda: queue.pull_count >= 3, timeout_s=5.0)
        assert sib.kill_calls == 0, "a live sibling must survive the claim-side blip"
        worker._draining.set()  # noqa: SLF001
        await _wait_until(lambda: sib.terminate_calls == 1 or sib.kill_calls == 1, timeout_s=5.0)
        assert sib.kill_calls == 0, "the sibling must not be caught in any cascade"
        assert sib.terminate_calls == 1, "the run must be drained, not killed"
        await claim


async def test_a_run_mid_spawn_when_the_signal_lands_still_gets_the_drain_grace() -> None:
    """P2-6: a run whose child is still spawning when the drain signal lands used to find
    `_children` empty, consume ZERO grace — `_terminating` was set immediately and the
    run was SIGKILL'd `kill_grace` after spawn with no chance to finish naturally. The
    drain waits on the ACTIVE tasks (registered at claim time), so a mid-spawn run gets
    the full grace window and then a clean SIGTERM."""
    queue = _FakeQueue([[_FakeMsg(encode_message("t-midspawn", "'hi'", 60))]])
    spawn_started = asyncio.Event()
    release_spawn = asyncio.Event()
    procs: list[_FakeProcess] = []

    async def delayed_spawn(*args: Any, **kwargs: Any) -> _FakeProcess:
        spawn_started.set()
        await release_spawn.wait()
        proc = _FakeProcess(hang=True)
        procs.append(proc)
        return proc

    worker = _worker(
        queue, _FakePublisher(), slots=1, spawn=delayed_spawn, drain_grace_s=0.2, kill_grace_s=0.05
    )
    async with asyncio.TaskGroup() as tg:
        claim = tg.create_task(worker._claim_loop(tg))  # noqa: SLF001
        await _wait_until(spawn_started.is_set)
        t0 = time.monotonic()
        worker._draining.set()  # noqa: SLF001 — the signal lands mid-spawn
        await asyncio.sleep(0.05)
        release_spawn.set()  # the child registers during the drain
        await _wait_until(
            lambda: bool(procs) and (procs[0].terminate_calls == 1 or procs[0].kill_calls == 1),
            timeout_s=5.0,
        )
        assert procs[0].terminate_calls == 1, "a mid-spawn run must get a clean SIGTERM"
        assert procs[0].kill_calls == 0, "it must never reach the bare-SIGKILL path"
        assert time.monotonic() - t0 >= 0.15, "the drain must honor the grace window"
        await claim


async def test_a_child_registered_after_the_drain_passes_still_gets_sigterm_before_sigkill() -> (
    None
):
    """N-2: a child that spawns AFTER the drain's grace has expired used to miss the
    one-shot SIGTERM pass — its supervisor found `_terminating` already set and
    hard-killed it `kill_grace` after spawn, never SIGTERM'd, with no chance to publish
    its frames. The drain now terminates children as they appear until the pool empties,
    so the late child still receives SIGTERM before any SIGKILL."""
    queue = _FakeQueue([[_FakeMsg(encode_message("t-late", "'hi'", 60))]])
    release_spawn = asyncio.Event()
    procs: list[_FakeProcess] = []

    async def delayed_spawn(*args: Any, **kwargs: Any) -> _FakeProcess:
        await release_spawn.wait()
        proc = _FakeProcess(hang=True)
        procs.append(proc)
        return proc

    worker = _worker(
        queue, _FakePublisher(), slots=1, spawn=delayed_spawn, drain_grace_s=0.05, kill_grace_s=0.2
    )
    async with asyncio.TaskGroup() as tg:
        claim = tg.create_task(worker._claim_loop(tg))  # noqa: SLF001
        await asyncio.sleep(0.05)  # let the claim land and the spawn begin blocking
        worker._draining.set()  # noqa: SLF001
        # Let the drain pass its grace AND (old code) its one-shot terminate pass.
        await _wait_until(lambda: worker._terminating.is_set())  # noqa: SLF001
        release_spawn.set()  # the child registers AFTER the pass
        await _wait_until(
            lambda: bool(procs) and (procs[0].terminate_calls == 1 or procs[0].kill_calls == 1),
            timeout_s=5.0,
        )
        assert procs[0].terminate_calls == 1, "a late child must receive SIGTERM"
        assert procs[0].kill_calls == 0, "it must receive SIGTERM BEFORE any SIGKILL"
        await claim


async def test_a_child_vanished_under_the_drains_terminate_does_not_kill_the_worker() -> None:
    """V-1: `_release_child` removes a finished child only AFTER its publish and ack
    round trips, so an exited child is routinely still in `_children` when the drain's
    re-polling terminate pass lands — and `terminate()` on one is NOT harmless. A real
    transport raises `ProcessLookupError` (an `OSError`) from `_check_proc` once the
    process is reaped; unsuppressed, that escaped `_drain()` into the shared TaskGroup
    and SIGKILLed every remaining draining child before they could publish or ack — the
    P2-1 cascade, reintroduced by the drain itself, exercised on every drain."""
    queue = _FakeQueue([[_FakeMsg(encode_message("t-gone", "'hi'", 60))]])

    class _VanishedProcess(_FakeProcess):
        """A child reaped under the worker: `terminate()` finds no process, exactly
        like asyncio's `BaseSubprocessTransport._check_proc` window."""

        def terminate(self) -> None:  # type: ignore[override]
            raise ProcessLookupError("process attached to the transport no longer exists")

    proc = _VanishedProcess(hang=True)

    async def spawn(*args: Any, **kwargs: Any) -> _FakeProcess:
        return proc

    worker = _worker(
        queue, _FakePublisher(), slots=1, spawn=spawn, drain_grace_s=0.05, kill_grace_s=0.2
    )
    async with asyncio.TaskGroup() as tg:
        claim = tg.create_task(worker._claim_loop(tg))  # noqa: SLF001
        await asyncio.sleep(0.05)  # the claim lands; the child hangs in `wait()`
        worker._draining.set()  # noqa: SLF001
        await claim
    # The worker survived the vanished child; the kill path eventually reaped it.
    assert proc.kill_calls == 1, "a vanished child is eventually killed, never resurrected"


async def test_a_publish_failure_after_exit_does_not_cancel_a_siblings_live_child() -> None:
    """V-7(a): the P2-1 handler publishes the classified terminal frame "anyway" on an
    unreadable tail — but the publish is a broker call made DURING the same blip, and it
    was unguarded. Its failure escaped into the shared TaskGroup, cancelling every
    co-located supervisor — each sibling's cleanup SIGKILLs its live child — and the
    failed run's message never acked, so the FINISHED run redelivered and was executed a
    second time. The run HAS ended: a publish failure is logged, the ack still runs, and
    no sibling dies."""
    fail_msg = _FakeMsg(encode_message("t-fail", "'hi'", 60))
    sib_msg = _FakeMsg(encode_message("t-sib", "'hi'", 60))
    sib = _FakeProcess(hang=True)

    class _BlipPublisher(_FakePublisher):
        """The terminal publish for ONE topic fails; everything else is healthy."""

        async def publish(self, topic: str, event: Any) -> None:
            if topic == "t-fail" and isinstance(event, TerminatedEvent):
                raise nats.errors.Error("publish failed during the same blip")
            self.published.append(event)

    procs: list[_FakeProcess] = [_FakeProcess(exit_code=0), sib]

    async def spawn(*args: Any, **kwargs: Any) -> _FakeProcess:
        return procs.pop(0)

    worker = _worker(
        _FakeQueue([[fail_msg], [sib_msg]]),
        _BlipPublisher(),
        slots=2,
        spawn=spawn,
        drain_grace_s=0.05,
    )
    async with asyncio.TaskGroup() as tg:
        claim = tg.create_task(worker._claim_loop(tg))  # noqa: SLF001
        # The failed publish must not cancel anything: the sibling gets claimed, its
        # child runs, and the finished run still acks (no redelivery, no re-execution).
        await _wait_until(lambda: fail_msg.acked and sib in worker._children, timeout_s=5.0)
        assert sib.kill_calls == 0, "a live sibling must survive the publish-side blip"
        worker._draining.set()  # noqa: SLF001
        await claim
    assert fail_msg.acked, "the finished run must ack despite its lost terminal frame"
    assert sib.kill_calls == 0 and sib.terminate_calls == 1
