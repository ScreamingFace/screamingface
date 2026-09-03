"""The cross-pod duplicate-claim guard (OME-1089), against a fake fleet.

The worker's in-process duplicate guard (`RunSupervisor._topics_in_flight`) was the WHOLE
world at `runnerPool.replicas: 1`. At N pods there are N of those sets, and the other two
claim gates both pass for a still-RUNNING run: `_terminal_frame_exists` matches only a
`TerminatedEvent` (a live run's stream tail is a Span or a Log) and `_capability_expired`
is False inside the deadline. So a mid-run redelivery landing on a DIFFERENT pod forked a
SECOND child for one run — two children on one event stream, both racing to the terminal
frame, every model call paid for twice.

These tests model the fleet as two `Worker` instances on one event loop, each with its own
registries, wired to a `_FakeBroker` that routes `url4.runown.*` requests to every worker
that has joined it — first responder wins, and silence is a timeout, exactly like core
NATS request/reply. The fakes are local to this module rather than imported from
`test_worker_claim.py`: that file is under the repo's append-only test check, and the
redelivery counter these tests turn on (`metadata.num_delivered`) is not on its `_FakeMsg`.
"""

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import nats.errors
import pytest

from screamingface_engine import job_env
from screamingface_engine.subjects import OWNERSHIP_SUBJECT_PREFIX, ownership_subject_for
from screamingface_engine.worker.loop import Worker
from url4.streaming.protocol import (
    LogData,
    LogEvent,
    TerminatedData,
    TerminatedEvent,
    source_for,
)

pytestmark = pytest.mark.asyncio


class _FakeMsg:
    """A claimed queue message, with the DELIVERY COUNT the probe gate reads.

    `num_delivered > 1` is what marks a claim as a redelivery — the only way two pods can
    ever hold the same message, since the queue is `WorkQueue` retention with one durable
    consumer per bucket subject.
    """

    def __init__(self, data: bytes, *, num_delivered: int = 1) -> None:
        self.data = data
        self.metadata = SimpleNamespace(timestamp=None, num_delivered=num_delivered)
        self.headers: dict[str, str] | None = None
        self.acked = False
        self.in_progress_calls = 0

    async def ack(self) -> None:
        self.acked = True

    async def in_progress(self) -> None:
        self.in_progress_calls += 1


class _LivePublisher:
    """A publisher whose stream tail is a NON-terminal frame — a run still executing.

    This is the state the claim gates cannot read: `_terminal_frame_exists` answers False,
    so nothing about the run's own stream tells a second pod the run is alive.
    """

    def __init__(self, last_frame: Any = None) -> None:
        self._last_frame = last_frame
        self.published: list[Any] = []
        self.ensured: list[str] = []

    async def last_frame(self, topic: str) -> Any:
        return self._last_frame

    async def ensure_stream(self, topic: str) -> None:
        self.ensured.append(topic)

    async def publish(self, topic: str, event: Any) -> None:
        self.published.append(event)

    async def flush(self) -> None:
        pass


class _FakeProcess:
    """A controllable child: `wait()` blocks until released, or exits immediately."""

    def __init__(self, exit_code: int = 0, *, hang: bool = False) -> None:
        self._exit_code = exit_code
        self._hang = hang
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
        self.release(-15)

    def kill(self) -> None:
        self.kill_calls += 1
        self.release(-9)


class _FakeQueue:
    """A queue that never serves anything: these tests drive `supervise` directly."""

    async def pull(self, batch: int, timeout_s: float) -> list[_FakeMsg]:
        await asyncio.sleep(timeout_s)
        return []


class _ProbeMsg:
    """One `url4.runown.<topic>` request as the receiving worker's handler sees it."""

    def __init__(self, subject: str, payload: bytes) -> None:
        self.subject = subject
        self.data = payload
        self.replied: list[bytes] = []

    async def respond(self, data: bytes = b"") -> None:
        self.replied.append(data)


