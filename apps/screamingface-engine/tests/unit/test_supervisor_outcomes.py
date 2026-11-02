"""The worker publishes each run's Candidate outcome, only when the terminal frame behind it
landed (OME-1785, E5 P1 spec R3)."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from test_supervisor_terminal_root_source import _Launcher, _Msg, _Proc, _Publisher

from screamingface_engine import child_protocol
from screamingface_engine.adapters.memory import InMemoryCandidateOutcomeStream
from screamingface_engine.candidate_outcomes import CandidateOutcome
from screamingface_engine.worker.loop import Worker
from screamingface_engine.worker.warm_pool import SPAWN_FAILED, LaunchFailed
from url4.streaming.protocol import TerminatedData, TerminatedEvent, source_for

pytestmark = pytest.mark.asyncio


class _Settling(_Launcher):
    """A launcher whose child reports ``settled`` on its control pipe (or nothing)."""

    def __init__(self, proc: Any, settled: child_protocol.Settled | None) -> None:
        super().__init__(proc)
        self._settled = settled
        self.forgotten: list[Any] = []

    async def settlement(self, proc: Any) -> child_protocol.Settled | None:
        settled, self._settled = self._settled, None
        return settled

    def forget(self, proc: Any) -> None:
        self.forgotten.append(proc)


class _ConditionalPublisher(_Publisher):
    """`publish_next` as JetStream's: nothing after a terminal frame. ``lose_the_race`` lands
    another writer's terminal frame between this writer's tail read and its append."""

    def __init__(self, *, lose_the_race: bool = False) -> None:
        super().__init__()
        self._lose_the_race = lose_the_race

    async def publish_next(self, topic: str, event: Any) -> bool:
        if self._lose_the_race:
            self.published.append(_terminated(topic, "succeeded"))
        if self.published and isinstance(self.published[-1], TerminatedEvent):
            return False
        self.published.append(event)
        return True


class _Owner:
    async def request(self, subject: str, payload: bytes, *, timeout: float) -> Any:
        return SimpleNamespace(data=b"worker-elsewhere")


def _terminated(topic: str, status: Any) -> TerminatedEvent:
    return TerminatedEvent(
        id="other", source=source_for(topic), subject=topic, data=TerminatedData(status=status)
    )


def _worker(
    publisher: _Publisher,
    launcher: _Launcher,
    outcomes: InMemoryCandidateOutcomeStream,
    *,
    control: Any = None,
) -> Worker:
    worker = Worker(
        queue=SimpleNamespace(),  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        slots=1,
        drain_grace_s=0.1,
        io_capacity=4,
        memory_budget_bytes=1024**3,
        spawn=lambda *a, **k: None,  # type: ignore[arg-type,return-value]  # replaced below
        deadline_margin_s=0.05,
        kill_grace_s=0.05,
        control=control,
        outcomes=outcomes,
    )
    worker._supervisor._launcher = launcher  # noqa: SLF001 - the seam under test
    return worker


async def _published(outcomes: InMemoryCandidateOutcomeStream) -> list[tuple[str, Any]]:
    seen: list[tuple[str, Any]] = []
    deliveries = outcomes.consume()
    try:
        while True:
            delivery = await asyncio.wait_for(anext(deliveries), 0.1)
            seen.append((delivery.topic, delivery.outcome))
            await delivery.ack()
    except TimeoutError:
        return seen
    finally:
        await deliveries.aclose()


async def test_a_childs_settled_outcome_is_published_with_its_cost() -> None:
    outcomes = InMemoryCandidateOutcomeStream()
    settled = child_protocol.Settled("succeeded", None, Decimal("0.3"))
    launcher = _Settling(_Proc(code=0), settled)
    worker = _worker(_Publisher(), launcher, outcomes)

    await worker._supervisor.supervise(_Msg("t-ok"))  # type: ignore[arg-type]

    assert await _published(outcomes) == [
        ("t-ok", CandidateOutcome("succeeded", None, Decimal("0.3")))
    ]


async def test_a_child_killed_before_reporting_gets_the_workers_classification() -> None:
    outcomes = InMemoryCandidateOutcomeStream()
    publisher = _Publisher()
    worker = _worker(publisher, _Settling(_Proc(code=-9), None), outcomes)

    await worker._supervisor.supervise(_Msg("t-killed"))  # type: ignore[arg-type]

    [frame] = publisher.published
    [(topic, outcome)] = await _published(outcomes)
    assert topic == "t-killed"
    assert outcome == CandidateOutcome(frame.data.status, frame.data.error.code)


async def test_a_spawn_failure_publishes_failed() -> None:
    outcomes = InMemoryCandidateOutcomeStream()
    failure = LaunchFailed(SPAWN_FAILED, "the child never became ready")
    worker = _worker(_Publisher(), _Launcher(failure), outcomes)

    await worker._supervisor.supervise(_Msg("t-spawn"))  # type: ignore[arg-type]

    assert await _published(outcomes) == [("t-spawn", CandidateOutcome("failed", SPAWN_FAILED))]


async def test_an_expired_message_publishes_failed() -> None:
    outcomes = InMemoryCandidateOutcomeStream()
    worker = _worker(_Publisher(), _Launcher(_Proc(code=0)), outcomes)

    await worker._supervisor.supervise(_Msg("t-expired", deadline_s=1, queued_for_s=3600))  # type: ignore[arg-type]

    assert await _published(outcomes) == [
        ("t-expired", CandidateOutcome("failed", "queue_expired"))
    ]


async def test_a_claim_after_a_tombstone_publishes_nothing_more() -> None:
    """The App already published the tombstone's outcome; the worker's claim skips the run."""
    outcomes = InMemoryCandidateOutcomeStream()
    publisher = _Publisher()
    publisher.published.append(_terminated("t-cancelled", "stopped"))
    worker = _worker(publisher, _Launcher(_Proc(code=0)), outcomes)

    await worker._supervisor.supervise(_Msg("t-cancelled"))  # type: ignore[arg-type]

    assert await _published(outcomes) == []


async def test_a_duplicate_claim_publishes_nothing() -> None:
    outcomes = InMemoryCandidateOutcomeStream()
    worker = _worker(_Publisher(), _Launcher(_Proc(code=0)), outcomes, control=_Owner())

    await worker._supervisor.supervise(_Msg("t-dup", delivered=2))  # type: ignore[arg-type]

    assert await _published(outcomes) == []


async def test_a_worker_frame_that_lost_the_race_publishes_nothing() -> None:
    """INVARIANT (spec R3): a final success that landed first keeps its own outcome."""
    outcomes = InMemoryCandidateOutcomeStream()
    publisher = _ConditionalPublisher(lose_the_race=True)
    worker = _worker(publisher, _Settling(_Proc(code=-9), None), outcomes)

    await worker._supervisor.supervise(_Msg("t-raced"))  # type: ignore[arg-type]

    assert await _published(outcomes) == []


async def test_the_childs_control_reader_is_always_released() -> None:
    launcher = _Settling(_Proc(code=0), None)
    worker = _worker(_Publisher(), launcher, InMemoryCandidateOutcomeStream())

    await worker._supervisor.supervise(_Msg("t-released"))  # type: ignore[arg-type]

    assert len(launcher.forgotten) == 1
