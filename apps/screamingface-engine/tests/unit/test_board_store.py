"""An Imported Board is read in O(selected Cases) through a byte-offset index (OME-1790).

FEATURE (OME-1790, Option B): the writer keeps ``cases.json`` byte for byte and adds
``cases.offsets`` (where each row sits inside it) and ``board.json`` (how many Cases, whether
any carries a picture). The Cases route then reads only the selected prefix, and picture
admission reads one flag instead of every row.

INVARIANT the suite defends: the rows served through the index are exactly the rows a full
read would serve, and an index that no longer matches its ``cases.json`` is a bounded
"unavailable" error, never wrong rows.
"""

from __future__ import annotations

import json
import logging
import struct
from pathlib import Path
from typing import Any

import pytest

from screamingface_engine.benchmarks.board_store import (
    BOARD_FILE,
    BOARD_SCHEMA,
    CASES_FILE,
    OFFSETS_FILE,
    IndexedBoard,
    LegacyBoard,
    encode_board,
    open_board,
)
from screamingface_engine.benchmarks.contract import CANDIDATE_INPUT_V2_SCHEMA
from screamingface_engine.benchmarks.picture_admission import cases_need_pictures
from url4.core.errors import ResolutionError

_PNG: str = "data:image/png;base64,iVBORw0KGgo="
_PICTURE_INPUT: str = json.dumps(
    {
        "schema": CANDIDATE_INPUT_V2_SCHEMA,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": _PNG}},
                    {"type": "text", "text": "How tall is the bar?"},
                ],
            }
        ],
    },
    separators=(",", ":"),
)


def _rows(*inputs: str) -> list[dict[str, Any]]:
    return [
        {"id": index, "case_id": f"c{index}", "input": text}
        for index, text in enumerate(inputs, start=1)
    ]


_TEXT_ROWS: list[dict[str, Any]] = _rows("What is 6 × 7?", "Zwei — vier", "π ≈ ?", "last one")


def _legacy_bytes(rows: list[dict[str, Any]]) -> bytes:
    """What the writer wrote before OME-1790."""

    return json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _write(root: Path, rows: list[dict[str, Any]]) -> Path:
    files = encode_board(rows)
    root.mkdir(parents=True, exist_ok=True)
    (root / BOARD_FILE).write_bytes(files.board)
    (root / OFFSETS_FILE).write_bytes(files.offsets)
    (root / CASES_FILE).write_bytes(files.cases)
    return root


# ── the format ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "rows",
    [_TEXT_ROWS, _rows("only"), _rows(_PICTURE_INPUT, "text"), []],
    ids=["non-ascii", "single row", "picture", "empty"],
)
def test_cases_json_is_byte_identical_to_the_pre_change_writer(rows: list[dict[str, Any]]) -> None:
    assert encode_board(rows).cases == _legacy_bytes(rows)


def test_every_offset_slice_parses_to_its_row() -> None:
    files = encode_board(_TEXT_ROWS)
    entries = list(struct.iter_unpack("<QQ", files.offsets))

    assert len(files.offsets) == 16 * len(_TEXT_ROWS)
    for (offset, length), row in zip(entries, _TEXT_ROWS, strict=True):
        assert json.loads(files.cases[offset : offset + length]) == row


def test_board_json_records_count_pictures_and_cases_size() -> None:
    files = encode_board(_rows("text", _PICTURE_INPUT))

    assert json.loads(files.board) == {
        "schema": BOARD_SCHEMA,
        "case_count": 2,
        "has_pictures": True,
        "cases_bytes": len(files.cases),
    }
    assert json.loads(encode_board(_TEXT_ROWS).board)["has_pictures"] is False


def test_the_files_are_a_pure_function_of_the_rows() -> None:
    """Spec acceptance 7: two prepares of the same pins give identical files."""

    assert encode_board(_TEXT_ROWS) == encode_board([dict(row) for row in _TEXT_ROWS])


# ── the indexed store ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("count", [1, 2, 4])
def test_head_equals_the_legacy_slice(tmp_path: Path, count: int) -> None:
    """Spec acceptance 2: byte-identical to ``json.dumps(json.loads(cases.json)[:N])``."""

    board = IndexedBoard(_write(tmp_path, _TEXT_ROWS))

    expected = json.dumps(_TEXT_ROWS[:count], ensure_ascii=False, separators=(",", ":"))
    assert board.head(count) == expected
    assert board.case_count() == 4
    assert board.has_pictures() is False


def test_head_out_of_range_is_refused(tmp_path: Path) -> None:
    board = IndexedBoard(_write(tmp_path, _TEXT_ROWS))

    for count in (0, 5, -1):
        with pytest.raises(ValueError):
            board.head(count)


def test_a_picture_board_says_so_without_reading_the_rows(tmp_path: Path) -> None:
    root = _write(tmp_path, _rows("text", _PICTURE_INPUT))
    board = IndexedBoard(root)
    # WHY overwrite the rows with text of the same size: the flag must come from board.json.
    (root / CASES_FILE).write_bytes(b" " * (root / CASES_FILE).stat().st_size)

    assert board.has_pictures() is True


def _unavailable(exc: pytest.ExceptionInfo[ResolutionError]) -> None:
    assert exc.value.code == "benchmark_unavailable"
    assert str(exc.value).startswith("imported board cases are unavailable:")


def test_a_cases_file_of_another_size_is_a_stale_index(tmp_path: Path) -> None:
    root = _write(tmp_path, _TEXT_ROWS)
    (root / CASES_FILE).write_bytes((root / CASES_FILE).read_bytes()[:-5])

    with pytest.raises(ResolutionError) as exc:
        IndexedBoard(root)
    _unavailable(exc)


