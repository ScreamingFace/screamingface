"""The five ordered failure checks every rubric board grades one Case through.

Think of a Case as one exam paper landing on the marker's desk: before any mark is
written, the marker checks — is the answer key present, did the paper arrive at all, is
it a note saying "the student's desk caught fire", was every question actually judged,
is the key itself usable? Only a paper that survives every check gets a score; every
other paper is retained with a named reason, never quietly dropped.

FEATURE: one grading spine per benchmark (OME-1024); this module is the first extraction
(OME-1039) — the checks gdpval and healthbench previously duplicated verbatim.

The checks run most-broken first; the first one that trips becomes a Failure whose
``code`` makes a ``None`` exam score traceable per Case:

    no rubric asset      → "missing_rubric_asset"
    no row for this Case → "missing_case_row" (orphan collected errors attached)
    row is an error row  → "case_error" (error attached in metadata)
    verdicts incomplete  → "incomplete_verdicts" (judged/expected counts)
    complete, no + item  → "no_positive_points" (a baked-asset defect —
                           prepare guarantees one positive item per Case)
    everything valid     → grade with the Case score, no failures

INVARIANT: every unusable state becomes a VISIBLE failed result — a judge outage, a
broken asset and a genuinely bad answer must stay distinguishable in the report.
INVARIANT: failure codes and message texts stay byte-identical per board — the message
table is board-supplied (gdpval says "criterion" where healthbench says "rubric item"),
so this extraction moves logic, never wording. The e2e goldens pin every failed case's
code, so a reclassification cannot slip through.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from screamingface_engine.benchmarks.aggregation import (
    SelectedCase,
    failed_case_result,
    public_error,
    refused_case_result,
    scored_case_result,
)
from screamingface_engine.benchmarks.contract import CaseResult

#: ``(case_result, score_or_None, judged_count, met_count, invalid_reply_count)``
type CaseOutcome = tuple[CaseResult, float | None, int, int, int]


@dataclass(frozen=True, slots=True)
class CaseGrader:
    """One board's case grader — the shared grading steps bound to the board's own hooks.

    Each board constructs one module-level instance. The hooks are the pieces a rubric
    board still owns after this extraction (later spine tickets move them in too):

    ``failure_messages`` — failure code → the public message shown for it. The wording
    is part of the board's published failure output, so the grader never invents text.
    ``case_score`` — the board's official per-Case scoring formula; returns ``None``
    for a Case that was fully judged but has nothing worth points (reported as the
    ``no_positive_points`` failure).
    ``verdicts`` — reads ``(verdicts_by_position, invalid_reply_count)`` off one row.
    ``checks`` — turns one row's judge evidence into the SDK's check rows.
    ``candidate_fields`` — pulls status/output/refusal/finish_reason/metadata/execution
    off the hoisted Case record.
    """

    failure_messages: Mapping[str, str]
    case_score: Callable[[list[int], Mapping[int, bool]], float | None]
    verdicts: Callable[[Mapping[str, Any]], tuple[dict[int, bool], int]]
    checks: Callable[[Mapping[str, Any], list[int]], list[dict[str, Any]]]
    candidate_fields: Callable[[Mapping[str, Any] | None], dict[str, Any]]

    def case_result(
        self,
        selected_case: SelectedCase,
        row: Mapping[str, Any] | None,
        points: list[int] | None,
        orphan_errors: list[dict[str, Any]] | None = None,
    ) -> CaseOutcome:
        """Score one selected Case; every unusable state becomes a VISIBLE failed result."""

        terminal = self._terminal_failure_outcome(selected_case, row, points, orphan_errors)
        if terminal is not None:
            return terminal
        assert row is not None and points is not None
        verdicts, invalid = self.verdicts(row)
        checks = self.checks(row, points)
        complete = len(verdicts) == len(points) and not invalid
        score = self.case_score(points, verdicts) if complete else None
        if score is None:
            failure = self._failure(
                int(selected_case.case_id),
                "grading",
                # WHY: a complete-but-unscorable Case means the baked asset lost its
                # positive-points item (prepare guarantees one) — name it distinctly.
                "no_positive_points" if complete else "incomplete_verdicts",
                judged=len(verdicts),
                expected=len(points),
            )
            return (
                self._failed_result(selected_case, row, checks, failure),
                None,
                len(verdicts),
                sum(verdicts.values()),
                invalid,
            )
        return self._scored_outcome(selected_case, row, points, verdicts, checks, score, invalid)

    def _terminal_failure_outcome(
        self,
        selected_case: SelectedCase,
        row: Mapping[str, Any] | None,
        points: list[int] | None,
        orphan_errors: list[dict[str, Any]] | None,
    ) -> CaseOutcome | None:
        case_id = int(selected_case.case_id)
        outcome: CaseOutcome | None
        if points is None:
            failure = self._failure(case_id, "grading", "missing_rubric_asset")
            outcome = self._failed_result(selected_case, row, [], failure), None, 0, 0, 0
        elif row is None:
            # WHY the collected_errors attachment: an on_error=collect row loses its
            # Case identity, so a mid-chain error surfaces HERE as a missing row —
            # without the orphan payloads the report would name the symptom but hide
            # the cause (exactly what happened in the first live smoke run).
            outcome = self._missing_row_outcome(selected_case, orphan_errors)
        elif "error" in row:
            failure = self._failure(case_id, "candidate", "case_error", error=row["error"])
            outcome = self._failed_result(selected_case, row, [], failure), None, 0, 0, 0
        else:
            outcome = None
        return outcome

    def _scored_outcome(
        self,
        selected_case: SelectedCase,
        row: Mapping[str, Any],
        points: list[int],
        verdicts: Mapping[int, bool],
        checks: list[dict[str, Any]],
        score: float,
        invalid: int,
    ) -> tuple[CaseResult, float, int, int, int]:
        fields = self.candidate_fields(row)
        grade = {
            "method": "rubric",
            "score": round(score, 4),
            "metrics": {
                "judged": len(verdicts),
                "expected": len(points),
                "invalid_replies": invalid,
            },
            "checks": checks,
        }
        common = {
            "selected_case": selected_case,
            "finish_reason": fields["finish_reason"],
            "grade": grade,
            "metadata": fields["metadata"],
            "execution": fields["execution"],
            "operations": fields.get("operations"),
        }
        if fields["status"] == "refused":
            scored = refused_case_result(refusal=fields["refusal"], **common)
        else:
            scored = scored_case_result(output=fields["output"], **common)
        return scored, score, len(verdicts), sum(verdicts.values()), invalid

    def _missing_row_outcome(
        self,
        selected_case: SelectedCase,
        orphan_errors: list[dict[str, Any]] | None,
    ) -> tuple[CaseResult, None, int, int, int]:
        failure = self._failure(
            int(selected_case.case_id),
            "candidate",
            "missing_case_row",
            **({"collected_errors": orphan_errors[:3]} if orphan_errors else {}),
        )
        return self._failed_result(selected_case, None, [], failure), None, 0, 0, 0

    def _failed_result(
        self,
        selected_case: SelectedCase,
        row: Mapping[str, Any] | None,
        checks: list[dict[str, Any]],
        failure: dict[str, Any],
    ) -> CaseResult:
        fields = self.candidate_fields(row)
        # WHY a grade with score None rather than no grade: the judge evidence for a
        # partially judged Case is audit material, and the grade's checks list is the
        # contract's slot for it.
        grade = {"method": "rubric", "score": None, "metrics": {}, "checks": checks}
        common = {
            "selected_case": selected_case,
            "finish_reason": fields["finish_reason"],
            "grade": grade,
            "failures": [failure],
            "metadata": fields["metadata"],
            "execution": fields["execution"],
            "operations": fields.get("operations"),
        }
        if fields["status"] == "refused":
            return refused_case_result(refusal=fields["refusal"], **common)
        return failed_case_result(output=fields["output"], **common)

    def _failure(self, case_id: int, stage: str, code: str, **metadata: Any) -> dict[str, Any]:
        public_metadata = _failure_metadata(metadata)
        message = self.failure_messages[code]
        retryable: bool | None = None
        if source_error := _source_error(metadata):
            diagnostic = public_error(source_error, default_code=code, default_message=message)
            message = diagnostic.message
            retryable = diagnostic.retryable
            public_metadata["source_error"] = {
                "kind": diagnostic.kind,
                "code": diagnostic.code,
                "message": diagnostic.message,
                "retryable": diagnostic.retryable,
            }
        return {
            "stage": stage,
            "code": code,
            "message": message,
            "retryable": retryable,
            "case_id": case_id,
            "metadata": public_metadata,
        }


def _failure_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in metadata.items()
        if key in {"judged", "expected", "row_index"}
        and isinstance(value, int)
        and not isinstance(value, bool)
    }


def _source_error(metadata: Mapping[str, Any]) -> Mapping[str, Any] | None:
    error = metadata.get("error")
    if isinstance(error, Mapping):
        return error
    collected = metadata.get("collected_errors")
    rows = collected[:3] if isinstance(collected, list) else []
    return next(
        (
            source
            for row in rows
            if isinstance(row, Mapping) and isinstance((source := row.get("error")), Mapping)
        ),
        None,
    )


__all__ = ["CaseGrader", "CaseOutcome"]
