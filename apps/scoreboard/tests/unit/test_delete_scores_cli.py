"""The `python -m scoreboard.delete_scores` boundary (OME-1385).

WHY a real on-disk database, as in `test_retire_benchmark_cli.py`: `main()` goes through
`Settings()`, `init_db()` and `close_db()`, and a fixture-provided connection would hide whether
the CLI opens and closes its own on both the success and the refusal path.

INVARIANT: stdout carries the backup and NOTHING else, so `kubectl exec ... > backup.jsonl` lands
a clean JSONL file on the operator's disk. Every message goes to stderr.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from tortoise import Tortoise

from scoreboard.db import close_db, init_db
from scoreboard.delete_scores import main
from scoreboard.scores.models import Score
from scoreboard.scores.schemas import ScoreSubmission
from scoreboard.scores.store import ScoreStore

BOARD = "draco-3pass"
CUTOFF = "2026-09-09T00:00:00Z"


@pytest.fixture
def seeded_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    url = f"sqlite://{tmp_path / 'scoreboard.sqlite3'}"
    monkeypatch.setenv("SCOREBOARD_DATABASE_URL", url)
    ids: list[str] = []

    async def _seed() -> None:
        await init_db(url)
        await Tortoise.generate_schemas(safe=True)
        store = ScoreStore()
        await store.register_benchmark(benchmark_id=BOARD, display_name="Draco 3-pass")
        for spec_id, submitted_at in (
            ("old-a", datetime(2026, 9, 8, tzinfo=UTC)),
            ("old-b", datetime(2026, 9, 8, tzinfo=UTC)),
            ("new", datetime(2026, 9, 25, tzinfo=UTC)),
        ):
            outcome = await store.submit(
                ScoreSubmission(
                    benchmark_id=BOARD,
                    spec_id=spec_id,
                    url4_expression=f"url4://benchmark/{spec_id}",
                    submitted_by="irina@example.test",
                    score=0.5,
                    total_questions=100,
                    correct_questions=50,
                    ran_with_providers=["openrouter"],
                    run_cost_usd=Decimal("0.000000"),
                    run_cost_status="complete",
                )
            )
            await Score.filter(id=outcome.score.id).update(submitted_at=submitted_at)
            ids.append(str(outcome.score.id))
        await close_db()

    asyncio.run(_seed())
    yield ids


def _remaining_specs() -> set[str]:
    async def _go() -> set[str]:
        await init_db(os.environ["SCOREBOARD_DATABASE_URL"])
        try:
            return {score.spec_id for score in await Score.all()}
        finally:
            await close_db()

    return asyncio.run(_go())


def _by_cutoff(*extra: str) -> list[str]:
    return ["--benchmark", BOARD, "--submitted-before", CUTOFF, "--expect", "2", *extra]


def test_the_default_is_a_dry_run_whose_stdout_is_only_the_backup(
    seeded_database: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    main(_by_cutoff())

    captured = capsys.readouterr()
    lines = [json.loads(line) for line in captured.out.splitlines()]
    assert {line["spec_id"] for line in lines} == {"old-a", "old-b"}
    assert "would delete 2" in captured.err
    assert "--yes" in captured.err
    assert _remaining_specs() == {"old-a", "old-b", "new"}


def test_yes_deletes_and_still_writes_the_backup_first(
    seeded_database: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    main(_by_cutoff("--yes"))

    captured = capsys.readouterr()
    assert len(captured.out.splitlines()) == 2
    assert "deleted 2" in captured.err
    assert _remaining_specs() == {"new"}


def test_ids_are_accepted_repeatedly(
    seeded_database: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    old_a, old_b, _new = seeded_database

    main(["--benchmark", BOARD, "--id", old_a, "--id", old_b, "--expect", "2", "--yes"])

    assert _remaining_specs() == {"new"}


def test_a_count_mismatch_exits_two_and_leaves_stdout_empty(
    seeded_database: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--benchmark", BOARD, "--submitted-before", CUTOFF, "--expect", "3", "--yes"])

    captured = capsys.readouterr()
    assert exit_info.value.code == 2
    assert "matched 2" in captured.err
    # WHY empty: a refusal's output redirected to backup.jsonl must not look like a real backup.
    assert captured.out == ""
    # The refusal path closed its connection: the database is readable afterwards.
    assert _remaining_specs() == {"old-a", "old-b", "new"}


def test_an_unknown_benchmark_exits_two_without_a_traceback(
    seeded_database: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--benchmark", "ghost", "--submitted-before", CUTOFF, "--expect", "1"])

    assert exit_info.value.code == 2
    assert "unknown benchmark_id" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [
        ["--benchmark", BOARD, "--expect", "2"],
        ["--benchmark", BOARD, "--submitted-before", CUTOFF],
        ["--benchmark", BOARD, "--id", "not-a-uuid", "--expect", "1"],
        ["--benchmark", BOARD, "--submitted-before", "yesterday", "--expect", "1"],
        ["--benchmark", BOARD, "--submitted-before", "2026-09-09", "--expect", "1"],
    ],
    ids=["no-selector", "no-expect", "bad-uuid", "bad-date", "naive-date"],
)
def test_malformed_arguments_exit_two_and_delete_nothing(
    seeded_database: list[str], capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main([*argv, "--yes"])

    assert exit_info.value.code == 2
    assert capsys.readouterr().out == ""
    assert _remaining_specs() == {"old-a", "old-b", "new"}


def test_the_two_selectors_cannot_be_combined(
    seeded_database: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    old_a = seeded_database[0]

    with pytest.raises(SystemExit) as exit_info:
        main(["--benchmark", BOARD, "--id", old_a, "--submitted-before", CUTOFF, "--expect", "1"])

    assert exit_info.value.code == 2
    assert _remaining_specs() == {"old-a", "old-b", "new"}
