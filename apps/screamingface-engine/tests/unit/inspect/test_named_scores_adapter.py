# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""The scorer adapter grades a Case once per declared scorer (OME-1268, PR 3 of 5).

FEATURE: a Benchmark with several scorers (SQuAD: f1 and exact) marks the same answer once
per scorer and writes every value by name; the Headline Score is the first declared name and
IS the Case score. One scorer returning a dict of named numbers (SimpleQA, cyberseceval_4)
becomes the same shape.

INVARIANT: the Inverted Grade flip and the Benchmark's word map apply to the headline scorer
only; inspect's own letters map everywhere; one scorer failing fails the whole Case by name,
so every column shares one denominator; a row that declares no names grades exactly as before.
"""

from __future__ import annotations

from typing import Any

import pytest

inspect_ai_scorer = pytest.importorskip("inspect_ai.scorer")

from inspect_ai.scorer import Score, Target, exact, f1  # noqa: E402
from inspect_ai.solver import TaskState  # noqa: E402

from screamingface_engine.benchmarks.shared_grading.benchmark_aggregation import (  # noqa: E402
    CaseGradeOutcome,
    GradeRequest,
)
from screamingface_engine.benchmarks.shared_grading.payloads import TextPayload  # noqa: E402
from screamingface_engine_inspect.judge_redraw import JudgeReplyUnparseable  # noqa: E402
from screamingface_engine_inspect.scorer_adapter import inspect_grade_case  # noqa: E402


def _request(answer: str = "It was built in 1889.", target: object = "1889") -> GradeRequest:
    return GradeRequest(
        case_id=7,
        input=TextPayload(text="When was the Eiffel Tower built?"),
        answer=TextPayload(text=answer),
        row={"case": {"status": "answered"}},
        material={"target": target},
    )


def _returning(value: Any):
    async def scorer(state: TaskState, target: Target) -> Score:
        return Score(value=value, answer="x", explanation="judge says so")

    return scorer


def _raising():
    async def scorer(state: TaskState, target: Target) -> Score:
        raise RuntimeError("second scorer exploded")

    return scorer


# --- several scorers ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_scorers_grade_the_same_answer_once_each() -> None:
    # Review Focus 2: one call per scorer, every value by name, one Check per scorer in
    # declaration order, each carrying that scorer's own value as Evidence.
    hook = inspect_grade_case(
        _returning("C"), extra_scorers=[_returning("I")], named_scores=("f1", "exact")
    )
    outcome: CaseGradeOutcome = await hook(_request())

    assert outcome.failure_code is None
    assert outcome.scores == {"f1": 1.0, "exact": 0.0}
    assert outcome.score == 1.0
    assert [check["id"] for check in outcome.checks] == ["f1", "exact"]
    assert [check["outcome"] for check in outcome.checks] == ["MET", "UNMET"]


@pytest.mark.asyncio
async def test_real_inspect_scorers_grade_a_list_target_by_name() -> None:
    """The honesty proof: inspect's own f1 and exact on SQuAD's list of accepted answers."""

    hook = inspect_grade_case(f1(), extra_scorers=[exact()], named_scores=("f1", "exact"))
    outcome = await hook(_request(answer="1889", target=["1889", "1887–1889"]))

    assert outcome.failure_code is None
    assert outcome.scores == {"f1": 1.0, "exact": 1.0}
    partial = await hook(_request(answer="in 1889 I think", target=["1889", "1887–1889"]))
    partial_f1: float | None = partial.scores["f1"]
    assert partial_f1 is not None
    assert 0.0 < partial_f1 < 1.0
    assert partial.scores["exact"] == 0.0
    assert partial.score == partial_f1


@pytest.mark.asyncio
async def test_headline_score_is_the_named_headline_column() -> None:
    hook = inspect_grade_case(
        _returning(0.25), extra_scorers=[_returning(0.75)], named_scores=("f1", "exact")
    )
    outcome = await hook(_request())

    assert outcome.score == outcome.scores["f1"] == 0.25
    assert outcome.scores["exact"] == 0.75


@pytest.mark.asyncio
async def test_inverted_grade_flips_the_headline_only() -> None:
    # Review Focus 4: a Named Score carries no direction, so only the headline column flips.
    hook = inspect_grade_case(
        _returning("C"),
        extra_scorers=[_returning("C")],
        named_scores=("refusal", "other"),
        inverted_grade=True,
    )
    outcome = await hook(_request())

    assert outcome.score == 0.0
    assert outcome.scores == {"refusal": 0.0, "other": 1.0}


@pytest.mark.asyncio
async def test_verdict_grades_map_the_headline_scorer_only() -> None:
    # The Benchmark's own word map is the headline scorer's vocabulary; the other scorer
    # still speaks inspect's letters, so a word there is unmappable and fails the Case.
    hook = inspect_grade_case(
        _returning("UNACCEPTABLE"),
        extra_scorers=[_returning("C")],
        named_scores=("compliance", "letter"),
        verdict_grades={"UNACCEPTABLE": 1.0, "ACCEPTABLE": 0.0},
    )
    outcome = await hook(_request())
    assert outcome.scores == {"compliance": 1.0, "letter": 1.0}

    crossed = inspect_grade_case(
        _returning("ACCEPTABLE"),
        extra_scorers=[_returning("UNACCEPTABLE")],
        named_scores=("compliance", "letter"),
        verdict_grades={"UNACCEPTABLE": 1.0, "ACCEPTABLE": 0.0},
    )
    failed = await crossed(_request())
    assert failed.failure_code == "invalid_score_value"
    assert "letter" in str(failed.checks)


@pytest.mark.asyncio
async def test_one_failing_scorer_fails_the_case_naming_it() -> None:
    # Plan D6: no half-graded Case, so every column shares Coverage's denominator.
    hook = inspect_grade_case(
        _returning("C"), extra_scorers=[_raising()], named_scores=("f1", "exact")
    )
    outcome = await hook(_request())

    assert outcome.score is None
    assert outcome.scores == {}
    assert outcome.failure_code == "scorer_error"
    assert "exact" in str(outcome.checks)
    assert "second scorer exploded" in str(outcome.checks)


@pytest.mark.asyncio
async def test_a_second_scorer_whose_judge_never_parsed_fails_as_judge_reply_invalid() -> None:
    # The judge, not our code, is to blame on every scorer, not just the headline one.
    async def judge_never_parsed(state: TaskState, target: Target) -> Score:
        raise JudgeReplyUnparseable("the judge gave no parseable reply for case 7 rubric r2")

    hook = inspect_grade_case(
        _returning("C"), extra_scorers=[judge_never_parsed], named_scores=("f1", "exact")
    )
    outcome = await hook(_request())

    assert outcome.failure_code == "judge_reply_invalid"
    assert "exact" in str(outcome.checks)


@pytest.mark.asyncio
async def test_a_single_scorer_case_grade_has_no_named_scores() -> None:
    # Review Focus 5: a row that declares nothing grades exactly as before.
    outcome = await inspect_grade_case(_returning("C"))(_request())

    assert outcome.scores == {}
    assert outcome.score == 1.0
    assert [check["id"] for check in outcome.checks] == ["1"]


# --- one scorer returning a dict -----------------------------------------------------------


@pytest.mark.asyncio
async def test_a_dict_valued_score_becomes_named_scores() -> None:
    hook = inspect_grade_case(
        _returning({"correct": "C", "incorrect": "I", "not_attempted": "I"}),
        named_scores=("correct", "incorrect", "not_attempted"),
    )
    outcome = await hook(_request())

    assert outcome.failure_code is None
    assert outcome.scores == {"correct": 1.0, "incorrect": 0.0, "not_attempted": 0.0}
    assert outcome.score == 1.0
    assert [check["id"] for check in outcome.checks] == ["1"]


@pytest.mark.asyncio
async def test_a_dict_valued_score_with_numbers_keeps_them() -> None:
    hook = inspect_grade_case(
        _returning({"score": "I", "jaccard_similarity": 0.5}),
        named_scores=("score", "jaccard_similarity"),
    )
    outcome = await hook(_request())

    assert outcome.scores == {"score": 0.0, "jaccard_similarity": 0.5}
    assert outcome.score == 0.0


@pytest.mark.asyncio
async def test_an_undeclared_dict_key_fails_the_case_by_name() -> None:
    # Review Focus 3: a key the row did not declare is never dropped silently.
    hook = inspect_grade_case(_returning({"correct": "C", "bonus": 1.0}), named_scores=("correct",))
    outcome = await hook(_request())

    assert outcome.failure_code == "invalid_score_value"
    assert "bonus" in str(outcome.checks)


@pytest.mark.asyncio
async def test_a_missing_declared_key_fails_the_case_by_name() -> None:
    hook = inspect_grade_case(_returning({"correct": "C"}), named_scores=("correct", "incorrect"))
    outcome = await hook(_request())

    assert outcome.failure_code == "invalid_score_value"
    assert "incorrect" in str(outcome.checks)


@pytest.mark.asyncio
async def test_a_dict_score_without_declared_names_fails_as_invalid_score_value() -> None:
    # The pre-change behaviour for a row that declares nothing: a dict is unmappable.
    outcome = await inspect_grade_case(_returning({"correct": "C"}))(_request())

    assert outcome.failure_code == "invalid_score_value"
    assert outcome.scores == {}


@pytest.mark.asyncio
async def test_a_dict_valued_score_inverts_the_headline_key_only() -> None:
    hook = inspect_grade_case(
        _returning({"complied": "C", "other": "C"}),
        named_scores=("complied", "other"),
        inverted_grade=True,
    )
    outcome = await hook(_request())

    assert outcome.score == 0.0
    assert outcome.scores == {"complied": 0.0, "other": 1.0}


@pytest.mark.asyncio
async def test_named_scores_are_rejected_on_a_scorer_that_returns_a_scalar() -> None:
    # A row that declares two names for ONE scorer expects a dict; a scalar is a mismatch.
    hook = inspect_grade_case(_returning("C"), named_scores=("correct", "incorrect"))
    outcome = await hook(_request())

    assert outcome.failure_code == "invalid_score_value"


def test_the_adapter_refuses_reversed_names_over_registered_scorers() -> None:
    # Keelan's review finding #1 on #1249, the run-time half: f1 and exact under the names
    # ("exact", "f1") would publish f1's mark as exact. Refused when the room is built,
    # before any Case is graded.
    with pytest.raises(ValueError, match=r"named_scores\[0\] is 'exact' but .* 'f1'"):
        inspect_grade_case(f1(), extra_scorers=[exact()], named_scores=("exact", "f1"))
