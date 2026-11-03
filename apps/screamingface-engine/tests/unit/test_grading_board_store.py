"""Grading reads an indexed board's selected Cases by seeking, not by streaming the file.

FEATURE (follow-up to OME-1789 and OME-1790): ``read_selected_cases`` streamed the whole
``cases.json`` to find a run's selected rows. When the bundle carries the per-Case offset index
(``board.json`` + ``cases.offsets``), it now reads one 16-byte entry and one row per selected
Case. Boards without an index keep the streaming reader.

INVARIANT the suite defends: for any selection — a prefix, ids out of order (181, 7, 90),
duplicates, ids outside the board — the indexed read returns exactly what the streaming reader
returns for the same rows, or raises the same error with the same text. An index that no longer
matches its rows is the bounded ``benchmark_unavailable``, never another Case's input.
"""

from __future__ import annotations

import json
import shutil
import struct
from collections.abc import Callable, Iterator
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
from screamingface_engine.benchmarks.shared_grading import case_grades
from screamingface_engine.benchmarks.shared_grading.case_grades import read_selected_cases
from url4.core.errors import ResolutionError


class BoardError(ValueError):
    """Stands in for a benchmark's own ``AggregateError``."""


_ENTRY = struct.Struct("<QQ")
_BOARD_SIZE = 200


def _rows(count: int = _BOARD_SIZE) -> list[dict[str, Any]]:
    return [
        {"id": i, "case_id": f"c{i}", "input": f"question {i} — π ≈ {i}?"}
        for i in range(1, count + 1)
    ]


def _write_indexed(root: Path, rows: list[dict[str, Any]]) -> Path:
    files = encode_board(rows)
    root.mkdir(parents=True, exist_ok=True)
    (root / BOARD_FILE).write_bytes(files.board)
    (root / OFFSETS_FILE).write_bytes(files.offsets)
    (root / CASES_FILE).write_bytes(files.cases)
    return root


def _write_streamed(root: Path, rows: list[dict[str, Any]]) -> Path:
    """The same ``cases.json`` bytes, with no index beside them."""

    root.mkdir(parents=True, exist_ok=True)
    (root / CASES_FILE).write_bytes(encode_board(rows).cases)
    return root


def _outcome(root: Path, case_ids: tuple[int, ...]) -> object:
    """What grading sees: the selected Cases, or the error class and its exact text."""

    try:
        selected = read_selected_cases(
            root, case_ids, benchmark_label="Board", error_type=BoardError
        )
    except BoardError as exc:
        return ("error", type(exc).__name__, str(exc))
    return [(case.case_id, case.input, dict(case.metadata)) for case in selected]


def _refuse_streaming(*_args: object, **_kwargs: object) -> Iterator[object]:
    raise AssertionError("an indexed board must not be streamed")


