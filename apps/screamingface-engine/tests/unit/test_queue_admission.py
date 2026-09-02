"""Depth-based admission (OME-1091): the queue runner refuses at the depth ceiling with
`JobRunnerAtCapacity`, the reservation counter closes the read-modify-write race between
two admissions in one refresh window, the per-caller in-flight cap bounds one caller's
footprint, and the REST edge derives `Retry-After` from a drain estimate instead of the
constant 1.

The counted resource changed from OME-1065 (quota headroom → queue depth); the
cache-plus-reservation shape did not. Depth and oldest-message age come from the queue's
cached `stream_info` reading; the runner's own refresh window plus the reservation counter
close the race when two `schedule()` calls land between refreshes.
"""

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport

from screamingface_engine.adapters.queue_runner import QueueJobRunner
from screamingface_engine.app import create_app
from screamingface_engine.auth import JwtCodec
from screamingface_engine.config import Settings
from screamingface_engine.ports import IdentityAwareJobRunner
from screamingface_engine.testing import InMemoryEventStream
from url4.streaming.interfaces import JobRunnerAtCapacity, JobStatus, job_name
from url4.streaming.protocol import CachePolicy

pytestmark = pytest.mark.asyncio

CAPABILITY_LIFETIME_S = 100.0
T0 = datetime(2026, 9, 2, 9, 0, 0, tzinfo=UTC)
SECRET = "admission-secret"
WINDOW_S = 60
LIFETIME_S = 58_800

CALLER_A: Mapping[str, str] = {"X-User-Email": "a@example.com"}
CALLER_B: Mapping[str, str] = {"X-User-Email": "b@example.com"}


class _FakeClock:
    """A wall clock the test advances by hand."""

    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class _FakeQueue:
    """The slice of `RunQueue` the queue runner uses, scripted per test."""

    def __init__(self, *, depth: int = 0, oldest_age: float | None = None) -> None:
        self._depth = depth
        self._oldest_age = oldest_age
        self.published: list[tuple[bytes, Mapping[str, str] | None]] = []

    async def publish(self, message: bytes, *, identity: Mapping[str, str] | None = None) -> None:
        self.published.append((message, identity))

    async def depth(self) -> int:
        return self._depth

    async def oldest_age(self) -> float | None:
        return self._oldest_age


class _FakePublisher:
    """The slice of `JetStreamPublisher` the queue runner reads, scripted per test."""

    def __init__(self, last_frame: Any = None) -> None:
        self._last_frame = last_frame
        self.published: list[Any] = []
        self.ensured: list[str] = []

    async def last_frame(self, topic: str) -> Any:
        return self._last_frame

    async def stream_exists(self, topic: str) -> bool:
        return True

    async def ensure_stream(self, topic: str) -> None:
        self.ensured.append(topic)

    async def publish(self, topic: str, event: Any) -> None:
        self.published.append(event)

    async def flush(self) -> None:
        pass


class _FakeControl:
    async def request(self, subject: str, payload: bytes, *, timeout: float) -> Any:
        raise TimeoutError()


def _runner(
    queue: _FakeQueue,
    *,
    depth_ceiling: int = 10,
    caller_inflight_cap: int = 8,
    clock: _FakeClock | None = None,
) -> QueueJobRunner:
    return QueueJobRunner(
        queue=queue,
        publisher=_FakePublisher(),
        control=_FakeControl(),
        clock=clock or _FakeClock(),
        capability_lifetime_s=CAPABILITY_LIFETIME_S,
        depth_ceiling=depth_ceiling,
        caller_inflight_cap=caller_inflight_cap,
    )


# --- 1. depth at the ceiling refuses -------------------------------------------------------


async def test_depth_at_the_ceiling_raises_job_runner_at_capacity() -> None:
    """A queue as deep as the ceiling refuses the run with `JobRunnerAtCapacity` — the
    substrate is saturated, and an identical retry later succeeds."""
    queue = _FakeQueue(depth=10)
    runner = _runner(queue, depth_ceiling=10)

    with pytest.raises(JobRunnerAtCapacity) as exc:
        await runner.schedule("t", "'hi'", 60)

    assert exc.value.limit == 10
    assert queue.published == []


