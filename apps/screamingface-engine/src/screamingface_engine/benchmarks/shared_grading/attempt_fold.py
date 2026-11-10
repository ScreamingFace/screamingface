"""Fold a Case's N graded Attempts into its one Case Result, by one of two rules.

Think of it as an exam that accepts several answer sheets per question. Each sheet was already
marked on its own by the Benchmark's own Grading; this module only decides what the question
earns overall, and which sheet a reader is shown. The Benchmark names the rule:

    ``any``   a Check is met if any Attempt met it (OME-1458; ARC-AGI-2's rule)
    ``mean``  the Case scores the share of its tries at full marks, which is what inspect's
              ``pass_at(1)`` computes over N epochs: 1 - C(n-c, 1)/C(n, 1) = c/n
              (``docs/spec/2026-11-09-attempts-mean-fold.md``; ZeroBench's pass@1). A try is
              a graded Attempt or an empty answer (below); an Attempt the gateway or a timeout
              failed never reached the Candidate and is left out, as inspect leaves out an
              errored epoch

FEATURE (OME-1458): ARC-AGI-2 gives two Attempts per test grid, and its own scorer credits each
grid separately. A task with grids A and B where Attempt 1 got A and Attempt 2 got B scores 1.0
there, so the fold is per Check, not "pick the best sheet" (which would score 0.5).

The stages, in execution order:

    Stage 1  keep every Attempt as a `CaseAttempt`, its cost records with it; count the empty
             answers: a failed Attempt whose leading failure is one of `EMPTY_ANSWER_CODES`
             (a textless refusal, a reasoning-only reply, a token budget spent before any
             text). inspect's scorer grades that empty completion 0, so under ``mean`` it is
             a wrong try; under ``any`` it adds nothing either way
    Stage 2  no Attempt was graded → the Case is Attempt 1's failure, with every Attempt kept
             (five silent refusals score the Case 0 under both rules, as inspect does)
    Stage 3  (``any`` only) every graded Check must be met or missed (0 or 1) → else the Case
             fails as `attempt_grade_not_pass_fail`, never a guessed fold. Under ``mean`` a
             partial mark is a defined number: not full marks, so not right (inspect's rule)
    Stage 4  ``any``: per Check, met if ANY graded Attempt met it; Case score = met Checks /
             Checks. ``mean``: per Check, the share of tries that met it; Case
             score = Attempts whose own score is 1.0 / tries (graded + empty answers)
    Stage 5  shown answer = the first graded Attempt with the highest own Case score; the Case
             Result is that Attempt's, with the folded grade and the Attempts list

Worked example, ``any`` — two Checks (grid A, grid B), two Attempts:

    Attempt 1: A MET, B UNMET → own score 0.5
    Attempt 2: A UNMET, B MET → own score 0.5
    fold: A MET (by 1), B MET (by 2) → Case score 2 / 2 = 1.0; shown answer: Attempt 1

Worked example, ``mean`` — one Check, five Attempts marked 1, 0, 1, 0, 0:

    fold: 2 of 5 Attempts at full marks → Case score 2 / 5 = 0.4 (any-of-5 would say 1.0);
    the Check's score is 0.4 too, met by Attempts [1, 3]; shown answer: Attempt 1

Worked example, ``mean`` — one right Attempt and four textless provider refusals:

    fold: 1 right of 5 tries → 1 / 5 = 0.2, as inspect scores the four empty completions 0
    (any-of-5 says 1.0). With a gateway failure in place of one refusal: 1 / 4 = 0.25, the
    failed call never reached the Candidate, so it is no try at all

INVARIANT: the fold reads only Case Results the shared marking room already built, so every
Benchmark's Grading, failure ladder and wording stay exactly its own.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from screamingface_engine.benchmarks.contract import (
    CaseAttempt,
    CaseGrade,
    CaseResult,
    Check,
    Failure,
)

ATTEMPT_GRADE_NOT_PASS_FAIL = "attempt_grade_not_pass_fail"
# WHY (D15, second pass): these are the Candidate's own empty answers — the request reached
# the model and it gave nothing a scorer can read. inspect never errors on them: the scorer
# sees an empty completion and grades it 0, so under ``mean`` each one is a wrong try. Every
# other declared code (the gateway family, timeouts, the grading itself) is a call inspect
# would have errored and left out of ``pass_at(1)``, so it leaves the mean over the rest.
# INVARIANT: a Case score of 1.0 means every try was right, never "the one try that got
# through"; 1 right + 4 silent refusals is 0.2, as inspect_evals and the authors count it.
# AIDEV-NOTE: today only a textless refusal reaches this fold as a failed Attempt (the gateway
# reports it as data). A token cap or a reasoning-only reply is raised as a url4 error and
# fails the whole Case before any Attempt row exists (OME-1458's accepted limitation, in
# `protocol.py`); the two codes are listed here for the unit that collects a failed call per
# Attempt, after which they arrive as failed Attempts and count as wrong tries.
EMPTY_ANSWER_CODES: frozenset[str] = frozenset(
    {"provider_refusal", "model_empty_content", "model_token_cap"}
)
MET_BY_ATTEMPTS_KEY = "met_by_attempts"
_SCORE_DIGITS = 4

#: The fold rules a Benchmark may declare (module docstring). The plugin maps a row's
#: ``epoch_reducer`` onto one of these; this core module never sees inspect's names.
AttemptFold = Literal["any", "mean"]
ANY_ATTEMPT_FOLD: AttemptFold = "any"
MEAN_ATTEMPT_FOLD: AttemptFold = "mean"


def fold_case_attempts(
    results: Sequence[CaseResult], fold: AttemptFold = ANY_ATTEMPT_FOLD
) -> CaseResult:
    """The one Case Result for a Case asked ``len(results)`` times.

    Args:
        results: one Case Result per Attempt, in Attempt order (Attempt 1 first), each built by
            the marking room exactly as a one-Attempt Case would be.
        fold: the Benchmark's rule, ``any`` (the default, so every caller that never named one
            is unchanged) or ``mean`` (module docstring).

    Returns:
        The Case's Case Result: the shown Attempt's answer, the per-Check folded grade, and an
        ``attempts`` list with every Attempt's own answer, grade, failures and cost records.

    Raises:
        ValueError: fewer than two Attempts, Attempts graded on different Checks, or a
            Benchmark with Named Scores (they have no per-Check meaning to fold).
    """

    if len(results) < 2:
        raise ValueError("a Case with Attempts has at least two")
    # Stage 1 — every Attempt as the reader will see it, its cost records with it.
    attempts: list[CaseAttempt] = [
        _case_attempt(number, result) for number, result in enumerate(results, start=1)
    ]
    graded: list[tuple[int, CaseResult]] = [
        (number, result)
        for number, result in enumerate(results, start=1)
        if result.status == "scored"
    ]
    empty_answers: int = sum(1 for result in results if _is_empty_answer(result))
    # Stage 2 — nothing was graded: the Case fails as Attempt 1 did.
    if not graded:
        return _validated(results[0], {"operations": None, "attempts": attempts})
    # Stage 3 — any-match only means something for a Check that was met or missed; the mean
    # reads a partial mark as "not full marks", as inspect's pass_at(1, value=1.0) does.
    unfoldable: tuple[int, str] | None = _first_partial_check(graded)
    if fold == ANY_ATTEMPT_FOLD and unfoldable is not None:
        return _not_pass_fail(results[0], attempts, *unfoldable)
    # Stage 4 — per Check and per Case, by the rule.
    if fold == ANY_ATTEMPT_FOLD:
        checks: list[Check] = _folded_checks(graded)
        met: int = sum(1 for check in checks if check.outcome == "MET")
        score: float = met / len(checks)
    else:
        # INVARIANT: the same count inspect's pass_at(1) makes over the Scores its scorer would
        # file: Attempts at full marks over the tries — graded Attempts plus empty answers,
        # which inspect grades 0 (Stage 1). The tally replays that reducer and checks it agrees.
        tries: int = len(graded) + empty_answers
        checks = _averaged_checks(graded, tries)
        full_marks: int = sum(1 for _, result in graded if _own_score(result) == 1.0)
        score = full_marks / tries
    # Stage 5 — show the first Attempt that earned the most on its own.
    shown: CaseResult = _shown(graded)
    assert shown.grade is not None
    grade = CaseGrade(
        method=shown.grade.method,
        score=round(score, _SCORE_DIGITS),
        metrics=dict(shown.grade.metrics),
        checks=checks,
    )
    return _validated(shown, {"grade": grade, "operations": None, "attempts": attempts})


def _validated(base: CaseResult, update: dict[str, object]) -> CaseResult:
    """``base`` with ``update`` applied, re-checked against every Case Result rule.

    WHY re-validate: ``model_copy`` skips validators, and the folded Case must obey the same
    scored-or-failed rules, plus the Attempts rules, as any Case on the wire.
    WHY by_alias: a Fusion's combine evidence only accepts its wire key ``schema``, never
    the field name ``schema_id``, so the round trip must use wire names.
    """

    return CaseResult.model_validate(base.model_copy(update=update).model_dump(by_alias=True))


def _case_attempt(number: int, result: CaseResult) -> CaseAttempt:
    """One Attempt's own answer, grade, failures and cost records, numbered from 1."""

    return CaseAttempt(
        attempt=number,
        status=result.status,
        output=result.output,
        finish_reason=result.finish_reason,
        refusal=result.refusal,
        grade=result.grade,
        failures=list(result.failures),
        operations=result.operations,
    )


