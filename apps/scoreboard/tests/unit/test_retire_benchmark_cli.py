"""The `python -m scoreboard.retire_benchmark` boundary.

WHY a separate file with a real on-disk database instead of the `tortoise_db` fixture: `main()`
goes through `Settings()`, `init_db()` and `close_db()`, and those are exactly what these tests
exist to exercise. Running them against a real SQLite file proves the CLI opens and closes its own
connection on both the success and the refusal path — which a fixture-provided connection would
hide (raised by @HupBaHa on PR #726).
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest
from tortoise import Tortoise

from scoreboard.db import close_db, init_db
from scoreboard.retire_benchmark import main
from scoreboard.scores.schemas import ScoreSubmission
from scoreboard.scores.store import ScoreStore


@pytest.fixture
def seeded_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    url = f"sqlite://{tmp_path / 'scoreboard.sqlite3'}"
    monkeypatch.setenv("SCOREBOARD_DATABASE_URL", url)

    async def _seed() -> None:
        await init_db(url)
        await Tortoise.generate_schemas(safe=True)
        store = ScoreStore()
        await store.register_benchmark(benchmark_id="legacy", display_name="Legacy")
        await store.register_benchmark(
            benchmark_id="engine-owned", display_name="Engine", revision="rev-1"
        )
        await store.register_benchmark(benchmark_id="referenced", display_name="Referenced")
        await store.submit(
            ScoreSubmission(
                benchmark_id="referenced",
                spec_id="spec-1",
                url4_expression="url4://benchmark/spec-1",
                submitted_by="tester@example.test",
                score=0.5,
                total_questions=100,
                correct_questions=50,
                ran_with_providers=["openai"],
                run_cost_usd=Decimal("1.000000"),
            )
        )
        await close_db()

    asyncio.run(_seed())
    yield


async def _survivors() -> list[str]:
    return [row.id for row in await ScoreStore().list_benchmarks()]


def _read_back() -> list[str]:
    import os

    async def _go() -> list[str]:
        await init_db(os.environ["SCOREBOARD_DATABASE_URL"])
        try:
            return await _survivors()
        finally:
            await close_db()

    return asyncio.run(_go())


def test_the_default_is_a_dry_run_that_deletes_nothing(
    seeded_database: None, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["--benchmark", "legacy"])

    assert "would retire" in capsys.readouterr().out
    assert "legacy" in _read_back()


def test_yes_deletes_and_reports_it(
    seeded_database: None, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["--benchmark", "legacy", "--yes"])

    assert "retired 'legacy'" in capsys.readouterr().out
    assert "legacy" not in _read_back()


def test_an_unknown_benchmark_exits_two_without_a_traceback(
    seeded_database: None, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--benchmark", "ghost", "--yes"])

    assert exit_info.value.code == 2
    assert "unknown benchmark_id" in capsys.readouterr().err


def test_a_referenced_benchmark_exits_two_without_a_traceback(
    seeded_database: None, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--benchmark", "referenced", "--yes"])

    assert exit_info.value.code == 2
    assert "1 score" in capsys.readouterr().err
    # INVARIANT: the refusal path must still close its connection, or the next call in the same
    # process hangs. Reading back proves the database is usable afterwards.
    assert "referenced" in _read_back()


def test_an_engine_owned_benchmark_exits_two_and_names_the_override(
    seeded_database: None, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--benchmark", "engine-owned", "--yes"])

    assert exit_info.value.code == 2
    assert "--include-engine-owned" in capsys.readouterr().err
    assert "engine-owned" in _read_back()


def test_the_override_flag_is_wired_through(
    seeded_database: None, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["--benchmark", "engine-owned", "--yes", "--include-engine-owned"])

    assert "retired 'engine-owned'" in capsys.readouterr().out
    assert "engine-owned" not in _read_back()


def test_the_override_alone_does_not_delete_without_yes(
    seeded_database: None, capsys: pytest.CaptureFixture[str]
) -> None:
    # --include-engine-owned relaxes WHICH benchmarks are eligible. It is not a confirmation.
    main(["--benchmark", "engine-owned", "--include-engine-owned"])

    assert "would retire" in capsys.readouterr().out
    assert "engine-owned" in _read_back()


def test_benchmark_is_required(seeded_database: None) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main([])

    assert exit_info.value.code == 2
