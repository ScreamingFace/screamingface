"""Read an Imported Board's public Cases in O(selected Cases), not O(board) (OME-1790).

FEATURE (OME-1790, spec Option B): a 330 MB board used to be read and parsed whole for a 2-Case
run. The bundle now carries three files, written in this order:

1. ``board.json`` — ``{"schema", "case_count", "has_pictures", "cases_bytes"}``.
2. ``cases.offsets`` — 16 bytes per Case, in served order: the row's byte offset inside
   ``cases.json`` and its byte length, both little-endian uint64.
3. ``cases.json`` — unchanged, byte for byte, and still the bundle's completion marker
   (written last, so a bundle with ``cases.json`` always has its index).

Worked example: rows ``{"id":1}`` and ``{"id":2}`` make ``cases.json`` ``[{"id":1},{"id":2}]``
(19 bytes) and ``cases.offsets`` the entries ``(1, 8)`` and ``(10, 8)``. Selecting 1 Case reads
bytes 1..9 and serves ``[{"id":1}]``.

INVARIANT: every file is a pure function of the rows (no timestamps, no paths, fixed key order),
so two prepares of the same pins give the same bytes and the Case Digest never moves.

AIDEV-NOTE: a selection is a prefix (:meth:`BoardStore.head`) or, since OME-1739, explicit
Case ids (:meth:`BoardStore.rows`, served as JSON for the Cases route). Aggregation reads the
same validated walk by id through :meth:`IndexedBoard.rows_by_id` (grading-board-store); an
input lookup for the check surface is left for that unit.
"""

from __future__ import annotations

import json
import logging
import struct
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any, NamedTuple, Protocol

from screamingface_engine.benchmarks.grading_endpoints import benchmark_unavailable
from screamingface_engine.benchmarks.picture_admission import cases_need_pictures
from url4.core.errors import ResolutionError

logger = logging.getLogger(__name__)

BOARD_FILE = "board.json"
OFFSETS_FILE = "cases.offsets"
CASES_FILE = "cases.json"
BOARD_SCHEMA = "screamingface.board.v1"

_ENTRY = struct.Struct("<QQ")
_SEPARATORS = (",", ":")


class BoardFiles(NamedTuple):
    """The three files of one board, as bytes, in the order they are written."""

    board: bytes
    offsets: bytes
    cases: bytes


def encode_board(rows: Sequence[Mapping[str, Any]]) -> BoardFiles:
    """Serialise every row once and record where it sits.

    INVARIANT: ``cases`` equals ``json.dumps(list(rows), ensure_ascii=False,
    separators=(",", ":"))`` encoded as UTF-8 — the pre-OME-1790 bytes — because a JSON array
    with these separators is exactly ``"[" + ",".join(rows) + "]"``.
    """

    # WHY one join over ["[", row0, ",", row1, ..., "]"]: the rows plus the final bytes is the
    # same 2x-board peak as the pre-OME-1790 ``json.dumps(...).encode()``. A ``b",".join`` and
    # then ``b"[" + ... + b"]"`` held a third board-sized copy at image build (review, P2).
    pieces: list[bytes] = [b"["]
    entries: list[bytes] = []
    position: int = 1  # WHY 1: the opening "[".
    for row in rows:
        encoded: bytes = json.dumps(row, ensure_ascii=False, separators=_SEPARATORS).encode("utf-8")
        entries.append(_ENTRY.pack(position, len(encoded)))
        position += len(encoded) + 1  # the row, then its "," (or the closing "]").
        pieces.append(encoded)
        pieces.append(b",")
    if entries:
        pieces[-1] = b"]"  # the last row's "," becomes the closing "]".
    else:
        pieces.append(b"]")  # an empty board is "[]".
    cases: bytes = b"".join(pieces)
    del pieces
    board: bytes = json.dumps(
        {
            "schema": BOARD_SCHEMA,
            "case_count": len(entries),
            # WHY over the rows as written: an envelope board wraps plain-text inputs only,
            # and a wrapped plain prompt never carries a picture, so the flag is the same.
            "has_pictures": cases_need_pictures(rows),
            "cases_bytes": len(cases),
        },
        separators=_SEPARATORS,
    ).encode("utf-8")
    return BoardFiles(board=board, offsets=b"".join(entries), cases=cases)


