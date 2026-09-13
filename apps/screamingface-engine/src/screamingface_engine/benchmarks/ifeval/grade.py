"""IFEval's grading hooks — everything this board still writes to be graded.

The spine owns the marking room (``spine/scored.py``); this module is the board's
contribution: its deterministic ``grade_case`` (the vendored checkers' verdict vectors
turned into one grade), its published accuracy scorer, its selection order, and its
failure wording. The engine ships mechanisms; a benchmark ships semantics.

FEATURE: one grading spine per benchmark (OME-1024); this fold (OME-1101) is the
``deterministic`` kind's first consumer — the proof the spine is not rubric-shaped.
STORY: as a researcher, the number I publish is the IFEval paper's prompt-level strict
accuracy (arXiv:2311.07911).

INVARIANT: only connector-owned diagnostics establish Candidate provenance for an
anonymous collected row (OME-981). Ambiguous rows retain the grading fallback;
protected checker failures retain the shared spine's explicit grading boundary.

INVARIANT: malformed or mismatched verifier envelopes abort the run (the RowReader
wraps this module's decode ``ValueError`` with the row position) — their identity
cannot be trusted, and scoring the wrong Case is worse than reporting a failed one.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from screamingface_engine.benchmarks.aggregation import (
    CandidateScore,
    SelectedCase,
    failed_case_result,
    public_error,
)
from screamingface_engine.benchmarks.contract import CaseResult, Failure
from screamingface_engine.benchmarks.ifeval.case_evaluation import CHECK_SCHEMA, graded_record
from screamingface_engine.benchmarks.ifeval.definition import REVISION as IFEVAL_REVISION
from screamingface_engine.benchmarks.spine.rows import RowReader
from screamingface_engine.benchmarks.spine.scored import (
    CaseGradeOutcome,
    GradeRequest,
    ScoredPath,
)

SCHEMA = CHECK_SCHEMA

# WHY the rubric-vocabulary keys: the ladder rungs are spine-fixed names. Neither can
# fire for IFEval — selection aborts on a missing spec before any grading, and this
# board's collected rows are anonymous (the missing-row hook owns them) — but the
# table must answer for every rung the spine could look up.
_FAILURE_MESSAGES = {
    "missing_rubric_asset": "the installed instruction spec for this Case is missing",
    "missing_case_row": "no evaluation row for this Case reached the aggregate",
    "case_error": "the Case pipeline collected an error instead of an evaluation",
}


class AggregateError(ValueError):
    """The reducer's input is unusable — raised before any scoring."""


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


def aggregate(
    rows_json: str,
    specs: Mapping[int, Mapping[str, Any]],
    benchmark_id: str,
    case_order: Sequence[int],
    *,
    selected_case_count: int,
) -> dict[str, Any]:
    """Score every selected Case on the shared scored path, with this board's hooks.

    ``case_order`` is the installed selection order (``load_case_order``): case ids
    are official IFEval keys, which are NOT sorted in case order, so the mapping from
    collected row position to case id must come from ``cases.json`` — never from
    ``sorted(specs)`` or ``index + 1``.
    """

    selected = _selected_cases(specs, case_order, selected_case_count)
    path = ScoredPath(
        reader=RowReader(
            benchmark_label="IFEval",
            error_type=AggregateError,
            decode_case_evaluation=_decode(specs),
        ),
        grade_case=_grade_case,
        failure_messages=_FAILURE_MESSAGES,
        method="deterministic",
        grading_failure_code="ifeval_checker_failed",
        grading_failure_message="the IFEval checker could not grade this Case",
        missing_row_result=_missing_row_result,
    )
    return path.aggregate(
        rows_json,
        benchmark_id=benchmark_id,
        benchmark_revision=IFEVAL_REVISION,
        selected_cases=selected,
        # The spec is verified present for every selected Case before any grading,
        # so the spine's missing-material rung is unreachable on this board.
        grading_material=lambda case_id: specs.get(case_id),
        scorer=_ifeval_score,
    )


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


