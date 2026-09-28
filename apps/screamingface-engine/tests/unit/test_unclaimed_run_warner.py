"""The unclaimed-run warner's policy: one generic WARN for a queued run nobody has claimed.

FEATURE: warn the client about an unclaimed queued run (under OME-1086; the residual gap of
OME-1059 and OME-948).

Every test drives the runner's ages by hand and calls `sweep()` directly — no sleeps. The
lesson this suite guards (`14982d83`, PR #822): the queue-position notice fired on EVERY run of
a healthy stack and was removed as noise. This notice must fire only on a real wait.
"""

from datetime import UTC, datetime

import pytest

from screamingface_engine.adapters.jetstream import QueueReadError
from screamingface_engine.unclaimed import UNCLAIMED_MESSAGE, UnclaimedRunWarner
from url4.streaming.interfaces import JobStatus
from url4.streaming.protocol import LogEvent, OutboundFrame

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


def _warner(runner: _Runner, audience: _Audience) -> UnclaimedRunWarner:
    return UnclaimedRunWarner(runner, audience, grace_s=GRACE, frame_clock=lambda: T0)


@pytest.mark.asyncio
async def test_a_run_queued_past_the_grace_is_warned_once() -> None:
    runner, audience = _Runner(), _Audience({"t"})
    runner.ages["t"] = GRACE + 1
    warner = _warner(runner, audience)

    assert await warner.sweep() == ("t",)
    runner.ages["t"] = GRACE * 10
    assert await warner.sweep() == ()

    # INVARIANT: at most ONE notice per run, however long it keeps waiting.
    assert [topic for topic, _ in audience.notices] == ["t"]
    assert warner.warned_total == 1


@pytest.mark.asyncio
async def test_the_notice_is_a_generic_warn_log_frame_for_the_topic() -> None:
    runner, audience = _Runner(), _Audience({"t"})
    runner.ages["t"] = 301.7
    await _warner(runner, audience).sweep()

    [(topic, frame)] = audience.notices
    assert topic == "t"
    assert isinstance(frame, LogEvent)
    assert frame.subject == "t"
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

    assert await _warner(runner, audience).sweep() == ()
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

    assert await warner.sweep() == ()
    assert runner.status_reads == []

    audience.present.add("t")
    assert await warner.sweep() == ("t",)


@pytest.mark.asyncio
async def test_an_unreadable_tail_is_unknown_and_retried() -> None:
    runner, audience = _Runner(), _Audience({"t"})
    runner.ages["t"] = GRACE + 1
    runner.unreadable.add("t")
    warner = _warner(runner, audience)

    assert await warner.sweep() == ()
    assert audience.notices == []

    runner.unreadable.clear()
    assert await warner.sweep() == ("t",)


@pytest.mark.asyncio
async def test_one_unreadable_topic_does_not_hide_another() -> None:
    runner, audience = _Runner(), _Audience({"a", "b"})
    runner.ages.update({"a": GRACE + 1, "b": GRACE + 1})
    runner.unreadable.add("a")

    assert await _warner(runner, audience).sweep() == ("b",)


@pytest.mark.asyncio
async def test_decisions_are_forgotten_with_the_runner_record() -> None:
    """The decision set stays bounded by the runner's own record (capability expiry)."""
    runner, audience = _Runner(), _Audience({"t"})
    runner.ages["t"] = GRACE + 1
    warner = _warner(runner, audience)
    await warner.sweep()
    assert warner.decided_count == 1

    del runner.ages["t"]
    await warner.sweep()

    assert warner.decided_count == 0


@pytest.mark.parametrize(("grace", "tick"), [(300.0, 37.5), (4.0, 1.0), (0.5, 1.0)])
def test_the_tick_is_an_eighth_of_the_grace_with_a_one_second_floor(
    grace: float, tick: float
) -> None:
    warner = UnclaimedRunWarner(_Runner(), _Audience(), grace_s=grace)
    assert warner.tick_s == tick
