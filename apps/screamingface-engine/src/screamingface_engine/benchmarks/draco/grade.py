"""DRACO's grading hooks — everything the multi-pass boards still write to be graded.

The spine owns the marking room (``spine/scored.py``); this module is the board's
contribution: its multi-pass ``grade_case`` (N seeded judge verdicts per criterion
reduced to one grade), its published cross-Case scorer, its selection validation,
and its failure shapes. The engine ships mechanisms; a benchmark ships semantics.

FEATURE: one grading spine per benchmark (OME-1024); this fold (OME-1100) is the
first board with a genuinely different GRADING shape (N judge passes per criterion)
on the shared hook — the proof the hook is not single-pass-shaped.
STORY: as a researcher, the number I publish is the DRACO paper's
``normalized_score`` (arXiv:2602.11685 §4.2).

The stages, in execution order (one aggregate call = marking one board's exam):

    Stage 1  selection validation      → non-empty, unique positive ids, input text
    Stage 2  row filing (spine)        → RowReader + the exact envelope decoder;
             draco CLAIMS anonymous error rows — position is identity here
    Stage 3  the ladder (spine)        → draco's board-owned failure shapes ride the
             four result hooks below; the spine's default rungs never fire
    Stage 4  grade_case (this module)  → valid verdicts per rubric → score_case over
             the passes, or the incomplete grade when nothing was scoreable
    Stage 5  the scorer (this module)  → the official cross-Case reduction

INVARIANT: failure output is byte-identical to the pre-fold ``draco/aggregate.py``,
with ONE owner-approved delta: an error row's Case now carries the selected Case's
own metadata (the cases.json extras, e.g. ``domain``) where pre-fold published
``{}`` — error rows were the only Case shape dropping it (pinned in
``test_draco_failure_integrity.py::test_an_error_row_case_carries_the_selected_cases_own_metadata``).
The seven e2e failure tapes pin an error row's UPSTREAM code ("rate_limited",
"provider_error") on a candidate-stage, grade-less failure; a missing row lands as
the finalizer's ``case_result_missing``; a missing rubric is ``missing_case_rubric``
with a ``row_index``; an unscoreable Case is ``no_valid_judge_verdict`` carrying its
full zeroed metric block as audit material. The draco-3pass golden pins the scored
path (100 cases, score 0.3593).

INVARIANT: a Case that produced no valid verdicts is never scored 0.0. Scoring it
zero would penalise the Candidate for a harness failure, the same class of error as
counting an unjudged criterion as UNMET. The Case instead carries no numeric grade,
is excluded from the official reduction, and lowers the Candidate's factual
top-level coverage.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from screamingface_engine.benchmarks.aggregation import (
    CandidateScore,
    SelectedCase,
    failed_case_result,
    public_error,
)
from screamingface_engine.benchmarks.contract import CaseResult
from screamingface_engine.benchmarks.draco import case_results
from screamingface_engine.benchmarks.draco.case_evaluation import decode_case_evaluation
from screamingface_engine.benchmarks.draco.definition import JUDGE_PASSES, REVISION
from screamingface_engine.benchmarks.draco.errors import AggregateError
from screamingface_engine.benchmarks.draco.validation import optional_integer
from screamingface_engine.benchmarks.spine.rows import RowReader
from screamingface_engine.benchmarks.spine.scored import (
    CaseGradeOutcome,
    GradeCase,
    GradeRequest,
    ScoredPath,
)

# WHY the table exists at all: every default rung of the spine's ladder is replaced
# by a board-owned result hook below, so the spine never looks a draco code up —
# but the field is required, and the table documents which rungs draco owns.
_FAILURE_MESSAGES: dict[str, str] = {
    "missing_rubric_asset": "the selected Case has no installed DRACO rubric",
    "missing_case_row": "no evaluation row for this Case reached the aggregate",
    "case_error": "the Case pipeline collected an error instead of an evaluation",
}


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

    Args:
        rows_json: the collected array of Case execution rows, in selected order.
        rubrics: case_id → the installed private rubric (the grading material).
        benchmark_id: the board publishing this result ("draco" / "draco-3pass").
        selected_cases: the raw selected-case mappings from the baked ``cases.json``
            prefix — every field beyond id/input rides the result as Case metadata.
        judge_passes: this board's evidence cardinality (5-pass vs 3-pass).
        benchmark_revision: the board's revision, stamped into the result.

    The Case-scoped failure is attached to its own Case Result. Candidate-level
    ``failures`` stays empty by design — it is reserved for failures that cannot be
    attributed to a selected Case.
    """
    if isinstance(judge_passes, bool) or not isinstance(judge_passes, int) or judge_passes < 1:
        raise AggregateError("judge_passes must be a positive integer")
    expected: list[Mapping[str, Any]] = _validate_selected_cases(selected_cases)
    selection: list[SelectedCase] = [
        SelectedCase(
            case_id=int(case["id"]),
            input=str(case["input"]),
            metadata={key: value for key, value in case.items() if key not in {"id", "input"}},
        )
        for case in expected
    ]
    path = ScoredPath(
        reader=RowReader(
            benchmark_label="DRACO",
            error_type=AggregateError,
            decode_case_evaluation=_decode(judge_passes),
            # Position is identity: an anonymous error row IS that Case's row here.
            claim_anonymous_errors=True,
        ),
        grade_case=_grade_case(judge_passes),
        failure_messages=_FAILURE_MESSAGES,
        method="rubric",
        grading_failure_code="draco_grading_failed",
        grading_failure_message="the DRACO grader could not grade this Case",
        # A missing row files NOTHING — the finalizer reports case_result_missing,
        # exactly the shape the pre-fold zip produced by dropping the Case.
        missing_row_result=lambda selected, index, orphans: None,
        error_row_result=_error_row_result,
        missing_material_result=_missing_material_result,
        hook_failure_result=_hook_failure_result,
    )
    return path.aggregate(
        rows_json,
        benchmark_id=benchmark_id,
        benchmark_revision=benchmark_revision,
        selected_cases=selection,
        grading_material=lambda case_id: rubrics.get(case_id),
        scorer=draco_scorer,
    )


