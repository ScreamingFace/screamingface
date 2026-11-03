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
