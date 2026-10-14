# pyright: reportMissingImports=false
# WHY file-level: these tests import the `inspect` extra, absent in the extra-less
# typecheck install.
"""A judged run adds up its Cases' verdict counts, so the Report warns again (OME-1527, row 18b).

FEATURE: the Report's "Grading did not fully land" warning. Think of each judged Case as a
marking sheet with one box per rubric line per pass. The Case score only reports the boxes
that were ticked; the warning reports the boxes the judge never ticked usably (its reply
never parsed), added up over the run. The hand-built DRACO grader fed it; when DRACO moved to
a local inspect Task the lane's run tally stopped adding the counts up, so a run with hundreds
of unreadable judge replies showed a clean Report.

What these tests pin, and why:

- the spec: draco-3pass over the four canned Cases its own tests use (one line left out of a
  pass in Case 2, one in Case 3, Case 4 failed outright) publishes 18 expected, 16 accepted,
  2 rejected, and the SDK Report's own warning code renders "2 rejected of 18 verdicts" from
  those run metrics. The failed Case adds nothing, as the hand-built sums left it out;
- a clean run still publishes its counts (rejected 0), and the Report stays silent;
- a row whose scorer writes no counts publishes exactly what it published before;
- a row that tallies with the eval's own whole-run metric adds the counts up too;
- counts that would make the warning lie fail the Case by name, never publish.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

import ast
import html
import json
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from inspect_ai.scorer import Score, Scorer, Target, accuracy, scorer  # noqa: E402
from inspect_ai.solver import TaskState  # noqa: E402
from test_local_task_draco import _CASES, _material, _ScriptedJudge  # noqa: E402
from test_whole_run_metric import (  # noqa: E402
    _NONE,
    _SEVENTY_PERCENT_NONE,
    _aggregate,
    _benchmark,
    _row,
    clause_match,
    found_rate,
)

from screamingface_engine.benchmarks.shared_grading.benchmark_aggregation import (  # noqa: E402
    CaseGradeOutcome,
    GradeRequest,
)
from screamingface_engine.benchmarks.shared_grading.payloads import TextPayload  # noqa: E402
from screamingface_engine.request_scope import RequestScope, request_scope  # noqa: E402
from screamingface_engine_inspect.benchmarks import imported_benchmark  # noqa: E402
from screamingface_engine_inspect.judge_provider import (  # noqa: E402
    JudgeTransport,
    bound_judge_transport,
)
from screamingface_engine_inspect.prepare import PreparedCase, _write_cases  # noqa: E402
from screamingface_engine_inspect.scorer_adapter import inspect_grade_case  # noqa: E402
from screamingface_engine_inspect.single_shot import benchmark_aggregate_async  # noqa: E402

# parents[4] = apps/, so its parent is the monorepo root.
_SDK_PACKAGE: Path = Path(__file__).resolve().parents[4].parent / "packages" / "screamingface"
_SDK_REPORT_VIEW: Path = _SDK_PACKAGE / "src" / "screamingface" / "_ui" / "report_view.py"

_WARNING: str = "Grading did not fully land"


def _report_grading_warning() -> Callable[[Mapping[str, Any]], str]:
    """The SDK Report's own grading-warning code, lifted from its source.

    WHY lift, not import: the Engine never depends on the SDK (no cross-app import, the same
    bind as the failure-code conformance twin). Running the Report's real function means a
    rename on either side (the lane's metric names, the Report's reads) turns this lane red.
    A present SDK whose warning moved must FAIL, not skip.
    """

    if not _SDK_PACKAGE.exists():
        pytest.skip("SDK package not present")
    assert _SDK_REPORT_VIEW.exists(), "SDK report_view.py moved — update this bind"
    tree: ast.Module = ast.parse(_SDK_REPORT_VIEW.read_text(encoding="utf-8"))
    wanted: set[str] = {"_grading_html", "_metric"}
    functions: list[ast.stmt] = [
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted
    ]
    assert {getattr(node, "name", "") for node in functions} == wanted, (
        "the SDK Report's grading warning moved — update this bind"
    )
    namespace: dict[str, Any] = {"escape": html.escape, "Any": Any}
    exec(
        compile(ast.Module(body=functions, type_ignores=[]), str(_SDK_REPORT_VIEW), "exec"),
        namespace,
    )
    return namespace["_grading_html"]


@pytest.fixture
def judge() -> Iterator[_ScriptedJudge]:
    """draco-3pass's scripted judge (the draco tests' own stand-in for the gateway judge),
    bound with the row's pinned params and a seed per pass inside a run's request scope."""

    scripted: _ScriptedJudge = _ScriptedJudge()
    spec = imported_benchmark("draco-3pass").judge
    assert spec is not None
    transport = JudgeTransport(
        fetch=scripted,
        params=spec.params,
        benchmark_id="draco-3pass",
        seed_per_pass=spec.seed_per_pass,
    )
    with request_scope(RequestScope(origin="run")), bound_judge_transport(transport):
        yield scripted


async def _draco_run(root: Path, case_ids: tuple[int, ...]) -> dict[str, Any]:
    """Run draco-3pass's real aggregate over the canned Cases ``case_ids``."""

    prepared: list[PreparedCase] = [
        {
            "case": {"id": index, "case_id": str(index), "input": _CASES[index - 1][0]},
            "grading_material": _material(index),
        }
        for index in case_ids
    ]
    _write_cases(prepared, root)
    rows: str = json.dumps([_row(index, _CASES[index - 1][1]) for index in case_ids])
    return await benchmark_aggregate_async(
        imported_benchmark("draco-3pass"), rows, root, case_ids=case_ids
    )


