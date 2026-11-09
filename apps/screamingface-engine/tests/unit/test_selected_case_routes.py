"""The routes a run calls serve and grade exactly the Case ids it selected (OME-1739).

FEATURE (OME-1739): the Cases step reads only the selected rows (through the board's offset
index from OME-1790 when it has one), and the aggregate and early-result routes grade those
same ids, so a held-out run of 40 Cases never scores Case 1's answer key for Case 3.

INVARIANT: every served row's ``id`` equals the position it was read from. A board whose rows
are out of order fails as a contract error instead of serving one Case under another's id.
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
    LegacyBoard,
    encode_board,
)
from screamingface_engine.benchmarks.case_selection import board_cases_handler, cases_handler
from screamingface_engine.benchmarks.grading_endpoints import (
    aggregate_endpoint,
    async_aggregate_endpoint,
)
from screamingface_engine.benchmarks.shared_grading.incremental_routes import case_result_endpoint
from url4.core.errors import ResolutionError
from url4.peer.server import Request

# Example: a 50-Case board; the researcher's dev set is Cases 3, 17 and 42.
_ROWS: list[dict[str, Any]] = [
    {"id": index, "case_id": f"c{index}", "input": f"question {index}"} for index in range(1, 51)
]


def _indexed(tmp_path: Path, rows: list[dict[str, Any]] = _ROWS) -> IndexedBoard:
    files = encode_board(rows)
    (tmp_path / BOARD_FILE).write_bytes(files.board)
    (tmp_path / OFFSETS_FILE).write_bytes(files.offsets)
    (tmp_path / CASES_FILE).write_bytes(files.cases)
    return IndexedBoard(tmp_path)


def _legacy(rows: list[dict[str, Any]] = _ROWS) -> LegacyBoard:
    return LegacyBoard(json.dumps(rows))


def _request(intent: str, context: str = "") -> Request:
    return Request("/route", context, intent, {})


# ── the board store ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("kind", ["indexed", "legacy"])
def test_rows_reads_exactly_the_selected_ids_in_order(tmp_path: Path, kind: str) -> None:
    board = _indexed(tmp_path) if kind == "indexed" else _legacy()

    served: list[dict[str, Any]] = json.loads(board.rows((3, 17, 42)))

    assert [row["id"] for row in served] == [3, 17, 42]
    assert served[1] == _ROWS[16]


def test_rows_of_one_to_n_is_byte_identical_to_head(tmp_path: Path) -> None:
    board = _indexed(tmp_path)

    assert board.rows((1, 2, 3)) == board.head(3)


@pytest.mark.parametrize("kind", ["indexed", "legacy"])
@pytest.mark.parametrize("ids", [(0,), (51,), (3, 51)])
def test_rows_refuses_an_id_outside_the_board(tmp_path: Path, kind: str, ids: tuple[int]) -> None:
    board = _indexed(tmp_path) if kind == "indexed" else _legacy()

    with pytest.raises(ValueError):
        board.rows(ids)


@pytest.mark.parametrize("kind", ["indexed", "legacy"])
def test_a_row_whose_id_is_not_its_position_is_refused(tmp_path: Path, kind: str) -> None:
    # Stand-in for a board written out of order: position 17 holds the row with id 18.
    shuffled: list[dict[str, Any]] = [*_ROWS[:16], _ROWS[17], _ROWS[16], *_ROWS[18:]]
    board = _indexed(tmp_path, shuffled) if kind == "indexed" else _legacy(shuffled)

    with pytest.raises(ResolutionError) as exc:
        board.rows((3, 17))

    assert "17" in str(exc.value)


# ── the Cases routes ────────────────────────────────────────────────────────


def test_the_board_cases_route_serves_an_id_list(tmp_path: Path) -> None:
    board = _indexed(tmp_path)

    served = board_cases_handler(lambda: board)(_request("[3,17,42]"))

    assert isinstance(served, str)
    assert [row["id"] for row in json.loads(served)] == [3, 17, 42]


def test_the_board_cases_route_refuses_an_id_above_the_board(tmp_path: Path) -> None:
    board = _indexed(tmp_path)

    with pytest.raises(ResolutionError) as exc:
        board_cases_handler(lambda: board)(_request("[3,51]"))

    assert exc.value.code == "benchmark_contract_error"
    assert exc.value.permanent is True


def test_the_hand_built_cases_route_serves_an_id_list() -> None:
    served = cases_handler(lambda: json.dumps(_ROWS))(_request("[3,17,42]"))

    assert isinstance(served, str)
    assert [row["id"] for row in json.loads(served)] == [3, 17, 42]


def test_the_hand_built_cases_route_keeps_serving_a_count_as_written() -> None:
    # INVARIANT: a count still serves the whole booklet unchanged; url4's slice cuts it.
    raw: str = json.dumps(_ROWS)

    assert cases_handler(lambda: raw)(_request("3")) == raw


@pytest.mark.parametrize("intent", ["[3,51]", "[3,3]", "[0]", "[true]", "3)!/x"])
def test_the_hand_built_cases_route_refuses_a_bad_id_list(intent: str) -> None:
    with pytest.raises(ResolutionError) as exc:
        cases_handler(lambda: json.dumps(_ROWS))(_request(intent))

    assert exc.value.code == "benchmark_contract_error"


def test_the_hand_built_cases_route_refuses_a_row_out_of_position() -> None:
    shuffled: list[dict[str, Any]] = [*_ROWS[:16], _ROWS[17], _ROWS[16], *_ROWS[18:]]

    with pytest.raises(ResolutionError) as exc:
        cases_handler(lambda: json.dumps(shuffled))(_request("[17]"))

    assert exc.value.code == "benchmark_contract_error"


# ── grading ─────────────────────────────────────────────────────────────────


def test_the_aggregate_adapter_receives_the_selected_case_ids() -> None:
    seen: list[tuple[int, ...]] = []

    def aggregate(rows: str, case_ids: tuple[int, ...]) -> dict[str, object]:
        seen.append(case_ids)
        return {}

    endpoint = aggregate_endpoint(label="Example", available_case_count=50, aggregate=aggregate)
    endpoint(_request("aggregate:[3,17,42]", "[]"))
    endpoint(_request("aggregate:2", "[]"))

    # WHY ids, not a count: a count of 3 would mark Cases 1, 2 and 3 against the answers to
    # Cases 3, 17 and 42.
    assert seen == [(3, 17, 42), (1, 2)]


@pytest.mark.asyncio
@pytest.mark.parametrize("intent", ["aggregate:[3,51]", "aggregate:[3,3]", "aggregate:[]"])
async def test_the_aggregate_refuses_a_bad_id_list_before_scoring(intent: str) -> None:
    async def aggregate(rows: str, case_ids: tuple[int, ...]) -> dict[str, object]:
        pytest.fail("invalid selection reached scorer")

    endpoint = async_aggregate_endpoint(
        label="Example", available_case_count=50, aggregate=aggregate
    )
    with pytest.raises(ResolutionError) as caught:
        await endpoint(_request(intent, "[]"))

    assert caught.value.code == "benchmark_definition_error"


class _Scoring:
    """Stand-in Scoring: records which served position it was asked to grade."""

    def __init__(self) -> None:
        self.graded: list[int] = []

    async def grade_row(self, raw: str, index: int) -> str:
        self.graded.append(index)
        return "{}"


@pytest.mark.asyncio
async def test_the_early_result_loads_the_selected_ids_and_grades_by_position() -> None:
    loads: list[tuple[int, ...]] = []
    scoring = _Scoring()

    def load(case_ids: tuple[int, ...]) -> Any:
        loads.append(case_ids)
        return scoring

    endpoint = case_result_endpoint(load, available_case_count=50)
    # url4 writes `$index` as the served position: 1 is the second selected Case, id 17.
    await endpoint(_request("1:[3,17,42]", "{}"))

    assert loads == [(3, 17, 42)]
    assert scoring.graded == [1]


@pytest.mark.asyncio
@pytest.mark.parametrize("intent", ["3:[3,17,42]", "0:[3,51]", "0:[3,3]"])
async def test_the_early_result_refuses_a_bad_position_or_list(intent: str) -> None:
    def load(case_ids: tuple[int, ...]) -> Any:
        pytest.fail("invalid selection reached the loader")

    with pytest.raises(ResolutionError) as caught:
        await case_result_endpoint(load, available_case_count=50)(_request(intent, "{}"))

    assert caught.value.code == "benchmark_contract_error"
