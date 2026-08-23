"""The DRACO cross-row reducer — per-criterion verdicts in, Candidate Result out.

FEATURE: one url4 expression per Candidate ends in a cross-row reduce that turns every case's
judge verdicts into one scored result.
STORY: as a researcher, the number I publish is the DRACO paper's `normalized_score`.

Installed directly into each Runner world in the reducer position::

    (…iteration…)!/benchmarks/draco/<revision>/aggregate($rows)!'aggregate'

    context (row array)  →  the JSON array of every row's judge output
    intent ("aggregate") →  the fixed reduction operation

INVARIANT: the scoring formulas mirror `screamingface-benchmarks/benchmarking/graders/rubric.py`
(arXiv:2602.11685 §4.2) EXACTLY. Do not "improve" them. A different formula is a different
benchmark, and a leaderboard number computed here must mean what the paper says it means.

The expression this reducer serves runs the paper's `official` grading mode: ONE judge call per
CRITERION, five independent passes, and the judge blind to the weights and to the sibling
criteria. The Engine-owned Benchmark definition constructs that fan-out and this in-process
handler reduces the complete row collection without crossing an operating-system argv boundary.

AIDEV-NOTE: protocol caveats, the three ways a run here still differs from the paper:

* `judge_reasoning: "low"` (arXiv:2602.11685 §4.2) is NOT carried until the gateway supports it.
  `reasoning_effort` is absent from the OpenRouter plugin's rule set, and the gateway fails
  closed on an unknown parameter, so
  sending it would turn every judge call into a 400 rather than a deviation. `judge_temperature`
  and `max_tokens` DO reach the model.
* Candidate retrieval runs on the PROVIDER's search, not a backend this repo pins. Every lineup
  model is `openrouter/*`, so as of OME-797 (2026-08-12) all eight take the native mechanism,
  and OME-800 leaves the engine unset — OpenRouter picks its own built-in search where the model
  has one and Exa where it does not. So the search product can differ BETWEEN candidates of one
  run, and can change under us without a config edit.
  Before 2026-08-12 the mechanism was declared per route, and five candidates
  (`gemini-3.1-pro-preview`, `gemini-3-flash-preview`, `kimi-k2.6`, `deepseek-v4-pro`,
  `qwen3.6-plus`) answered through the runner-driven Tavily loop instead. Runs either side of
  that date are not the same experiment.
* `EXCLUDED_DOMAINS` changes MEANING with the mechanism. The Tavily loop drops blocked hosts
  client-side (`runner.web_tools._is_blocked`) — the Runner enforces it. The native path only
  forwards `web_search_excluded_domains` and relies on the provider to honour it. Since the
  blocklist covers `arxiv.org`, `paperswithcode.com`, `semanticscholar.org` and `alphaxiv.org`
  — where the paper under reproduction lives — a native-path run rests on OpenRouter's
  compliance for its leakage control, which is not verified here.

None of the three is visible in the numbers this module emits. A score published as
"DRACO-reproduced" has to state all three.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from screamingface_engine.benchmarks.aggregation import (
    CandidateScore,
    SelectedCase,
    finalize_candidate_result,
    grading_failure_case_result,
    public_error,
)
from screamingface_engine.benchmarks.case_execution_contract import (
    case_execution_matches,
    case_execution_outcome,
)
from screamingface_engine.benchmarks.contract import CaseResult
from screamingface_engine.benchmarks.draco import assets
from screamingface_engine.benchmarks.draco import case_results as case_results_module
from screamingface_engine.benchmarks.draco.case_evaluation import decode_case_evaluation
from screamingface_engine.benchmarks.draco.definition import JUDGE_PASSES, REVISION
from screamingface_engine.benchmarks.draco.errors import AggregateError as AggregateError
from screamingface_engine.benchmarks.draco.scoring import flatten_criteria as flatten_criteria
from screamingface_engine.benchmarks.draco.validation import optional_integer
from screamingface_engine.benchmarks.evaluation import CandidateAnswer

VERDICT_SCHEMA = case_results_module.VERDICT_SCHEMA
group_runs = case_results_module.group_runs
valid_verdicts = case_results_module.valid_verdicts
load_rubrics = assets.load_rubrics


@dataclass(frozen=True)
class _DecodedRow:
    """One selected Case and its exact decoded evaluation, kept together."""

    raw: Any
    expected_case: Mapping[str, Any]
    evaluation: Mapping[str, Any] | None
    candidate: CandidateAnswer | None
    grading_error: Mapping[str, object] | None
    decode_error: str | None

    @property
    def case_records(self) -> Sequence[Mapping[str, Any]]:
        return [self.evaluation["case"]] if self.evaluation is not None else []

    @property
    def checks(self) -> Sequence[Mapping[str, Any]]:
        return self.evaluation["checks"] if self.evaluation is not None else []

    @property
    def evidence(self) -> Sequence[Mapping[str, Any]]:
        return self.evaluation["evidence"] if self.evaluation is not None else []


# --- the reduction ---------------------------------------------------------------


def aggregate(
    rows_json: str,
    rubrics: Mapping[int, Mapping[str, Any]],
    benchmark_id: str,
    *,
    selected_cases: Sequence[Mapping[str, Any]],
    judge_passes: int = JUDGE_PASSES,
    benchmark_revision: str = REVISION,
) -> dict[str, Any]:
    """Reduce the row array into a Candidate Result — one row per Case.

    INVARIANT: a Case that produced no valid verdicts is never scored 0.0. Scoring it zero would
    penalise the Candidate for a harness failure, the same class of error as counting an unjudged
    criterion as UNMET. The Case instead carries no numeric grade, is excluded from the official
    reduction, and lowers the Candidate's factual top-level coverage.

    The Case-scoped failure is attached to its own Case Result. Candidate-level ``failures`` stays
    empty by design — it is reserved for failures that cannot be attributed to a selected Case.
    """
    try:
        rows = json.loads(rows_json)
    except (TypeError, ValueError) as exc:
        raise AggregateError(f"reducer payload is not JSON: {exc}") from None
    if not isinstance(rows, list):
        raise AggregateError(f"reducer payload must be a JSON array, got {type(rows).__name__}")
    if isinstance(judge_passes, bool) or not isinstance(judge_passes, int) or judge_passes < 1:
        raise AggregateError("judge_passes must be a positive integer")
    expected_cases = _validate_selected_cases(selected_cases)
    if len(rows) > len(expected_cases):
        raise AggregateError(
            f"aggregate received {len(rows)} rows for {len(expected_cases)} selected Cases"
        )
    selection = [
        SelectedCase(
            case_id=int(case["id"]),
            input=str(case["input"]),
            metadata={key: value for key, value in case.items() if key not in {"id", "input"}},
        )
        for case in expected_cases
    ]

    decoded_rows = _decode_rows(rows, expected_cases, judge_passes)
    _require_verifiable_mapping(decoded_rows)
    case_results = _aggregate_rows(decoded_rows, rubrics, judge_passes)
    return finalize_candidate_result(
        benchmark_id=benchmark_id,
        benchmark_revision=benchmark_revision,
        selected_cases=selection,
        cases=case_results,
        scorer=score_cases,
    ).as_payload()


def score_cases(cases: Sequence[CaseResult]) -> CandidateScore:
    """Apply the official DRACO cross-Case reduction to gradeable typed Cases."""

    scored = [case.model_dump() for case in cases]
    return CandidateScore(
        score=_mean_grades(scored, "score"),
        metrics={
            "normalized_score_sd": _mean_grade_metrics(scored, "normalized_score_sd"),
            "pass_rate": _mean_grade_metrics(scored, "pass_rate"),
            "pass_rate_sd": _mean_grade_metrics(scored, "pass_rate_sd"),
            "accuracy": _mean_optional_grade_metrics(scored, "accuracy"),
            "accuracy_pass_rate": _mean_optional_grade_metrics(scored, "accuracy_pass_rate"),
            "axis_scores": _mean_grade_metric_maps(scored, "axis_scores"),
            "axis_pass_rates": _mean_grade_metric_maps(scored, "axis_pass_rates"),
            "verdict_coverage": _mean_grade_metrics(scored, "coverage"),
            "verdict_coverage_sd": _mean_grade_metrics(scored, "coverage_sd"),
            "n_runs": max((_grade_metric(case, "n_runs") for case in scored), default=0),
            "verdicts_expected": _sum_grade_metrics(scored, "verdicts_expected"),
            "verdicts_accepted": _sum_grade_metrics(scored, "verdicts_accepted"),
            "verdicts_rejected": _sum_grade_metrics(scored, "verdicts_rejected"),
            "verdicts_invalid": _sum_grade_metrics(scored, "verdicts_invalid"),
            "verdicts_missing": _sum_grade_metrics(scored, "verdicts_missing"),
        },
    )


def _decode_rows(
    rows: Sequence[Any],
    expected_cases: Sequence[Mapping[str, Any]],
    judge_passes: int,
) -> list[_DecodedRow]:
    decoded: list[_DecodedRow] = []
    for raw, expected_case in zip(rows, expected_cases, strict=False):
        try:
            outcome = case_execution_outcome(raw)
            if not case_execution_matches(outcome, int(expected_case["id"])):
                raise ValueError(
                    f"Case execution claims case_id {outcome.case_id!r}, "
                    f"but the selected Case is {expected_case['id']!r}"
                )
            if outcome.error is not None:
                decoded.append(
                    _DecodedRow(
                        raw,
                        expected_case,
                        None,
                        outcome.candidate,
                        outcome.error,
                        None,
                    )
                )
                continue
            evaluation = decode_case_evaluation(
                outcome.grading,
                int(expected_case["id"]),
                judge_passes=judge_passes,
            )
        except (TypeError, ValueError) as exc:
            evaluation = None
            candidate = None
            error = str(exc)
        else:
            candidate = outcome.candidate
            error = None
        decoded.append(_DecodedRow(raw, expected_case, evaluation, candidate, None, error))
    return decoded


def _aggregate_rows(
    decoded_rows: Sequence[_DecodedRow],
    rubrics: Mapping[int, Mapping[str, Any]],
    judge_passes: int,
) -> list[CaseResult]:
    return [
        _grade_decoded_case(row, rubrics, judge_passes, row_index=index)
        for index, row in enumerate(decoded_rows)
    ]


def grade_case(
    raw: object,
    expected_case: Mapping[str, Any],
    rubric: Mapping[str, Any],
    *,
    judge_passes: int,
) -> CaseResult:
    """Project one exact DRACO Case with the same rules used by final aggregation."""

    selected = _validate_selected_cases([expected_case])
    decoded = _decode_rows([raw], selected, judge_passes)
    _require_verifiable_mapping(decoded)
    return _grade_decoded_case(decoded[0], {int(expected_case["id"]): rubric}, judge_passes)


def _grade_decoded_case(
    row: _DecodedRow,
    rubrics: Mapping[int, Mapping[str, Any]],
    judge_passes: int,
    *,
    row_index: int = 0,
) -> CaseResult:
    if row.grading_error is not None and row.candidate is not None:
        result = grading_failure_case_result(
            selected_case=_selected_case(row.expected_case),
            candidate=row.candidate,
            error=row.grading_error,
            method="rubric",
            default_code="draco_grading_failed",
            default_message="the DRACO grader could not grade this Case",
        )
    elif not row.case_records:
        failure = _row_failure(row.raw, row_index, row.expected_case, row.decode_error)
        result = case_results_module.failed_selected_case_result(row.expected_case, failure)
    else:
        result = _grade_evaluation(row, rubrics, judge_passes, row_index)
    return result


def _grade_evaluation(
    row: _DecodedRow,
    rubrics: Mapping[int, Mapping[str, Any]],
    judge_passes: int,
    row_index: int,
) -> CaseResult:
    case_record = row.case_records[0]
    case_id = optional_integer(case_record.get("case_id"))
    if case_id is None:  # pragma: no cover - sealed by _require_verifiable_mapping
        raise AssertionError("a scored DRACO row must carry its Engine-bound case_id")
    rubric = rubrics.get(case_id)
    if rubric is None:
        failure = {
            "stage": "grading",
            "code": "missing_case_rubric",
            "message": "the selected Case has no installed DRACO rubric",
            "retryable": None,
            "case_id": case_id,
            "metadata": {"row_index": row_index},
        }
        result = case_results_module.ungraded_case_result(case_record, failure)
    else:
        verdicts = case_results_module.valid_verdicts(rubric, row.evidence, case_id)
        result = (
            case_results_module.scored_case_result(
                case_record,
                rubric,
                row.checks,
                row.evidence,
                verdicts,
                judge_passes,
            )
            if verdicts
            else case_results_module.incomplete_case_result(
                case_record,
                rubric,
                row.checks,
                row.evidence,
                judge_passes,
                {
                    "stage": "grading",
                    "code": "no_valid_judge_verdict",
                    "message": "no valid Judge verdict was produced for this Case",
                    "retryable": None,
                    "case_id": case_id,
                    "metadata": {"row_index": row_index},
                },
            )
        )
    return result


def _row_failure(
    row: Any,
    index: int,
    expected_case: Mapping[str, Any],
    decode_error: str | None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "row_index": index,
        **({"reason": " ".join(decode_error.split())[:200]} if decode_error else {}),
    }
    failure: dict[str, Any] = {
        "stage": "grading",
        "code": "invalid_case_evaluation",
        "message": "the Case produced no valid DRACO Case Evaluation",
        "retryable": None,
        "case_id": int(expected_case["id"]),
        "metadata": metadata,
    }
    error = row.get("error") if isinstance(row, Mapping) else None
    if not isinstance(error, Mapping):
        return failure
    metadata.clear()
    metadata["row_index"] = index
    diagnostic = public_error(
        error,
        default_code="case_execution_failed",
        default_message="Candidate Case execution failed",
    )
    failure.update(
        {
            "stage": "candidate",
            "code": diagnostic.code,
            "message": diagnostic.message,
            "retryable": diagnostic.retryable,
        }
    )
    if diagnostic.kind is not None:
        metadata["error_kind"] = diagnostic.kind
    return failure


def _require_verifiable_mapping(rows: Sequence[_DecodedRow]) -> None:
    """Require one unique Engine-bound Case identity for every scoreable row."""

    claimed: dict[int, int] = {}
    for index, row in enumerate(rows):
        case_id = _verified_row_case_id(row, index)
        if case_id is None:
            continue
        previous = claimed.get(case_id)
        if previous is not None:
            raise AggregateError(
                f"duplicate case_id {case_id} appears at Case result positions "
                f"{previous} and {index}"
            )
        expected_id = int(row.expected_case["id"])
        if case_id != expected_id:
            raise AggregateError(
                f"Case result at position {index} claims case_id {case_id}, "
                f"but the selected Case is {expected_id}"
            )
        claimed[case_id] = index


def _verified_row_case_id(row: _DecodedRow, index: int) -> int | None:
    if row.evaluation is None:
        if row.grading_error is not None and row.candidate is not None:
            return None
        error = row.raw.get("error") if isinstance(row.raw, Mapping) else None
        if isinstance(error, Mapping):
            return None
        detail = f": {row.decode_error}" if row.decode_error else ""
        raise AggregateError(
            f"Case result at position {index} is not a valid DRACO Case Evaluation{detail}"
        )
    case_records = row.case_records
    if len(case_records) != 1:  # pragma: no cover - exact decoder seals this
        raise AggregateError(
            f"Case result at position {index} must carry exactly one Engine-bound Case record; "
            f"found {len(case_records)}"
        )
    records = (*case_records, *row.checks, *row.evidence)
    identities = [optional_integer(record.get("case_id")) for record in records]
    if any(case_id is None for case_id in identities):
        raise AggregateError(
            f"Case result at position {index} has a verdict without an Engine-bound case_id"
        )
    unique = {case_id for case_id in identities if case_id is not None}
    if len(unique) != 1:
        raise AggregateError(
            f"Case result at position {index} carries multiple case_id values {sorted(unique)}"
        )
    return unique.pop()


def _selected_case(case: Mapping[str, Any]) -> SelectedCase:
    return SelectedCase(
        case_id=int(case["id"]),
        input=str(case["input"]),
        metadata={key: value for key, value in case.items() if key not in {"id", "input"}},
    )


def _validate_selected_cases(
    selected_cases: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    expected = list(selected_cases)
    if not expected:
        raise AggregateError("selected Case sequence must be non-empty")
    ids: set[int] = set()
    for index, case in enumerate(expected):
        case_id = optional_integer(case.get("id")) if isinstance(case, Mapping) else None
        input_value = case.get("input") if isinstance(case, Mapping) else None
        if case_id is None or case_id < 1 or not isinstance(input_value, str) or not input_value:
            raise AggregateError(f"selected Case {index} must carry a positive id and input text")
        if case_id in ids:
            raise AggregateError(f"selected Case sequence repeats case_id {case_id}")
        ids.add(case_id)
    return expected


def _grade(case: Mapping[str, Any]) -> Mapping[str, Any]:
    grade = case.get("grade")
    if not isinstance(grade, Mapping):  # pragma: no cover - selected by caller
        raise AssertionError("scored Case must carry a Case Grade")
    return grade


def _grade_metric(case: Mapping[str, Any], key: str) -> Any:
    metrics = _grade(case).get("metrics")
    if not isinstance(metrics, Mapping):  # pragma: no cover - constructed locally
        raise AssertionError("Case Grade must carry metrics")
    return metrics[key]


def _mean_grades(cases: Sequence[Mapping[str, Any]], key: str) -> float:
    return round(sum(float(_grade(case)[key]) for case in cases) / len(cases), 4)


def _mean_grade_metrics(cases: Sequence[Mapping[str, Any]], key: str) -> float:
    return round(sum(float(_grade_metric(case, key)) for case in cases) / len(cases), 4)


def _mean_optional_grade_metrics(cases: Sequence[Mapping[str, Any]], key: str) -> float | None:
    """Mean over the Cases that reported ``key``, or ``None`` when none of them did.

    A Case whose rubric has no Factual Accuracy axis reports ``None`` rather than 0.0, so it must
    be skipped instead of dragging the Candidate mean toward zero. This mirrors how
    :func:`_mean_grade_metric_maps` averages each axis over the Cases that carry it.
    """
    values = [
        float(value)
        for case in cases
        if (value := _grade_metric(case, key)) is not None and not isinstance(value, bool)
    ]
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _sum_grade_metrics(cases: Sequence[Mapping[str, Any]], key: str) -> int:
    return sum(int(_grade_metric(case, key)) for case in cases)


def _mean_grade_metric_maps(cases: Sequence[Mapping[str, Any]], key: str) -> dict[str, float]:
    values: dict[str, list[float]] = {}
    for case in cases:
        metric = _grade_metric(case, key)
        if not isinstance(metric, Mapping):  # pragma: no cover - constructed locally
            raise AssertionError(f"Case Grade metric {key!r} must be an object")
        for name, value in metric.items():
            values.setdefault(str(name), []).append(float(value))
    return {name: round(sum(items) / len(items), 4) for name, items in sorted(values.items())}