# ── the spec: the counts reach the run, and the Report warns from them ─────────────────────


@pytest.mark.asyncio
async def test_a_draco_run_adds_up_its_cases_verdict_counts_so_the_report_warns(
    tmp_path: Path, judge: _ScriptedJudge
) -> None:
    """Worked example, 3 passes each: Case 1 has 3 lines → 9 boxes, all ticked; Case 2 has 1
    line → 3 boxes, its pass-2 reply never parses → 2 ticked; Case 3 has 2 lines → 6 boxes,
    one line's pass-3 reply has no explanation → 5 ticked. Case 4's judge never gives a
    verdict, so the Case fails (``judge_reply_invalid``) and adds nothing, as the hand-built
    sums left a failed Case out. Run: expected 9 + 3 + 6 = 18, accepted 16, rejected 2."""

    result: dict[str, Any] = await _draco_run(tmp_path, (1, 2, 3, 4))

    per_case: list[tuple[str, dict[str, Any]]] = [
        (case["status"], case["grade"]["metrics"]) for case in result["cases"]
    ]
    assert per_case == [
        ("scored", {"verdicts_expected": 9, "verdicts_accepted": 9, "verdicts_rejected": 0}),
        ("scored", {"verdicts_expected": 3, "verdicts_accepted": 2, "verdicts_rejected": 1}),
        ("scored", {"verdicts_expected": 6, "verdicts_accepted": 5, "verdicts_rejected": 1}),
        # The failed Case keeps its Check as evidence, and no counts.
        ("failed", {}),
    ]
    assert result["metrics"] == {
        "correct": 0,
        "scored_cases": 3,
        "verdicts_expected": 18,
        "verdicts_accepted": 16,
        "verdicts_rejected": 2,
    }
    warning: str = _report_grading_warning()(result["metrics"])
    assert f"{_WARNING}: 2 rejected of 18 verdicts" in warning


@pytest.mark.asyncio
async def test_a_clean_draco_run_publishes_its_counts_and_the_report_stays_silent(
    tmp_path: Path, judge: _ScriptedJudge
) -> None:
    """Case 1 alone: every box ticked, so the counts are published with 0 rejected and the
    Report says nothing, as it said nothing for a clean hand-built run."""

    result: dict[str, Any] = await _draco_run(tmp_path, (1,))

    assert result["metrics"]["verdicts_expected"] == 9
    assert result["metrics"]["verdicts_rejected"] == 0
    assert _report_grading_warning()(result["metrics"]) == ""


