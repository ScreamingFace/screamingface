"""ContractEval's grading hooks — everything this board still writes to be graded.

The spine owns the marking room (``spine/scored.py``); this module is the board's
contribution: its containment ``grade_case`` (every gold sentence quoted verbatim, or a
correct abstention), its confusion-matrix scorer, and its own failure wording.

INVARIANT — the headline score is F1 from a DATASET-level confusion matrix, not a mean of
case scores. Every other board binds ``exam_scorer(mean)``; this one cannot, because a mean
destroys the fact that distinguishes the two ways of being wrong:

    positive row (a clause exists)  → TP if the reply contains every gold span, else FN
    negative row (no clause exists) → TN if the reply abstains,                  else FP

A case score of 0.0 is a false negative on a positive row and a false positive on a negative
one. ``ScoredPath.aggregate`` takes the board's whole ``CandidateScore`` builder, which is
exactly the generality this needs.

AIDEV-NOTE: read that table before changing anything here. Positive rows can never be TN/FP
and negative rows can never be TP/FN, so ``precision`` mixes positive-row successes against
negative-row failures. That is unusual, it is the published metric, and it is not a bug.

AIDEV-NOTE: F1 rather than accuracy is the headline because 70.3% of rows have no clause — a
model that always abstains earns ~70% accuracy while answering nothing, and F1 scores it 0.

INVARIANT — a failure to COMMIT and a failure to RUN are different facts. A model that quotes
the wrong sentences has been measured (score 0.0, and it occupies a cell in the matrix). A Case
whose invocation errored has NOT been measured (score ``None``, a visible failed Case, and no
cell) — collapsing the two would let an outage read as a false negative and depress recall.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from screamingface_engine.benchmarks.aggregation import CandidateScore, SelectedCase
from screamingface_engine.benchmarks.contract import CaseResult
from screamingface_engine.benchmarks.contracteval.case_evaluation import decode_case_evaluation
from screamingface_engine.benchmarks.spine.rows import RowReader, read_selected_cases
from screamingface_engine.benchmarks.spine.scored import (
    CaseGradeOutcome,
    GradeRequest,
    ScoredPath,
)

# INVARIANT: failure wording is this board's published voice — no rubric-flavored code
# ("missing_rubric_asset") may leak into a result whose grading material is an answer key.
_FAILURE_MESSAGES = {
    "missing_answer_asset": "the baked answer record for this Case is missing or invalid",
    "missing_case_row": "no evaluation row for this Case reached the aggregate",
    "case_error": "the Case pipeline collected an error instead of an evaluation",
    "polarity_mismatch": (
        "the checked attempt disagrees with the baked answer key about whether this Case has a "
        "clause — the assets and the run are out of step"
    ),
}


class AggregateError(ValueError):
    """The reducer's input is unusable — raised before any scoring."""


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
    """The roll call from the baked ``cases.json``, in selected order."""

    return read_selected_cases(
        root, case_ids, benchmark_label="ContractEval", error_type=AggregateError
    )


def aggregate(
    raw_rows: str,
    root: Path,
    *,
    benchmark_id: str,
    benchmark_revision: str,
    case_ids: tuple[int, ...],
) -> dict[str, Any]:
    """Score every selected Case on the shared scored path, then the paper's F1."""

    answers: dict[int, dict[str, Any] | None] = {
        case_id: load_answer(root, case_id) for case_id in case_ids
    }
    return _PATH.aggregate(
        raw_rows,
        benchmark_id=benchmark_id,
        benchmark_revision=benchmark_revision,
        selected_cases=selected_cases(root, case_ids),
        grading_material=lambda case_id: answers.get(case_id),
        scorer=_confusion_matrix_score,
    )


def _decode(grading: object, expected_case_id: int) -> dict[str, Any]:
    """Validate the envelope, then hoist attempt 1 into the spine's candidate shape."""

    envelope = decode_case_evaluation(grading, expected_case_id)
    attempt: Mapping[str, Any] = envelope["attempts"][0]
    # AIDEV-NOTE (review, PR #984): this used to read `attempt.get("metadata")`, which `_check`
    # never emits — dead on arrival, ported verbatim from medxpert where it is equally dead. The
    # empty dict is now explicit. If a future check record carries per-Case report metadata,
    # THIS is the seam it joins; `ScoredPath.aggregate`'s `case_metadata=` is the other option,
    # and the right one for anything read from the private answer asset rather than the reply.
    fields: dict[str, Any] = {}
    return {
        "case": {
            "status": attempt.get("status"),
            "output": attempt.get("output"),
            "finish_reason": attempt.get("finish_reason"),
            "refusal": attempt.get("refusal"),
            "execution": attempt.get("execution"),
            "operations": attempt.get("operations"),
            "metadata": fields,
        },
        "attempt": dict(attempt),
    }


