"""Read an Imported Board's public Cases in O(selected Cases), not O(board) (OME-1790).

FEATURE (OME-1790, spec Option B): a 330 MB board used to be read and parsed whole for a 2-Case
run. The bundle now carries three files, written in this order:

1. ``board.json`` — ``{"schema", "case_count", "cases_bytes", "modalities"}`` (schema
   ``screamingface.board.v2``). ``modalities`` is the sorted list of non-text input types any
   Case needs, in the gateway's ``input_modalities`` vocabulary (``image``, ``pdf``); ``text``
   is never listed, so ``[]`` is a text-only board (OME-1803).
2. ``cases.offsets`` — 16 bytes per Case, in served order: the row's byte offset inside
   ``cases.json`` and its byte length, both little-endian uint64.
3. ``cases.json`` — unchanged, byte for byte, and still the bundle's completion marker
   (written last, so a bundle with ``cases.json`` always has its index).

Worked example: rows ``{"id":1}`` and ``{"id":2}`` make ``cases.json`` ``[{"id":1},{"id":2}]``
(19 bytes) and ``cases.offsets`` the entries ``(1, 8)`` and ``(10, 8)``. Selecting 1 Case reads
bytes 1..9 and serves ``[{"id":1}]``.

FEATURE (OME-1803, owner 2026-11-03): v2 replaced v1's ``has_pictures`` flag, which could not
carry the PDF decision. A v1 board (or one with no ``board.json``) is read the legacy way, with
one logged scan of ``cases.json`` for its modalities; v1's flag is never trusted for PDFs. Any
other schema fails closed as ``benchmark_unavailable``.

INVARIANT: every file is a pure function of the rows (no timestamps, no paths, fixed key order),
so two prepares of the same pins give the same bytes and the Case Digest never moves.

AIDEV-NOTE: a selection is a prefix (:meth:`BoardStore.head`) or, since OME-1739, explicit
Case ids (:meth:`BoardStore.rows`, one seek per selected row). Id-keyed reads for aggregation
(OME-1789) and an input lookup for the check surface are left for those units.
"""

from __future__ import annotations

import json
import logging
import struct
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, NamedTuple, Protocol

from screamingface_engine.benchmarks.grading_endpoints import benchmark_unavailable
from screamingface_engine.benchmarks.picture_admission import (
    PART_MODALITIES,
    cases_need_modalities,
)
from url4.core.errors import ResolutionError

logger = logging.getLogger(__name__)

BOARD_FILE = "board.json"
OFFSETS_FILE = "cases.offsets"
CASES_FILE = "cases.json"
BOARD_SCHEMA = "screamingface.board.v2"
BOARD_SCHEMA_V1 = "screamingface.board.v1"
"""The OME-1790 record (``has_pictures``), read only through the legacy full scan."""

_ENTRY = struct.Struct("<QQ")
_NEEDS: frozenset[str] = frozenset(PART_MODALITIES.values())
"""The only values a recorded ``modalities`` set may hold: the table's non-text types."""
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
            "cases_bytes": len(cases),
            # WHY over the rows as written: an envelope board wraps plain-text inputs only,
            # and a wrapped plain prompt never carries a picture or a PDF, so the set is the same.
            "modalities": sorted(cases_need_modalities(rows)),
        },
        separators=_SEPARATORS,
    ).encode("utf-8")
    return BoardFiles(board=board, offsets=b"".join(entries), cases=cases)


class BoardStore(Protocol):
    """What the Cases route reads from one Imported Board."""

    def case_count(self) -> int:
        """How many Cases the board holds."""
        ...

    def modalities(self) -> frozenset[str]:
        """The non-text input types any Case hands the Candidate (spec: anywhere in the board)."""
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


