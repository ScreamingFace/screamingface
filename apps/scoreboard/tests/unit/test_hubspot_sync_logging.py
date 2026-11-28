"""A real HubSpot sync run says what it did, in the CronJob's log (OME-1991).

FEATURE: going live needs monitoring. A dry run logs every planned change through its sink, but a
real run logged nothing per person, and its summary line never reached the log at all.

STORY: as the engineer watching the first real runs, I read in the pod log which contact and
card each run created or changed, with HubSpot ids and no email.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

import pytest

from scoreboard.crm.decisions import PROP_COUNT, PROP_ENTRY, CardState
from scoreboard.crm.port import Contact, CrmError
from scoreboard.hubspot_sync import run_sync
from tests.unit.test_hubspot_sync_job import CONFIG, NOW, FakeSink, _board, _score

pytestmark = pytest.mark.asyncio

LOGGER = "scoreboard.hubspot_sync"
APP = Path(__file__).resolve().parents[2]


def _lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [record.getMessage() for record in caplog.records if record.name == LOGGER]


async def test_the_summary_line_reaches_the_log_when_run_as_a_module(tmp_path: Path) -> None:
    # WHY a real `python -m`: the CronJob runs the module that way, where `__name__` is
    # "__main__"; a logger named after `__name__` fell outside the configured `scoreboard` tree,
    # and every INFO line, the run summary included, was dropped in prod.
    database = tmp_path / "summary.sqlite3"
    env = {
        "PATH": "/usr/bin:/bin",
        "SCOREBOARD_DATABASE_URL": f"sqlite://{database}",
        "PYTHONPATH": str(APP / "src"),
    }
    subprocess.run(
        [sys.executable, "-m", "tortoise", "-c", "scoreboard.db.TORTOISE_CONFIG", "migrate"],
        cwd=APP,
        env=env,
        check=True,
        capture_output=True,
        timeout=180,
    )

    result = subprocess.run(
        [sys.executable, "-m", "scoreboard.hubspot_sync"],
        cwd=APP,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )

    assert result.returncode == 0, result.stderr
    lines = [line.split(None, 2) for line in result.stderr.splitlines()]
    assert [
        "INFO:",
        LOGGER,
        "hubspot sync: queued=0 skipped=0 sent=0 failed=0 waiting=0 rate_limited=False",
    ] in lines


async def test_a_real_run_logs_each_created_contact_and_card(
    tortoise_db: None, caplog: pytest.LogCaptureFixture
) -> None:
    await _board()
    await _score("ana@uni.edu")

    with caplog.at_level(logging.INFO, logger=LOGGER):
        await run_sync(FakeSink(), CONFIG, now=NOW)

    assert _lines(caplog) == [
        "hubspot sync: created contact c-1",
        "hubspot sync: created card new-card for contact c-1 in stage s1, set "
        "sf_leaderboard_url, sf_submission_count",
    ]


async def test_a_real_run_logs_what_changed_on_an_existing_card(
    tortoise_db: None, caplog: pytest.LogCaptureFixture
) -> None:
    await _board()
    await _board("gpqa")
    await _score("ana@uni.edu", spec="r1", day=1)
    await _score("ana@uni.edu", benchmark="gpqa", spec="r2", day=2)
    sink = FakeSink()
    sink.contacts["ana@uni.edu"] = Contact("c-9", "Ana", None, None)
    sink.cards["c-9"] = [CardState("deal-9", "s1", {PROP_COUNT: "1"}, frozenset())]

    with caplog.at_level(logging.INFO, logger=LOGGER):
        await run_sync(sink, CONFIG, now=NOW)

    assert _lines(caplog) == [
        "hubspot sync: card deal-9 for contact c-9: stage s1 -> s2, set "
        f"{PROP_ENTRY}, {PROP_COUNT}",
    ]


async def test_refusals_and_failures_are_logged_without_an_email(
    tortoise_db: None, caplog: pytest.LogCaptureFixture
) -> None:
    await _board()
    await _score("ana@uni.edu", spec="r1")
    await _score("bo@uni.edu", spec="r2")
    sink = FakeSink()
    sink.contacts["ana@uni.edu"] = Contact("c-9", "Ana", None, None)
    sink.cards["c-9"] = [CardState("deal-9", "out", {}, frozenset())]
    sink.fail_for["bo@uni.edu"] = CrmError(503)

    with caplog.at_level(logging.INFO, logger=LOGGER):
        await run_sync(sink, CONFIG, now=NOW)

    assert _lines(caplog) == [
        "hubspot sync: contact c-9 left alone (dropped_out)",
        "hubspot sync: one submitter failed (hubspot_503), next attempt 2026-11-20T12:05:00+00:00",
    ]


async def test_a_dry_run_does_not_repeat_the_sinks_own_lines(
    tortoise_db: None, caplog: pytest.LogCaptureFixture
) -> None:
    await _board()
    await _score("ana@uni.edu")

    with caplog.at_level(logging.INFO, logger=LOGGER):
        await run_sync(FakeSink(), CONFIG, now=NOW, dry_run=True)

    assert _lines(caplog) == []
