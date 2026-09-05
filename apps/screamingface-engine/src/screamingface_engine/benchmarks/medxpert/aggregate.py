"""Reduce every selected MedXpertQA Case into one Candidate result.

INVARIANT — an unparseable answer scores 0.0; it is NOT excluded. This is the official harness's
empty-prediction verdict, and it is what keeps two systems comparable: the prior experimental run
scored a model answering 77% of rows over that smaller, easier denominator, so its accuracy was
not the same measurement as a model that answered all of them.

AIDEV-NOTE: that is deliberately NOT the board's `failure_policy`. That axis governs a Case which
never got a valid grade — an infrastructure failure — and those go to the shared
`finalize_candidate_result`, which scores the gradeable subset and publishes coverage. Hence the
board declares `coverage_declare`. An empty answer DOES get a grade here, of 0.0.

INVARIANT — a failure to COMMIT and a failure to RUN are different facts. A model that replies
without a valid letter has answered badly (score 0.0, `answered: false`). A Case whose invocation
errored has not been measured at all (score `None`, a visible failed Case). Collapsing the two
would let an outage look like weakness, or weakness look like an outage.

AIDEV-NOTE: this board deliberately does NOT use `spine.CaseGrader`. That grader is rubric-shaped
— it takes `points: list[int]` with verdicts-by-position, and emits hardcoded failure codes
(`missing_rubric_asset`, `incomplete_verdicts`, `no_positive_points`) that a board can reword but
not rename. An MCQ board publishing `code: "missing_rubric_asset"` would contradict its own
message. `spine.RowReader` IS used — row indexing is genuinely board-independent. If a second
non-rubric board arrives, generalising `CaseGrader` becomes a spine ticket with two data points.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from screamingface_engine.benchmarks.aggregation import (
    CandidateScore,
    SelectedCase,
    failed_case_result,
    finalize_candidate_result,
    grading_failure_case_result,
    public_error,
    refused_case_result,
    scored_case_result,
)
from screamingface_engine.benchmarks.contract import CaseResult
from screamingface_engine.benchmarks.medxpert.case_evaluation import decode_case_evaluation
from screamingface_engine.benchmarks.spine.rows import RowReader

_FAILURE_MESSAGES = {
    "missing_answer_asset": "the baked answer record for this Case is missing or invalid",
    "missing_case_row": "no evaluation row for this Case reached the aggregate",
    "case_error": "the Case pipeline collected an error instead of an evaluation",
}


class AggregateError(ValueError):
    """The reducer's input is unusable — raised before any scoring."""


_ROWS = RowReader(
    benchmark_label="MedXpertQA",
    error_type=AggregateError,
    decode_case_evaluation=decode_case_evaluation,
)


