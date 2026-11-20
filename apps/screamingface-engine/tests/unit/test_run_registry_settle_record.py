"""E5 P2 spec §4.4: `settle` stores a Candidate's record with its state and cost.

FEATURE: a detached Run (OME-1837). STORY: as a researcher reattaching from another machine, I
find each Candidate's record beside its state, even when a second copy of its outcome is the one
that carries it.

Same databases as `test_run_registry_contract.py`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from run_registry_support import (
    DATABASES,
    Registry,
    open_registry,
    postgres_server,  # noqa: F401  (a fixture the Postgres parameter requests)
    start_spec,
)

from screamingface_engine.candidate_outcomes import CandidateOutcome
from screamingface_engine.runs.records import CandidateRecord, owner_key

pytestmark = pytest.mark.asyncio

ALICE = owner_key("alice@example.org")
TOPIC = "0" * 64
RECORD = {"trace_id": "a" * 32, "cache_hits": 2, "client_version": "1.4.0"}


@pytest_asyncio.fixture(params=DATABASES)
async def registry(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[Registry]:
    async for opened in open_registry(request, tmp_path):
        yield opened


async def _scheduled(registry: Registry) -> str:
    run, _ = await registry.store.register(ALICE, start_spec("a"))
    await registry.store.bind(ALICE, run.id, 0, TOPIC)
    await registry.store.mark_scheduled(TOPIC)
    return run.id


async def _candidate(registry: Registry, run_id: str) -> CandidateRecord:
    record = await registry.store.get(ALICE, run_id)
    assert record is not None
    return record.candidates[0]


async def test_settle_writes_the_state_cost_and_record_together(registry: Registry) -> None:
    run_id = await _scheduled(registry)

    await registry.store.settle(
        TOPIC, CandidateOutcome("succeeded", None, Decimal("0.5"), record=RECORD)
    )

    candidate = await _candidate(registry, run_id)
    assert (candidate.state, candidate.cost_usd, candidate.record) == (
        "succeeded",
        Decimal("0.5"),
        RECORD,
    )


async def test_a_second_settle_for_the_topic_writes_nothing(registry: Registry) -> None:
    run_id = await _scheduled(registry)
    await registry.store.settle(
        TOPIC, CandidateOutcome("succeeded", None, Decimal("0.5"), record=RECORD)
    )

    other = {"trace_id": "b" * 32}
    await registry.store.settle(
        TOPIC, CandidateOutcome("succeeded", None, Decimal("9"), record=other)
    )

    candidate = await _candidate(registry, run_id)
    assert (candidate.cost_usd, candidate.record) == (Decimal("0.5"), RECORD)


async def test_a_later_outcome_with_the_same_state_fills_an_empty_cost_and_record(
    registry: Registry,
) -> None:
    """INVARIANT (§4.4): an outcome rebuilt from the stream (R7) settles first with neither, and
    the runner's own outcome, landing later, completes it."""
    run_id = await _scheduled(registry)
    await registry.store.settle(TOPIC, CandidateOutcome("succeeded"))
    assert (await _candidate(registry, run_id)).record is None

    await registry.store.settle(
        TOPIC, CandidateOutcome("succeeded", None, Decimal("0.5"), record=RECORD)
    )

    candidate = await _candidate(registry, run_id)
    assert (candidate.state, candidate.cost_usd, candidate.record) == (
        "succeeded",
        Decimal("0.5"),
        RECORD,
    )


async def test_a_later_outcome_fills_only_what_is_empty(registry: Registry) -> None:
    run_id = await _scheduled(registry)
    await registry.store.settle(TOPIC, CandidateOutcome("succeeded", None, Decimal("0.5")))

    await registry.store.settle(
        TOPIC, CandidateOutcome("succeeded", None, Decimal("9"), record=RECORD)
    )

    candidate = await _candidate(registry, run_id)
    assert (candidate.cost_usd, candidate.record) == (Decimal("0.5"), RECORD)


async def test_a_later_outcome_with_another_state_changes_nothing(registry: Registry) -> None:
    """State and error code are first-wins (P1 spec R3)."""
    run_id = await _scheduled(registry)
    await registry.store.settle(TOPIC, CandidateOutcome("stopped"))

    await registry.store.settle(
        TOPIC, CandidateOutcome("failed", "provider_error", Decimal("0.5"), record=RECORD)
    )

    candidate = await _candidate(registry, run_id)
    assert (candidate.state, candidate.error_code) == ("stopped", None)
    assert (candidate.cost_usd, candidate.record) == (None, None)


async def test_an_outcome_without_a_record_settles_with_none(registry: Registry) -> None:
    run_id = await _scheduled(registry)

    await registry.store.settle(TOPIC, CandidateOutcome("failed", "provider_error"))

    candidate = await _candidate(registry, run_id)
    assert (candidate.state, candidate.cost_usd, candidate.record) == ("failed", None, None)


async def test_only_get_reads_the_record(registry: Registry) -> None:
    """§4.4: the summary a 1 s poll reads carries no record."""
    run_id = await _scheduled(registry)
    await registry.store.settle(TOPIC, CandidateOutcome("succeeded", record=RECORD))

    summary = await registry.store.summary(ALICE, run_id)

    assert summary is not None
    assert summary.candidates[0].record is None


async def test_a_record_with_text_one_database_refuses_still_settles(registry: Registry) -> None:
    """A run's error text is the provider's, and may hold a NUL or a lone surrogate. INVARIANT:
    the outcome is written on either database, so it never blocks the outcomes behind it."""
    run_id = await _scheduled(registry)
    record = {"error": {"code": "boom", "message": "a\x00b\ud800", "details": {"n": float("inf")}}}

    await registry.store.settle(TOPIC, CandidateOutcome("failed", "boom", record=record))

    candidate = await _candidate(registry, run_id)
    assert candidate.state == "failed"
    assert candidate.record == {
        "error": {"code": "boom", "message": "a�b�", "details": {"n": None}}
    }
