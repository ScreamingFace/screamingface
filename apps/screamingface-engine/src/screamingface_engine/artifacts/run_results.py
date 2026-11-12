"""The run-results store: every result of a driver-started run, and each Run's context.

FEATURE: a detached Run (OME-1837), E5 P2 spec D9a, D9b and §4.4. A Client reattaching from any
machine reads each Candidate's result and its Run's context from the Engine for the Run's 30 days.
The artifact bucket cannot hold them: it expires everything after 2 days and takes only checksum
keys.

INVARIANT (D9a): the App builds every key, from the Run, the index and the result's checksum, and
never reads one from a runner. The checksum in a result's key means a second execution of one start
never overwrites the first.

INVARIANT (R13): retention deletes the keys a Run names, its context and each recorded result. An
object no record names (a second execution, a lost outcome) is removed by age: by the bucket's
31-day lifecycle rule on S3, by `delete_older_than` in a folder. So the S3 adapter never lists,
and `artifacts/sigv4.py` keeps its one-object bound.

LAYERING: a shared leaf (`artifacts`). The runner puts results; the App puts contexts, reads and
deletes.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

from screamingface_engine.artifacts.ports import ArtifactContent, LocalFile
from screamingface_engine.artifacts.s3 import S3ArtifactStore
from screamingface_engine.artifacts.s3_responses import S3StorageError

# WHY this strict: a key is signed unencoded on S3 and joined onto a folder on disk, so only the
# two shapes the App builds may reach either. `run_` + 32 hex is the Run id (`runs/ids.py`).
_RUN = r"runs/run_[0-9a-f]{32}"
_INDEX = r"(?:0|[1-9][0-9]{0,5})"
_KEY = re.compile(rf"^{_RUN}/(?:context|{_INDEX}/[0-9a-f]{{64}})$")
_PREFIX = re.compile(rf"^{_RUN}/{_INDEX}$")

# The first retry's wait, and the longest one (R5).
_FIRST_DELAY_S = 0.5
_MAX_DELAY_S = 10.0
DEFAULT_RESULT_WRITE_BUDGET_S = 60.0
"""How long a runner retries a refused write before it fails the run (R5)."""

RESULT_STORE_MISSING = "result_store_missing"
"""The code of a run sent with a result prefix to a pool with no run-results store (R5)."""
RESULT_STORE_UNAVAILABLE = "result_store_unavailable"
"""The code of a run whose result the store refused for the whole write budget (R5). Not
permanent: another attempt may find the store back."""


def result_prefix(run_id: str, index: int) -> str:
    """Where a Candidate's results go, ``runs/{run_id}/{index}``; the driver sends it."""
    return _checked(_PREFIX, f"runs/{run_id}/{index}")


def result_key(prefix: str, sha256: str) -> str:
    """A result's key: its Candidate's prefix and its checksum."""
    return check_key(f"{_checked(_PREFIX, prefix)}/{sha256}")


def context_key(run_id: str) -> str:
    """Where the Client's context for a Run goes (D9b)."""
    return check_key(f"runs/{run_id}/context")


def check_key(key: str) -> str:
    """``key`` if it is one the App builds; `ValueError` before any I/O otherwise."""
    return _checked(_KEY, key)


def _checked(pattern: re.Pattern[str], key: str) -> str:
    if pattern.fullmatch(key) is None:
        raise ValueError(f"not a run-results key: {key!r}")
    return key


class RunResultStoreUnavailable(RuntimeError):
    """The store refused a result for the whole write budget. INVARIANT (R5): the run then ends
    `failed` with `result_store_unavailable`, which is not permanent."""


@runtime_checkable
class RunResultStore(Protocol):
    """Sync, as the artifact ports are: the runner calls `put` where it already holds the result,
    off the event loop, and the App calls it through `asyncio.to_thread`."""

    def put(self, key: str, body: bytes) -> None: ...

    def open(self, key: str) -> ArtifactContent | None:
        """The object under ``key``, or None when it is absent."""
        ...

    def delete(self, keys: Iterable[str]) -> None:
        """Remove these keys; an absent one is not an error."""
        ...

    def delete_older_than(self, cutoff: datetime) -> int:
        """Remove what was written before ``cutoff``, where the store has no rule of its own that
        does; the number removed."""
        ...


