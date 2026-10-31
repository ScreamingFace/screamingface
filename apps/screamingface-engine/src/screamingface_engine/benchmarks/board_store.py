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

AIDEV-NOTE: the selection is always a prefix today (``protocol.py``: ``slice=(0, N)``), so
:meth:`BoardStore.head` is the one read the Cases route needs. Id-keyed reads for aggregation
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

    serialised: list[bytes] = [
        json.dumps(row, ensure_ascii=False, separators=_SEPARATORS).encode("utf-8") for row in rows
    ]
    entries: list[bytes] = []
    position: int = 1  # WHY 1: the opening "[".
    for row in serialised:
        entries.append(_ENTRY.pack(position, len(row)))
        position += len(row) + 1  # the row, then its "," (or the closing "]").
    cases: bytes = b"[" + b",".join(serialised) + b"]"
    board: bytes = json.dumps(
        {
            "schema": BOARD_SCHEMA,
            "case_count": len(serialised),
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


def _broken(detail: str) -> ResolutionError:
    return benchmark_unavailable(f"imported board cases are unavailable: {detail}")


def _check_count(count: int, available: int) -> None:
    if not 1 <= count <= available:
        raise ValueError(f"selected {count} of {available} Cases")


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
            start: int = entries[0][0]
            end: int = entries[-1][0] + entries[-1][1]
            self._check_layout(entries, start, end)
            with self._cases.open("rb") as handle:
                handle.seek(start)
                chunk: bytes = handle.read(end - start)
        except OSError as exc:
            raise _broken(str(exc)) from exc
        # INVARIANT: each row starts with "{" and ends with "}" where the index says it does,
        # so an index paired with other rows fails here instead of serving shifted rows.
        for offset, length in entries:
            first, last = offset - start, offset - start + length - 1
            if length < 2 or chunk[first : first + 1] != b"{" or chunk[last : last + 1] != b"}":
                raise _broken(f"{OFFSETS_FILE} does not match {CASES_FILE}")
        return "[" + chunk.decode("utf-8") + "]"

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
