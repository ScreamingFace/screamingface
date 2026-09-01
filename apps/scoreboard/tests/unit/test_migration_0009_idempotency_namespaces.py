"""Migration 0009 removes legacy raw idempotency mappings, but no durable data."""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

REPO_APP = Path(__file__).resolve().parents[2]


def _migrate(database_url: str, target: str | None = None) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, "-m", "tortoise", "-c", "scoreboard.db.TORTOISE_CONFIG", "migrate"]
    if target is not None:
        command += ["models", target]
    return subprocess.run(
        command,
        cwd=REPO_APP,
        env={
            "PATH": "/usr/bin:/bin",
            "SCOREBOARD_DATABASE_URL": database_url,
            "PYTHONPATH": str(REPO_APP / "src"),
        },
        capture_output=True,
        text=True,
        timeout=180,
    )


def test_idempotency_namespace_migration_discards_only_temporary_mappings(tmp_path: Path) -> None:
    database = tmp_path / "scoreboard.sqlite3"
    url = f"sqlite://{database}"

    to_0008 = _migrate(url, "0008_benchmark_visibility")
    assert to_0008.returncode == 0, to_0008.stdout + to_0008.stderr

    connection = sqlite3.connect(database)
    connection.execute(
        """INSERT INTO benchmarks (id, display_name, visibility, created_at)
           VALUES (?, ?, ?, ?)""",
        ("sentinel", "Sentinel", "public", "2026-01-01 00:00:00"),
    )
    # WHY no score fixture: SQLite connections do not enable FK enforcement by default, which
    # lets this test seed the child table directly and stay focused on the migration's data scope.
    connection.executemany(
        """INSERT INTO idempotency_keys (key, expires_at, score_id)
           VALUES (?, ?, ?)""",
        (
            (
                "legacy-raw-key",
                "2026-08-27 00:00:00",
                "00000000-0000-0000-0000-000000000001",
            ),
            (
                "sfp-legacy-public-collision",
                "2026-08-27 00:00:00",
                "00000000-0000-0000-0000-000000000002",
            ),
        ),
    )
    connection.commit()
    connection.close()

    applied = _migrate(url)
    assert applied.returncode == 0, applied.stdout + applied.stderr

    connection = sqlite3.connect(database)
    mappings = connection.execute("SELECT key FROM idempotency_keys").fetchall()
    benchmark = connection.execute("SELECT id FROM benchmarks WHERE id = 'sentinel'").fetchone()
    connection.close()

    # INVARIANT: idempotency rows are 24-hour retry mappings, not submitted score data. They are
    # invalid under the new storage format and may be discarded; unrelated durable rows survive.
    assert mappings == [("legacy-raw-key",)]
    assert benchmark == ("sentinel",)


def test_the_migration_clears_the_escaped_public_namespace_too(tmp_path: Path) -> None:
    # `sfu-` became server-owned when the escape path started EMITTING it, but `0009` still deleted
    # only `sfp-%`, so a crafted legacy row in the new namespace survived and an escaped request
    # resolved it (review of PR #719).
    #
    # AIDEV-NOTE: this RUNS the migration rather than grepping its SQL. The clause is a compound
    # `LIKE ... OR LIKE ...`; a source-text assertion passes on a malformed one, which is how a fix
    # ships without a test that holds it.
    database = tmp_path / "scoreboard.sqlite3"
    url = f"sqlite://{database}"

    to_0008 = _migrate(url, "0008_benchmark_visibility")
    assert to_0008.returncode == 0, to_0008.stdout + to_0008.stderr

    connection = sqlite3.connect(database)
    connection.executemany(
        """INSERT INTO idempotency_keys (key, expires_at, score_id)
           VALUES (?, ?, ?)""",
        (
            ("sfu-crafted-legacy", "2026-08-27 00:00:00", "00000000-0000-0000-0000-000000000003"),
            ("sfp-crafted-legacy", "2026-08-27 00:00:00", "00000000-0000-0000-0000-000000000004"),
            # Neither reserved namespace, and both must survive: this clears two
            # prefixes, not a table.
            ("sfx-not-reserved", "2026-08-27 00:00:00", "00000000-0000-0000-0000-000000000005"),
            ("ordinary-retry", "2026-08-27 00:00:00", "00000000-0000-0000-0000-000000000006"),
        ),
    )
    connection.commit()
    connection.close()

    applied = _migrate(url)
    assert applied.returncode == 0, applied.stdout + applied.stderr

    connection = sqlite3.connect(database)
    survivors = sorted(
        row[0] for row in connection.execute("SELECT key FROM idempotency_keys").fetchall()
    )
    connection.close()

    assert survivors == ["ordinary-retry", "sfx-not-reserved"]
