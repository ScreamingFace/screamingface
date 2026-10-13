"""Answers of a Case: member and computed Answers joined to the operation graph (OME-1289 gap).

STORY: as a researcher, I read what every member answered and what the combine step decided, with
each member's original text, in author order.
"""

from __future__ import annotations

from typing import Any

import pytest
from _answer_fixtures import bound, evidence_cases, fixture_case, fixture_graph
from test_report import candidate

import screamingface as sf
from screamingface.answer import Answer
from screamingface.case_result import CaseOperation
from screamingface.operation import OperationInfo


def _failed_case() -> sf.CaseResult:
    return sf.CaseResult(
        case_id=9,
        input="q",
        output=None,
        finish_reason=None,
        grade=None,
        failures=(
            sf.Failure(stage="candidate", code="candidate_failed", message="failed", case_id=9),
        ),
        metadata={},
    )


def test_case_without_operations_has_no_answers() -> None:
    plain = sf.CaseResult(
        case_id=1,
        input="q",
        output="a",
        finish_reason="stop",
        grade=sf.CaseGrade(method="fixture", score=1.0, metrics={}, checks=()),
        failures=(),
        metadata={},
    )

    assert plain.answers() == ()
    assert _failed_case().answers() == ()
    model_only = sf.CaseResult(
        case_id=2,
        input="q",
        output="a",
        finish_reason="stop",
        grade=sf.CaseGrade(method="fixture", score=1.0, metrics={}, checks=()),
        failures=(),
        metadata={},
        operations=(CaseOperation("op_model_1", "a", "stop"),),
    )
    assert model_only.answers() == ()


def _two_combine_case() -> sf.CaseResult:
    first = fixture_case("vote_one_failed")
    second = evidence_cases()["median_nearest"]
    operations = [
        *(first.operations or ()),
        *(CaseOperation(f"op_model_{k}", f"text {k}", "stop") for k in range(4, 8)),
        CaseOperation("op_synthesis_2", "20", "stop", None, combine=second),
    ]
    case = sf.CaseResult(
        case_id=1,
        input="Question 1",
        output="x",
        finish_reason="stop",
        grade=first.grade,
        failures=(),
        metadata={},
        operations=operations,
    )
    graph = (
        *fixture_graph(3),
        *(OperationInfo(id=f"op_model_{k}", kind="model", label="m") for k in range(4, 8)),
        OperationInfo(
            id="op_synthesis_2",
            kind="combine",
            label="s2",
            depends_on=tuple(f"op_model_{k}" for k in range(4, 8)),
        ),
    )
    return bound(case, graph)


def test_answers_are_in_author_order_then_result() -> None:
    case = _two_combine_case()

    answers = case.answers()
    shape = [(a.member_id, a.status) for a in answers]
    assert shape == [
        ("member_1", "answered"),
        ("member_2", "fail"),
        ("member_3", "answered"),
        ("member_1", "answered"),  # the computed Answer of the vote: the chosen member
        ("member_1", "answered"),
        ("member_2", "answered"),
        ("member_3", "answered"),
        ("member_4", "fail"),
        ("member_2", "answered"),  # the computed Answer of the median: the nearest member
    ]
    assert [a.text for a in answers[:4]] == ["text 1", "text 2", "text 3", "42"]
    assert [a.text for a in answers[4:]] == ["text 4", "text 5", "text 6", "text 7", "20"]
    assert answers[3].raw is None
    assert answers[3].value == "42"
    assert answers[3].signals == {}
    second = case.answers("op_synthesis_2")
    assert second == answers[4:]
    assert case.answers("op_synthesis_1") == answers[:4]
    assert case.answers("op_model_1") == ()
    with pytest.raises(ValueError, match="has no operation 'op_x'"):
        case.answers("op_x")


def test_a_computed_answer_without_a_member_has_no_member_id() -> None:
    case = bound(fixture_case("median_value"), fixture_graph(4))

    computed = case.answers()[-1]
    assert (computed.member_id, computed.value, computed.status) == (None, "20", "answered")
    abstained = bound(fixture_case("vote_abstain"), fixture_graph(3)).answers()[-1]
    assert (abstained.member_id, abstained.value, abstained.status, abstained.reason) == (
        None,
        None,
        "abstain",
        "no_votes",
    )


@pytest.mark.parametrize("name", sorted(evidence_cases()))
def test_answer_round_trips_through_to_dict(name: str) -> None:
    case = bound(fixture_case(name), fixture_graph(len(evidence_cases()[name].members)))

    for answer in case.answers():
        copy = Answer.from_dict(answer.to_dict())
        assert copy == answer
        assert hash(copy) == hash(answer)
        assert list(answer.to_dict()) == [
            "member_id",
            "text",
            "raw",
            "value",
            "status",
            "reason",
            "signals",
        ]


