# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""Two Cases judged at the same moment each pay for their own judge call (OME-1527, R4).

The final aggregate marks several Cases at once, so two judge calls can be in flight
together. The run's accounting join learns which Case a judge call belongs to from the
grading scope the scorer adapter raises around each Case; this suite drives the real
adapter and the real gateway judge provider through the aggregate, holds both Cases
inside their scope until both are judging, and checks each judge request is booked to
the Case whose answer it carries.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

pytest.importorskip("inspect_ai")

from inspect_ai.model import get_model  # noqa: E402
from inspect_ai.scorer import Score, Target  # noqa: E402
from inspect_ai.solver import TaskState  # noqa: E402
from test_judge_observability import _assembled, _judged_spec  # noqa: E402

from screamingface_engine.benchmarks.aggregation import CandidateScore, SelectedCase  # noqa: E402
from screamingface_engine.benchmarks.contract import encode_candidate_invocation  # noqa: E402
from screamingface_engine.benchmarks.graded_answer import graded_answer_payload  # noqa: E402
from screamingface_engine.benchmarks.shared_grading.benchmark_aggregation import (  # noqa: E402
    CASE_GRADING_CONCURRENCY,
    BenchmarkAggregation,
)
from screamingface_engine.benchmarks.shared_grading.case_grades import (  # noqa: E402
    CaseGradeReader,
)
from screamingface_engine.grading_accounting import (  # noqa: E402
    capture_grading_requests,
    grading_case_for_request,
)
from screamingface_engine.request_identity import model_request_key  # noqa: E402
from screamingface_engine_inspect.judge_provider import (  # noqa: E402
    JudgeTransport,
    bound_judge_transport,
)
from screamingface_engine_inspect.scorer_adapter import inspect_grade_case  # noqa: E402
from url4.wire.subrequest import (  # noqa: E402
    decode_subrequest_http,
    extract_expression_params,
)

_WAIT_S: float = 5.0


def _row(case_id: int) -> dict[str, object]:
    """One collected row whose Candidate answered ``answer-<case_id>``."""

    answer: str = f"answer-{case_id}"
    case: dict[str, Any] = {"case_id": case_id, "status": "completed", "output": answer}
    return graded_answer_payload(
        case_id, encode_candidate_invocation(answer, "stop", None), [{"case": case}]
    )


def _decode(grading: object, case_id: int) -> dict[str, Any]:
    """Hand the collected grading envelope through untouched (a stub Benchmark decoder)."""

    assert isinstance(grading, dict)
    return dict(grading)


def _booked_cases(targets: list[str]) -> dict[str, Any]:
    """Which Case the accounting join books each recorded judge call to, keyed by answer.

    Each target is decoded with the wire codec's own decoders into the identity the
    connector records, then looked up the way the run's accounting join looks it up.
    """

    booked: dict[str, Any] = {}
    for target in targets:
        route, _, query = target.partition("?")
        params, expression = extract_expression_params(query)
        assert expression is not None
        context, intent = decode_subrequest_http(expression)
        key = model_request_key(path=route, params=dict(params), context=context, intent=intent)
        answer: str = json.loads(context)["messages"][-1]["content"]
        booked[answer] = grading_case_for_request(key)
    return booked


@pytest.mark.asyncio
async def test_two_cases_judged_at_once_each_book_their_judge_call_to_their_own_case() -> None:
    """INVARIANT: judge cost lands on the Case that paid for it, even with Cases in flight."""

    targets: list[str] = []
    judging: list[int] = []
    both_judging: asyncio.Event = asyncio.Event()

    async def fetch(target: str) -> str:
        """The node's model route, faked: record the wire target, answer a verdict."""

        targets.append(target)
        return "GRADE: C"

    async def judged(state: TaskState, target: Target) -> Score:
        """A stand-in for a judged eval scorer: one judge call about this Case's answer.

        WHY the wait: both Cases are inside their own grading scope before either calls
        the judge, so a scope shared between Cases would book one Case's call to the other.
        It simulates overlap only; it proves nothing about the judge's prompt or verdict.
        """

        judging.append(1)
        if len(judging) == 2:
            both_judging.set()
        await asyncio.wait_for(both_judging.wait(), _WAIT_S)
        output = await get_model("screamingface/judge-4").generate(state.output.completion)
        return Score(value=1.0 if output.completion == "GRADE: C" else 0.0)

    path = BenchmarkAggregation(
        reader=CaseGradeReader(
            benchmark_label="Judged",
            error_type=ValueError,
            decode_case_grade=_decode,
        ),
        grade_case=inspect_grade_case(judged),
        failure_messages={},
        method="inspect",
        grading_failure_code="judged_grading_failed",
        grading_failure_message="the grader failed",
        case_grading_concurrency=CASE_GRADING_CONCURRENCY,
    )
    transport = JudgeTransport(fetch=fetch, params=(("temperature", "0"),), benchmark_id="judged")
    with capture_grading_requests(), bound_judge_transport(transport):
        result: dict[str, Any] = await path.aggregate_async(
            json.dumps([_row(1), _row(2)]),
            benchmark_id="judged",
            benchmark_revision="rev",
            selected_cases=[
                SelectedCase(case_id=n, input=f"question-{n}", metadata={}) for n in (1, 2)
            ],
            grading_material=lambda case_id: {"target": "C"},
            scorer=lambda cases: CandidateScore(score=1.0, metrics={}),
        )
        booked: dict[str, Any] = _booked_cases(targets)
    assert [case["grade"]["score"] for case in result["cases"]] == [1.0, 1.0]
    assert booked == {"answer-1": 1, "answer-2": 2}


def test_only_a_judged_benchmark_marks_cases_side_by_side(monkeypatch: pytest.MonkeyPatch) -> None:
    """WHY: only a judge call makes a Case wait; a judge-free scorer keeps serial marking."""

    judged: Any = _assembled(_judged_spec(), monkeypatch)
    assert judged.aggregation().case_grading_concurrency == CASE_GRADING_CONCURRENCY
    judge_free: Any = _assembled(
        _judged_spec(judge=None, scorer="inspect_ai.scorer:match", scorer_kwargs={}), monkeypatch
    )
    assert judge_free.aggregation().case_grading_concurrency == 1
