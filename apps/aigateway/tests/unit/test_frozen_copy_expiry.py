"""The expiry rule of the frozen copy sweep on SQLite
(OME-1947, prd/copy-sweep.md S-1, S-4, S-6, S-35, S-37)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

import aigateway.frozen_copy_sweep as cli
from aigateway.config import Settings
from aigateway.core.frozen_copy.models import STATUS_ABANDONED, FrozenCopy
from aigateway.core.frozen_copy.sweep import FrozenCopySweep, build_frozen_copy_sweep
from aigateway.core.frozen_copy.sweep_rules import ExpiryRule
from tests.unit.test_frozen_copy_support import (
    account_id_of,
    run_async,
    seed_copy,
    stored_entries,
)
from tests.unit.test_frozen_copy_sweep_support import make_entries, read_copy

_TTL_S = 7_776_000
_TTL = timedelta(seconds=_TTL_S)
_DAY = timedelta(days=1)
_SECOND = timedelta(seconds=1)


async def _no_sleep(_delay: float) -> None:
    return None


def _sweep(ttl_s: int = _TTL_S) -> FrozenCopySweep:
    return FrozenCopySweep(
        [ExpiryRule(unclaimed_ttl_seconds=ttl_s)],
        max_entries=100_000,
        sleep=_no_sleep,
        clock=lambda: 0.0,
    )


def _set_times(client: TestClient, copy_id: str, **values: datetime | None) -> None:
    # INVARIANT (plan Risk 3): each value is a timezone-aware UTC time; SQLite compares text.
    async def _update() -> None:
        await FrozenCopy.filter(id=UUID(copy_id)).update(**values)

    run_async(client, _update)


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _candidate_ids(client: TestClient, rule: ExpiryRule, at: datetime) -> set[str]:
    return {str(c.copy_id) for c in run_async(client, lambda: rule.candidates(at))}


def _command(client: TestClient, argv: list[str]) -> None:
    args = cli._parse_args(argv)
    no_env_file: dict[str, Any] = {"_env_file": None}
    settings = Settings(**no_env_file)
    run_async(client, lambda: cli._amain(args, settings))


def _last_json(capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


@pytest.fixture
def _no_db_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop(*_args: object) -> None:
        return None

    monkeypatch.setattr(cli, "init_db", _noop)
    monkeypatch.setattr(cli, "close_db", _noop)


def test_s6_an_unclaimed_sealed_copy_past_its_period_expires_and_is_purged(
    authenticated_client: TestClient,
) -> None:
    owner = account_id_of(authenticated_client)
    copy_id = seed_copy(authenticated_client, owner, make_entries(3))
    _set_times(authenticated_client, copy_id, sealed_at=_now() - 91 * _DAY)

    report = run_async(authenticated_client, lambda: _sweep().run_pass(trigger="command"))

    assert report.marked == {"expired": 1}
    assert report.entries_purged == 3
    copy = read_copy(authenticated_client, copy_id)
    assert copy.status == "expired"
    assert copy.swept_at is not None
    assert copy.purged_at is not None
    assert copy.entries == 3
    assert stored_entries(authenticated_client, copy_id) == []


def test_s6_an_expired_copy_with_no_entry_is_purged_at_the_mark(
    authenticated_client: TestClient,
) -> None:
    owner = account_id_of(authenticated_client)
    copy_id = seed_copy(authenticated_client, owner, [])
    _set_times(authenticated_client, copy_id, sealed_at=_now() - 91 * _DAY)

    run_async(authenticated_client, lambda: _sweep().run_pass(trigger="command"))

    copy = read_copy(authenticated_client, copy_id)
    assert copy.status == "expired"
    assert copy.purged_at is not None
    assert copy.swept_at is not None


def test_s1_a_claimed_sealed_copy_keeps_its_status_and_entries_at_any_age(
    authenticated_client: TestClient,
) -> None:
    owner = account_id_of(authenticated_client)
    copy_id = seed_copy(authenticated_client, owner, make_entries(2))
    _set_times(authenticated_client, copy_id, sealed_at=_now() - 400 * _DAY, claimed_at=_now())

    report = run_async(authenticated_client, lambda: _sweep().run_pass(trigger="command"))

    assert report.marked == {"expired": 0}
    copy = read_copy(authenticated_client, copy_id)
    assert copy.status == "sealed"
    assert copy.swept_at is None
    assert len(stored_entries(authenticated_client, copy_id)) == 2


def test_s4_retention_from_starts_the_clock_and_not_sealed_at(
    authenticated_client: TestClient,
) -> None:
    owner = account_id_of(authenticated_client)
    copy_id = seed_copy(authenticated_client, owner, make_entries(1))
    now = _now()
    start = now - 10 * _DAY
    _set_times(authenticated_client, copy_id, retention_from=start, sealed_at=now - 200 * _DAY)
    rule = ExpiryRule(unclaimed_ttl_seconds=_TTL_S)

    assert copy_id not in _candidate_ids(authenticated_client, rule, now)
    assert copy_id not in _candidate_ids(authenticated_client, rule, start + _TTL - _SECOND)
    assert copy_id in _candidate_ids(authenticated_client, rule, start + _TTL)


def test_s4_with_no_retention_from_the_clock_starts_at_the_seal(
    authenticated_client: TestClient,
) -> None:
    owner = account_id_of(authenticated_client)
    copy_id = seed_copy(authenticated_client, owner, make_entries(1))
    sealed = _now() - 10 * _DAY
    _set_times(authenticated_client, copy_id, sealed_at=sealed)
    rule = ExpiryRule(unclaimed_ttl_seconds=_TTL_S)

    assert copy_id not in _candidate_ids(authenticated_client, rule, sealed + _TTL - _SECOND)
    assert copy_id in _candidate_ids(authenticated_client, rule, sealed + _TTL)
    outcome = run_async(
        authenticated_client, lambda: rule.mark(UUID(copy_id), sealed + _TTL - _SECOND)
    )
    assert outcome == "rule no longer true"
    outcome = run_async(authenticated_client, lambda: rule.mark(UUID(copy_id), sealed + _TTL))
    assert outcome == "marked"
    assert read_copy(authenticated_client, copy_id).status == "expired"


def test_s4_only_a_sealed_copy_past_its_period_expires(
    authenticated_client: TestClient,
) -> None:
    owner = account_id_of(authenticated_client)
    open_id = seed_copy(authenticated_client, owner, make_entries(1), seal=False)
    _set_times(authenticated_client, open_id, created_at=_now() - 200 * _DAY)
    abandoned_id = seed_copy(authenticated_client, owner, make_entries(1))
    _set_times(authenticated_client, abandoned_id, sealed_at=_now() - 200 * _DAY)

    async def _abandon() -> None:
        await FrozenCopy.filter(id=UUID(abandoned_id)).update(status=STATUS_ABANDONED)

    run_async(authenticated_client, _abandon)
    sealed_id = seed_copy(authenticated_client, owner, make_entries(1))
    _set_times(authenticated_client, sealed_id, sealed_at=_now() - 10 * _DAY)

    report = run_async(authenticated_client, lambda: _sweep().run_pass(trigger="command"))

    assert report.marked == {"expired": 0}
    assert read_copy(authenticated_client, open_id).status == "open"
    assert read_copy(authenticated_client, abandoned_id).status == "abandoned"
    assert read_copy(authenticated_client, sealed_id).status == "sealed"
    rule = ExpiryRule(unclaimed_ttl_seconds=_TTL_S)
    outcome = run_async(authenticated_client, lambda: rule.mark(UUID(abandoned_id), _now()))
    assert outcome == "rule no longer true"


def test_s37_the_builder_uses_the_unclaimed_ttl_of_the_settings(
    authenticated_client: TestClient,
) -> None:
    owner = account_id_of(authenticated_client)
    copy_id = seed_copy(authenticated_client, owner, make_entries(1))
    _set_times(authenticated_client, copy_id, sealed_at=_now() - timedelta(hours=2))
    ttl_1h: dict[str, Any] = {"_env_file": None, "frozen_copy_unclaimed_ttl_seconds": 3600}
    sweep = build_frozen_copy_sweep(Settings(**ttl_1h))

    report = run_async(authenticated_client, lambda: sweep.run_pass(trigger="command"))

    assert report.marked == {"abandoned": 0, "expired": 1}
    assert read_copy(authenticated_client, copy_id).status == "expired"


@pytest.mark.usefixtures("_no_db_lifecycle")
def test_s35_a_dry_run_lists_an_expired_candidate_and_changes_nothing(
    authenticated_client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    owner = account_id_of(authenticated_client)
    a_id = seed_copy(authenticated_client, owner, make_entries(2))
    _set_times(authenticated_client, a_id, sealed_at=_now() - 91 * _DAY)
    b_id = seed_copy(authenticated_client, owner, make_entries(1))
    _set_times(authenticated_client, b_id, sealed_at=_now() - 80 * _DAY)

    def _state(copy_id: str) -> tuple[str, Any, Any, int]:
        copy = read_copy(authenticated_client, copy_id)
        return (
            copy.status,
            copy.swept_at,
            copy.purged_at,
            len(stored_entries(authenticated_client, copy_id)),
        )

    before = [_state(a_id), _state(b_id)]

    _command(authenticated_client, [])
    doc = _last_json(capsys)

    assert doc["rules"]["expired"] == {"copies": 1, "entries": 2}
    assert doc["candidates"] == [{"rule": "expired", "id": a_id, "entries": 2}]
    assert doc["by_account"] == [{"account": "admin", "rule": "expired", "copies": 1, "entries": 2}]

    cutoff = (datetime.now(UTC) + 11 * _DAY).isoformat()
    _command(authenticated_client, ["--cutoff", cutoff])
    expired_ids = {c["id"] for c in _last_json(capsys)["candidates"] if c["rule"] == "expired"}
    assert expired_ids == {a_id, b_id}

    assert [_state(a_id), _state(b_id)] == before
