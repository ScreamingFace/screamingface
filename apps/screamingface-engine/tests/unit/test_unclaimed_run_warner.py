"""The unclaimed-run warner's policy: one generic WARN for a queued run nobody has claimed.

FEATURE: warn the client about an unclaimed queued run (under OME-1086; the residual gap of
OME-1059 and OME-948).

Every test drives the runner's ages by hand and calls `sweep()` directly — no sleeps. The
lesson this suite guards (`14982d83`, PR #822): the queue-position notice fired on EVERY run of
a healthy stack and was removed as noise. This notice must fire only on a real wait.
"""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from screamingface_engine.adapters.jetstream import QueueReadError
from screamingface_engine.adapters.queue_runner import QueueJobRunner
from screamingface_engine.unclaimed import UNCLAIMED_MESSAGE, UnclaimedRunWarner
from url4.streaming.interfaces import JobStatus
from url4.streaming.protocol import LogEvent, OutboundFrame, StartedData, StartedEvent

GRACE = 300.0
T0 = datetime(2026, 9, 28, 9, 0, 0, tzinfo=UTC)


class _Runner:
    """`ages` is `accepted_ages()`; `statuses` answers `status()`; `unreadable` raises."""

    def __init__(self) -> None:
        self.ages: dict[str, float] = {}
        self.statuses: dict[str, JobStatus] = {}
        self.unreadable: set[str] = set()
        self.status_reads: list[str] = []

    def accepted_ages(self) -> dict[str, float]:
        return dict(self.ages)

    async def status(self, topic: str) -> JobStatus:
        self.status_reads.append(topic)
        if topic in self.unreadable:
            raise QueueReadError("stream tail unreadable")
        return self.statuses.get(topic, "scheduled")


class _Audience:
    def __init__(self, present: set[str] | None = None) -> None:
        self.present = present if present is not None else set()
        self.notices: list[tuple[str, OutboundFrame]] = []

    async def has_subscriber(self, topic: str) -> bool:
        return topic in self.present

    def notify(self, topic: str, frame: OutboundFrame) -> None:
        self.notices.append((topic, frame))

    @property
    def warned(self) -> list[str]:
        return [topic for topic, _ in self.notices]


def _warner(runs: Any, audience: _Audience, grace_s: float = GRACE) -> UnclaimedRunWarner:
    return UnclaimedRunWarner(runs, audience, grace_s=grace_s, frame_clock=lambda: T0)


@pytest.mark.asyncio
async def test_a_run_queued_past_the_grace_is_warned_once() -> None:
    runner, audience = _Runner(), _Audience({"t"})
    runner.ages["t"] = GRACE + 1
    warner = _warner(runner, audience)

    await warner.sweep()
    runner.ages["t"] = GRACE * 10
    await warner.sweep()

    # INVARIANT: at most ONE notice per run, however long it keeps waiting.
    assert audience.warned == ["t"]
    assert runner.status_reads == ["t"]


@pytest.mark.asyncio
async def test_the_notice_is_a_generic_warn_log_frame_for_the_topic() -> None:
    runner, audience = _Runner(), _Audience({"t"})
    runner.ages["t"] = 301.7
    await _warner(runner, audience).sweep()

    [(topic, frame)] = audience.notices
    assert topic == "t"
    assert isinstance(frame, LogEvent)
    assert frame.subject == "t"
    # The App's clock stamps the frame, not a private one.
    assert frame.time == T0
    assert frame.data.severity_text == "WARN"
    assert frame.data.body == UNCLAIMED_MESSAGE
    assert frame.data.attributes == {"run.wait_s": 301}


def test_the_message_names_no_internals() -> None:
    """INVARIANT: symptom, not cause — no queue depth, pod, bucket, subject or broker name."""
    assert UNCLAIMED_MESSAGE == (
        "the runner service is at capacity; your run is queued and has not started yet"
    )
    for internal in ("nats", "jetstream", "pod", "bucket", "url4", "depth", "worker"):
        assert internal not in UNCLAIMED_MESSAGE.lower()


@pytest.mark.asyncio
async def test_a_run_inside_the_grace_is_not_warned_or_read() -> None:
    runner, audience = _Runner(), _Audience({"t"})
    runner.ages["t"] = GRACE - 0.001

    await _warner(runner, audience).sweep()

    assert audience.notices == []
    # WHY asserted: a healthy stack must cost no broker read at all inside the grace.
    assert runner.status_reads == []


