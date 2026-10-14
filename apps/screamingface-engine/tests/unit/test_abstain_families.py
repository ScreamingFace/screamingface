"""An abstained Case is graded on the empty answer, then scored 0.0 (E4a, AB-D10).

FEATURE: when the Candidate abstained, the grader still runs on the empty answer and keeps its
metrics and checks, but the Case's score is replaced by 0.0 and the Case says ``abstained``
(OME-1289, erd section 9). The benchmark score counts the Case like any other scored Case.
STORY: as a researcher, a vote that found no answer costs the candidate exactly one wrong Case,
in every benchmark family, and I can tell it from a wrong answer in the report.
INVARIANT defended: "ignored" means the grader ran and still returned grade material. A grading
step that left none (the ladder rung, a hook failure with no metrics and no checks) keeps the
Case failed, because publishing a scored Case with ``metrics={}`` would break the scorers that
read them (the mean and the DRACO block).
"""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from test_shared_grading_aggregation import (
    MESSAGES,
    _aggregate,
    _envelope,
    _grading,
    _Hook,
    _path,
    _selected,
)

from screamingface_engine.benchmarks.case_request import candidate_input
from screamingface_engine.benchmarks.contract import CANDIDATE_ROUTE, encode_candidate_invocation
from screamingface_engine.benchmarks.graded_answer import (
    graded_answer_payload,
    install_graded_answer_endpoint,
)
from screamingface_engine.benchmarks.ifeval.definition import IFEVAL, install_ifeval
from screamingface_engine.benchmarks.shared_grading.benchmark_aggregation import (
    CaseGradeOutcome,
    GradeRequest,
)
from screamingface_engine.benchmarks.shared_grading.payloads import TextPayload
from url4 import Text, expr, render, src
from url4.peer.server import Request, Url4Node

_ABST = encode_candidate_invocation("", "stop", None, abstained=True)
_LOGGER = "screamingface_engine.benchmarks.shared_grading.benchmark_aggregation"
_METRICS = {"judged": 1, "expected": 1, "invalid_replies": 0}
_MET = {
    "type": "rubric_item",
    "id": "1",
    "label": "[1] c1",
    "outcome": "MET",
    "evidence": [],
    "metadata": {},
}


def _abstained_row(case_id: int) -> dict[str, object]:
    """The envelope of an abstained Case: the mark on the invocation and on the hoisted row."""
    grading = {
        "case": {
            "case_id": case_id,
            "status": "completed",
            "output": "",
            "finish_reason": "stop",
            "refusal": None,
            "execution": None,
            "metadata": {},
            "candidate_abstained": True,
        }
    }
    return graded_answer_payload(case_id, _ABST, [grading])


class _ByCase(_Hook):
    """Scores 1.0 with a MET check, except the Cases it is told to score 0.0."""

    def __init__(self, zeros: frozenset[int]) -> None:
        super().__init__(CaseGradeOutcome(score=1.0, metrics=_METRICS, checks=[_MET]))
        self.zeros = zeros

    async def __call__(self, request: GradeRequest) -> CaseGradeOutcome:
        outcome = await super().__call__(request)
        return replace(outcome, score=0.0) if int(request.case_id) in self.zeros else outcome


def test_abstained_cases_count_as_zero_in_the_benchmark_score() -> None:
    hook = _ByCase(zeros=frozenset({3, 5, 9}))
    abstained = {2, 7}
    rows = [
        _abstained_row(case_id) if case_id in abstained else _envelope(case_id, _grading(case_id))
        for case_id in range(1, 11)
    ]

    result = _aggregate(_path(hook), rows, _selected(*range(1, 11)))

    # 5 Cases score 1.0, 3 score 0.0 from the grader and 2 abstain: 5 / 10.
    assert result["score"] == 0.5
    assert result["coverage"] == 1.0
    for case in result["cases"]:
        marked = case["case_id"] in abstained
        assert case["status"] == "scored"
        assert case.get("abstained") is (True if marked else None)
        if marked:
            assert (case["grade"]["score"], case["output"]) == (0.0, "")
            # The grader ran on the empty answer, and its metrics and checks are kept.
            assert case["grade"]["metrics"] == _METRICS
            assert [check["outcome"] for check in case["grade"]["checks"]] == ["MET"]
    graded_on = {int(request.case_id): request.answer for request in hook.requests}
    assert all(graded_on[case_id] == TextPayload(text="") for case_id in abstained)


def _warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == _LOGGER and r.levelno == logging.WARNING]


def _failing_outcome(**overrides: Any) -> CaseGradeOutcome:
    fields: dict[str, Any] = {
        "score": None,
        "metrics": {"judged": 0, "expected": 1, "invalid_replies": 1},
        "checks": [_MET],
        "failure_code": "incomplete_verdicts",
    }
    fields.update(overrides)
    return CaseGradeOutcome(**fields)


def test_abstained_grader_error_is_ignored_and_logged(caplog: pytest.LogCaptureFixture) -> None:
    hook = _Hook(_failing_outcome())
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        result = _aggregate(_path(hook), [_abstained_row(4)], _selected(4))
    control = _aggregate(
        _path(_Hook(_failing_outcome())), [_envelope(4, _grading(4))], _selected(4)
    )

    case = result["cases"][0]
    assert (case["status"], case["grade"]["score"], case.get("abstained")) == ("scored", 0.0, True)
    assert case["grade"]["metrics"] == {"judged": 0, "expected": 1, "invalid_replies": 1}
    assert [check["outcome"] for check in case["grade"]["checks"]] == ["MET"]
    assert case["failures"] == []
    assert [r.args for r in _warnings(caplog)] == [(4, "incomplete_verdicts")]
    # Control: the same grader error on a Case the model answered stays a failed Case.
    assert control["cases"][0]["status"] == "failed"
    assert "abstained" not in control["cases"][0]


