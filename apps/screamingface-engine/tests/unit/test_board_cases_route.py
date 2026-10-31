"""The Imported-Board Cases route serves only the selected Cases (OME-1790).

FEATURE (OME-1790): the route opens the board through its index, checks the selection against
``board.json``'s Case count, and serves only the first N rows. Picture admission takes the
board's ``has_pictures`` flag instead of scanning every row.

INVARIANT: a bad selection is the same permanent ``benchmark_contract_error`` as before, and a
picture board still refuses a blind Candidate model before anything is spent.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from screamingface_engine.benchmarks import case_selection
from screamingface_engine.benchmarks.board_store import (
    BOARD_FILE,
    CASES_FILE,
    OFFSETS_FILE,
    BoardStore,
    IndexedBoard,
    encode_board,
)
from screamingface_engine.benchmarks.case_selection import board_cases_handler, install_board_cases
from screamingface_engine.benchmarks.definition import candidate, link_candidate
from screamingface_engine.benchmarks.picture_admission import (
    refuse_blind_candidate,
    register_model_sight,
    run_expression_scope,
)
from screamingface_engine.benchmarks.protocol import build_evaluation_protocol
from url4 import RelExpr, render, text
from url4.core.errors import ResolutionError
from url4.peer.server import Request, Url4Node

_ROWS: list[dict[str, Any]] = [
    {"id": index, "case_id": f"c{index}", "input": f"question {index}"} for index in range(1, 6)
]


def _board(tmp_path: Path, rows: list[dict[str, Any]] = _ROWS) -> IndexedBoard:
    files = encode_board(rows)
    (tmp_path / BOARD_FILE).write_bytes(files.board)
    (tmp_path / OFFSETS_FILE).write_bytes(files.offsets)
    (tmp_path / CASES_FILE).write_bytes(files.cases)
    return IndexedBoard(tmp_path)


def _request(intent: str) -> Request:
    return Request("/cases", "", intent, {})


@pytest.mark.parametrize("count", [1, 2, 5])
def test_the_route_serves_only_the_selected_rows(tmp_path: Path, count: int) -> None:
    board = _board(tmp_path)

    served = board_cases_handler(lambda: board)(_request(str(count)))

    assert isinstance(served, str)
    assert json.loads(served) == _ROWS[:count]


@pytest.mark.parametrize("intent", ["0", "6", "-1", "two", ""])
def test_a_bad_selection_is_the_permanent_contract_error(tmp_path: Path, intent: str) -> None:
    board = _board(tmp_path)

    with pytest.raises(ResolutionError) as exc:
        board_cases_handler(lambda: board)(_request(intent))

    assert exc.value.code == "benchmark_contract_error"
    assert exc.value.permanent is True


def test_serve_runs_over_the_selected_rows_only(tmp_path: Path) -> None:
    """The envelope (``serve``) sees N rows, never the board."""

    board = _board(tmp_path)
    seen: list[int] = []

    def serve(selected: str) -> str:
        seen.append(len(json.loads(selected)))
        return selected

    board_cases_handler(lambda: board, serve=serve)(_request("2"))

    assert seen == [2]


def test_a_serve_error_is_not_rewritten_as_a_selection_error(tmp_path: Path) -> None:
    """A broken Case names itself (OME-1271), as the whole-board envelope did."""

    board = _board(tmp_path)

    def serve(selected: str) -> str:
        raise ValueError("case 2: broken envelope")

    with pytest.raises(ValueError, match="case 2"):
        board_cases_handler(lambda: board, serve=serve)(_request("2"))


def test_install_registers_the_route_once(tmp_path: Path) -> None:
    board = _board(tmp_path)
    node = Url4Node()

    install_board_cases(node, "/board/cases", lambda: board)
    install_board_cases(node, "/board/cases", lambda: board)

    assert "/board/cases" in node.processor_routes()


class _Flagged:
    """A board whose rows say nothing, so only its flag can make it a picture board."""

    def __init__(self, pictures: bool) -> None:
        self.pictures = pictures

    def case_count(self) -> int:
        return 1

    def has_pictures(self) -> bool:
        return self.pictures

    def head(self, count: int) -> str:
        return '[{"id":1,"input":"text"}]'


async def _awaited(value: Awaitable[str]) -> str:
    return await value


def test_admission_takes_the_boards_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[bool] = []

    async def spy(node: Url4Node, *, needs_pictures: bool) -> None:
        calls.append(needs_pictures)

    monkeypatch.setattr(case_selection, "refuse_blind_candidate", spy)
    node = Url4Node()
    for pictures in (True, False):
        store: BoardStore = _Flagged(pictures)
        served = board_cases_handler(lambda store=store: store, node=node)(_request("1"))
        assert not isinstance(served, str)
        assert json.loads(asyncio.run(_awaited(served))) == [{"id": 1, "input": "text"}]

    assert calls == [True, False]


# ── refuse_blind_candidate: the flag form of the OME-1548 check ───────────────


class _Reader:
    def __init__(self, modalities: Mapping[str, Sequence[str]]) -> None:
        self.modalities = modalities
        self.reads = 0

    def model_routes(self) -> Mapping[str, str]:
        return {"/blind": "ollama/blind", "/seeing": "anthropic/seeing"}

    async def input_modalities(self) -> Mapping[str, Sequence[str]]:
        self.reads += 1
        return self.modalities


def _run_url4(model_route: str) -> str:
    protocol = build_evaluation_protocol(
        cases_route="/cases",
        case_evaluation=candidate("$item.input", web_search=False),
        selected_case_count=1,
        available_case_count=1,
        aggregate_route="/aggregate",
    )
    return link_candidate(
        render(RelExpr(path=model_route, context="$input", intent=text("Answer."))), protocol
    )


def _admit(model_route: str, *, needs_pictures: bool, reader: _Reader) -> None:
    node = Url4Node()
    register_model_sight(node, reader)
    with run_expression_scope(_run_url4(model_route)):
        asyncio.run(refuse_blind_candidate(node, needs_pictures=needs_pictures))


def test_a_picture_board_refuses_a_blind_model_by_name() -> None:
    reader = _Reader({"ollama/blind": ["text"], "anthropic/seeing": ["text", "image"]})

    with pytest.raises(ResolutionError) as exc:
        _admit("/blind", needs_pictures=True, reader=reader)

    assert exc.value.code == "intent_error"
    assert "ollama/blind" in str(exc.value)


def test_a_picture_board_admits_a_seeing_model() -> None:
    reader = _Reader({"anthropic/seeing": ["text", "image"]})

    _admit("/seeing", needs_pictures=True, reader=reader)

    assert reader.reads == 1


def test_a_text_board_never_reads_the_model_list() -> None:
    reader = _Reader({})

    _admit("/blind", needs_pictures=False, reader=reader)

    assert reader.reads == 0


def test_without_a_bound_run_nothing_is_checked() -> None:
    node = Url4Node()
    reader = _Reader({})
    register_model_sight(node, reader)

    asyncio.run(refuse_blind_candidate(node, needs_pictures=True))

    assert reader.reads == 0


def test_a_picture_board_with_no_model_in_the_candidate_reads_no_model_list() -> None:
    reader = _Reader({})

    _admit("/not-a-model", needs_pictures=True, reader=reader)

    assert reader.reads == 0