def _decode(specs: Mapping[int, Mapping[str, Any]]) -> Callable[[object, int], dict[str, Any]]:
    """Bind the private specs into the board's row decoder for the spine's RowReader.

    Returns the row the spine files: the authentic verifier record under ``record``
    plus a hoisted ``case`` mapping (the spine reads the candidate's half of the row
    there). Raises ``ValueError`` on any untrustworthy envelope — the RowReader turns
    that into this board's abort with the row position attached.
    """

    def decode(grading: object, expected_case_id: int) -> dict[str, Any]:
        record = graded_record(grading, expected_case_id, _instruction_ids(specs[expected_case_id]))
        # The verifier record IS the candidate outcome for this board (one row spans
        # invocation and checking); hoist it into the spine's candidate-field shape.
        return {
            "case": {
                "status": record["status"],
                "output": str(record["answer"]),
                "finish_reason": record["finish_reason"],
                "refusal": record.get("refusal"),
                "execution": record["execution"],
                "operations": record.get("operations"),
                "metadata": {},
            },
            "record": record,
        }

    return decode


async def _grade_case(request: GradeRequest) -> CaseGradeOutcome:
    """Turn one authentic verifier record's bool vectors into the published grade.

    Pure and infallible by construction: every trust decision already happened in
    ``_decode`` (an invalid record aborted the run), so this hook only projects
    strict/loose verdicts into the report schema's checks and metrics.
    """

    record = request.row["record"]
    strict = [bool(value) for value in record["strict"]]
    loose = [bool(value) for value in record["loose"]]
    descriptions = record["descriptions"]
    assert isinstance(descriptions, list)
    checks = [
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
    ]
    return CaseGradeOutcome(
        score=float(all(strict)),
        metrics={
            "follow_all_strict": all(strict),
            "follow_all_loose": all(loose),
            "strict_checks_passed": sum(strict),
            "loose_checks_passed": sum(loose),
        },
        checks=checks,
    )


def _missing_row_result(
    selected_case: SelectedCase,
    selected_index: int,
    orphan_errors: list[dict[str, Any]] | None,
) -> CaseResult:
    """This board's shape for a selected Case with no usable row — wording pinned.

    A collected error row retains the diagnostic and row index, attributing known
    Gateway-call failures to Candidate execution (OME-981); a Case
    with no row at all keeps the pre-fold ``case_result_missing`` synthesis.
    """

    if orphan_errors:
        # INVARIANT: selected_index IS the row position — rows.py enforces
        # position-is-identity (a row claiming another Case aborts the run), so the
        # golden-pinned ``row_index`` metadata can be rebuilt from the roll call.
        return _collected_failure_result(selected_case, selected_index, orphan_errors[0])
    return CaseResult(
        status="failed",
        case_id=selected_case.case_id,
        input=selected_case.input,
        output=None,
        finish_reason=None,
        refusal=None,
        grade=None,
        failures=[
            Failure(
                stage="aggregation",
                code="case_result_missing",
                message="the selected Case produced no Case Result",
                retryable=None,
                case_id=selected_case.case_id,
                metadata={},
            )
        ],
        metadata=selected_case.metadata,
    )


def _collected_failure_result(
    selected_case: SelectedCase,
    row_index: int,
    row: Mapping[str, Any],
) -> CaseResult:
    """Retain one selected Case whose Candidate Invocation or Grading failed."""

    error = row.get("error")
    assert isinstance(error, Mapping)  # the spine only orphans rows carrying an error
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
                "stage": "candidate" if _is_gateway_call_failure(error) else "grading",
                "code": diagnostic.code,
                "message": diagnostic.message,
                "retryable": diagnostic.retryable,
                "case_id": selected_case.case_id,
                "metadata": metadata,
            }
        ],
    )


def _is_gateway_call_failure(error: Mapping[str, Any]) -> bool:
    # WHY: these codes are emitted by runner/connector.py at the model-call boundary.
    # IFEval's checker is deterministic; its protected failures never take this path.
    # Do not infer provenance from a message, a broad prefix, or a sanitized code:
    # unknown and legacy kind/message-only rows remain the grading fallback.
    code = error.get("code")
    return isinstance(code, str) and (
        code in {"aigateway_transport_error", "aigateway_empty_response", "aigateway_bad_response"}
        or re.fullmatch(r"aigateway_http_[45][0-9]{2}", code) is not None
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