class _FakeBroker:
    """The fleet's core-NATS stand-in: request/reply over `url4.runown.*`.

    `request` fans the probe out to every worker that has JOINED — including the prober
    itself, which is the whole self-veto hazard — and returns the FIRST reply. Nobody
    replying raises `TimeoutError`, which is how a non-owner's silence reaches the prober
    on a real broker.
    """

    def __init__(self) -> None:
        self._workers: list[Worker] = []
        self.requests: list[tuple[str, bytes]] = []

    def join(self, worker: Worker) -> None:
        self._workers.append(worker)

    async def subscribe(self, subject: str) -> Any:
        async def _messages() -> Any:
            while True:  # pragma: no cover - these tests call the handlers directly
                await asyncio.sleep(3600)
                yield None

        return SimpleNamespace(messages=_messages())

    async def request(self, subject: str, payload: bytes = b"", *, timeout: float) -> Any:
        self.requests.append((subject, payload))
        for worker in list(self._workers):
            probe = _ProbeMsg(subject, payload)
            await worker._handle_ownership(probe)  # noqa: SLF001
            if probe.replied:
                return SimpleNamespace(data=probe.replied[0])
        raise TimeoutError("nobody owns this run")


class _RaisingControl:
    """A control client whose ownership probe always fails with a given exception."""

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc
        self.requests: list[str] = []

    async def subscribe(self, subject: str) -> Any:  # pragma: no cover - never served here
        raise AssertionError("these tests do not serve subscriptions")

    async def request(self, subject: str, payload: bytes = b"", *, timeout: float) -> Any:
        self.requests.append(subject)
        raise self._exc


def _message(topic: str, deadline_s: int = 60, grace_s: float = 60.0) -> bytes:
    return json.dumps(
        {
            job_env.TOPIC: topic,
            job_env.EXPRESSION: "'hi'",
            job_env.JOB_DEADLINE_S: str(deadline_s),
            job_env.STREAM_GRACE_S: str(grace_s),
        }
    ).encode()


def _running_tail(topic: str) -> LogEvent:
    """A live run's stream tail: a Log frame, NOT a `TerminatedEvent`."""
    return LogEvent(
        id="mid-run",
        source=source_for(topic),
        subject=topic,
        data=LogData(severity_number=9, severity_text="INFO", body="still running"),
    )


def _terminal(topic: str) -> TerminatedEvent:
    return TerminatedEvent(
        id="already-there",
        source=source_for(topic),
        subject=topic,
        data=TerminatedData(status="succeeded"),
    )


def _pod(publisher: Any, *, spawn: Any = None, control: Any = None) -> Worker:
    return Worker(
        queue=_FakeQueue(),
        publisher=publisher,
        slots=2,
        drain_grace_s=0.1,
        io_capacity=4,
        memory_budget_bytes=1024**3,
        spawn=spawn,
        control=control,
        pull_timeout_s=0.05,
        heartbeat_interval_s=20.0,
        deadline_margin_s=30.0,
        kill_grace_s=0.05,
        ownership_probe_timeout_s=0.1,
    )


def _spawner(procs: list[_FakeProcess], *, hang: bool = False) -> Any:
    """A spawn callable that records every child it forks."""

    async def _spawn(*args: Any, **kwargs: Any) -> _FakeProcess:
        proc = _FakeProcess(hang=hang)
        procs.append(proc)
        return proc

    return _spawn


async def _wait_until(predicate: Any, timeout_s: float = 2.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.01)


# --- the bug: a redelivery on a SECOND pod forked a second child --------------------------


async def test_a_redelivery_on_a_second_pod_is_acked_away_without_a_second_child() -> None:
    """RED → GREEN, the whole defect. Pod A is mid-run; the same message is redelivered
    (`num_delivered=2`) to pod B, whose in-process guard is empty and whose stream tail is a
    live Log frame. Before the ownership probe, pod B forked a SECOND child for one run —
    two children on one event stream, both racing to the terminal frame, every model call
    billed twice. Pod B must now find pod A over `url4.runown.<topic>`, ack the duplicate
    away, and spawn nothing."""
    topic = "t-cross-pod"
    body = _message(topic)
    broker = _FakeBroker()
    a_procs: list[_FakeProcess] = []
    b_procs: list[_FakeProcess] = []
    pod_a = _pod(
        _LivePublisher(_running_tail(topic)),
        spawn=_spawner(a_procs, hang=True),  # pod A's run stays LIVE
        control=broker,
    )
    pod_b = _pod(
        # Pod B's child exits at once, so the RED case (a second child forked) FAILS the
        # assertion below instead of hanging this test on a live duplicate.
        _LivePublisher(_running_tail(topic)),
        spawn=_spawner(b_procs),
        control=broker,
    )
    broker.join(pod_a)
    broker.join(pod_b)

    original = asyncio.ensure_future(pod_a._supervisor.supervise(_FakeMsg(body)))  # noqa: SLF001
    await _wait_until(lambda: len(a_procs) == 1)  # pod A's run is live

    duplicate = _FakeMsg(body, num_delivered=2)
    await pod_b._supervisor.supervise(duplicate)  # noqa: SLF001

    assert duplicate.acked, "the duplicate is done — acked, not left to hit max_deliver"
    assert not b_procs, "pod B must not fork a second child for a run pod A is executing"
    assert broker.requests == [(ownership_subject_for(topic), pod_b._worker_id.encode())]  # noqa: SLF001
    assert pod_b._metrics.cross_pod_duplicate_claims._value.get() == 1  # noqa: SLF001

    a_procs[0].release(0)
    await original
    assert len(a_procs) == 1, "pod A's own run is untouched"


