"""Run-level and fetch-level fairness (OME-1091, the deployed half of OME-908).

Run-level: per-caller queue subjects (`url4-runq.<bucket>`, a stable hash of the identity
value — never the raw address, which a subject name would expose to anyone with broker
access) with round-robin pull, so one caller's 9-candidate evaluation cannot drain ahead of
another caller's runs. Fetch-level: the worker's spawn-time io budget
(`worker_io_capacity / active_children`) travels to the child as
`URL4_CLOUD_IO_CONCURRENCY`, fixed at spawn.
"""

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from screamingface_engine import job_env
from screamingface_engine.runner_queue import RunQueue, encode_message, topic_of_message
from screamingface_engine.worker.supervisor import RunSupervisor

pytestmark = pytest.mark.asyncio

CALLER_A: Mapping[str, str] = {"X-User-Email": "a@example.com"}
CALLER_B: Mapping[str, str] = {"X-User-Email": "alice@example.com"}


class _FakeSub:
    """A pull subscription that serves the SHARED per-subject message list — a message
    claimed by one subscription is gone for the next, like the broker's consumer state.

    An EMPTY window RAISES, exactly like the real broker: nats-py's `fetch` never
    returns an empty list, it raises `nats.errors.TimeoutError` (a `TimeoutError`
    subclass). A fake returning `[]` masks an uncaught-timeout crash in `pull`."""

    def __init__(self, messages: list[bytes], fetch_log: list[str] | None = None, subject: str = "") -> None:
        self._messages = messages
        self.unsubscribed = False
        self._fetch_log = fetch_log
        self._subject = subject

    async def fetch(self, batch: int, timeout: float) -> list[Any]:
        if self._fetch_log is not None:
            self._fetch_log.append(self._subject)
        out = self._messages[:batch]
        del self._messages[:batch]
        if not out:
            raise TimeoutError("nats: timeout")
        return [SimpleNamespace(data=payload) for payload in out]

    async def unsubscribe(self) -> None:
        self.unsubscribed = True


class _FakeJetStream:
    """The slice of `JetStreamContext` the queue uses, subject-aware: publishes land on the
    subject they were given, and each pull subscription serves that subject's messages."""

    def __init__(self) -> None:
        self._messages: dict[str, list[bytes]] = {}
        self.published: list[tuple[str, bytes]] = []
        self.pull_subjects: list[str] = []
        self.bound_subjects: list[str] = []
        self.fetches: list[str] = []
        self._prefix = "$JS.API"

    async def add_stream(self, **kwargs: Any) -> object:
        return object()

    async def publish(
        self, subject: str, payload: bytes = b"", headers: dict[str, str] | None = None, **_: Any
    ) -> object:
        self.published.append((subject, payload))
        self._messages.setdefault(subject, []).append(payload)
        return SimpleNamespace(stream="url4-runq", seq=len(self.published))

    async def _api_request(self, subject: str, req: bytes = b"", **_: Any) -> dict[str, Any]:
        return {"state": {"messages": 0, "first_ts": None}}

    async def pull_subscribe(
        self,
        subject: str,
        durable: str | None = None,
        stream: str | None = None,
        config: Any = None,
    ) -> _FakeSub:
        self.pull_subjects.append(subject)
        self.bound_subjects.append(subject)
        return _FakeSub(self._messages.get(subject, []), fetch_log=self.fetches, subject=subject)


def _queue(fake: _FakeJetStream, **kwargs: Any) -> RunQueue:
    queue = RunQueue("nats://unused:4222", **kwargs)

    async def _fake_jetstream() -> _FakeJetStream:
        return fake

    queue._jetstream = _fake_jetstream  # type: ignore[assignment,method-assign]
    return queue


# --- 1. round-robin pull interleaves two callers -------------------------------------------


async def test_round_robin_pull_interleaves_two_callers_runs() -> None:
    """Round-robin pull serves one message per bucket per cycle, so two callers' runs
    interleave instead of one caller draining first."""
    fake = _FakeJetStream()
    queue = _queue(fake, bucket_count=2)
    await queue.publish(encode_message("a1", "'hi'", 60), identity=CALLER_A)
    await queue.publish(encode_message("a2", "'hi'", 60), identity=CALLER_A)
    await queue.publish(encode_message("b1", "'hi'", 60), identity=CALLER_B)
    await queue.publish(encode_message("b2", "'hi'", 60), identity=CALLER_B)

    # The two callers must land in different buckets for the interleaving to be visible.
    assert len({subject for subject, _ in fake.published}) == 2

    pulled = await queue.pull(4, timeout_s=1.0)
    topics = [topic_of_message(msg.data) for msg in pulled]

    caller_of = {"a1": "A", "a2": "A", "b1": "B", "b2": "B"}
    assert [caller_of[t] for t in topics] in (["A", "B", "A", "B"], ["B", "A", "B", "A"])


