"""Contract tests for the pure seams of ``fixtures/reducer_lane.py`` (OME-1289 E4a, EV-12).

DEFAULT lane: no docker, no key, no recording. The script's ``record`` step is paid and its
``bless`` step needs docker and a recording, so neither runs here. What does run is everything
between the recording and the committed fixtures that needs no stack: the refusals of ``bless`` (a
replay that does not reproduce the saved report), the choice of the pinned evidence, and the
authoring of the golden. A mistake there would otherwise first show after the user's paid recording.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fixtures import reducer_lane
from harness.goldens import canonical_score, expression_sha
from harness.reducer_golden import ReducerCandidateSpec
from test_reducer_golden_contracts import _case, _evidence, _spec_doc

_URL4 = "(rendered expression)"


def _facts(**overrides: Any) -> Any:
    values: dict[str, Any] = {
        "board": "inspect-gsm8k",
        "rendered_url4": _URL4,
        "expected_score": 0.5,
        "case_statuses": {"1": "scored", "2": "failed"},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _failed_case() -> Any:
    failure = SimpleNamespace(stage="candidate", code="combine_no_votes")
    return SimpleNamespace(case_id="2", status="failed", operations=None, failures=(failure,))


def _report(*, url4: str = _URL4, score: float | None = 0.5, cases: list[Any] | None = None) -> Any:
    scored = _case("1")
    scored.status, scored.failures = "scored", ()
    outcome = SimpleNamespace(url4=url4, score=score, cases=cases or [scored, _failed_case()])
    return SimpleNamespace(
        benchmark=SimpleNamespace(revision="rev-1"), candidates=SimpleNamespace(only=outcome)
    )


def test_a_reproducing_replay_is_accepted_and_its_statuses_returned() -> None:
    assert reducer_lane._refuse_unless_reproduced(_report(), _facts()) == {
        "1": "scored",
        "2": "failed",
    }


@pytest.mark.parametrize(
    ("report", "reason"),
    [
        (_report(url4="(another expression)"), "different url4"),
        (_report(score=0.25), "score"),
    ],
)
def test_a_replay_that_does_not_reproduce_the_report_refuses_the_bless(
    report: Any, reason: str
) -> None:
    with pytest.raises(SystemExit, match=reason):
        reducer_lane._refuse_unless_reproduced(report, _facts())


def test_a_replay_with_other_case_statuses_refuses_the_bless() -> None:
    facts = _facts(case_statuses={"1": "scored", "2": "scored"})
    with pytest.raises(SystemExit, match="case statuses diverge"):
        reducer_lane._refuse_unless_reproduced(_report(), facts)


def test_the_pinned_evidence_is_the_first_case_that_carries_it() -> None:
    cases = [_failed_case(), _case("7"), _case("8")]

    lock = reducer_lane._evidence(cases)

    assert (lock.case_id, lock.operation_id) == ("7", "op_synthesis_1")
    assert lock.combine == _evidence().to_dict()


def test_a_run_without_combine_evidence_refuses_the_bless() -> None:
    with pytest.raises(SystemExit, match="no case carries combine evidence"):
        reducer_lane._evidence([_failed_case()])


def test_the_authored_golden_holds_the_five_locks_and_the_evidence() -> None:
    spec = ReducerCandidateSpec.model_validate(_spec_doc())
    statuses = {"1": "scored", "2": "failed"}

    golden = reducer_lane._author_golden(_report(), spec, statuses)

    assert golden.lane == "inspect-gsm8k-vote"
    assert (golden.board, golden.revision, golden.limit) == ("inspect-gsm8k", "rev-1", 2)
    assert golden.expression_sha == expression_sha(_URL4)
    assert golden.final_score == canonical_score(0.5) == "0.5"
    assert (golden.case_count, golden.gradeable_count) == (2, 1)
    assert [(f.stage, f.code) for f in golden.case_failures["2"]] == [
        ("candidate", "combine_no_votes")
    ]
    assert golden.evidence.case_id == "1"


def test_record_arguments_default_to_the_documented_lane() -> None:
    args = reducer_lane._parse_args(["record", "--model", "openrouter/x/y", "--out", "out"])

    assert (args.samples, args.temperature, args.limit) == (5, 0.7, 20)
    assert (args.extract, args.normalize) == ("last_number", "numeric")
    assert args.run is reducer_lane.record
