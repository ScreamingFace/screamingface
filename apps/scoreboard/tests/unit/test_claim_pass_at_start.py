"""The claim pass and its start task (OME-1947; prd/score-claim.md K-30, K-31, K-33)."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest
from tortoise import Tortoise
from tortoise.exceptions import OperationalError

from scoreboard.core.copy_claims import (
    ClaimPassTask,
    ClaimResult,
    GatewayUnavailable,
    ScoreClaim,
    count_results,
    not_kept,
    run_claim_pass,
)
from scoreboard.db import close_db, init_db
from scoreboard.scores.models import Benchmark
from scoreboard.scores.schemas import ScoreSubmission
from scoreboard.scores.store import ScoreStore
from tests.unit.test_submit_claims_copy import ALICE, UNCAPTURED, _payload

PASS_LOGGER = "scoreboard.core.copy_claims"
COPY_A = "0192a1b2-c3d4-4e5f-8a9b-0c1d2e3f4a01"
COPY_B = "0192a1b2-c3d4-4e5f-8a9b-0c1d2e3f4a02"
COPY_C = "0192a1b2-c3d4-4e5f-8a9b-0c1d2e3f4a03"
ROWS = [("score-1", COPY_A), ("score-2", COPY_B), ("score-3", COPY_C)]


class MemoryClaims:
    """A fake gateway: the first claim of a copy is CLAIMED, and each later claim is ALREADY.

    A result in `scripted` comes before that rule, one time for each entry.
    """

    def __init__(self, scripted: dict[str, list[ClaimResult]] | None = None) -> None:
        self.calls: list[str] = []
        self.closed = False
        self._scripted = {copy_id: list(results) for copy_id, results in (scripted or {}).items()}
        self._claimed: set[str] = set()

    async def claim(self, copy_id: str) -> ClaimResult:
        self.calls.append(copy_id)
        scripted = self._scripted.get(copy_id)
        if scripted:
            return scripted.pop(0)
        result = ClaimResult.ALREADY if copy_id in self._claimed else ClaimResult.CLAIMED
        self._claimed.add(copy_id)
        return result

    async def aclose(self) -> None:
        self.closed = True


class RecordedSleep:
    """Records each delay. With `block`, it waits until the task is cancelled."""

    def __init__(self, *, block: bool = False) -> None:
        self.delays: list[float] = []
        self.entered = asyncio.Event()
        self._block = block

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)
        self.entered.set()
        if self._block:
            await asyncio.Event().wait()


class FlakyRows:
    """Gives ROWS, after `failures` reads that raise a database error."""

    def __init__(self, failures: int = 0) -> None:
        self.reads = 0
        self._failures = failures

    async def __call__(self) -> list[tuple[str, str]]:
        self.reads += 1
        if self.reads <= self._failures:
            raise OperationalError("no such table: score")
        return list(ROWS)


async def seed_scores() -> list[tuple[str, str]]:
    """Two Scores on a public board and one on a private board name a copy; one Score names none.

    Gives the (score id, copy id) rows sorted by score id. It needs an open database.
    """
    await Benchmark.create(id="hle", display_name="Humanity's Last Exam")
    await Benchmark.create(id="secret", display_name="Private board")
    store = ScoreStore()
    rows: list[tuple[str, str]] = []
    for board, spec, copy_id in (
        ("hle", "spec-a", COPY_A),
        ("hle", "spec-b", COPY_B),
        ("secret", "spec-c", COPY_C),
    ):
        payload = _payload(
            benchmark_id=board,
            spec_id=spec,
            url4_expression=f"url4://benchmark/{spec}",
            frozen_copy_id=copy_id,
        )
        outcome = await store.submit(
            ScoreSubmission.model_validate({**payload, "submitted_by": ALICE})
        )
        rows.append((str(outcome.score.id), copy_id))
    plain = _payload(
        spec_id="spec-none", url4_expression="url4://benchmark/spec-none", **UNCAPTURED
    )
    await store.submit(ScoreSubmission.model_validate({**plain, "submitted_by": ALICE}))
    # WHY after the submits: the pass reads the Scores of a private board too.
    await Benchmark.filter(id="secret").update(visibility="private")
    return sorted(rows)


def seed_database_file(path: Path) -> tuple[str, list[tuple[str, str]]]:
    """A SQLite file with the Scores of `seed_scores`. Gives its URL and the rows."""
    url = f"sqlite://{path}"

    async def _seed() -> list[tuple[str, str]]:
        await init_db(url)
        try:
            await Tortoise.generate_schemas(safe=True)
            return await seed_scores()
        finally:
            await close_db()

    return url, asyncio.run(_seed())


def _records(caplog: pytest.LogCaptureFixture, level: int) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == PASS_LOGGER and r.levelno == level]


@pytest.mark.asyncio
async def test_run_claim_pass_sends_one_claim_for_each_row_in_order() -> None:
    claims = MemoryClaims()

    results = await run_claim_pass(claims, ROWS)

    assert results == [
        ScoreClaim("score-1", COPY_A, ClaimResult.CLAIMED),
        ScoreClaim("score-2", COPY_B, ClaimResult.CLAIMED),
        ScoreClaim("score-3", COPY_C, ClaimResult.CLAIMED),
    ]
    assert claims.calls == [COPY_A, COPY_B, COPY_C]


@pytest.mark.asyncio
async def test_run_claim_pass_stops_at_the_first_unavailable_result() -> None:
    claims = MemoryClaims({COPY_B: [ClaimResult.UNAVAILABLE]})

    with pytest.raises(GatewayUnavailable) as stopped:
        await run_claim_pass(claims, ROWS)

    assert stopped.value.results == [
        ScoreClaim("score-1", COPY_A, ClaimResult.CLAIMED),
        ScoreClaim("score-2", COPY_B, ClaimResult.UNAVAILABLE),
    ]
    assert claims.calls == [COPY_A, COPY_B]


def test_the_counts_and_the_list_that_is_not_kept_skip_a_dry_run_row() -> None:
    results = [
        ScoreClaim("score-1", COPY_A, ClaimResult.CLAIMED),
        ScoreClaim("score-2", COPY_B, ClaimResult.EXPIRED),
        ScoreClaim("score-3", COPY_C, None),
    ]

    assert count_results(results) == {"claimed": 1, "expired": 1}
    assert not_kept(results) == [results[1]]
    assert results[2].as_dict() == {"score_id": "score-3", "frozen_copy_id": COPY_C, "result": None}
    assert results[1].as_dict()["result"] == "expired"


@pytest.mark.asyncio
async def test_the_task_waits_600_seconds_after_no_answer_and_starts_again_at_the_first_score(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=PASS_LOGGER)
    claims = MemoryClaims({COPY_B: [ClaimResult.UNAVAILABLE]})
    sleep = RecordedSleep()
    task = ClaimPassTask(claims, FlakyRows(), sleep=sleep)

    task.start()
    running = task.task
    assert running is not None
    await asyncio.wait_for(running, timeout=2)

    assert claims.calls == [COPY_A, COPY_B, COPY_A, COPY_B, COPY_C]
    assert sleep.delays == [600.0]
    assert running.exception() is None
    warnings = _records(caplog, logging.WARNING)
    assert len(warnings) == 1
    assert "the gateway did not answer" in warnings[0].getMessage()
    assert "next pass in 600 s" in warnings[0].getMessage()
    assert len(_records(caplog, logging.INFO)) == 1


@pytest.mark.asyncio
async def test_a_database_error_gives_one_error_record_and_the_same_wait(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=PASS_LOGGER)
    rows = FlakyRows(failures=1)
    claims = MemoryClaims()
    sleep = RecordedSleep()
    task = ClaimPassTask(claims, rows, sleep=sleep)

    task.start()
    running = task.task
    assert running is not None
    await asyncio.wait_for(running, timeout=2)

    assert rows.reads == 2
    assert sleep.delays == [600.0]
    errors = _records(caplog, logging.ERROR)
    assert len(errors) == 1
    assert "OperationalError" in errors[0].getMessage()
    assert "no such table" not in errors[0].getMessage()
    assert claims.calls == [COPY_A, COPY_B, COPY_C]


@pytest.mark.asyncio
async def test_a_complete_pass_writes_the_counts_and_one_warning_with_the_ids_that_are_not_kept(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=PASS_LOGGER)
    claims = MemoryClaims({COPY_B: [ClaimResult.EXPIRED], COPY_C: [ClaimResult.NOT_FOUND]})
    sleep = RecordedSleep()
    task = ClaimPassTask(claims, FlakyRows(), sleep=sleep)

    task.start()
    running = task.task
    assert running is not None
    await asyncio.wait_for(running, timeout=2)

    infos = [r.getMessage() for r in _records(caplog, logging.INFO)]
    assert infos == [
        'claim pass done: scores=3 results={"claimed": 1, "expired": 1, "not_found": 1}'
    ]
    warnings = _records(caplog, logging.WARNING)
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    for part in ("score-2", COPY_B, "expired", "score-3", COPY_C, "not_found"):
        assert part in message
    assert "score-1" not in message
    for record in caplog.records:
        if record.name == PASS_LOGGER:
            assert "@" not in record.getMessage()
    assert sleep.delays == []


@pytest.mark.asyncio
async def test_a_pass_with_each_copy_kept_writes_no_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=PASS_LOGGER)
    task = ClaimPassTask(MemoryClaims(), FlakyRows(), sleep=RecordedSleep())

    task.start()
    running = task.task
    assert running is not None
    await asyncio.wait_for(running, timeout=2)

    assert _records(caplog, logging.WARNING) == []
    assert len(_records(caplog, logging.INFO)) == 1


@pytest.mark.asyncio
async def test_stop_ends_the_task_while_it_waits_for_the_next_pass() -> None:
    claims = MemoryClaims({COPY_A: [ClaimResult.UNAVAILABLE]})
    sleep = RecordedSleep(block=True)
    task = ClaimPassTask(claims, FlakyRows(), sleep=sleep)

    task.start()
    running = task.task
    assert running is not None
    await asyncio.wait_for(sleep.entered.wait(), timeout=2)
    await asyncio.wait_for(task.stop(), timeout=2)

    assert running.cancelled()
    assert task.task is None
    assert claims.calls == [COPY_A]


@pytest.mark.asyncio
async def test_stop_before_start_does_nothing() -> None:
    task = ClaimPassTask(MemoryClaims(), FlakyRows())

    await task.stop()

    assert task.task is None


@pytest.mark.asyncio
async def test_the_store_lists_each_score_that_names_a_copy_on_every_board(
    tortoise_db: None,
) -> None:
    rows = await seed_scores()

    assert len(rows) == 3
    assert await ScoreStore().scores_that_name_a_copy() == rows


class BrokenOnceRows:
    """Gives ROWS, after one read that raises an error that is not a database error."""

    def __init__(self) -> None:
        self.reads = 0

    async def __call__(self) -> list[tuple[str, str]]:
        self.reads += 1
        if self.reads == 1:
            raise RuntimeError("row data score-1")
        return list(ROWS)


@pytest.mark.asyncio
async def test_an_error_that_is_not_from_the_database_gets_a_neutral_error_record(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=PASS_LOGGER)
    rows = BrokenOnceRows()
    sleep = RecordedSleep()
    task = ClaimPassTask(MemoryClaims(), rows, sleep=sleep)

    task.start()
    running = task.task
    assert running is not None
    await asyncio.wait_for(running, timeout=2)

    assert rows.reads == 2
    assert sleep.delays == [600.0]
    errors = _records(caplog, logging.ERROR)
    assert [record.getMessage() for record in errors] == [
        "claim pass stopped: error=RuntimeError; next pass in 600 s"
    ]


@pytest.mark.asyncio
async def test_a_wait_that_is_not_a_whole_number_is_written_as_it_is(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=PASS_LOGGER)
    claims = MemoryClaims({COPY_B: [ClaimResult.UNAVAILABLE]})
    sleep = RecordedSleep()
    task = ClaimPassTask(claims, BrokenOnceRows(), retry_s=0.5, sleep=sleep)

    task.start()
    running = task.task
    assert running is not None
    await asyncio.wait_for(running, timeout=2)

    messages = [r.getMessage() for r in _records(caplog, logging.WARNING)]
    assert "claim pass stopped: the gateway did not answer; next pass in 0.5 s" in messages
    errors = [r.getMessage() for r in _records(caplog, logging.ERROR)]
    assert errors == ["claim pass stopped: error=RuntimeError; next pass in 0.5 s"]