# --- the self-veto deadlock: a pod must never answer its own probe ------------------------


async def test_a_pod_does_not_veto_its_own_redelivered_claim() -> None:
    """The most likely way this fix goes wrong. `_supervise` registers the topic in
    `_starting` BEFORE `_claim` probes, and the probing pod is itself subscribed to
    `url4.runown.*` — so a handler without the self-id check answers its OWN probe, the pod
    declines its own claim, and the run executes NOWHERE. That would silently break every
    redelivery-after-crash recovery."""
    topic = "t-self-probe"
    broker = _FakeBroker()
    procs: list[_FakeProcess] = []
    pod = _pod(_LivePublisher(), spawn=_spawner(procs), control=broker)
    broker.join(pod)  # the only worker in the fleet: nobody else can answer

    msg = _FakeMsg(_message(topic), num_delivered=2)
    await pod._supervisor.supervise(msg)  # noqa: SLF001

    assert len(procs) == 1, "a redelivery nobody else owns must still run"
    assert msg.acked
    assert broker.requests, "the probe was issued — it just must not veto its own pod"
    assert pod._metrics.cross_pod_duplicate_claims._value.get() == 0  # noqa: SLF001


# --- fail open: the guard must never cost a run -------------------------------------------


@pytest.mark.parametrize(
    "exc",
    [
        TimeoutError("no owner answered"),
        nats.errors.NoRespondersError(),
        ConnectionError("broker reset"),
        nats.errors.Error("transient broker blip"),
    ],
    ids=["timeout", "no_responders", "connection_error", "broker_error"],
)
async def test_a_failed_probe_still_runs_the_child(exc: BaseException) -> None:
    """FAIL OPEN, always. Declining a claim is how runs get LOST: `max_deliver=2` gives a
    run exactly one redelivery, so a second decline hits the ceiling and the advisory
    subscriber ends it as `Terminated(failed, max_deliveries)` — a run that today re-runs
    and succeeds. A partitioned owner that cannot answer the probe also cannot publish
    frames and dies on its own deadline, so failing open costs at most the duplicate we
    already have today."""
    control = _RaisingControl(exc)
    procs: list[_FakeProcess] = []
    pod = _pod(_LivePublisher(), spawn=_spawner(procs), control=control)

    msg = _FakeMsg(_message("t-fail-open"), num_delivered=2)
    await pod._supervisor.supervise(msg)  # noqa: SLF001

    assert control.requests, "the probe was attempted"
    assert len(procs) == 1, "an unanswerable probe must not cost the run"
    assert msg.acked


async def test_a_worker_without_a_control_channel_probes_nothing_and_runs() -> None:
    """`control=None` — every pre-existing unit test, and any worker built without a core
    NATS connection. No probe is attempted at all and the claim path is what it always
    was."""
    procs: list[_FakeProcess] = []
    pod = _pod(_LivePublisher(), spawn=_spawner(procs), control=None)

    msg = _FakeMsg(_message("t-no-control"), num_delivered=2)
    await pod._supervisor.supervise(msg)  # noqa: SLF001

    assert len(procs) == 1
    assert msg.acked


# --- the probe costs the normal path nothing ----------------------------------------------


