"""Build auditable DRACO Case Results from Engine-bound checks and evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from screamingface_engine.benchmarks.aggregation import (
    SelectedCase,
)
from screamingface_engine.benchmarks.aggregation import (
    failed_case_result as build_failed_case_result,
)
from screamingface_engine.benchmarks.aggregation import (
    refused_case_result as build_refused_case_result,
)
from screamingface_engine.benchmarks.aggregation import (
    scored_case_result as build_scored_case_result,
)
from screamingface_engine.benchmarks.contract import CaseResult
from screamingface_engine.benchmarks.draco.errors import AggregateError
from screamingface_engine.benchmarks.draco.scoring import flatten_criteria, score_case
from screamingface_engine.benchmarks.draco.validation import optional_integer
from screamingface_engine.benchmarks.draco.verdict import SCHEMA as VERDICT_SCHEMA


def group_runs(verdicts: Sequence[Mapping[str, Any]]) -> list[dict[str, bool]]:
    """Split flat verdicts into one dict per judge pass, in sequence order.

    INVARIANT: the paper scores each pass independently and then means the passes. Majority-voting
    first would erase the judge-disagreement signal. A criterion with fewer verdicts has no entry
    in the later runs, so it drops out rather than becoming an UNMET.
    """
    runs: list[dict[str, bool]] = []
    for verdict in verdicts:
        criterion_id = verdict.get("criterion_id") or verdict.get("id")
        sequence = optional_integer(verdict.get("sequence"))
        if criterion_id is None or sequence is None or sequence < 1:
            continue
        index = sequence - 1
        while len(runs) <= index:
            runs.append({})
        runs[index][str(criterion_id)] = str(verdict.get("criterion_status", "")).upper() == "MET"
    return runs


def valid_verdicts(
    rubric: Mapping[str, Any], verdicts: Sequence[Mapping[str, Any]], case_id: int
) -> list[dict[str, Any]]:
    """Keep strict verdicts for criterion ids owned by this case's rubric."""
    expected = {str(criterion["id"]) for criterion in flatten_criteria(rubric)}
    accepted: list[dict[str, Any]] = []
    for verdict in verdicts:
        criterion_id = verdict.get("criterion_id") or verdict.get("id")
        status = str(verdict.get("criterion_status", "")).upper()
        if (
            verdict.get("schema") != VERDICT_SCHEMA
            or verdict.get("valid") is not True
            or optional_integer(verdict.get("case_id")) != case_id
            or str(criterion_id) not in expected
            or status not in {"MET", "UNMET"}
            or (optional_integer(verdict.get("sequence")) or 0) < 1
            or verdict.get("producer_type") != "model"
            or not isinstance(verdict.get("producer_id"), str)
            or not isinstance(verdict.get("raw_output"), str)
        ):
            continue
        accepted.append({**verdict, "criterion_id": str(criterion_id), "criterion_status": status})
    return accepted


def scored_case_result(
    case_record: Mapping[str, Any],
    rubric: Mapping[str, Any],
    check_records: Sequence[Mapping[str, Any]],
    records: Sequence[Mapping[str, Any]],
    verdicts: Sequence[Mapping[str, Any]],
    judge_passes: int,
) -> CaseResult:
    """Build one scored or coverage-failed Case Result."""
    case_id, criteria_expected = _expected_criteria(case_record, rubric)
    expected = criteria_expected * judge_passes
    accepted = len(verdicts)
    scored = score_case(rubric, group_runs(verdicts), criteria_expected=criteria_expected)
    coverage = (accepted / expected) if expected else 0.0
    metrics = {
        "normalized_score_sd": scored["normalized_score_sd"],
        "pass_rate": scored["pass_rate"],
        "pass_rate_sd": scored["pass_rate_sd"],
        "accuracy": scored["accuracy"],
        "accuracy_pass_rate": scored["accuracy_pass_rate"],
        "axis_scores": scored["axis_scores"],
        "axis_pass_rates": scored["axis_pass_rates"],
        "coverage": round(coverage, 4),
        "coverage_sd": scored["coverage_sd"],
        "n_runs": scored["n_runs"],
        "verdicts_expected": expected,
        "verdicts_accepted": accepted,
        "verdicts_rejected": max(expected - accepted, 0),
        "verdicts_invalid": max(len(records) - accepted, 0),
        "verdicts_missing": max(expected - len(records), 0),
    }
    return _case_result(
        case_record,
        score=scored["normalized_score"],
        metrics=metrics,
        checks=_checks(case_id, rubric, check_records, records, criteria_expected),
        failures=[],
    )


