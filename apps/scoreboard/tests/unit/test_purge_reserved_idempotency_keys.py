"""The reserved-namespace purge: its report, its CLI, and its wiring to the chart."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from tortoise import Tortoise, run_async

from scoreboard.db import close_db, init_db
from scoreboard.purge_reserved_idempotency_keys import _format, main
from scoreboard.scores.models import IdempotencyKey, Score
from scoreboard.scores.schemas import ScoreSubmission
from scoreboard.scores.store import RESERVED_KEY_PREFIXES, ScoreStore

CHART = Path(__file__).resolve().parents[2] / "charts/scoreboard"


def test_the_report_names_every_prefix_and_the_total() -> None:
    # An operator has to be able to tell "the window produced nothing" from "the job did nothing".
    assert _format({"sfp-": 2, "sfu-": 0}, dry_run=False) == (
        "removed 2 reserved-namespace mappings (sfp-2, sfu-0)"
    )


def test_a_dry_run_says_it_changed_nothing() -> None:
    assert _format({"sfp-": 1, "sfu-": 1}, dry_run=True).startswith("would remove 2")


def test_an_unknown_flag_is_refused_rather_than_ignored() -> None:
    # A typo'd flag on an operator command must not silently run the default action.
    with pytest.raises(SystemExit):
        main(["--purge-everything"])


def test_the_job_runs_post_upgrade_only() -> None:
    # INVARIANT: the whole point is to run AFTER the rollout the pre-upgrade migration cannot see.
    # A `pre-*` hook here would reproduce the bug it exists to close, and `post-install` would be
    # noise — a fresh install has no old replicas and no legacy rows.
    manifest = (CHART / "templates/job-purge-idempotency.yaml").read_text()

    assert '"helm.sh/hook": post-upgrade' in manifest
    assert "pre-upgrade" not in manifest.split("*/}}")[-1]
    assert "python\n            - -m\n            - scoreboard.purge_reserved_idempotency_keys" in (
        manifest
    )


def test_the_job_is_enabled_by_default() -> None:
    # Shipped off, the rollout window stays open on every deploy and nobody finds out.
    values = (CHART / "values.yaml").read_text()

    assert "purgeReservedIdempotencyKeys:" in values
    block = values.split("purgeReservedIdempotencyKeys:")[1]
    assert block.split("\n")[1].strip() == "enabled: true"


def test_the_purge_does_not_keep_its_own_copy_of_the_prefixes() -> None:
    source = (CHART.parents[1] / "src/scoreboard/purge_reserved_idempotency_keys.py").read_text()

    for prefix in RESERVED_KEY_PREFIXES:
        assert f'"{prefix}"' not in source, (
            f"{prefix!r} is hardcoded in the purge; it must share RESERVED_KEY_PREFIXES so a third "
            "namespace cannot be reserved without being purged"
        )


@pytest.fixture
def seeded_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    # A FILE-backed database, matching `test_retire_benchmark_cli`: `main()` opens and closes its
    # own connection, so an in-memory URL would vanish between the seed and the call under test.
    url = f"sqlite://{tmp_path / 'scoreboard.sqlite3'}"
    monkeypatch.setenv("SCOREBOARD_DATABASE_URL", url)

    async def _seed() -> None:
        await init_db(url)
        await Tortoise.generate_schemas(safe=True)
        store = ScoreStore()
        await store.register_benchmark(benchmark_id="hle", display_name="HLE")
        await store.submit(
            ScoreSubmission(
                benchmark_id="hle",
                spec_id="spec-1",
                url4_expression="url4://benchmark/spec-1",
                submitted_by="tester@example.test",
                score=0.5,
                total_questions=100,
                correct_questions=50,
                ran_with_providers=["openai"],
            ),
            idempotency_key="ordinary",
        )
        score = await Score.all().first()
        assert score is not None
        expires = datetime.now(UTC) + timedelta(hours=24)
        for key in ("sfp-crafted", "sfu-crafted"):
            await IdempotencyKey.create(key=key, score=score, expires_at=expires)
        await close_db()

    run_async(_seed())
    yield


def _read_back() -> list[str]:
    keys: list[str] = []

    async def _load() -> None:
        import os

        await init_db(os.environ["SCOREBOARD_DATABASE_URL"])
        keys.extend(sorted(row.key for row in await IdempotencyKey.all()))
        await close_db()

    run_async(_load())
    return keys


def test_the_cli_purges_both_namespaces_and_reports_it(
    seeded_database: None, capsys: pytest.CaptureFixture[str]
) -> None:
    main([])

    assert "removed 2 reserved-namespace mappings (sfp-1, sfu-1)" in capsys.readouterr().out
    # INVARIANT: an ordinary client key is untouched — a reserved namespace is purged,
    # never the table.
    assert _read_back() == ["ordinary"]


def test_the_cli_dry_run_reports_without_deleting(
    seeded_database: None, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["--dry-run"])

    assert "would remove 2" in capsys.readouterr().out
    assert _read_back() == ["ordinary", "sfp-crafted", "sfu-crafted"]