class S3RunResultStore:
    """`RunResultStore` on a bucket of its own (§8: a 31-day lifecycle rule, and the runner pool's
    write-only key)."""

    def __init__(self, store: S3ArtifactStore) -> None:
        self._store = store

    def put(self, key: str, body: bytes) -> None:
        # One PUT with the known length and the body's sha256, acknowledged before returning.
        self._store.put_object(check_key(key), body)

    def open(self, key: str) -> ArtifactContent | None:
        return self._store.object_content(check_key(key))

    def delete(self, keys: Iterable[str]) -> None:
        for key in keys:
            self._store.delete_object(check_key(key))

    def delete_older_than(self, cutoff: datetime) -> int:
        """Always 0: the bucket's lifecycle rule removes by age (R13)."""
        return 0


class FilesystemRunResultStore:
    """`RunResultStore` in a folder under the Engine data dir, for local mode (D9a)."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def put(self, key: str, body: bytes) -> None:
        path = self._root / check_key(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # WHY a rename: a reader never sees a partly written file.
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            handle.write(body)
        os.replace(handle.name, path)

    def open(self, key: str) -> ArtifactContent | None:
        path = self._root / check_key(key)
        return LocalFile(path) if path.is_file() else None

    def delete(self, keys: Iterable[str]) -> None:
        for key in keys:
            path = self._root / check_key(key)
            path.unlink(missing_ok=True)
            self._prune(path.parent)

    def delete_older_than(self, cutoff: datetime) -> int:
        removed = 0
        before = cutoff.timestamp()
        for path in list(self._root.rglob("*")):
            if path.is_file() and path.stat().st_mtime < before:
                path.unlink(missing_ok=True)
                self._prune(path.parent)
                removed += 1
        return removed

    def _prune(self, folder: Path) -> None:
        """Remove ``folder`` and its parents up to the root while they are empty."""
        while folder != self._root and folder.is_relative_to(self._root):
            try:
                folder.rmdir()
            except OSError:
                return
            folder = folder.parent


@dataclass(frozen=True)
class ResultSink:
    """Where a driver-started run puts its result (R5): its Candidate's prefix, the store, and
    how long a refused write is retried. ``store`` is None on a pool with no run-results store,
    and the run fails `RESULT_STORE_MISSING` before any model call."""

    prefix: str
    store: RunResultStore | None
    budget_s: float = DEFAULT_RESULT_WRITE_BUDGET_S

    def write(self, body: bytes) -> str:
        """Put ``body`` under the prefix and its checksum; the checksum."""
        if self.store is None:
            raise RunResultStoreUnavailable("this pool has no run-results store")
        return write_result(self.store, self.prefix, body, budget_s=self.budget_s)


def write_result(
    store: RunResultStore,
    prefix: str,
    body: bytes,
    *,
    budget_s: float,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> str:
    """Put a run's result under ``prefix`` and its checksum, retried with backoff for up to
    ``budget_s`` (R5); the checksum. `RunResultStoreUnavailable` once the budget is spent."""
    digest = hashlib.sha256(body).hexdigest()
    key = result_key(prefix, digest)
    deadline = clock() + budget_s
    delay = _FIRST_DELAY_S
    while True:
        try:
            store.put(key, body)
            return digest
        except (S3StorageError, OSError) as exc:
            if clock() + delay > deadline:
                raise RunResultStoreUnavailable(f"could not write {key}: {exc}") from exc
        sleep(delay)
        delay = min(delay * 2, _MAX_DELAY_S)


__all__ = [
    "DEFAULT_RESULT_WRITE_BUDGET_S",
    "RESULT_STORE_MISSING",
    "RESULT_STORE_UNAVAILABLE",
    "FilesystemRunResultStore",
    "ResultSink",
    "RunResultStore",
    "RunResultStoreUnavailable",
    "S3RunResultStore",
    "check_key",
    "context_key",
    "result_key",
    "result_prefix",
    "write_result",
]