def _answer(**change: Any) -> Answer:
    values: dict[str, Any] = {
        "member_id": "member_1",
        "text": "t",
        "raw": "1",
        "value": "1",
        "status": "answered",
        "reason": None,
    }
    return Answer(**{**values, **change})


def test_answer_from_dict_and_invariants() -> None:
    wire = _answer().to_dict()
    with pytest.raises(ValueError, match="extra"):
        Answer.from_dict({**wire, "extra": 1})
    with pytest.raises(ValueError, match="text"):
        Answer.from_dict({key: value for key, value in wire.items() if key != "text"})
    with pytest.raises(TypeError):
        Answer.from_dict([])  # type: ignore[arg-type]
    for change, error in (
        (
            {"member_id": "abstain", "status": "abstain", "value": None, "reason": "no_votes"},
            ValueError,
        ),
        ({"member_id": None, "status": "abstain", "value": None, "reason": "empty"}, ValueError),
        ({"status": "fail", "reason": "empty"}, ValueError),
        ({"status": "fail", "reason": "no_votes", "value": None}, ValueError),
        ({"reason": "empty"}, ValueError),
        ({"status": "bogus"}, ValueError),
        ({"member_id": "m1"}, ValueError),
        ({"text": 3}, TypeError),
        ({"signals": {"a": "x"}}, TypeError),
        ({"signals": {"a": float("inf")}}, ValueError),
    ):
        with pytest.raises(error):
            _answer(**change)
    assert _answer(signals={"cost_usd": 1}).signals == {"cost_usd": 1.0}


def test_ambiguous_attribution_gives_none_text() -> None:
    case = bound(
        fixture_case("vote_one_failed", outputs=["text 1", None, "text 3"]), fixture_graph(3)
    )

    answers = case.answers()
    assert [a.text for a in answers[:3]] == ["text 1", None, "text 3"]
    assert (answers[1].value, answers[1].status) == (None, "fail")
    assert answers[3].text == "42"  # the computed Answer's text is the combine op output

    unbound = fixture_case("vote_one_failed")
    assert [a.text for a in unbound.answers()[:3]] == [None, None, None]
    assert unbound.answers()[3].text == "42"


def test_candidate_result_binds_its_operation_graph_without_copying() -> None:
    first = fixture_case("vote_one_failed")
    base = candidate("opus")
    graph = fixture_graph(3)
    result = sf.CandidateResult(
        benchmark=base.benchmark,
        run_id=base.run_id,
        started_at=base.started_at,
        completed_at=base.completed_at,
        name=base.name,
        kind=base.kind,
        url4=base.url4,
        models=base.models,
        operations=graph,
        score=1.0,
        coverage=1.0,
        metrics={},
        cases=(first,),
        members=(),
        failures=(),
        usage=base.usage,
    )

    assert result.cases[0] is first
    assert [a.text for a in first.answers()[:3]] == ["text 1", "text 2", "text 3"]
    before = first.to_dict()
    assert "_operation_graph" not in str(before)
    # a Case shared by a second Candidate keeps its first graph (AIDEV-NOTE in the code)
    other = fixture_graph(3, extra=(OperationInfo(id="op_extra", kind="model", label="x"),))
    again = sf.CandidateResult(
        benchmark=base.benchmark,
        run_id="run_2",
        started_at=base.started_at,
        completed_at=base.completed_at,
        name="second",
        kind=base.kind,
        url4=base.url4,
        models=base.models,
        operations=other,
        score=1.0,
        coverage=1.0,
        metrics={},
        cases=(first,),
        members=(),
        failures=(),
        usage=base.usage,
    )
    assert again.cases[0] is first
    assert [a.text for a in first.answers()[:3]] == ["text 1", "text 2", "text 3"]
    assert first.to_dict() == before


def _candidate_over(case: sf.CaseResult, *, coverage: float) -> sf.CandidateResult:
    base = candidate("opus")
    return sf.CandidateResult(
        benchmark=base.benchmark,
        run_id=base.run_id,
        started_at=base.started_at,
        completed_at=base.completed_at,
        name=base.name,
        kind=base.kind,
        url4=base.url4,
        models=base.models,
        operations=fixture_graph(3),
        score=1.0,
        coverage=coverage,
        metrics={},
        cases=(case,),
        members=(),
        failures=(),
        usage=base.usage,
    )


def test_a_candidate_that_fails_validation_leaves_its_cases_unbound() -> None:
    case = fixture_case("vote_one_failed")

    with pytest.raises(ValueError):
        _candidate_over(case, coverage=0.5)
    assert [a.text for a in case.answers()[:3]] == [None, None, None]

    _candidate_over(case, coverage=1.0)
    assert [a.text for a in case.answers()[:3]] == ["text 1", "text 2", "text 3"]