class BoardStore(Protocol):
    """What the Cases route reads from one Imported Board."""

    def case_count(self) -> int:
        """How many Cases the board holds."""
        ...

    def has_pictures(self) -> bool:
        """Whether any Case hands the Candidate a picture (spec: a picture anywhere)."""
        ...

    def head(self, count: int) -> str:
        """The first ``count`` rows as a JSON array, byte-identical to the legacy slice.

        Raises:
            ValueError: ``count`` is outside ``1..case_count()``, or a legacy board is malformed.
            ResolutionError: ``benchmark_unavailable``; the index does not match its rows.
        """
        ...

    def rows(self, case_ids: Sequence[int]) -> str:
        """The rows for ``case_ids`` (ascending, distinct) as a JSON array (OME-1739).

        Worked example: ``rows((3, 17))`` serves ``[{"id":3,…},{"id":17,…}]``, walking tiles
        1..17 to prove each is a top-level element but holding only the selected ones;
        ``rows((1, 2, 3))`` is byte-identical to ``head(3)``.

        Raises:
            ValueError: an id is outside ``1..case_count()``.
            ResolutionError: ``benchmark_unavailable``; a read row's ``id`` is not its position,
                or the index does not match its rows.
        """
        ...


def _broken(detail: str) -> ResolutionError:
    return benchmark_unavailable(f"imported board cases are unavailable: {detail}")


def _check_count(count: int, available: int) -> None:
    if not 1 <= count <= available:
        raise ValueError(f"selected {count} of {available} Cases")


def _check_ids(case_ids: Sequence[int], available: int) -> None:
    if not case_ids or case_ids[0] < 1 or case_ids[-1] > available:
        raise ValueError(f"selected Cases {list(case_ids)} outside 1..{available}")
    # WHY (review on #1636): the 1..N shortcut below reads ``case_ids[-1] == len(case_ids)``,
    # which ``(2, 2)`` satisfies; only an ascending, distinct list may take it.
    if any(later <= earlier for earlier, later in zip(case_ids, case_ids[1:], strict=False)):
        raise ValueError(f"selected Cases {list(case_ids)} are not ascending and distinct")


def _positioned(row: object, case_id: int) -> None:
    """INVARIANT (OME-1739): the row read from position ``case_id`` carries that id.

    WHY: a selection names Cases by position, so a board whose rows are out of order would
    serve one question under another's id and grade it against the wrong answer key.
    """

    found: object = row.get("id") if isinstance(row, dict) else row
    # WHY type() not isinstance: a JSON true is a Python bool, and ``True == 1`` would let a
    # ``{"id": true}`` row pass as Case 1.
    if not isinstance(row, dict) or type(found) is not int or found != case_id:
        raise _broken(f"Case {case_id} is stored with id {found!r}")


def _check_row(chunk: bytes, first: int, length: int, position: int) -> dict[str, object]:
    """The entry at ``chunk[first:first + length]`` is exactly one JSON object, Case ``position``.

    INVARIANT (review round 2, P2): an index paired with other rows — shifted, reordered, or
    splitting a nested object such as ``{"parts":[{},{}]}`` — fails here, never serves bytes
    that are not the selected rows. Cost: one parse of the selected bytes only, never the board.

    Raises:
        ValueError: the bytes are not one object at this position (the caller bounds it).
    """

    row_bytes: bytes = chunk[first : first + length]
    # WHY the brace check beside the parse: json.loads accepts surrounding whitespace, and a
    # served row must be the writer's exact bytes, not merely an equal object.
    if length < 2 or row_bytes[:1] != b"{" or row_bytes[-1:] != b"}":
        raise ValueError(f"entry {position} is not an object's bytes")
    if first > 0 and chunk[first - 1 : first] != b",":
        raise ValueError(f"entry {position} does not follow a ','")
    # INVARIANT: bytes that start with "{", end with "}" and parse whole are one JSON object,
    # so the parse is the dict check — a split nested object or trailing data fails here.
    row: dict[str, object] = json.loads(row_bytes)
    # WHY id is positional but case_id only a string: the writer numbers Cases from 1 in served
    # order (capture.py), while case_id is the transport's string spelling, not bound here.
    row_id: object = row.get("id", position)
    if type(row_id) is not int or row_id != position:
        raise ValueError(f"entry {position} holds Case {row_id!r}")
    if "case_id" in row and not isinstance(row["case_id"], str):
        raise ValueError(f"entry {position} has a non-string case_id")
    return row


