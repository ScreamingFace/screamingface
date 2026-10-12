"""Fold a Case's N graded Attempts into its one Case Result: a Check is met if any Attempt met it.

Think of it as an exam that accepts two answer sheets per question. Each sheet was already
marked on its own by the Benchmark's own Grading; this module only decides what the question
earns overall, and which sheet a reader is shown.

FEATURE (OME-1458): ARC-AGI-2 gives two Attempts per test grid, and its own scorer credits each
grid separately. A task with grids A and B where Attempt 1 got A and Attempt 2 got B scores 1.0
there, so the fold is per Check, not "pick the best sheet" (which would score 0.5).

The stages, in execution order:

    Stage 1  keep every Attempt as a `CaseAttempt`, its cost records with it
    Stage 2  no Attempt was graded → the Case is Attempt 1's failure, with every Attempt kept
    Stage 3  every graded Check must be met or missed (0 or 1) → else the Case fails as
             `attempt_grade_not_pass_fail`, never a guessed fold
    Stage 4  per Check, met if ANY graded Attempt met it; Case score = met Checks / Checks
    Stage 5  shown answer = the first graded Attempt with the highest own Case score; the Case
             Result is that Attempt's, with the folded grade and the Attempts list

Worked example — two Checks (grid A, grid B), two Attempts:

    Attempt 1: A MET, B UNMET → own score 0.5
    Attempt 2: A UNMET, B MET → own score 0.5
    fold: A MET (by 1), B MET (by 2) → Case score 2 / 2 = 1.0; shown answer: Attempt 1

INVARIANT: the fold reads only Case Results the shared marking room already built, so every
Benchmark's Grading, failure ladder and wording stay exactly its own.
"""

from __future__ import annotations

from collections.abc import Sequence

from screamingface_engine.benchmarks.contract import (
    CaseAttempt,
    CaseGrade,
    CaseResult,
    Check,
    Failure,
)

ATTEMPT_GRADE_NOT_PASS_FAIL = "attempt_grade_not_pass_fail"
MET_BY_ATTEMPTS_KEY = "met_by_attempts"
_SCORE_DIGITS = 4


def fold_case_attempts(results: Sequence[CaseResult]) -> CaseResult:
    """The one Case Result for a Case asked ``len(results)`` times.

    Args:
        results: one Case Result per Attempt, in Attempt order (Attempt 1 first), each built by
            the marking room exactly as a one-Attempt Case would be.

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
    # Stage 2 — nothing was graded: the Case fails as Attempt 1 did.
    if not graded:
        return _validated(results[0], {"operations": None, "attempts": attempts})
    # Stage 3 — any-match only means something for a Check that was met or missed.
    unfoldable: tuple[int, str] | None = _first_partial_check(graded)
    if unfoldable is not None:
        return _not_pass_fail(results[0], attempts, *unfoldable)
    # Stage 4 — per Check, met if any graded Attempt met it.
    checks: list[Check] = _folded_checks(graded)
    met: int = sum(1 for check in checks if check.outcome == "MET")
    # Stage 5 — show the first Attempt that earned the most on its own.
    shown: CaseResult = _shown(graded)
    assert shown.grade is not None
    grade = CaseGrade(
        method=shown.grade.method,
        score=round(met / len(checks), _SCORE_DIGITS),
        metrics=dict(shown.grade.metrics),
        checks=checks,
    )
    return _validated(shown, {"grade": grade, "operations": None, "attempts": attempts})


def _validated(base: CaseResult, update: dict[str, object]) -> CaseResult:
    """``base`` with ``update`` applied, re-checked against every Case Result rule.

    WHY re-validate: ``model_copy`` skips validators, and the folded Case must obey the same
    scored-or-failed rules, plus the Attempts rules, as any Case on the wire.
    """

    return CaseResult.model_validate(base.model_copy(update=update).model_dump())


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


def _folded_checks(graded: Sequence[tuple[int, CaseResult]]) -> list[Check]:
    """Each Check met if any graded Attempt met it, recording which Attempts did."""

    ids: list[list[str]] = [
        [check.id for check in result.grade.checks] for _, result in graded if result.grade
    ]
    if any(item != ids[0] for item in ids):
        raise ValueError(f"Attempts of one Case were graded on different Checks: {ids}")
    folded: list[Check] = []
    for position, check_id in enumerate(ids[0]):
        by_attempt: list[tuple[int, Check]] = [
            (number, result.grade.checks[position]) for number, result in graded if result.grade
        ]
        met_by: list[int] = [number for number, check in by_attempt if _check_met(check)]
        # WHY the evidence of the first Attempt that met it: that is the answer that earned
        # the point, and copying every Attempt's evidence would bill one judge call twice.
        template: Check = next(
            (check for number, check in by_attempt if number in met_by), by_attempt[0][1]
        )
        folded.append(
            template.model_copy(
                update={
                    "outcome": "MET" if met_by else "UNMET",
                    "score": None if template.score is None else (1.0 if met_by else 0.0),
                    "metadata": {**template.metadata, MET_BY_ATTEMPTS_KEY: met_by},
                    "id": check_id,
                }
            )
        )
    return folded


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


__all__ = ["ATTEMPT_GRADE_NOT_PASS_FAIL", "MET_BY_ATTEMPTS_KEY", "fold_case_attempts"]
