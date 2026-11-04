"""``board.json`` cannot talk admission out of a refusal (OME-1803, review on #1645).

FEATURE (OME-1803): admission trusts ``board.json``'s ``modalities`` instead of scanning the
rows, so the record itself must be both well-formed and bound to the Cases it describes.

INVARIANT the suite defends: a record whose set is not canonical (sorted, distinct, each one of
the non-text ``PART_MODALITIES`` values) fails to open as ``benchmark_unavailable``, so a PDF
board can never be admitted to a text-only model by a record that claims ``["text"]``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from screamingface_engine.benchmarks import board_record
from screamingface_engine.benchmarks.board_store import (
    BOARD_FILE,
    BOARD_SCHEMA,
    CASES_FILE,
    OFFSETS_FILE,
    IndexedBoard,
    encode_board,
    open_board,
)
from screamingface_engine.benchmarks.case_selection import board_cases_handler
from screamingface_engine.benchmarks.contract import CANDIDATE_INPUT_V2_SCHEMA
from screamingface_engine.benchmarks.definition import candidate, link_candidate
from screamingface_engine.benchmarks.picture_admission import (
    PART_MODALITIES,
    register_model_sight,
    run_expression_scope,
)
from screamingface_engine.benchmarks.protocol import build_evaluation_protocol
from url4 import RelExpr, render, text
from url4.core.errors import ResolutionError
from url4.peer.server import Request, Url4Node

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


# ── blocker 2: the record is bound to the Cases by a digest (owner, 2026-11-04) ──


class _Reader:
    """The gateway's model list, counting reads so a refusal can prove none happened."""

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


async def _awaited(value: Awaitable[str] | str) -> str:
    assert not isinstance(value, str)
    return await value


def _same_size_text_rows(pdf_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Text rows whose every encoded row is exactly as long as its PDF counterpart."""

    padded: list[str] = []
    for row in pdf_rows:
        encoded_input: int = len(json.dumps(row["input"], ensure_ascii=False))
        padded.append("t" * (encoded_input - 2))  # WHY -2: the string's own quotes.
    return _rows(*padded)


def test_stale_text_metadata_beside_same_size_pdf_cases_is_refused_before_the_model_list(
    tmp_path: Path,
) -> None:
    """The review's probe: a text build's record and index next to a PDF build's Cases.

    Size and offsets agree, so only the digest can tell; admission would see ``[]``, return
    before reading ``/v1/models``, and hand a PDF to a text-only model.
    """

    pdf_rows = _rows(_pdf_input(), _pdf_input())
    text_rows = _same_size_text_rows(pdf_rows)
    stale = encode_board(text_rows)
    root = _write(tmp_path, pdf_rows)
    assert len(stale.cases) == (root / CASES_FILE).stat().st_size
    assert stale.offsets == (root / OFFSETS_FILE).read_bytes()
    assert json.loads(stale.board)["modalities"] == []
    (root / BOARD_FILE).write_bytes(stale.board)

    node = Url4Node()
    reader = _Reader({"vendor/model": ["text"]})
    register_model_sight(node, reader)
    handler = board_cases_handler(lambda: open_board(root, _never_read), node=node)
    with run_expression_scope(_run_url4()), pytest.raises(ResolutionError) as exc:
        asyncio.run(_awaited(handler(Request("/cases", "", "1", {}))))

    _unavailable(exc)
    assert reader.reads == 0


def test_the_writer_records_the_cases_digest_under_schema_v3() -> None:
    files = encode_board(_rows(_pdf_input(), "text"))
    record = json.loads(files.board)

    assert record["schema"] == BOARD_SCHEMA == "screamingface.board.v3"
    assert record["cases_sha256"] == hashlib.sha256(files.cases).hexdigest()
    assert list(record) == ["schema", "case_count", "cases_bytes", "modalities", "cases_sha256"]


@pytest.mark.parametrize(
    "digest",
    [None, "", hashlib.sha256(b"other").hexdigest(), 7, "Z" * 64],
    ids=["null", "empty", "another file's", "a number", "not hex"],
)
def test_a_wrong_digest_fails_closed(tmp_path: Path, digest: object) -> None:
    root = _write(tmp_path, _rows(_pdf_input()))
    IndexedBoard(root)  # WHY: the control, the writer's own record opens.
    _rewrite(root, {**_record(root), "cases_sha256": digest})

    with pytest.raises(ResolutionError) as exc:
        open_board(root, _never_read)
    _unavailable(exc)


def test_a_missing_digest_fails_closed(tmp_path: Path) -> None:
    root = _write(tmp_path, _rows(_pdf_input()))
    record = _record(root)
    del record["cases_sha256"]
    _rewrite(root, record)

    with pytest.raises(ResolutionError) as exc:
        open_board(root, _never_read)
    _unavailable(exc)


def test_a_v2_board_is_refused_and_asks_for_a_re_prepare(tmp_path: Path) -> None:
    """Owner, 2026-11-04: v2 carried no digest, so it is refused, never scanned or trusted."""

    root = _write(tmp_path, _rows(_pdf_input()))
    record = _record(root)
    del record["cases_sha256"]
    _rewrite(root, {**record, "schema": "screamingface.board.v2"})

    with pytest.raises(ResolutionError) as exc:
        open_board(root, _never_read)
    _unavailable(exc)
    assert "re-prepare" in str(exc.value)


def test_a_cases_file_changed_after_the_build_is_refused(tmp_path: Path) -> None:
    """One byte flipped inside a row: same size, same offsets, valid JSON, other content."""

    root = _write(tmp_path, _rows("abc", "def"))
    cases = (root / CASES_FILE).read_bytes()
    (root / CASES_FILE).write_bytes(cases.replace(b"abc", b"abd"))

    with pytest.raises(ResolutionError) as exc:
        open_board(root, _never_read)
    _unavailable(exc)


def test_the_digest_is_streamed_never_a_whole_file_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """INVARIANT (OME-1790 memory budget): opening holds one block of cases.json, not all of it."""

    root = _write(tmp_path, _rows(*("x" * 300 for _ in range(50))))
    whole: list[str] = []
    read_bytes = Path.read_bytes
    read_text = Path.read_text

    def guarded_bytes(self: Path) -> bytes:
        if self.name == CASES_FILE:
            whole.append("read_bytes")
        return read_bytes(self)

    def guarded_text(self: Path, *args: Any, **kwargs: Any) -> str:
        if self.name == CASES_FILE:
            whole.append("read_text")
        return read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", guarded_bytes)
    monkeypatch.setattr(Path, "read_text", guarded_text)
    monkeypatch.setattr(board_record, "_DIGEST_BLOCK", 64)

    board = open_board(root, _never_read)

    assert board.case_count() == 50
    assert whole == []
