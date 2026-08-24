"""Slice a ``snapshot-cache`` pg_dump down to its COPY block (OME-952).

A snapshot is a gzip'd single-table ``pg_dump`` of ``public.request_cache_entries``: a fixed
prologue, one ``COPY ... FROM stdin;`` header, the rows in COPY text format, a ``\\.`` terminator,
and a fixed epilogue. The loader (see :mod:`.bulk_loader`) re-feeds exactly the row lines to
Postgres through its own COPY protocol, which is why this module works at the BYTE level and
never decodes a value: a value may contain any byte the dump format escapes, and the only
guarantee that survives a decode/re-encode round trip is the one we never make.

INVARIANT — nothing here parses SQL. The header is recognised by shape, the data lines are
yielded verbatim, and the epilogue (``CREATE TABLE``, indexes, constraints) is discarded
unread. The dump's own DDL must never reach the server through this path.
"""

from __future__ import annotations

import gzip
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO, Final

from pydantic import BaseModel, Field, field_validator

# The table's column order, as pg_dump writes it — which is the DATABASE's column order, pinned
# by the migrations and verified against a live deployment (OME-952 plan). The loader feeds
# ``copy_to_table`` with THIS tuple, so no upload-derived identifier ever reaches a COPY
# command; a dump whose header disagrees is refused rather than re-interpreted.
CANONICAL_COLUMNS: Final[tuple[str, ...]] = (
    "id",
    "key_hash",
    "prompt_hash",
    "provider",
    "model",
    "response_json",
    "response_size_bytes",
    "created_at",
    "updated_at",
    "expires_at",
    "last_hit_at",
    "hit_count",
)

_TABLE_NAME: Final = "request_cache_entries"
_HEADER_PREFIX: Final = f"COPY public.{_TABLE_NAME} (".encode()
_HEADER_SUFFIX: Final = b" FROM stdin;"
_GZIP_MAGIC: Final = b"\x1f\x8b"


class NoCopyBlock(ValueError):
    """The stream contains no COPY block for the request-cache table."""


class CopyHeaderMismatch(ValueError):
    """A COPY block was found but its column layout is not this gateway's."""

    def __init__(self, columns: tuple[str, ...]) -> None:
        self.columns = columns
        super().__init__(
            f"the snapshot's COPY header lists {len(columns)} column(s) in an order this "
            "gateway does not share; the rows could not be loaded honestly"
        )


def open_snapshot_stream(path: Path) -> BinaryIO:
    """Open a snapshot for reading, transparently gunzipping when the magic bytes say so.

    ``snapshot-cache`` writes gzip; a plain ``pg_dump`` output is accepted too because the
    bytes are indistinguishable to every later stage — detection by magic, never by filename.
    """
    raw = path.open("rb")
    try:
        head = raw.read(2)
        raw.seek(0)
        if head == _GZIP_MAGIC:
            return gzip.open(raw, "rb")  # type: ignore[return-value]
        return raw
    except Exception:
        raw.close()
        raise


