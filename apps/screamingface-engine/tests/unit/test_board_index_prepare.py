"""The prepare step writes the board index, and the imported Cases route reads through it
(OME-1790).

INVARIANT: ``cases.json`` stays byte for byte what the writer wrote before, and it is still
written last — it is the bundle's completion marker, so a bundle that has it has its index.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from screamingface_engine.benchmarks.board_store import (
    BOARD_FILE,
    CASES_FILE,
    OFFSETS_FILE,
    IndexedBoard,
    LegacyBoard,
    encode_board,
)
from screamingface_engine.benchmarks.case_selection import board_cases_handler
from screamingface_engine_inspect.prepare import SKIPPED_MARKER, PreparedCase, _write_cases
from screamingface_engine_inspect.single_shot import _board, _enveloped_inputs
from url4.core.errors import ResolutionError
from url4.peer.server import Request

_PREPARED: list[PreparedCase] = [
    {
        "case": {"id": index, "case_id": str(index), "input": text},
        "grading_material": {"target": str(index)},
    }
    for index, text in enumerate(["What is 6 × 7?", "Zwei plus zwei — vier", "π"], start=1)
]


def _pre_change_bytes(prepared: list[PreparedCase]) -> bytes:
    return json.dumps(
        [item["case"] for item in prepared], ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")


def test_the_writer_keeps_cases_json_and_adds_the_index(tmp_path: Path) -> None:
    _write_cases(_PREPARED, tmp_path)

    expected = encode_board([item["case"] for item in _PREPARED])
    assert (tmp_path / CASES_FILE).read_bytes() == _pre_change_bytes(_PREPARED)
    assert (tmp_path / BOARD_FILE).read_bytes() == expected.board
    assert (tmp_path / OFFSETS_FILE).read_bytes() == expected.offsets
    assert (tmp_path / "targets" / "2.json").read_text(encoding="utf-8") == '{"target":"2"}'


def test_the_index_is_written_before_the_completion_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[str] = []
    write_bytes = Path.write_bytes
    write_text = Path.write_text

    def recording_bytes(self: Path, data: Any) -> int:
        order.append(self.name)
        return write_bytes(self, data)

    def recording_text(self: Path, data: str, *args: Any, **kwargs: Any) -> int:
        order.append(self.name)
        return write_text(self, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_bytes", recording_bytes)
    monkeypatch.setattr(Path, "write_text", recording_text)
    _write_cases(_PREPARED, tmp_path)

    assert order[-1] == CASES_FILE
    assert order.index(BOARD_FILE) < order.index(CASES_FILE)
    assert order.index(OFFSETS_FILE) < order.index(CASES_FILE)


def test_two_prepares_write_the_same_bytes(tmp_path: Path) -> None:
    """Spec acceptance 7: the index is byte-reproducible."""

    _write_cases(_PREPARED, tmp_path / "a")
    _write_cases(_PREPARED, tmp_path / "b")

    for name in (BOARD_FILE, OFFSETS_FILE, CASES_FILE):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()


def test_the_writer_still_refuses_a_used_bundle(tmp_path: Path) -> None:
    _write_cases(_PREPARED, tmp_path)

    with pytest.raises(Exception, match="non-empty directory"):
        _write_cases(_PREPARED, tmp_path)


# ── the imported Cases route's opener ──────────────────────────────────────────


def _serve(root: Path, count: int, *, envelope: bool = False) -> list[dict[str, Any]]:
    handler = board_cases_handler(_board(root), serve=_enveloped_inputs if envelope else None)
    served = handler(Request("/cases", "", str(count), {}))
    assert isinstance(served, str)
    return json.loads(served)


def test_a_prepared_bundle_opens_through_its_index(tmp_path: Path) -> None:
    _write_cases(_PREPARED, tmp_path)

    assert isinstance(_board(tmp_path)(), IndexedBoard)
    assert _serve(tmp_path, 2) == [item["case"] for item in _PREPARED[:2]]


def test_the_envelope_wraps_the_selected_rows_as_the_whole_board_read_did(tmp_path: Path) -> None:
    _write_cases(_PREPARED, tmp_path)
    whole: list[dict[str, Any]] = json.loads(
        _enveloped_inputs((tmp_path / CASES_FILE).read_text(encoding="utf-8"))
    )

    assert _serve(tmp_path, 2, envelope=True) == whole[:2]


def test_an_old_bundle_falls_back_to_the_full_read_with_a_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / CASES_FILE).write_bytes(_pre_change_bytes(_PREPARED))

    with caplog.at_level(logging.WARNING):
        board = _board(tmp_path)()

    assert isinstance(board, LegacyBoard)
    assert caplog.records, "the fallback must be logged"
    assert _serve(tmp_path, 3) == [item["case"] for item in _PREPARED]


def test_a_skipped_board_still_names_why_it_has_no_questions(tmp_path: Path) -> None:
    (tmp_path / SKIPPED_MARKER).write_text("gated dataset, no token\n", encoding="utf-8")

    with pytest.raises(ResolutionError) as exc:
        _board(tmp_path)()

    assert exc.value.code == "benchmark_unavailable"
    assert "gated dataset, no token" in str(exc.value)


def test_a_missing_bundle_is_the_bounded_unavailable_error(tmp_path: Path) -> None:
    with pytest.raises(ResolutionError) as exc:
        _board(tmp_path / "absent")()

    assert exc.value.code == "benchmark_unavailable"
    assert str(exc.value).startswith("imported board cases are unavailable:")
