"""Reduce every selected ContractEval Case into one Candidate result.

INVARIANT — this is the only reducer in the repo that does NOT average case scores. ContractEval's
F1/F2 come from a dataset-level confusion matrix (Evaluation.py lines 60-79), so each Case must
carry its polarity and verdict up to the scorer rather than collapsing to a number on the way.

    positive row (a clause exists)  → TP if the reply contains every gold span, else FN
    negative row (no clause exists) → TN if the reply abstains,                  else FP

AIDEV-NOTE: read that table before changing anything here. Positive rows can never be TN/FP and
negative rows can never be TP/FN, so `precision` mixes positive-row successes against
negative-row failures. That is unusual and it is the published metric; it is not a bug.

INVARIANT — a failure to COMMIT and a failure to RUN are different facts. A model that answers
wrongly has been measured (score 0.0, and it occupies a cell in the matrix). A Case whose
invocation errored has NOT been measured (score `None`, a visible failed Case, and NO cell) —
collapsing the two would let an outage read as a false-negative and depress recall.

AIDEV-NOTE: this board deliberately does NOT use `spine.CaseGrader` — that grader is
rubric-shaped (`points: list[int]` with verdicts-by-position) and emits rubric failure codes.
`spine.RowReader` IS used; row indexing is genuinely board-independent. Same call as MedXpertQA.
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
    refusal_case_result,
    scored_case_result,
)
from screamingface_engine.benchmarks.contract import CaseResult
from screamingface_engine.benchmarks.contracteval.case_evaluation import decode_case_evaluation
from screamingface_engine.benchmarks.spine.rows import RowReader

_FAILURE_MESSAGES = {
    "missing_answer_asset": "the baked answer record for this Case is missing or invalid",
    "missing_case_row": "no evaluation row for this Case reached the aggregate",
    "case_error": "the Case pipeline collected an error instead of an evaluation",
}


class AggregateError(ValueError):
    """The reducer's input is unusable — raised before any scoring."""


_ROWS = RowReader(
    benchmark_label="ContractEval",
    error_type=AggregateError,
    decode_case_evaluation=decode_case_evaluation,
)


