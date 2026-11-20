"""Durable, process-exclusive outcomes for the OME-1958 operator batch (Unix only)."""

from __future__ import annotations

import fcntl
import json
import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any, BinaryIO

RESOLVED = frozenset({"regraded", "already_regraded", "owner_resolved"})
NO_RETRY = RESOLVED | {"refused_permanently", "no_pinned_cache"}
_OUTCOMES = NO_RETRY | {"refused_retryable"}


class LogError(RuntimeError):
    """An outcome log cannot be safely resumed."""


class BatchAlreadyRunning(LogError):
    """Another process already owns this batch's outcome log."""


def entry_key(record: Mapping[str, Any]) -> str:
    """Stable across reruns, including rows without a pinned cache."""
    source = record.get("source_score_id") or record["spec_id"]
    return f"{record['benchmark_id']}/{record['revision']}/{source}"


class Journal:
    """Read and append outcomes while the caller owns the file lock."""

    def __init__(self, stream: BinaryIO, scope: str, transitions: Mapping[str, Any]) -> None:
        self.stream = stream
        self.scope = scope
        self.transitions = transitions
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
            self.stream.seek(end)
            self.stream.truncate()
            self.stream.flush()
            os.fsync(self.stream.fileno())
            print(f"recovered {len(data) - end} bytes of unterminated final log record")

    def append(self, record: dict[str, Any]) -> None:
        """Persist the outcome before it becomes eligible to skip on another run."""
        record = {**record, "scope": self.scope, "entry_key": entry_key(record)}
        self._validate(record)
        self.stream.write((json.dumps(record) + "\n").encode())
        self.stream.flush()
        os.fsync(self.stream.fileno())
        self.records[record["entry_key"]] = record

    def resolve(self, resolutions: Mapping[str, str], at: str) -> None:
        """Record an explicit owner decision; reject all invalid requests before appending."""
        for key, note in resolutions.items():
            if (
                not note.strip()
                or key not in self.records
                or self.records[key]["outcome"] in RESOLVED
            ):
                raise LogError(f"resolution needs an unresolved entry key and nonempty note: {key}")
        for key, note in resolutions.items():
            self.append({**self.records[key], "at": at, "outcome": "owner_resolved", "note": note})


@contextmanager
def locked_journal(path: Path, scope: str, transitions: Mapping[str, Any]) -> Iterator[Journal]:
    """Lock the log inode through recovery, replay and durable append; never unlink it.

    All scheduled runs must use the same log on the same machine. A second operator on
    another machine needs coordination; this advisory lock is not a distributed lease.
    """
    with path.open("a+b") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise BatchAlreadyRunning(f"already running with log {path}") from exc
        try:
            yield Journal(stream, scope, transitions)
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)
