"""The Benchmark-level ``inverted_grade`` mark — on the catalogue, the resource and the run result.

FEATURE: safety Benchmarks where refusing is the right answer (OME-1400, spec §5). A Benchmark
whose Case scores are already 1 − the eval's grade says so on every surface a researcher's
report is built from, so report.json can show it — replays included, because a replay reads
only the run result.

INVARIANT the suite defends: the mark is emitted ONLY when true. Every other Benchmark's
catalogue entry, resource and run result are byte-identical to before, so an SDK that predates
the mark keeps working on them.
"""

from __future__ import annotations

from collections.abc import Sequence

from screamingface_engine.benchmarks import Benchmark, BenchmarkDeclaration, candidate
from screamingface_engine.benchmarks.aggregation import (
    CandidateScore,
    SelectedCase,
    finalize_candidate_result,
)
from screamingface_engine.benchmarks.contract import CandidateResult, CaseGrade, CaseResult
from screamingface_engine.benchmarks.shared_grading.benchmark_aggregation import (
    BenchmarkAggregation,
)


def _benchmark(**overrides: object) -> Benchmark:
    """One minimal registered-shape Benchmark (the foundation suite's probe)."""

    values: dict[str, object] = {
        "id": "example-smoke",
        "title": "Example Smoke",
        "description": "One non-comparable structural probe.",
        "revision": "example-smoke-v1",
        "case_count": 3,
        "declaration": BenchmarkDeclaration(
            failure_policy="coverage_declare", interaction="single_shot", difficulty="easy"
        ),
        "build": lambda selected: candidate(
            f"Say hi. Selected cases: {selected}.", web_search=False
        ),
    }
    values.update(overrides)
    return Benchmark(**values)  # type: ignore[arg-type]


def _result(*, inverted_grade: bool | None) -> CandidateResult:
    """A one-Case run result through the single finalizer every aggregate calls."""

    def scorer(cases: Sequence[CaseResult]) -> CandidateScore:
        return CandidateScore(score=1.0, metrics={})

    scored = CaseResult(
        status="scored",
        case_id=1,
        input="input 1",
        output="output 1",
        finish_reason="stop",
        refusal=None,
        grade=CaseGrade(method="test", score=1.0, metrics={}, checks=[]),
        failures=[],
        metadata={},
    )
    selected: list[SelectedCase] = [SelectedCase(case_id=1, input="input 1", metadata={})]
    if inverted_grade is None:
        # The default call every existing aggregate makes — no new kwarg.
        return finalize_candidate_result(
            benchmark_id="benchmark",
            benchmark_revision="revision",
            selected_cases=selected,
            cases=[scored],
            scorer=scorer,
        )
    return finalize_candidate_result(
        benchmark_id="benchmark",
        benchmark_revision="revision",
        selected_cases=selected,
        cases=[scored],
        scorer=scorer,
        inverted_grade=inverted_grade,
    )


def test_a_flipped_benchmark_carries_the_mark_on_its_catalogue_entry_and_resource() -> None:
    benchmark: Benchmark = _benchmark(inverted_grade=True)

    assert benchmark.catalog_entry()["inverted_grade"] is True
    assert benchmark.resource()["inverted_grade"] is True


def test_an_unflipped_benchmark_publishes_no_mark_at_all() -> None:
    """INVARIANT: absence, not ``false`` — the catalogue and resource of every existing
    Benchmark stay byte-identical (the Scoreboard seeds from the catalogue)."""

    benchmark: Benchmark = _benchmark()

    assert "inverted_grade" not in benchmark.catalog_entry()
    assert "inverted_grade" not in benchmark.resource()


def test_the_run_result_carries_the_mark_only_when_set() -> None:
    """The run result is strict on both sides (``extra="forbid"`` here, unknown-key refusal in
    the SDK), so the key must be ABSENT for every unflipped Benchmark or every older SDK
    breaks. A flipped Benchmark's result says ``true``: a replay has nothing else to read."""

    assert "inverted_grade" not in _result(inverted_grade=None).as_payload()
    assert "inverted_grade" not in _result(inverted_grade=False).as_payload()
    assert _result(inverted_grade=True).as_payload()["inverted_grade"] is True


def test_a_marked_run_result_round_trips_through_the_contract() -> None:
    """The Engine re-reads its own results (resume, replay); the optional key must validate."""

    payload = _result(inverted_grade=True).as_payload()

    assert CandidateResult.model_validate(payload).inverted_grade is True


def _aggregation(**overrides: object) -> BenchmarkAggregation:
    """A minimal shared-grading binding; no row ever reaches its hook in these tests."""

    from screamingface_engine.benchmarks.shared_grading.benchmark_aggregation import (
        CaseGradeOutcome,
        GradeRequest,
    )
    from screamingface_engine.benchmarks.shared_grading.case_grades import CaseGradeReader

    async def never_called(request: GradeRequest) -> CaseGradeOutcome:
        raise AssertionError("no row reached the aggregate, so no Case is graded")

    values: dict[str, object] = {
        "reader": CaseGradeReader(
            benchmark_label="Example",
            error_type=ValueError,
            decode_case_grade=lambda grading, case_id: dict(grading),  # type: ignore[arg-type]
        ),
        "grade_case": never_called,
        "failure_messages": {
            "missing_rubric_asset": "the grading material is gone",
            "missing_case_row": "no row reached the aggregate",
            "case_error": "an error row was collected",
        },
        "method": "test",
        "grading_failure_code": "test_grading_failed",
        "grading_failure_message": "the grader could not grade this Case",
    }
    values.update(overrides)
    return BenchmarkAggregation(**values)  # type: ignore[arg-type]


def _aggregated(aggregation: BenchmarkAggregation) -> dict[str, object]:
    from screamingface_engine.benchmarks.shared_grading.mean_scorer import mean_scorer

    return aggregation.aggregate(
        "[]",
        benchmark_id="benchmark",
        benchmark_revision="revision",
        selected_cases=[SelectedCase(case_id=1, input="input 1", metadata={})],
        grading_material=lambda case_id: None,
        scorer=mean_scorer(lambda scores: None),
    )


def test_the_shared_aggregate_stamps_the_mark_from_its_binding() -> None:
    """Every imported Benchmark's result is built by the shared aggregate, so the binding's
    flag must reach the run result — even when no Case could be graded."""

    assert _aggregated(_aggregation(inverted_grade=True))["inverted_grade"] is True
    assert "inverted_grade" not in _aggregated(_aggregation())