async def test_depth_below_the_ceiling_is_admitted() -> None:
    """One below the ceiling is admitted — the ceiling is a bound, not a cliff."""
    queue = _FakeQueue(depth=9)
    runner = _runner(queue, depth_ceiling=10)

    name = await runner.schedule("t", "'hi'", 60)

    assert name == job_name("t")
    assert len(queue.published) == 1


async def test_the_drain_estimate_derives_retry_after_from_depth_and_throughput() -> None:
    """`Retry-After` is derived from the pool's observed throughput — the oldest message's
    wait implies the drain rate (`depth / oldest_age`) — so the client is told when the
    queue will actually have room, not the constant 1."""
    runner = _runner(_FakeQueue(depth=100, oldest_age=600.0), depth_ceiling=10)

    with pytest.raises(JobRunnerAtCapacity) as exc:
        await runner.schedule("t", "'hi'", 60)

    # rate = 100 / 600 = 1/6 per second; (100 - 10) / (1/6) = 540 seconds.
    assert exc.value.retry_after_s == 540


# --- 2. the reservation counter closes the race -------------------------------------------


async def test_two_admissions_racing_the_last_slot_cannot_both_pass() -> None:
    """Two admissions inside one refresh window both read the same cached depth; the
    reservation counter (OME-1065, carried over) makes the second see the first's
    reservation and refuse — the read-modify-write race does not survive the change of
    counted resource."""
    queue = _FakeQueue(depth=9)
    runner = _runner(queue, depth_ceiling=10)

    results = await asyncio.gather(
        runner.schedule("t1", "'hi'", 60),
        runner.schedule("t2", "'hi'", 60),
        return_exceptions=True,
    )

    accepted = [r for r in results if isinstance(r, str)]
    refused = [r for r in results if isinstance(r, JobRunnerAtCapacity)]
    assert len(accepted) == 1
    assert len(refused) == 1
    assert len(queue.published) == 1


# --- 3. the per-caller in-flight cap -------------------------------------------------------


async def test_the_per_caller_inflight_cap_refuses_caller_as_n_plus_one() -> None:
    """A caller at its in-flight cap is refused, while another caller is still admitted —
    one caller's 9-candidate evaluation cannot occupy every slot."""
    runner = _runner(_FakeQueue(), caller_inflight_cap=2)

    await runner.schedule("a1", "'hi'", 60, identity=CALLER_A)
    await runner.schedule("a2", "'hi'", 60, identity=CALLER_A)

    with pytest.raises(JobRunnerAtCapacity) as exc:
        await runner.schedule("a3", "'hi'", 60, identity=CALLER_A)
    assert exc.value.limit == 2

    # Caller B is unaffected by caller A's footprint.
    name = await runner.schedule("b1", "'hi'", 60, identity=CALLER_B)
    assert name == job_name("b1")


async def test_an_anonymous_caller_has_its_own_cap() -> None:
    """A caller with no identity is its own caller — the anonymous bucket — so it cannot
    hide behind another caller's footprint."""
    runner = _runner(_FakeQueue(), caller_inflight_cap=1)

    await runner.schedule("anon1", "'hi'", 60)
    with pytest.raises(JobRunnerAtCapacity):
        await runner.schedule("anon2", "'hi'", 60)
    await runner.schedule("a1", "'hi'", 60, identity=CALLER_A)  # a named caller is separate


# --- 4. the REST edge derives Retry-After --------------------------------------------------


class _AtCapacityRunner(IdentityAwareJobRunner):
    """A fake runner that refuses every schedule with a derived drain estimate."""

    async def schedule(
        self,
        topic: str,
        url4: str,
        deadline_s: int,
        *,
        traceparent: str | None = None,
        credential: str | None = None,
        profile: str | None = None,
        identity: Mapping[str, str] | None = None,
        cache: CachePolicy | None = None,
    ) -> str:
        raise JobRunnerAtCapacity(active=100, limit=10, retry_after_s=42)

    async def stop(self, topic: str) -> None:
        pass

    async def exists(self, topic: str) -> bool:
        return False

    async def status(self, topic: str) -> JobStatus:
        return "scheduled"


