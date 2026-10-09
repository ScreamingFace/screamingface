# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against. Only unresolved-import
# reporting is relaxed; every other diagnostic stays on, and with the extra installed
# these imports type-check normally.
"""Wrap one inspect scorer as a benchmark's ``grade_case`` hook — the hourglass waist proof.

Think of an inspect scorer as an external examiner who only reads their own benchmark-office
forms. This adapter is the clerk who copies our sealed grade request onto their forms
(``TaskState`` + ``Target``), hands them over, and copies their mark (``Score``) back
onto ours (``CaseGradeOutcome``) — one clerk for ALL scorers, with ZERO per-scorer
branches (spec ``docs/spec/2026-09-09-OME-1113-inspect-evals-import.md`` §3.2). If any
of the ~94 single-shot scorers ever needs a special case here, the seam failed review.

Stages, in execution order (see :func:`inspect_grade_case`):

    Stage 1 — unpack our envelope: input/answer must be kind="text" (the only kind
              today, §7 scope); a missing answer grades as "" — inspect's own
              empty-prediction path.
    Stage 2 — build the minimal TaskState + Target from the request's grading material
              (the imported Sample's target, plus its choices for MCQ benchmarks). When the
              material declares choices, replay inspect's OWN answer-marking step
              (``parse_answers`` + ``set_choices_based_on_generated_response``) — their
              ``choice()`` scorer reads marks the ``multiple_choice`` solver would have
              left, and we import no solver, so the marking is part of building the
              state their scorer expects. Keyed off the MATERIAL's shape, never off
              which scorer — still zero per-scorer branches.
    Stage 3 — await their scorer. A raise becomes the named failure code
              ``scorer_error`` with the exception's words as evidence, never a crash of
              the whole aggregate — except a judge that never gave a parseable verdict
              (``JudgeReplyUnparseable``), which is ``judge_reply_invalid``: the judge's
              fault, not our code's.
    Stage 4 — translate the Score: value → float (worked example: CORRECT "C" → 1.0,
              "P" → 0.5, ``0.25`` → 0.25, ``True`` → 1.0); an unmappable value (a list,
              an unknown string) → ``invalid_score_value``. A Benchmark whose judge
              answers in WORDS declares its own closed map (``verdict_grades``,
              OME-1371), which replaces the letters: coconot's "UNACCEPTABLE" → 1.0,
              "C" → ``invalid_score_value``. answer/explanation/metadata
              → the checks evidence block, preserving the judge's own words. On a
              Benchmark whose grade counts the unwanted behaviour (``inverted_grade``,
              OME-1400) the Case score is 1 − that grade: xstest_unsafe's judge says "I"
              (refused) → grade 0.0 → Case score 1.0, so the mean is the refusal rate.

INVARIANT: everything crosses as plain data — the scorer adapter reads only the ``GradeRequest``
and returns a complete ``CaseGradeOutcome``; it never reaches around the hook.

INVARIANT: no silent coercion. inspect's own ``value_to_float`` maps unknown values to
0.0 with a log warning; a wrong grade published as a real one is exactly the failure
mode the named codes exist to prevent, so the mapping here is explicit and closed.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from typing import Any

from inspect_ai.model import ChatMessageUser, ModelOutput
from inspect_ai.scorer import Score, Scorer, Target
from inspect_ai.solver import TaskState
from inspect_ai.solver._multiple_choice import (
    parse_answers,
    set_choices_based_on_generated_response,
)

from screamingface_engine.benchmarks.case_grading_report import report_case_grading
from screamingface_engine.benchmarks.shared_grading.benchmark_aggregation import (
    CaseGradeOutcome,
    GradeCase,
    GradeRequest,
)
from screamingface_engine.benchmarks.shared_grading.payloads import CasePayload
from screamingface_engine.grading_call_scope import grading_call_scope
from screamingface_engine_inspect.judge_redraw import JudgeReplyUnparseable

#: Score string verdicts → floats, per inspect's own vocabulary: CORRECT / INCORRECT /
#: PARTIAL / NOANSWER. Closed on purpose (see the module invariant).
_INSPECT_LETTER_SCORE_VALUES: Mapping[str, float] = {"C": 1.0, "I": 0.0, "P": 0.5, "N": 0.0}

#: The scorer's model identity inside the fabricated TaskState. Display-only — no
#: model is resolved from it; the candidate already answered upstream.
_CANDIDATE_MODEL = "screamingface/candidate"


def inspect_grade_case(
    scorer: Scorer,
    *,
    extra_scorers: Sequence[Scorer] = (),
    named_scores: Sequence[str] = (),
    multiple_correct: bool = False,
    inverted_grade: bool = False,
    verdict_grades: Mapping[str, float] | None = None,
) -> GradeCase:
    """Wrap one inspect scorer — or several — as this benchmark's ``grade_case`` hook.

    Think of it as one marking room where every examiner the Task declared marks the SAME
    answer sheet, and the room writes every mark on the Case by the examiner's name.
    Stages, in execution order:

    Stage 1-2 — unpack our envelope, build their TaskState/Target once (the same forms go
                to every examiner).
    Stage 3 — each examiner marks, in declaration order, under the Case's grading scope;
                ANY raise fails the whole Case by name (``scorer_error``, or
                ``judge_reply_invalid`` when the judge never gave a verdict; naming the
                examiner), never a half-graded Case.
    Stage 4 — copy their marks back onto our form: one named value per examiner (or one
                per key of a dict-valued Score), the Headline Score first; ``score`` IS
                the headline. The Benchmark's word map and the Inverted Grade flip apply
                to the headline only (a Named Score carries no direction); inspect's own
                C/I/P/N letters map everywhere. A row that declares no names grades
                exactly as before (OME-1268).

    Args:
        scorer: the imported eval's scorer — any standalone async callable obeying
            inspect's ``(state, target) -> Score`` protocol. With ``named_scores`` set it
            is the HEADLINE scorer.
        extra_scorers: the Task's other scorers, in upstream order; each writes the
            Named Score at the matching position of ``named_scores`` (OME-1268).
        named_scores: the keys of the Case's Named Scores, headline first. Empty on a
            single-scorer Benchmark. With ONE scorer and several names, the scorer must
            return a dict carrying exactly those keys (SimpleQA, cyberseceval_4).
        multiple_correct: whether an MCQ benchmark admits multiple correct letters
            (inspect's ``parse_answers`` flag); single-answer benchmarks leave the default.
        inverted_grade: whether the eval's grade counts the behaviour we don't want
            (a should-refuse safety Benchmark: 1 = complied). The Case score is then
            1 − grade, so "higher is better" holds without anything downstream knowing.
        verdict_grades: the Benchmark's own verdict word → grade map, for a judge that
            answers in words (coconot); replaces the C/I/P/N letters, matched ignoring
            case. None keeps the letters.

    Returns:
        The async hook the shared grading code calls once per gradeable Case.

    Raises:
        ValueError: with several scorers, when a registered scorer's name is not the
            Named Score at its position (``("exact", "f1")`` over f1 and exact) — the
            pairing is by position, so a swap would publish the wrong number under the
            right label with no Case failing. Checked once, here, before any Case is
            graded; the registry conformance test checks every row the same way in CI.
    """

    _check_scorer_names((scorer, *extra_scorers), tuple(named_scores))
    names: tuple[str, ...] = tuple(named_scores)
    extras: tuple[Scorer, ...] = tuple(extra_scorers)
    if extras and len(names) != 1 + len(extras):
        raise ValueError(
            f"named_scores must name the headline scorer and each of the {len(extras)} "
            f"extra scorers, got {list(names)}"
        )

    # WHY casefold once here: the eval's own reducer compares lowercased words, and
    # coconot's grade pattern captures the judge's spelling as written.
    word_grades: Mapping[str, float] = (
        _INSPECT_LETTER_SCORE_VALUES
        if verdict_grades is None
        else {word.casefold(): grade for word, grade in verdict_grades.items()}
    )
    case_insensitive: bool = verdict_grades is not None

    async def grade(request: GradeRequest) -> CaseGradeOutcome:
        # Stage 1-2 — unpack our envelope, build their benchmark-office forms.
        state, target = _task_state(request, multiple_correct)
        # Stage 3 — their examiner marks the script, under the Case's grading
        # scope: a judge call made inside resolves to THIS Case for the run's
        # accounting join and for the connector's log tags (OME-1240).
        try:
            with grading_call_scope(request.case_id):
                score: Score | None = await scorer(state, target)
        except Exception as exc:  # noqa: BLE001 — WHY broad: the scorer is stranger
            # code from any of ~94 community evals; ANY raise must become this benchmark's
            # named failure, not an aborted aggregate for the other 49 Cases.
            return _failure(_raise_code(exc), f"{type(exc).__name__}: {exc}")
        # Stage 4 — copy their mark back onto our form.
        if not names:
            return _outcome(
                score, state.output.completion, inverted_grade, word_grades, case_insensitive
            )
        return await _named_outcome(
            request.case_id,
            score,
            state,
            target,
            names,
            extras,
            inverted_grade,
            word_grades,
            case_insensitive,
        )

    async def observed(request: GradeRequest) -> CaseGradeOutcome:
        report_case_grading(request.case_id, "started")
        try:
            outcome = await grade(request)
        except Exception:
            report_case_grading(request.case_id, "failed")
            raise
        report_case_grading(request.case_id, "failed" if outcome.failure_code else "completed")
        return outcome

    return observed


def _outcome(
    score: Score | None,
    completion: str,
    inverted_grade: bool,
    word_grades: Mapping[str, float],
    case_insensitive: bool,
) -> CaseGradeOutcome:
    """Stage 4 — one complete outcome per Score, unmappable values failing by name."""

    if score is None:
        # Their protocol admits "no score"; a Case must still fail by name.
        return _failure("invalid_score_value", "scorer returned no Score")
    grade: float | None = _score_as_float(score.value, word_grades, case_insensitive)
    case_score: float | None = None if grade is None else _case_score(grade, inverted_grade)
    if grade is None or case_score is None:
        return _failure("invalid_score_value", repr(score.value), score)
    return CaseGradeOutcome(
        score=case_score, metrics={}, checks=[_check(score, grade, case_score, completion)]
    )


def _check_scorer_names(scorers: Sequence[Scorer], names: tuple[str, ...]) -> None:
    """Refuse a multi-scorer room whose examiners are not seated under their own names.

    Only a REGISTERED scorer (one carrying inspect's registry info) can be compared; a
    plain callable stand-in has no name of its own and is left to the position it was
    given. The rows the Engine serves hold registered scorers only, and CI resolves every
    one of them (``check_named_scores_are_the_scorers``).
    """

    from inspect_ai._util.registry import is_registry_object, registry_unqualified_name

    if len(scorers) < 2:
        return
    for position, (examiner, name) in enumerate(zip(scorers, names, strict=True)):
        if not is_registry_object(examiner):
            continue
        actual: str = str(registry_unqualified_name(examiner))
        if actual != name:
            raise ValueError(
                f"named_scores[{position}] is {name!r} but the scorer at that position is "
                f"{actual!r}; names must be the scorers' registry names in order"
            )


async def _named_outcome(
    case_id: Any,
    headline: Score | None,
    state: TaskState,
    target: Target,
    names: tuple[str, ...],
    extras: Sequence[Scorer],
    inverted_grade: bool,
    word_grades: Mapping[str, float],
    case_insensitive: bool,
) -> CaseGradeOutcome:
    """Stage 3-4 for a row with Named Scores: the other examiners mark the same forms,
    then every mark is copied back by name — or, with one examiner, its dict is."""

    completion: str = state.output.completion
    if not extras:
        return _dict_outcome(
            headline, names, completion, inverted_grade, word_grades, case_insensitive
        )
    # Several examiners: each marks the same forms; one raise fails the whole Case.
    marks: list[Score | None] = [headline]
    for name, extra in zip(names[1:], extras, strict=True):
        try:
            with grading_call_scope(case_id):
                marks.append(await extra(state, target))
        except Exception as exc:  # noqa: BLE001 — stranger code; a raise is a named failure
            return _failure(_raise_code(exc), f"{name}: {type(exc).__name__}: {exc}")
    return _multi_outcome(marks, names, completion, inverted_grade, word_grades, case_insensitive)


def _multi_outcome(
    marks: Sequence[Score | None],
    names: tuple[str, ...],
    completion: str,
    inverted_grade: bool,
    word_grades: Mapping[str, float],
    case_insensitive: bool,
) -> CaseGradeOutcome:
    """Stage 4, several scorers — one named value and one Check per scorer, headline first.

    INVARIANT: the headline scorer alone speaks the Benchmark's word map and takes the
    Inverted Grade flip; every other scorer speaks inspect's letters and keeps its raw
    grade (a Named Score carries no direction). Any unmappable value fails the Case by the
    scorer's name — never a half-graded Case, so every column shares one denominator.
    """

    values: dict[str, float | None] = {}
    checks: list[dict[str, Any]] = []
    for index, (name, mark) in enumerate(zip(names, marks, strict=True)):
        if mark is None:
            return _failure("invalid_score_value", f"{name}: scorer returned no Score")
        headline: bool = index == 0
        grade: float | None = _score_as_float(
            mark.value,
            word_grades if headline else _INSPECT_LETTER_SCORE_VALUES,
            case_insensitive if headline else False,
        )
        value: float | None = (
            None if grade is None else (_case_score(grade, inverted_grade) if headline else grade)
        )
        if grade is None or value is None:
            return _failure("invalid_score_value", f"{name}: {mark.value!r}", mark)
        values[name] = value
        checks.append(_check(mark, grade, value, completion, check_id=name))
    headline_value: float | None = values[names[0]]
    assert headline_value is not None
    return CaseGradeOutcome(score=headline_value, metrics={}, checks=checks, scores=values)


def _dict_outcome(
    score: Score | None,
    names: tuple[str, ...],
    completion: str,
    inverted_grade: bool,
    word_grades: Mapping[str, float],
    case_insensitive: bool,
) -> CaseGradeOutcome:
    """Stage 4, one scorer returning a dict — each declared key becomes a named value.

    INVARIANT: the dict carries exactly the declared keys: an undeclared key is never
    dropped silently and a missing one is never defaulted — either fails the Case naming
    the key. The headline key alone takes the word map and the flip.
    """

    if score is None:
        return _failure("invalid_score_value", "scorer returned no Score")
    raw: Mapping[str, Any] = score.value if isinstance(score.value, Mapping) else {}
    problem: str | None = _dict_shape_problem(score.value, names)
    values: dict[str, float | None] = {}
    headline_grade: float = 0.0
    for index, name in enumerate(names):
        if problem is not None:
            break
        is_headline: bool = index == 0
        grade: float | None = _score_as_float(
            raw[name],
            word_grades if is_headline else _INSPECT_LETTER_SCORE_VALUES,
            case_insensitive if is_headline else False,
        )
        value: float | None = (
            None
            if grade is None
            else (_case_score(grade, inverted_grade) if is_headline else grade)
        )
        if grade is None or value is None:
            problem = f"{name}: {raw[name]!r}"
        elif is_headline:
            headline_grade = grade
        values[name] = value
    if problem is not None:
        return _failure("invalid_score_value", problem, score)
    headline_value: float | None = values[names[0]]
    assert headline_value is not None
    return CaseGradeOutcome(
        score=headline_value,
        metrics={},
        checks=[_check(score, headline_grade, headline_value, completion)],
        scores=values,
    )


def _dict_shape_problem(raw: object, names: tuple[str, ...]) -> str | None:
    """Why a dict-valued Score cannot fill the declared names, or ``None`` when it can."""

    if not isinstance(raw, Mapping):
        return f"declared named scores {list(names)} but the scorer returned {raw!r}"
    undeclared: list[str] = [str(key) for key in raw if key not in names]
    if undeclared:
        return f"undeclared score key {undeclared[0]!r}"
    missing: list[str] = [name for name in names if name not in raw]
    return f"missing declared score key {missing[0]!r}" if missing else None


def _case_score(grade: float, inverted_grade: bool) -> float | None:
    """Our Case score from the eval's grade — itself, or 1 − grade on a should-refuse
    Benchmark (OME-1400); ``None`` means no score exists (failed by name, never coerced).

    INVARIANT: the flip runs only on a real grade in 0..1. An unscored or unknown
    verdict never reaches here, and 1 − 5 is no score, so a broken judge can never be
    credited as a refusal.
    """

    if not inverted_grade:
        return grade
    return 1.0 - grade if 0.0 <= grade <= 1.0 else None


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
        # the Sample's metadata off the state; the prepare step delivers it in the Grading
        # Material record behind TaskReplayCasesSpec.keep_sample_metadata (OME-1240).
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
    """The prepared Sample metadata off the Grading Material record; absence stays an empty dict."""

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


def _score_as_float(
    value: object, word_grades: Mapping[str, float], case_insensitive: bool
) -> float | None:
    """The closed value → float map; ``None`` means unmappable (never coerced).

    ``word_grades`` is inspect's letters, or the Benchmark's own words (keys already
    casefolded, looked up ignoring case) — one map either way, never both.
    """

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
        mapped = word_grades.get(value.casefold() if case_insensitive else value)
    else:
        mapped = None
    return mapped


def _check(
    score: Score, grade: float, case_score: float, completion: str, *, check_id: str = "1"
) -> dict[str, Any]:
    """One check entry preserving the judge's own words as evidence.

    ``grade`` is the eval's own number and ``case_score`` ours — equal unless the
    Benchmark inverts its grade. The verdict (MET/PASS) follows the Case score; the
    evidence keeps the eval's grade, so an auditor reads the judge's call, not our flip.
    ``check_id`` is the scorer's Named Score key on a multi-scorer Benchmark (one Check
    per scorer); the single-scorer Check keeps its historical id ``"1"``.
    """

    reasoning: str | None = _judge_reasoning(score, completion)
    return {
        "type": "inspect_scorer",
        "id": check_id,
        "label": "inspect scorer verdict",
        "outcome": "MET" if case_score >= 1.0 else "UNMET",
        "evidence": [
            {
                "sequence": 1,
                "producer": {"type": "inspect_scorer", "id": "inspect/scorer"},
                "valid": True,
                "outcome": "PASS" if case_score >= 1.0 else "FAIL",
                # The judge's own words, verbatim — audit material for every Case.
                "raw_output": score.explanation or "",
                # The same words where the notebook report reads them (OME-1339).
                **({} if reasoning is None else {"explanation": reasoning}),
                "metadata": {
                    "value": score.value if isinstance(score.value, str) else grade,
                    "answer": score.answer,
                    **_json_metadata(score.metadata),
                },
                "accounting": None,
            }
        ],
        "metadata": {"answer": score.answer},
    }


def _judge_reasoning(score: Score, completion: str) -> str | None:
    """The scorer's explanation when it actually explains something, else ``None``.

    WHY: inspect's match, choice, pattern and math scorers put the candidate's own
    completion in ``explanation`` — shown under the verdict it would repeat the answer
    as if it were the judge's reasoning (owner decision, 2026-09-28). One comparison
    against the graded completion, so still zero per-scorer branches. ``None`` (not "")
    keeps the wire field absent, so an echoing scorer's evidence serializes as before.
    A scorer's OWN message is reasoning and does show — ``pattern()``'s "Scoring
    pattern not matched in output: …" on boolq, the AIME scorer's "Model produced
    empty completion" — because it says why a Case failed.
    """

    explanation: str | None = score.explanation
    if not explanation or explanation == completion:
        return None
    return explanation


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


def _raise_code(exc: Exception) -> str:
    """Name who is to blame for a scorer's raise: the judge, or the scorer code."""

    # WHY judge_reply_invalid: the redraw budget ran out because the JUDGE never sent a
    # verdict; ``scorer_error`` would send the reader hunting for a bug in our code.
    return "judge_reply_invalid" if isinstance(exc, JudgeReplyUnparseable) else "scorer_error"


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
