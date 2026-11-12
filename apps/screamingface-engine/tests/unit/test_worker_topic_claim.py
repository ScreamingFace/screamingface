"""E5 P2 spec D7 and R3: a worker claims a driver-started run's topic before it runs it.

FEATURE: a detached Run (OME-1837). STORY: as a researcher, a Candidate the Engine started twice
runs once, so I never pay for it twice.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from screamingface_engine.adapters.memory import InMemoryTopicClaims
from screamingface_engine.subjects import claim_subject_for
from screamingface_engine.topic_claims import Claim, TopicClaimsUnavailable
from screamingface_engine.worker.topic_claim import ClaimGate, FinishingMessage

pytestmark = pytest.mark.asyncio

TOPIC = "url4-cloud.5f1c2a"


class _Fleet:
    """The `url4.runclaim.*` subject: each worker answers for the topics it claimed."""

    def __init__(self) -> None:
        self.claimed: dict[str, set[str]] = {}
        self.asked: list[tuple[str, bytes]] = []

    async def request(self, subject: str, payload: bytes, *, timeout: float) -> Any:
        self.asked.append((subject, payload))
        holder = payload.decode()
        topic = subject.removeprefix("url4.runclaim.")
        if topic in self.claimed.get(holder, set()):
            return SimpleNamespace(data=payload)
        raise TimeoutError


class _Tail:
    def __init__(self, ended: bool = False) -> None:
        self.ended = ended
        self.reads = 0

    async def __call__(self, topic: str) -> bool:
        self.reads += 1
        return self.ended


def _gate(
    worker: str,
    claims: Any,
    fleet: _Fleet,
    tail: _Tail | None = None,
    *,
    budget_s: float = 5.0,
) -> ClaimGate:
    claimed = fleet.claimed.setdefault(worker, set())
    return ClaimGate(
        claims=claims,
        worker_id=worker,
        ask=fleet,
        ended=tail or _Tail(),
        claimed=claimed,
        budget_s=budget_s,
    )


async def test_a_new_claim_runs_and_is_answered_for() -> None:
    fleet = _Fleet()
    gate = _gate("w1", InMemoryTopicClaims(), fleet)

    assert await gate.admit(TOPIC)
    assert TOPIC in fleet.claimed["w1"]


async def test_of_two_copies_taken_together_exactly_one_runs() -> None:
    claims, fleet = InMemoryTopicClaims(), _Fleet()

    admitted = await asyncio.gather(
        _gate("w1", claims, fleet).admit(TOPIC), _gate("w2", claims, fleet).admit(TOPIC)
    )

    assert sorted(admitted) == [False, True]


async def test_a_copy_taken_later_while_the_holder_runs_is_acked_away() -> None:
    claims, fleet = InMemoryTopicClaims(), _Fleet()
    assert await _gate("w1", claims, fleet).admit(TOPIC)

    assert not await _gate("w2", claims, fleet).admit(TOPIC)
    assert fleet.asked == [(claim_subject_for(TOPIC), b"w1")]


async def test_a_dead_holders_claim_is_taken_over_by_exactly_one_contender() -> None:
    claims, fleet = InMemoryTopicClaims(), _Fleet()
    await claims.claim(TOPIC, "dead")

    admitted = await asyncio.gather(
        _gate("w1", claims, fleet).admit(TOPIC), _gate("w2", claims, fleet).admit(TOPIC)
    )

    assert sorted(admitted) == [False, True]
    winner = "w1" if admitted[0] else "w2"
    assert (await claims.claim(TOPIC, "probe")).holder == winner


async def test_a_contender_never_answers_for_a_topic_it_does_not_hold() -> None:
    claims, fleet = InMemoryTopicClaims(), _Fleet()
    assert await _gate("w1", claims, fleet).admit(TOPIC)
    assert not await _gate("w2", claims, fleet).admit(TOPIC)

    assert TOPIC not in fleet.claimed["w2"]


async def test_a_copy_arriving_as_the_holder_finishes_is_acked_away_by_the_mark() -> None:
    claims, fleet = InMemoryTopicClaims(), _Fleet()
    holder = _gate("w1", claims, fleet)
    assert await holder.admit(TOPIC)
    await holder.finish(TOPIC)

    assert not await _gate("w2", claims, fleet).admit(TOPIC)
    assert TOPIC not in fleet.claimed["w1"]


async def test_a_copy_arriving_after_the_end_is_acked_away_by_the_second_tail_read() -> None:
    """The holder published its terminal frame but had not yet marked its claim finished."""
    claims, fleet = InMemoryTopicClaims(), _Fleet()
    await claims.claim(TOPIC, "gone")
    tail = _Tail(ended=True)

    assert not await _gate("w2", claims, fleet, tail).admit(TOPIC)
    assert tail.reads == 1
    assert (await claims.claim(TOPIC, "probe")).holder == "gone"


async def test_a_claim_naming_this_worker_with_nothing_in_flight_runs() -> None:
    """A worker that restarted under the same id: its old process holds nothing."""
    claims, fleet = InMemoryTopicClaims(), _Fleet()
    await claims.claim(TOPIC, "w1")

    assert await _gate("w1", claims, fleet).admit(TOPIC)


class _Unavailable:
    async def claim(self, topic: str, worker_id: str) -> Claim:
        raise TopicClaimsUnavailable("the bucket is gone")

    async def finish(self, topic: str, worker_id: str) -> None:
        raise TopicClaimsUnavailable("the bucket is gone")


class _Slow(InMemoryTopicClaims):
    async def claim(self, topic: str, worker_id: str) -> Claim:
        await asyncio.sleep(10)
        return await super().claim(topic, worker_id)


async def test_an_unreachable_bucket_runs_the_copy() -> None:
    """R3: a worker that cannot tell runs, as it does today."""
    assert await _gate("w1", _Unavailable(), _Fleet()).admit(TOPIC)


async def test_a_spent_budget_runs_the_copy() -> None:
    assert await _gate("w1", _Slow(), _Fleet(), budget_s=0.05).admit(TOPIC)


async def test_the_ack_of_a_won_claim_marks_it_finished_first() -> None:
    """R3: the claim is marked finished after the terminal frame and before the ack."""
    claims, fleet = InMemoryTopicClaims(), _Fleet()
    gate = _gate("w1", claims, fleet)
    order: list[str] = []

    class _Msg:
        data = b"{}"
        metadata = None

        async def ack(self) -> None:
            order.append("ack:" + str((await claims.claim(TOPIC, "probe")).finished))

        async def in_progress(self) -> None:
            order.append("in_progress")

    assert await gate.admit(TOPIC)
    message = FinishingMessage(_Msg(), gate, TOPIC)
    await message.in_progress()
    await message.ack()

    assert order == ["in_progress", "ack:True"]


async def test_finishing_a_claim_this_worker_never_won_writes_nothing() -> None:
    claims, fleet = InMemoryTopicClaims(), _Fleet()
    await claims.claim(TOPIC, "w2")

    await _gate("w1", claims, fleet).finish(TOPIC)

    assert not (await claims.claim(TOPIC, "probe")).finished


async def test_a_failing_finish_never_blocks_the_ack() -> None:
    gate = _gate("w1", _Unavailable(), _Fleet())
    gate._claimed.add(TOPIC)  # noqa: SLF001 - a claim won before the bucket went away

    await gate.finish(TOPIC)

    assert TOPIC not in gate._claimed  # noqa: SLF001