async def test_the_bucket_key_is_a_stable_hash_of_the_identity_value() -> None:
    """The bucket key is a stable hash of the identity VALUE, not the raw address — a
    subject name is readable by anything with broker access, so the caller's email must
    not appear in it."""
    queue = _queue(_FakeJetStream(), bucket_count=16)
    subject = queue.bucket_subject(CALLER_A)

    assert subject.startswith("url4-runq.")
    assert "a@example.com" not in subject
    assert subject == queue.bucket_subject(CALLER_A)  # stable across calls


async def test_a_pull_that_finds_nothing_returns_within_the_timeout() -> None:
    """An empty queue still returns within the pull timeout — each bucket gets a share of
    the budget, so no single bucket can hold the pull open."""
    fake = _FakeJetStream()
    queue = _queue(fake, bucket_count=2)

    pulled = await queue.pull(4, timeout_s=0.2)

    assert pulled == []
    # The pull still cycled both buckets every slot — four FETCHES — but bound each
    # bucket's durable subscription ONCE: the held-subscription cache (review
    # follow-up) removes the per-cycle bind/unbind round trip from every poll.
    assert fake.fetches == [
        queue.bucket_subjects()[0],
        queue.bucket_subjects()[1],
        queue.bucket_subjects()[0],
        queue.bucket_subjects()[1],
    ]
    assert fake.bound_subjects == [
        queue.bucket_subjects()[0],
        queue.bucket_subjects()[1],
    ]


# --- 2. the spawn-time io budget -----------------------------------------------------------


class _FakeMsg:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.metadata = SimpleNamespace(timestamp=datetime.now(UTC))
        self.acked = False

    async def ack(self) -> None:
        self.acked = True

    async def in_progress(self) -> None:
        pass


class _FakeProcess:
    def __init__(self, *, hang: bool = True) -> None:
        self._hang = hang
        self._released = asyncio.Event()
        self.returncode: int | None = None
        self.stdout = None
        self.stderr = None

    async def wait(self) -> int:
        if self._hang:
            await self._released.wait()
        self.returncode = 0
        return 0

    def release(self) -> None:
        self._released.set()

    def terminate(self) -> None:
        self.release()

    def kill(self) -> None:
        self.release()


class _FakePublisher:
    async def last_frame(self, topic: str) -> Any:
        return None

    async def ensure_stream(self, topic: str) -> None:
        pass

    async def publish(self, topic: str, event: Any) -> None:
        pass

    async def flush(self) -> None:
        pass


async def _wait_until(predicate: Any, timeout_s: float = 2.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.01)


def _supervisor(spawn: Any, *, io_capacity: int = 4) -> RunSupervisor:
    return RunSupervisor(
        publisher=_FakePublisher(),
        spawn=spawn,
        memory_budget_bytes=1024**3,
        io_capacity=io_capacity,
        draining=asyncio.Event(),
        terminating=asyncio.Event(),
        children=set(),
        children_by_topic={},
        cancelled=set(),
    )


async def test_the_spawn_time_io_budget_is_io_capacity_over_active_children() -> None:
    """The worker's io budget is `io_capacity / active_children` (the new child included),
    written onto the child env as `URL4_CLOUD_IO_CONCURRENCY` — a solo child gets the full
    capacity, the second child gets half, and the budget is fixed at spawn."""
    envs: list[dict[str, str]] = []
    procs: list[_FakeProcess] = []

    async def fake_spawn(*args: Any, **kwargs: Any) -> _FakeProcess:
        envs.append(kwargs["env"])
        proc = _FakeProcess(hang=True)
        procs.append(proc)
        return proc

    supervisor = _supervisor(fake_spawn, io_capacity=4)
    async with asyncio.TaskGroup() as tg:
        first = tg.create_task(supervisor.supervise(_FakeMsg(encode_message("t1", "'hi'", 60))))
        await _wait_until(lambda: len(procs) == 1)
        second = tg.create_task(supervisor.supervise(_FakeMsg(encode_message("t2", "'hi'", 60))))
        await _wait_until(lambda: len(procs) == 2)

        assert envs[0][job_env.IO_CONCURRENCY] == "4"  # solo: 4 / 1
        assert envs[1][job_env.IO_CONCURRENCY] == "2"  # two active: 4 / 2

        for proc in procs:
            proc.release()
        await first
        await second


# --- held pull subscriptions (review follow-up) ----------------------------------------------


async def test_pulls_bind_each_bucket_once_and_reuse_their_subscription() -> None:
    """The claim loop polls flat out whenever slots are free, and the old pull bound a
    FRESH subscription per bucket PER CYCLE — a `consumer_info` round trip each way,
    multiplied by the bucket count, paid on every poll even when the queue was empty.
    Bind-per-cycle was a multiplicative cost with no correctness benefit: the durable
    consumers are server-side and persist. Subscriptions are now HELD (bounded by the
    configured bucket list; cleared on reconnect), so every poll after the first costs
    the `fetch` alone."""
    fake = _FakeJetStream()
    queue = _queue(fake, bucket_count=2)

    for _ in range(3):
        await queue.pull(1, timeout_s=0.01)

    assert len(fake.bound_subjects) == 2, "one bind per bucket for the queue's lifetime"
    assert len(fake.fetches) == 6, "each pull still fetches per slot of the rotation"
