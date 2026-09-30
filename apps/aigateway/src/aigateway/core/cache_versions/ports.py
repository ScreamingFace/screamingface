"""The capture ports and value types (OME-1307, GW-capture).

FEATURE: OME-1307 (E14) - one traced chat call becomes one capture record that a sink stores.

INVARIANT: this module is a LEAF. It imports no Tortoise and nothing from ``plugins`` or ``routes``,
so the chat route and later units depend on the port and never on the adapter (contract C11 row 4).
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final, Literal, Protocol, get_args
from uuid import UUID

CaptureOutcome = Literal["hit", "stored", "unstored", "bypass", "version_hit", "error"]
CAPTURE_OUTCOMES: Final[frozenset[str]] = frozenset(get_args(CaptureOutcome))
# INVARIANT (CV-D8): only these outcomes keep the served body inline in the index row.
INLINE_OUTCOMES: Final[frozenset[str]] = frozenset({"unstored", "bypass", "version_hit"})


@dataclass(frozen=True, slots=True)
class CaptureKey:
    """The capture key of one call: the global cache key hash and its canonical material."""

    key_hash: str  # 64 lowercase hex; equals the global cache key for the same body
    material: str  # the canonical key material (prompt text). Never logged. Never in a repr.

    def __repr__(self) -> str:
        # INVARIANT: the material holds the prompt verbatim, so a repr shows a hash prefix only.
        return f"CaptureKey(key_hash={self.key_hash[:12]}…)"


@dataclass(frozen=True, slots=True)
class CaptureRecord:
    account_id: str
    trace_id: str  # 32 lowercase hex
    outcome: CaptureOutcome
    key_hash: str | None  # None only when the call has no capture key
    request_material: str | None  # None exactly when key_hash is None
    response_json: str | None  # compact JSON text; set only for INLINE_OUTCOMES with a key


class CaptureSink(Protocol):
    async def record(self, record: CaptureRecord) -> None:
        """Store one record. May raise; the route helper owns the never-raise rule."""
        ...


# --- FEATURE: OME-1307 (E14, GW-freeze) - freeze a traced run, sign a receipt, archive it --------

CoverageStatus = Literal["complete", "partial"]


class TraceNotCaptured(LookupError):
    """The account has no capture row for this trace. Maps to ``404 trace_not_captured``."""


class CacheVersionTooLarge(ValueError):
    """A freeze would pass a cap. Maps to ``413 cache_version_too_large``."""

    def __init__(self, limit: Literal["entries", "archive_bytes"]) -> None:
        super().__init__(f"cache version is too large: {limit} cap exceeded")
        self.limit = limit


class VersionAlreadyExists(Exception):
    """The adapter lost the unique-version race. The service re-reads the winner."""


class ArchiveTooLarge(ValueError):
    """The compressed archive passed its byte cap. Raised by the archive sink."""


class ArchiveStoreError(RuntimeError):
    """A bucket or directory write failed. The message never carries a credential."""


@dataclass(frozen=True, slots=True)
class ReceiptClaims:
    sub: str
    vid: UUID
    tid: str
    sha: str
    n: int
    c: int
    cov: CoverageStatus


class ReceiptSigner(Protocol):
    @property
    def kid(self) -> str: ...

    def sign(self, claims: ReceiptClaims) -> str: ...


@dataclass(frozen=True, slots=True)
class CaptureRow:
    ordinal: int
    key_hash: str | None
    outcome: str
    response_json: str | None


@dataclass(frozen=True, slots=True)
class LiveAnswer:
    response_json: str
    metadata_json: str | None


@dataclass(frozen=True, slots=True)
class StoredVersion:
    id: UUID
    owner_account_id: str
    trace_id: str
    status: str
    entry_count: int
    call_count: int
    missing_count: int
    coverage_status: CoverageStatus
    archive_sha256: str
    archive_key: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class NewBlob:
    sha256: str
    request_json: str
    response_json: str
    metadata_json: str | None
    size_bytes: int


@dataclass(frozen=True, slots=True)
class NewEntry:
    key_hash: str
    blob_sha256: str  # a value field; the database column is `blob_id` (D8)
    first_ordinal: int


@dataclass(frozen=True, slots=True)
class CanonicalJson:
    """JSON that is already canonical text, so the archive writer splices it without a parse.

    INVARIANT: NOT a ``str`` subclass. ``canonical_material`` must raise on it and never quote it
    as a string value. The text is a body or an answer, so a repr shows its length only.
    """

    text: str

    def __repr__(self) -> str:
        return f"CanonicalJson(<{len(self.text)} chars>)"


@dataclass(frozen=True, slots=True)
class ArchiveEntry:
    """One archive entry. ``request``, ``response`` and ``metadata`` take TWO forms.

    A JSON value (the writer renders it), or a `CanonicalJson` (the writer splices its text, which
    MUST be `canonical_material` output). ``metadata`` is ``None`` when the blob has none.
    """

    key_hash: str
    first_ordinal: int
    request: Any
    response: Any
    metadata: Any | None


class FreezeStore(Protocol):
    async def find_version(self, owner_account_id: str, trace_id: str) -> StoredVersion | None: ...

    async def load_capture(self, account_id: str, trace_id: str) -> list[CaptureRow]:
        """The account's capture rows for the trace, ORDER BY ordinal."""
        ...

    async def load_prompts(self, key_hashes: Collection[str]) -> dict[str, str]:
        """key_hash -> request_json."""
        ...

    async def load_live_answers(self, key_hashes: Collection[str]) -> dict[str, LiveAnswer]: ...

    async def load_blob_metadata(self, shas: Collection[str]) -> dict[str, str | None]:
        """Existing blobs only: sha256 -> metadata_json."""
        ...

    async def insert_version(
        self, version: StoredVersion, blobs: Sequence[NewBlob], entries: Sequence[NewEntry]
    ) -> None:
        """Insert all three in one transaction. Raises VersionAlreadyExists on the unique race."""
        ...


class ExportStore(Protocol):
    async def list_frozen(self, limit: int, exclude: Collection[UUID] = ()) -> list[StoredVersion]:
        """Versions with status ``frozen`` and an id not in ``exclude``, ORDER BY created_at."""
        ...

    async def count_frozen(self) -> int: ...

    async def load_archive_entries(self, version_id: UUID) -> list[ArchiveEntry]:
        """The version's entries, ORDER BY first_ordinal.

        ``request``, ``response`` and ``metadata`` are each a JSON value OR a `CanonicalJson`
        (stored columns are canonical text, so an adapter may return them unparsed).
        """
        ...

    async def mark_archived(self, version_id: UUID) -> None:
        """UPDATE ... WHERE status = 'frozen'."""
        ...


class VersionArchiveStore(Protocol):
    async def put_once(
        self, key: str, path: Path, *, sha256_hex: str
    ) -> Literal["written", "exists"]: ...


@dataclass(frozen=True, slots=True)
class FreezeResult:
    created: bool
    version_id: UUID
    entry_count: int
    call_count: int
    missing_count: int
    coverage_status: CoverageStatus
    archive_sha256: str
    receipt: str


class CacheVersionFreezer(Protocol):
    async def freeze(self, *, account_id: str, subject: str, trace_id: str) -> FreezeResult: ...
