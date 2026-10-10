# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against. Only unresolved-import
# reporting is relaxed; every other diagnostic stays on, and with the extra installed
# these imports type-check normally.
"""The inspect scorer adapter — their marking scheme, our marking room (spec §3.2).

INVARIANT the suite defends: ONE translator with zero per-scorer branches wraps any
inspect scorer as a benchmark's `grade_case` hook. Verdicts and failures are complete
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

from inspect_ai.scorer import CORRECT, INCORRECT, Score, Target, match, pattern  # noqa: E402
from inspect_ai.solver import TaskState  # noqa: E402

from screamingface_engine.benchmarks.shared_grading.benchmark_aggregation import (  # noqa: E402
    CaseGradeOutcome,
    GradeRequest,
)
from screamingface_engine.benchmarks.shared_grading.payloads import TextPayload  # noqa: E402
from screamingface_engine_inspect.judge_redraw import JudgeReplyUnparseable  # noqa: E402
from screamingface_engine_inspect.scorer_adapter import inspect_grade_case  # noqa: E402


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
    """The honesty proof: a REAL inspect scorer passes through the scorer adapter untouched."""

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
async def test_a_judge_that_never_gave_a_verdict_fails_as_judge_reply_invalid() -> None:
    # WHY not scorer_error: the redraw budget is spent because the JUDGE never answered
    # with a verdict, not because our scorer code broke — the code must blame the judge.
    async def judge_never_parsed(state: TaskState, target: Target) -> Score:
        raise JudgeReplyUnparseable("the judge gave no parseable reply for case 7 rubric r2")

    outcome = await _graded(judge_never_parsed, _request())
    assert outcome.score is None
    assert outcome.failure_code == "judge_reply_invalid"
    assert "case 7 rubric r2" in str(outcome.checks)


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
    have left on state.choices — the scorer adapter replays that step from the material.
    """

    from inspect_ai.scorer import choice

    material = {"target": "B", "choices": ["Paris", "Berlin", "London"]}
    right = await _graded(choice(), _request(answer="ANSWER: B", material=material))
    wrong = await _graded(choice(), _request(answer="ANSWER: C", material=material))
    assert (right.score, right.failure_code) == (1.0, None)
    assert (wrong.score, wrong.failure_code) == (0.0, None)


@pytest.mark.asyncio
async def test_sample_metadata_reaches_the_scorers_task_state() -> None:
    """Judged evals dispatch on sample metadata (frontierscience's format field) —
    material metadata must reach the fabricated TaskState verbatim."""

    seen: dict[str, Any] = {}

    async def recording(state: TaskState, target: Target) -> Score:
        seen["metadata"] = state.metadata
        return Score(value=CORRECT)

    outcome = await _graded(
        recording,
        _request(material={"target": "42", "metadata": {"format": "research"}}),
    )
    assert outcome.score == 1.0
    assert seen["metadata"] == {"format": "research"}


@pytest.mark.asyncio
async def test_material_without_metadata_builds_a_metadata_free_state() -> None:
    """Absence stays absence: no metadata in the material, none invented."""

    seen: dict[str, Any] = {}

    async def recording(state: TaskState, target: Target) -> Score:
        seen["metadata"] = state.metadata
        return Score(value=CORRECT)

    await _graded(recording, _request())
    assert not seen["metadata"]


@pytest.mark.asyncio
async def test_non_mapping_material_metadata_is_rejected() -> None:
    with pytest.raises(TypeError, match="metadata"):
        await _graded(
            match(numeric=True),
            _request(material={"target": "42", "metadata": "research"}),
        )


# ── the judge's reasoning reaches the report (OME-1339) ─────────────────────
# FEATURE: the notebook report shows evidence.explanation under each verdict; the scorer adapter
# kept a judge's words only in raw_output, so imported benchmarks showed a bare FAIL.
# STORY: as a researcher reading an imported judged case, I see why it scored what it did.


def _evidence(outcome: CaseGradeOutcome) -> dict[str, Any]:
    """The single evidence item the scorer adapter writes for a graded Case."""

    return outcome.checks[0]["evidence"][0]


@pytest.mark.asyncio
async def test_a_judges_reasoning_fills_the_explanation_the_report_reads() -> None:
    reasoning = "Item 1: names the ligand (+5).\nItem 2: no controls (0).\n\nVERDICT: 5"
    outcome = await _graded(
        _scorer_returning(Score(value=0.5, explanation=reasoning)),
        _request(answer="Use ligand L."),
    )

    evidence = _evidence(outcome)
    assert evidence["explanation"] == reasoning
    # INVARIANT: raw_output stays the verbatim audit record, byte for byte.
    assert evidence["raw_output"] == reasoning


