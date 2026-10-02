"""Bind a rebuildable SQLite projection to both its raw source and published bytes."""

import hashlib
import json
import sqlite3
from contextlib import closing
from itertools import zip_longest
from pathlib import Path

from screamingface._results.store import atomic_json


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def reusable(target: Path, source_digest: str) -> bool:
    try:
        value = json.loads(target.with_suffix(".index.json").read_text())
        return value == {
            "version": 1,
            "source_sha256": source_digest,
            "index_sha256": digest(target),
        }
    except (OSError, ValueError):
        # WHY: a missing or damaged derivative is rebuilt; raw integrity is checked upstream.
        return False


def publish(target: Path, source_digest: str, index_digest: str) -> None:
    # INVARIANT: the receipt describes the temporary index that was actually built,
    # never a concurrently replaced target. Interrupted publication forces a rebuild.
    atomic_json(
        target.with_suffix(".index.json"),
        {
            "version": 1,
            "source_sha256": source_digest,
            "index_sha256": index_digest,
        },
    )


def matches(expected: Path, target: Path) -> bool:
    """Compare read-only legacy projections with a freshly built disk projection."""
    try:
        with (
            closing(sqlite3.connect(expected)) as fresh,
            closing(sqlite3.connect(target.resolve().as_uri() + "?mode=ro", uri=True)) as cached,
        ):
            fresh.execute("PRAGMA cache_size=-2048")
            cached.execute("PRAGMA cache_size=-2048")
            for table, columns, order in (
                ("cases", "position,id,body", "position"),
                ("metadata", "body", "rowid"),
                ("case_stats", "gradeable", "rowid"),
                ("case_failures", "position,body", "position"),
            ):
                exists = cached.execute(
                    "SELECT name FROM sqlite_master WHERE name=?", (table,)
                ).fetchone()
                if not exists and table in {"case_stats", "case_failures"}:
                    continue  # WHY: legacy readers derive these optional tables from cases.
                query = f"SELECT {columns} FROM {table} ORDER BY {order}"
                # INVARIANT: compare at most one row per index in memory, including bodies.
                if any(a != b for a, b in zip_longest(fresh.execute(query), cached.execute(query))):
                    return False
            return True
    except sqlite3.Error:
        return False