def incomplete_case_result(
    case_record: Mapping[str, Any],
    rubric: Mapping[str, Any],
    check_records: Sequence[Mapping[str, Any]],
    evidence: Sequence[Mapping[str, Any]],
    judge_passes: int,
    failure: Mapping[str, Any],
) -> CaseResult:
    """Retain auditable grading material when no Judge Evidence was scoreable."""
    case_id, criteria_expected = _expected_criteria(case_record, rubric)
    verdicts_expected = criteria_expected * judge_passes
    metrics = {
        "normalized_score_sd": 0.0,
        "pass_rate": 0.0,
        "pass_rate_sd": 0.0,
        # Nothing was judged, so the Factual Accuracy axis was never observed — unknown, not zero.
        "accuracy": None,
        "accuracy_pass_rate": None,
        "axis_scores": {},
        "axis_pass_rates": {},
        "coverage": 0.0,
        "coverage_sd": 0.0,
        "n_runs": 0,
        "verdicts_expected": verdicts_expected,
        "verdicts_accepted": 0,
        "verdicts_rejected": verdicts_expected,
        "verdicts_invalid": len(evidence),
        "verdicts_missing": max(verdicts_expected - len(evidence), 0),
    }
    return _case_result(
        case_record,
        score=None,
        metrics=metrics,
        checks=_checks(case_id, rubric, check_records, evidence, criteria_expected),
        failures=[dict(failure)],
    )


def failed_selected_case_result(
    selected_case: Mapping[str, Any], failure: Mapping[str, Any]
) -> CaseResult:
    """Represent a selected Case that never produced a Candidate answer."""
    return build_failed_case_result(
        selected_case=_selected_case(selected_case, id_key="id"),
        failures=[failure],
    )


def ungraded_case_result(case_record: Mapping[str, Any], failure: Mapping[str, Any]) -> CaseResult:
    """Retain an observed Candidate answer when private grading material is unavailable."""
    selected = _selected_case(case_record, id_key="case_id")
    refusal = case_record.get("refusal")
    if case_record.get("status") == "refused":
        return build_refused_case_result(
            selected_case=selected,
            refusal=refusal if isinstance(refusal, str) else None,
            finish_reason=_finish_reason(case_record.get("finish_reason")),
            grade={"method": "rubric", "score": None, "metrics": {}, "checks": []},
            failures=[failure],
            execution=case_record.get("execution"),
            operations=case_record.get("operations"),
        )
    return build_failed_case_result(
        selected_case=selected,
        failures=[failure],
        output=str(case_record["output"]),
        finish_reason=_finish_reason(case_record.get("finish_reason")),
        execution=case_record.get("execution"),
        operations=case_record.get("operations"),
    )


def _expected_criteria(
    case_record: Mapping[str, Any],
    rubric: Mapping[str, Any],
) -> tuple[int, int]:
    case_id = int(case_record["case_id"])
    rubric_count = sum(1 for _ in flatten_criteria(rubric))
    return case_id, rubric_count


def _case_result(
    case_record: Mapping[str, Any],
    *,
    score: float | None,
    metrics: Mapping[str, Any],
    checks: Sequence[Mapping[str, Any]],
    failures: Sequence[Mapping[str, Any]],
) -> CaseResult:
    """Assemble the shared Case Result envelope once."""
    selected = _selected_case(case_record, id_key="case_id")
    output = case_record.get("output")
    refusal = case_record.get("refusal")
    finish_reason = _finish_reason(case_record.get("finish_reason"))
    grade = {
        "method": "rubric",
        "score": score,
        "metrics": dict(metrics),
        "checks": [dict(check) for check in checks],
    }
    if case_record.get("status") == "refused":
        return build_refused_case_result(
            selected_case=selected,
            refusal=refusal if isinstance(refusal, str) else None,
            finish_reason=finish_reason,
            grade=grade,
            failures=failures,
            execution=case_record.get("execution"),
            operations=case_record.get("operations"),
        )
    if not isinstance(output, str):  # pragma: no cover - sealed by the Case record decoder
        raise AggregateError("a non-refused DRACO Case must carry Candidate output text")
    if score is not None and not failures:
        return build_scored_case_result(
            selected_case=selected,
            output=output,
            finish_reason=finish_reason,
            grade=grade,
            execution=case_record.get("execution"),
            operations=case_record.get("operations"),
        )
    return build_failed_case_result(
        selected_case=selected,
        failures=failures,
        output=output,
        finish_reason=finish_reason,
        grade=grade,
        execution=case_record.get("execution"),
        operations=case_record.get("operations"),
    )