@pytest.mark.parametrize("code", ["no_positive_points", "polarity_mismatch"])
def test_an_asset_defect_stays_failed_on_an_abstained_case(
    code: str, caplog: pytest.LogCaptureFixture
) -> None:
    """A broken prepared asset says nothing about the answer, so the Case is not forgiven."""
    path = _path(
        _Hook(_failing_outcome(failure_code=code)),
        failure_messages={**MESSAGES, "polarity_mismatch": "test: polarity mismatch"},
    )
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        result = _aggregate(path, [_abstained_row(4)], _selected(4))

    case = result["cases"][0]
    assert case["status"] == "failed"
    assert "abstained" not in case
    assert case["failures"][0]["code"] == code
    warnings = _warnings(caplog)
    assert [r.args for r in warnings] == [(4, code)]
    assert "asset defect" in warnings[0].getMessage()


def test_abstained_case_without_any_grade_stays_failed_and_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    ladder_row = graded_answer_payload(
        1, _ABST, [{"error": {"code": "upstream_error", "message": "judge down"}}]
    )
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        ladder = _aggregate(_path(_Hook()), [ladder_row], _selected(1))

    failed = ladder["cases"][0]
    assert failed["status"] == "failed"
    assert "abstained" not in failed
    assert failed["grade"]["score"] is None
    assert [r.args for r in _warnings(caplog)] == [(1,)]

    # (b) the polarity_mismatch shape: a hook failure that left neither metrics nor checks.
    caplog.clear()
    empty = _failing_outcome(metrics={}, checks=[], failure_code="case_error")
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        hook_failure = _aggregate(_path(_Hook(empty)), [_abstained_row(2)], _selected(2))

    failed = hook_failure["cases"][0]
    assert failed["status"] == "failed"
    assert "abstained" not in failed
    assert failed["failures"][0]["code"] == "case_error"
    assert [r.args for r in _warnings(caplog)] == [(2, "case_error")]


# --- IFEval end to end ------------------------------------------------------------------------


def _two_case_ifeval_assets(root: Path) -> None:
    (root / "instructions").mkdir(parents=True)
    prompts = {1: "Describe tea without commas.", 2: "Describe coffee without commas."}
    (root / "cases.json").write_text(
        json.dumps([{"id": case_id, "input": prompt} for case_id, prompt in prompts.items()]),
        encoding="utf-8",
    )
    for case_id, prompt in prompts.items():
        (root / "instructions" / f"{case_id}.json").write_text(
            json.dumps(
                {
                    "key": case_id,
                    "prompt": prompt,
                    "instruction_id_list": ["punctuation:no_comma"],
                    "kwargs": [{}],
                }
            ),
            encoding="utf-8",
        )


@pytest.mark.asyncio
async def test_abstained_case_score_replaced_native(tmp_path: Path) -> None:
    _two_case_ifeval_assets(tmp_path / "ifeval")
    node = Url4Node("test")
    install_ifeval(node, tmp_path)
    install_graded_answer_endpoint(node)

    @node.endpoint(CANDIDATE_ROUTE)
    def candidate(request: Request) -> str:
        _, case_id = candidate_input(request)
        if str(case_id) == "2":
            return _ABST
        return encode_candidate_invocation("tea is warm", "stop", None)

    expression = expr(
        src(Text("unused-candidate-recipe"), name="candidate", weight=0.0),
        src(IFEVAL.protocol(2), name="exam", weight=0.0),
        intent=Text("$exam"),
    )
    result = json.loads((await node.evaluate(render(expression))).text)

    assert result["score"] == 0.5
    answered, abstained = result["cases"]
    assert "abstained" not in answered
    assert (abstained["status"], abstained["grade"]["score"]) == ("scored", 0.0)
    assert abstained.get("abstained") is True
    assert abstained["grade"]["method"] == "deterministic"
    assert [check["outcome"] for check in abstained["grade"]["checks"]] == ["UNMET"]
    # F9: only `score` is replaced; the grader's own secondary verdicts are kept.
    assert abstained["grade"]["metrics"]["follow_all_strict"] is False


def test_an_abstained_case_stays_at_zero_on_a_refusal_rate_benchmark(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """On an ``inverted_grade`` Benchmark (OME-1400) the abstain rule still runs (OME-1289).

    WHY: the inverted Benchmark's Case scores are already 1 − grade before they reach the
    aggregate, and the flag is only a stamp on the run result. So an abstained Case whose grader
    failed with a non-asset code is scored 0.0 with no failure, exactly as on any Benchmark, and
    the run result still says ``inverted_grade``.
    """
    path = _path(_Hook(_failing_outcome()), inverted_grade=True)
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        result = _aggregate(path, [_abstained_row(4)], _selected(4))

    case = result["cases"][0]
    assert (case["status"], case["grade"]["score"], case.get("abstained")) == ("scored", 0.0, True)
    assert case["failures"] == []
    assert result["score"] == 0.0
    assert result["inverted_grade"] is True
    assert [r.args for r in _warnings(caplog)] == [(4, "incomplete_verdicts")]
