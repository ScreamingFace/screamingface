"""CV-12: the archive bytes are canonical, deterministic, and hash to the recorded digest.

FEATURE: OME-1307 (E14) - the same frozen entries always give the same gzip bytes, so the
``archive_sha256`` of a version can be checked by anyone who reads the bucket object.
INVARIANT (decided: D7, X-16): the digest is the sha256 of the gzip bytes, ``mtime=0``, level 9.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import random
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from aigateway.core.cache_versions.archive import (
    ARCHIVE_SCHEMA,
    ENTRIES_OBJECT,
    MANIFEST_OBJECT,
    archive_prefix,
    blob_sha256,
    manifest_bytes,
    write_entries,
)
from aigateway.core.cache_versions.ports import ArchiveEntry, ArchiveTooLarge, StoredVersion
from aigateway.core.request_cache import global_keys
from aigateway.core.request_cache.canonical import canonical_digest, canonical_material

_TEXT = st.text(alphabet=st.characters(codec="utf-8"))
_JSON = st.recursive(
    st.none()
    | st.booleans()
    | st.integers(min_value=-(2**53), max_value=2**53)
    | st.floats(allow_nan=False, allow_infinity=False)
    | _TEXT,
    lambda children: st.lists(children, max_size=4) | st.dictionaries(_TEXT, children, max_size=4),
    max_leaves=12,
)
_ENTRIES = st.lists(
    st.builds(
        ArchiveEntry,
        key_hash=st.text(alphabet="0123456789abcdef", min_size=64, max_size=64),
        first_ordinal=st.integers(min_value=0, max_value=10_000),
        request=_JSON,
        response=_JSON,
        metadata=st.none() | _JSON,
    ),
    max_size=8,
    unique_by=lambda e: e.first_ordinal,
)


def _write(entries: list[ArchiveEntry], *, max_bytes: int = 10**9) -> tuple[bytes, Any]:
    buffer = io.BytesIO()
    digest = write_entries(entries, buffer, max_bytes=max_bytes)
    return buffer.getvalue(), digest


@settings(max_examples=60, deadline=None)
@given(entries=_ENTRIES, seed=st.integers(min_value=0, max_value=2**16))
def test_archive_bytes_are_canonical_and_hash_matches(
    entries: list[ArchiveEntry], seed: int
) -> None:
    first_bytes, first = _write(entries)
    second_bytes, second = _write(entries)
    shuffled = list(entries)
    random.Random(seed).shuffle(shuffled)
    shuffled_bytes, _ = _write(shuffled)

    assert first_bytes == second_bytes
    assert first.sha256 == second.sha256
    assert shuffled_bytes == first_bytes, "the input order must not change the bytes"
    assert hashlib.sha256(first_bytes).hexdigest() == first.sha256
    assert first.size_bytes == len(first_bytes)
    assert first_bytes[4:8] == b"\x00\x00\x00\x00", "the gzip header MTIME must be zero"
    text = gzip.decompress(first_bytes).decode("utf-8")
    lines = text.split("\n")
    assert lines.pop() == "", "every line, the last one too, ends with a newline"
    assert [json.loads(line)["first_ordinal"] for line in lines] == sorted(
        e.first_ordinal for e in entries
    )
    for line in lines:
        parsed = json.loads(line)
        assert list(parsed) == sorted(parsed), "keys are sorted"
        assert set(parsed) == {"key_hash", "first_ordinal", "request", "response", "metadata"}
        assert canonical_material(parsed) == line


def test_write_entries_without_a_sink_gives_the_same_digest() -> None:
    entries = [ArchiveEntry("a" * 64, 0, {"q": 1}, {"a": 2}, None)]
    _, with_sink = _write(entries)

    assert write_entries(entries, None, max_bytes=10**9) == with_sink


def test_archive_of_no_entries_is_a_valid_empty_gzip() -> None:
    data, digest = _write([])

    assert gzip.decompress(data) == b""
    assert digest.sha256 == hashlib.sha256(data).hexdigest()


def test_archive_cap_raises_archive_too_large() -> None:
    entries = [
        ArchiveEntry(f"{i:064x}", i, {"q": random.Random(i).random()}, {"a": "x" * 500}, None)
        for i in range(20)
    ]

    with pytest.raises(ArchiveTooLarge):
        write_entries(entries, None, max_bytes=64)


def test_archive_cap_is_also_checked_after_the_final_flush() -> None:
    # One small entry: the gzip header (10 bytes) is out before the entry, and the compressed body
    # and the trailer come out only when the stream closes. The cap must count those bytes too.
    entries = [ArchiveEntry("a" * 64, 0, {"q": 1}, {"a": "x" * 200}, None)]
    _, digest = _write(entries)
    assert digest.size_bytes > 30

    with pytest.raises(ArchiveTooLarge):
        write_entries(entries, None, max_bytes=30)
    assert write_entries(entries, None, max_bytes=digest.size_bytes) == digest


def test_blob_sha256_is_the_canonical_digest_of_request_and_response() -> None:
    assert blob_sha256({"b": 1, "a": [2]}, {"z": None}) == canonical_digest(
        {"request": {"a": [2], "b": 1}, "response": {"z": None}}
    )


def test_archive_prefix_names_the_version() -> None:
    vid = UUID("11111111-2222-4333-8444-555555555555")

    assert archive_prefix(vid) == f"cache-versions/{vid}/"
    assert (ENTRIES_OBJECT, MANIFEST_OBJECT) == ("entries.jsonl.gz", "manifest.json")


def test_manifest_has_the_eleven_keys_and_no_trailing_newline() -> None:
    vid = UUID("11111111-2222-4333-8444-555555555555")
    version = StoredVersion(
        id=vid,
        owner_account_id="acct",
        trace_id="ab" * 16,
        status="frozen",
        entry_count=2,
        call_count=3,
        missing_count=1,
        coverage_status="partial",
        archive_sha256="cd" * 32,
        archive_key=archive_prefix(vid),
        created_at=datetime(2026, 9, 29, 12, 30, 45, 999999, tzinfo=UTC),
    )

    data = manifest_bytes(version)

    assert not data.endswith(b"\n")
    parsed = json.loads(data)
    assert parsed == {
        "schema": ARCHIVE_SCHEMA,
        "version_id": str(vid),
        "trace_id": "ab" * 16,
        "created_at": "2026-09-29T12:30:45Z",
        "entry_count": 2,
        "call_count": 3,
        "missing_count": 1,
        "coverage_status": "partial",
        "entries_sha256": "cd" * 32,
        "parameter_contract_revision": global_keys.PARAMETER_CONTRACT_REVISION,
        "key_revision": global_keys.KEY_REVISION,
    }
    assert data.decode("utf-8") == canonical_material(parsed)