def _selected_case(record: Mapping[str, Any], *, id_key: str) -> SelectedCase:
    metadata = record.get("metadata")
    return SelectedCase(
        case_id=int(record[id_key]),
        input=str(record["input"]),
        metadata=dict(metadata) if isinstance(metadata, Mapping) else {},
    )


def _finish_reason(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _checks(
    case_id: int,
    rubric: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    evidence: Sequence[Mapping[str, Any]],
    criteria_expected: int,
) -> list[dict[str, Any]]:
    rubric_by_id = {str(criterion["id"]): criterion for criterion in flatten_criteria(rubric)}
    selected_ids = [str(record.get("criterion_id")) for record in records]
    if len(selected_ids) != criteria_expected or len(set(selected_ids)) != criteria_expected:
        raise AggregateError(
            f"Case {case_id} must carry exactly {criteria_expected} unique Engine-bound Checks"
        )
    try:
        selected = [rubric_by_id[criterion_id] for criterion_id in selected_ids]
    except KeyError as exc:
        raise AggregateError(
            f"Case {case_id} has an Engine-bound Check for unknown criterion {exc.args[0]!r}"
        ) from None
    by_id = {str(record.get("criterion_id")): record for record in records}
    checks: list[dict[str, Any]] = []
    for criterion in selected:
        criterion_id = str(criterion["id"])
        record = by_id.get(criterion_id)
        if record is None or optional_integer(record.get("case_id")) != case_id:
            raise AggregateError(f"Case {case_id} has no Engine-bound Check {criterion_id!r}")
        selected_evidence = [
            _evidence(item)
            for item in sorted(
                (item for item in evidence if str(item.get("criterion_id")) == criterion_id),
                key=lambda item: int(item["sequence"]),
            )
        ]
        check: dict[str, Any] = {
            "type": "criterion",
            "id": criterion_id,
            "label": record["requirement"],
            "evidence": selected_evidence,
            "metadata": {
                "criterion_type": record["criterion_type"],
                "weight": criterion["weight"],
                "axis": criterion["axis"],
            },
        }
        # Check-level verdict in the report schema's vocabulary — same contract the
        # healthbench builder documents ("without a top-level outcome the SDK renders
        # the check as unjudged"). DRACO's 5 seeded passes fold to their MAJORITY over
        # the VALID passes; no valid pass, or a tie among them (possible only when
        # invalid passes thin the odd count), leaves the check honestly outcome-less.
        outcome = _majority_outcome(selected_evidence)
        if outcome is not None:
            check["outcome"] = outcome
        checks.append(check)
    return checks


def _majority_outcome(evidence: Sequence[Mapping[str, Any]]) -> str | None:
    met = sum(1 for item in evidence if item.get("outcome") == "MET")
    unmet = sum(1 for item in evidence if item.get("outcome") == "UNMET")
    if met == unmet:
        return None
    return "MET" if met > unmet else "UNMET"


def _evidence(record: Mapping[str, Any]) -> dict[str, Any]:
    value: dict[str, Any] = {
        "sequence": int(record["sequence"]),
        "producer": {"type": record["producer_type"], "id": record["producer_id"]},
        "valid": record.get("valid") is True,
        "raw_output": record["raw_output"],
        "metadata": {},
        "accounting": record.get("accounting"),
    }
    if value["valid"]:
        value["outcome"] = record["criterion_status"]
        value["explanation"] = record["explanation"]
    else:
        value["metadata"] = {"rejection_reason": record.get("reason", "invalid")}
    return value