def _decode(judge_passes: int) -> Callable[[object, int], dict[str, Any]]:
    """Bind this board's evidence cardinality into the exact envelope decoder."""

    def decode(grading: object, expected_case_id: int) -> dict[str, Any]:
        return decode_case_evaluation(grading, expected_case_id, judge_passes=judge_passes)

    return decode


def _grade_case(judge_passes: int) -> GradeCase:
    """Build the multi-pass hook: N seeded verdicts per criterion in, one grade out."""

    async def grade(request: GradeRequest) -> CaseGradeOutcome:
        rubric = request.material
        assert isinstance(rubric, Mapping)
        case_id: int = int(request.case_id)
        evidence: Sequence[Mapping[str, Any]] = request.row["evidence"]
        checks: Sequence[Mapping[str, Any]] = request.row["checks"]
        verdicts: list[dict[str, Any]] = case_results.valid_verdicts(rubric, evidence, case_id)
        if not verdicts:
            return case_results.incomplete_grade(
                request.row["case"], rubric, checks, evidence, judge_passes
            )
        return case_results.scored_grade(
            request.row["case"], rubric, checks, evidence, verdicts, judge_passes
        )

    return grade


# ── the board-owned failure shapes (each replaces one spine rung) ───────────


def _error_row_result(selected: SelectedCase, index: int, row: Mapping[str, Any]) -> CaseResult:
    """An error row publishes the UPSTREAM error's own code, with no grade envelope."""

    metadata: dict[str, Any] = {"row_index": index}
    diagnostic = public_error(
        row["error"],
        default_code="case_execution_failed",
        default_message="Candidate Case execution failed",
    )
    if diagnostic.kind is not None:
        metadata["error_kind"] = diagnostic.kind
    return failed_case_result(
        selected_case=selected,
        failures=[
            {
                "stage": "candidate",
                "code": diagnostic.code,
                "message": diagnostic.message,
                "retryable": diagnostic.retryable,
                "case_id": int(selected.case_id),
                "metadata": metadata,
            }
        ],
    )


def _missing_material_result(
    selected: SelectedCase, index: int, row: Mapping[str, Any] | None
) -> CaseResult:
    """A Case with no installed rubric keeps its answer, under a grade-less failure."""

    failure: dict[str, Any] = {
        "stage": "grading",
        "code": "missing_case_rubric",
        "message": "the selected Case has no installed DRACO rubric",
        "retryable": None,
        "case_id": int(selected.case_id),
        "metadata": {"row_index": index},
    }
    if row is None:
        # No row AND no rubric: nothing observable to retain. Unreachable on an
        # installed board (asset validation requires every case's rubric).
        return failed_case_result(selected_case=selected, failures=[failure])
    return case_results.ungraded_case_result(row["case"], failure)