async def test_a_first_delivery_never_probes() -> None:
    """The queue is `WorkQueue` retention and each bucket subject maps to exactly ONE durable
    consumer, so a message is outstanding on at most one worker at a time: a FIRST delivery
    cannot be a duplicate of anything. Gating the probe on redelivery keeps the normal claim
    path at ZERO added broker round trips."""
    broker = _FakeBroker()
    procs: list[_FakeProcess] = []
    pod = _pod(_LivePublisher(), spawn=_spawner(procs), control=broker)
    broker.join(pod)

    msg = _FakeMsg(_message("t-first"))  # num_delivered defaults to 1
    await pod._supervisor.supervise(msg)  # noqa: SLF001

    assert broker.requests == [], "a first delivery must not pay for a probe"
    assert len(procs) == 1
    assert msg.acked


async def test_a_finished_run_is_acked_by_the_cheaper_gate_without_a_probe() -> None:
    """The probe sits AFTER `_terminal_frame_exists`: a redelivery of a run that already
    ENDED is acked away by the local read, with no broker round trip and no child."""
    topic = "t-already-done"
    broker = _FakeBroker()
    procs: list[_FakeProcess] = []
    pod = _pod(_LivePublisher(_terminal(topic)), spawn=_spawner(procs), control=broker)
    broker.join(pod)

    msg = _FakeMsg(_message(topic), num_delivered=2)
    await pod._supervisor.supervise(msg)  # noqa: SLF001

    assert msg.acked
    assert not procs
    assert broker.requests == [], "a finished run needs no ownership probe"


# --- the serving side ----------------------------------------------------------------------


async def test_the_ownership_handler_replies_only_for_a_run_it_owns() -> None:
    """The handler is the fleet's answer to "is this run yours?": a reply for a topic in
    `_children_by_topic`, a reply for a topic still in `_starting` (the spawn window — a
    probe landing there must answer "mine", or the guard reopens the race the starting
    registry exists to close), silence for anything else, and NEVER a reply to our own id.

    INVARIANT: no side effects. Unlike `_handle_control`, this handler must never touch a
    child — that is precisely why the probe is a separate subject from `url4.runctl.*`,
    whose handler SIGTERMs the owner."""
    pod = _pod(_LivePublisher(), control=_FakeBroker())
    child = _FakeProcess(hang=True)
    pod._children_by_topic["t-running"] = child  # noqa: SLF001
    pod._starting.add("t-spawning")  # noqa: SLF001
    foreign_id = b"some-other-pod"

    running = _ProbeMsg(ownership_subject_for("t-running"), foreign_id)
    spawning = _ProbeMsg(ownership_subject_for("t-spawning"), foreign_id)
    unowned = _ProbeMsg(ownership_subject_for("t-elsewhere"), foreign_id)
    own = _ProbeMsg(ownership_subject_for("t-running"), pod._worker_id.encode())  # noqa: SLF001
    for probe in (running, spawning, unowned, own):
        await pod._handle_ownership(probe)  # noqa: SLF001

    assert running.replied == [pod._worker_id.encode()], "an owner names itself"  # noqa: SLF001
    assert spawning.replied == [pod._worker_id.encode()], "the spawn window counts as owned"  # noqa: SLF001
    assert unowned.replied == [], "a non-owner stays SILENT — silence is the negative answer"
    assert own.replied == [], "a pod must never answer its own probe"
    assert child.terminate_calls == 0 and child.kill_calls == 0, "the handler has no side effects"


def test_the_ownership_subject_is_not_the_control_subject() -> None:
    """The probe rides its OWN subject. On `url4.runctl.*` an old worker mid rolling deploy
    would read a probe as the cancel that subject has always meant and SIGTERM a healthy
    run; on a new subject it simply never subscribes, never replies, and the prober fails
    open — today's behavior."""
    from screamingface_engine.subjects import CONTROL_SUBJECT_PREFIX

    assert OWNERSHIP_SUBJECT_PREFIX != CONTROL_SUBJECT_PREFIX
    assert not OWNERSHIP_SUBJECT_PREFIX.startswith(f"{CONTROL_SUBJECT_PREFIX}.")
    assert ownership_subject_for("t") == f"{OWNERSHIP_SUBJECT_PREFIX}.t"


def test_each_worker_pod_has_its_own_identity() -> None:
    """The worker id is what keeps a pod from vetoing its own claim, so two pods must never
    share one — and the supervisor must probe with the SAME id its handler drops."""
    first, second = _pod(_LivePublisher()), _pod(_LivePublisher())

    assert first._worker_id != second._worker_id  # noqa: SLF001
    assert first._supervisor._worker_id == first._worker_id  # noqa: SLF001
