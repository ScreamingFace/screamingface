"""The indexed store serves Cases as ASCII text, so one wide character cannot cost gigabytes.

STORY: as a researcher running every Case of a large picture Benchmark, the run's Cases step
fits the run's memory budget. Measured on EnigmaEval (1,158 Cases, a 381 MiB ``cases.json``):
the old read peaked at 5,048 MiB against a 2,560 MiB budget and was killed before the first
model call; this read peaks at 840 MiB.

WHY it was so large: Python stores a ``str`` at the width of its widest character. One Case
held U+1F815, so the whole 381-million-character text cost 4 bytes a character, and the read
held two such copies beside the file's bytes.

INVARIANT the suite defends: the served text is ASCII, it is the same JSON value as the rows on
disk, and url4 hands on exactly the item texts it handed on before.
"""

from __future__ import annotations

import gc
import json
import tracemalloc
from pathlib import Path
from typing import Any

import pytest

from screamingface_engine.benchmarks.board_store import (
    BOARD_FILE,
    CASES_FILE,
    OFFSETS_FILE,
    IndexedBoard,
    encode_board,
)
from url4.dag.semantics.collection import parse_collection

# Example: four Cases. Case 2 holds characters of every width a str can take: "é" (1 byte a
# character in a str), "π" (2) and "🠕" (U+1F815, the EnigmaEval character, 4).
_ROWS: list[dict[str, Any]] = [
    {"id": 1, "case_id": "c1", "input": "What is 6 times 7?"},
    {"id": 2, "case_id": "c2", "input": "café, π ≈ 3.14, arrow 🠕 up"},
    {"id": 3, "case_id": "c3", "input": 'a quote " and a backslash \\ stay as written'},
    {"id": 4, "case_id": "c4", "input": "last one"},
]


def _board(root: Path, rows: list[dict[str, Any]]) -> IndexedBoard:
    files = encode_board(rows)
    (root / BOARD_FILE).write_bytes(files.board)
    (root / OFFSETS_FILE).write_bytes(files.offsets)
    (root / CASES_FILE).write_bytes(files.cases)
    return IndexedBoard(root)


@pytest.mark.parametrize("count", [1, 2, 4])
def test_a_prefix_is_served_as_ascii_text_of_the_same_rows(tmp_path: Path, count: int) -> None:
    served: str = _board(tmp_path, _ROWS).head(count)

    assert served.isascii()
    assert json.loads(served) == _ROWS[:count]


def test_an_id_list_is_served_as_ascii_text_of_the_same_rows(tmp_path: Path) -> None:
    served: str = _board(tmp_path, _ROWS).rows((2, 4))

    assert served.isascii()
    assert json.loads(served) == [_ROWS[1], _ROWS[3]]


def test_a_character_above_the_basic_plane_is_served_as_a_surrogate_pair(tmp_path: Path) -> None:
    """A non-ASCII character gets the escape ``json.dumps`` writes, so any reader takes it back.

    Example: "🠕" is U+1F815, written as the pair ``\\ud83e\\udc15``; "π" is ``\\u03c0``.
    """

    served: str = _board(tmp_path, _ROWS).rows((2,))

    assert served == "[" + json.dumps(_ROWS[1], separators=(",", ":")) + "]"
    assert "\\ud83e\\udc15" in served
    assert "\\u03c0" in served


def test_an_all_ascii_benchmark_is_served_byte_for_byte_as_written(tmp_path: Path) -> None:
    """Most Benchmarks hold no non-ASCII character: for them the served bytes do not move."""

    rows: list[dict[str, Any]] = [_ROWS[0], {"id": 2, "input": {"parts": [{}, 2.50]}}]
    board: IndexedBoard = _board(tmp_path, rows)

    assert board.head(2).encode("ascii") == (tmp_path / CASES_FILE).read_bytes()


def test_url4_hands_on_the_same_item_texts_as_it_did_for_the_files_own_text(
    tmp_path: Path,
) -> None:
    """INVARIANT: escaping is invisible after url4's collection parse.

    WHY this is the test that makes the change safe: a run's Candidate calls are built from the
    item texts ``parse_collection`` returns, never from the served body. If these texts moved,
    every request, cached reply and frozen copy of a non-ASCII Benchmark would move with them.
    """

    board: IndexedBoard = _board(tmp_path, _ROWS)
    as_written: str = (tmp_path / CASES_FILE).read_bytes().decode("utf-8")

    assert parse_collection(board.head(4)) == parse_collection(as_written)
    assert parse_collection(board.rows((2, 3))) == parse_collection(as_written, window=(1, 3))


def test_an_ascii_character_is_never_respelled_even_del(tmp_path: Path) -> None:
    """The promise is "same value, ASCII text", not "the text ``json.dumps`` would write".

    WHY DEL: U+007F is the one ASCII character ``json.dumps`` escapes (as ``\\u007f``) that the
    writer leaves raw. The store leaves every ASCII character as written, so a row holding DEL
    keeps its bytes, beside a non-ASCII character or not. A test that compares served rows to
    ``json.dumps`` text would fail on such a row for no bug; compare values.
    """

    rows: list[dict[str, Any]] = [
        {"id": 1, "input": "del \x7f alone"},
        {"id": 2, "input": "del \x7f beside π"},
    ]
    board: IndexedBoard = _board(tmp_path, rows)

    served: str = board.head(2)

    assert served.isascii()
    assert json.loads(served) == rows
    assert served.count("\x7f") == 2
    assert "\\u007f" not in served


def _traced_peak(build: Any) -> int:
    gc.collect()
    tracemalloc.start()
    try:
        result = build()
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    del result
    return peak


def test_one_wide_character_does_not_multiply_the_memory_of_a_full_read(tmp_path: Path) -> None:
    """A full read peaks under 3x the file, even with one U+1F815 among the Cases.

    Worked example: 256 Cases of 16 KiB each make a 4 MiB ``cases.json``. Decoded as one string
    that holds "🠕", it costs 4 bytes a character, 16 MiB a copy; the old read held the file's
    bytes and two such copies, measured at 13x the file. Served row by row as ASCII, the rows and
    the joined text are 2x the file.
    """

    rows: list[dict[str, Any]] = [
        {"id": index, "input": ("🠕" if index == 200 else "") + "x" * 16384}
        for index in range(1, 257)
    ]
    board: IndexedBoard = _board(tmp_path, rows)
    file_bytes: int = (tmp_path / CASES_FILE).stat().st_size

    peak: int = _traced_peak(lambda: board.head(256))

    assert peak <= 3 * file_bytes, (peak, file_bytes)
