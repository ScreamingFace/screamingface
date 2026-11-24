"""The database refuses a sealed copy that the sweep has swept (OME-1947, PR #1911 finding 1).

An image before 0018 seals each copy that is not `sealed`. While it runs beside a new image, it
could seal a copy that the new sweep made `abandoned` and is purging. Migration 0018 makes the
database refuse `status = 'sealed'` with a non-null `swept_at`
(`ck_frozen_copies_sealed_not_swept`): a CHECK constraint on Postgres, two triggers on SQLite.

The unit suite builds its tables with `generate_schemas`, which has no such constraint, so the
SQLite tests here run on a database that `tortoise migrate` built.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from aigateway.core.frozen_copy.models import FrozenCopy
from aigateway.core.frozen_copy.sweep import FrozenCopySweep, IdleRule, database_now
from tests.unit.test_frozen_copy_support import (
    account_id_of,
    run_async,
    seed_copy,
    stored_entries,
)
from tests.unit.test_frozen_copy_sweep_support import age_copy, make_entries, read_copy

APP_DIR = Path(__file__).resolve().parents[2]
_PREVIOUS = "0017_drop_migration_note"
_CONSTRAINT = "ck_frozen_copies_sealed_not_swept"
_OLD_SEAL_SQL = (
    "UPDATE frozen_copies SET status = 'sealed', sealed_at = '2026-11-23T00:00:00+00:00' "
    "WHERE status <> 'sealed'"
)


def _tortoise(database_url: str, *args: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "tortoise", "-c", "aigateway.db.TORTOISE_CONFIG", *args],
        cwd=APP_DIR,
        env={**os.environ, "AIGATEWAY_DATABASE_URL": database_url},
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def migrated(tmp_path: Path) -> Path:
    db = tmp_path / "migrated.sqlite3"
    _tortoise(f"sqlite://{db}", "migrate")
    return db


def _insert_copy(conn: sqlite3.Connection, *, status: str, swept_at: str | None = None) -> str:
    copy_id = str(uuid4())
    conn.execute(
        "INSERT INTO frozen_copies (id, account_id, status, entries, entry_seq, created_at, "
        "swept_at) VALUES (?, ?, ?, 0, 0, '2026-11-20T00:00:00+00:00', ?)",
        (copy_id, str(uuid4()), status, swept_at),
    )
    return copy_id


def _status(conn: sqlite3.Connection, copy_id: str) -> tuple[str, str | None]:
    row = conn.execute(
        "SELECT status, sealed_at FROM frozen_copies WHERE id = ?", (copy_id,)
    ).fetchone()
    return row[0], row[1]


def _guards(db: Path) -> set[str]:
    with sqlite3.connect(db) as conn:
        return {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = ?",
                ("frozen_copies",),
            )
        }


def test_an_old_style_seal_of_a_swept_copy_is_refused(migrated: Path) -> None:
    with sqlite3.connect(migrated) as conn:
        copy_id = _insert_copy(conn, status="abandoned", swept_at="2026-11-22T00:00:00+00:00")
        conn.commit()

        with pytest.raises(sqlite3.IntegrityError, match=_CONSTRAINT):
            conn.execute(_OLD_SEAL_SQL)
        conn.rollback()

        assert _status(conn, copy_id) == ("abandoned", None)


def test_a_swept_copy_cannot_be_inserted_as_sealed(migrated: Path) -> None:
    with sqlite3.connect(migrated) as conn:
        with pytest.raises(sqlite3.IntegrityError, match=_CONSTRAINT):
            _insert_copy(conn, status="sealed", swept_at="2026-11-22T00:00:00+00:00")


def test_a_sealed_copy_cannot_be_given_a_sweep_time(migrated: Path) -> None:
    with sqlite3.connect(migrated) as conn:
        copy_id = _insert_copy(conn, status="sealed")
        conn.commit()

        with pytest.raises(sqlite3.IntegrityError, match=_CONSTRAINT):
            conn.execute(
                "UPDATE frozen_copies SET swept_at = '2026-11-22T00:00:00+00:00' WHERE id = ?",
                (copy_id,),
            )


def test_the_writes_of_this_change_are_allowed(migrated: Path) -> None:
    """Seal of an open copy, mark of an open copy, the purge stamp, and a sealed copy as is."""
    with sqlite3.connect(migrated) as conn:
        to_seal = _insert_copy(conn, status="open")
        conn.execute(
            "UPDATE frozen_copies SET status = 'sealed', sealed_at = '2026-11-23T00:00:00+00:00' "
            "WHERE id = ?",
            (to_seal,),
        )
        to_mark = _insert_copy(conn, status="open")
        conn.execute(
            "UPDATE frozen_copies SET status = 'abandoned', swept_at = '2026-11-22T00:00:00+00:00'"
            " WHERE id = ?",
            (to_mark,),
        )
        conn.execute(
            "UPDATE frozen_copies SET purged_at = '2026-11-22T00:00:01+00:00' WHERE id = ?",
            (to_mark,),
        )
        expired = _insert_copy(conn, status="expired", swept_at="2026-11-22T00:00:00+00:00")
        conn.commit()

        assert _status(conn, to_seal)[0] == "sealed"
        assert _status(conn, to_mark)[0] == "abandoned"
        assert _status(conn, expired)[0] == "expired"


def test_0018_installs_the_guard(migrated: Path) -> None:
    assert {f"{_CONSTRAINT}_insert", f"{_CONSTRAINT}_update"} <= _guards(migrated)


def test_0018_downgrade_drops_the_guard_and_upgrade_restores_it(tmp_path: Path) -> None:
    db = tmp_path / "down.sqlite3"
    url = f"sqlite://{db}"
    _tortoise(url, "migrate")
    _tortoise(url, "downgrade", "models", _PREVIOUS)

    assert not any(name.startswith(_CONSTRAINT) for name in _guards(db))

    _tortoise(url, "migrate")

    assert {f"{_CONSTRAINT}_insert", f"{_CONSTRAINT}_update"} <= _guards(db)


def test_the_purge_skips_a_sealed_copy_that_carries_a_sweep_time(
    authenticated_client: TestClient,
) -> None:
    """Defence in depth: the purge reads only `abandoned` and `expired` copies.

    The unit tables have no constraint, so a sealed copy with `swept_at` can be arranged here.
    """
    client = authenticated_client
    copy_id = seed_copy(client, account_id_of(client), make_entries(2))
    age_copy(client, copy_id, copy_age=48 * timedelta(hours=1), entry_age=48 * timedelta(hours=1))

    async def _stamp() -> None:
        await FrozenCopy.filter(id=UUID(copy_id)).update(swept_at=await database_now())

    run_async(client, _stamp)
    sweep = FrozenCopySweep(
        [IdleRule(open_idle_seconds=86_400)], max_entries=100_000, sleep=_no_sleep
    )

    report = run_async(client, lambda: sweep.run_pass(trigger="command"))

    copy = read_copy(client, copy_id)
    assert copy.status == "sealed"
    assert copy.purged_at is None
    assert len(stored_entries(client, copy_id)) == 2
    assert report.entries_purged == 0
    assert report.copies_completed == 0


async def _no_sleep(_delay: float) -> None:
    return None
