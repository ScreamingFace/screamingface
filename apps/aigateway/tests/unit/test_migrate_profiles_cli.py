"""`python -m aigateway.migrate_profiles` — the command line around the backfill (OME-1208, S4).

# FEATURE: the operator-facing shell: modes, scope, exit codes, the JSON report on stdout, the
# optional journal, and the real `-m` entry point on the fixture database.
# INVARIANT: the tool never mints a master key (a database with neither `AIGATEWAY_SECRET_KEY` nor a
# persisted key is refused, exit 2); a conflict exits 3 so a scheduler retries; the report and the
# journal carry opaque identifiers only.
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
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from aigateway import migrate_profiles
from aigateway.core.auth.models import Account
from aigateway.core.oauth.store import credential_locator_for
from aigateway.core.profile_index import ProfileIndexStore
from aigateway.core.profile_models import Profile, ProfileDefaults, ProfileState, profile_id_for
from aigateway.core.provider_access.pair_authority import PairAuthorityConflict, PairAuthorityStore
from aigateway.db import close_db, init_db

PROVIDER = "anthropic"
TOKEN = "tok-cli-4242"
PROMPT = "TOP SECRET CLI PROMPT"
NEEDLES = (TOKEN, PROMPT, "v1:", "aigateway:", "default")


@pytest.fixture
def env(credential_blobs: Any, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    key = base64.b64encode(b"k" * 32).decode()
    monkeypatch.setenv("AIGATEWAY_SECRET_KEY", key)
    return {
        **os.environ,
        "AIGATEWAY_DATABASE_URL": f"sqlite://{credential_blobs.db_path}",
        "AIGATEWAY_SECRET_KEY": key,
    }


def seed_profile_only(credential_blobs: Any, *, with_account: bool) -> str:
    """A legacy authenticated document + its blob for a fresh account, optionally its Account."""
    account_id = str(uuid4())
    locator = credential_locator_for(PROVIDER, account_id, "default")
    credential_blobs.write(
        locator["service"],
        locator["account"],
        json.dumps({"access_token": TOKEN, "refresh_token": "rt", "token_type": "Bearer"}),
    )
    profile = Profile(
        id=profile_id_for(account_id, PROVIDER, "default"),
        account_id=account_id,
        provider=PROVIDER,
        name="default",
        state=ProfileState.AUTHENTICATED,
        defaults=ProfileDefaults(system_prompt=PROMPT),
    )
    asyncio.run(ProfileIndexStore(credential_store=credential_blobs.store).upsert(profile))
    if with_account:

        async def create_account() -> None:
            await init_db(f"sqlite://{credential_blobs.db_path}")
            try:
                await Account.create(id=account_id, username=account_id[:8], password_hash="x")
            finally:
                await close_db()

        asyncio.run(create_account())
    return account_id


def rows(credential_blobs: Any, table: str) -> int:
    with sqlite3.connect(credential_blobs.db_path) as conn:
        return conn.execute(f"select count(*) from {table}").fetchone()[0]  # noqa: S608


def run_main(*argv: str) -> tuple[int, dict[str, Any]]:
    out = io.StringIO()
    code = migrate_profiles.main(list(argv), out=out)
    return code, json.loads(out.getvalue())


# --- argument contract -------------------------------------------------------------------------


def test_modes_and_scope_parse() -> None:
    args = migrate_profiles.parse_args(["--dry-run", "--all"])
    assert (args.mode, args.all, args.account, args.journal) == ("dry-run", True, None, None)
    args = migrate_profiles.parse_args(["--apply", "--account", "abc", "--journal", "j.log"])
    assert (args.mode, args.all, args.account, args.journal) == ("apply", False, "abc", "j.log")
    assert migrate_profiles.parse_args(["--rollback", "--all"]).mode == "rollback"


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--apply"],
        ["--all"],
        ["--dry-run", "--apply", "--all"],
        ["--dry-run", "--all", "--account", "abc"],
    ],
)
def test_incomplete_or_contradictory_arguments_are_usage_errors(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        migrate_profiles.parse_args(argv)
    assert exc.value.code == migrate_profiles.EXIT_USAGE


# --- the real thing on the fixture database -----------------------------------------------------


def test_dry_run_then_apply_then_dry_run(credential_blobs: Any, env: dict[str, str]) -> None:
    account_id = seed_profile_only(credential_blobs, with_account=True)

    code, report = run_main("--dry-run", "--account", account_id)
    assert code == migrate_profiles.EXIT_OK
    (pair,) = report["accounts"][0]["pairs"]
    assert (pair["disposition"], pair["category"], pair["applied"]) == (
        "migrated",
        "profile_only",
        False,
    )
    assert rows(credential_blobs, "oauth_connections") == 0
    assert rows(credential_blobs, "provider_credential_slots") == 0
    text = json.dumps(report)
    assert [needle for needle in NEEDLES if needle in text] == []

    code, report = run_main("--apply", "--account", account_id)
    assert code == migrate_profiles.EXIT_OK
    assert report["counts"] == {
        "migrated": 1,
        "quarantined": 0,
        "none": 0,
        "applied": 1,
        "conflicts": 0,
    }
    assert rows(credential_blobs, "oauth_connections") == 1
    assert rows(credential_blobs, "provider_credential_slots") == 1

    code, report = run_main("--dry-run", "--account", account_id)
    (pair,) = report["accounts"][0]["pairs"]
    assert (pair["category"], pair["applied"], pair["generation"]) == ("already_migrated", False, 1)


def test_journal_appends_one_line_per_pair_and_a_summary(
    credential_blobs: Any, env: dict[str, str], tmp_path: Path
) -> None:
    account_id = seed_profile_only(credential_blobs, with_account=False)
    journal = tmp_path / "backfill.jsonl"
    code, _report = run_main("--dry-run", "--account", account_id, "--journal", str(journal))
    assert code == migrate_profiles.EXIT_OK
    lines = [json.loads(line) for line in journal.read_text().splitlines()]
    assert len(lines) == 2
    assert (lines[0]["account_id"], lines[0]["category"]) == (account_id, "profile_only")
    assert lines[1] == {
        "mode": "dry-run",
        "summary": {"migrated": 1, "quarantined": 0, "none": 0, "applied": 0, "conflicts": 0},
    }
    assert [needle for needle in NEEDLES if needle in journal.read_text()] == []


def test_a_conflict_exits_three(
    credential_blobs: Any, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    account_id = seed_profile_only(credential_blobs, with_account=True)

    async def losing(*_args: Any, **_kwargs: Any) -> Any:
        raise PairAuthorityConflict(PROVIDER, 0)

    monkeypatch.setattr(PairAuthorityStore, "advance", losing)
    code, report = run_main("--apply", "--account", account_id)
    assert code == migrate_profiles.EXIT_RETRY
    assert report["accounts"][0]["conflict"] is True
    assert rows(credential_blobs, "oauth_connections") == 0


def test_without_any_master_key_the_tool_refuses_and_mints_none(
    credential_blobs: Any, env: dict[str, str], monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    account_id = seed_profile_only(credential_blobs, with_account=False)
    monkeypatch.delenv("AIGATEWAY_SECRET_KEY")
    code = migrate_profiles.main(["--dry-run", "--account", account_id], out=io.StringIO())
    assert code == migrate_profiles.EXIT_USAGE
    assert "refused" in capsys.readouterr().err
    # INVARIANT: a dry run writes nothing — not even the master key the app would auto-generate.
    assert rows(credential_blobs, "secret_master_keys") == 0


def test_the_module_runs_under_python_m(credential_blobs: Any, env: dict[str, str]) -> None:
    account_id = seed_profile_only(credential_blobs, with_account=False)
    completed = subprocess.run(
        [sys.executable, "-m", "aigateway.migrate_profiles", "--dry-run", "--account", account_id],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert completed.returncode == migrate_profiles.EXIT_OK, completed.stderr
    report = json.loads(completed.stdout)
    assert report["mode"] == "dry-run"
    assert report["counts"]["migrated"] == 1
    assert [needle for needle in NEEDLES if needle in completed.stdout] == []