async def _grade_case(request: GradeRequest) -> CaseGradeOutcome:
    """Mark one script: did the reply contain every gold sentence, or rightly abstain?

    INVARIANT: the verdict itself was computed ONCE, at check time, and is only read here.
    Re-deriving it would be a second implementation and a second chance to disagree.
    """

    attempt: Mapping[str, Any] = request.row["attempt"]
    material = request.material
    assert isinstance(material, Mapping)  # the ladder already rejected unusable assets
    is_positive = bool(material.get("is_positive"))
    # INVARIANT: the baked key is the authority on polarity; the check record carries its own
    # copy. Disagreement means the assets and the run are out of step, and silently trusting
    # either one files the Case in the WRONG confusion-matrix cell.
    if bool(attempt.get("is_positive")) != is_positive:
        return CaseGradeOutcome(score=None, metrics={}, checks=[], failure_code="polarity_mismatch")
    correct = bool(attempt.get("correct"))
    abstained = bool(attempt.get("abstained"))
    spans = material.get("gold_spans")
    return CaseGradeOutcome(
        score=1.0 if correct else 0.0,
        # WHY these ride on the grade: the scorer needs each Case's CELL in the confusion
        # matrix, and a mean of the scores cannot reconstruct it.
        metrics={
            "is_positive": is_positive,
            "abstained": abstained,
            "jaccard": _ratio(attempt.get("jaccard")),
        },
        checks=[
            {
                "type": "clause",
                "id": "1",
                "label": (
                    "every gold clause sentence appears verbatim"
                    if is_positive
                    else "the model correctly reports no related clause"
                ),
                "outcome": "MET" if correct else "UNMET",
                "evidence": [_containment_evidence(spans, attempt, correct)],
                "metadata": {"is_positive": is_positive, "abstained": abstained},
            }
        ],
    )


def _containment_evidence(
    spans: object, attempt: Mapping[str, Any], correct: bool
) -> dict[str, Any]:
    """The verdict as the report schema's Evidence record.

    WHY `gold_span_count` and not the spans themselves: the report is published, and on a Case
    whose contract text is public the spans ARE the answer key.
    """

    return {
        "sequence": 1,
        "producer": {"type": "deterministic", "id": "contracteval/containment"},
        "valid": True,
        # WHY the verdict and not the reply text: this producer is the containment check, so
        # its OUTPUT is the boolean it computed. The reply is already on the Case as `output`.
        "outcome": "PASS" if correct else "FAIL",
        "raw_output": correct,
        "metadata": {
            "gold_span_count": len(spans) if isinstance(spans, list) else 0,
            "abstained": bool(attempt.get("abstained")),
            "jaccard": _ratio(attempt.get("jaccard")),
        },
        "accounting": None,
    }


def _ratio(value: object) -> float:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else 0.0


def _confusion_matrix_score(cases: Sequence[CaseResult]) -> CandidateScore:
    """The paper's F1 — Evaluation.py lines 60-79, with one named deviation and one guard."""

    tp = fn = tn = fp = 0
    abstentions = false_abstentions = positives = 0
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
    # ZeroDivisionError for a model that never scores a TP. With 70.3% of rows negative, an
    # always-abstaining model is realistic rather than hypothetical, so we return the limit.
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


# WHY bound at module bottom: the scored path lives in the spine; the hooks and the failure
# wording stay board-owned, so per-Case output keeps this board's voice.
_PATH = ScoredPath(
    reader=RowReader(
        benchmark_label="ContractEval",
        error_type=AggregateError,
        decode_case_evaluation=_decode,
    ),
    grade_case=_grade_case,
    failure_messages=_FAILURE_MESSAGES,
    method="containment",
    grading_failure_code="contracteval_grading_failed",
    grading_failure_message="the ContractEval checker could not grade this Case",
    missing_material_code="missing_answer_asset",
)

__all__ = ["AggregateError", "aggregate", "load_answer", "selected_cases"]
