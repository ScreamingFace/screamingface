"""`python -m aigateway.purge_profile_history` — the command line around the purge (OME-1138, E5b).

# FEATURE: Stage E history cleanup, spec C5 — the owner-run shell: modes, scope, exit codes, the
# JSON report on stdout, the optional journal, and the real `-m` entry point on the fixture
# database.
# INVARIANT: the tool never mints a master key (a database with neither `AIGATEWAY_SECRET_KEY` nor a
# persisted key is refused, exit 2); a skipped account exits 4, so the owner looks before calling an
# environment clean; the report and the journal carry account ids and counts only.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from aigateway import purge_profile_history
from aigateway.core.auth.models import Account
from aigateway.core.provider_access.pair_authority import PairAuthorityStore
from aigateway.db import close_db, init_db
from tests.conftest import TEST_SECRET_KEY

KEY = "sk-cli-purge-1357"
NEEDLES = ("aigateway:", "v1:", "default", KEY)


@pytest.fixture
def env(credential_blobs: Any, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    key = base64.b64encode(TEST_SECRET_KEY).decode()
    monkeypatch.setenv("AIGATEWAY_SECRET_KEY", key)
    monkeypatch.delenv("AIGW_REMOTE_ENDPOINTS_CONFIG", raising=False)
    return {
        **os.environ,
        "AIGATEWAY_DATABASE_URL": f"sqlite://{credential_blobs.db_path}",
        "AIGATEWAY_SECRET_KEY": key,
    }


def seed_account(credential_blobs: Any, *, quarantined: bool = False) -> str:
    """An account with its Profile index row and one blob no Connection addresses."""
    account_id = str(uuid4())

    async def create() -> None:
        await init_db(f"sqlite://{credential_blobs.db_path}")
        try:
            await Account.create(id=account_id, username=account_id[:8], password_hash="x")
            if quarantined:
                await PairAuthorityStore().advance(
                    account_id, "anthropic", expected_generation=0, migration_state="quarantined"
                )
        finally:
            await close_db()

    asyncio.run(create())
    credential_blobs.write(
        f"aigateway:anthropic:{account_id}:{uuid4()}", "default", json.dumps({"api_key": KEY})
    )
    credential_blobs.write("aigateway:index", f"account:{account_id}", '{"profiles": []}')
    return account_id


def rows(credential_blobs: Any, table: str = "credential_blobs") -> int:
    with closing(sqlite3.connect(credential_blobs.db_path)) as conn:
        return conn.execute(f"select count(*) from {table}").fetchone()[0]  # noqa: S608


def run_main(*argv: str) -> tuple[int, dict[str, Any]]:
    out = io.StringIO()
    code = purge_profile_history.main(list(argv), out=out)
    return code, json.loads(out.getvalue())


# --- argument contract -------------------------------------------------------------------------


def test_modes_and_scope_parse() -> None:
    account_id = str(uuid4())
    args = purge_profile_history.parse_args(["--dry-run", "--all"])
    assert (args.mode, args.all, args.account, args.journal) == ("dry-run", True, None, None)
    args = purge_profile_history.parse_args(
        ["--apply", "--account", account_id, "--journal", "j.log"]
    )
    assert (args.mode, args.all, args.account, args.journal) == (
        "apply",
        False,
        account_id,
        "j.log",
    )


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--apply"],
        ["--all"],
        ["--dry-run", "--apply", "--all"],
        ["--dry-run", "--all", "--account", str(uuid4())],
        ["--dry-run", "--account", "not-an-account-id"],
        ["--rollback", "--all"],
    ],
)
def test_incomplete_or_contradictory_arguments_are_usage_errors(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        purge_profile_history.parse_args(argv)
    assert exc.value.code == purge_profile_history.EXIT_USAGE


@pytest.mark.parametrize("scope", [["--all"], ["--account", str(uuid4())]])
def test_apply_without_a_journal_is_a_usage_error(scope: list[str]) -> None:
    # WHY: an apply commits account by account; the journal is the record of a run that stops
    # part-way, and a dry run needs none.
    with pytest.raises(SystemExit) as exc:
        purge_profile_history.parse_args(["--apply", *scope])
    assert exc.value.code == purge_profile_history.EXIT_USAGE
    assert purge_profile_history.parse_args(["--dry-run", *scope]).journal is None


def test_help_names_the_conditions_of_a_run(capsys: Any) -> None:
    # WHY: the run resolves physical accounts from its own environment, and the owner reads these
    # conditions where they type the command.
    with pytest.raises(SystemExit) as exc:
        purge_profile_history.parse_args(["--help"])
    assert exc.value.code == 0
    text = " ".join(capsys.readouterr().out.split())
    for condition in (
        "the gateway's own environment",
        "address_unproven",
        "Back the database up",
        "On SQLite, stop the gateway",
        "kept_unrecognised_rows",
        # WHY: revoking a Connection keeps its row, and the purge counts rows of every status.
        "connection_unresolvable",
        "a revoked row still counts",
        "kept_unproven_rows",
        "the sweep's line with --all",
    ):
        assert condition in text


# --- the real thing on the fixture database -----------------------------------------------------


def test_dry_run_then_apply_then_dry_run(
    credential_blobs: Any, env: dict[str, str], tmp_path: Path
) -> None:
    account_id = seed_account(credential_blobs)
    journal = str(tmp_path / "purge.jsonl")

    code, report = run_main("--dry-run", "--account", account_id)
    assert code == purge_profile_history.EXIT_OK
    assert report["mode"] == "dry-run"
    assert (report["counts"]["index_rows"], report["counts"]["uuid_shaped_blobs"]) == (1, 1)
    assert rows(credential_blobs) == 2
    assert [needle for needle in NEEDLES if needle in json.dumps(report)] == []

    code, report = run_main("--apply", "--all", "--journal", journal)
    assert code == purge_profile_history.EXIT_OK
    assert (report["counts"]["index_rows"], report["counts"]["uuid_shaped_blobs"]) == (1, 1)
    assert rows(credential_blobs) == 0

    code, report = run_main("--dry-run", "--all")
    assert code == purge_profile_history.EXIT_OK
    assert set(report["counts"].values()) == {0}


def test_a_skipped_account_exits_four_and_keeps_every_row(
    credential_blobs: Any, env: dict[str, str], tmp_path: Path
) -> None:
    account_id = seed_account(credential_blobs, quarantined=True)
    journal = str(tmp_path / "purge.jsonl")

    code, report = run_main("--apply", "--account", account_id, "--journal", journal)

    assert code == purge_profile_history.EXIT_SKIPPED
    assert report["accounts"] == [
        {
            "account_id": account_id,
            "rows": {"index_rows": 0, "name_shaped_blobs": 0, "uuid_shaped_blobs": 0},
            "skipped": "quarantined_marker",
        }
    ]
    assert report["counts"]["skipped_accounts"] == 1
    assert rows(credential_blobs) == 2


def test_journal_appends_one_line_per_account_and_a_summary(
    credential_blobs: Any, env: dict[str, str], tmp_path: Path
) -> None:
    account_id = seed_account(credential_blobs)
    journal = tmp_path / "purge.jsonl"

    code, report = run_main("--dry-run", "--account", account_id, "--journal", str(journal))

    assert code == purge_profile_history.EXIT_OK
    lines = [json.loads(line) for line in journal.read_text().splitlines()]
    assert len(lines) == 2
    assert (lines[0]["account_id"], lines[0]["skipped"]) == (account_id, None)
    assert lines[1] == {"mode": "dry-run", "summary": report["counts"], "legacy_index": None}
    assert [needle for needle in NEEDLES if needle in journal.read_text()] == []


def test_without_any_master_key_the_tool_refuses_and_mints_none(
    credential_blobs: Any, env: dict[str, str], monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    account_id = seed_account(credential_blobs)
    monkeypatch.delenv("AIGATEWAY_SECRET_KEY")

    code = purge_profile_history.main(["--dry-run", "--account", account_id], out=io.StringIO())

    assert code == purge_profile_history.EXIT_USAGE
    assert "refused" in capsys.readouterr().err
    # INVARIANT: a dry run writes nothing — not even the master key the app would auto-generate.
    assert rows(credential_blobs, "secret_master_keys") == 0
    assert rows(credential_blobs) == 2


def test_the_module_runs_under_python_m(credential_blobs: Any, env: dict[str, str]) -> None:
    account_id = seed_account(credential_blobs)

    completed = subprocess.run(
        [sys.executable, "-m", "aigateway.purge_profile_history", "--dry-run", "--all"],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert completed.returncode == purge_profile_history.EXIT_OK, completed.stderr
    report = json.loads(completed.stdout)
    assert report["mode"] == "dry-run"
    assert [account["account_id"] for account in report["accounts"]] == [account_id]
    assert [needle for needle in NEEDLES if needle in completed.stdout] == []
