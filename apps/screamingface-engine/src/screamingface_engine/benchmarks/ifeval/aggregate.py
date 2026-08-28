"""The IFEval cross-row reducer — check records in, `CandidateResult` out.

FEATURE: one url4 expression per Candidate ends in a cross-row reduce that turns every
case's deterministic check into one scored result.
STORY: as a researcher, the number I publish is the IFEval paper's prompt-level strict
accuracy (arXiv:2311.07911).

INVARIANT: `case_count` is EXACT (one entry per selected Case) and every scored Case has a
real verifier record. A collected or missing operational result is retained without a grade
and lowers top-level coverage; valid deterministic grades still publish their official score.
Malformed or mismatched verifier envelopes abort because their identity cannot be trusted.
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
from screamingface_engine.benchmarks.case_execution import (
    case_execution_matches,
    case_execution_outcome,
)
from screamingface_engine.benchmarks.contract import CaseResult, is_valid_corrective_execution
from screamingface_engine.benchmarks.ifeval.case_evaluation import (
    CHECK_SCHEMA,
    decode_case_evaluation,
)
from screamingface_engine.benchmarks.ifeval.definition import REVISION as IFEVAL_REVISION

SCHEMA = CHECK_SCHEMA


class AggregateError(ValueError):
    """The reducer's input is unusable — raised before any scoring."""


def aggregate(
    rows_json: str,
    specs: Mapping[int, Mapping[str, Any]],
    benchmark_id: str,
    case_order: Sequence[int],
    *,
    selected_case_count: int,
) -> dict[str, Any]:
    """Reduce the row array into a `CandidateResult` — exactly one entry per row.

    ``case_order`` is the installed selection order (``load_case_order``): case ids
    are official IFEval keys, which are NOT sorted in case order, so the mapping from
    collected row position to case id must come from ``cases.json`` — never from
    ``sorted(specs)`` or ``index + 1``.
    """

    rows = _rows(rows_json)
    selected = _selected_cases(specs, case_order, selected_case_count)
    _reject_surplus_rows(rows, selected)
    case_results: list[CaseResult] = []
    for index, raw in enumerate(rows):
        selected_case = selected[index]
        case_id = int(selected_case.case_id)
        spec = specs[case_id]
        if _collected_error(raw) is not None:
            case_results.append(_failed_case_result(raw, index, selected_case))
            continue
        try:
            outcome = case_execution_outcome(raw)
        except (TypeError, ValueError) as exc:
            raise AggregateError(
                f"Case result at position {index} is not a valid Case execution: {exc}"
            ) from None
        if not case_execution_matches(outcome, selected_case.case_id):
            raise AggregateError(
                f"Case result at position {index} claims case_id {outcome.case_id!r}, "
                f"but the selected Case is {selected_case.case_id!r}"
            )
        if outcome.error is not None:
            case_results.append(
                grading_failure_case_result(
                    selected_case=selected_case,
                    candidate=outcome.candidate,
                    error=outcome.error,
                    method="deterministic",
                    default_code="ifeval_checker_failed",
                    default_message="the IFEval checker could not grade this Case",
                )
            )
            continue
        record = _first_valid_record(outcome.grading, case_id, spec)
        if record is None:
            raise AggregateError(
                f"Case result at position {index} is not a valid IFEval Case Evaluation"
            )
        case_results.append(_case_result(selected_case, record))
    return finalize_candidate_result(
        benchmark_id=benchmark_id,
        benchmark_revision=IFEVAL_REVISION,
        selected_cases=selected,
        cases=case_results,
        scorer=_ifeval_score,
    ).as_payload()


def _failed_case_result(
    row: Any,
    row_index: int,
    selected_case: SelectedCase,
) -> CaseResult:
    """Retain one selected Case whose Candidate Invocation or Grading failed."""

    error = _collected_error(row)
    if error is None:  # pragma: no cover - guarded by both aggregate entry points
        raise AssertionError("failed IFEval rows must carry a collected error")
    diagnostic = public_error(
        error,
        default_code="invalid_case_evaluation",
        default_message="the Case produced no valid IFEval evaluation record",
    )
    metadata: dict[str, Any] = {"row_index": row_index}
    if diagnostic.kind is not None:
        metadata["error_kind"] = diagnostic.kind
    return failed_case_result(
        selected_case=selected_case,
        failures=[
            {
                # WHY the constant stage: a collected url4 error row carries only
                # kind+message — never a code — so public_error always falls back to
                # the aggregate defaults and the old provider_/aigateway_ prefix
                # heuristic could not fire. One IFEval row spans invocation AND
                # checking, so "grading" (the stage that failed to produce a valid
                # evaluation record) is the honest constant.
                "stage": "grading",
                "code": diagnostic.code,
                "message": diagnostic.message,
                "retryable": diagnostic.retryable,
                "case_id": selected_case.case_id,
                "metadata": metadata,
            }
        ],
    )


