"""``board.json`` cannot talk admission out of a refusal (OME-1803, review on #1645).

FEATURE (OME-1803): admission trusts ``board.json``'s ``modalities`` instead of scanning the
rows, so the record itself must be both well-formed and bound to the Cases it describes.

INVARIANT the suite defends: a record whose set is not canonical (sorted, distinct, each one of
the non-text ``PART_MODALITIES`` values) fails to open as ``benchmark_unavailable``, so a PDF
board can never be admitted to a text-only model by a record that claims ``["text"]``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from screamingface_engine.benchmarks.board_store import (
    BOARD_FILE,
    CASES_FILE,
    OFFSETS_FILE,
    IndexedBoard,
    encode_board,
    open_board,
)
from screamingface_engine.benchmarks.contract import CANDIDATE_INPUT_V2_SCHEMA
from screamingface_engine.benchmarks.picture_admission import PART_MODALITIES
from url4.core.errors import ResolutionError

_PDF: dict[str, Any] = {
    "type": "file",
    "file": {"file_data": "data:application/pdf;base64,JVBERi0=", "filename": "paper.pdf"},
}


def _pdf_input() -> str:
    return json.dumps(
        {
            "schema": CANDIDATE_INPUT_V2_SCHEMA,
            "messages": [{"role": "user", "content": [_PDF, {"type": "text", "text": "Why?"}]}],
        },
        separators=(",", ":"),
    )


def _rows(*inputs: str) -> list[dict[str, Any]]:
    return [
        {"id": index, "case_id": f"c{index}", "input": value}
        for index, value in enumerate(inputs, start=1)
    ]


def _write(root: Path, rows: list[dict[str, Any]]) -> Path:
    files = encode_board(rows)
    root.mkdir(parents=True, exist_ok=True)
    (root / BOARD_FILE).write_bytes(files.board)
    (root / OFFSETS_FILE).write_bytes(files.offsets)
    (root / CASES_FILE).write_bytes(files.cases)
    return root


def _record(root: Path) -> dict[str, Any]:
    return json.loads((root / BOARD_FILE).read_bytes())


def _rewrite(root: Path, record: dict[str, Any]) -> None:
    (root / BOARD_FILE).write_bytes(json.dumps(record).encode())


def _never_read() -> str:
    raise AssertionError("the indexed path must not read the whole board")


def _unavailable(exc: pytest.ExceptionInfo[ResolutionError]) -> None:
    assert exc.value.code == "benchmark_unavailable"
    assert str(exc.value).startswith("imported board cases are unavailable:")


# ── blocker 1: the recorded set is canonical ───────────────────────────────────


def test_a_real_pdf_board_whose_record_says_text_does_not_open(tmp_path: Path) -> None:
    """The review's probe: ``modalities: ["text"]`` on a PDF board would admit a text model."""

    root = _write(tmp_path, _rows(_pdf_input(), "text"))
    assert _record(root)["modalities"] == ["pdf"]  # WHY: the control, the writer saw the PDF.
    _rewrite(root, {**_record(root), "modalities": ["text"]})

    with pytest.raises(ResolutionError) as exc:
        open_board(root, _never_read)
    _unavailable(exc)


@pytest.mark.parametrize(
    "modalities",
    [["text"], ["image", "text"], ["audio"], ["pdf", "image"], ["pdf", "pdf"], [""], ["PDF"]],
    ids=["text", "text beside image", "unknown", "unsorted", "repeated", "empty", "wrong case"],
)
def test_a_non_canonical_set_fails_closed(tmp_path: Path, modalities: list[str]) -> None:
    root = _write(tmp_path, _rows(_pdf_input()))
    _rewrite(root, {**_record(root), "modalities": modalities})

    with pytest.raises(ResolutionError) as exc:
        IndexedBoard(root)
    _unavailable(exc)


@pytest.mark.parametrize("modalities", [[], ["image"], ["pdf"], ["image", "pdf"]])
def test_every_canonical_set_opens(tmp_path: Path, modalities: list[str]) -> None:
    """The boundary: each sorted subset of the non-text table values is a valid record."""

    root = _write(tmp_path, _rows("text"))
    _rewrite(root, {**_record(root), "modalities": modalities})

    assert IndexedBoard(root).modalities() == frozenset(modalities)


def test_the_canonical_values_are_the_tables_non_text_values() -> None:
    """INVARIANT: the validator and the part table cannot drift; ``text`` is never a need."""

    assert sorted(set(PART_MODALITIES.values())) == ["image", "pdf"]
