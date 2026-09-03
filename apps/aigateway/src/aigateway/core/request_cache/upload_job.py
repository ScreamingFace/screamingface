"""The admin cache-upload job runner: one slot, owned task, honest records (OME-952).

The upload route spools the file synchronously (a Starlette ``UploadFile`` dies with its
request) and hands the PATH here; everything that can refuse a snapshot — checksum, row count,
revision mismatch, the replace guard — runs inside the job and lands as the terminal state
``refused`` with a machine code, because the upload itself was accepted (spec contract).

INVARIANTS
- ONE load job per process at a time; a second upload while one runs raises
  :class:`CacheUploadBusy`, which the route answers 409 (spec invariant 5).
- The spawned task is OWNED: the runner holds the reference for its lifetime, so the event
  loop's weak reference to nameless tasks cannot let it be collected mid-load.
- Job records live on ``app.state`` only — a restart forgets reports, never data (spec
  limitation, accepted). The durable truth is the table plus the audit log.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from .bulk_loader import (
    CacheUploadUnsupportedDatabase,
    LoadOutcome,
    ReplaceGuardBlocked,
    StagedRowCountMismatch,
    load_snapshot,
)
from .revisions import active_cache_revisions
from .snapshot import (
    CopyHeaderMismatch,
    NoCopyBlock,
    SnapshotManifest,
    digest_matches,
    parse_manifest,
)

MAX_UPLOAD_BYTES_DEFAULT = 256 * 1024 * 1024
_HISTORY_LIMIT = 50


class CacheUploadBusy(RuntimeError):
    """Another load job is running; only one may run per deployment at a time."""


# Refusal codes are API surface (the console renders them); new ones are additive.
REFUSAL_CODES = (
    "manifest_invalid",
    "checksum_mismatch",
    "revision_mismatch",
    "upload_too_large",
    "no_copy_block",
    "column_layout_mismatch",
    "row_count_mismatch",
    "newer_rows_would_be_lost",
    "unsupported_database",
)


@dataclass
class CacheJobRecord:
    """One load attempt's observable history. Serialized to ``AdminCacheJobOut``."""

    id: uuid.UUID
    actor: str
    mode: Literal["merge", "replace"]
    created_at: datetime
    state: str = "validating"
    finished_at: datetime | None = None
    staged_rows: int | None = None
    live_before: int | None = None
    live_after: int | None = None
    inserted_rows: int | None = None
    updated_rows: int | None = None
    manifest_present: bool = False
    forced: bool = False
    warnings: list[str] = field(default_factory=list)
    refusal: str | None = None
    error: str | None = None

    def out_counts(self, outcome: LoadOutcome) -> None:
        """Fill the counters from a finished load. Merge additionally splits inserted/updated.

        The split is derived from counts, not per-row RETURNING: ``inserted = live_after -
        live_before`` because merge only adds keys that were absent, and every other staged
        row landed on the update path. A concurrent delete between the two counts can blur
        the split by a row — the spec records it as best-effort, and it is.
        """
        self.staged_rows = outcome.staged_rows
        self.live_before = outcome.live_before
        self.live_after = outcome.live_after
        if self.mode == "merge":
            inserted = max(outcome.live_after - outcome.live_before, 0)
            self.inserted_rows = inserted
            self.updated_rows = max(outcome.staged_rows - inserted, 0)


Loader = Callable[..., Awaitable[LoadOutcome]]
RevisionSource = Callable[[], dict[str, str]]


@dataclass(frozen=True)
class UploadAcceptance:
    """What the route validated synchronously, passed to the runner as trusted input."""

    upload_path: Path
    sha256_hex: str
    actual_bytes: int
    manifest_raw: bytes | None
    mode: Literal["merge", "replace"]
    force: bool
    acknowledge_loss: bool
    actor: str