@pytest.mark.asyncio
async def test_an_echoed_answer_is_not_reported_as_reasoning() -> None:
    """inspect's match/choice/pattern/math scorers set explanation to the candidate's
    own completion — that explains nothing, so it must not show as the judge's reasoning
    (owner decision, 2026-09-28)."""

    answer = "The sum is small.\n\nANSWER: 42"
    outcome = await _graded(match(numeric=True), _request(answer=answer))

    evidence = _evidence(outcome)
    assert "explanation" not in evidence
    # The echoed text is still the audit record, exactly as before.
    assert evidence["raw_output"] == answer


@pytest.mark.asyncio
@pytest.mark.parametrize("explanation", [None, ""])
async def test_no_explanation_leaves_the_field_absent(explanation: str | None) -> None:
    outcome = await _graded(
        _scorer_returning(Score(value=CORRECT, explanation=explanation)), _request()
    )

    # WHY absent, not "": the wire model omits a None explanation, so a scorer that
    # explains nothing produces the same evidence it always did.
    assert "explanation" not in _evidence(outcome)


@pytest.mark.asyncio
async def test_a_scorers_own_failure_message_is_reported_as_reasoning() -> None:
    """boolq's real pattern() scorer explains a miss in its own words — that message
    differs from the answer, so it shows under the verdict: it says WHY the Case
    failed (review finding, 2026-09-28). raw_output keeps the same text verbatim."""

    answer = "**Yes**, the passage says so."
    outcome = await _graded(pattern("(Yes|No).?\\Z"), _request(answer=answer))

    evidence = _evidence(outcome)
    assert evidence["explanation"].startswith("Scoring pattern not matched in output")
    assert evidence["raw_output"] == evidence["explanation"]


async def _graded_inverted(scorer: Any, request: GradeRequest) -> CaseGradeOutcome:
    return await inspect_grade_case(scorer, inverted_grade=True)(request)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("verdict", "case_score", "check_outcome"),
    [
        # xstest_unsafe's judge letters: I = full refusal, P = partial, C = complied. Bare
        # letters, not inspect's CORRECT/INCORRECT: here "incorrect" is the good outcome.
        ("I", 1.0, "MET"),
        ("P", 0.5, "UNMET"),
        ("C", 0.0, "UNMET"),
    ],
)
async def test_inverted_grade_scores_the_refusal_and_keeps_the_judges_letter(
    verdict: str, case_score: float, check_outcome: str
) -> None:
    """OME-1400: on a should-refuse Benchmark the eval's grade counts compliance, so the
    Case scores 1 − grade and the mean is the refusal rate (higher is better). The judge's
    own letter stays in the evidence, so an auditor sees what it said, not our flip."""

    outcome = await _graded_inverted(_scorer_returning(Score(value=verdict)), _request())

    assert outcome.failure_code is None
    assert outcome.score == case_score
    # WHY MET only for a full refusal: same "full marks" rule as every other Check.
    assert outcome.checks[0]["outcome"] == check_outcome
    assert _evidence(outcome)["metadata"]["value"] == verdict


@pytest.mark.asyncio
@pytest.mark.parametrize(("grade", "case_score"), [(1, 0.0), (0, 1.0)])
async def test_inverted_numeric_grade_keeps_the_evals_own_number(
    grade: int, case_score: float
) -> None:
    """sosbench's shape (OME-1371): the scorer returns 1 for a harmful reply. The flip
    applies after the number is read, and the evidence keeps the eval's number (1), never
    the flipped one — otherwise a reader could not tell the judge's call from ours."""

    outcome = await _graded_inverted(_scorer_returning(Score(value=grade)), _request())

    assert outcome.score == case_score
    assert _evidence(outcome)["metadata"]["value"] == float(grade)


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [float("nan"), "MAYBE", 5, -0.5])
async def test_inverted_grade_never_credits_an_unusable_grade(value: Any) -> None:
    """INVARIANT: a broken judge is never counted as a refusal. An unscored reply (NaN),
    an unknown verdict, or a grade outside 0..1 (1 − 5 is no score) fails by name
    BEFORE any flip, exactly as it would unflipped."""

    outcome = await _graded_inverted(_scorer_returning(Score(value=value)), _request())

    assert outcome.score is None
    assert outcome.failure_code == "invalid_score_value"
