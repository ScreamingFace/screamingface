"""E5 P1 spec §6, the registry contract: create, get, list, bind and settle.

FEATURE: first-class Runs (OME-1785). One suite, on SQLite in every run and on Postgres where
`URL4_CLOUD_TEST_PG=1` (the CI Postgres step). Cancel, state, reconcile and expire are in
`test_run_registry_lifecycle.py`.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from run_registry_support import (
    DATABASES,
    GRACE,
    T0,
    Registry,
    open_registry,
    postgres_server,  # noqa: F401  (a fixture the Postgres parameter requests)
    spec,
)

from screamingface_engine.candidate_outcomes import CandidateOutcome, OutcomeStatus
from screamingface_engine.runs import store as store_module
from screamingface_engine.runs.ids import RUN_ID_PATTERN
from screamingface_engine.runs.records import RunQuery, owner_key
from screamingface_engine.runs.registry import (
    CandidateAlreadyStarted,
    RunCanceled,
    RunNotFound,
    UnknownCandidate,
)

pytestmark = pytest.mark.asyncio

ALICE = owner_key("alice@example.org")
BOB = owner_key("bob@example.org")
TOPIC = "t" * 64
OTHER_TOPIC = "u" * 64


@pytest_asyncio.fixture(params=DATABASES)
async def registry(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[Registry]:
    async for opened in open_registry(request, tmp_path):
        yield opened


# --- create and get ----------------------------------------------------------------------


async def test_create_registers_a_running_run_of_pending_candidates(registry: Registry) -> None:
    record = await registry.store.create(ALICE, spec("alpha", "beta"))

    assert RUN_ID_PATTERN.fullmatch(record.id)
    assert (record.state, record.created_at, record.finished_at) == ("running", T0, None)
    assert (record.benchmark, record.case_count) == ("gsm8k", 10)
    assert [(c.index, c.name, c.state, c.attempt_id) for c in record.candidates] == [
        (0, "alpha", "pending", None),
        (1, "beta", "pending", None),
    ]
    assert await registry.store.get(ALICE, record.id) == record


async def test_a_repeated_client_key_returns_the_existing_run(registry: Registry) -> None:
    """Spec §4.1: a retry after a lost `POST /runs` response returns the same Run."""
    first = await registry.store.create(ALICE, spec("alpha"))
    registry.clock.advance(seconds=5)

    again = await registry.store.create(ALICE, spec("other", "names"))

    assert again == first


async def test_the_same_client_key_from_another_owner_is_another_run(registry: Registry) -> None:
    mine = await registry.store.create(ALICE, spec())
    theirs = await registry.store.create(BOB, spec())

    assert mine.id != theirs.id


async def test_concurrent_creates_of_one_client_key_make_one_run(registry: Registry) -> None:
    records = await asyncio.gather(*(registry.store.create(ALICE, spec()) for _ in range(5)))

    assert len({record.id for record in records}) == 1


async def test_another_owners_run_is_not_found(registry: Registry) -> None:
    record = await registry.store.create(ALICE, spec())

    assert await registry.store.get(BOB, record.id) is None
    assert await registry.store.get(ALICE, "run_" + "0" * 32) is None


async def test_owners_differing_only_in_case_or_space_are_one_owner(registry: Registry) -> None:
    record = await registry.store.create(owner_key("Alice@Example.org "), spec())

    assert await registry.store.get(ALICE, record.id) == record


# --- list --------------------------------------------------------------------------------


async def _create_runs(registry: Registry, count: int, *, step_s: float = 1) -> list[str]:
    ids = []
    for index in range(count):
        ids.append((await registry.store.create(ALICE, spec(client_key=f"k{index}"))).id)
        registry.clock.advance(seconds=step_s)
    return ids


async def test_runs_list_newest_first_in_pages(registry: Registry) -> None:
    ids = await _create_runs(registry, 5)

    first = await registry.store.list(ALICE, RunQuery(limit=2))
    second = await registry.store.list(ALICE, RunQuery(limit=2, cursor=first.next_cursor))
    last = await registry.store.list(ALICE, RunQuery(limit=2, cursor=second.next_cursor))

    pages = [first, second, last]
    assert [[run.id for run in page.runs] for page in pages] == [
        ids[4:2:-1],
        ids[2:0:-1],
        ids[:1],
    ]
    assert last.next_cursor is None


async def test_runs_created_in_the_same_instant_list_by_id(registry: Registry) -> None:
    ids = await _create_runs(registry, 4, step_s=0)

    page = await registry.store.list(ALICE, RunQuery(limit=2))
    rest = await registry.store.list(ALICE, RunQuery(limit=10, cursor=page.next_cursor))

    assert [run.id for run in (*page.runs, *rest.runs)] == sorted(ids, reverse=True)


async def test_list_shows_only_the_owners_runs_since_the_given_time(registry: Registry) -> None:
    ids = await _create_runs(registry, 3, step_s=60)
    await registry.store.create(BOB, spec(client_key="theirs"))

    page = await registry.store.list(ALICE, RunQuery(since=T0.replace(minute=1)))

    assert [run.id for run in page.runs] == [ids[2], ids[1]]


async def test_a_state_filter_still_fills_each_page(registry: Registry) -> None:
    """Spec R5: the App derives and filters, so a page is never short while matches remain."""
    ids = await _create_runs(registry, 6)
    for run_id in ids[::2]:
        await _finish(registry, run_id, "succeeded")

    first = await registry.store.list(ALICE, RunQuery(state="complete", limit=2))
    second = await registry.store.list(
        ALICE, RunQuery(state="complete", limit=2, cursor=first.next_cursor)
    )

    assert [run.id for run in first.runs] == [ids[4], ids[2]]
    assert [run.id for run in second.runs] == [ids[0]]
    assert second.next_cursor is None


async def test_a_state_filter_scans_past_many_batches(
    registry: Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store_module, "_SCAN_BATCH", 2)
    ids = await _create_runs(registry, 7)
    await _finish(registry, ids[0], "succeeded")

    page = await registry.store.list(ALICE, RunQuery(state="complete", limit=1))

    assert ([run.id for run in page.runs], page.next_cursor) == ([ids[0]], None)


async def test_an_unknown_cursor_gives_an_empty_page(registry: Registry) -> None:
    await _create_runs(registry, 2)

    page = await registry.store.list(ALICE, RunQuery(cursor="run_" + "f" * 32))

    assert (page.runs, page.next_cursor) == ((), None)


async def _finish(registry: Registry, run_id: str, status: OutcomeStatus) -> None:
    record = await registry.store.get(ALICE, run_id)
    assert record is not None
    for candidate in record.candidates:
        topic = f"{run_id}-{candidate.index}".ljust(64, "x")
        await registry.store.bind(ALICE, run_id, candidate.index, topic)
        await registry.store.settle(topic, CandidateOutcome(status))


# --- bind --------------------------------------------------------------------------------


async def test_a_bind_leaves_the_candidate_pending_until_it_is_scheduled(
    registry: Registry,
) -> None:
    run = await registry.store.create(ALICE, spec("alpha"))
    registry.clock.advance(seconds=3)

    await registry.store.bind(ALICE, run.id, 0, TOPIC)
    bound = await registry.store.get(ALICE, run.id)
    await registry.store.mark_scheduled(TOPIC)
    scheduled = await registry.store.get(ALICE, run.id)

    assert bound is not None and scheduled is not None
    assert bound.candidates[0].state == "pending"
    assert (bound.candidates[0].attempt_id, bound.candidates[0].started_at) == (
        TOPIC,
        T0.replace(second=3),
    )
    assert scheduled.candidates[0].state == "scheduled"


async def test_binding_the_same_triple_again_changes_nothing(registry: Registry) -> None:
    """Spec R2: the Client re-sends a start after a 503, and that start must still schedule."""
    run = await registry.store.create(ALICE, spec("alpha"))
    await registry.store.bind(ALICE, run.id, 0, TOPIC)
    before = await registry.store.get(ALICE, run.id)
    registry.clock.advance(seconds=10)

    await registry.store.bind(ALICE, run.id, 0, TOPIC)

    after = await registry.store.get(ALICE, run.id)
    assert after is not None and before is not None
    assert after.candidates == before.candidates


async def test_a_second_topic_for_a_bound_candidate_is_refused(registry: Registry) -> None:
    run = await registry.store.create(ALICE, spec("alpha"))
    await registry.store.bind(ALICE, run.id, 0, TOPIC)

    with pytest.raises(CandidateAlreadyStarted):
        await registry.store.bind(ALICE, run.id, 0, OTHER_TOPIC)


async def test_a_topic_bound_elsewhere_is_refused(registry: Registry) -> None:
    run = await registry.store.create(ALICE, spec("alpha", "beta"))
    other = await registry.store.create(ALICE, spec("gamma", client_key="key-2"))
    await registry.store.bind(ALICE, run.id, 0, TOPIC)

    with pytest.raises(CandidateAlreadyStarted):
        await registry.store.bind(ALICE, run.id, 1, TOPIC)
    with pytest.raises(CandidateAlreadyStarted):
        await registry.store.bind(ALICE, other.id, 0, TOPIC)


async def test_a_bind_to_an_unknown_or_foreign_run_is_not_found(registry: Registry) -> None:
    run = await registry.store.create(ALICE, spec("alpha"))

    with pytest.raises(RunNotFound):
        await registry.store.bind(BOB, run.id, 0, TOPIC)
    with pytest.raises(RunNotFound):
        await registry.store.bind(ALICE, "run_" + "0" * 32, 0, TOPIC)


@pytest.mark.parametrize("index", [-1, 1, 99])
async def test_a_bind_to_an_unknown_candidate_is_refused(registry: Registry, index: int) -> None:
    run = await registry.store.create(ALICE, spec("alpha"))

    with pytest.raises(UnknownCandidate):
        await registry.store.bind(ALICE, run.id, index, TOPIC)


async def test_a_bind_under_a_canceled_run_is_refused(registry: Registry) -> None:
    run = await registry.store.create(ALICE, spec("alpha", "beta"))
    await registry.store.bind(ALICE, run.id, 0, TOPIC)
    await registry.store.mark_scheduled(TOPIC)
    await registry.store.cancel(ALICE, run.id)

    with pytest.raises(RunCanceled):
        await registry.store.bind(ALICE, run.id, 1, OTHER_TOPIC)


async def test_scheduling_an_unbound_topic_is_a_no_op(registry: Registry) -> None:
    await registry.store.mark_scheduled(TOPIC)


# --- settle ------------------------------------------------------------------------------


async def _bound_run(registry: Registry, *names: str) -> str:
    run = await registry.store.create(ALICE, spec(*names))
    await registry.store.bind(ALICE, run.id, 0, TOPIC)
    await registry.store.mark_scheduled(TOPIC)
    return run.id


async def test_settle_records_the_outcome(registry: Registry) -> None:
    run_id = await _bound_run(registry, "alpha")
    registry.clock.advance(minutes=2)

    await registry.store.settle(
        TOPIC, CandidateOutcome("failed", "provider_error", Decimal("0.0042"))
    )

    record = await registry.store.get(ALICE, run_id)
    assert record is not None
    candidate = record.candidates[0]
    assert (candidate.state, candidate.error_code, candidate.cost_usd) == (
        "failed",
        "provider_error",
        Decimal("0.0042"),
    )
    assert candidate.finished_at == record.finished_at == T0.replace(minute=2)
    assert record.state == "errored"


async def test_the_first_terminal_outcome_wins(registry: Registry) -> None:
    """INVARIANT (spec R4): a redelivery or a duplicate claim cannot contradict the first."""
    run_id = await _bound_run(registry, "alpha")
    await registry.store.settle(TOPIC, CandidateOutcome("succeeded", None, Decimal("1")))
    registry.clock.advance(minutes=1)

    await registry.store.settle(TOPIC, CandidateOutcome("succeeded", None, Decimal("1")))
    await registry.store.settle(TOPIC, CandidateOutcome("failed", "late"))

    record = await registry.store.get(ALICE, run_id)
    assert record is not None
    assert (record.state, record.candidates[0].cost_usd, record.finished_at) == (
        "complete",
        Decimal("1"),
        T0,
    )


async def test_concurrent_settles_leave_exactly_one_winner(registry: Registry) -> None:
    run_id = await _bound_run(registry, "alpha")
    outcomes = [CandidateOutcome("failed", f"code-{n}") for n in range(8)]

    await asyncio.gather(*(registry.store.settle(TOPIC, outcome) for outcome in outcomes))

    record = await registry.store.get(ALICE, run_id)
    assert record is not None
    assert record.candidates[0].state == "failed"
    assert record.candidates[0].error_code in {outcome.error_code for outcome in outcomes}


async def test_an_outcome_for_an_unbound_topic_is_a_no_op(registry: Registry) -> None:
    await registry.store.settle(TOPIC, CandidateOutcome("succeeded"))


async def test_an_outcome_before_scheduling_still_settles(registry: Registry) -> None:
    """WHY: a fast run can end before its start route marks it scheduled."""
    run = await registry.store.create(ALICE, spec("alpha"))
    await registry.store.bind(ALICE, run.id, 0, TOPIC)

    await registry.store.settle(TOPIC, CandidateOutcome("succeeded"))
    await registry.store.mark_scheduled(TOPIC)

    record = await registry.store.get(ALICE, run.id)
    assert record is not None and record.candidates[0].state == "succeeded"


async def test_every_write_moves_last_activity_forward_only(registry: Registry) -> None:
    """A bind or settle at an older clock never pulls the grace window back (spec R5)."""
    run = await registry.store.create(ALICE, spec("alpha", "beta"))
    registry.clock.advance(seconds=GRACE.total_seconds() - 10)
    await registry.store.bind(ALICE, run.id, 0, TOPIC)
    registry.clock.now = T0
    await registry.store.bind(ALICE, run.id, 1, OTHER_TOPIC)
    registry.clock.now = T0 + GRACE + GRACE / 2

    record = await registry.store.get(ALICE, run.id)

    assert record is not None and record.state == "running"