def _reject_surplus_rows(rows: Sequence[Any], selected: Sequence[SelectedCase]) -> None:
    if len(rows) > len(selected):
        raise AggregateError(
            f"aggregate received {len(rows)} rows for {len(selected)} selected Cases"
        )


def _collected_error(row: object) -> Mapping[str, Any] | None:
    error = row.get("error") if isinstance(row, Mapping) else None
    return error if isinstance(error, Mapping) else None


def load_specs(directory: Path) -> dict[int, dict[str, Any]]:
    """Load ``<directory>/<case_id>.json`` for every private instruction spec on disk.

    INVARIANT: an absent or empty directory RAISES — draco's load_rubrics lesson. A
    misconfigured assets path must fail loudly, never reach a client as a terminated
    run carrying a plausible zero.
    """

    specs: dict[int, dict[str, Any]] = {}
    for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
        case_id = _as_int(path.stem)
        if case_id is not None:
            specs[case_id] = json.loads(path.read_text(encoding="utf-8"))
    if not specs:
        raise AggregateError(
            f"no instruction specs under {str(directory)!r}; "
            "the installed IFEval assets are incomplete"
        )
    return specs


def load_case_order(root: Path) -> list[int]:
    """The installed selection order — ``cases.json``'s ids, in file order.

    Case ids are official IFEval keys, which are NOT sorted in case order, so this
    file is the only source of "which case is collected row N". Same fail-loud rule
    as ``load_specs``: a missing or malformed ``cases.json`` raises before any
    scoring.
    """

    path = root / "cases.json"
    if not path.is_file():
        raise AggregateError(
            f"no cases.json under {str(root)!r}; the installed IFEval assets are incomplete"
        )
    try:
        cases = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AggregateError(f"cases.json is not JSON: {exc}") from None
    if not isinstance(cases, list) or not cases:
        raise AggregateError("cases.json must be a non-empty JSON array")
    order: list[int] = []
    for entry in cases:
        case_id = _as_int(entry.get("id")) if isinstance(entry, Mapping) else None
        if case_id is None:
            raise AggregateError(f"cases.json entry without an int id: {entry!r}")
        order.append(case_id)
    if len(set(order)) != len(order):
        raise AggregateError("cases.json carries duplicate case ids")
    return order


def _rows(rows_json: str) -> list[Any]:
    try:
        rows = json.loads(rows_json)
    except (TypeError, ValueError) as exc:
        raise AggregateError(f"reducer payload is not JSON: {exc}") from None
    if not isinstance(rows, list):
        raise AggregateError(f"reducer payload must be a JSON array, got {type(rows).__name__}")
    return rows


def _selected_cases(
    specs: Mapping[int, Mapping[str, Any]],
    case_order: Sequence[int],
    selected_case_count: int,
) -> list[SelectedCase]:
    """The exact installed Case prefix authored into the Benchmark URL4.

    The slice walks ``cases.json`` in file order. Ids are official keys — sorting
    them would grade rows against the wrong specs.
    """

    if (
        isinstance(selected_case_count, bool)
        or not isinstance(selected_case_count, int)
        or selected_case_count < 1
        or selected_case_count > len(case_order)
    ):
        raise AggregateError(f"selected_case_count must be between 1 and {len(case_order)}")
    selected = list(case_order[:selected_case_count])
    missing = [case_id for case_id in selected if case_id not in specs]
    if missing:
        raise AggregateError(
            f"cases.json selects case ids {missing} that have no installed instruction "
            "spec; the installed IFEval assets are incomplete"
        )
    return [
        SelectedCase(case_id=case_id, input=str(specs[case_id]["prompt"]), metadata={})
        for case_id in selected
    ]


def _first_valid_record(
    row: Any,
    expected_case_id: int,
    spec: Mapping[str, Any],
) -> dict[str, Any] | None:
    expected_ids = list(_instruction_ids(spec))
    records = decode_case_evaluation(row, expected_case_id)
    if records is None or len(records) != 1:
        return None
    record = records[0]
    strict = record.get("strict")
    loose = record.get("loose")
    if (
        record.get("schema") == SCHEMA
        and record.get("valid") is True
        # INVARIANT: an authentic record for ANOTHER known Case is still not this row's
        # grade. The private instruction vector binds the record to the same Case too.
        and _as_int(record.get("case_id")) == expected_case_id
        and record.get("instruction_id_list") == expected_ids
        and _is_bool_vector(strict, len(expected_ids))
        and _is_bool_vector(loose, len(expected_ids))
        and _record_content(record, len(expected_ids))
    ):
        return record
    return None


def _is_bool_vector(value: object, expected_length: int) -> bool:
    """True only for the exact vector type emitted by deterministic verification."""

    return (
        isinstance(value, list)
        and len(value) == expected_length
        and all(type(item) is bool for item in value)
    )