def load_answer(root: Path, case_id: int) -> dict[str, Any] | None:
    """Read one Case's private answer record; ``None`` when the asset is unusable."""

    try:
        decoded = json.loads((root / "answers" / f"{case_id}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(decoded, Mapping):
        return None
    label = decoded.get("label")
    return dict(decoded) if isinstance(label, str) and label else None


def selected_cases(root: Path, case_ids: tuple[int, ...]) -> list[SelectedCase]:
    try:
        decoded = json.loads((root / "cases.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AggregateError(f"MedXpertQA cases are unavailable: {exc}") from None
    if not isinstance(decoded, list):
        raise AggregateError("MedXpertQA cases must be a JSON array")
    by_id = {
        row.get("id"): row
        for row in decoded
        if isinstance(row, Mapping) and isinstance(row.get("id"), int)
    }
    chosen: list[SelectedCase] = []
    for case_id in case_ids:
        row = by_id.get(case_id)
        value = row.get("input") if isinstance(row, Mapping) else None
        if not isinstance(value, str) or not value.strip():
            raise AggregateError(f"MedXpertQA Case {case_id} has no public input")
        chosen.append(SelectedCase(case_id=case_id, input=value, metadata={}))
    return chosen


def aggregate(
    raw_rows: str,
    root: Path,
    *,
    benchmark_id: str,
    benchmark_revision: str,
    case_ids: tuple[int, ...],
) -> dict[str, Any]:
    """Score every selected Case, then the exam as plain accuracy."""

    chosen = selected_cases(root, case_ids)
    index = _ROWS.index(raw_rows, case_ids)
    results: list[CaseResult] = []
    for selected in chosen:
        case_id = int(selected.case_id)
        failure = index.grading_failures.get(case_id)
        if failure is not None:
            assert failure.error is not None
            results.append(
                grading_failure_case_result(
                    selected_case=selected,
                    candidate=failure.candidate,
                    error=failure.error,
                    method="exact_match",
                    default_code="medxpert_grading_failed",
                    default_message="the MedXpertQA checker could not grade this Case",
                )
            )
            continue
        results.append(
            _case_result(
                selected,
                index.rows.get(case_id),
                load_answer(root, case_id),
                index.collected_errors.get(case_id),
            )
        )
    return finalize_candidate_result(
        benchmark_id=benchmark_id,
        benchmark_revision=benchmark_revision,
        selected_cases=chosen,
        cases=results,
        scorer=_accuracy,
    ).as_payload()


def _case_result(
    selected: SelectedCase,
    row: Mapping[str, Any] | None,
    answer: Mapping[str, Any] | None,
    orphan_errors: list[dict[str, Any]] | None,
) -> CaseResult:
    """Score one Case, or turn an unusable state into a visible failure.

    Most-broken first: no answer key, then no row, then an error row. Only after all three does
    the Candidate's own reply decide the score.
    """

    failure = _terminal_failure(selected, row, answer, orphan_errors)
    if failure is not None:
        return _failed(selected, None if row is None else row, failure)
    assert row is not None and answer is not None
    return _scored(selected, row, str(answer["label"]))


def _terminal_failure(
    selected: SelectedCase,
    row: Mapping[str, Any] | None,
    answer: Mapping[str, Any] | None,
    orphan_errors: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    """The first unusable state, most-broken first — or ``None`` when the Case can be scored."""

    case_id = int(selected.case_id)
    if answer is None:
        return _failure(case_id, "grading", "missing_answer_asset")
    if row is None:
        # WHY attach collected errors: an on_error=collect row loses its Case identity, so a
        # mid-chain error surfaces here as a missing row. Without them the report names the
        # symptom and hides the cause.
        extra = {"collected_errors": orphan_errors[:3]} if orphan_errors else {}
        return _failure(case_id, "candidate", "missing_case_row", **extra)
    return (
        _failure(case_id, "candidate", "case_error", error=row["error"]) if "error" in row else None
    )


def _scored(selected: SelectedCase, row: Mapping[str, Any], label: str) -> CaseResult:
    attempt = _attempt(row)
    committed = str(attempt.get("answer") or "")
    answered = bool(committed)
    correct = answered and committed == label
    fields = _candidate_fields(attempt)
    # INVARIANT: an unanswered Case scores 0.0, not None — the official empty-prediction
    # verdict. It counts toward the denominator like any other answered Case.
    grade = {
        "method": "exact_match",
        "score": 1.0 if correct else 0.0,
        "metrics": {"answered": answered},
        "checks": [
            {
                "type": "choice",
                "id": "1",
                "label": "committed choice matches the published key",
                "outcome": "MET" if correct else "UNMET",
                "evidence": [_match_evidence(committed, label, correct)],
                "metadata": {"committed": committed, "expected": label},
            }
        ],
    }
    common = {
        "selected_case": selected,
        "finish_reason": fields["finish_reason"],
        "grade": grade,
        "metadata": fields["metadata"],
        "execution": fields["execution"],
        "operations": fields.get("operations"),
    }
    if fields["status"] == "refused":
        return refused_case_result(refusal=fields["refusal"], **common)
    return scored_case_result(output=fields["output"], **common)


def _match_evidence(committed: str, label: str, correct: bool) -> dict[str, Any]:
    """The exact-match verdict, as the report schema's Evidence record.

    WHY it exists at all for a one-check MCQ Board: `Check.evidence` is required, and a
    reader must be able to see WHAT was compared without re-deriving it from the score.
    `raw_output` carries the committed letter — "" when the reply named no choice.
    """

    return {
        "sequence": 1,
        "producer": {"type": "deterministic", "id": "medxpert/exact-match"},
        "valid": True,
        "outcome": "PASS" if correct else "FAIL",
        "raw_output": committed,
        "metadata": {"expected": label, "answered": bool(committed)},
        "accounting": None,
    }


def _failed(
    selected: SelectedCase, row: Mapping[str, Any] | None, failure: dict[str, Any]
) -> CaseResult:
    fields = _candidate_fields(_attempt(row) if row else {})
    grade = {"method": "exact_match", "score": None, "metrics": {}, "checks": []}
    common = {
        "selected_case": selected,
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


def _attempt(row: Mapping[str, Any] | None) -> Mapping[str, Any]:
    attempts = row.get("attempts") if isinstance(row, Mapping) else None
    first = attempts[0] if isinstance(attempts, list) and attempts else None
    return first if isinstance(first, Mapping) else {}


def _candidate_fields(attempt: Mapping[str, Any]) -> dict[str, Any]:
    output = attempt.get("commit_output")
    finish_reason = attempt.get("finish_reason")
    refusal = attempt.get("refusal")
    metadata = attempt.get("metadata")
    return {
        "status": attempt.get("status"),
        "output": output if isinstance(output, str) else None,
        "finish_reason": finish_reason if isinstance(finish_reason, str) else None,
        "refusal": refusal if isinstance(refusal, str) and refusal.strip() else None,
        "execution": attempt.get("execution"),
        "operations": attempt.get("operations"),
        "metadata": dict(metadata) if isinstance(metadata, Mapping) else {},
    }


def _failure(case_id: int, stage: str, code: str, **metadata: Any) -> dict[str, Any]:
    message = _FAILURE_MESSAGES[code]
    retryable: bool | None = None
    public: dict[str, Any] = {}
    source = metadata.get("error")
    if not isinstance(source, Mapping):
        collected = metadata.get("collected_errors")
        rows = collected[:3] if isinstance(collected, list) else []
        source = next(
            (
                r.get("error")
                for r in rows
                if isinstance(r, Mapping) and isinstance(r.get("error"), Mapping)
            ),
            None,
        )
    if isinstance(source, Mapping):
        diagnostic = public_error(source, default_code=code, default_message=message)
        message = diagnostic.message
        retryable = diagnostic.retryable
        public["source_error"] = {
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
        "metadata": public,
    }


def _accuracy(cases: Sequence[CaseResult]) -> CandidateScore:
    """Plain accuracy, with the answered fraction reported beside it.

    WHY report `answered` even though withhold already counts unanswered Cases as wrong: 40%
    built from 40% correct reads very differently from 40% built from 90% correct and half the
    rows unanswered, and only the second is a formatting failure rather than a knowledge failure.
    """

    grades = [case.grade for case in cases if case.grade is not None]
    scored = [grade for grade in grades if grade.score is not None]
    if not scored:  # pragma: no cover - a Benchmark always selects one Case
        raise AssertionError("MedXpertQA scorer requires at least one scored Case")
    values = [float(grade.score) for grade in scored if grade.score is not None]
    answered = sum(1 for grade in scored if grade.metrics.get("answered"))
    return CandidateScore(
        score=round(sum(values) / len(values), 4),
        metrics={
            "correct": sum(1 for value in values if value >= 1.0),
            "scored_cases": len(values),
            "answered": answered,
            "answered_rate": round(answered / len(values), 4),
        },
    )


__all__ = ["AggregateError", "aggregate", "load_answer", "selected_cases"]
