"""The pure canonical archive writer and manifest (OME-1307, GW-freeze; erd 3.5, contract C8a).

FEATURE: OME-1307 (E14) - a frozen version is archived as ``entries.jsonl.gz`` plus
``manifest.json``. The bytes are canonical, so the same version always gives the same sha256.

INVARIANT: PURE. No clock, no I/O of its own (the caller gives the sink), no logging. The
canonical form is ``request_cache.canonical`` and no second form exists here (its docstring
says why).
"""

from __future__ import annotations

import gzip
import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC
from typing import Any, BinaryIO, Final
from uuid import UUID

from ..request_cache import global_keys
from ..request_cache.canonical import canonical_compose, canonical_material
from .ports import ArchiveEntry, ArchiveTooLarge, CanonicalJson, StoredVersion

ARCHIVE_SCHEMA: Final = "screamingface.cache-version.v1"
ENTRIES_OBJECT: Final = "entries.jsonl.gz"
MANIFEST_OBJECT: Final = "manifest.json"


def archive_prefix(version_id: UUID) -> str:
    return f"cache-versions/{version_id}/"


@dataclass(frozen=True, slots=True)
class ArchiveDigest:
    sha256: str  # of the COMPRESSED bytes (decided: D7, X-16)
    size_bytes: int


@dataclass(frozen=True, slots=True)
class CanonicalEntry:
    """One archive entry as canonical JSON TEXT, so the writers never parse or walk it again.

    INVARIANT: each text is `canonical_material` output (or a proven byte copy of it). The texts
    hold prompt and answer verbatim, so the repr never shows them.
    """

    key_hash: str
    first_ordinal: int
    request_json: str
    response_json: str
    metadata_json: str | None

    def __repr__(self) -> str:
        return f"CanonicalEntry(key_hash={self.key_hash[:12]}…, first_ordinal={self.first_ordinal})"


def blob_digest(request_json: str, response_json: str) -> str:
    """The blob sha256 of two canonical texts: the digest of ``{"request":..,"response":..}``."""
    material = canonical_compose({}, {"request": request_json, "response": response_json})
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _archive_line(entry: CanonicalEntry) -> str:
    """The canonical JSON line of one entry (no newline): the five keys, sorted."""
    values: dict[str, Any] = {"key_hash": entry.key_hash, "first_ordinal": entry.first_ordinal}
    rendered = {"request": entry.request_json, "response": entry.response_json}
    if entry.metadata_json is None:
        values["metadata"] = None
    else:
        rendered["metadata"] = entry.metadata_json
    return canonical_compose(values, rendered)


def _text(value: Any) -> str:
    return value.text if isinstance(value, CanonicalJson) else canonical_material(value)


def _as_canonical(entry: ArchiveEntry) -> CanonicalEntry:
    """``entry`` as texts: a `CanonicalJson` field is taken as is, a JSON value is rendered."""
    return CanonicalEntry(
        key_hash=entry.key_hash,
        first_ordinal=entry.first_ordinal,
        request_json=_text(entry.request),
        response_json=_text(entry.response),
        metadata_json=None if entry.metadata is None else _text(entry.metadata),
    )


def blob_sha256(request: Any, response: Any) -> str:
    # Kept for existing tests: production code uses `blob_digest` on texts it already holds.
    return blob_digest(_text(request), _text(response))


class _Tee:
    """A write-only file that hashes and counts every compressed byte, and forwards it if asked.

    AIDEV-NOTE: it never raises on the cap. ``GzipFile`` writes its trailer again inside
    ``close()``, so a raise from here would fire twice. ``_write_lines`` reads ``total`` after
    each line instead.
    """

    def __init__(self, sink: BinaryIO | None) -> None:
        self._sink = sink
        self._digest = hashlib.sha256()
        self.total = 0

    def write(self, data: bytes) -> int:
        self._digest.update(data)
        self.total += len(data)
        if self._sink is not None:
            self._sink.write(data)
        return len(data)

    def flush(self) -> None:
        if self._sink is not None:
            self._sink.flush()

    @property
    def hexdigest(self) -> str:
        return self._digest.hexdigest()


def _order(entry: ArchiveEntry | CanonicalEntry) -> tuple[int, str]:
    return (entry.first_ordinal, entry.key_hash)


def _write_lines(lines: Iterable[str], sink: BinaryIO | None, *, max_bytes: int) -> ArchiveDigest:
    """Write the lines into one gzip stream, one at a time.

    ``lines`` is consumed lazily, so the rendered lines of a whole version never exist at once.
    Raises ``ArchiveTooLarge`` when the compressed size passes ``max_bytes``.
    """
    tee = _Tee(sink)
    gz = gzip.GzipFile(filename="", mode="wb", fileobj=tee, compresslevel=9, mtime=0)
    try:
        for line in lines:
            gz.write(f"{line}\n".encode())
            if tee.total > max_bytes:
                raise ArchiveTooLarge(f"the archive passed {max_bytes} compressed bytes")
    finally:
        gz.close()
    if tee.total > max_bytes:
        raise ArchiveTooLarge(f"the archive passed {max_bytes} compressed bytes")
    return ArchiveDigest(sha256=tee.hexdigest, size_bytes=tee.total)


def write_canonical(
    entries: Iterable[CanonicalEntry], sink: BinaryIO | None, *, max_bytes: int
) -> ArchiveDigest:
    """Write the entries as canonical JSON lines into one gzip stream, with no parse or walk.

    ``sink=None`` only hashes and counts (what the freeze uses). Raises ``ArchiveTooLarge`` when
    the compressed size passes ``max_bytes``.

    INVARIANT: the bytes depend on the entries only, never on their input order: the sort key is
    ``(first_ordinal, key_hash)``, and gzip has ``mtime=0``, no file name and level 9. The sort
    runs on the entries BEFORE any line is rendered.
    """
    ordered = sorted(entries, key=_order)
    return _write_lines((_archive_line(entry) for entry in ordered), sink, max_bytes=max_bytes)


def write_entries(
    entries: Iterable[ArchiveEntry], sink: BinaryIO | None, *, max_bytes: int
) -> ArchiveDigest:
    """`write_canonical` over entries that hold JSON values or `CanonicalJson` (same bytes)."""
    ordered = sorted(entries, key=_order)
    return _write_lines(
        (_archive_line(_as_canonical(entry)) for entry in ordered), sink, max_bytes=max_bytes
    )


def manifest_bytes(version: StoredVersion) -> bytes:
    """The ``manifest.json`` bytes of erd 3.5: the eleven keys, canonical, no trailing newline."""
    return canonical_material(
        {
            "schema": ARCHIVE_SCHEMA,
            "version_id": str(version.id),
            "trace_id": version.trace_id,
            "created_at": version.created_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "entry_count": version.entry_count,
            "call_count": version.call_count,
            "missing_count": version.missing_count,
            "coverage_status": version.coverage_status,
            "entries_sha256": version.archive_sha256,
            "parameter_contract_revision": global_keys.PARAMETER_CONTRACT_REVISION,
            "key_revision": global_keys.KEY_REVISION,
        }
    ).encode("utf-8")
