"""Byte-emitter tests for the cache-snapshot exporter (OME-1021).

The exporter is the trust boundary of the weekly archive: everything downstream — the
existing OME-952 loader, `restore-cache`, any future restore path — consumes what this
module emits. These tests pin the loader contract (header lists `CANONICAL_COLUMNS`
verbatim, rows pass through byte-identical, the `\\.` terminator ends the block), and the
manifest's honesty: `row_count` and `sha256` are the real ones, `revisions` are stamped
from the injected source, and a failed export leaves no spool behind.
"""

from __future__ import annotations

import gzip
import hashlib
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aigateway.core.request_cache.snapshot import (
    CANONICAL_COLUMNS,
    CopyBlockSource,
    digest_matches,
    open_snapshot_stream,
    parse_manifest,
)
from aigateway.core.request_cache.snapshot_export import (
    CacheSnapshotExporter,
    SnapshotExportCopyFailed,
    SnapshotExportDatabaseUnavailable,
    SnapshotExportSpoolExceeded,
    SnapshotExportUnsupportedDatabase,
    postgres_connect,
)

_HEADER_LINE = (
    "COPY public.request_cache_entries (" + ", ".join(CANONICAL_COLUMNS) + ") FROM stdin;\n"
)

_STAMP = datetime(2026, 8, 28, 5, 0, 0, tzinfo=UTC)

# Two COPY-text rows (what a real server emits), including a response whose JSON embeds
# backslashes and an escaped newline — the loader must receive these bytes unchanged.
_ROW_ONE = (
    b"\t".join(
        [
            b"0a0a0a0a-0a0a-4a0a-8a0a-0a0a0a0a0a0a",
            b"a" * 64,
            b"b" * 64,
            b"openrouter",
            b"openrouter/anthropic/claude-opus-4.8",
            b'{"choices":[{"message":{"content":"hi"}}]}',
            b"38",
            b"2026-08-26 05:00:00.123456+00",
            b"2026-08-26 05:00:00.123456+00",
            b"\\N",
            b"\\N",
            b"3",
        ]
    )
    + b"\n"
)

_ROW_2 = (
    b"\t".join(
        [
            b"0b0b0b0b-0b0b-4b0b-8b0b-0b0b0b0b0b0b",
            b"c" * 64,
            b"d" * 64,
            b"openrouter",
            b"openrouter/google/gemini-3.1-pro-preview",
            b'{"msg":"a\\\\b\\nc"}',  # backslashes + escaped newline, pre-escaped by the server
            b"19",
            b"2026-08-26 05:00:01.000000+00",
            b"2026-08-26 05:00:01.000000+00",
            b"\\N",
            b"2026-08-27 12:00:00+00",
            b"7",
        ]
    )
    + b"\n"
)

_REVISIONS = {"parameter_contract": "rev-param", "openrouter_adapter": "rev-or"}


class _FakeConnection:
    """A minimal stand-in for the asyncpg connection the exporter drives."""

    def __init__(self, chunks: list[bytes], status: str = "COPY 2") -> None:
        self._chunks = chunks
        self._status = status
        self.query: str | None = None
        self.closed = False

    async def copy_from_query(
        self,
        query: str,
        *,
        output: Callable[[bytes], Awaitable[None]],
        **_: object,
    ) -> str:
        self.query = query
        for chunk in self._chunks:
            await output(chunk)
        return self._status

    async def close(self) -> None:
        self.closed = True


def _exporter(
    tmp_path: Path,
    conn: _FakeConnection,
    *,
    max_bytes: int = 1 << 20,
) -> CacheSnapshotExporter:
    return CacheSnapshotExporter(
        lambda: _connect(conn),
        revisions=lambda: dict(_REVISIONS),
        now=lambda: _STAMP,
        spool_dir=str(tmp_path),
        max_bytes=max_bytes,
    )


async def _connect(conn: _FakeConnection) -> _FakeConnection:
    return conn


@pytest.mark.asyncio
async def test_the_archive_round_trips_through_the_existing_loader(tmp_path: Path) -> None:
    rows = [_ROW_ONE, _ROW_2]
    conn = _FakeConnection(rows)
    export = await _exporter(tmp_path, conn).export()

    # The loader's view: canonical header, rows byte-identical, terminates at `\.`.
    source = CopyBlockSource(open_snapshot_stream(export.archive_path))
    assert source.header() == CANONICAL_COLUMNS
    assert list(source.data_lines()) == rows

    # The archive is gzip with the fixed preamble/header/epilogue framing.
    decoded = gzip.decompress(export.archive_path.read_bytes())
    assert decoded.startswith(b"--\n-- ScreamingFace response-cache snapshot (data only)\n--")
    assert decoded.endswith(b"--\n-- ScreamingFace response-cache snapshot complete\n--\n")

    # The manifest is honest: schema, stamp, rows, checksum, revisions.
    manifest = parse_manifest(export.manifest_path.read_bytes())
    assert manifest.row_count == 2
    assert manifest.generated_at == "2026-08-28T05:00:00Z"
    assert manifest.sha256 == export.sha256_hex
    assert digest_matches(export.sha256_hex, manifest)
    assert hashlib.sha256(export.archive_path.read_bytes()).hexdigest() == export.sha256_hex
    assert manifest.revisions == _REVISIONS

    # The driver sent exactly the canonical-columns COPY SELECT, and closed the connection.
    assert conn.query == "SELECT " + ", ".join(CANONICAL_COLUMNS) + " FROM request_cache_entries"
    assert conn.closed

    # The object-storage naming stamp is path-safe and unique per run.
    assert export.stamp == "2026-08-28T05-00-00Z"
    assert export.archive_path.name == "2026-08-28T05-00-00Z.sql.gz"
    assert export.manifest_path.name == "2026-08-28T05-00-00Z.manifest.json"


@pytest.mark.asyncio
async def test_a_spool_over_the_cap_is_refused_and_removed(tmp_path: Path) -> None:
    conn = _FakeConnection([b"x" * 4096], status="COPY 1")
    exporter = _exporter(tmp_path, conn, max_bytes=16)

    with pytest.raises(SnapshotExportSpoolExceeded):
        await exporter.export()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_a_connect_failure_propagates_and_cleans_the_spool(tmp_path: Path) -> None:
    async def connect() -> _FakeConnection:
        raise SnapshotExportDatabaseUnavailable("boom")

    exporter = CacheSnapshotExporter(
        connect,
        revisions=lambda: dict(_REVISIONS),
        now=lambda: _STAMP,
        spool_dir=str(tmp_path),
    )

    with pytest.raises(SnapshotExportDatabaseUnavailable):
        await exporter.export()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_an_unparseable_copy_status_is_refused(tmp_path: Path) -> None:
    conn = _FakeConnection([], status="COPY nope")

    with pytest.raises(SnapshotExportCopyFailed):
        await _exporter(tmp_path, conn).export()


@pytest.mark.asyncio
async def test_postgres_connect_refuses_a_non_postgres_dsn() -> None:
    with pytest.raises(SnapshotExportUnsupportedDatabase):
        await postgres_connect("sqlite://./aigateway.sqlite3")
