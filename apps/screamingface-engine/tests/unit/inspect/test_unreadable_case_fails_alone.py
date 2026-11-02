# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""A Case the grader can't read fails by name, alone; the run's other Cases still grade (OME-1271).

FEATURE (OME-1271): the scorer adapter rebuilds each Case's chat before the eval's scorer marks
it. A Case whose input breaks the envelope rules used to raise out of that rebuild, past the
per-Case error handling, and the aggregate stopped: one bad Case, no grade for any Case. The
importer never writes such a Case, so only a hand-written or hand-edited Cases file reaches this.
STORY: as a researcher whose Cases file holds one Case the grader can't read, that Case fails
by name and the rest still grade.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

pytest.importorskip("inspect_ai")

from inspect_ai.scorer import Score, Target, match  # noqa: E402
from inspect_ai.solver import TaskState  # noqa: E402

from screamingface_engine.benchmarks.aggregation import CandidateScore, SelectedCase  # noqa: E402
from screamingface_engine.benchmarks.contract import encode_candidate_invocation  # noqa: E402
from screamingface_engine.benchmarks.graded_answer import graded_answer_payload  # noqa: E402
from screamingface_engine.benchmarks.shared_grading.benchmark_aggregation import (  # noqa: E402
    BenchmarkAggregation,
    GradeRequest,
)
from screamingface_engine.benchmarks.shared_grading.case_grades import (  # noqa: E402
    CaseGradeReader,
)
from screamingface_engine.benchmarks.shared_grading.payloads import TextPayload  # noqa: E402
from screamingface_engine_inspect.scorer_adapter import inspect_grade_case  # noqa: E402
from screamingface_engine_inspect.single_shot import _FAILURE_MESSAGES  # noqa: E402

# WHY a developer message as the stand-in for a Case the scorer's reader refuses: the shared
# reader, which the connector uses, admits ``developer``, so the Candidate is asked and answers,
# and only grading refuses it (inspect's chat has no such role). Nothing we generate writes one;
# it stands for a hand-written Cases file.
_UNREADABLE: str = json.dumps(
    {
        "schema": "screamingface.candidate-input.v1",
        "messages": [
            {"role": "developer", "content": "Answer with a number."},
            {"role": "user", "content": "What is 6 times 7?"},
        ],
    }
)
_READABLE: str = "What is 6 times 7?"


def _request(case_id: int, case_input: str) -> GradeRequest:
    """One Case to grade, answered ``42``, with the target ``42``."""

    return GradeRequest(
        case_id=case_id,
        input=TextPayload(text=case_input),
        answer=TextPayload(text="42"),
        row={"case": {"status": "answered"}},
        material={"target": "42"},
    )


def _row(case_id: int) -> dict[str, object]:
    """One collected row whose Candidate answered ``42``."""

    case: dict[str, Any] = {"case_id": case_id, "status": "completed", "output": "42"}
    return graded_answer_payload(
        case_id, encode_candidate_invocation("42", "stop", None), [{"case": case}]
    )


def _decode(grading: object, case_id: int) -> dict[str, Any]:
    """Hand the collected grading envelope through untouched (a stub Benchmark decoder)."""

    assert isinstance(grading, dict)
    return dict(grading)


@pytest.mark.asyncio
async def test_an_unreadable_case_fails_by_name_and_its_scorer_is_never_called() -> None:
    """INVARIANT: the refusal names the rule it broke, and no scorer marks a Case it can't read."""

    marked: list[int] = []

    async def scorer(state: TaskState, target: Target) -> Score:
        """A stand-in scorer that records which Case it marked, then marks it right."""

        marked.append(int(state.sample_id))
        return Score(value="C")

    grade = inspect_grade_case(scorer)
    outcomes = [
        await grade(_request(case_id, case_input))
        for case_id, case_input in ((1, _READABLE), (2, _UNREADABLE), (3, _READABLE))
    ]

    assert [outcome.failure_code for outcome in outcomes] == [None, "invalid_candidate_input", None]
    assert [outcome.score for outcome in outcomes] == [1.0, None, 1.0]
    assert marked == [1, 3]
    assert "conversation message 0 must be a known role" in str(outcomes[1].checks)


@pytest.mark.asyncio
async def test_one_unreadable_case_leaves_the_runs_other_cases_graded() -> None:
    """INVARIANT: through the real aggregate and the plugin's own failure wording, one bad Case
    fails as itself; before the fix the raise escaped and no Case of the run got a grade."""

    path = BenchmarkAggregation(
        failure_policy="withhold",
        reader=CaseGradeReader(
            benchmark_label="Arithmetic",
            error_type=ValueError,
            decode_case_grade=_decode,
        ),
        grade_case=inspect_grade_case(match(numeric=True)),
        failure_messages=_FAILURE_MESSAGES,
        method="inspect",
        grading_failure_code="inspect_grading_failed",
        grading_failure_message="the grader failed",
    )
    inputs: dict[int, str] = {1: _READABLE, 2: _UNREADABLE, 3: _READABLE}
    result: dict[str, Any] = await path.aggregate_async(
        json.dumps([_row(case_id) for case_id in inputs]),
        benchmark_id="arithmetic",
        benchmark_revision="rev",
        selected_cases=[
            SelectedCase(case_id=case_id, input=case_input, metadata={})
            for case_id, case_input in inputs.items()
        ],
        grading_material=lambda case_id: {"target": "42"},
        scorer=lambda cases: CandidateScore(score=1.0, metrics={}),
    )

    by_case: dict[int, dict[str, Any]] = {case["case_id"]: case for case in result["cases"]}
    assert by_case[1]["grade"]["score"] == 1.0
    assert by_case[3]["grade"]["score"] == 1.0
    assert by_case[2]["grade"]["score"] is None
    assert "invalid_candidate_input" in json.dumps(by_case[2])
