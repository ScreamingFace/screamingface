"""Slicing evidence for the cache-snapshot loader (OME-952).

The slicer is the trust boundary of the whole feature: everything downstream (staging COPY,
merge SQL) consumes what these functions yield. Pinned here — the header is recognised by
shape and column layout, data lines pass through byte-identical, the terminator ends the
block, and the epilogue never yields. A hand-made hostile "dump" whose epilogue carries SQL
reaches the loader as nothing at all.
"""

from __future__ import annotations

import gzip
from io import BytesIO

import pytest

from aigateway.core.request_cache.snapshot import (
    CANONICAL_COLUMNS,
    CopyBlockSource,
    CopyHeaderMismatch,
    NoCopyBlock,
    SnapshotManifest,
    open_snapshot_stream,
    parse_manifest,
)

_HEADER_LINE = (
    "COPY public.request_cache_entries (" + ", ".join(CANONICAL_COLUMNS) + ") FROM stdin;\n"
)


def _dump(*rows: bytes, header: str = _HEADER_LINE, epilogue: bytes = b"") -> BytesIO:
    return BytesIO(
        b"--\n-- Name: request_cache_entries; Type: TABLE DATA\n--\n\n"
        + header.encode()
        + b"".join(rows)
        + b"\\.\n"
        + epilogue
    )


def test_header_returns_the_canonical_columns() -> None:
    source = CopyBlockSource(_dump(b"one row\n"))
    assert source.header() == CANONICAL_COLUMNS


def test_a_dump_for_a_different_table_has_no_block() -> None:
    source = CopyBlockSource(BytesIO(b"COPY public.other_table (id) FROM stdin;\n1\n\\.\n"))
    with pytest.raises(NoCopyBlock):
        source.header()


def test_a_column_layout_that_is_not_ours_is_refused_not_reinterpreted() -> None:
    reordered = ", ".join((CANONICAL_COLUMNS[1], CANONICAL_COLUMNS[0], *CANONICAL_COLUMNS[2:]))
    source = CopyBlockSource(
        _dump(b"row\n", header=f"COPY public.request_cache_entries ({reordered}) FROM stdin;\n")
    )
    with pytest.raises(CopyHeaderMismatch):
        source.header()


def test_data_lines_pass_through_byte_identical_and_stop_at_the_terminator() -> None:
    # A payload with every COPY text escape: tab, newline, backslash, quotes, unicode, and
    # the NULL marker \N in a nullable column. None of it may be touched. Built as str and
    # encoded once: a real tab separates columns, two-character escapes travel as written.
    row_text = (
        'uuid1\tk1\tp1\topenrouter\tm1\t{\\n  "a": "x\\\\y\\t"}\t123\t'
        "2026-01-01 00:00:00+00\t2026-01-01 00:00:00+00\t\\N\t\\N\t0\n"
    )
    row = row_text.encode()
    hostile_epilogue = (
        b"\n\n--\n-- Name: request_cache_entries_pkey; Type: CONSTRAINT\n--\n"
        b"ALTER TABLE ONLY public.request_cache_entries ADD CONSTRAINT pkey PRIMARY KEY (id);\n"
    )
    source = CopyBlockSource(_dump(row, b"uuid2\tk2\\t\\N\n", epilogue=hostile_epilogue))
    source.header()
    lines = list(source.data_lines())
    assert lines == [row, b"uuid2\tk2\\t\\N\n"]


def test_a_final_line_without_a_newline_is_terminated() -> None:
    # pg_dump always terminates rows; hand input might not. The COPY wire format needs row
    # separators, so the slicer supplies the missing one and nothing else.
    stream = BytesIO(_HEADER_LINE.encode() + b"uuid1\tk1" + b"\n\\.\n")
    source = CopyBlockSource(stream)
    source.header()
    assert list(source.data_lines()) == [b"uuid1\tk1\n"]


def test_an_empty_table_yields_no_lines() -> None:
    source = CopyBlockSource(_dump())
    source.header()
    assert list(source.data_lines()) == []


def test_open_snapshot_stream_detects_gzip_by_magic_not_name(tmp_path) -> None:
    payload = _HEADER_LINE.encode() + b"\\.\n"
    gz = tmp_path / "snapshot.sql.gz"
    gz.write_bytes(gzip.compress(payload))
    plain = tmp_path / "snapshot.sql"
    plain.write_bytes(payload)

    with open_snapshot_stream(gz) as stream:
        assert stream.read() == payload
    with open_snapshot_stream(plain) as stream:
        assert stream.read() == payload


# --- manifest -----------------------------------------------------------------------------------


def _manifest_dict(**overrides: object) -> dict:
    base = {
        "schema": "screamingface.cache-snapshot.v1",
        "generated_at": "2026-08-22",
        "row_count": 197130,
        "sha256": "a" * 64,
        "revisions": {"parameter_contract": "aigw-parameter-contract-2026-08b"},
    }
    base.update(overrides)
    return base


def test_a_valid_manifest_parses() -> None:
    manifest = parse_manifest(
        b'{"schema": "screamingface.cache-snapshot.v1", "generated_at": "2026-08-22",'
        b' "row_count": 12, "sha256": "' + b"f" * 64 + b'",'
        b' "revisions": {"parameter_contract": "x"}}'
    )
    assert manifest.row_count == 12
    assert isinstance(manifest, SnapshotManifest)


@pytest.mark.parametrize(
    "overrides",
    [
        {"schema": "screamingface.cache-snapshot.v2"},
        {"row_count": -1},
        {"sha256": "XYZ"},  # not hex, wrong length
        {"sha256": "A" * 64},  # uppercase is not the digest form
        {"revisions": {}},
        {"revisions": {"k": 1}},
    ],
)
def test_a_manifest_that_lies_about_its_shape_is_invalid(overrides: dict) -> None:
    import json

    with pytest.raises(ValueError):
        parse_manifest(json.dumps(_manifest_dict(**overrides)).encode())


def test_non_json_is_invalid() -> None:
    with pytest.raises(ValueError):
        parse_manifest(b"not json at all")


def test_batches_past_the_terminator_never_leak_the_epilogue() -> None:
    """Regression: the loader reads in batches; a fresh batch after the terminator must be
    empty, not the dump's epilogue (blank line + comments + `\\unrestrict` in pg_dump 18).
    Feeding the epilogue to COPY parsed its leading blank line as a row (empty uuid)."""
    from aigateway.core.request_cache.bulk_loader import _read_batch

    epilogue = b"\n\n-- PostgreSQL database dump complete\n--\n\n\\unrestrict tok123\n"
    source = CopyBlockSource(_dump(b"row-1\nrow-2\n", epilogue=epilogue))
    source.header()
    first = _read_batch(source)
    second = _read_batch(source)
    third = _read_batch(source)
    assert first == b"row-1\nrow-2\n"
    assert second == b""
    assert third == b""
