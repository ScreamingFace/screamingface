"""The idle rule and the purge of the frozen copy sweep on SQLite (OME-1947, prd/copy-sweep.md
section 7).
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from aigateway.config import Settings
from aigateway.core.frozen_copy.models import FrozenCopyEntry
from aigateway.core.frozen_copy.sweep import (
    FrozenCopySweep,
    IdleRule,
    SweepReport,
    build_frozen_copy_sweep,
    database_now,
)
from tests.unit.test_frozen_copy_support import (
    account_id_of,
    run_async,
    seed_copy,
    stored_entries,
)
from tests.unit.test_frozen_copy_sweep_support import age_copy, make_entries, read_copy

_HOUR = timedelta(hours=1)
_SWEEP_LOGGER = "aigateway.core.frozen_copy.sweep"


class _Sleeps:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)


class _StepClock:
    def __init__(self, step: float = 0.0) -> None:
        self.t = 0.0
        self._step = step

    def __call__(self) -> float:
        current = self.t
        self.t += self._step
        return current


def _sweep(
    *,
    max_entries: int = 100_000,
    chunk_size: int = 500,
    clock: Any = None,
    sleep: Any = None,
) -> FrozenCopySweep:
    return FrozenCopySweep(
        [IdleRule(open_idle_seconds=86_400)],
        max_entries=max_entries,
        chunk_size=chunk_size,
        sleep=sleep or _Sleeps(),
        clock=clock or _StepClock(),
    )


def _pass(client: TestClient, sweep: FrozenCopySweep, **kw: Any) -> SweepReport:
    return run_async(client, lambda: sweep.run_pass(trigger="command", **kw))


def test_an_open_copy_with_a_recent_entry_stays_open(authenticated_client: TestClient) -> None:
    copy_id = seed_copy(
        authenticated_client, account_id_of(authenticated_client), make_entries(3), seal=False
    )
    age_copy(authenticated_client, copy_id, copy_age=40 * _HOUR, entry_age=timedelta(minutes=10))

    report = _pass(authenticated_client, _sweep())

    copy = read_copy(authenticated_client, copy_id)
    assert copy.status == "open"
    assert copy.swept_at is None
    assert len(stored_entries(authenticated_client, copy_id)) == 3
    assert report.marked == {"abandoned": 0}


def test_a_sealed_copy_is_never_marked(authenticated_client: TestClient) -> None:
    copy_id = seed_copy(authenticated_client, account_id_of(authenticated_client), make_entries(2))
    age_copy(authenticated_client, copy_id, copy_age=48 * _HOUR, entry_age=48 * _HOUR)

    _pass(authenticated_client, _sweep())

    copy = read_copy(authenticated_client, copy_id)
    assert copy.status == "sealed"
    assert copy.swept_at is None
    assert len(stored_entries(authenticated_client, copy_id)) == 2


def test_an_idle_open_copy_is_abandoned_then_purged(authenticated_client: TestClient) -> None:
    copy_id = seed_copy(
        authenticated_client, account_id_of(authenticated_client), make_entries(3), seal=False
    )
    age_copy(authenticated_client, copy_id, copy_age=30 * _HOUR, entry_age=25 * _HOUR)

    report = _pass(authenticated_client, _sweep())

    copy = read_copy(authenticated_client, copy_id)
    assert copy.status == "abandoned"
    assert copy.swept_at is not None
    assert copy.entries == 3
    assert stored_entries(authenticated_client, copy_id) == []
    assert copy.purged_at is not None
    assert report.marked == {"abandoned": 1}
    assert report.entries_purged == 3
    assert report.copies_completed == 1
    assert report.copies_with_entries == 0
    assert report.purge_stopped is None


def test_the_status_is_final_before_the_first_delete(
    authenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    copy_id = seed_copy(
        authenticated_client, account_id_of(authenticated_client), make_entries(3), seal=False
    )
    age_copy(authenticated_client, copy_id, copy_age=30 * _HOUR, entry_age=25 * _HOUR)
    sweep = _sweep()

    async def _boom(copy_id: UUID, *, limit: int | None = None) -> int:
        raise RuntimeError("db down SECRET-MARKER")

    monkeypatch.setattr(sweep, "purge_chunk", _boom)
    with caplog.at_level(logging.ERROR, logger=_SWEEP_LOGGER):
        with pytest.raises(RuntimeError):
            _pass(authenticated_client, sweep)

    copy = read_copy(authenticated_client, copy_id)
    assert copy.status == "abandoned"
    assert copy.swept_at is not None
    assert copy.purged_at is None
    assert len(stored_entries(authenticated_client, copy_id)) == 3
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert "RuntimeError" in errors[0].getMessage()
    assert "SECRET-MARKER" not in caplog.text


def test_a_failed_purge_leaves_purged_at_null_and_the_next_run_completes_it(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    copy_id = seed_copy(
        authenticated_client, account_id_of(authenticated_client), make_entries(3), seal=False
    )
    age_copy(authenticated_client, copy_id, copy_age=30 * _HOUR, entry_age=25 * _HOUR)
    sweep = _sweep(chunk_size=1)
    real = sweep.purge_chunk
    calls = [0]

    async def _flaky(copy_id: UUID, *, limit: int | None = None) -> int:
        calls[0] += 1
        if calls[0] == 2:
            raise RuntimeError("db down")
        return await real(copy_id, limit=limit)

    monkeypatch.setattr(sweep, "purge_chunk", _flaky)
    with pytest.raises(RuntimeError):
        _pass(authenticated_client, sweep)

    copy = read_copy(authenticated_client, copy_id)
    assert copy.purged_at is None
    assert len(stored_entries(authenticated_client, copy_id)) == 2

    report = _pass(authenticated_client, _sweep())

    copy = read_copy(authenticated_client, copy_id)
    assert stored_entries(authenticated_client, copy_id) == []
    assert copy.purged_at is not None
    assert report.copies_completed == 1


def test_an_open_copy_with_no_entry_is_abandoned_and_purged_by_the_mark(
    authenticated_client: TestClient,
) -> None:
    copy_id = seed_copy(authenticated_client, account_id_of(authenticated_client), [], seal=False)
    age_copy(authenticated_client, copy_id, copy_age=25 * _HOUR)
    at = run_async(authenticated_client, database_now)

    outcome = run_async(
        authenticated_client,
        lambda: IdleRule(open_idle_seconds=86_400).mark(UUID(copy_id), at),
    )

    assert outcome == "marked"
    copy = read_copy(authenticated_client, copy_id)
    assert copy.status == "abandoned"
    assert copy.purged_at is not None
    assert copy.swept_at is not None
    assert copy.entries == 0


def test_the_purge_stops_at_the_budget_and_continues_with_the_copy_marked_first(
    authenticated_client: TestClient,
) -> None:
    owner = account_id_of(authenticated_client)
    copy_a = seed_copy(authenticated_client, owner, make_entries(2), seal=False)
    copy_b = seed_copy(authenticated_client, owner, make_entries(3), seal=False)
    for copy_id in (copy_a, copy_b):
        age_copy(authenticated_client, copy_id, copy_age=30 * _HOUR, entry_age=25 * _HOUR)
    at = run_async(authenticated_client, database_now)
    rule = IdleRule(open_idle_seconds=86_400)

    async def _mark_both() -> list[str]:
        return [
            await rule.mark(UUID(copy_a), at),
            await rule.mark(UUID(copy_b), at + timedelta(seconds=1)),
        ]

    assert run_async(authenticated_client, _mark_both) == ["marked", "marked"]

    first = _pass(authenticated_client, _sweep(), max_entries=3)

    assert first.purge_stopped == "budget"
    assert first.entries_purged == 3
    assert first.copies_completed == 1
    assert first.copies_with_entries == 1
    assert stored_entries(authenticated_client, copy_a) == []
    assert read_copy(authenticated_client, copy_a).purged_at is not None
    assert len(stored_entries(authenticated_client, copy_b)) == 2
    assert read_copy(authenticated_client, copy_b).purged_at is None

    second = _pass(authenticated_client, _sweep(), max_entries=3)

    assert second.entries_purged == 2
    assert second.copies_completed == 1
    assert second.purge_stopped is None
    assert read_copy(authenticated_client, copy_b).purged_at is not None


def test_a_second_run_changes_nothing_on_a_purged_copy(authenticated_client: TestClient) -> None:
    copy_id = seed_copy(
        authenticated_client, account_id_of(authenticated_client), make_entries(2), seal=False
    )
    age_copy(authenticated_client, copy_id, copy_age=30 * _HOUR, entry_age=25 * _HOUR)
    _pass(authenticated_client, _sweep())
    before = read_copy(authenticated_client, copy_id)

    second = _pass(authenticated_client, _sweep())

    after = read_copy(authenticated_client, copy_id)
    assert (after.swept_at, after.purged_at, after.status, after.entries) == (
        before.swept_at,
        before.purged_at,
        before.status,
        before.entries,
    )
    assert second.marked == {"abandoned": 0}
    assert second.entries_purged == 0


def test_an_open_copy_whose_newest_entry_is_missing_is_skipped(
    authenticated_client: TestClient,
) -> None:
    copy_id = seed_copy(
        authenticated_client, account_id_of(authenticated_client), make_entries(2), seal=False
    )
    age_copy(authenticated_client, copy_id, copy_age=30 * _HOUR, entry_age=25 * _HOUR)

    async def _drop_newest() -> None:
        await FrozenCopyEntry.filter(frozen_copy_id=UUID(copy_id), seq=2).delete()

    run_async(authenticated_client, _drop_newest)
    at = run_async(authenticated_client, database_now)
    rule = IdleRule(open_idle_seconds=86_400)

    candidates = run_async(authenticated_client, lambda: rule.candidates(at))
    assert [(c.copy_id, c.skip) for c in candidates] == [(UUID(copy_id), "newest entry not found")]
    outcome = run_async(authenticated_client, lambda: rule.mark(UUID(copy_id), at))

    assert outcome == "newest entry not found"
    copy = read_copy(authenticated_client, copy_id)
    assert copy.status == "open"
    assert copy.swept_at is None


def test_the_purge_stops_when_chunks_are_slow(authenticated_client: TestClient) -> None:
    copy_id = seed_copy(
        authenticated_client, account_id_of(authenticated_client), make_entries(11), seal=False
    )
    age_copy(authenticated_client, copy_id, copy_age=30 * _HOUR, entry_age=25 * _HOUR)
    sleeps = _Sleeps()

    report = _pass(
        authenticated_client,
        _sweep(chunk_size=1, clock=_StepClock(step=6.0), sleep=sleeps),
    )

    assert report.purge_stopped == "slow"
    assert report.entries_purged == 10
    assert report.copies_with_entries == 1
    assert sleeps.delays == [0.2] * 9


def test_a_dry_run_lists_the_idle_copy_and_changes_nothing(
    authenticated_client: TestClient,
) -> None:
    copy_id = seed_copy(
        authenticated_client, account_id_of(authenticated_client), make_entries(2), seal=False
    )
    age_copy(authenticated_client, copy_id, copy_age=30 * _HOUR, entry_age=25 * _HOUR)

    doc = run_async(authenticated_client, lambda: _sweep().dry_run())

    assert doc["rules"] == {
        "abandoned": {"copies": 1, "entries": 2},
        "expired": {"copies": 0, "entries": 0},
    }
    assert doc["by_account"] == [
        {"account": "admin", "rule": "abandoned", "copies": 1, "entries": 2}
    ]
    assert doc["candidates"] == [{"rule": "abandoned", "id": copy_id, "entries": 2}]
    assert "evaluated_at" in doc
    copy = read_copy(authenticated_client, copy_id)
    assert copy.status == "open"
    assert len(stored_entries(authenticated_client, copy_id)) == 2


def test_the_builder_uses_the_idle_time_and_the_budget_of_the_settings(
    authenticated_client: TestClient,
) -> None:
    copy_id = seed_copy(
        authenticated_client, account_id_of(authenticated_client), make_entries(2), seal=False
    )
    # WHY 2 h idle: the default 24 h would not mark this copy; the 1 h of the settings does.
    age_copy(authenticated_client, copy_id, copy_age=3 * _HOUR, entry_age=2 * _HOUR)
    idle_1h: dict[str, Any] = {"_env_file": None, "frozen_copy_open_idle_seconds": 3600}
    sweep = build_frozen_copy_sweep(Settings(**idle_1h, frozen_copy_sweep_max_entries=1))

    report = run_async(authenticated_client, lambda: sweep.run_pass(trigger="command"))

    assert report.marked == {"abandoned": 1, "expired": 0}
    assert report.entries_purged == 1
    assert report.purge_stopped == "budget"
    assert read_copy(authenticated_client, copy_id).status == "abandoned"
    assert len(stored_entries(authenticated_client, copy_id)) == 1


def test_the_run_log_record_has_counts_and_no_account_name_or_copy_id(
    authenticated_client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    owner = account_id_of(authenticated_client)
    copy_id = seed_copy(authenticated_client, owner, make_entries(3), seal=False)
    age_copy(authenticated_client, copy_id, copy_age=30 * _HOUR, entry_age=25 * _HOUR)

    with caplog.at_level(logging.INFO, logger=_SWEEP_LOGGER):
        _pass(authenticated_client, _sweep())

    records = [r for r in caplog.records if r.name == _SWEEP_LOGGER and r.levelno == logging.INFO]
    assert len(records) == 1
    assert records[0].getMessage() == (
        'frozen copy sweep run trigger=command marked={"abandoned": 1} '
        'skipped={"abandoned": {}} entries_purged=3 copies_completed=1 '
        "copies_with_entries=0 purge_stopped=none"
    )
    assert copy_id not in caplog.text
    assert str(owner) not in caplog.text
    assert "admin" not in caplog.text


def test_a_run_reports_an_open_copy_whose_newest_entry_is_missing(
    authenticated_client: TestClient,
) -> None:
    copy_id = seed_copy(
        authenticated_client, account_id_of(authenticated_client), make_entries(2), seal=False
    )
    age_copy(authenticated_client, copy_id, copy_age=30 * _HOUR, entry_age=25 * _HOUR)

    async def _drop_newest() -> None:
        await FrozenCopyEntry.filter(frozen_copy_id=UUID(copy_id), seq=2).delete()

    run_async(authenticated_client, _drop_newest)

    doc = run_async(authenticated_client, lambda: _sweep().dry_run())

    assert doc["candidates"] == []
    assert doc["rules"]["abandoned"] == {"copies": 0, "entries": 0}

    report = _pass(authenticated_client, _sweep())

    assert report.marked == {"abandoned": 0}
    assert report.skipped == {"abandoned": {"newest entry not found": 1}}
    assert report.entries_purged == 0
    copy = read_copy(authenticated_client, copy_id)
    assert copy.status == "open"
    assert copy.swept_at is None
    assert copy.purged_at is None
    assert len(stored_entries(authenticated_client, copy_id)) == 1


def test_a_chunk_that_uses_the_budget_exactly_completes_the_copy(
    authenticated_client: TestClient,
) -> None:
    copy_id = seed_copy(
        authenticated_client, account_id_of(authenticated_client), make_entries(3), seal=False
    )
    age_copy(authenticated_client, copy_id, copy_age=30 * _HOUR, entry_age=25 * _HOUR)

    report = _pass(authenticated_client, _sweep(), max_entries=3)

    assert report.entries_purged == 3
    assert report.copies_completed == 1
    assert report.copies_with_entries == 0
    assert report.purge_stopped is None
    assert read_copy(authenticated_client, copy_id).purged_at is not None
    assert stored_entries(authenticated_client, copy_id) == []


def test_after_an_exact_budget_the_next_copy_waits_for_the_next_run(
    authenticated_client: TestClient,
) -> None:
    owner = account_id_of(authenticated_client)
    copy_a = seed_copy(authenticated_client, owner, make_entries(3), seal=False)
    copy_b = seed_copy(authenticated_client, owner, make_entries(2), seal=False)
    for copy_id in (copy_a, copy_b):
        age_copy(authenticated_client, copy_id, copy_age=30 * _HOUR, entry_age=25 * _HOUR)
    at = run_async(authenticated_client, database_now)
    rule = IdleRule(open_idle_seconds=86_400)

    async def _mark_both() -> list[str]:
        return [
            await rule.mark(UUID(copy_a), at),
            await rule.mark(UUID(copy_b), at + timedelta(seconds=1)),
        ]

    assert run_async(authenticated_client, _mark_both) == ["marked", "marked"]

    report = _pass(authenticated_client, _sweep(), max_entries=3)

    assert report.purge_stopped == "budget"
    assert report.entries_purged == 3
    assert report.copies_completed == 1
    assert report.copies_with_entries == 1
    assert read_copy(authenticated_client, copy_a).purged_at is not None
    assert stored_entries(authenticated_client, copy_a) == []
    assert read_copy(authenticated_client, copy_b).purged_at is None
    assert len(stored_entries(authenticated_client, copy_b)) == 2