def _token(topic: str) -> str:
    return JwtCodec(secret=SECRET, iat_window_s=WINDOW_S, capability_lifetime_s=LIFETIME_S).sign(
        topic, T0
    )


def _make_app(runner: IdentityAwareJobRunner) -> FastAPI:
    settings = Settings(jwt_secret=SECRET, iat_window_s=WINDOW_S)
    return create_app(
        settings,
        stream=InMemoryEventStream(),
        job_runner=runner,
        clock=lambda: T0,
        interest=FixedGate(True),
    )


class FixedGate:
    def __init__(self, present: bool = True) -> None:
        self._present = present

    async def has_subscriber(self, topic: str) -> bool:
        return self._present


async def test_the_rest_edge_answers_503_with_a_derived_retry_after() -> None:
    """The 503 + `Retry-After` mapping is unchanged in shape, but the value is the drain
    estimate the runner attached to the refusal — not the constant 1."""
    app = _make_app(_AtCapacityRunner())
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/", params={"q": "gpt()"}, headers={"URL4-Capability": _token("topic-cap")}
        )

    assert resp.status_code == 503
    assert resp.headers["Retry-After"] == "42"
    assert resp.headers["Retry-After"] != "1"


# --- 5. the reservation counter's floor (review follow-up) ---------------------------------


async def test_a_release_racing_a_refresh_cannot_drive_the_counter_negative() -> None:
    """`_refresh_if_stale` RESETS `_reserved` on every refresh, and a sibling `schedule()`
    can land its refresh between this run's RESERVE and its RELEASE (the publish failed).
    Decrementing from the reset baseline drove the counter to -1 — under-counting depth
    forever after, so one extra run slips past the ceiling on every later admission. The
    release clamps at zero: a release below zero is a refresh that already accounted for
    the reservation."""
    clock = _FakeClock()
    queue = _FakeQueue(depth=9)
    runner = QueueJobRunner(
        queue=queue,
        publisher=_FakePublisher(),
        control=_FakeControl(),
        clock=clock,
        capability_lifetime_s=CAPABILITY_LIFETIME_S,
        depth_ceiling=10,
        state_cache_ttl_s=0.0,  # every check refreshes — the racing refresh is the point
    )

    async def refresh_then_fail(message: bytes, *, identity: Mapping[str, str] | None = None) -> None:
        # The racing sibling's refresh, landing between this run's reserve and release:
        # the depth now accounts for everything older than the window, so the counter
        # RESETS — and the release that follows must not decrement from that baseline.
        await runner._refresh_if_stale()
        raise OSError("broker unavailable")

    queue.publish = refresh_then_fail  # type: ignore[method-assign]

    with pytest.raises(OSError):
        await runner.schedule("t-race", "'hi'", 60, identity=CALLER_A)

    assert runner._reserved == 0, "a release must never drive the counter negative"

    # The clamp is load-bearing: with the counter at -1 this admission check reads
    # depth 10 + (-1) < 10 and lets a run PAST the ceiling.
    queue._depth = 10
    with pytest.raises(JobRunnerAtCapacity):
        await runner.schedule("t-next", "'hi'", 60, identity=CALLER_A)


