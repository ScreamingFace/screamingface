"""Reduce trustworthy HealthBench Case evaluations into one board's result.

Think of this as the exam office totalling a stack of graded papers into one
final grade. It receives one row per Case (the graded paper), scores each, and
returns the exam score: the ``mean`` the calling board chose — the official clip
for the professional board, the unclipped challenge metric for worst-30%. Every
step before that reduction is identical for both.

Every selected Case stays visible. Cases with complete rubric Evidence carry
their normal penalty-bearing grade; infrastructure failures carry no numeric
grade, lower top-level coverage, and are excluded from the official mean.

Why so strict? Two ways a lenient reducer would quietly CHEAT in the
submitter's favor:

1. **Dropping a failed Case inflates the mean.** On the worst-30% board these are
   the *hardest* Cases — most score low. Example: scores ``[0.9, 0.1, <failed>]``. Averaging
   the survivors gives 0.50; the honest three-Case run would likely land near
   0.35. The failure deleted a hard row and the score went UP (review finding
   B1 against DRACO's reducer).
2. **Defaulting a missing verdict erases a penalty.** A rubric penalty item
   (say -3, "invents a dosage") only subtracts when the judge says "hit". If
   the judge call failed and we defaulted to "not hit", the -3 vanishes and the
   Case scores higher than it should.

Both failure classes stay explicit: a Case is scored only when every rubric
item has a valid verdict (no defaults), and a missing grade is retained rather
than converted to zero. Malformed or mismatched internal envelopes abort the
run because their identities or contents cannot be trusted.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from screamingface_engine.benchmarks.aggregation import (
    CandidateScore,
    SelectedCase,
    finalize_candidate_result,
    grading_failure_case_result,
)
from screamingface_engine.benchmarks.contract import CaseResult
from screamingface_engine.benchmarks.healthbench.case_evaluation import decode_case_evaluation
from screamingface_engine.benchmarks.healthbench.scoring import (
    case_score,
    sample_stdev,
    verdict_coverage,
)
from screamingface_engine.benchmarks.spine.grading import CaseGrader
from screamingface_engine.benchmarks.spine.rows import RowReader


class AggregateError(ValueError):
    """The reducer's input is unusable — raised before any scoring."""


def load_rubric_points(root: Path, case_id: int) -> list[int] | None:
    """Read one Case's private points list; ``None`` when the asset is unusable."""

    path = root / "rubrics" / f"{case_id}.json"
    try:
        decoded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return _points_from(decoded)


def _points_from(decoded: object) -> list[int] | None:
    items = decoded.get("items") if isinstance(decoded, Mapping) else None
    if not isinstance(items, list) or not items:
        return None
    points: list[int] = []
    for index, item in enumerate(items, start=1):
        value = item.get("points") if isinstance(item, Mapping) else None
        usable = (
            not isinstance(value, bool)
            and isinstance(value, int)
            and isinstance(item, Mapping)
            and item.get("rubric_id") == index
        )
        if not usable:
            return None
        assert isinstance(value, int)
        points.append(value)
    return points