def _is_empty_answer(result: CaseResult) -> bool:
    """True for a failed Attempt the Candidate answered with nothing a scorer can read."""

    return (
        result.status == "failed"
        and bool(result.failures)
        and result.failures[0].code in EMPTY_ANSWER_CODES
    )


def _check_met(check: Check) -> bool | None:
    """True when met, False when missed, None when the Check is neither (a partial grade)."""

    if check.score is not None:
        return {1.0: True, 0.0: False}.get(check.score)
    if check.outcome is not None:
        return check.outcome == "MET"
    return None


def _first_partial_check(graded: Sequence[tuple[int, CaseResult]]) -> tuple[int, str] | None:
    """The first (Attempt, Check id) graded neither 0 nor 1, or a Case graded on no Check."""

    for number, result in graded:
        assert result.grade is not None
        if result.grade.scores:
            raise ValueError("a Benchmark with Named Scores cannot fold Attempts per Check")
        if not result.grade.checks:
            return number, "(none)"
        for check in result.grade.checks:
            if _check_met(check) is None:
                return number, check.id
    return None


def _aligned_checks(
    graded: Sequence[tuple[int, CaseResult]],
) -> list[tuple[str, list[tuple[int, Check]], list[int], Check]]:
    """Each Check across the graded Attempts: its id, every Attempt's copy, the Attempts that
    met it, and the template to fold from.

    WHY the first Attempt that met it as the template: that is the answer that earned the
    point, and copying every Attempt's evidence would bill one judge call twice.
    """

    ids: list[list[str]] = [
        [check.id for check in result.grade.checks] for _, result in graded if result.grade
    ]
    if any(item != ids[0] for item in ids):
        raise ValueError(f"Attempts of one Case were graded on different Checks: {ids}")
    aligned: list[tuple[str, list[tuple[int, Check]], list[int], Check]] = []
    for position, check_id in enumerate(ids[0]):
        by_attempt: list[tuple[int, Check]] = [
            (number, result.grade.checks[position]) for number, result in graded if result.grade
        ]
        met_by: list[int] = [number for number, check in by_attempt if _check_met(check)]
        template: Check = next(
            (check for number, check in by_attempt if number in met_by), by_attempt[0][1]
        )
        aligned.append((check_id, by_attempt, met_by, template))
    return aligned