async def test_a_readmitted_topic_does_not_orphan_the_first_callers_slot() -> None:
    """`_caller_of_topic[topic]` is OVERWRITTEN when a re-scheduled topic is admitted
    under a second identity, and `_forget_in_flight` used to resolve the caller through
    that mapping — so the FIRST caller's entry was never reached again (`_prune` routes
    through it too) and that caller permanently lost one of its in-flight slots,
    surfacing later as spurious 503s for a caller with no live runs. The forget now
    removes the topic from every caller that holds it."""
    from url4.streaming.protocol import TerminatedData, TerminatedEvent, source_for

    runner = _runner(_FakeQueue(), caller_inflight_cap=2, clock=_FakeClock())
    key_a = "a@example.com"
    key_b = "b@example.com"

    await runner.schedule("t-shared", "'hi'", 60, identity=CALLER_A)
    await runner.schedule("t-shared", "'hi'", 60, identity=CALLER_B)  # the overwrite

    assert runner._caller_of_topic["t-shared"] == key_b
    assert "t-shared" in runner._in_flight_by_caller[key_a], "both callers hold the topic"

    # The run ends: a terminal frame NEWER than both admissions reaches the forget.
    frame = TerminatedEvent(
        id="t",
        source=source_for("t-shared"),
        subject="t-shared",
        time=T0 + timedelta(seconds=5),
        data=TerminatedData(status="succeeded"),
    )
    runner._forget_in_flight("t-shared", frame)

    assert key_a not in runner._in_flight_by_caller, "A's slot must be released, not orphaned"
    assert key_b not in runner._in_flight_by_caller
    assert "t-shared" not in runner._caller_of_topic

    # And A keeps its full cap — the orphaned entry used to eat one slot forever.
    await runner.schedule("a-1", "'hi'", 60, identity=CALLER_A)
    await runner.schedule("a-2", "'hi'", 60, identity=CALLER_A)


# --- 6. a cancelled schedule must not leak its reservation (review follow-up) ---------------


class _HangingQueue(_FakeQueue):
    """A queue whose publish hangs until the test releases it — the cancellation lands
    mid-publish, exactly the window a client disconnect or upstream timeout hits."""

    def __init__(self) -> None:
        super().__init__()
        self._release = asyncio.Event()

    async def publish(
        self, message: bytes, *, identity: Mapping[str, str] | None = None
    ) -> None:
        await self._release.wait()

    def finish(self) -> None:
        self._release.set()


async def test_a_schedule_cancelled_mid_publish_releases_its_reservation() -> None:
    """`CancelledError` is a BaseException, not an Exception — since 3.8 precisely so
    `except Exception` cannot swallow it. The release-on-failure clause never ran on a
    cancelled publish: the reservation leaked (`_reserved` stuck, the caller's in-flight
    entry a dead topic forever), and a caller whose clients keep disconnecting under
    load ends up permanently refused for runs that never queued. Cleanup must run on the
    cancellation path too — with the cancellation still propagating."""
    queue = _HangingQueue()
    runner = _runner(queue)

    task = asyncio.create_task(runner.schedule("t-hang", "'hi'", 60, identity=CALLER_A))
    await asyncio.sleep(0)  # let the task reach the hanging publish
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert runner._reserved == 0, "a cancelled schedule must release its reservation"
    key_a = "a@example.com"
    assert key_a not in runner._in_flight_by_caller, "no dead topic may linger"
    queue.finish()


# --- 7. a failed re-admission may not erase the first caller's slot (review follow-up) ------


class _FailingQueue(_FakeQueue):
    """A queue that publishes fine until armed, then rejects — the transient broker error
    that leaves an admitted-but-unpublished run behind."""

    def __init__(self) -> None:
        super().__init__()
        self.fail_next = False

    async def publish(
        self, message: bytes, *, identity: Mapping[str, str] | None = None
    ) -> None:
        if self.fail_next:
            self.fail_next = False
            raise OSError("broker unavailable")
        await super().publish(message, identity=identity)


