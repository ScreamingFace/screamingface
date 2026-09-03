"""The queue runner's status derivation (OME-1090): a pure function of the run's own
event stream plus capability validity — no Job, no new store.

| Evidence on the run's event stream | Status |
| terminal frame present | its outcome (succeeded/failed/timed_out/stopped) |
| StartedEvent, no terminal frame | running |
| neither, capability unexpired | scheduled |
| neither, capability expired | not_found |

The table is the whole contract, so it is pinned one test per row, including the exact
capability-expiry boundary between `scheduled` and `not_found`.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from screamingface_engine.adapters.queue_runner import QueueJobRunner
from url4.streaming.protocol import (
    LogData,
    LogEvent,
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
    """A wall clock the test advances by hand."""

    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class _FakeQueue:
    def __init__(self) -> None:
        self.published: list[bytes] = []

    async def publish(self, message: bytes) -> None:
        self.published.append(message)

    async def depth(self) -> int:
        return 0


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


def _runner(clock: _FakeClock, publisher: _FakePublisher) -> QueueJobRunner:
    return QueueJobRunner(
        queue=_FakeQueue(),
        publisher=publisher,
        control=_FakeControl(),
        clock=clock,
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


def _log(topic: str) -> LogEvent:
    return LogEvent(
        id="l", source=source_for(topic), subject=topic, data=LogData.at("INFO", "working")
    )


# --- row 1: a terminal frame IS the run's outcome ------------------------------------------


async def test_a_terminal_frame_maps_to_its_outcome() -> None:
    """Row 1: whatever terminal frame the stream ends in is the run's status."""
    clock = _FakeClock()
    for status in ("succeeded", "failed", "timed_out", "stopped"):
        runner = _runner(clock, _FakePublisher(last_frame=_terminated("t", status)))
        assert await runner.status("t") == status


# --- row 2: started, not terminal → running -------------------------------------------------


async def test_a_started_event_without_a_terminal_frame_is_running() -> None:
    """Row 2: the run started; it is running."""
    clock = _FakeClock()
    runner = _runner(clock, _FakePublisher(last_frame=_started("t")))
    assert await runner.status("t") == "running"


async def test_any_non_terminal_frame_means_running() -> None:
    """A log/span/cost frame after StartedEvent is the same running evidence — the run
    started, whatever it is doing now."""
    clock = _FakeClock()
    runner = _runner(clock, _FakePublisher(last_frame=_log("t")))
    assert await runner.status("t") == "running"


# --- rows 3 & 4: no evidence → capability decides ------------------------------------------


async def test_no_evidence_with_an_unexpired_capability_is_scheduled() -> None:
    """Row 3: accepted but not yet started — queued. `scheduled` already means exactly
    that, so `JobStatus` needs no new member."""
    clock = _FakeClock()
    runner = _runner(clock, _FakePublisher(last_frame=None))
    await runner.schedule("t", "'hi'", 60)
    assert await runner.status("t") == "scheduled"


async def test_no_evidence_with_an_expired_capability_is_not_found() -> None:
    """Row 4: the capability expired while the run sat unstarted — it is gone."""
    clock = _FakeClock()
    runner = _runner(clock, _FakePublisher(last_frame=None))
    await runner.schedule("t", "'hi'", 60)
    clock.advance(CAPABILITY_LIFETIME_S)
    assert await runner.status("t") == "not_found"


async def test_the_capability_boundary_is_exact() -> None:
    """The boundary between `scheduled` and `not_found`: unexpired at lifetime-ε, expired
    at lifetime."""
    clock = _FakeClock()
    runner = _runner(clock, _FakePublisher(last_frame=None))
    await runner.schedule("t", "'hi'", 60)
    clock.advance(CAPABILITY_LIFETIME_S - 0.001)
    assert await runner.status("t") == "scheduled"
    clock.advance(0.001)
    assert await runner.status("t") == "not_found"


async def test_a_topic_never_scheduled_here_is_not_found() -> None:
    """A topic this replica never scheduled has no capability to speak of — the
    conservative answer for the reaper, which must not stop a run it cannot see."""
    clock = _FakeClock()
    runner = _runner(clock, _FakePublisher(last_frame=None))
    assert await runner.status("unknown") == "not_found"


# --- exists(): the reaper's question -------------------------------------------------------


async def test_exists_is_true_only_for_scheduled_or_running() -> None:
    """`exists` answers the reaper's question: a terminal run does not exist, so an
    audience-loss stop never lands a second terminal frame on a finished run."""
    clock = _FakeClock()
    runner = _runner(clock, _FakePublisher(last_frame=None))
    await runner.schedule("t", "'hi'", 60)
    assert await runner.exists("t") is True
    clock.advance(CAPABILITY_LIFETIME_S)
    assert await runner.exists("t") is False

    terminal = _runner(clock, _FakePublisher(last_frame=_terminated("t", "succeeded")))
    assert await terminal.exists("t") is False


async def test_an_unreadable_tail_is_an_error_not_a_state() -> None:
    """P2-10 then V-2/V-3: `status()`'s tail read was unguarded (a 500), and the first fix
    answered "running" — assumed alive. But `exists()` is this same status, and `POST /`
    used it to 409 a BRAND-NEW topic on a transient blip: a definitive false claim
    clients do not retry. Unknown is not a state for ANY consumer — the typed raise lets
    each caller answer honestly (the REST edge 503s; the reaper re-arms)."""
    from screamingface_engine.adapters.jetstream import QueueReadError

    class _UnreadablePublisher(_FakePublisher):
        async def last_frame(self, topic: str) -> Any:
            raise QueueReadError("stream tail unreadable")

    runner = _runner(_FakeClock(), _UnreadablePublisher())

    with pytest.raises(QueueReadError):
        await runner.status("t-unreadable")
    with pytest.raises(QueueReadError):
        await runner.exists("t-unreadable")
