"""An Imported Board records the input types its Cases need, and admission reads them (OME-1803).

FEATURE (OME-1803, owner 2026-11-03): ``board.json`` schema v2 carries ``modalities``, the sorted
non-text input types any Case needs (``image``, ``pdf``), instead of v1's ``has_pictures``. The
build-time scan and the rows path share ONE part-type table, so a picture or PDF board refuses a
Candidate model that cannot take it before anything is spent.

INVARIANT the suite defends: a board never admits a model its Cases are blind to. A v1 board is
re-scanned (its flag is never trusted for PDFs), and a record that cannot say what it needs
fails closed as ``benchmark_unavailable``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from screamingface_engine.benchmarks import board_store
from screamingface_engine.benchmarks.board_store import (
    BOARD_FILE,
    BOARD_SCHEMA,
    BOARD_SCHEMA_V1,
    CASES_FILE,
    OFFSETS_FILE,
    BoardStore,
    IndexedBoard,
    LegacyBoard,
    encode_board,
    open_board,
)
from screamingface_engine.benchmarks.case_selection import board_cases_handler
from screamingface_engine.benchmarks.contract import CANDIDATE_INPUT_V2_SCHEMA
from screamingface_engine.benchmarks.definition import candidate, link_candidate
from screamingface_engine.benchmarks.picture_admission import (
    PART_MODALITIES,
    cases_need_modalities,
    refuse_blind_candidate,
    register_model_sight,
    run_expression_scope,
)
from screamingface_engine.benchmarks.protocol import build_evaluation_protocol
from url4 import RelExpr, render, text
from url4.core.errors import ResolutionError
from url4.peer.server import Request, Url4Node

_PICTURE: dict[str, Any] = {
    "type": "image_url",
    "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="},
}
# WHY `JVBERi0=` ("%PDF-"): a data URI the envelope reader accepts; nothing here opens the file.
_PDF: dict[str, Any] = {
    "type": "file",
    "file": {"file_data": "data:application/pdf;base64,JVBERi0=", "filename": "paper.pdf"},
}


def _media(*parts: dict[str, Any]) -> str:
    return json.dumps(
        {
            "schema": CANDIDATE_INPUT_V2_SCHEMA,
            "messages": [{"role": "user", "content": [*parts, {"type": "text", "text": "Why?"}]}],
        },
        separators=(",", ":"),
    )


def _rows(*inputs: str) -> list[dict[str, Any]]:
    return [
        {"id": index, "case_id": f"c{index}", "input": value}
        for index, value in enumerate(inputs, start=1)
    ]


_BOARDS: dict[str, tuple[list[dict[str, Any]], list[str]]] = {
    "image only": (_rows("text", _media(_PICTURE)), ["image"]),
    "pdf only": (_rows(_media(_PDF), "text"), ["pdf"]),
    "both": (_rows(_media(_PDF), _media(_PICTURE)), ["image", "pdf"]),
    "both in one case": (_rows(_media(_PICTURE, _PDF)), ["image", "pdf"]),
    "text only": (_rows("text", "more text"), []),
}


def _write(root: Path, rows: list[dict[str, Any]]) -> Path:
    files = encode_board(rows)
    root.mkdir(parents=True, exist_ok=True)
    (root / BOARD_FILE).write_bytes(files.board)
    (root / OFFSETS_FILE).write_bytes(files.offsets)
    (root / CASES_FILE).write_bytes(files.cases)
    return root


def _rewrite_board_json(root: Path, record: object) -> None:
    (root / BOARD_FILE).write_bytes(json.dumps(record).encode())


def _never_read() -> str:
    raise AssertionError("the indexed path must not read the whole board")


# ── the build writes the set ───────────────────────────────────────────────────


@pytest.mark.parametrize(("name"), list(_BOARDS))
def test_the_build_records_the_modalities_the_cases_need(name: str) -> None:
    rows, expected = _BOARDS[name]

    record = json.loads(encode_board(rows).board)

    assert record["schema"] == BOARD_SCHEMA == "screamingface.board.v2"
    assert record["modalities"] == expected
    assert "has_pictures" not in record
    assert list(record) == ["schema", "case_count", "cases_bytes", "modalities"]


@pytest.mark.parametrize(("name"), list(_BOARDS))
def test_one_table_feeds_the_build_the_rows_path_and_the_legacy_scan(name: str) -> None:
    """The build-time scan, the rows path and the v1 fallback agree, because they share a table."""

    rows, expected = _BOARDS[name]
    legacy = LegacyBoard(encode_board(rows).cases.decode("utf-8"))

    assert json.loads(encode_board(rows).board)["modalities"] == sorted(cases_need_modalities(rows))
    assert legacy.modalities() == cases_need_modalities(rows) == frozenset(expected)


def test_the_table_maps_each_media_part_to_its_gateway_modality() -> None:
    """``text`` is never a need, and Office files are text by the time a Case is written."""

    assert dict(PART_MODALITIES) == {"image_url": "image", "file": "pdf"}


@pytest.mark.parametrize(("name"), list(_BOARDS))
def test_a_v2_board_serves_its_set_from_board_json(tmp_path: Path, name: str) -> None:
    rows, expected = _BOARDS[name]

    board = open_board(_write(tmp_path, rows), _never_read)

    assert isinstance(board, IndexedBoard)
    assert board.modalities() == frozenset(expected)


# ── admission from a v2 board ──────────────────────────────────────────────────


class _Reader:
    def __init__(self, modalities: Mapping[str, Sequence[str]]) -> None:
        self.modalities = modalities
        self.reads = 0

    def model_routes(self) -> Mapping[str, str]:
        return {"/model": "vendor/model"}

    async def input_modalities(self) -> Mapping[str, Sequence[str]]:
        self.reads += 1
        return self.modalities


def _run_url4() -> str:
    protocol = build_evaluation_protocol(
        cases_route="/cases",
        case_evaluation=candidate("$item.input", web_search=False),
        selected_case_count=1,
        available_case_count=1,
        aggregate_route="/aggregate",
    )
    return link_candidate(
        render(RelExpr(path="/model", context="$input", intent=text("Answer."))), protocol
    )


async def _awaited(value: Awaitable[str]) -> str:
    return await value


def _serve(board: BoardStore, listed: Sequence[str]) -> str:
    """One run of the board's Cases route with ``vendor/model`` listing ``listed``."""

    node = Url4Node()
    register_model_sight(node, _Reader({"vendor/model": listed}))
    with run_expression_scope(_run_url4()):
        served = board_cases_handler(lambda: board, node=node)(Request("/cases", "", "1", {}))
        assert not isinstance(served, str)
        return asyncio.run(_awaited(served))


