"""Incremental result indexing and immutable, disk-backed case sequences."""

from __future__ import annotations

import errno
import json
import logging
import os
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import closing
from decimal import Decimal
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, overload

import ijson
from ijson.common import ObjectBuilder

from screamingface._report_primitives import CaseId
from screamingface._results.index_integrity import digest, matches, publish, reusable
from screamingface._results.store import sync_directory
from screamingface.case_result import CaseResult
from screamingface.errors import ExecutionError


class DiskCases(Sequence[CaseResult]):
    """An index holds only paths and counts; no case is cached in memory."""

    def __init__(self, path: Path, count: int, gradeable: int | None = None) -> None:
        self.path = path.resolve()
        self._count = count
        self.gradeable = gradeable

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)

    def __len__(self) -> int:
        return self._count

    @overload
    def __getitem__(self, index: int) -> CaseResult: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[CaseResult, ...]: ...

    def __getitem__(self, index: int | slice) -> CaseResult | tuple[CaseResult, ...]:
        if isinstance(index, slice):
            return tuple(self[i] for i in range(*index.indices(self._count)))
        selected = index + self._count if index < 0 else index
        if not 0 <= selected < self._count:
            raise IndexError(index)
        with closing(self._connect()) as db:
            row = db.execute("SELECT body FROM cases WHERE position=?", (selected,)).fetchone()
        if row is None:
            raise ExecutionError("Saved result index is incomplete; recover the run again")
        return _decode(row[0])

    def __iter__(self) -> Iterator[CaseResult]:
        with closing(self._connect()) as db:
            for row in db.execute("SELECT body FROM cases ORDER BY position"):
                yield _decode(row[0])

    def identities(self) -> Iterator[CaseId]:
        with closing(self._connect()) as db:
            for row in db.execute("SELECT id FROM cases ORDER BY position"):
                yield json.loads(row[0])

    def matching_indices(self, query: str) -> Iterator[int]:
        # WHY: scan the existing JSON index without decoding and rebuilding every Case.
        # INVARIANT: parameter binding keeps quotes, % and _ literal; Unicode uses casefold.
        with closing(self._connect()) as db:
            db.create_function("sf_casefold", 1, str.casefold, deterministic=True)
            for row in db.execute(
                "SELECT position FROM cases WHERE instr(sf_casefold(body), ?) > 0 "
                "ORDER BY position",
                (query.casefold(),),
            ):
                yield row[0]

    def by_id(self, case_id: CaseId) -> CaseResult:
        with closing(self._connect()) as db:
            row = db.execute("SELECT body FROM cases WHERE id=?", (json.dumps(case_id),)).fetchone()
        if row is None:
            raise KeyError(f"unknown Case id {case_id!r}")
        return _decode(row[0])

    def failures(self):
        from screamingface._evaluation.results import _failure

        with closing(self._connect()) as db:
            compact = db.execute(
                "SELECT name FROM sqlite_master WHERE name='case_failures'"
            ).fetchone()
            query = (
                "SELECT body FROM case_failures ORDER BY position"
                if compact
                else "SELECT json_extract(body, '$.failures') FROM cases ORDER BY position"
            )
            for row in db.execute(query):
                yield from (_failure(value) for value in json.loads(row[0]))

    def __repr__(self) -> str:
        return f"DiskCases(count={self._count}, path={str(self.path)!r})"


def _decode(body: str) -> CaseResult:
    from screamingface._evaluation.results import _case_result

    return _case_result(json.loads(body))


def _value(events: Iterator[Any], first: tuple[str, Any]) -> Any:
    """Build one value; the caller splits the top-level cases array first."""
    builder = ObjectBuilder()
    event, value = first
    builder.event(event, value)
    depth = int(event in ("start_map", "start_array"))
    while depth:
        event, value = next(events)
        builder.event(event, value)
        depth += int(event in ("start_map", "start_array"))
        depth -= int(event in ("end_map", "end_array"))
    return builder.value


def _json(value: object) -> str:
    # WHY: ijson preserves arbitrary integers and parses fractional numbers as Decimal.
    # The existing decoder uses json.loads floats; match that public numeric behavior.
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=_number)


def _number(value: object) -> float:
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(f"Not JSON: {type(value).__name__}")


def _populate(source: Path, db: sqlite3.Connection) -> dict[str, object]:
    metadata: dict[str, object] = {}
    seen: set[str] = set()
    with source.open("rb") as stream:
        events = iter(ijson.basic_parse(stream))
        if next(events)[0] != "start_map":
            raise ValueError("result must be an object")
        for event, key in events:
            if event == "end_map":
                break
            if event != "map_key" or key in seen:
                raise ValueError("invalid or duplicate result field")
            seen.add(key)
            first = next(events)
            if key != "cases":
                metadata[key] = json.loads(_json(_value(events, first)))
                continue
            if first[0] != "start_array":
                raise ValueError("cases must be an array")
            gradeable = _insert_cases(events, db)
            db.execute("INSERT INTO case_stats VALUES (?)", (gradeable,))
        if next(events, None) is not None or "cases" not in seen:
            raise ValueError("invalid result JSON or missing cases")
    return metadata