class CopyBlockSource:
    """Line-level cursor over one dump's COPY block.

    :meth:`header` scans forward to the ``COPY public.request_cache_entries (...) FROM stdin;``
    line and returns its column list — parsed from the HEADER only, which pg_dump generates
    from the table definition, never from row data. :meth:`data_lines` then yields the row
    lines up to the ``\\.`` terminator, newline-terminated, bytes verbatim.
    """

    def __init__(self, stream: BinaryIO) -> None:
        self._lines: Iterator[bytes] = iter(stream)
        self._block_exhausted = False

    def header(self) -> tuple[str, ...]:
        for line in self._lines:
            if not line.startswith(_HEADER_PREFIX):
                continue
            clean = line.rstrip(b"\r\n")
            if not clean.endswith(_HEADER_SUFFIX):
                # A COPY line for our table that is not a data header (e.g. a comment quoting
                # one) is not something pg_dump produces; treat it as an unrecognised shape.
                continue
            body = clean[len(_HEADER_PREFIX) : -len(_HEADER_SUFFIX)]
            if not body.endswith(b")"):
                raise CopyHeaderMismatch(())  # pragma: no cover - hand-crafted input only
            body = body[:-1]
            try:
                columns = tuple(name.strip() for name in body.decode("ascii").split(","))
            except UnicodeDecodeError as exc:  # pragma: no cover - hand-crafted input only
                raise CopyHeaderMismatch(()) from exc
            if any(not name for name in columns):
                raise CopyHeaderMismatch(columns)
            if columns != CANONICAL_COLUMNS:
                raise CopyHeaderMismatch(columns)
            return columns
        raise NoCopyBlock(f"no COPY block for public.{_TABLE_NAME} in the snapshot")

    def data_lines(self) -> Iterator[bytes]:
        """Yield COPY data lines, each newline-terminated, through the ``\\.`` terminator.

        A raw newline can never occur INSIDE a COPY text value (newlines are escaped as
        ``\\n`` by the dump), so splitting on ``b"\\n"`` splits rows exactly. The terminator
        itself is consumed and not yielded. pg_dump always terminates rows with a newline;
        a final line without one (hand-made input) is terminated here, because the COPY wire
        format needs row separators.

        LATCHED CLOSED: the loader reads this in BATCHES, and a batch boundary can fall past
        the terminator. A fresh call here must never resume into the dump's epilogue (pg_dump
        18 even appends ``\\unrestrict`` directives there) — those lines are not data, and
        feeding them to COPY was a real defect: the epilogue's leading blank line parsed as
        a row whose first field was empty. After the terminator, this yields nothing.
        """
        if self._block_exhausted:
            return
        for line in self._lines:
            if line.rstrip(b"\r\n") == b"\\.":
                self._block_exhausted = True
                return
            yield line if line.endswith(b"\n") else line + b"\n"


class SnapshotManifest(BaseModel):
    """The sidecar ``snapshot-cache`` emits beside the archive (OME-954's contract).

    Present ⇒ the loader can PROVE the rows were keyed by the same revision constants this
    gateway hashes with. Absent ⇒ the load proceeds with ``revisions_unverified`` — an honest
    warning, not a refusal, because snapshots taken before manifests existed are still valid
    dumps of this table.
    """

    schema: str  # noqa: A003 - the manifest's own field name
    generated_at: str
    row_count: int = Field(ge=0)
    sha256: str
    revisions: dict[str, str]

    @field_validator("schema")
    @classmethod
    def _known_schema(cls, value: str) -> str:
        if value != "screamingface.cache-snapshot.v1":
            raise ValueError(f"unknown manifest schema: {value!r}")
        return value

    @field_validator("sha256")
    @classmethod
    def _hex_digest(cls, value: str) -> str:
        if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("sha256 must be a 64-character lowercase hex digest")
        return value

    @field_validator("revisions")
    @classmethod
    def _nonempty(cls, value: dict[str, str]) -> dict[str, str]:
        if not value:
            raise ValueError("revisions must name at least one constant")
        return value


def parse_manifest(raw: bytes) -> SnapshotManifest:
    """Strict parse: any shape or content problem raises ``ValueError``.

    The manifest is operator-supplied input, so it is validated as hard as the rows are: a
    manifest that lies about its own checksum or row count must be refused as ``manifest_invalid``
    rather than silently downgrade the verification it exists to provide.
    """
    from pydantic import ValidationError

    try:
        return SnapshotManifest.model_validate_json(raw)
    except ValidationError as exc:
        raise ValueError(f"manifest is not a valid cache-snapshot v1 document: {exc}") from exc


def digest_matches(actual_hex: str, manifest: SnapshotManifest) -> bool:
    return actual_hex == manifest.sha256


__all__ = [
    "CANONICAL_COLUMNS",
    "CopyBlockSource",
    "CopyHeaderMismatch",
    "NoCopyBlock",
    "SnapshotManifest",
    "digest_matches",
    "open_snapshot_stream",
    "parse_manifest",
]