def load_answer(root: Path, case_id: int) -> dict[str, Any] | None:
    """Read one Case's private answer record; ``None`` when the asset is unusable."""

    try:
        decoded = json.loads((root / "answers" / f"{case_id}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(decoded, Mapping) or not isinstance(decoded.get("gold_spans"), list):
        return None
    return dict(decoded)


def selected_cases(root: Path, case_ids: tuple[int, ...]) -> list[SelectedCase]:
    try:
        decoded = json.loads((root / "cases.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AggregateError(f"ContractEval cases are unavailable: {exc}") from None
    if not isinstance(decoded, list):
        raise AggregateError("ContractEval cases must be a JSON array")
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
            raise AggregateError(f"ContractEval Case {case_id} has no public input")
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
    """Score every selected Case, then the exam as the paper's confusion-matrix F1."""

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
                    method="containment",
                    default_code="contracteval_grading_failed",
                    default_message="the ContractEval checker could not grade this Case",
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
        scorer=_confusion_matrix_score,
    ).as_payload()


def _case_result(
    selected: SelectedCase,
    row: Mapping[str, Any] | None,
    answer: Mapping[str, Any] | None,
    orphan_errors: list[dict[str, Any]] | None,
) -> CaseResult:
    """Score one Case, or turn an unusable state into a visible failure."""

    failure = _terminal_failure(selected, row, answer, orphan_errors)
    if failure is not None:
        return _failed(selected, None if row is None else row, failure)
    assert row is not None and answer is not None
    return _scored(selected, row, answer)


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


def _scored(
    selected: SelectedCase, row: Mapping[str, Any], answer: Mapping[str, Any]
) -> CaseResult:
    attempt = _attempt(row)
    correct = bool(attempt.get("correct"))
    is_positive = bool(answer.get("is_positive"))
    abstained = bool(attempt.get("abstained"))
    fields = _candidate_fields(attempt)
    grade = {
        "method": "containment",
        "score": 1.0 if correct else 0.0,
        # WHY these ride on the grade: the scorer needs each Case's CELL in the confusion
        # matrix, and a mean of the scores cannot reconstruct it — 0.0 could be an FN or an FP.
        "metrics": {
            "is_positive": is_positive,
            "abstained": abstained,
            "jaccard": _ratio(attempt.get("jaccard")),
        },
        "checks": [
            {
                "type": "clause",
                "id": "1",
                "label": (
                    "every gold clause sentence appears verbatim"
                    if is_positive
                    else "the model correctly reports no related clause"
                ),
                "outcome": "MET" if correct else "UNMET",
                "evidence": [_containment_evidence(answer, attempt, correct)],
                "metadata": {"is_positive": is_positive, "abstained": abstained},
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
        # OME-1037: a refusal WITH text is graded — 0.0 here, since a refusal quotes no clause —
        # and stays a scored Case carrying the refusal, so it occupies its confusion-matrix cell
        # like any other wrong answer. A TEXTLESS refusal is a content_filter provider decline:
        # the classifier drops the score and fails the Case, so infrastructure never publishes
        # as a plausible grade.
        return refusal_case_result(refusal=fields["refusal"], **common)
    return scored_case_result(output=fields["output"], **common)


def _containment_evidence(
    answer: Mapping[str, Any], attempt: Mapping[str, Any], correct: bool
) -> dict[str, Any]:
    """The verdict as the report schema's Evidence record.

    WHY `gold_span_count` and not the spans themselves: the report is published, and the spans
    ARE the answer key for a row whose contract text is public.
    """

    spans = answer.get("gold_spans")
    return {
        "sequence": 1,
        "producer": {"type": "deterministic", "id": "contracteval/containment"},
        "valid": True,
        "outcome": "PASS" if correct else "FAIL",
        "raw_output": bool(attempt.get("abstained")),
        "metadata": {
            "gold_span_count": len(spans) if isinstance(spans, list) else 0,
            "jaccard": _ratio(attempt.get("jaccard")),
        },
        "accounting": None,
    }


def _failed(
    selected: SelectedCase, row: Mapping[str, Any] | None, failure: dict[str, Any]
) -> CaseResult:
    fields = _candidate_fields(_attempt(row) if row else {})
    grade = {"method": "containment", "score": None, "metrics": {}, "checks": []}
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
        return refusal_case_result(refusal=fields["refusal"], **common)
    return failed_case_result(output=fields["output"], **common)


def _attempt(row: Mapping[str, Any] | None) -> Mapping[str, Any]:
    attempts = row.get("attempts") if isinstance(row, Mapping) else None
    first = attempts[0] if isinstance(attempts, list) and attempts else None
    return first if isinstance(first, Mapping) else {}


def _ratio(value: object) -> float:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else 0.0


def _candidate_fields(attempt: Mapping[str, Any]) -> dict[str, Any]:
    output = attempt.get("output")
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


def _confusion_matrix_score(cases: Sequence[CaseResult]) -> CandidateScore:
    """The paper's F1 — Evaluation.py lines 60-79, with one named deviation and one guard."""

    tp = fn = tn = fp = 0
    abstentions = false_abstentions = 0
    positives = 0
    jaccards: list[float] = []
    for case in cases:
        grade = case.grade
        if grade is None or grade.score is None:
            continue  # not measured — an errored Case occupies no cell (see module INVARIANT)
        is_positive = bool(grade.metrics.get("is_positive"))
        abstained = bool(grade.metrics.get("abstained"))
        correct = grade.score >= 1.0
        abstentions += 1 if abstained else 0
        if is_positive:
            positives += 1
            jaccards.append(float(grade.metrics.get("jaccard") or 0.0))
            false_abstentions += 1 if abstained else 0
            tp, fn = (tp + 1, fn) if correct else (tp, fn + 1)
        else:
            tn, fp = (tn + 1, fp) if correct else (tn, fp + 1)
    graded = tp + tn + fp + fn
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    # NAMED DEVIATION: the reference computes 2PR/(P+R) with no zero guard and raises
    # ZeroDivisionError for a model that never scores a TP. Given that 70.3% of rows are
    # negative, an always-abstaining model is realistic rather than hypothetical, so we return
    # the limit — 0.0 — instead of crashing the run.
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    f2 = 5 * precision * recall / (4 * precision + recall) if 4 * precision + recall else 0.0
    return CandidateScore(
        score=round(f1, 4),
        metrics={
            "accuracy": round((tp + tn) / graded, 4) if graded else 0.0,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f2": round(f2, 4),
            "true_positives": tp,
            "false_negatives": fn,
            "true_negatives": tn,
            "false_positives": fp,
            "scored_cases": graded,
            "no_related_clause_rate": round(abstentions / graded, 4) if graded else 0.0,
            # NAMED DEVIATION (spec D-3): the reference divides by a hardcoded 1244 — the FULL
            # split's positive count — which is wrong for any subset run. Identical at full
            # split, correct everywhere else.
            "false_no_related_clause_rate": (
                round(false_abstentions / positives, 4) if positives else 0.0
            ),
            # PROTOCOL (spec F-5): positive rows only — Evaluation.py `continue`s on empty labels.
            "jaccard_mean": round(sum(jaccards) / len(jaccards), 4) if jaccards else 0.0,
        },
    )


__all__ = ["AggregateError", "aggregate", "load_answer", "selected_cases"]