_IMAGE_REFUSAL: str = (
    "This Benchmark's Cases carry pictures, and these models cannot take images: "
    "vendor/model. The gateway reports them as text-only; a model it knows nothing about "
    "counts as text-only too."
)
_PDF_REFUSAL: str = (
    "This Benchmark's Cases carry PDFs, and these models cannot take PDFs: vendor/model. The "
    "gateway does not list pdf among their input types; a model it knows nothing about cannot "
    "take PDFs either."
)


def test_a_v2_pdf_board_refuses_a_model_that_cannot_take_pdfs(tmp_path: Path) -> None:
    board = open_board(_write(tmp_path, _BOARDS["pdf only"][0]), _never_read)

    with pytest.raises(ResolutionError) as exc:
        _serve(board, ["text", "image"])

    assert exc.value.code == "intent_error"
    assert exc.value.permanent is True
    assert str(exc.value) == _PDF_REFUSAL


def test_a_v2_picture_board_refuses_a_blind_model_with_the_picture_sentence(
    tmp_path: Path,
) -> None:
    """INVARIANT (C9): the OME-1548 picture refusal is byte-identical through the v2 board."""

    board = open_board(_write(tmp_path, _BOARDS["image only"][0]), _never_read)

    with pytest.raises(ResolutionError) as exc:
        _serve(board, ["text", "pdf"])

    assert exc.value.code == "intent_error"
    assert str(exc.value) == _IMAGE_REFUSAL


def test_a_board_needing_both_names_every_gap_in_one_refusal(tmp_path: Path) -> None:
    board = open_board(_write(tmp_path, _BOARDS["both"][0]), _never_read)

    with pytest.raises(ResolutionError) as exc:
        _serve(board, ["text"])

    assert str(exc.value) == f"{_IMAGE_REFUSAL} {_PDF_REFUSAL}"


@pytest.mark.parametrize(
    ("name", "listed"),
    [("both", ["text", "image", "pdf"]), ("pdf only", ["text", "pdf"]), ("text only", ["text"])],
)
def test_a_v2_board_admits_a_model_that_lists_what_it_needs(
    tmp_path: Path, name: str, listed: list[str]
) -> None:
    rows = _BOARDS[name][0]
    board = open_board(_write(tmp_path, rows), _never_read)

    assert json.loads(_serve(board, listed)) == rows[:1]