def _check_row(chunk: bytes, first: int, length: int, position: int) -> None:
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
        modalities: object = meta.get("modalities")
        expected_size: object = meta.get("cases_bytes")
        # WHY type() not isinstance: a JSON true is a Python bool, which isinstance counts as int.
        if type(count) is not int or type(expected_size) is not int:
            raise _broken(f"{BOARD_FILE} fields have the wrong types")
        # INVARIANT: a missing or malformed set fails closed; reading it as "text only" would
        # admit a blind model to a picture or PDF board.
        if not isinstance(modalities, list) or not all(
            isinstance(modality, str) for modality in modalities
        ):
            raise _broken(f"{BOARD_FILE} modalities is not a list of strings")
        # INVARIANT (review on #1645, blocker 1): only the writer's canonical form opens. A set
        # naming "text" or an unknown type would be satisfied by a text-only model, so a PDF
        # board relabelled ["text"] would be admitted to one; sorted and distinct keeps the
        # record the pure function of the rows that ``encode_board`` writes.
        if modalities != sorted(set(modalities)) or not set(modalities) <= _NEEDS:
            raise _broken(
                f"{BOARD_FILE} modalities {modalities!r} is not a sorted, distinct subset of "
                f"{sorted(_NEEDS)}"
            )
        # INVARIANT: a cases.json rewritten after its index was built is never read through it.
        if cases_size != expected_size:
            raise _broken(
                f"the index is stale ({CASES_FILE} is {cases_size} bytes, "
                f"{BOARD_FILE} recorded {expected_size})"
            )
        if offsets_size != count * _ENTRY.size:
            raise _broken(f"{OFFSETS_FILE} does not hold {count} entries")
        self._count: int = count
        self._modalities: frozenset[str] = frozenset(modalities)
        self._size: int = cases_size

    def case_count(self) -> int:
        return self._count

    def modalities(self) -> frozenset[str]:
        return self._modalities

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
        selected: frozenset[int] = frozenset(case_ids)
        last: int = case_ids[-1]
        served: list[str] = []
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
                    _check_row(chunk, first, length, position)
                    if position in selected:
                        served.append(chunk[first:].decode("utf-8"))
        # WHY ValueError: json.JSONDecodeError and UnicodeDecodeError are both ValueErrors.
        except (OSError, struct.error, ValueError) as exc:
            raise _broken(f"{OFFSETS_FILE} does not match {CASES_FILE} ({exc})") from exc
        return "[" + ",".join(served) + "]"

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
        self._modalities: frozenset[str] | None = None

    def _all(self) -> list[Any]:
        if not isinstance(self._rows, list):
            raise ValueError("cases.json is not a JSON array")
        return self._rows

    def case_count(self) -> int:
        return len(self._all())

    def modalities(self) -> frozenset[str]:
        # WHY cached: the scan parses every Case's envelope; the route asks once per run, and a
        # second ask must not pay for it again.
        if self._modalities is None:
            self._modalities = cases_need_modalities(
                [row for row in self._all() if isinstance(row, dict)]
            )
        return self._modalities

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


def _schema_of(path: Path) -> object:
    """The ``schema`` field of ``board.json``, or ``None`` when it cannot be read as an object.

    WHY ``None`` and no error here: an unreadable record goes on to :class:`IndexedBoard`, which
    names the fault as the bounded ``benchmark_unavailable``.
    """

    try:
        meta: object = json.loads(path.read_bytes())
    except (OSError, ValueError):
        return None
    return meta.get("schema") if isinstance(meta, dict) else None


def open_board(root: Path, read_legacy: Callable[[], str]) -> BoardStore:
    """The indexed store for a v2 ``board.json``, else (v1, or none) the logged full read.

    WHY a fallback, not a refusal (owner, OME-1790 Q4): local and CI caches hold bundles
    prepared before the index existed; they keep working, only without the saving.
    """

    if (root / BOARD_FILE).is_file():
        if _schema_of(root / BOARD_FILE) != BOARD_SCHEMA_V1:
            # WHY: v2 is served through the index; anything else is refused there, fail closed.
            return IndexedBoard(root)
        logger.warning(
            "imported board %s has a %s %s with no modalities; reading the whole %s to find "
            "them (re-prepare to index it)",
            root.name,
            BOARD_SCHEMA_V1,
            BOARD_FILE,
            CASES_FILE,
        )
        return LegacyBoard(read_legacy())
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
    "BOARD_SCHEMA_V1",
    "CASES_FILE",
    "OFFSETS_FILE",
    "BoardFiles",
    "BoardStore",
    "IndexedBoard",
    "LegacyBoard",
    "encode_board",
    "open_board",
]
