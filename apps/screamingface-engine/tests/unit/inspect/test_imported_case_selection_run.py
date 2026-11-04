"""A real imported Benchmark run on a fixed list of Case ids scores exactly those Cases (OME-1739).

FEATURE (OME-1739): the whole recipe the selection route hands out runs end to end on the
imported ``inspect-gsm8k`` Benchmark (its real Cases route, check, aggregate and inspect
scorer), with a stand-in model in place of a paid one. Nothing is paid, nothing leaves the
process.

INVARIANT: the run grades the selected Case ids against their own answer keys, so the score
follows which Cases were picked, never their positions.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from replayed_cases_helpers import prepare_with_stand_in_hub  # noqa: E402

from screamingface_engine.benchmarks.selection import CaseSelection  # noqa: E402
from screamingface_engine.world.candidate_adapter import (  # noqa: E402
    install_candidate_invocation,
)
from screamingface_engine_inspect.benchmarks import imported_benchmark  # noqa: E402
from url4 import RelExpr, Text, render  # noqa: E402
from url4.peer.server import Request, Url4Node  # noqa: E402

GSM8K = imported_benchmark("gsm8k")

# Example: three Cases; the stand-in model always answers 60, which is right only for Case 2.
_ROWS: list[dict[str, Any]] = [
    {"question": "What is 6 times 7?", "answer": "6 * 7 = 42\n#### 42"},
    {"question": "A train travels 30 km twice. Total?", "answer": "30 + 30 = 60\n#### 60"},
    {"question": "What is 9 plus 9?", "answer": "9 + 9 = 18\n#### 18"},
]


async def _run(tmp_path: Path, resource: dict[str, object]) -> tuple[dict[str, Any], list[str]]:
    """Run one resource's recipe on a fresh node; return the result and the questions asked."""

    prepare_with_stand_in_hub("gsm8k", _ROWS, tmp_path / GSM8K.benchmark.id)
    node = Url4Node("test")
    GSM8K.benchmark.install(node, tmp_path)
    install_candidate_invocation(node)
    asked: list[str] = []

    @node.endpoint("/stand-in-model")
    async def model(request: Request) -> str:
        asked.append(request.context)
        return "ANSWER: 60"

    recipe: str = render(RelExpr(path="/stand-in-model", context="$input", intent=Text("Answer")))
    try:
        result = await node.evaluate(str(resource["url4"]), env={"candidate": recipe})
    finally:
        await node.aclose()
    return json.loads(result.text), asked


@pytest.mark.asyncio
async def test_a_selected_run_asks_and_grades_only_the_selected_cases(tmp_path: Path) -> None:
    resource: dict[str, object] = GSM8K.benchmark.resource(cases=CaseSelection.of([2, 3]))

    result, asked = await _run(tmp_path, resource)

    assert len(asked) == 2
    assert "train" in asked[0] and "9 plus 9" in asked[1]
    assert [case["case_id"] for case in result["cases"]] == [2, 3]
    # Case 2's key is 60 (right), Case 3's is 18 (wrong): graded against their own keys.
    assert [case["grade"]["score"] for case in result["cases"]] == [1.0, 0.0]
    assert result["score"] == 0.5


@pytest.mark.asyncio
async def test_the_same_count_as_a_limit_runs_cases_one_and_two(tmp_path: Path) -> None:
    # WHY: the contrast that proves the ids, not the count, choose the Cases.
    result, asked = await _run(tmp_path, GSM8K.benchmark.resource(limit=2))

    assert [case["case_id"] for case in result["cases"]] == [1, 2]
    assert [case["grade"]["score"] for case in result["cases"]] == [0.0, 1.0]
    assert "6 times 7" in asked[0]


@pytest.mark.asyncio
async def test_a_selected_case_with_no_row_is_named_not_dropped(tmp_path: Path) -> None:
    # WHY: the roll call comes from the selection, not from the rows that arrived, so a
    # selected Case that produced nothing is a named failure instead of a smaller run.
    from test_inspect_gsm8k_benchmark import _call, _row

    prepare_with_stand_in_hub("gsm8k", _ROWS, tmp_path / GSM8K.benchmark.id)
    node = Url4Node("test")
    GSM8K.benchmark.install(node, tmp_path)
    rows: str = json.dumps([_row(2, "ANSWER: 60")])

    result = json.loads(await _call(node, GSM8K.aggregate_route, rows, "aggregate:[2,3]"))

    assert [case["case_id"] for case in result["cases"]] == [2, 3]
    assert result["cases"][1]["failures"][0]["code"] == "missing_case_row"
    assert result["metrics"]["scored_cases"] == 1
