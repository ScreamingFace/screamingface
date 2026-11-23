"""Durable, process-exclusive outcomes for the OME-1958 operator batch (Unix only)."""

from __future__ import annotations

import fcntl
import json
import os
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import quote

RESOLVED = frozenset({"regraded", "already_regraded", "owner_resolved"})
NO_RETRY = RESOLVED | {"refused_permanently", "no_pinned_cache"}
_OUTCOMES = NO_RETRY | {"refused_retryable"}


class LogError(RuntimeError):
    """An outcome log cannot be safely resumed."""


class BatchAlreadyRunning(LogError):
    """Another process already owns this batch's outcome log."""


def entry_key(record: Mapping[str, Any]) -> str:
    """Stable across reruns, including rows without a pinned cache."""
    source = record.get("source_score_id")
    kind = "spec" if source is None else "score"
    identity = record["spec_id"] if source is None else source
    parts = ("v2", record["benchmark_id"], record["revision"], kind, identity)
    return "/".join(quote(part, safe="") for part in parts)


class Journal:
    """Read and append outcomes while the caller owns the file lock."""

    def __init__(
        self,
        stream: BinaryIO,
        scope: str,
        transitions: Mapping[str, Any],
        check_current: Callable[[], None],
    ) -> None:
        self.stream = stream
        self.scope = scope
        self.transitions = transitions
        self.check_current = check_current
        self.records: dict[str, dict[str, Any]] = {}
        self._recover()

    def _validate(self, record: Any) -> None:
        required = {
            "entry_key",
            "benchmark_id",
            "revision",
            "target_revision",
            "spec_id",
            "scope",
            "outcome",
        }
        if not isinstance(record, dict) or not required <= record.keys():
            raise LogError(
                "invalid or legacy log record; inspect/archive the log before restarting"
            )
        if any(not isinstance(record[key], str) or not record[key].strip() for key in required):
            raise LogError("invalid log field type or empty identity")
        source = record.get("source_score_id")
        if source is not None and (not isinstance(source, str) or not source.strip()):
            raise LogError("invalid source score identity")
        transition = self.transitions.get(record["benchmark_id"])
        if (
            record["scope"] != self.scope
            or transition is None
            or record["revision"] != transition["source"]
            or record["target_revision"] != transition["target"]
        ):
            raise LogError("log belongs to a different Scoreboard or revision transition")
        if record["entry_key"] != entry_key(record) or record["outcome"] not in _OUTCOMES:
            raise LogError("invalid log identity or outcome")
        self._validate_evidence(record)

    @staticmethod
    def _validate_evidence(record: Mapping[str, Any]) -> None:
        field = {
            "regraded": "new_score_id",
            "already_regraded": "new_score_id",
            "owner_resolved": "note",
        }.get(record["outcome"])
        if field is not None:
            value = record.get(field)
            if not isinstance(value, str) or not value.strip():
                raise LogError(f"resolved outcome requires nonempty {field}")

    def _recover(self) -> None:
        self.check_current()
        self.stream.seek(0)
        data = self.stream.read()
        end = data.rfind(b"\n") + 1
        # INVARIANT: validate all complete records BEFORE modifying a partial tail.
        for line in data[:end].splitlines():
            try:
                record = json.loads(line)
            except (ValueError, UnicodeDecodeError) as exc:
                raise LogError("corrupt complete log record; manual inspection required") from exc
            self._validate(record)
            self.records[record["entry_key"]] = record
        if end != len(data):
            try:
                record = json.loads(data[end:])
            except (ValueError, UnicodeDecodeError):
                # WHY: only an undecodable final fragment may be discarded automatically.
                self.check_current()
                self.stream.seek(end)
                self.stream.truncate()
                print(f"recovered {len(data) - end} bytes of partial final log record")
            else:
                # INVARIANT: a valid final record is evidence even without its newline.
                self._validate(record)
                self.check_current()
                self.stream.write(b"\n")
                self.records[record["entry_key"]] = record
            self.stream.flush()
            os.fsync(self.stream.fileno())

    def append(self, record: dict[str, Any]) -> None:
        """Persist the outcome before it becomes eligible to skip on another run."""
        record = {**record, "scope": self.scope, "entry_key": entry_key(record)}
        self._validate(record)
        self.check_current()
        self.stream.write((json.dumps(record) + "\n").encode())
        self.stream.flush()
        os.fsync(self.stream.fileno())
        self.records[record["entry_key"]] = record

    def resolve(self, resolutions: Mapping[str, str], at: str) -> None:
        """Record an explicit owner decision; reject all invalid requests before appending."""
        for key, note in resolutions.items():
            previous = self.records.get(key, {})
            if previous.get("outcome") == "owner_resolved" and previous.get("note") == note:
                continue
            if (
                not note.strip()
                or key not in self.records
                or self.records[key]["outcome"] in RESOLVED
            ):
                raise LogError(f"resolution needs an unresolved entry key and nonempty note: {key}")
        for key, note in resolutions.items():
            if self.records[key]["outcome"] == "owner_resolved":
                continue
            self.append({**self.records[key], "at": at, "outcome": "owner_resolved", "note": note})


@contextmanager
def locked_journal(path: Path, scope: str, transitions: Mapping[str, Any]) -> Iterator[Journal]:
    """Lock a persistent sidecar through recovery, replay and durable append.

    All scheduled runs must use the same log on the same machine. A second operator on
    another machine needs coordination; this advisory lock is not a distributed lease.
    """
    path = path.resolve()
    lock_path = path.with_name(path.name + ".lock")
    # INVARIANT: replacing the journal cannot replace its independently held lock.
    # Operators must never unlink/rotate the sidecar lock or use a different journal path.
    with lock_path.open("a+b") as lock_stream:
        try:
            fcntl.flock(lock_stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise BatchAlreadyRunning(f"already running with log {path}") from exc
        try:
            with path.open("a+b") as stream:

                def check_current() -> None:
                    for opened, named in ((stream, path), (lock_stream, lock_path)):
                        try:
                            actual, expected = os.fstat(opened.fileno()), named.stat()
                        except FileNotFoundError as exc:
                            raise LogError(f"journal or lock path replaced: {named}") from exc
                        if (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino):
                            raise LogError(f"journal or lock path replaced: {named}")

                yield Journal(stream, scope, transitions, check_current)
        finally:
            fcntl.flock(lock_stream, fcntl.LOCK_UN)
