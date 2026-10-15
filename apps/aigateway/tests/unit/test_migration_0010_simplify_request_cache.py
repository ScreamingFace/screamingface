from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[2]
_TABLE = "request_cache_entries"

type _SQLiteIndex = tuple[str, bool, str, tuple[str, ...]]

_HEAD_INDEXES: set[_SQLiteIndex] = {
    ("idx_request_cac_expires_fec131", False, "c", ("expires_at",)),
    ("idx_request_cac_key_has_b2926c", False, "c", ("key_hash",)),
    ("idx_request_cac_model_e0199d", False, "c", ("model",)),
    ("idx_request_cac_prompt__feba99", False, "c", ("prompt_hash",)),
    ("idx_request_cac_provide_662524", False, "c", ("provider",)),
    ("sqlite_autoindex_request_cache_entries_1", True, "pk", ("id",)),
    ("sqlite_autoindex_request_cache_entries_2", True, "u", ("key_hash",)),
}
_LEGACY_INDEXES: set[_SQLiteIndex] = _HEAD_INDEXES | {
    ("idx_request_cac_account_8282e8", False, "c", ("account_id",)),
    (
        "idx_request_cac_account_ea8c05",
        False,
        "c",
        ("account_id", "profile_name", "provider", "expires_at"),
    ),
    ("idx_request_cac_profile_38b028", False, "c", ("profile_name",)),
}


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


def _downgrade(database_url: str, migration: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "tortoise",
            "-c",
            "aigateway.db.TORTOISE_CONFIG",
            "downgrade",
            "models",
            migration,
        ],
        cwd=APP_DIR,
        env={**os.environ, "AIGATEWAY_DATABASE_URL": database_url},
        check=True,
        capture_output=True,
        text=True,
    )


def _seed_preflight_row(db: Path) -> None:
    payload = json.dumps({"id": "obsolete"}, separators=(",", ":"))
    with sqlite3.connect(db) as conn:
        conn.execute(
            f"insert into {_TABLE} (id, key_hash, key_version, account_id, profile_name,"
            " prompt_hash, provider, model, response_ciphertext, response_size_bytes,"
            " created_at, updated_at, expires_at, hit_count)"
            " values (?, ?, 'aigw-chat-cache-v1', 'acct-1', 'default', ?, 'anthropic',"
            " 'anthropic/claude-haiku-4-5', ?, ?, datetime('now'), datetime('now'), ?, 0)",
            (
                str(uuid.uuid4()),
                "a" * 64,
                "p" * 64,
                payload,
                len(payload),
                (datetime.now(UTC) + timedelta(hours=1)).isoformat(sep=" "),
            ),
        )


def _indexes(db: Path) -> set[_SQLiteIndex]:
    with sqlite3.connect(db) as conn:
        rows = list(conn.execute(f"pragma index_list({_TABLE})"))
        return {
            (
                row[1],
                bool(row[2]),
                row[3],
                tuple(column[2] for column in conn.execute(f"pragma index_info('{row[1]}')")),
            )
            for row in rows
        }


@pytest.fixture
def populated_0009(tmp_path: Path) -> tuple[Path, str]:
    db = tmp_path / "populated-0009.sqlite3"
    url = f"sqlite://{db}"
    _migrate(url, "models", "0009_global_request_cache")
    _seed_preflight_row(db)
    return db, url


def test_0010_replaces_the_preflight_schema_with_one_cache_lane(
    populated_0009: tuple[Path, str],
) -> None:
    db, url = populated_0009

    _migrate(url, "models", "0010_simplify_request_cache")

    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        columns = {row["name"]: row for row in conn.execute(f"pragma table_info({_TABLE})")}
        row_count = conn.execute(f"select count(*) from {_TABLE}").fetchone()[0]

    assert row_count == 0
    assert {"account_id", "profile_name", "key_version", "response_ciphertext"}.isdisjoint(columns)
    assert "response_json" in columns
    assert columns["expires_at"]["notnull"] == 0
    assert _indexes(db) == _HEAD_INDEXES


def test_0010_downgrade_clears_rows_before_restoring_required_columns(
    populated_0009: tuple[Path, str],
) -> None:
    db, url = populated_0009
    _migrate(url)
    with sqlite3.connect(db) as conn:
        conn.execute(
            f"insert into {_TABLE} (id, key_hash, prompt_hash, provider, model, response_json,"
            " response_size_bytes, created_at, updated_at, expires_at, hit_count)"
            " values (?, ?, ?, 'anthropic', 'anthropic/claude-haiku-4-5', '{}', 2,"
            " datetime('now'), datetime('now'), NULL, 0)",
            (str(uuid.uuid4()), "b" * 64, "q" * 64),
        )

    _downgrade(url, "0009_global_request_cache")

    with sqlite3.connect(db) as conn:
        columns = {row[1] for row in conn.execute(f"pragma table_info({_TABLE})")}
        row_count = conn.execute(f"select count(*) from {_TABLE}").fetchone()[0]
    assert row_count == 0
    assert {"account_id", "profile_name", "key_version", "response_ciphertext"} <= columns
    assert _indexes(db) == _LEGACY_INDEXES