class CacheUploadRunner:
    """Runs cache-snapshot loads one at a time and remembers their records."""

    def __init__(
        self,
        *,
        loader: Loader = load_snapshot,
        revisions: RevisionSource = active_cache_revisions,
        max_upload_bytes: int = MAX_UPLOAD_BYTES_DEFAULT,
        history_limit: int = _HISTORY_LIMIT,
    ) -> None:
        self._loader = loader
        self._revisions = revisions
        self.max_upload_bytes = max_upload_bytes
        self._history_limit = history_limit
        self._jobs: deque[CacheJobRecord] = deque(maxlen=history_limit)
        self._task: asyncio.Task[None] | None = None

    # --- queries --------------------------------------------------------------------------------

    def jobs(self) -> list[CacheJobRecord]:
        return list(self._jobs)

    def get(self, job_id: uuid.UUID) -> CacheJobRecord | None:
        return next((job for job in self._jobs if job.id == job_id), None)

    def busy(self) -> bool:
        return self._task is not None and not self._task.done()

    # --- one load -------------------------------------------------------------------------------

    def start(self, acceptance: UploadAcceptance) -> CacheJobRecord:
        """Accept one upload and begin its load. Raises :class:`CacheUploadBusy` if occupied."""
        if self.busy():
            raise CacheUploadBusy("a cache snapshot load is already running on this gateway")
        record = CacheJobRecord(
            id=uuid.uuid4(),
            actor=acceptance.actor,
            mode=acceptance.mode,
            created_at=datetime.now(UTC),
        )
        self._jobs.append(record)
        # OWNED reference: kept on self until done, so the loop's weak task refs cannot
        # drop it mid-load. Exceptions never escape _run — it always reaches a terminal state.
        self._task = asyncio.create_task(self._run(record, acceptance))
        return record

    async def _run(self, record: CacheJobRecord, acceptance: UploadAcceptance) -> None:
        manifest: SnapshotManifest | None = None
        try:
            if acceptance.actual_bytes > self.max_upload_bytes:
                self._refuse(record, "upload_too_large")
                return

            if acceptance.manifest_raw is not None:
                record.manifest_present = True
                try:
                    manifest = parse_manifest(acceptance.manifest_raw)
                except ValueError as exc:
                    self._refuse(record, "manifest_invalid", detail=str(exc))
                    return
                if not digest_matches(acceptance.sha256_hex, manifest):
                    self._refuse(record, "checksum_mismatch")
                    return
                mismatched = {
                    name: {"manifest": value, "gateway": self._revisions().get(name)}
                    for name, value in manifest.revisions.items()
                    if self._revisions().get(name) != value
                }
                if mismatched:
                    if not acceptance.force:
                        self._refuse(record, "revision_mismatch", detail=str(mismatched))
                        return
                    record.forced = True
                    record.warnings.append("revision_mismatch_forced")
            else:
                record.warnings.append("revisions_unverified")

            try:
                outcome = await self._loader(
                    acceptance.upload_path,
                    mode=acceptance.mode,
                    expected_rows=manifest.row_count if manifest is not None else None,
                    acknowledge_loss=acceptance.acknowledge_loss,
                    on_phase=_phase_recorder(record),
                )
            except (
                NoCopyBlock,
                CopyHeaderMismatch,
                StagedRowCountMismatch,
                ReplaceGuardBlocked,
                CacheUploadUnsupportedDatabase,
            ) as exc:
                code = _REFUSAL_FOR[type(exc)]
                self._refuse(record, code, detail=str(exc))
                return
            except Exception as exc:  # noqa: BLE001 - the job boundary; recorded, not hidden
                record.state = "failed"
                record.error = f"{type(exc).__name__}: {exc}"
                record.finished_at = datetime.now(UTC)
                return

            record.out_counts(outcome)
            record.state = "complete"
            record.finished_at = datetime.now(UTC)
        finally:
            try:
                acceptance.upload_path.unlink(missing_ok=True)
            except OSError:  # pragma: no cover - best-effort temp cleanup
                pass

    @staticmethod
    def _refuse(record: CacheJobRecord, code: str, *, detail: str | None = None) -> None:
        record.state = "refused"
        record.refusal = code
        record.error = detail
        record.finished_at = datetime.now(UTC)


_REFUSAL_FOR: dict[type[Exception], str] = {
    NoCopyBlock: "no_copy_block",
    CopyHeaderMismatch: "column_layout_mismatch",
    StagedRowCountMismatch: "row_count_mismatch",
    ReplaceGuardBlocked: "newer_rows_would_be_lost",
    CacheUploadUnsupportedDatabase: "unsupported_database",
}


def _phase_recorder(
    record: CacheJobRecord,
) -> Callable[[Literal["loading", "merging"]], Awaitable[None]]:
    async def on_phase(phase: Literal["loading", "merging"]) -> None:
        record.state = phase

    return on_phase


__all__ = [
    "CacheUploadBusy",
    "CacheUploadRunner",
    "CacheJobRecord",
    "MAX_UPLOAD_BYTES_DEFAULT",
    "REFUSAL_CODES",
    "UploadAcceptance",
]