def _insert_cases(events: Iterator[Any], db: sqlite3.Connection) -> int:
    from screamingface._evaluation.results import _case_result

    gradeable = 0
    for position, first in enumerate(events):
        if first[0] == "end_array":
            break
        body = _json(_value(events, first))
        case = _case_result(json.loads(body))
        gradeable += int(case.grade is not None and case.grade.score is not None)
        db.execute("INSERT INTO cases VALUES (?,?,?)", (position, json.dumps(case.case_id), body))
        if case.failures:
            db.execute(
                "INSERT INTO case_failures VALUES (?,?)",
                (position, _json([failure.to_dict() for failure in case.failures])),
            )
    return gradeable


def index_result(source: Path) -> tuple[dict[str, object], DiskCases]:
    """Publish an index only after the entire JSON has parsed and validated."""
    target = source.with_suffix(".sqlite3")
    source_digest = digest(source)
    # INVARIANT: raw results are authoritative; even readable altered indices are rebuilt.
    cached = _cached_index(target, source_digest)
    if cached is not None:
        return cached
    try:
        with NamedTemporaryFile(dir=source.parent, prefix=".index-", delete=False) as handle:
            temporary = Path(handle.name)
    except OSError as exc:
        if exc.errno not in {errno.EACCES, errno.EPERM, errno.EROFS}:
            raise
        verified = _readonly_index(source, target, source_digest)
        if verified is None:
            raise
        return verified
    try:
        _build_index(source, temporary)
        _publish_index(source, temporary, target, source_digest)
    finally:
        temporary.unlink(missing_ok=True)
    return _open_index(target)


def _cached_index(target: Path, source_digest: str):
    if reusable(target, source_digest):
        try:
            return _open_index(target)
        except (sqlite3.Error, ValueError, TypeError, IndexError):
            pass
    return None


def _readonly_index(source: Path, target: Path, source_digest: str):
    # WHY: old read-only caches need verification without writing to their saved directory.
    with NamedTemporaryFile(prefix=".sf-index-", delete=False) as handle:
        temporary = Path(handle.name)
    try:
        _build_index(source, temporary)
        if digest(source) == source_digest and matches(temporary, target):
            return _open_index(target)
        return None
    finally:
        temporary.unlink(missing_ok=True)


def _build_index(source: Path, temporary: Path) -> None:
    try:
        with closing(sqlite3.connect(temporary)) as db:
            db.execute("PRAGMA cache_size=-2048")
            db.execute(
                "CREATE TABLE cases (position INTEGER PRIMARY KEY, id TEXT UNIQUE, body TEXT)"
            )
            _create_metadata_tables(db)
            metadata = _populate(source, db)
            db.execute("INSERT INTO metadata VALUES (?)", (_json(metadata),))
            db.commit()

    except sqlite3.IntegrityError as exc:
        raise ExecutionError("duplicate Candidate Case Result id") from exc
    except (ijson.JSONError, StopIteration, ValueError) as exc:
        raise ExecutionError(f"Invalid result JSON: {exc}") from exc


def _publish_index(source: Path, temporary: Path, target: Path, source_digest: str) -> None:
    with temporary.open("rb") as handle:
        os.fsync(handle.fileno())
    if digest(source) != source_digest:
        raise ExecutionError("Result changed while indexing", code="result_integrity_mismatch")
    index_digest = digest(temporary)
    temporary.replace(target)
    sync_directory(target.parent)
    publish(target, source_digest, index_digest)


def _open_index(path: Path) -> tuple[dict[str, object], DiskCases]:
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        metadata = json.loads(db.execute("SELECT body FROM metadata").fetchone()[0])
        count = db.execute("SELECT count(*) FROM cases").fetchone()[0]
        stats = db.execute("SELECT name FROM sqlite_master WHERE name='case_stats'").fetchone()
        compact = db.execute("SELECT name FROM sqlite_master WHERE name='case_failures'").fetchone()
        if stats:
            gradeable = db.execute("SELECT gradeable FROM case_stats").fetchone()[0]
        else:
            # WHY: upgrade existing validated indices without rebuilding or dropping results.
            gradeable = db.execute(
                "SELECT count(*) FROM cases WHERE json_type(body, '$.grade.score') "
                "IN ('integer', 'real')"
            ).fetchone()[0]
    if not stats or not compact:
        _save_stats(path, gradeable)
    return metadata, DiskCases(path, count, gradeable)


def _save_stats(path: Path, gradeable: int) -> None:
    try:
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS case_stats (gradeable INTEGER NOT NULL)")
            if db.execute("SELECT count(*) FROM case_stats").fetchone()[0] == 0:
                db.execute("INSERT INTO case_stats VALUES (?)", (gradeable,))
            db.execute(
                "CREATE TABLE IF NOT EXISTS case_failures (position INTEGER PRIMARY KEY, body TEXT)"
            )
            db.execute(
                "INSERT OR IGNORE INTO case_failures "
                "SELECT position, json_extract(body, '$.failures') FROM cases "
                "WHERE json_array_length(body, '$.failures') > 0"
            )
    except sqlite3.Error:
        logging.getLogger(__name__).warning("Could not cache report coverage; using derived count")


def _create_metadata_tables(db: sqlite3.Connection) -> None:
    db.execute("CREATE TABLE metadata (body TEXT)")
    db.execute("CREATE TABLE case_stats (gradeable INTEGER NOT NULL)")
    db.execute("CREATE TABLE case_failures (position INTEGER PRIMARY KEY, body TEXT)")