def test_a_modality_with_no_sentence_of_its_own_is_still_refused_by_name() -> None:
    """A future table row (``audio``) refuses before its wording is written, never admits."""

    node = Url4Node()
    register_model_sight(node, _Reader({"vendor/model": ["text", "image", "pdf"]}))
    with run_expression_scope(_run_url4()), pytest.raises(ResolutionError) as exc:
        asyncio.run(refuse_blind_candidate(node, needs=frozenset({"audio"})))

    assert exc.value.code == "intent_error"
    assert "audio" in str(exc.value)
    assert "vendor/model" in str(exc.value)


# ── the v1 board: warned, re-scanned, never trusted for PDFs ───────────────────


def _v1_board(root: Path, rows: list[dict[str, Any]], *, has_pictures: bool) -> Path:
    """What an OME-1790 build wrote: the same index, with v1's flag instead of the set."""

    files = encode_board(rows)
    _write(root, rows)
    _rewrite_board_json(
        root,
        {
            "schema": BOARD_SCHEMA_V1,
            "case_count": len(rows),
            "has_pictures": has_pictures,
            "cases_bytes": len(files.cases),
        },
    )
    return root


def test_a_v1_board_falls_back_with_a_warning_and_still_catches_a_pdf(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = _BOARDS["pdf only"][0]
    root = _v1_board(tmp_path, rows, has_pictures=False)
    reads: list[str] = []
    scans: list[int] = []
    scan = board_store.cases_need_modalities

    def read_legacy() -> str:
        reads.append("read")
        return (root / CASES_FILE).read_text(encoding="utf-8")

    def counted(scanned: Sequence[Mapping[str, object]]) -> frozenset[str]:
        scans.append(len(scanned))
        return scan(scanned)

    monkeypatch.setattr(board_store, "cases_need_modalities", counted)
    with caplog.at_level(logging.WARNING):
        board = open_board(root, read_legacy)

    assert isinstance(board, LegacyBoard)
    assert reads == ["read"]
    assert any(BOARD_SCHEMA_V1 in record.getMessage() for record in caplog.records)
    # WHY has_pictures=False above: v1's flag says "text", the rows say PDF; the rows win.
    with pytest.raises(ResolutionError) as exc:
        _serve(board, ["text", "image"])
    assert str(exc.value) == _PDF_REFUSAL
    assert board.modalities() == frozenset({"pdf"})
    assert scans == [len(rows)]  # one scan of the whole file, cached for the second ask


# ── a record that cannot say what it needs fails closed ────────────────────────


def _unavailable(exc: pytest.ExceptionInfo[ResolutionError]) -> None:
    assert exc.value.code == "benchmark_unavailable"
    assert str(exc.value).startswith("imported board cases are unavailable:")


def test_an_unknown_board_schema_fails_closed(tmp_path: Path) -> None:
    root = _write(tmp_path, _BOARDS["pdf only"][0])
    record = json.loads((root / BOARD_FILE).read_bytes())
    _rewrite_board_json(root, {**record, "schema": "screamingface.board.v3"})

    with pytest.raises(ResolutionError) as exc:
        open_board(root, _never_read)
    _unavailable(exc)


def _v2_record(root: Path) -> dict[str, Any]:
    return json.loads((root / BOARD_FILE).read_bytes())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("modalities", "image"),
        ("modalities", [1]),
        ("modalities", ["image", None]),
        ("modalities", None),
        ("case_count", "1"),
        ("case_count", True),
        ("cases_bytes", "9"),
    ],
    ids=[
        "modalities a string",
        "modalities a number member",
        "modalities a null member",
        "modalities null",
        "str count",
        "bool count",
        "str size",
    ],
)
def test_one_bad_field_on_an_otherwise_valid_v2_record_is_refused(
    tmp_path: Path, field: str, value: object
) -> None:
    """Each reason is isolated: every other field is the writer's own, valid v2 value."""

    root = _write(tmp_path, _BOARDS["image only"][0])
    record = _v2_record(root)
    IndexedBoard(root)  # WHY: the control, the untouched record opens.
    _rewrite_board_json(root, {**record, field: value})

    with pytest.raises(ResolutionError) as exc:
        open_board(root, _never_read)
    _unavailable(exc)


def test_a_v2_record_without_modalities_is_refused(tmp_path: Path) -> None:
    root = _write(tmp_path, _BOARDS["text only"][0])
    record = _v2_record(root)
    del record["modalities"]
    _rewrite_board_json(root, record)

    with pytest.raises(ResolutionError) as exc:
        open_board(root, _never_read)
    _unavailable(exc)
