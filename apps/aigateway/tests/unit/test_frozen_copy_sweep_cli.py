"""The operator command of the frozen copy sweep (OME-1947, contracts K6).

WHY the database lifecycle is patched: the app's own Tortoise is already up on the portal loop,
so the command must not open or close it a second time.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

import aigateway.frozen_copy_sweep as cli
from aigateway.config import Settings
from tests.unit.test_frozen_copy_support import (
    account_id_of,
    run_async,
    seed_copy,
    stored_entries,
)
from tests.unit.test_frozen_copy_sweep_support import age_copy, make_entries, read_copy

_HOUR = timedelta(hours=1)


def _state(client: TestClient, copy_id: str) -> tuple[str, Any, Any, int]:
    copy = read_copy(client, copy_id)
    return (copy.status, copy.swept_at, copy.purged_at, len(stored_entries(client, copy_id)))


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


@pytest.mark.usefixtures("_no_db_lifecycle")
def test_the_command_with_no_argument_is_a_dry_run_that_changes_nothing(
    authenticated_client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    owner = account_id_of(authenticated_client)
    idle_id = seed_copy(authenticated_client, owner, make_entries(2), seal=False)
    age_copy(authenticated_client, idle_id, copy_age=30 * _HOUR, entry_age=25 * _HOUR)
    active_id = seed_copy(authenticated_client, owner, make_entries(1), seal=False)
    age_copy(authenticated_client, active_id, copy_age=_HOUR, entry_age=_HOUR)
    before = [_state(authenticated_client, idle_id), _state(authenticated_client, active_id)]

    _command(authenticated_client, [])

    doc = _last_json(capsys)
    assert set(doc) == {"evaluated_at", "rules", "by_account", "candidates"}
    assert doc["rules"]["abandoned"] == {"copies": 1, "entries": 2}
    assert doc["rules"]["expired"] == {"copies": 0, "entries": 0}
    assert doc["by_account"] == [
        {"account": "admin", "rule": "abandoned", "copies": 1, "entries": 2}
    ]
    assert [c["id"] for c in doc["candidates"]] == [idle_id]
    after = [_state(authenticated_client, idle_id), _state(authenticated_client, active_id)]
    assert after == before


@pytest.mark.parametrize(
    "argv",
    [
        ["--run", "--cutoff", "2026-12-01T00:00:00+00:00"],
        ["--cutoff", "2026-12-01T00:00:00"],
        ["--max-entries", "5"],
        ["--run", "--max-entries", "0"],
        ["--cutoff", "tomorrow"],
    ],
)
def test_bad_arguments_exit_with_status_2(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.main(argv)

    assert exc_info.value.code == 2


@pytest.mark.usefixtures("_no_db_lifecycle")
def test_a_future_cutoff_lists_a_copy_that_is_idle_at_that_time(
    authenticated_client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    copy_id = seed_copy(
        authenticated_client, account_id_of(authenticated_client), make_entries(1), seal=False
    )
    age_copy(authenticated_client, copy_id, copy_age=2 * _HOUR, entry_age=_HOUR)

    _command(authenticated_client, [])
    assert _last_json(capsys)["candidates"] == []

    cutoff = (datetime.now(UTC) + timedelta(hours=25)).isoformat()
    _command(authenticated_client, ["--cutoff", cutoff])

    assert [c["id"] for c in _last_json(capsys)["candidates"]] == [copy_id]
    copy = read_copy(authenticated_client, copy_id)
    assert copy.status == "open"
    assert len(stored_entries(authenticated_client, copy_id)) == 1


@pytest.mark.usefixtures("_no_db_lifecycle")
def test_run_marks_and_purges_in_one_pass(
    authenticated_client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    owner = account_id_of(authenticated_client)
    first_id = seed_copy(authenticated_client, owner, make_entries(2), seal=False)
    second_id = seed_copy(authenticated_client, owner, make_entries(3), seal=False)
    for copy_id in (first_id, second_id):
        age_copy(authenticated_client, copy_id, copy_age=30 * _HOUR, entry_age=30 * _HOUR)

    _command(authenticated_client, ["--run"])

    out = _last_json(capsys)
    assert out["trigger"] == "command"
    assert out["marked"] == {"abandoned": 2}
    assert out["entries_purged"] == 5
    assert out["copies_completed"] == 2
    assert out["purge_stopped"] is None
    for copy_id in (first_id, second_id):
        copy = read_copy(authenticated_client, copy_id)
        assert copy.status == "abandoned"
        assert copy.purged_at is not None
        assert stored_entries(authenticated_client, copy_id) == []


@pytest.mark.usefixtures("_no_db_lifecycle")
def test_max_entries_sets_the_budget_of_the_pass(
    authenticated_client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    copy_id = seed_copy(
        authenticated_client, account_id_of(authenticated_client), make_entries(2), seal=False
    )
    age_copy(authenticated_client, copy_id, copy_age=30 * _HOUR, entry_age=30 * _HOUR)

    _command(authenticated_client, ["--run", "--max-entries", "1"])

    out = _last_json(capsys)
    assert out["purge_stopped"] == "budget"
    assert out["entries_purged"] == 1
    assert out["copies_with_entries"] == 1
    assert len(stored_entries(authenticated_client, copy_id)) == 1


def test_a_failure_exits_with_status_1_and_prints_only_the_type(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def _boom(args: object, settings: object) -> None:
        raise RuntimeError("SECRET-MARKER")

    monkeypatch.setattr(cli, "_amain", _boom)

    assert cli.main([]) == 1

    err = capsys.readouterr().err
    assert "RuntimeError" in err
    assert "SECRET-MARKER" not in err