class IndexedBoard:
    """A board with ``board.json`` and ``cases.offsets``: reads only the selected bytes."""

    def __init__(self, root: Path) -> None:
        self._cases: Path = root / CASES_FILE
        self._offsets: Path = root / OFFSETS_FILE
        try:
            meta: object = json.loads((root / BOARD_FILE).read_bytes())
            cases_size: int = self._cases.stat().st_size
            offsets_size: int = self._offsets.stat().st_size
        except (OSError, ValueError) as exc:
            raise _broken(f"{BOARD_FILE} or its index cannot be read ({exc})") from exc
        if not isinstance(meta, dict) or meta.get("schema") != BOARD_SCHEMA:
            raise _broken(f"{BOARD_FILE} is not a {BOARD_SCHEMA} record")
        count: object = meta.get("case_count")
        pictures: object = meta.get("has_pictures")
        expected_size: object = meta.get("cases_bytes")
        # WHY type() not isinstance: a JSON true is a Python bool, which isinstance counts as int.
        if type(count) is not int or type(expected_size) is not int or type(pictures) is not bool:
            raise _broken(f"{BOARD_FILE} fields have the wrong types")
        # INVARIANT: a cases.json rewritten after its index was built is never read through it.
        if cases_size != expected_size:
            raise _broken(
                f"the index is stale ({CASES_FILE} is {cases_size} bytes, "
                f"{BOARD_FILE} recorded {expected_size})"
            )
        if offsets_size != count * _ENTRY.size:
            raise _broken(f"{OFFSETS_FILE} does not hold {count} entries")
        self._count: int = count
        self._pictures: bool = pictures
        self._size: int = cases_size

    def case_count(self) -> int:
        return self._count

    def has_pictures(self) -> bool:
        return self._pictures

    def head(self, count: int) -> str:
        _check_count(count, self._count)
        try:
            with self._offsets.open("rb") as handle:
                entries: list[tuple[int, int]] = list(
                    _ENTRY.iter_unpack(handle.read(count * _ENTRY.size))
                )
            if len(entries) != count:
                raise _broken(f"{OFFSETS_FILE} holds fewer than {count} entries")
            start: int = entries[0][0]
            end: int = entries[-1][0] + entries[-1][1]
            self._check_layout(entries, start, end)
            with self._cases.open("rb") as handle:
                handle.seek(start)
                chunk: bytes = handle.read(end - start)
            if len(chunk) != end - start:
                raise _broken(f"{CASES_FILE} is shorter than its index")
            for position, (offset, length) in enumerate(entries, start=1):
                _check_row(chunk, offset - start, length, position)
            text: str = chunk.decode("utf-8")
        # WHY ValueError: json.JSONDecodeError and UnicodeDecodeError are both ValueErrors.
        except (OSError, struct.error, ValueError) as exc:
            raise _broken(f"{OFFSETS_FILE} does not match {CASES_FILE} ({exc})") from exc
        # INVARIANT: "[" + one object per entry joined by "," + "]" — a JSON array of exactly
        # the selected rows, served as the original bytes (never re-serialised).
        return "[" + text + "]"

    def rows(self, case_ids: Sequence[int]) -> str:
        _check_ids(case_ids, self._count)
        if case_ids[-1] == len(case_ids):
            return self.head(len(case_ids))  # 1..N: one contiguous read, as ``head``
        served: list[str] = [text for _, text, _ in self._walk(frozenset(case_ids))]
        return "[" + ",".join(served) + "]"

    def rows_by_id(self, case_ids: Iterable[int]) -> dict[int, dict[str, object]]:
        """The parsed rows of the given Case ids, keyed by id, through :meth:`rows`' walk.

        FEATURE (grading-board-store): aggregation's selection need not be a prefix nor sorted
        (Cases 181, 7, 90), and may repeat an id. Ids outside ``1..case_count()`` are left out;
        the caller decides what a missing Case means. The rows are the dicts ``_check_row``
        already parsed, so grading never parses a row twice.

        INVARIANT: the same validated read as :meth:`rows` — tiles 1..max(selected) proven by
        induction from the array start — so an index that :meth:`rows` refuses (a nested
        ``{"id":3}``, a ``true`` id, a shifted or reordered entry) is refused here too, with
        the same bounded ``benchmark_unavailable``. Memory stays O(selected); I/O is
        O(largest selected id), as for :meth:`rows`.

        Raises:
            ResolutionError: ``benchmark_unavailable``; the index does not match its rows.
        """

        wanted: frozenset[int] = frozenset(i for i in case_ids if 1 <= i <= self._count)
        if not wanted:
            return {}
        return {position: row for position, _, row in self._walk(wanted)}

    def _walk(self, selected: frozenset[int]) -> Iterator[tuple[int, str, dict[str, object]]]:
        """Prove tiles ``1..max(selected)`` and yield each selected one: id, text, parsed row.

        AIDEV-NOTE: the one per-id read path behind :meth:`rows` and :meth:`rows_by_id`. Do not
        add a second reader that seeks straight to a selected entry — see the INVARIANT below.

        Raises:
            ResolutionError: ``benchmark_unavailable``; ``selected`` must be non-empty and
                inside ``1..case_count()`` (the callers check it).
        """

        last: int = max(selected)
        # INVARIANT (review on #1636, round 2): a selected tile is proven a top-level element
        # by INDUCTION from the array start, never by its neighbouring bytes. A delimiter
        # cannot prove nesting depth: inside ``"nested":[{"id":3,…}]`` the inner object sits
        # between "[" and "]" exactly like a real element, and rewriting the entries around it
        # keeps a neighbour-only chain contiguous. So: tile 1 is pinned at offset 1 (just after
        # the array's "[") and is checked to be one whole object, hence it is the true Case 1;
        # each proven tile ends one "," before the next entry's offset (``_check_layout``),
        # which pins the next tile's start; therefore tiles 1..last are the array's own
        # elements in order, and an object nested inside one of them can never be among them.
        # AIDEV-NOTE: this costs O(largest selected id) reads, like ``limit=`` does, while memory
        # stays O(selected): one tile is in flight at a time. An offsets hash recorded in
        # board.json at prepare time would let a selected read trust the index and go back to
        # O(selected) I/O — a follow-up, not this PR.
        try:
            with self._offsets.open("rb") as handle:
                entries: list[tuple[int, int]] = list(
                    _ENTRY.iter_unpack(handle.read(last * _ENTRY.size))
                )
            if len(entries) != last:
                raise _broken(f"{OFFSETS_FILE} holds fewer than {last} entries")
            self._check_layout(entries, entries[0][0], entries[-1][0] + entries[-1][1])
            with self._cases.open("rb") as cases:
                for position, (offset, length) in enumerate(entries, start=1):
                    # WHY the gap byte: ``_check_row`` proves the "," before every tile but the
                    # first, whose start is pinned by ``_check_layout`` (offset 1) instead.
                    first: int = 0 if position == 1 else 1
                    cases.seek(offset - first)
                    chunk: bytes = cases.read(length + first)
                    if len(chunk) != length + first:
                        raise _broken(f"{CASES_FILE} is shorter than its index")
                    row: dict[str, object] = _check_row(chunk, first, length, position)
                    if position in selected:
                        # WHY decode for both callers: ``rows`` serves the text, and grading
                        # must refuse the same non-UTF-8 bytes ``rows`` refuses.
                        yield position, chunk[first:].decode("utf-8"), row
        # WHY ValueError: json.JSONDecodeError and UnicodeDecodeError are both ValueErrors.
        except (OSError, struct.error, ValueError) as exc:
            raise _broken(f"{OFFSETS_FILE} does not match {CASES_FILE} ({exc})") from exc

    def _check_layout(self, entries: Sequence[tuple[int, int]], start: int, end: int) -> None:
        """The rows are contiguous, comma-separated, and inside the array brackets."""

        if len(entries) == 0 or start != 1 or end > self._size - 1:
            raise _broken(f"{OFFSETS_FILE} points outside {CASES_FILE}")
        for (offset, length), (following, _) in zip(entries, entries[1:], strict=False):
            if offset + length + 1 != following:
                raise _broken(f"{OFFSETS_FILE} is not in served order")