@pytest.fixture
def no_streaming(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Fail the test if the indexed path falls back to scanning the whole file."""

    monkeypatch.setattr(case_grades, "iter_array_rows", _refuse_streaming)
    yield


SELECTIONS: list[tuple[str, tuple[int, ...]]] = [
    ("prefix", (1, 2, 3)),
    ("one Case", (1,)),
    ("the last Case", (_BOARD_SIZE,)),
    ("non-prefix, out of order", (181, 7, 90)),
    ("duplicates", (5, 5, 2, 5)),
    ("empty", ()),
    ("zero", (0,)),
    ("negative", (-1,)),
    ("past the end", (_BOARD_SIZE + 1,)),
    ("in range, then past the end", (3, _BOARD_SIZE + 1)),
]


@pytest.mark.parametrize(("label", "case_ids"), SELECTIONS)
def test_indexed_selection_matches_the_streamed_reader(
    tmp_path: Path, label: str, case_ids: tuple[int, ...]
) -> None:
    rows = _rows()
    streamed = _outcome(_write_streamed(tmp_path / "streamed", rows), case_ids)
    indexed_root = _write_indexed(tmp_path / "indexed", rows)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(case_grades, "iter_array_rows", _refuse_streaming)
        indexed = _outcome(indexed_root, case_ids)
    assert indexed == streamed, label


def test_out_of_range_ids_keep_the_streamed_wording(tmp_path: Path, no_streaming: None) -> None:
    root = _write_indexed(tmp_path, _rows(3))
    with pytest.raises(BoardError, match="^Board Case 4 has no public input$"):
        read_selected_cases(root, (1, 4), benchmark_label="Board", error_type=BoardError)


ODD_ROWS: list[tuple[str, dict[str, Any]]] = [
    ("blank input", {"id": 2, "input": "   "}),
    ("non-text input", {"id": 2, "input": 7}),
    ("no input", {"id": 2}),
    # WHY: the index admits a row without an id at its position, but the streamed filter only
    # files rows that carry an int id — so grading must call that Case unanswerable both ways.
    ("no id", {"input": "anonymous"}),
]


@pytest.mark.parametrize(("label", "odd"), ODD_ROWS)
def test_a_row_grading_cannot_use_fails_the_same_way(
    tmp_path: Path, label: str, odd: dict[str, Any]
) -> None:
    rows: list[dict[str, Any]] = [{"id": 1, "input": "one"}, odd, {"id": 3, "input": "three"}]
    streamed = _outcome(_write_streamed(tmp_path / "streamed", rows), (3, 2))
    indexed_root = _write_indexed(tmp_path / "indexed", rows)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(case_grades, "iter_array_rows", _refuse_streaming)
        indexed = _outcome(indexed_root, (3, 2))
    assert indexed == streamed == ("error", "BoardError", "Board Case 2 has no public input"), label


def test_a_board_without_an_index_is_still_streamed(tmp_path: Path) -> None:
    root = _write_streamed(tmp_path, _rows(5))
    assert _outcome(root, (4, 2)) == [
        (4, "question 4 — π ≈ 4?", {}),
        (2, "question 2 — π ≈ 2?", {}),
    ]


def test_indexed_board_reads_rows_by_id_and_skips_ids_it_does_not_hold(tmp_path: Path) -> None:
    root = _write_indexed(tmp_path, _rows(4))
    rows = IndexedBoard(root).rows((4, 0, 2, 9, 2, -3))
    assert rows == {
        4: {"id": 4, "case_id": "c4", "input": "question 4 — π ≈ 4?"},
        2: {"id": 2, "case_id": "c2", "input": "question 2 — π ≈ 2?"},
    }


# ── a corrupt index is the bounded error, never another Case's input ─────────────────────


def _swap_entries(root: Path, first: int, second: int) -> None:
    entries = list(_ENTRY.iter_unpack((root / OFFSETS_FILE).read_bytes()))
    entries[first - 1], entries[second - 1] = entries[second - 1], entries[first - 1]
    (root / OFFSETS_FILE).write_bytes(b"".join(_ENTRY.pack(*entry) for entry in entries))


def _set_entry(root: Path, case_id: int, offset: int, length: int) -> None:
    raw = bytearray((root / OFFSETS_FILE).read_bytes())
    raw[(case_id - 1) * _ENTRY.size : case_id * _ENTRY.size] = _ENTRY.pack(offset, length)
    (root / OFFSETS_FILE).write_bytes(bytes(raw))


def _entry(root: Path, case_id: int) -> tuple[int, int]:
    raw = (root / OFFSETS_FILE).read_bytes()
    offset, length = _ENTRY.unpack(raw[(case_id - 1) * _ENTRY.size : case_id * _ENTRY.size])
    return offset, length


def _stale_size(root: Path) -> None:
    with (root / CASES_FILE).open("ab") as handle:
        handle.write(b" ")


def _swapped(root: Path) -> None:
    _swap_entries(root, 7, 90)


def _shifted(root: Path) -> None:
    offset, length = _entry(root, 7)
    _set_entry(root, 7, offset + 1, length)


def _past_the_file(root: Path) -> None:
    _set_entry(root, 7, (root / CASES_FILE).stat().st_size, 10)


def _before_the_array(root: Path) -> None:
    offset, length = _entry(root, 1)
    _set_entry(root, 7, 0, length + 1)


def _offsets_truncated(root: Path) -> None:
    raw = (root / OFFSETS_FILE).read_bytes()
    (root / OFFSETS_FILE).write_bytes(raw[: -_ENTRY.size])


def _board_json_garbage(root: Path) -> None:
    (root / BOARD_FILE).write_bytes(b"{not json")


def _same_size_rows_reordered(root: Path) -> None:
    rows = _rows()
    rows[6], rows[89] = rows[89], rows[6]
    (root / CASES_FILE).write_bytes(encode_board(rows).cases)


def _cases_missing(root: Path) -> None:
    (root / CASES_FILE).unlink()


CORRUPTIONS = [
    _stale_size,
    _swapped,
    _shifted,
    _past_the_file,
    _before_the_array,
    _offsets_truncated,
    _board_json_garbage,
    _same_size_rows_reordered,
    _cases_missing,
]


@pytest.mark.parametrize("corrupt", CORRUPTIONS, ids=lambda fn: fn.__name__.strip("_"))
def test_a_corrupt_index_is_the_bounded_unavailable_error(
    tmp_path: Path, corrupt: Any, no_streaming: None
) -> None:
    root = _write_indexed(tmp_path, _rows())
    corrupt(root)
    with pytest.raises(ResolutionError) as exc:
        read_selected_cases(root, (181, 7, 90), benchmark_label="Board", error_type=BoardError)
    assert exc.value.code == "benchmark_unavailable"
    assert str(exc.value).startswith("imported board cases are unavailable: ")


def test_only_the_selected_entries_are_checked(tmp_path: Path, no_streaming: None) -> None:
    """A broken entry the run never selects costs nothing and refuses nothing (O(selected))."""

    root = _write_indexed(tmp_path, _rows())
    _swap_entries(root, 50, 51)
    assert [case.case_id for case in _selected(root, (181, 7, 90))] == [181, 7, 90]


def _selected(root: Path, case_ids: tuple[int, ...]) -> list[Any]:
    return read_selected_cases(root, case_ids, benchmark_label="Board", error_type=BoardError)


# ── memory follows the selection, not the board ──────────────────────────────────────────


def _peak(root: Path, case_ids: tuple[int, ...]) -> int:
    import tracemalloc

    tracemalloc.start()
    try:
        selected = _selected(root, case_ids)
        peak: int = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert [case.case_id for case in selected] == list(case_ids)
    return peak


def _big_rows(count: int, row_chars: int) -> list[dict[str, Any]]:
    return [{"id": i, "input": f"{i:03d}" + "y" * row_chars} for i in range(1, count + 1)]


def test_peak_memory_scales_with_the_selection_not_the_board(tmp_path: Path) -> None:
    """INVARIANT: an indexed read holds the selected rows, whatever the board's size.

    Three FigQA-shaped boards in miniature (~100 KB rows): 100, 200 and 400 Cases, about 10, 20
    and 40 MB. Measured: selecting the same two Cases peaks at 512 KB on all three (the two
    kept inputs plus one row's bytes and parse in flight); twenty Cases peak at 2.3 MB, i.e.
    ~100 KB per extra Case. The streaming reader this replaces peaks at 5.6-5.7 MB on the
    two-Case selection (its 1 MiB read buffer), so the 1.2 MB bound fails a regression to
    streaming as well as to a full parse (over 40 MB here).
    """

    row_chars: int = 100_000
    peaks: dict[int, int] = {}
    for count in (100, 200, 400):
        root = _write_indexed(tmp_path / f"board-{count}", _big_rows(count, row_chars))
        peaks[count] = _peak(root, (90, 7))
        if count != 400:
            shutil.rmtree(root)
    two_rows: int = 2 * row_chars
    for count, peak in peaks.items():
        assert peak < 6 * two_rows, f"{count} Cases: peak {peak:,} B for two selected rows"
    assert max(peaks.values()) < 1.25 * min(peaks.values()), peaks

    twenty: int = _peak(tmp_path / "board-400", tuple(range(300, 320)))
    assert twenty > 3 * peaks[400], (twenty, peaks[400])
    assert twenty < 6 * 10 * two_rows, f"twenty Cases: peak {twenty:,} B"


def test_the_index_entry_layout_is_what_the_writer_wrote(tmp_path: Path) -> None:
    """Guards the test helpers above against the writer's format drifting under them."""

    root = _write_indexed(tmp_path, [{"id": 1, "input": "a"}])
    assert _entry(root, 1) == (1, len(json.dumps({"id": 1, "input": "a"}, separators=(",", ":"))))


def test_a_board_open_board_reads_whole_is_streamed_not_held(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``open_board`` alone decides which ``board.json`` records the index serves.

    WHY: a schema split is in flight (a v1 record goes to the whole-file read). Whatever
    ``open_board`` sends to its full read, grading streams instead — it never parses the whole
    board, and never second-guesses the decision.
    """

    root = _write_indexed(tmp_path, _rows(5))
    asked: list[Path] = []

    def whole_file_read(board_root: Path, read_legacy: Callable[[], str]) -> object:
        asked.append(board_root)
        read_legacy()
        raise AssertionError("grading must not receive a whole-file board")

    monkeypatch.setattr(case_grades, "open_board", whole_file_read)
    assert _outcome(root, (4, 2)) == [
        (4, "question 4 — π ≈ 4?", {}),
        (2, "question 2 — π ≈ 2?", {}),
    ]
    assert asked == [root]