def _selected_cases(root: Path, case_ids: tuple[int, ...]) -> list[SelectedCase]:
    try:
        decoded = json.loads((root / "cases.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AggregateError(f"HealthBench cases are unavailable: {exc}") from None
    if not isinstance(decoded, list):
        raise AggregateError("HealthBench cases must be a JSON array")
    by_id = {
        row.get("id"): row
        for row in decoded
        if isinstance(row, Mapping)
        and isinstance(row.get("id"), int)
        and not isinstance(row.get("id"), bool)
    }
    selected: list[SelectedCase] = []
    for case_id in case_ids:
        row = by_id.get(case_id)
        input_value = row.get("input") if isinstance(row, Mapping) else None
        if not isinstance(input_value, str) or not input_value.strip():
            raise AggregateError(f"HealthBench Case {case_id} has no public input")
        selected.append(SelectedCase(case_id=case_id, input=input_value, metadata={}))
    return selected


def aggregate(
    raw_rows: str,
    root: Path,
    *,
    benchmark_id: str,
    benchmark_revision: str,
    case_ids: tuple[int, ...],
    mean: Callable[[Sequence[float]], float | None],
) -> dict[str, Any]:
    """Score every selected Case, then the exam with the board's own mean.

    ``case_ids`` is authoritative. Missing or explicitly error-collected Cases
    remain visible without a grade; valid Cases are scored with the unchanged
    HealthBench math. The shared finalizer publishes their factual coverage.

    Args:
        raw_rows: the JSON array of Case execution rows, in selected order.
        root: the baked asset directory both boards read (cases + private rubrics).
        benchmark_id: the board publishing this result.
        benchmark_revision: that board's revision, stamped into the result.
        case_ids: the Cases this run selected — the authoritative roll call.
        mean: the exam-level reduction. INVARIANT: this is the ONLY place the two
            HealthBench boards differ in scoring — ``scoring.clipped_mean`` for the
            official professional number, ``scoring.unclipped_mean`` for the worst-30%
            challenge metric. Per-Case grades are identical either way.

    Returns:
        The Candidate result payload: every selected Case, its grade or its failure, the
        exam score, and the run's factual coverage.

    Reference counterpart: the metric aggregation in ``HealthBenchEval``
    (https://github.com/openai/simple-evals/blob/main/healthbench_eval.py) —
    matching it on the clip when ``mean`` is ``clipped_mean``, and deliberately
    diverging on spread (sample stdev, see ``scoring.sample_stdev``).
    """

    selected_cases = _selected_cases(root, case_ids)
    indexed = _ROWS.index(raw_rows, case_ids)
    case_results: list[CaseResult] = []
    for selected in selected_cases:
        case_id = int(selected.case_id)
        grading_failure = indexed.grading_failures.get(case_id)
        if grading_failure is not None:
            assert grading_failure.error is not None
            result = grading_failure_case_result(
                selected_case=selected,
                candidate=grading_failure.candidate,
                error=grading_failure.error,
                method="rubric",
                default_code="healthbench_grading_failed",
                default_message="the HealthBench grader could not grade this Case",
            )
        else:
            points = load_rubric_points(root, case_id)
            result, _, _, _, _ = _GRADER.case_result(
                selected,
                indexed.rows.get(case_id),
                points,
                indexed.collected_errors.get(case_id),
            )
        case_results.append(result)
    return finalize_candidate_result(
        benchmark_id=benchmark_id,
        benchmark_revision=benchmark_revision,
        selected_cases=selected_cases,
        cases=case_results,
        scorer=_healthbench_scorer(mean),
    ).as_payload()


def _healthbench_scorer(
    mean: Callable[[Sequence[float]], float | None],
) -> Callable[[Sequence[CaseResult]], CandidateScore]:
    """Bind one board's exam-level mean into the shared penalty-bearing reduction."""

    def score(cases: Sequence[CaseResult]) -> CandidateScore:
        grades = [case.grade for case in cases]
        if any(grade is None or grade.score is None for grade in grades):  # pragma: no cover
            raise AssertionError("HealthBench scorer requires complete graded Cases")
        typed_grades = [grade for grade in grades if grade is not None and grade.score is not None]
        scores = [float(grade.score) for grade in typed_grades if grade.score is not None]
        judged_items = sum(int(grade.metrics["judged"]) for grade in typed_grades)
        total_items = sum(int(grade.metrics["expected"]) for grade in typed_grades)
        invalid_replies = sum(int(grade.metrics["invalid_replies"]) for grade in typed_grades)
        met_items = sum(
            1 for grade in typed_grades for check in grade.checks if check.outcome == "MET"
        )
        coverage = round(verdict_coverage(judged_items, total_items), 4)
        exam_score = mean(scores)
        if exam_score is None:  # pragma: no cover - a Benchmark always selects one Case
            raise AssertionError("HealthBench scorer requires at least one Case")
        return CandidateScore(
            score=round(exam_score, 4),
            metrics={
                "pass_rate": round(met_items / judged_items, 4) if judged_items else 0.0,
                "scored_cases": len(scores),
                "score_sd": round(sample_stdev(scores), 4),
                "verdict_coverage": coverage,
                "judge_invalid_replies": invalid_replies,
            },
        )

    return score


def _candidate_fields(row: Mapping[str, Any] | None) -> dict[str, Any]:
    """Pull input/output/finish_reason/metadata off the hoisted Case record."""

    case = row.get("case") if isinstance(row, Mapping) else None
    if not isinstance(case, Mapping):
        return {
            "status": None,
            "output": None,
            "finish_reason": None,
            "refusal": None,
            "execution": None,
            "operations": None,
            "metadata": {},
        }
    metadata = case.get("metadata")
    output = case.get("output")
    finish_reason = case.get("finish_reason")
    refusal = case.get("refusal")
    return {
        "status": case.get("status"),
        "output": output if isinstance(output, str) else None,
        "finish_reason": finish_reason if isinstance(finish_reason, str) else None,
        "refusal": refusal if isinstance(refusal, str) and refusal.strip() else None,
        "execution": case.get("execution"),
        "operations": case.get("operations"),
        "metadata": dict(metadata) if isinstance(metadata, Mapping) else {},
    }


def _checks(row: Mapping[str, Any], points: list[int]) -> list[dict[str, Any]]:
    """Project rubric evaluations into the SDK's check/evidence rows."""

    evaluations = row.get("rubric_evaluations")
    if not isinstance(evaluations, list):
        return []
    checks: dict[int, dict[str, Any]] = {}
    for evaluation in evaluations:
        if not isinstance(evaluation, Mapping):
            continue
        rubric = evaluation.get("rubric")
        evidence = evaluation.get("evidence")
        rubric_id = evaluation.get("rubric_id")
        if (
            not isinstance(rubric, Mapping)
            or not isinstance(evidence, Mapping)
            or isinstance(rubric_id, bool)
            or not isinstance(rubric_id, int)
        ):
            continue
        check: dict[str, Any] = {
            "type": "rubric_item",
            "id": str(rubric_id),
            "label": str(rubric.get("rubric_item", "")),
            "evidence": [_evidence(evidence)],
        }
        # Check-level verdict in the report schema's vocabulary — the judge decides
        # it. Without a top-level outcome the SDK renders the check as unjudged
        # (ifeval precedent), so it is emitted whenever the judge reply was valid;
        # an invalid reply leaves the check outcome-less on purpose.
        if evidence.get("valid") is True:
            check["outcome"] = "MET" if evidence.get("criteria_met") is True else "UNMET"
        # One check per rubric_id, last entry wins — the same dict-assignment
        # dedup as _verdicts, so a duplicate judge entry (retry noise) never
        # becomes a second check and met can never exceed judged.
        checks[rubric_id] = {
            **check,
            "metadata": (
                {"points": points[rubric_id - 1]} if 1 <= rubric_id <= len(points) else {}
            ),
        }
    return list(checks.values())


def _evidence(record: Mapping[str, Any]) -> dict[str, Any]:
    valid = record.get("valid") is True
    value: dict[str, Any] = {
        # One judge pass per rubric item (the reference grades each item once),
        # so the sequence is always 1.
        "sequence": 1,
        "producer": {
            "type": str(record.get("producer_type", "model")),
            # Even a malformed Judge reply has a known Benchmark-owned producer.
            "id": str(record.get("producer_id") or "healthbench/judge"),
        },
        "valid": valid,
        "raw_output": str(record.get("raw_output", "")),
        "metadata": {},
        "accounting": record.get("accounting"),
    }
    if valid:
        value["outcome"] = "MET" if record.get("criteria_met") is True else "UNMET"
        value["explanation"] = str(record.get("explanation", ""))
    else:
        value["metadata"] = {"rejection_reason": str(record.get("reason", "invalid"))}
    return value


_FAILURE_MESSAGES = {
    "missing_rubric_asset": "the baked rubric asset for this Case is missing or invalid",
    "missing_case_row": "no evaluation row for this Case reached the aggregate",
    "case_error": "the Case pipeline collected an error instead of an evaluation",
    "incomplete_verdicts": "not every rubric item received a valid judge verdict",
    "no_positive_points": "no judged rubric item carries positive points (baked-asset defect)",
    "invalid_case_evaluation": "the evaluation row lacked a usable candidate envelope",
}


def _verdicts(row: Mapping[str, Any]) -> tuple[dict[int, bool], int]:
    verdicts: dict[int, bool] = {}
    invalid = 0
    evaluations = row.get("rubric_evaluations")
    if not isinstance(evaluations, list):
        return verdicts, invalid
    for evaluation in evaluations:
        if not isinstance(evaluation, Mapping):
            invalid += 1
            continue
        evidence = evaluation.get("evidence")
        if not isinstance(evidence, Mapping) or evidence.get("valid") is not True:
            invalid += 1
            continue
        rubric_id = evidence.get("rubric_id")
        criteria_met = evidence.get("criteria_met")
        if (
            isinstance(rubric_id, int)
            and not isinstance(rubric_id, bool)
            and (criteria_met is True or criteria_met is False)
        ):
            verdicts[rubric_id] = criteria_met
        else:
            invalid += 1
    return verdicts, invalid


# WHY bound at module bottom: the grading steps live in the spine (OME-1039); the
# hooks and the failure-message wording stay board-owned so per-case failure output
# is byte-identical to the pre-extraction copies (the goldens pin every failure code).
_ROWS = RowReader(
    benchmark_label="HealthBench",
    error_type=AggregateError,
    decode_case_evaluation=decode_case_evaluation,
)

_GRADER = CaseGrader(
    failure_messages=_FAILURE_MESSAGES,
    case_score=case_score,
    verdicts=_verdicts,
    checks=_checks,
    candidate_fields=_candidate_fields,
)

__all__ = [
    "AggregateError",
    "CaseResult",
    "aggregate",
    "load_rubric_points",
]
