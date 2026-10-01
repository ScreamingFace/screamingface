"""Incremental result indexing and immutable, disk-backed case sequences."""

from __future__ import annotations

import json
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
from screamingface._results.store import sync_directory
from screamingface.case_result import CaseResult
from screamingface.errors import ExecutionError


class DiskCases(Sequence[CaseResult]):
    """An index holds only paths and counts; no case is cached in memory."""

    def __init__(self, path: Path, count: int) -> None:
        self.path = path.resolve()
        self._count = count

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
            _insert_cases(events, db)
        if next(events, None) is not None or "cases" not in seen:
            raise ValueError("invalid result JSON or missing cases")
    return metadata


def _insert_cases(events: Iterator[Any], db: sqlite3.Connection) -> None:
    from screamingface._evaluation.results import _case_result

    for position, first in enumerate(events):
        if first[0] == "end_array":
            break
        body = _json(_value(events, first))
        case = _case_result(json.loads(body))
        db.execute("INSERT INTO cases VALUES (?,?,?)", (position, json.dumps(case.case_id), body))


def index_result(source: Path) -> tuple[dict[str, object], DiskCases]:
    """Publish an index only after the entire JSON has parsed and validated."""
    target = source.with_suffix(".sqlite3")
    # INVARIANT: only complete, atomically published indices are reusable after a crash.
    if target.exists():
        return _open_index(target)
    with NamedTemporaryFile(dir=source.parent, prefix=".index-", delete=False) as handle:
        temporary = Path(handle.name)
    try:
        with closing(sqlite3.connect(temporary)) as db:
            db.execute("PRAGMA cache_size=-2048")
            db.execute(
                "CREATE TABLE cases (position INTEGER PRIMARY KEY, id TEXT UNIQUE, body TEXT)"
            )
            db.execute("CREATE TABLE metadata (body TEXT)")
            metadata = _populate(source, db)
            db.execute("INSERT INTO metadata VALUES (?)", (_json(metadata),))
            db.commit()
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        temporary.replace(target)
        sync_directory(target.parent)
    except sqlite3.IntegrityError as exc:
        raise ExecutionError("duplicate Candidate Case Result id") from exc
    except (ijson.JSONError, StopIteration, ValueError) as exc:
        raise ExecutionError(f"Invalid result JSON: {exc}") from exc
    finally:
        temporary.unlink(missing_ok=True)
    return _open_index(target)


def _open_index(path: Path) -> tuple[dict[str, object], DiskCases]:
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        metadata = json.loads(db.execute("SELECT body FROM metadata").fetchone()[0])
        count = db.execute("SELECT count(*) FROM cases").fetchone()[0]
    return metadata, DiskCases(path, count)