def _record_content(record: Mapping[str, Any], instruction_count: int) -> bool:
    status = record.get("status")
    refusal = record.get("refusal")
    answer = record.get("answer")
    return (
        isinstance(answer, str)
        and status in {"completed", "refused"}
        and "refusal" in record
        and (refusal is None or isinstance(refusal, str) and bool(refusal.strip()))
        and (
            status == "completed"
            and refusal is None
            or status == "refused"
            and answer == (refusal or "")
        )
        and "finish_reason" in record
        and (
            record["finish_reason"] is None
            or isinstance(record["finish_reason"], str)
            and bool(record["finish_reason"].strip())
        )
        and "execution" in record
        and is_valid_corrective_execution(record["execution"])
        and isinstance(record.get("descriptions"), list)
        and len(record["descriptions"]) == instruction_count
        and all(isinstance(value, str) and value for value in record["descriptions"])
        and isinstance(record.get("violations"), list)
        and all(isinstance(value, str) for value in record["violations"])
    )


def _case_result(selected_case: SelectedCase, record: Mapping[str, Any]) -> CaseResult:
    strict = [bool(value) for value in record["strict"]]
    loose = [bool(value) for value in record["loose"]]
    descriptions = record["descriptions"]
    assert isinstance(descriptions, list)
    grade = {
        "method": "deterministic",
        "score": float(all(strict)),
        "metrics": {
            "follow_all_strict": all(strict),
            "follow_all_loose": all(loose),
            "strict_checks_passed": sum(strict),
            "loose_checks_passed": sum(loose),
        },
        "checks": [
            {
                "type": "instruction",
                "id": f"instruction-{index}",
                "label": descriptions[index - 1],
                # Check-level verdict in the report schema's vocabulary; the strict
                # verifier decides it, matching the headline score. Without it a
                # reader must dig into evidence, and the SDK renders the check as
                # unjudged.
                "outcome": "MET" if strict[index - 1] else "UNMET",
                "evidence": [
                    _verification_evidence(1, "strict", strict[index - 1]),
                    _verification_evidence(2, "loose", loose[index - 1]),
                ],
                "metadata": {"instruction_index": index},
            }
            for index in range(1, len(strict) + 1)
        ],
    }
    refusal = record.get("refusal")
    if record.get("status") == "refused":
        return refused_case_result(
            selected_case=selected_case,
            refusal=refusal if isinstance(refusal, str) else None,
            finish_reason=record["finish_reason"],
            grade=grade,
            execution=record["execution"],
            operations=record.get("operations"),
        )
    return scored_case_result(
        selected_case=selected_case,
        output=str(record["answer"]),
        finish_reason=record["finish_reason"],
        grade=grade,
        execution=record["execution"],
        operations=record.get("operations"),
    )


def _ifeval_score(cases: Sequence[CaseResult]) -> CandidateScore:
    """Apply IFEval's published accuracy formulas to gradeable typed Cases."""

    grades = [case.grade for case in cases]
    if any(grade is None or grade.score is None for grade in grades):  # pragma: no cover
        raise AssertionError("IFEval scorer requires complete graded Cases")
    typed_grades = [grade for grade in grades if grade is not None]
    strict_all = [grade.score == 1.0 for grade in typed_grades]
    loose_all = [grade.metrics.get("follow_all_loose") is True for grade in typed_grades]
    strict_flat = [check.outcome == "MET" for grade in typed_grades for check in grade.checks]
    loose_flat = [
        evidence.outcome == "PASS"
        for grade in typed_grades
        for check in grade.checks
        for evidence in check.evidence
        if evidence.metadata.get("mode") == "loose"
    ]
    inst_level_strict = _accuracy(strict_flat)
    metrics: dict[str, Any] = {
        "inst_level_strict_accuracy": inst_level_strict,
        "prompt_level_loose_accuracy": _accuracy(loose_all),
        "inst_level_loose_accuracy": _accuracy(loose_flat),
        "pass_rate": inst_level_strict,
    }
    return CandidateScore(score=_accuracy(strict_all), metrics=metrics)


def _verification_evidence(sequence: int, mode: str, passed: bool) -> dict[str, Any]:
    return {
        "sequence": sequence,
        "producer": {"type": "deterministic", "id": "ifeval/official-verifier"},
        "valid": True,
        "outcome": "PASS" if passed else "FAIL",
        "raw_output": passed,
        "metadata": {"mode": mode},
        "accounting": None,
    }


def _instruction_ids(spec: Mapping[str, Any]) -> Sequence[str]:
    ids = spec.get("instruction_id_list")
    if not isinstance(ids, list) or not ids:
        raise AggregateError("an instruction spec is missing its instruction_id_list")
    return ids


def _accuracy(values: Sequence[bool]) -> float:
    return round(sum(1 for value in values if value) / len(values), 4) if values else 0.0


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "SCHEMA",
    "AggregateError",
    "aggregate",
    "load_case_order",
    "load_specs",
]