class LegacyBoard:
    """A bundle prepared before OME-1790: the whole ``cases.json``, parsed once."""

    def __init__(self, text: str) -> None:
        self._rows: object = json.loads(text)

    def _all(self) -> list[Any]:
        if not isinstance(self._rows, list):
            raise ValueError("cases.json is not a JSON array")
        return self._rows

    def case_count(self) -> int:
        return len(self._all())

    def has_pictures(self) -> bool:
        return cases_need_pictures([row for row in self._all() if isinstance(row, dict)])

    def head(self, count: int) -> str:
        rows: list[Any] = self._all()
        _check_count(count, len(rows))
        if any(not isinstance(row, dict) for row in rows[:count]):
            raise ValueError("case rows must be objects")
        return json.dumps(rows[:count], ensure_ascii=False, separators=_SEPARATORS)

    def rows(self, case_ids: Sequence[int]) -> str:
        rows: list[Any] = self._all()
        _check_ids(case_ids, len(rows))
        selected: list[Any] = [rows[case_id - 1] for case_id in case_ids]
        for row, case_id in zip(selected, case_ids, strict=True):
            _positioned(row, case_id)
        return json.dumps(selected, ensure_ascii=False, separators=_SEPARATORS)


def open_board(root: Path, read_legacy: Callable[[], str]) -> BoardStore:
    """The indexed store when the bundle has ``board.json``, else the logged full read.

    WHY a fallback, not a refusal (owner, OME-1790 Q4): local and CI caches hold bundles
    prepared before the index existed; they keep working, only without the saving.
    """

    if (root / BOARD_FILE).is_file():
        return IndexedBoard(root)
    logger.warning(
        "imported board %s has no %s/%s; reading the whole %s (re-prepare to index it)",
        root.name,
        BOARD_FILE,
        OFFSETS_FILE,
        CASES_FILE,
    )
    return LegacyBoard(read_legacy())


__all__ = [
    "BOARD_FILE",
    "BOARD_SCHEMA",
    "CASES_FILE",
    "OFFSETS_FILE",
    "BoardFiles",
    "BoardStore",
    "IndexedBoard",
    "LegacyBoard",
    "encode_board",
    "open_board",
]
