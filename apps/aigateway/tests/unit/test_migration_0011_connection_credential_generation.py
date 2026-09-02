"""Migration 0011 — the durable Connection credential generation (OME-1026 U2).

The unit suite builds schemas with ``Tortoise.generate_schemas()``, so migration
files never execute there. This replays the deployed upgrade path: migrate to the
previous head, insert a REAL populated connection row, apply 0011, and prove the
column arrives NOT NULL with a SQL DEFAULT so existing rows are backfilled with 0
(their pre-fence generation) instead of failing the ADD COLUMN.

INVARIANT: the fence value is non-secret and strictly advancing per connection —
the schema only has to guarantee existence + default; the atomic bump lives in the
store's conditional UPDATEs.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[2]


def _migrate(database_url: str, *target: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "tortoise",
            "-c",
            "aigateway.db.TORTOISE_CONFIG",
            "migrate",
            *target,
        ],
        cwd=APP_DIR,
        env={**os.environ, "AIGATEWAY_DATABASE_URL": database_url},
        check=True,
        capture_output=True,
        text=True,
    )


def test_0011_backfills_existing_connections_with_generation_zero(tmp_path: Path) -> None:
    db = tmp_path / "populated.sqlite3"
    url = f"sqlite://{db}"

    _migrate(url, "models", "0010_simplify_request_cache")
    with sqlite3.connect(db) as conn:
        conn.execute(
            "insert into accounts (id, username, password_hash, created_at, is_active)"
            " values ('a1', 'u1', 'x', datetime('now'), 1)"
        )
        conn.execute(
            "insert into oauth_connections"
            " (id, provider, label, status, auth_type, credential_locator, created_at,"
            "  account_id)"
            " values ('c1', 'anthropic', 'work', 'active', 'api_key', '{}',"
            "  datetime('now'), 'a1')"
        )

    _migrate(url)
    rerun = _migrate(url)
    assert "No migrations to apply" in rerun.stdout, "0011 must be idempotent"

    with sqlite3.connect(db) as conn:
        rows = conn.execute("select credential_generation from oauth_connections").fetchall()
        columns = {row[1]: row for row in conn.execute("pragma table_info(oauth_connections)")}
    assert rows == [(0,)], "existing rows are backfilled at generation 0"
    generation_col = columns["credential_generation"]
    assert generation_col[3] == 1, "credential_generation must be NOT NULL"
    assert "0" in str(generation_col[4]), "credential_generation must carry a SQL DEFAULT"
