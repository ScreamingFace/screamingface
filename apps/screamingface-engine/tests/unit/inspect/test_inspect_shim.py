# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against. Only unresolved-import
# reporting is relaxed; every other diagnostic stays on, and with the extra installed
# these imports type-check normally.
"""The inspect scorer shim — their marking scheme, our marking room (spec §3.2).

INVARIANT the suite defends: ONE translator with zero per-scorer branches wraps any
inspect scorer as a board's `grade_case` hook. Verdicts and failures are complete
values; a scorer that raises or returns an unmappable Score becomes a NAMED failure
code, never a silent drop; the judge's own words (answer/explanation/metadata) survive
into the checks evidence verbatim.

Runs only with the `inspect` extra installed (`uv run --extra inspect pytest …`);
the plain gate run skips it, which is exactly the extra-less contract.
"""

from __future__ import annotations

from typing import Any

import pytest

inspect_ai_scorer = pytest.importorskip("inspect_ai.scorer")

from inspect_ai.scorer import CORRECT, INCORRECT, Score, Target, match  # noqa: E402
from inspect_ai.solver import TaskState  # noqa: E402

from screamingface_engine.benchmarks.spine.payloads import TextPayload  # noqa: E402
from screamingface_engine.benchmarks.spine.scored import (  # noqa: E402
    CaseGradeOutcome,
    GradeRequest,
)
from screamingface_engine_inspect.shim import inspect_grade_case  # noqa: E402


def _request(
    *,
    answer: str | None = "ANSWER: 42",
    material: object | None = None,
) -> GradeRequest:
    return GradeRequest(
        case_id=7,
        input=TextPayload(text="What is 6 times 7?"),
        answer=None if answer is None else TextPayload(text=answer),
        row={"case": {"status": "answered"}},
        material={"target": "42"} if material is None else material,
    )


def _scorer_returning(score: Score):
    async def scorer(state: TaskState, target: Target) -> Score:
        return score

    return scorer


async def _graded(scorer: Any, request: GradeRequest) -> CaseGradeOutcome:
    return await inspect_grade_case(scorer)(request)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (CORRECT, 1.0),
        (INCORRECT, 0.0),
        ("P", 0.5),
        ("N", 0.0),
        (True, 1.0),
        (False, 0.0),
        (1, 1.0),
        (0.25, 0.25),
    ],
)
async def test_score_values_map_to_floats(value: Any, expected: float) -> None:
    outcome = await _graded(_scorer_returning(Score(value=value)), _request())
    assert outcome.failure_code is None
    assert outcome.score == expected


@pytest.mark.asyncio
async def test_real_match_scorer_grades_correct_and_incorrect() -> None:
    """The honesty proof: a REAL inspect scorer passes through the shim untouched."""

    scorer = match(numeric=True)
    right = await _graded(scorer, _request(answer="The answer is...\n\nANSWER: 42"))
    wrong = await _graded(scorer, _request(answer="ANSWER: 41"))
    assert (right.score, right.failure_code) == (1.0, None)
    assert (wrong.score, wrong.failure_code) == (0.0, None)


@pytest.mark.asyncio
async def test_scorer_exception_becomes_scorer_error() -> None:
    async def broken(state: TaskState, target: Target) -> Score:
        raise RuntimeError("judge exploded mid-call")

    outcome = await _graded(broken, _request())
    assert outcome.score is None
    assert outcome.failure_code == "scorer_error"
    # The cause is audit material — the exception's own words ride the evidence.
    assert "judge exploded mid-call" in str(outcome.checks)


@pytest.mark.asyncio
async def test_unmappable_score_value_becomes_invalid_score_value() -> None:
    outcome = await _graded(
        _scorer_returning(Score(value=["C", "I"])),
        _request(),
    )
    assert outcome.score is None
    assert outcome.failure_code == "invalid_score_value"


@pytest.mark.asyncio
async def test_none_score_becomes_invalid_score_value() -> None:
    """Their Scorer protocol admits None ("not scored") — it must fail by name."""

    async def unscoring(state: TaskState, target: Target) -> Score | None:
        return None

    outcome = await _graded(unscoring, _request())
    assert outcome.score is None
    assert outcome.failure_code == "invalid_score_value"


@pytest.mark.asyncio
async def test_unknown_string_value_becomes_invalid_score_value() -> None:
    outcome = await _graded(_scorer_returning(Score(value="MAYBE")), _request())
    assert outcome.failure_code == "invalid_score_value"


@pytest.mark.asyncio
async def test_evidence_preserves_the_judges_own_words() -> None:
    score = Score(
        value=CORRECT,
        answer="42",
        explanation="the model committed to forty-two",
        metadata={"judge_note": "clean extraction"},
    )
    outcome = await _graded(_scorer_returning(score), _request())
    rendered = str(outcome.checks)
    assert "42" in rendered
    assert "the model committed to forty-two" in rendered
    assert "clean extraction" in rendered


@pytest.mark.asyncio
async def test_missing_answer_grades_an_empty_completion() -> None:
    """A refusal/empty answer is graded as "" — inspect's own empty-prediction path."""

    outcome = await _graded(match(numeric=True), _request(answer=None))
    assert outcome.failure_code is None
    assert outcome.score == 0.0


@pytest.mark.asyncio
async def test_non_text_payload_kind_is_rejected() -> None:
    class _EnvelopeOfTomorrow:
        kind = "environment"

    request = GradeRequest(
        case_id=1,
        input=_EnvelopeOfTomorrow(),  # type: ignore[arg-type]
        answer=None,
        row={},
        material={"target": "42"},
    )
    with pytest.raises(TypeError, match="text"):
        await inspect_grade_case(match(numeric=True))(request)


@pytest.mark.asyncio
async def test_material_without_target_is_rejected() -> None:
    with pytest.raises(TypeError, match="target"):
        await inspect_grade_case(match(numeric=True))(_request(material={"label": "B"}))


@pytest.mark.asyncio
async def test_choices_material_replays_inspects_answer_marking() -> None:
    """MCQ path: inspect's own parse/mark step runs when the material declares choices.

    Uses the REAL `choice()` scorer, which reads marks the multiple_choice SOLVER would
    have left on state.choices — the shim replays that step from the material.
    """

    from inspect_ai.scorer import choice

    material = {"target": "B", "choices": ["Paris", "Berlin", "London"]}
    right = await _graded(choice(), _request(answer="ANSWER: B", material=material))
    wrong = await _graded(choice(), _request(answer="ANSWER: C", material=material))
    assert (right.score, right.failure_code) == (1.0, None)
    assert (wrong.score, wrong.failure_code) == (0.0, None)
