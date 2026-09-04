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

import nats.errors
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

    def __init__(
        self, messages: list[bytes], fetch_log: list[str] | None = None, subject: str = ""
    ) -> None:
        self._messages = messages
        self.unsubscribed = False
        self._fetch_log = fetch_log
        self._subject = subject
        self.nakked: list[Any] = []
        self.timeouts: list[float] = []

    async def fetch(self, batch: int, timeout: float) -> list[Any]:
        if self._fetch_log is not None:
            self._fetch_log.append(self._subject)
        self.timeouts.append(timeout)
        out = self._messages[:batch]
        del self._messages[:batch]
        if not out:
            raise TimeoutError("nats: timeout")
        return [SimpleNamespace(data=payload, nak=self._record_nak) for payload in out]

    async def _record_nak(self) -> None:
        self.nakked.append(1)

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
        self.subs: list[_FakeSub] = []
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
        sub = _FakeSub(self._messages.get(subject, []), fetch_log=self.fetches, subject=subject)
        self.subs.append(sub)
        return sub


def _queue(fake: _FakeJetStream, **kwargs: Any) -> RunQueue:
    queue = RunQueue("nats://unused:4222", **kwargs)

    async def _fake_jetstream() -> _FakeJetStream:
        return fake

    queue._jetstream = _fake_jetstream  # type: ignore[assignment,method-assign]
    return queue


# --- 1. round-robin pull interleaves two callers -------------------------------------------


async def test_round_robin_pull_interleaves_two_callers_runs() -> None:
    """Round-robin pull serves at most `PULL_BUCKET_BATCH` (or the batch's fair share)
    per bucket per visit, so two callers SHARE a pull instead of one draining first —
    the per-visit cap, not strict one-per-bucket alternation, is the fairness property
    (review follow-up P2-7: the cap lets a single caller's burst drain several messages
    per poll instead of ~1 per poll)."""
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

    # Each visit takes at most ceil(4/2) = 2 from one bucket, so the pull is two
    # consecutive visits — each caller's pair — and NEITHER caller can take more than
    # its pair before the other is served.
    caller_of = {"a1": "A", "a2": "A", "b1": "B", "b2": "B"}
    assert [caller_of[t] for t in topics] in (["A", "A", "B", "B"], ["B", "B", "A", "A"])


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
    # Each pull fetches per bucket VISIT: the fast pass always visits every bucket once,
    # and (against these instant fakes, where budget remains) the slow pass visits them
    # again — 2 buckets x 2 phases x 3 pulls. The BIND count above is the cost fix this
    # test pins; the fetch count only documents the visit structure.
    assert len(fake.fetches) == 12, "each pull fetches per bucket visit of both phases"


async def test_one_callers_burst_fills_the_batch_from_one_bucket() -> None:
    """P2-7: one message per bucket per visit let a single caller's burst drain at ~1
    run per poll — the rest of the rotation burned the budget on empty buckets while the
    burst sat in its bucket, capping the caller at ~1 run per `timeout_s` per worker
    regardless of free slots. The per-visit fetch cap lets a burst fill the batch from
    one bucket while the rotation (and the cap) still bounds its share of a shared pull."""
    fake = _FakeJetStream()
    queue = _queue(fake, bucket_count=16)
    for i in range(8):
        await queue.publish(encode_message(f"burst-{i}", "'hi'", 60), identity=CALLER_A)

    pulled = await queue.pull(4, timeout_s=0.5)

    assert len(pulled) == 4, "a single caller's burst must fill the batch, not trickle 1 per poll"


async def test_a_pull_that_over_returns_clamps_and_naks_the_surplus() -> None:
    """V-4: nats-py's `_fetch_n` (want >= 2) drains the subscription's PENDING queue with
    no `needed` guard, so a held sub carrying late deliveries from a previous poll can
    return MORE than asked — and the claim loop spawns one supervisor per returned
    message, so an unclamped extend over-subscribed the pod past `worker_slots`. The
    pull must clamp to the per-visit cap and NAK the surplus back to the queue — not
    drop it, and not ack it away."""
    fake = _FakeJetStream()

    class _OverReturningSub(_FakeSub):
        """Serves one more than asked — the `_fetch_n` pending-queue drain shape."""

        async def fetch(self, batch: int, timeout: float) -> list[Any]:
            return await super().fetch(batch + 1, timeout)

    sub = _OverReturningSub([b"m1", b"m2", b"m3"], subject="url4-runq.0")
    fake.pull_subscribe = _pull_subscribe_returning(sub)  # type: ignore[method-assign]

    queue = _queue(fake, bucket_count=1)
    msgs = await queue.pull(2, timeout_s=1.0)

    assert len(msgs) == 2, "the pull must clamp to the batch, never over-return"
    assert len(sub.nakked) == 1, "the surplus must be NAK'd back to the queue"