def _hook_failure_result(
    selected: SelectedCase,
    index: int,
    row: Mapping[str, Any],
    outcome: CaseGradeOutcome,
) -> CaseResult:
    """An unscoreable Case retains its full zeroed metric block as audit material."""

    assert outcome.failure_code == "no_valid_judge_verdict"
    failure: dict[str, Any] = {
        "stage": "grading",
        "code": outcome.failure_code,
        "message": "no valid Judge verdict was produced for this Case",
        "retryable": None,
        "case_id": int(selected.case_id),
        "metadata": {"row_index": index},
    }
    return case_results.incomplete_case_result(row["case"], outcome, failure)


# ── the official cross-Case reduction (Stage 5) ─────────────────────────────


def draco_scorer(cases: Sequence[CaseResult]) -> CandidateScore:
    """Apply the official DRACO cross-Case reduction to gradeable typed Cases.

    The finalizer hands over exactly the Cases carrying a numeric grade; this
    reduction means the per-Case paper metrics into the Candidate block — per-axis
    maps and the optional Factual Accuracy axis are averaged over the Cases that
    carry them, verdict counters are summed.
    """

    scored: list[dict[str, Any]] = [case.model_dump() for case in cases]
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


def _validate_selected_cases(
    selected_cases: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    """Stage 1 — reject an empty, duplicated, or inputless selection before any filing."""
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
    """One dumped Case's grade mapping — present by the finalizer's gradeable selection."""
    grade = case.get("grade")
    if not isinstance(grade, Mapping):  # pragma: no cover - selected by caller
        raise AssertionError("scored Case must carry a Case Grade")
    return grade


def _grade_metric(case: Mapping[str, Any], key: str) -> Any:
    """One metric value off a dumped Case's grade block."""
    metrics = _grade(case).get("metrics")
    if not isinstance(metrics, Mapping):  # pragma: no cover - constructed locally
        raise AssertionError("Case Grade must carry metrics")
    return metrics[key]


def _mean_grades(cases: Sequence[Mapping[str, Any]], key: str) -> float:
    """Round-4 mean of one grade field over the gradeable Cases."""
    return round(sum(float(_grade(case)[key]) for case in cases) / len(cases), 4)


def _mean_grade_metrics(cases: Sequence[Mapping[str, Any]], key: str) -> float:
    """Round-4 mean of one metric over the gradeable Cases."""
    return round(sum(float(_grade_metric(case, key)) for case in cases) / len(cases), 4)


def _mean_optional_grade_metrics(cases: Sequence[Mapping[str, Any]], key: str) -> float | None:
    """Mean over the Cases that reported ``key``, or ``None`` when none of them did.

    A Case whose rubric has no Factual Accuracy axis reports ``None`` rather than 0.0, so it must
    be skipped instead of dragging the Candidate mean toward zero. This mirrors how
    :func:`_mean_grade_metric_maps` averages each axis over the Cases that carry it.
    """
    values: list[float] = [
        float(value)
        for case in cases
        if (value := _grade_metric(case, key)) is not None and not isinstance(value, bool)
    ]
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _sum_grade_metrics(cases: Sequence[Mapping[str, Any]], key: str) -> int:
    """Sum of one integer counter over the gradeable Cases."""
    return sum(int(_grade_metric(case, key)) for case in cases)


def _mean_grade_metric_maps(cases: Sequence[Mapping[str, Any]], key: str) -> dict[str, float]:
    """Per-axis round-4 means over the Cases that carry each axis, sorted by axis name."""
    values: dict[str, list[float]] = {}
    for case in cases:
        metric = _grade_metric(case, key)
        if not isinstance(metric, Mapping):  # pragma: no cover - constructed locally
            raise AssertionError(f"Case Grade metric {key!r} must be an object")
        for name, value in metric.items():
            values.setdefault(str(name), []).append(float(value))
    return {name: round(sum(items) / len(items), 4) for name, items in sorted(values.items())}


__all__ = ["AggregateError", "aggregate", "draco_scorer"]
