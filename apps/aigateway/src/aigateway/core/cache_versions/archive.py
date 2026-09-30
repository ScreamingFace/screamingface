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
from ..request_cache.canonical import canonical_digest, canonical_material
from .ports import ArchiveEntry, ArchiveTooLarge, StoredVersion

ARCHIVE_SCHEMA: Final = "screamingface.cache-version.v1"
ENTRIES_OBJECT: Final = "entries.jsonl.gz"
MANIFEST_OBJECT: Final = "manifest.json"


def archive_prefix(version_id: UUID) -> str:
    return f"cache-versions/{version_id}/"


@dataclass(frozen=True, slots=True)
class ArchiveDigest:
    sha256: str  # of the COMPRESSED bytes (decided: D7, X-16)
    size_bytes: int


def blob_sha256(request: Any, response: Any) -> str:
    return canonical_digest({"request": request, "response": response})


class _Tee:
    """A write-only file that hashes and counts every compressed byte, and forwards it if asked.

    AIDEV-NOTE: it never raises on the cap. ``GzipFile`` writes its trailer again inside
    ``close()``, so a raise from here would fire twice. ``write_entries`` reads ``total`` after
    each entry instead.
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


def write_entries(
    entries: Iterable[ArchiveEntry], sink: BinaryIO | None, *, max_bytes: int
) -> ArchiveDigest:
    """Write the entries as canonical JSON lines into one gzip stream.

    ``sink=None`` only hashes and counts (what the freeze uses). Raises ``ArchiveTooLarge`` when
    the compressed size passes ``max_bytes``.

    INVARIANT: the bytes depend on the entries only, never on their input order: the sort key is
    ``(first_ordinal, key_hash)``, and gzip has ``mtime=0``, no file name and level 9.
    """
    tee = _Tee(sink)
    gz = gzip.GzipFile(filename="", mode="wb", fileobj=tee, compresslevel=9, mtime=0)
    try:
        for entry in sorted(entries, key=lambda e: (e.first_ordinal, e.key_hash)):
            line = canonical_material(
                {
                    "key_hash": entry.key_hash,
                    "first_ordinal": entry.first_ordinal,
                    "request": entry.request,
                    "response": entry.response,
                    "metadata": entry.metadata,
                }
            )
            gz.write(f"{line}\n".encode())
            if tee.total > max_bytes:
                raise ArchiveTooLarge(f"the archive passed {max_bytes} compressed bytes")
    finally:
        gz.close()
    if tee.total > max_bytes:
        raise ArchiveTooLarge(f"the archive passed {max_bytes} compressed bytes")
    return ArchiveDigest(sha256=tee.hexdigest, size_bytes=tee.total)


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
