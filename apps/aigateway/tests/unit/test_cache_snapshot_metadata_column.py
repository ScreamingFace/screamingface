"""Standard cache-entry metadata — where the column sits and how it travels (OME-XXXX).

This module pins the SQL/column layer of the snapshot path only: the canonical column tuple,
the COPY-header validator's legacy tolerance, the merge/replace column lists, and the export
header. It deliberately never builds or parses a metadata block — that value object is a
different module's contract. What is pinned here is the COLUMN: it is last, it is nullable, it
survives a merge, and both archive layouts pass through the same loader entry point.

Scenario ids follow the PRD: S12 (legacy archive), S13 (old gateway), S20 (merge drop).
"""

from __future__ import annotations

import asyncio
import re
from io import BytesIO

import pytest

from aigateway.core.request_cache import snapshot
from aigateway.core.request_cache.bulk_loader import (
    _MERGE_INSERT_COLUMNS,
    _MERGE_SQL,
    _REPLACE_COLUMNS,
    _REPLACE_SQL,
    _copy_stream_into_staging,
)
from aigateway.core.request_cache.snapshot import (
    CANONICAL_COLUMNS,
    LEGACY_COLUMNS,
    CopyBlockSource,
    CopyHeaderMismatch,
)
from aigateway.core.request_cache.snapshot_export import _HEADER_LINE

_LEGACY_ROW = (
    b'uuid1\tk1\tp1\topenrouter\tm1\t{"v":1}\t7\t'
    b"2026-01-01 00:00:00+00\t2026-01-01 00:00:00+00\t\\N\t\\N\t0\n"
)


def _header(*columns: str) -> bytes:
    return f"COPY public.request_cache_entries ({', '.join(columns)}) FROM stdin;\n".encode()


def _dump(columns: tuple[str, ...], *rows: bytes) -> BytesIO:
    return BytesIO(_header(*columns) + b"".join(rows) + b"\\.\n")


def _listed(fragment: str) -> tuple[str, ...]:
    """The column names written in a comma-separated SQL column list."""
    return tuple(name.strip() for name in fragment.split(","))


def _set_clause() -> str:
    return _MERGE_SQL.split("DO UPDATE SET", 1)[1]


# --- A7: the canonical layout and its one tolerated predecessor ---------------------------------


def test_the_canonical_layout_gains_the_metadata_column_last() -> None:
    assert CANONICAL_COLUMNS[-1] == "metadata_json"
    assert LEGACY_COLUMNS == CANONICAL_COLUMNS[:-1]
    assert "metadata_json" not in LEGACY_COLUMNS


def test_a_legacy_twelve_column_archive_header_is_accepted() -> None:
    # S12: an archive written before this feature must still restore.
    source = CopyBlockSource(_dump(LEGACY_COLUMNS, _LEGACY_ROW))
    assert source.header() == LEGACY_COLUMNS


def test_a_thirteen_column_header_in_another_order_is_still_refused() -> None:
    # S13 stays loud: tolerance is exactly one extra layout, not "any 13 columns".
    shuffled = (CANONICAL_COLUMNS[0], *CANONICAL_COLUMNS[2:], CANONICAL_COLUMNS[1])
    source = CopyBlockSource(_dump(shuffled, _LEGACY_ROW))
    with pytest.raises(CopyHeaderMismatch) as refusal:
        source.header()
    assert refusal.value.columns == shuffled


def test_a_gateway_knowing_only_the_legacy_layout_refuses_the_new_archive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # S13: the archive-side half of the compatibility matrix. A pre-change gateway accepted
    # exactly LEGACY_COLUMNS; constrained to that, the new 13-column header must raise rather
    # than be reinterpreted. Pinned here instead of against a copy of the old code.
    monkeypatch.setattr(snapshot, "ACCEPTED_COLUMN_LAYOUTS", (LEGACY_COLUMNS,))
    source = CopyBlockSource(_dump(CANONICAL_COLUMNS, _LEGACY_ROW + b"\t{}\n"))
    with pytest.raises(CopyHeaderMismatch) as refusal:
        source.header()
    assert refusal.value.columns == CANONICAL_COLUMNS


# --- A7/A8: the column reaches the staging twins and the live table ------------------------------


class _RecordingCopyClient:
    """The one asyncpg surface the staging copy drives, recording its column list."""

    def __init__(self) -> None:
        self.columns: tuple[str, ...] | None = None
        self.rows = 0

    async def copy_to_table(
        self,
        table_name: str,
        *,
        source: object,
        columns: tuple[str, ...] | None = None,
        timeout: float | None = None,
    ) -> str:
        self.columns = tuple(columns) if columns is not None else None
        self.rows = 0
        async for chunk in source:  # type: ignore[union-attr]
            self.rows += chunk.count(b"\n")
        return f"COPY {self.rows}"


@pytest.mark.asyncio
async def test_a_legacy_archive_is_copied_over_only_its_own_columns() -> None:
    # S12: naming 12 columns leaves metadata_json at its default, which is NULL — the row is
    # loaded honestly rather than padded with a fabricated block.
    client = _RecordingCopyClient()
    source = CopyBlockSource(_dump(LEGACY_COLUMNS, _LEGACY_ROW))
    columns = await asyncio.to_thread(source.header)
    rows = await _copy_stream_into_staging(client, source, columns=columns)
    assert client.rows == rows == 1
    assert client.columns == LEGACY_COLUMNS


@pytest.mark.asyncio
async def test_the_current_archive_is_copied_over_all_thirteen_columns() -> None:
    client = _RecordingCopyClient()
    row = _LEGACY_ROW[:-1] + b"\t{}\n"
    source = CopyBlockSource(_dump(CANONICAL_COLUMNS, row))
    columns = await asyncio.to_thread(source.header)
    await _copy_stream_into_staging(client, source, columns=columns)
    assert client.columns == CANONICAL_COLUMNS


# --- A8: the merge and replace paths -------------------------------------------------------------


def test_every_loader_column_list_carries_the_metadata_column() -> None:
    assert _listed(_MERGE_INSERT_COLUMNS) == CANONICAL_COLUMNS
    assert _listed(_REPLACE_COLUMNS) == CANONICAL_COLUMNS
    assert "s.metadata_json" in _MERGE_SQL
    assert "metadata_json" in _REPLACE_SQL


def test_the_merge_keeps_the_snapshot_metadata_on_conflict() -> None:
    # S20: metadata_json is content, like response_json. Without this assignment a restore
    # silently drops every block the snapshot carried.
    assert re.search(r"metadata_json\s*=\s*EXCLUDED\.metadata_json", _set_clause())


def test_the_merge_still_never_updates_identity_or_serving_history() -> None:
    # F11: id, created_at, hit_count and last_hit_at must stay out of the SET clause; the
    # metadata column is added WITHOUT reopening that decision.
    for column in ("id", "created_at", "hit_count", "last_hit_at"):
        assert not re.search(rf"^\s*{column}\s*=", _set_clause(), re.MULTILINE), column


# --- A7: the export derives the header from the canonical layout ---------------------------------


def test_the_export_header_lists_the_canonical_columns_with_metadata_last() -> None:
    assert _HEADER_LINE.startswith("COPY public.request_cache_entries (")
    assert _HEADER_LINE.endswith(") FROM stdin;\n")
    listed = _HEADER_LINE.split("(", 1)[1].split(")", 1)[0]
    assert _listed(listed) == CANONICAL_COLUMNS
