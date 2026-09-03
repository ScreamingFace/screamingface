"""Reduce every selected GDPval Case into one Candidate result.

INVARIANT: every unusable state becomes a VISIBLE failed Case, never a silently missing one. A
``None`` exam score must always be traceable to a named per-Case failure code — otherwise a judge
outage, a broken asset and a genuinely bad answer are indistinguishable in the report, which is
the reading this board exists to avoid.

INVARIANT: points come from the PRIVATE baked rubric on disk, never from anything that has passed
through a model. The judge decides whether a criterion was met; it never decides what it is worth.
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
from screamingface_engine.benchmarks.case_execution import (
    CaseExecutionOutcome,
    case_execution_matches,
    case_execution_outcome,
)
from screamingface_engine.benchmarks.contract import CaseResult
from screamingface_engine.benchmarks.gdpval.case_evaluation import decode_case_evaluation
from screamingface_engine.benchmarks.gdpval.scoring import (
    case_score,
    sample_stdev,
    verdict_coverage,
)
from screamingface_engine.benchmarks.spine.grading import CaseGrader

_FAILURE_MESSAGES = {
    "missing_rubric_asset": "the baked rubric asset for this Case is missing or invalid",
    "missing_case_row": "no evaluation row for this Case reached the aggregate",
    "case_error": "the Case pipeline collected an error instead of an evaluation",
    "incomplete_verdicts": "not every rubric criterion received a valid judge verdict",
    "no_positive_points": "no judged criterion carries positive points (baked-asset defect)",
}


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
        # INVARIANT: rubric_id is the 1-based position `prepare` assigned. A file whose ids do
        # not match their positions is unusable rather than partially usable — scoring the wrong
        # criterion is worse than reporting a missing asset.
        usable = (
            isinstance(item, Mapping)
            and not isinstance(value, bool)
            and isinstance(value, int)
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
        raise AggregateError(f"GDPval cases are unavailable: {exc}") from None
    if not isinstance(decoded, list):
        raise AggregateError("GDPval cases must be a JSON array")
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
            raise AggregateError(f"GDPval Case {case_id} has no public input")
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
    """Score every selected Case, then the exam with the board's mean.

    ``case_ids`` is authoritative: a Case that produced no row stays visible without a grade
    rather than vanishing from the roll call.
    """

    selected_cases = _selected_cases(root, case_ids)
    by_case, errors_by_case, grading_failures = _index_rows(_decode_rows(raw_rows), case_ids)
    case_results: list[CaseResult] = []
    for selected in selected_cases:
        case_id = int(selected.case_id)
        grading_failure = grading_failures.get(case_id)
        if grading_failure is not None:
            assert grading_failure.error is not None
            result = grading_failure_case_result(
                selected_case=selected,
                candidate=grading_failure.candidate,
                error=grading_failure.error,
                method="rubric",
                default_code="gdpval_grading_failed",
                default_message="the GDPval grader could not grade this Case",
            )
        else:
            points = load_rubric_points(root, case_id)
            result, _, _, _, _ = _GRADER.case_result(
                selected, by_case.get(case_id), points, errors_by_case.get(case_id)
            )
        case_results.append(result)
    return finalize_candidate_result(
        benchmark_id=benchmark_id,
        benchmark_revision=benchmark_revision,
        selected_cases=selected_cases,
        cases=case_results,
        scorer=_gdpval_scorer(mean),
    ).as_payload()


def _gdpval_scorer(
    mean: Callable[[Sequence[float]], float | None],
) -> Callable[[Sequence[CaseResult]], CandidateScore]:
    def score(cases: Sequence[CaseResult]) -> CandidateScore:
        grades = [case.grade for case in cases]
        if any(grade is None or grade.score is None for grade in grades):  # pragma: no cover
            raise AssertionError("GDPval scorer requires complete graded Cases")
        typed = [grade for grade in grades if grade is not None and grade.score is not None]
        scores = [float(grade.score) for grade in typed if grade.score is not None]
        judged_items = sum(int(grade.metrics["judged"]) for grade in typed)
        total_items = sum(int(grade.metrics["expected"]) for grade in typed)
        invalid_replies = sum(int(grade.metrics["invalid_replies"]) for grade in typed)
        met_items = sum(1 for grade in typed for check in grade.checks if check.outcome == "MET")
        exam_score = mean(scores)
        if exam_score is None:  # pragma: no cover - a Benchmark always selects one Case
            raise AssertionError("GDPval scorer requires at least one Case")
        return CandidateScore(
            score=round(exam_score, 4),
            metrics={
                "pass_rate": round(met_items / judged_items, 4) if judged_items else 0.0,
                "scored_cases": len(scores),
                "score_sd": round(sample_stdev(scores), 4),
                "verdict_coverage": round(verdict_coverage(judged_items, total_items), 4),
                "judge_invalid_replies": invalid_replies,
            },
        )

    return score


def _candidate_fields(row: Mapping[str, Any] | None) -> dict[str, Any]:
    """Pull output/finish_reason/metadata off the hoisted Case record."""

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
    """Project criterion evaluations into the SDK's check/evidence rows."""

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
        # An invalid judge reply leaves the check outcome-less on purpose: the SDK renders it as
        # unjudged rather than as a failed criterion, which is the honest reading.
        if evidence.get("valid") is True:
            check["outcome"] = "MET" if evidence.get("criteria_met") is True else "UNMET"
        # One check per rubric_id, last wins — the same dedup as `_verdicts`, so retry noise can
        # never become a second check and `met` can never exceed `judged`.
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
        # One judge pass per criterion, so the sequence is always 1.
        "sequence": 1,
        "producer": {
            "type": str(record.get("producer_type", "model")),
            # Even a malformed judge reply has a known Benchmark-owned producer.
            "id": str(record.get("producer_id") or "gdpval/judge"),
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


def _decode_rows(raw: str) -> list[Any]:
    try:
        decoded = json.loads(raw or "")
    except ValueError as exc:
        raise AggregateError(f"GDPval rows are not JSON: {exc}") from None
    if not isinstance(decoded, list):
        raise AggregateError("GDPval rows must be a JSON array")
    return decoded


def _index_rows(
    rows: list[Any], case_ids: tuple[int, ...]
) -> tuple[
    dict[int, dict[str, Any]],
    dict[int, list[dict[str, Any]]],
    dict[int, CaseExecutionOutcome],
]:
    """Validate rows and split evaluations from positional collected errors."""

    if len(rows) > len(case_ids):
        raise AggregateError(
            f"aggregate received {len(rows)} rows for {len(case_ids)} selected Cases"
        )
    indexed: dict[int, dict[str, Any]] = {}
    errors_by_case: dict[int, list[dict[str, Any]]] = {}
    grading_failures: dict[int, CaseExecutionOutcome] = {}
    for index, entry in enumerate(rows):
        _index_row(entry, index, case_ids[index], indexed, errors_by_case, grading_failures)
    return indexed, errors_by_case, grading_failures


def _index_row(
    entry: object,
    index: int,
    expected_case_id: int,
    indexed: dict[int, dict[str, Any]],
    errors_by_case: dict[int, list[dict[str, Any]]],
    grading_failures: dict[int, CaseExecutionOutcome],
) -> None:
    row = _row_value(entry, index)
    if _index_outer_error(row, index, expected_case_id, indexed, errors_by_case):
        return
    try:
        outcome = case_execution_outcome(row)
        if not case_execution_matches(outcome, expected_case_id):
            raise ValueError(
                f"Case execution claims case_id {outcome.case_id!r}, "
                f"but the selected Case is {expected_case_id!r}"
            )
        if outcome.error is not None:
            grading_failures[expected_case_id] = outcome
        else:
            indexed[expected_case_id] = decode_case_evaluation(outcome.grading, expected_case_id)
    except (TypeError, ValueError) as exc:
        raise AggregateError(f"Case result at position {index} is invalid: {exc}") from None


def _index_outer_error(
    row: Mapping[str, Any],
    index: int,
    expected_case_id: int,
    indexed: dict[int, dict[str, Any]],
    errors_by_case: dict[int, list[dict[str, Any]]],
) -> bool:
    error = row.get("error")
    if error is None:
        return False
    if not isinstance(error, Mapping):
        raise AggregateError(f"Case result at position {index} has an invalid error")
    claimed = row.get("case_id")
    if claimed is not None and claimed != expected_case_id:
        raise AggregateError(
            f"Case result at position {index} claims case_id {claimed}, "
            f"but the selected Case is {expected_case_id}"
        )
    if claimed is None:
        errors_by_case.setdefault(expected_case_id, []).append(dict(row))
    else:
        indexed[expected_case_id] = dict(row)
    return True


def _row_value(entry: object, index: int) -> Mapping[str, Any]:
    try:
        row = json.loads(entry) if isinstance(entry, str) else entry
    except ValueError as exc:
        raise AggregateError(f"Case result at position {index} is not JSON: {exc}") from None
    if not isinstance(row, Mapping):
        raise AggregateError(f"Case result at position {index} must be an object")
    return row


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


# WHY bound at module bottom: the grading ladder lives in the spine (OME-1039); the
# hooks and the failure-message wording stay board-owned so per-case failure output
# is byte-identical to the pre-extraction copies (the goldens' codes rung pins it).
_GRADER = CaseGrader(
    failure_messages=_FAILURE_MESSAGES,
    case_score=case_score,
    verdicts=_verdicts,
    checks=_checks,
    candidate_fields=_candidate_fields,
)

__all__ = ["AggregateError", "CaseResult", "aggregate", "load_rubric_points"]