@pytest.mark.parametrize(
    "status", ["running", "succeeded", "failed", "stopped", "timed_out", "not_found"]
)
@pytest.mark.asyncio
async def test_a_run_that_is_not_scheduled_is_never_warned_and_never_read_again(
    status: JobStatus,
) -> None:
    """INVARIANT: never for a run that started. Any frame on the stream reads non-`scheduled`,
    and the decision is final — the topic costs no further read."""
    runner, audience = _Runner(), _Audience({"t"})
    runner.ages["t"] = GRACE + 1
    runner.statuses["t"] = status
    warner = _warner(runner, audience)

    await warner.sweep()
    runner.statuses["t"] = "scheduled"  # even if a later read were to disagree
    await warner.sweep()

    assert audience.notices == []
    assert runner.status_reads == ["t"]


@pytest.mark.asyncio
async def test_no_audience_means_no_notice_and_no_decision() -> None:
    """A topic with nobody attached is checked again, so a client that reconnects while its
    run is still queued is told."""
    runner, audience = _Runner(), _Audience()
    runner.ages["t"] = GRACE + 1
    warner = _warner(runner, audience)

    await warner.sweep()
    assert audience.notices == []
    assert runner.status_reads == []

    audience.present.add("t")
    await warner.sweep()
    assert audience.warned == ["t"]


@pytest.mark.asyncio
async def test_an_unreadable_tail_is_unknown_and_retried() -> None:
    runner, audience = _Runner(), _Audience({"t"})
    runner.ages["t"] = GRACE + 1
    runner.unreadable.add("t")
    warner = _warner(runner, audience)

    await warner.sweep()
    assert audience.notices == []

    runner.unreadable.clear()
    await warner.sweep()
    assert audience.warned == ["t"]


@pytest.mark.asyncio
async def test_one_unreadable_topic_does_not_hide_another() -> None:
    runner, audience = _Runner(), _Audience({"a", "b"})
    runner.ages.update({"a": GRACE + 1, "b": GRACE + 1})
    runner.unreadable.add("a")

    await _warner(runner, audience).sweep()

    assert audience.warned == ["b"]


@pytest.mark.asyncio
async def test_decisions_are_forgotten_with_the_runner_record() -> None:
    """The decision set stays bounded by the runner's own record (capability expiry): a topic
    the runner forgot is forgotten here too, so the same topic accepted again is judged anew."""
    runner, audience = _Runner(), _Audience({"t"})
    runner.ages["t"] = GRACE + 1
    warner = _warner(runner, audience)
    await warner.sweep()

    del runner.ages["t"]
    await warner.sweep()
    runner.ages["t"] = GRACE + 1
    await warner.sweep()

    assert audience.warned == ["t", "t"]


@pytest.mark.parametrize(("grace", "tick"), [(300.0, 37.5), (4.0, 1.0), (0.5, 1.0)])
def test_the_tick_is_an_eighth_of_the_grace_with_a_one_second_floor(
    grace: float, tick: float
) -> None:
    assert _warner(_Runner(), _Audience(), grace_s=grace).tick_s == tick


# --- against the REAL QueueJobRunner.status() -----------------------------------------------


class _Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


class _Queue:
    async def publish(self, message: bytes, *, identity: Mapping[str, str] | None = None) -> None:
        pass

    async def depth(self) -> int:
        return 0

    async def oldest_age(self) -> float | None:
        return None


class _Stream:
    """The run's event stream tail, as `JetStreamPublisher.last_frame` would answer."""

    def __init__(self) -> None:
        self.tail: dict[str, Any] = {}

    async def last_frame(self, topic: str) -> Any:
        return self.tail.get(topic)

    async def ensure_stream(self, topic: str) -> None:
        pass

    async def publish(self, topic: str, event: Any) -> None:
        pass

    async def flush(self) -> None:
        pass


class _Control:
    async def request(self, subject: str, payload: bytes, *, timeout: float) -> Any:
        raise TimeoutError()


async def _real_runner(topic: str) -> tuple[QueueJobRunner, _Stream]:
    clock, stream = _Clock(), _Stream()
    runner = QueueJobRunner(
        queue=_Queue(),
        publisher=stream,
        control=_Control(),
        clock=clock,
        capability_lifetime_s=58_800,
    )
    await runner.schedule(topic, "'hi'", 60)
    clock.now += timedelta(seconds=GRACE + 1)
    return runner, stream


@pytest.mark.asyncio
async def test_a_real_runner_with_a_started_event_is_never_warned() -> None:
    """Proves "never for a started run" against the real status logic (a StartedEvent on the
    stream reads `running`), not against a fake that answers it."""
    runner, stream = await _real_runner("t")
    stream.tail["t"] = StartedEvent(
        id="s", source="/trace/t/node/root", subject="t", data=StartedData(url4="'hi'")
    )
    audience = _Audience({"t"})

    await _warner(runner, audience).sweep()

    assert audience.notices == []


@pytest.mark.asyncio
async def test_a_real_runner_with_an_empty_stream_is_warned() -> None:
    runner, _ = await _real_runner("t")
    audience = _Audience({"t"})

    await _warner(runner, audience).sweep()

    assert audience.warned == ["t"]