# ── rows that count nothing, and the whole-run tally ───────────────────────────────────────


@pytest.mark.asyncio
async def test_a_row_whose_scorer_counts_no_verdicts_publishes_what_it_did_before(
    tmp_path: Path,
) -> None:
    """INVARIANT: the ~60 imported rows whose scorers write no counts are untouched — the same
    run metrics and empty Case grade metrics as before this change."""

    result: dict[str, Any] = await _aggregate(
        _benchmark("clause-mean", None), tmp_path, _SEVENTY_PERCENT_NONE, [_NONE] * 10
    )

    assert result["metrics"] == {"correct": 7, "scored_cases": 10}
    assert all(case["grade"]["metrics"] == {} for case in result["cases"])


@scorer(metrics=[accuracy()])
def counted_clause_match() -> Scorer:
    """A judged stand-in: ``clause_match``'s mark, plus 2 verdict boxes per Case, of which a
    Case whose clause was not found ticked only 1. It simulates the counts only."""

    marker: Scorer = clause_match()

    async def score(state: TaskState, target: Target) -> Score:
        mark: Score | None = await marker(state, target)
        assert mark is not None
        found: bool = mark.value == 1
        return Score(
            value=mark.value,
            answer=mark.answer,
            metadata={"verdicts_expected": 2, "verdicts_accepted": 2 if found else 1},
        )

    return score


@pytest.mark.asyncio
async def test_a_whole_run_metric_row_adds_up_the_counts_beside_its_own_metrics(
    tmp_path: Path,
) -> None:
    """The eval's-own-metric tally reads the mean's metrics too, so the counts ride there as
    well. 10 Cases × 2 boxes = 20; the 3 Cases with a clause answer "no related clause", are
    not found and tick 1 each → accepted 17, rejected 3; the headline is found_rate 0.7."""

    result: dict[str, Any] = await _aggregate(
        _benchmark("clause-counted", found_rate, scorer_factory=counted_clause_match),
        tmp_path,
        _SEVENTY_PERCENT_NONE,
        [_NONE] * 10,
    )

    assert result["score"] == 0.7
    assert result["metrics"] == {
        "correct": 7,
        "scored_cases": 10,
        "verdicts_expected": 20,
        "verdicts_accepted": 17,
        "verdicts_rejected": 3,
    }


# ── counts that would make the warning lie ─────────────────────────────────────────────────


def _scorer_writing(metadata: dict[str, Any]) -> Scorer:
    """A stand-in scorer that marks every Case 1 and writes ``metadata`` as its counts."""

    async def score(state: TaskState, target: Target) -> Score:
        return Score(value=1, metadata=metadata)

    return score


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("metadata", "reason"),
    [
        ({"verdicts_expected": 4}, "without its pair"),
        ({"verdicts_accepted": 4}, "without its pair"),
        (
            {"verdicts_expected": 4, "verdicts_accepted": 5},
            "accepted 5 verdicts but expected only 4",
        ),
        ({"verdicts_expected": -1, "verdicts_accepted": 0}, "whole number from 0 up"),
        ({"verdicts_expected": 4.0, "verdicts_accepted": 4}, "whole number from 0 up"),
        ({"verdicts_expected": True, "verdicts_accepted": 1}, "whole number from 0 up"),
    ],
)
async def test_counts_that_would_make_the_warning_lie_fail_the_case_by_name(
    metadata: dict[str, Any], reason: str
) -> None:
    """WHY fail the Case, not drop the counts: a dropped count makes the Report silent about
    the very misfire it exists to show; a failed Case is on the Report, named and explained."""

    outcome: CaseGradeOutcome = await inspect_grade_case(_scorer_writing(metadata))(
        GradeRequest(
            case_id=7,
            input=TextPayload(text="What is 6 times 7?"),
            answer=TextPayload(text="42"),
            row={"case": {"status": "answered"}},
            material={"target": "42"},
        )
    )

    assert outcome.failure_code == "invalid_score_value"
    assert outcome.score is None
    assert reason in outcome.checks[0]["evidence"][0]["raw_output"]