def test_an_offsets_file_of_the_wrong_length_is_refused(tmp_path: Path) -> None:
    root = _write(tmp_path, _TEXT_ROWS)
    (root / OFFSETS_FILE).write_bytes((root / OFFSETS_FILE).read_bytes()[:-16])

    with pytest.raises(ResolutionError) as exc:
        IndexedBoard(root)
    _unavailable(exc)


def test_offsets_that_point_at_other_rows_are_refused(tmp_path: Path) -> None:
    """A same-size ``cases.json`` with other row lengths must never serve shifted rows."""

    root = _write(tmp_path, _rows("aaaa", "b"))
    other = encode_board(_rows("a", "bbbb"))
    assert len(other.cases) == (root / CASES_FILE).stat().st_size
    (root / OFFSETS_FILE).write_bytes(other.offsets)

    board = IndexedBoard(root)
    with pytest.raises(ResolutionError) as exc:
        board.head(1)
    _unavailable(exc)


@pytest.mark.parametrize(
    "board_json",
    [
        b"not json",
        b"[]",
        json.dumps({"schema": "screamingface.board.v9", "case_count": 1}).encode(),
        json.dumps(
            {"schema": BOARD_SCHEMA, "case_count": "1", "has_pictures": False, "cases_bytes": 9}
        ).encode(),
        json.dumps(
            {"schema": BOARD_SCHEMA, "case_count": 1, "has_pictures": 0, "cases_bytes": 9}
        ).encode(),
        json.dumps(
            {"schema": BOARD_SCHEMA, "case_count": True, "has_pictures": False, "cases_bytes": 9}
        ).encode(),
    ],
    ids=["unparseable", "not an object", "unknown schema", "str count", "int flag", "bool count"],
)
def test_a_broken_board_json_is_refused(tmp_path: Path, board_json: bytes) -> None:
    root = _write(tmp_path, _TEXT_ROWS)
    (root / BOARD_FILE).write_bytes(board_json)

    with pytest.raises(ResolutionError) as exc:
        IndexedBoard(root)
    _unavailable(exc)


def test_a_missing_cases_file_beside_an_index_is_refused(tmp_path: Path) -> None:
    root = _write(tmp_path, _TEXT_ROWS)
    (root / CASES_FILE).unlink()

    with pytest.raises(ResolutionError) as exc:
        IndexedBoard(root)
    _unavailable(exc)


# ── the legacy store and the fallback ──────────────────────────────────────────


def test_legacy_store_serves_the_same_rows_and_scans_for_pictures() -> None:
    rows = _rows("text", _PICTURE_INPUT, "more")
    board = LegacyBoard(_legacy_bytes(rows).decode("utf-8"))

    assert board.case_count() == 3
    assert board.head(2) == json.dumps(rows[:2], ensure_ascii=False, separators=(",", ":"))
    assert board.has_pictures() is cases_need_pictures(rows) is True


@pytest.mark.parametrize(
    ("text", "count"),
    [("not json", 1), ('{"id": 1}', 1), ('[{"id": 1}, 2]', 2)],
    ids=["unparseable", "not a list", "a row that is not an object"],
)
def test_legacy_store_refuses_malformed_boards_as_value_errors(text: str, count: int) -> None:
    with pytest.raises(ValueError):
        LegacyBoard(text).head(count)


def test_a_bundle_without_an_index_falls_back_with_a_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / CASES_FILE).write_bytes(_legacy_bytes(_TEXT_ROWS))
    reads: list[str] = []

    def read_legacy() -> str:
        reads.append("read")
        return (tmp_path / CASES_FILE).read_text(encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        board = open_board(tmp_path, read_legacy)

    assert isinstance(board, LegacyBoard)
    assert reads == ["read"]
    assert board.head(4) == _legacy_bytes(_TEXT_ROWS).decode("utf-8")
    assert any(OFFSETS_FILE in record.getMessage() for record in caplog.records)


def test_a_bundle_with_an_index_never_reads_the_whole_file(tmp_path: Path) -> None:
    def read_legacy() -> str:
        raise AssertionError("the indexed path must not read the whole board")

    board = open_board(_write(tmp_path, _TEXT_ROWS), read_legacy)

    assert isinstance(board, IndexedBoard)
    assert json.loads(board.head(1)) == _TEXT_ROWS[:1]


def _rewrite_offsets(root: Path, entries: list[tuple[int, int]]) -> None:
    (root / OFFSETS_FILE).write_bytes(b"".join(struct.pack("<QQ", *entry) for entry in entries))


def test_offsets_that_do_not_start_at_the_first_row_are_refused(tmp_path: Path) -> None:
    root = _write(tmp_path, _TEXT_ROWS)
    entries = list(struct.iter_unpack("<QQ", (root / OFFSETS_FILE).read_bytes()))
    _rewrite_offsets(root, [(entries[1][0], entries[0][1]), *entries[1:]])

    with pytest.raises(ResolutionError) as exc:
        IndexedBoard(root).head(1)
    _unavailable(exc)


def test_offsets_out_of_served_order_are_refused(tmp_path: Path) -> None:
    root = _write(tmp_path, _TEXT_ROWS)
    entries = list(struct.iter_unpack("<QQ", (root / OFFSETS_FILE).read_bytes()))
    _rewrite_offsets(root, [entries[0], entries[2], entries[1], entries[3]])

    with pytest.raises(ResolutionError) as exc:
        IndexedBoard(root).head(3)
    _unavailable(exc)


def test_a_cases_file_removed_after_opening_is_the_bounded_error(tmp_path: Path) -> None:
    root = _write(tmp_path, _TEXT_ROWS)
    board = IndexedBoard(root)
    (root / CASES_FILE).unlink()

    with pytest.raises(ResolutionError) as exc:
        board.head(1)
    _unavailable(exc)
