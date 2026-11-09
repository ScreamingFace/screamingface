"""``IndexedBoard.rows()`` refuses a tampered or truncated board as ``benchmark_unavailable``.

STORY: as a researcher running ``cases=[3, 17, 42]``, a board whose index or rows were damaged
after the image was built never serves another Case's text under a selected id, and never
crashes the run with a raw file error: every corruption is the one bounded url4 error code.

INVARIANT (review on #1636): the explicit-id read gives the same guarantees as ``head()``: exact
offset-entry reads, exact row reads, the row framed by ``[``/``,`` and ``,``/``]`` as a whole
array element, one JSON object whose ``id`` is an ``int`` equal to its position, and every
``OSError``/``struct.error``/``ValueError`` (short reads, bad UTF-8, bad JSON) mapped to
``benchmark_unavailable``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from screamingface_engine.benchmarks.board_store import (
    _ENTRY,
    BOARD_FILE,
    CASES_FILE,
    OFFSETS_FILE,
    IndexedBoard,
    LegacyBoard,
    encode_board,
)
from url4.core.errors import ResolutionError

# Example: a 50-Case board; the researcher's held-out set includes Cases 3, 4 and 42.
_ROWS: list[dict[str, Any]] = [
    {"id": index, "case_id": f"c{index}", "input": f"question {index}"} for index in range(1, 51)
]


def _write(root: Path, rows: list[dict[str, Any]]) -> None:
    files = encode_board(rows)
    (root / BOARD_FILE).write_bytes(files.board)
    (root / OFFSETS_FILE).write_bytes(files.offsets)
    (root / CASES_FILE).write_bytes(files.cases)


def _unavailable(board: IndexedBoard | LegacyBoard, ids: tuple[int, ...]) -> ResolutionError:
    with pytest.raises(ResolutionError) as caught:
        board.rows(ids)
    assert caught.value.code == "benchmark_unavailable"
    return caught.value


def test_an_offsets_file_truncated_after_open_is_refused(tmp_path: Path) -> None:
    """A short read of the 16-byte entry is ``benchmark_unavailable``, not a raw struct error."""

    _write(tmp_path, _ROWS)
    board = IndexedBoard(tmp_path)
    # WHY after open: the size check at open passes; the damage lands between open and read.
    (tmp_path / OFFSETS_FILE).write_bytes((tmp_path / OFFSETS_FILE).read_bytes()[: 20 * 16 + 8])

    _unavailable(board, (3, 42))


def test_a_cases_file_truncated_after_open_is_refused(tmp_path: Path) -> None:
    """A selected row cut short by a truncated ``cases.json`` is ``benchmark_unavailable``."""

    _write(tmp_path, _ROWS)
    board = IndexedBoard(tmp_path)
    offsets: bytes = (tmp_path / OFFSETS_FILE).read_bytes()
    offset, _length = _ENTRY.unpack(offsets[41 * 16 : 42 * 16])
    (tmp_path / CASES_FILE).write_bytes((tmp_path / CASES_FILE).read_bytes()[: offset + 5])

    _unavailable(board, (3, 42))


def test_invalid_utf8_inside_a_selected_row_is_refused(tmp_path: Path) -> None:
    """Bytes that are not UTF-8 inside the selected row are ``benchmark_unavailable``."""

    _write(tmp_path, _ROWS)
    board = IndexedBoard(tmp_path)
    offsets: bytes = (tmp_path / OFFSETS_FILE).read_bytes()
    offset, length = _ENTRY.unpack(offsets[41 * 16 : 42 * 16])
    cases: bytearray = bytearray((tmp_path / CASES_FILE).read_bytes())
    # WHY the same length: cases_bytes still matches board.json, so the board opens as before.
    cases[offset + length - 3 : offset + length - 1] = b"\xff\xfe"
    (tmp_path / CASES_FILE).write_bytes(bytes(cases))

    _unavailable(board, (3, 42))


def test_an_index_entry_pointing_inside_another_row_is_refused(tmp_path: Path) -> None:
    """An offsets entry aimed at a nested object inside row 2 never serves it as Case 3.

    WHY: the nested object carries ``id: 3``, so an id check alone would serve "FAKE" under
    Case 3 and grade it against Case 3's answer key. The framing check (a ``[`` or ``,``
    before the row, a ``,`` or ``]`` after it) is what refuses it.
    """

    rows: list[dict[str, Any]] = [dict(row) for row in _ROWS]
    rows[1] = {"id": 2, "nested": {"id": 3, "input": "FAKE"}}
    _write(tmp_path, rows)
    nested: bytes = json.dumps({"id": 3, "input": "FAKE"}, separators=(",", ":")).encode()
    cases: bytes = (tmp_path / CASES_FILE).read_bytes()
    offsets: bytearray = bytearray((tmp_path / OFFSETS_FILE).read_bytes())
    # Tamper entry 3 (index 2) to point at the nested object; cases.json is byte-unchanged.
    offsets[2 * 16 : 3 * 16] = _ENTRY.pack(cases.index(nested), len(nested))
    (tmp_path / OFFSETS_FILE).write_bytes(bytes(offsets))
    board = IndexedBoard(tmp_path)

    error = _unavailable(board, (3, 4))

    assert "FAKE" not in str(error)


@pytest.mark.parametrize("kind", ["indexed", "legacy"])
def test_a_row_whose_id_is_true_is_refused(tmp_path: Path, kind: str) -> None:
    """A JSON ``true`` at position 1 is not Case 1, although ``True == 1`` in Python."""

    rows: list[dict[str, Any]] = [dict(row) for row in _ROWS]
    rows[0] = {"id": True, "input": "question 1"}
    if kind == "indexed":
        _write(tmp_path, rows)
        board: IndexedBoard | LegacyBoard = IndexedBoard(tmp_path)
    else:
        board = LegacyBoard(json.dumps(rows))

    _unavailable(board, (1, 3))


@pytest.mark.parametrize("kind", ["indexed", "legacy"])
def test_ids_that_are_not_ascending_and_distinct_are_refused(tmp_path: Path, kind: str) -> None:
    """``rows((2, 2))`` is a ``ValueError``, never the first two rows via the 1..N shortcut."""

    if kind == "indexed":
        _write(tmp_path, _ROWS)
        board: IndexedBoard | LegacyBoard = IndexedBoard(tmp_path)
    else:
        board = LegacyBoard(json.dumps(_ROWS))

    with pytest.raises(ValueError):
        board.rows((2, 2))
    with pytest.raises(ValueError):
        board.rows((3, 2))


def _tampered(
    tmp_path: Path, rows: list[dict[str, Any]], entries: dict[int, tuple[int, int]]
) -> IndexedBoard:
    """A board whose ``cases.json`` is untouched but whose offsets entries are rewritten.

    ``entries`` maps a Case position to the ``(offset, length)`` it should point at.
    """

    _write(tmp_path, rows)
    offsets: bytearray = bytearray((tmp_path / OFFSETS_FILE).read_bytes())
    for position, (offset, length) in entries.items():
        offsets[(position - 1) * 16 : position * 16] = _ENTRY.pack(offset, length)
    (tmp_path / OFFSETS_FILE).write_bytes(bytes(offsets))
    return IndexedBoard(tmp_path)


def _fake() -> bytes:
    return json.dumps({"id": 3, "input": "FAKE"}, separators=(",", ":")).encode()


def test_an_object_inside_a_nested_array_is_never_a_top_level_case(tmp_path: Path) -> None:
    """Review on #1636 (round 2): a delimiter byte cannot prove nesting depth.

    WHY: inside ``"nested":[{"id":3,"input":"FAKE"}]`` the inner object is preceded by ``[``
    and followed by ``]``, exactly like a top-level element, so a neighbour-byte check served
    FAKE as Case 3. Only a walk from Case 1 proves which tiles are the array's own elements.
    """

    rows: list[dict[str, Any]] = [dict(row) for row in _ROWS]
    rows[1] = {"id": 2, "nested": [{"id": 3, "input": "FAKE"}]}
    _write(tmp_path, rows)
    cases: bytes = (tmp_path / CASES_FILE).read_bytes()
    board = _tampered(tmp_path, rows, {3: (cases.index(_fake()), len(_fake()))})

    error = _unavailable(board, (3, 4))

    assert "FAKE" not in str(error)


def test_a_tampered_chain_around_the_selected_tile_is_still_refused(tmp_path: Path) -> None:
    """The pushed-out variant: entries 2, 3 and 4 are rewritten so the chain stays contiguous
    with one-byte gaps and every malformed tile lands on an UNSELECTED position.

    WHY: a check of only the selected tile and its neighbouring entries passes here (entry 3
    is FAKE, framed by ``,`` on both sides, and entries 2 and 4 are never read for
    ``rows((3,))``). INVARIANT: every tile from Case 1 to the largest selected id is proven a
    whole object at its position, so tile 2 (``{"id":2,"nested":[{"id":9}``) fails the walk.
    """

    rows: list[dict[str, Any]] = [dict(row) for row in _ROWS]
    rows[1] = {"id": 2, "nested": [{"id": 9}, {"id": 3, "input": "FAKE"}, {"id": 10}]}
    _write(tmp_path, rows)
    cases: bytes = (tmp_path / CASES_FILE).read_bytes()
    offsets: bytes = (tmp_path / OFFSETS_FILE).read_bytes()
    offset2, _ = _ENTRY.unpack(offsets[16:32])
    offset4, length4 = _ENTRY.unpack(offsets[48:64])
    fake_at: int = cases.index(_fake())
    board = _tampered(
        tmp_path,
        rows,
        {
            2: (offset2, fake_at - 1 - offset2),
            3: (fake_at, len(_fake())),
            4: (fake_at + len(_fake()) + 1, offset4 + length4 - (fake_at + len(_fake()) + 1)),
        },
    )

    error = _unavailable(board, (3,))

    assert "FAKE" not in str(error)