async def test_a_failed_readmission_releases_only_its_own_callers_slot() -> None:
    """A re-scheduled topic can be held by TWO callers at once (admission overwrites
    `_caller_of_topic` but not the first caller's dict entry). The release used the shared
    `_forget_in_flight`, whose no-frame path wipes EVERY caller holding the topic — so a
    failed publish under the SECOND identity also erased the FIRST caller's still-live
    admission, under-counting it and letting it exceed its in-flight cap. The release now
    pops exactly the caller/topic pair it reserved."""
    key_a = "a@example.com"
    key_b = "b@example.com"
    queue = _FailingQueue()
    runner = _runner(queue, caller_inflight_cap=2)

    # Caller A's admission of the shared topic — durable, still live.
    await runner.schedule("t-shared", "'hi'", 60, identity=CALLER_A)
    # Caller B re-admits the same topic, then its publish fails.
    queue.fail_next = True
    with pytest.raises(OSError):
        await runner.schedule("t-shared", "'hi'", 60, identity=CALLER_B)

    assert "t-shared" in runner._in_flight_by_caller[key_a], "A's slot must survive B's failure"
    assert key_b not in runner._in_flight_by_caller, "B's own failed entry is released"
    # (`_caller_of_topic` is write-only bookkeeping — the wipe scans every caller — so its
    # stale B entry is harmless; the in-flight maps above are the contract.)
    assert runner._reserved == 1, "exactly one live reservation remains"


# --- 8. the Retry-After header is always delta-seconds (review follow-up) --------------------


class _FractionalRunner(_AtCapacityRunner):
    """A runner whose drain estimate is a fractional float — legal at runtime even though
    the port types it `int | None`; the HTTP boundary must not care."""

    async def schedule(self, *args: Any, **kwargs: Any) -> str:
        raise JobRunnerAtCapacity(2, 10, retry_after_s=2.5)  # type: ignore[arg-type]


async def test_a_fractional_estimate_is_ceiled_into_a_valid_retry_after_header() -> None:
    """`Retry-After` is delta-seconds per RFC 7231 — a non-negative decimal INTEGER. The
    header used `str(retry_after)`; today's only producer happens to ceil, but any future
    adapter returning a float (an averaged latency, say) would emit "2.5" — malformed,
    which clients reject or ignore. The boundary ceils: 2.5 renders as "3", rounding UP
    so the caller is never told to retry sooner than the estimate."""
    app = _make_app(_FractionalRunner())
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/", params={"q": "gpt()"}, headers={"URL4-Capability": _token("topic-frac")}
        )

    assert resp.status_code == 503
    assert resp.headers["Retry-After"] == "3"


# --- 9. a failed retry of a LIVE topic releases only its own reservation (review follow-up) --


class _FailsSecondPublishQueue(_FakeQueue):
    """Publishes the first submission of a topic; rejects the retry — a client retry
    outside the broker's dedupe window meeting a transient broker error."""

    def __init__(self) -> None:
        super().__init__()
        self._failed_once = False

    async def publish(
        self, message: bytes, *, identity: Mapping[str, str] | None = None
    ) -> None:
        from screamingface_engine.runner_queue import topic_of_message

        if topic_of_message(message) == "t-retry" and self.published:
            self._failed_once = True
            raise OSError("broker unavailable")
        await super().publish(message, identity=identity)


async def test_a_failed_retry_of_a_live_topic_keeps_the_first_admission_counted() -> None:
    """A caller's client can re-schedule a STILL-LIVE topic — a retry outside the
    broker's dedupe window — and that retry's publish can fail. Releasing by the
    (caller, topic) pair erased the FIRST admission's accounting with the failed
    retry: the caller's in-flight count silently dropped by one for the rest of the
    run's lifetime, letting it exceed its cap by exactly that much. The release now
    removes only the reservation the retry itself minted."""
    queue = _FailsSecondPublishQueue()
    runner = _runner(queue, caller_inflight_cap=2)
    identity = {"sub": "caller-a"}

    await runner.schedule("t-retry", "'hi'", 60, identity=identity)  # live admission
    with pytest.raises(OSError):
        await runner.schedule("t-retry", "'hi'", 60, identity=identity)  # retry fails
    await runner.schedule("t-other", "'hi'", 60, identity=identity)  # count: 2 — at cap

    with pytest.raises(JobRunnerAtCapacity):
        # If the failed retry had erased the first admission, this would be admitted
        # (count read 1) — one run PAST the caller's cap.
        await runner.schedule("t-third", "'hi'", 60, identity=identity)
