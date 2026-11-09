"""One run's Case results, parked as each Case finishes and read back one at a time.

FEATURE (OME-1833, memory fix 2 for the MMLU-Pro ``memory_budget_exceeded`` kill): the
case-execution route used to hand url4 each Case's whole envelope (~12.5 KB). url4's
per-Case gather held every one of them until the last Case finished, and then the aggregate
received all of them joined into one ~150 MB context. Now the route appends the envelope here
and hands url4 a ~90 B reference. The aggregate resolves one reference at a time.

Think of a cloakroom with numbered tickets. The file is the rack: one compact JSON object per
line (NDJSON), in append order. The in-memory index is the ticket book: key -> (offset,
length, sha256). A ticket the book does not know, or a coat that no longer matches its
ticket's digest, is refused. It is never swapped for another coat.

WHY a local file and not the artifact store: the rows are written and read by the same Runner
process within one run, and they must be gone when the run ends. The artifact store hands
results across pods, and it is content-addressed and swept by TTL. Using it here would mean
12k PUT/GET round trips per run, with rows left behind afterwards.

INVARIANT: run-scoped and tenant-scoped. Each run gets its own store in its own 0700 temp
directory (``runner.operation_capture``), bound only for that run's steps, and deleted when
the run's ``execute`` ends, on success, failure or cancellation. A key resolves only through
the store that issued it.

INVARIANT: fail closed and typed. Every failure to resolve a key raises
``CaseResultStoreError``: an unknown key, a closed store, a missing or short file, a digest
mismatch, or undecodable JSON. It subclasses ``ValueError``, so the aggregate's existing
contract-error handling turns it into a failed run, never a quietly missing Case.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import shutil
import tempfile
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any, BinaryIO, NamedTuple

_ROWS_FILE = "case-results.ndjson"


class CaseResultStoreError(ValueError):
    """A parked Case result could not be resolved. The caller must fail; it must never guess."""


class _Entry(NamedTuple):
    offset: int
    length: int
    sha256: bytes


class CaseResultStore:
    """An append-only NDJSON file of one run's Case results, plus its offset index."""

    def __init__(self, directory: Path) -> None:
        self._directory: Path = directory
        self._path: Path = directory / _ROWS_FILE
        self._file: BinaryIO | None = self._path.open("ab")
        self._index: dict[str, _Entry] = {}
        self._end: int = 0
        # WHY a lock: url4 runs sync endpoints on the loop today, but a caller that moves a
        # route to a worker thread must not interleave two rows' bytes.
        self._lock: threading.Lock = threading.Lock()

    @classmethod
    def create(cls, parent: Path | None = None) -> CaseResultStore:
        """A fresh store in a new private (0700) directory under ``parent`` (default: tmp)."""

        return cls(Path(tempfile.mkdtemp(prefix="sf-case-results-", dir=parent)))

    @property
    def path(self) -> Path:
        """The NDJSON file itself (for diagnostics and tests)."""

        return self._path

    def __len__(self) -> int:
        return len(self._index)

    def append(self, record: Mapping[str, Any]) -> str:
        """Park one record and return its key. The key is opaque, and unique in this store."""

        encoded: bytes = json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        with self._lock:
            if self._file is None:
                raise CaseResultStoreError("the Case-result store is closed")
            self._file.write(encoded + b"\n")
            # WHY flush per row: a reader opens its own handle, so the bytes must reach the OS
            # before the reference is handed to url4.
            self._file.flush()
            key: str = str(len(self._index))
            self._index[key] = _Entry(self._end, len(encoded), hashlib.sha256(encoded).digest())
            self._end += len(encoded) + 1
        return key

    def read(self, key: str) -> dict[str, Any]:
        """The record parked under ``key``. Raises ``CaseResultStoreError`` for anything else."""

        with self._lock:
            if self._file is None:
                raise CaseResultStoreError("the Case-result store is closed")
            entry: _Entry | None = self._index.get(key)
        if entry is None:
            raise CaseResultStoreError(f"unknown Case-result key {key!r}")
        try:
            with self._path.open("rb") as stream:
                stream.seek(entry.offset)
                encoded: bytes = stream.read(entry.length)
        except OSError as exc:
            raise CaseResultStoreError(f"Case-result row {key!r} is unreadable: {exc}") from None
        if len(encoded) != entry.length or hashlib.sha256(encoded).digest() != entry.sha256:
            raise CaseResultStoreError(f"Case-result row {key!r} is corrupt")
        try:
            record: object = json.loads(encoded)
        except ValueError:  # pragma: no cover - a matching digest means these are our bytes
            raise CaseResultStoreError(f"Case-result row {key!r} is corrupt") from None
        if not isinstance(record, dict):  # pragma: no cover - append takes only mappings
            raise CaseResultStoreError(f"Case-result row {key!r} is corrupt")
        return record

    def close(self) -> None:
        """Delete every parked row. Idempotent; a closed store refuses reads and appends."""

        with self._lock:
            handle, self._file = self._file, None
        if handle is not None:
            handle.close()
        shutil.rmtree(self._directory, ignore_errors=True)


_bound: contextvars.ContextVar[CaseResultStore | None] = contextvars.ContextVar(
    "screamingface_case_results", default=None
)


@contextmanager
def binding_case_results(store: CaseResultStore | None) -> Iterator[None]:
    """Bind the run's store for the enclosed steps; ``None`` keeps every row inline.

    INVARIANT: the binding never outlives its block, so one run never parks into, or reads
    from, another run's store.
    """

    token: contextvars.Token[CaseResultStore | None] = _bound.set(store)
    try:
        yield
    finally:
        _bound.reset(token)


def bound_case_results() -> CaseResultStore | None:
    """The store bound to the current run, if there is one."""

    return _bound.get()


__all__ = [
    "CaseResultStore",
    "CaseResultStoreError",
    "binding_case_results",
    "bound_case_results",
]