def _pull_subscribe_returning(sub: _FakeSub) -> Any:
    async def _pull_subscribe(
        subject: str, durable: str | None = None, stream: str | None = None, config: Any = None
    ) -> _FakeSub:
        return sub

    return _pull_subscribe


async def test_the_fast_pass_uses_short_windows_and_the_slow_pass_the_remainder() -> None:
    """V-9: `_FakeSub.fetch` ignored `timeout`, so the P2-7 fast/slow split was
    unexercised — the test could not tell a two-phase pull from a uniform one. The fake
    now records every window: the first rotation's windows must total
    `PULL_FAST_PASS_S` (short, burst-collecting), and the slow pass must spend the
    REMAINING budget on a second rotation."""
    from screamingface_engine.runner_queue import PULL_FAST_PASS_S

    fake = _FakeJetStream()
    queue = _queue(fake, bucket_count=4)
    await queue.publish(encode_message("a1", "'hi'", 60), identity=CALLER_A)

    await queue.pull(4, timeout_s=5.0)

    assert len(fake.subs) == 4
    # The first rotation (fast pass) is one short window per bucket.
    fast_windows = [s.timeouts[0] for s in fake.subs]
    assert all(w == pytest.approx(min(PULL_FAST_PASS_S, 5.0) / 4) for w in fast_windows)
    # The slow pass re-visits with the remaining budget split across the rotation.
    slow_windows = [s.timeouts[1] for s in fake.subs]
    assert all(w > fast_windows[0] for w in slow_windows), "the slow pass must spend the remainder"


# --- 6. a blip mid-rotation must not discard what the rotation already collected ----------


class _ErroringJetStream(_FakeJetStream):
    """One nominated bucket's fetch fails with a real broker error; every other bucket
    behaves normally. Set `failing` AFTER publishing, so the test can pick the bucket the
    message did NOT land in."""

    failing: str | None = None

    async def pull_subscribe(
        self,
        subject: str,
        durable: str | None = None,
        stream: str | None = None,
        config: Any = None,
    ) -> _FakeSub:
        sub = await super().pull_subscribe(subject, durable, stream, config)
        if subject == self.failing:

            async def _boom(batch: int, timeout: float) -> list[Any]:
                raise nats.errors.Error("broker blip mid-rotation")

            sub.fetch = _boom  # type: ignore[method-assign]
        return sub


def _bucket_index(subject: str) -> int:
    """The bucket ordinal encoded in a run-queue subject (`url4-runq.0a` -> 10)."""
    return int(subject.rsplit(".", 1)[1], 16)


async def test_a_blip_mid_rotation_keeps_the_messages_already_collected() -> None:
    """`_fetch_from` re-raises a non-timeout `nats.errors.Error` after invalidating the
    subscription, and `pull` extends `collected` bucket by bucket — so a blip on a LATER
    bucket discarded every message the earlier buckets had already yielded, along with the
    stack frame holding them. Those messages had been DELIVERED: they were never acked and
    never NAK'd, so they sat out the full `ack_wait` and came back as their FINAL delivery
    (`DEFAULT_MAX_DELIVER` is 2). One more blip on that redelivery ends the run as
    `max_deliveries` instead of executing it.

    INVARIANT: a delivery attempt is expensive and must never be spent for nothing. Work
    already in hand is returned; the blip is reported by the NEXT pull, which hits the same
    broker. Only a pull that collected NOTHING propagates, so the claim loop keeps its
    backoff signal for a genuinely unproductive poll."""
    fake = _ErroringJetStream()
    queue = _queue(fake, bucket_count=2)
    await queue.publish(encode_message("a1", "'hi'", 60), identity=CALLER_A)

    landed = fake.published[0][0]
    # Fail the OTHER bucket, and start the rotation on the one holding the message so the
    # blip lands with something already collected.
    fake.failing = f"url4-runq.{(_bucket_index(landed) + 1) % 2:02x}"
    queue._rr_index = _bucket_index(landed)  # noqa: SLF001

    pulled = await queue.pull(2, timeout_s=1.0)

    assert [topic_of_message(msg.data) for msg in pulled] == ["a1"], (
        "the message collected before the blip must be returned, not dropped"
    )
    assert all(not sub.nakked for sub in fake.subs), (
        "a collected message must not spend a delivery attempt on a NAK either"
    )


async def test_a_blip_with_nothing_collected_still_propagates() -> None:
    """The claim loop counts pull failures and backs off on them, so a poll that produced
    NO work must still report the blip. Swallowing it unconditionally would turn a broker
    outage into a silent hot loop that looks exactly like an idle queue."""
    fake = _ErroringJetStream()
    queue = _queue(fake, bucket_count=1)
    fake.failing = "url4-runq.00"

    with pytest.raises(nats.errors.Error):
        await queue.pull(2, timeout_s=1.0)
