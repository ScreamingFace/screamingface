# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against. Only unresolved-import
# reporting is relaxed; every other diagnostic stays on, and with the extra installed
# these imports type-check normally.
"""Wrap one inspect scorer as a board's ``grade_case`` hook — the hourglass waist proof.

Think of an inspect scorer as an external examiner who only reads their own exam-office
forms. This shim is the clerk who copies our sealed grade request onto their forms
(``TaskState`` + ``Target``), hands them over, and copies their mark (``Score``) back
onto ours (``CaseGradeOutcome``) — one clerk for ALL scorers, with ZERO per-scorer
branches (spec ``docs/spec/2026-09-09-OME-1113-inspect-evals-import.md`` §3.2). If any
of the ~94 single-shot scorers ever needs a special case here, the seam failed review.

Stages, in execution order (see :func:`inspect_grade_case`):

    Stage 1 — unpack our envelope: input/answer must be kind="text" (the only kind
              today, §7 scope); a missing answer grades as "" — inspect's own
              empty-prediction path.
    Stage 2 — build the minimal TaskState + Target from the request's grading material
              (the imported Sample's target, plus its choices for MCQ boards). When the
              material declares choices, replay inspect's OWN answer-marking step
              (``parse_answers`` + ``set_choices_based_on_generated_response``) — their
              ``choice()`` scorer reads marks the ``multiple_choice`` solver would have
              left, and we import no solver, so the marking is part of building the
              state their scorer expects. Keyed off the MATERIAL's shape, never off
              which scorer — still zero per-scorer branches.
    Stage 3 — await their scorer. A raise becomes the named failure code
              ``scorer_error`` with the exception's words as evidence, never a crash of
              the whole aggregate.
    Stage 4 — translate the Score: value → float (worked example: CORRECT "C" → 1.0,
              "P" → 0.5, ``0.25`` → 0.25, ``True`` → 1.0); an unmappable value (a list,
              an unknown string) → ``invalid_score_value``; answer/explanation/metadata
              → the checks evidence block, preserving the judge's own words.

INVARIANT: everything crosses as plain data — the shim reads only the ``GradeRequest``
and returns a complete ``CaseGradeOutcome``; it never reaches around the hook.

INVARIANT: no silent coercion. inspect's own ``value_to_float`` maps unknown values to
0.0 with a log warning; a wrong grade published as a real one is exactly the failure
mode the named codes exist to prevent, so the mapping here is explicit and closed.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import Any

from inspect_ai.model import ChatMessageUser, ModelOutput
from inspect_ai.scorer import Score, Scorer, Target
from inspect_ai.solver import TaskState
from inspect_ai.solver._multiple_choice import (
    parse_answers,
    set_choices_based_on_generated_response,
)

from screamingface_engine.benchmarks.grading_activity import grading_activity
from screamingface_engine.benchmarks.spine.payloads import CasePayload
from screamingface_engine.benchmarks.spine.scored import (
    CaseGradeOutcome,
    GradeCase,
    GradeRequest,
)

#: Score string verdicts → floats, per inspect's own vocabulary: CORRECT / INCORRECT /
#: PARTIAL / NOANSWER. Closed on purpose (see the module invariant).
_STRING_VALUES: Mapping[str, float] = {"C": 1.0, "I": 0.0, "P": 0.5, "N": 0.0}

#: The scorer's model identity inside the fabricated TaskState. Display-only — no
#: model is resolved from it; the candidate already answered upstream.
_CANDIDATE_MODEL = "screamingface/candidate"


def inspect_grade_case(scorer: Scorer, *, multiple_correct: bool = False) -> GradeCase:
    """Wrap one inspect scorer as this board's ``grade_case`` hook.

    Args:
        scorer: the imported eval's scorer — any standalone async callable obeying
            inspect's ``(state, target) -> Score`` protocol.
        multiple_correct: whether an MCQ board admits multiple correct letters
            (inspect's ``parse_answers`` flag); single-answer boards leave the default.

    Returns:
        The async hook the spine calls once per gradeable Case.
    """

    async def grade(request: GradeRequest) -> CaseGradeOutcome:
        # Stage 1-2 — unpack our envelope, build their exam-office forms.
        state, target = _task_state(request, multiple_correct)
        # Stage 3 — their examiner marks the script.
        try:
            score: Score | None = await scorer(state, target)
        except Exception as exc:  # noqa: BLE001 — WHY broad: the scorer is stranger
            # code from any of ~94 community evals; ANY raise must become this board's
            # named failure, not an aborted aggregate for the other 49 Cases.
            return _failure("scorer_error", f"{type(exc).__name__}: {exc}")
        # Stage 4 — copy their mark back onto our form.
        return _outcome(score)

    async def observed(request: GradeRequest) -> CaseGradeOutcome:
        grading_activity(request.case_id, "started")
        try:
            outcome = await grade(request)
        except Exception:
            grading_activity(request.case_id, "failed")
            raise
        grading_activity(request.case_id, "failed" if outcome.failure_code else "completed")
        return outcome

    return observed


def _outcome(score: Score | None) -> CaseGradeOutcome:
    """Stage 4 — one complete outcome per Score, unmappable values failing by name."""

    if score is None:
        # Their protocol admits "no score"; a Case must still fail by name.
        return _failure("invalid_score_value", "scorer returned no Score")
    value: float | None = _score_as_float(score.value)
    if value is None:
        return _failure("invalid_score_value", repr(score.value), score)
    return CaseGradeOutcome(score=value, metrics={}, checks=[_check(score, value)])


def _task_state(request: GradeRequest, multiple_correct: bool) -> tuple[TaskState, Target]:
    """Stage 2 — the minimal TaskState/Target their scorer protocol expects."""

    input_text: str = _text(request.input, "input")
    completion: str = "" if request.answer is None else _text(request.answer, "answer")
    material: Mapping[str, Any] = _material(request.material)
    choices: list[str] | None = _choices(material)
    state = TaskState(
        model=_CANDIDATE_MODEL,  # type: ignore[arg-type]  # ModelName is a str alias at runtime
        sample_id=int(request.case_id),
        epoch=1,
        input=input_text,
        messages=[ChatMessageUser(content=input_text)],
        choices=choices,
        output=ModelOutput.from_content(model=_CANDIDATE_MODEL, content=completion),
        # WHY: metadata-dispatching scorers (frontierscience's format field) read
        # the Sample's metadata off the state; the bake delivers it in the target
        # record behind SnapshotSpec.keep_sample_metadata (OME-1240).
        metadata=_sample_metadata(material),
    )
    if choices:
        # WHY: their choice() scorer reads marks the multiple_choice SOLVER leaves on
        # state.choices; we import no solver, so the marking replays THEIR functions.
        set_choices_based_on_generated_response(state, parse_answers(state, multiple_correct))
    return state, Target(material["target"])


def _text(payload: CasePayload, label: str) -> str:
    kind: object = getattr(payload, "kind", None)
    if kind != "text":
        raise TypeError(
            f"inspect grade_case supports only kind='text' payloads today, "
            f"got {label} kind {kind!r} (spec §7 scope)"
        )
    return payload.text


def _material(material: object) -> Mapping[str, Any]:
    if not isinstance(material, Mapping) or "target" not in material:
        raise TypeError(
            "inspect grading material must be a mapping carrying the imported Sample's 'target'"
        )
    return material


def _sample_metadata(material: Mapping[str, Any]) -> dict[str, Any]:
    """The baked Sample metadata off the target record; absence stays an empty dict."""

    metadata: object = material.get("metadata")
    if metadata is None:
        return {}
    if not isinstance(metadata, Mapping):
        raise TypeError("inspect grading material 'metadata' must be a mapping")
    return dict(metadata)


def _choices(material: Mapping[str, Any]) -> list[str] | None:
    choices: object = material.get("choices")
    if choices is None:
        return None
    if not isinstance(choices, list) or any(not isinstance(item, str) for item in choices):
        raise TypeError("inspect grading material 'choices' must be a list of strings")
    return choices


def _score_as_float(value: object) -> float | None:
    """The closed value → float map; ``None`` means unmappable (never coerced)."""

    mapped: float | None
    # bool before int — bool IS an int, and True must read as 1.0 by intent, not accident.
    if isinstance(value, bool):
        mapped = 1.0 if value else 0.0
    elif isinstance(value, int | float):
        # INVARIANT: a grade is a finite number. inspect returns Score(value=NaN)
        # for an unscored model_graded reply; the wire model rejects non-finite
        # values, and letting NaN through would abort the WHOLE aggregate after
        # every candidate call is already paid for (review finding, 2026-09-24).
        mapped = float(value) if math.isfinite(value) else None
    elif isinstance(value, str):
        mapped = _STRING_VALUES.get(value)
    else:
        mapped = None
    return mapped


def _check(score: Score, value: float) -> dict[str, Any]:
    """One check entry preserving the judge's own words as evidence."""

    return {
        "type": "inspect_scorer",
        "id": "1",
        "label": "inspect scorer verdict",
        "outcome": "MET" if value >= 1.0 else "UNMET",
        "evidence": [
            {
                "sequence": 1,
                "producer": {"type": "inspect_scorer", "id": "inspect/scorer"},
                "valid": True,
                "outcome": "PASS" if value >= 1.0 else "FAIL",
                # The judge's own words, verbatim — audit material for every Case.
                "raw_output": score.explanation or "",
                "metadata": {
                    "value": score.value if isinstance(score.value, str) else value,
                    "answer": score.answer,
                    **_json_metadata(score.metadata),
                },
                "accounting": None,
            }
        ],
        "metadata": {"answer": score.answer},
    }


def _json_metadata(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    """Only JSON-safe metadata entries may cross into the wire evidence.

    WHY: judge scorers (``model_graded_qa``) attach rich objects to
    ``Score.metadata`` — their whole grading transcript, chat messages and usage
    objects included — and the report's wire model refuses non-JSON values. The
    judge's own words already ride ``raw_output``/``explanation``, so dropping an
    unserializable transcript loses no audit material. Still zero per-scorer
    branches: the rule is "JSON crosses, objects don't", whoever the scorer is.
    """

    if not metadata:
        return {}
    safe: dict[str, Any] = {}
    for key, value in metadata.items():
        try:
            json.dumps(value)
        except (TypeError, ValueError):
            continue
        safe[key] = value
    return safe


def _failure(code: str, detail: str, score: Score | None = None) -> CaseGradeOutcome:
    """A named, complete failure outcome — the cause rides the evidence, never a log."""

    evidence: dict[str, Any] = {
        "sequence": 1,
        "producer": {"type": "inspect_scorer", "id": "inspect/scorer"},
        # INVARIANT (wire model): invalid evidence claims NO outcome/explanation —
        # the cause rides raw_output + rejection_reason, the rubric evidence rule.
        "valid": False,
        "raw_output": detail,
        "metadata": {
            "rejection_reason": detail,
            **({} if score is None else {"answer": score.answer}),
        },
        "accounting": None,
    }
    return CaseGradeOutcome(
        score=None,
        metrics={},
        checks=[
            {
                "type": "inspect_scorer",
                "id": "1",
                "label": "inspect scorer verdict",
                "outcome": "UNMET",
                "evidence": [evidence],
                "metadata": {"failure": code},
            }
        ],
        failure_code=code,
    )


__all__ = ["inspect_grade_case"]