def _folded_checks(graded: Sequence[tuple[int, CaseResult]]) -> list[Check]:
    """Each Check met if any graded Attempt met it, recording which Attempts did."""

    return [
        template.model_copy(
            update={
                "outcome": "MET" if met_by else "UNMET",
                "score": None if template.score is None else (1.0 if met_by else 0.0),
                "metadata": {**template.metadata, MET_BY_ATTEMPTS_KEY: met_by},
                "id": check_id,
            }
        )
        for check_id, _, met_by, template in _aligned_checks(graded)
    ]


def _averaged_checks(graded: Sequence[tuple[int, CaseResult]], tries: int) -> list[Check]:
    """Each Check carrying the share of the ``tries`` that met it (``mean`` rule): MET when
    all did, UNMET when none did, no outcome otherwise, and which Attempts met it. An empty
    answer is a try no Check was graded on, so it counts against every Check."""

    averaged: list[Check] = []
    for check_id, _by_attempt, met_by, template in _aligned_checks(graded):
        share: float = round(len(met_by) / tries, _SCORE_DIGITS)
        averaged.append(
            template.model_copy(
                update={
                    "outcome": {1.0: "MET", 0.0: "UNMET"}.get(share),
                    "score": share,
                    "metadata": {**template.metadata, MET_BY_ATTEMPTS_KEY: met_by},
                    "id": check_id,
                }
            )
        )
    return averaged


def _own_score(result: CaseResult) -> float:
    """A graded Attempt's own Case score, 0.0 when its grade carries none."""

    assert result.grade is not None
    return result.grade.score or 0.0


def _shown(graded: Sequence[tuple[int, CaseResult]]) -> CaseResult:
    """The first graded Attempt with the highest own Case score — the answer a reader sees."""

    best: float = max(result.grade.score or 0.0 for _, result in graded if result.grade)
    return next(
        result
        for _, result in graded
        if result.grade is not None and (result.grade.score or 0.0) == best
    )


def _not_pass_fail(
    first: CaseResult, attempts: list[CaseAttempt], attempt: int, check_id: str
) -> CaseResult:
    """The Case failed by name: an Attempt's Check was graded neither met nor missed."""

    failure = Failure(
        stage="grading",
        code=ATTEMPT_GRADE_NOT_PASS_FAIL,
        message=(
            f"Attempt {attempt} graded Check {check_id!r} neither 0 nor 1, so whether any "
            "Attempt met it has no meaning"
        ),
        retryable=False,
        case_id=first.case_id,
        metadata={"attempt": attempt, "check_id": check_id},
    )
    return _validated(
        first,
        {
            "status": "failed",
            "grade": None,
            "refusal": None,
            "failures": [failure],
            "operations": None,
            "attempts": attempts,
        },
    )


__all__ = [
    "ANY_ATTEMPT_FOLD",
    "ATTEMPT_GRADE_NOT_PASS_FAIL",
    "EMPTY_ANSWER_CODES",
    "MEAN_ATTEMPT_FOLD",
    "MET_BY_ATTEMPTS_KEY",
    "AttemptFold",
    "fold_case_attempts",
]
