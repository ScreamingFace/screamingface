"""The scoring projection: attempts become [], a projection is its own fixed point.

FEATURE memory fix 3 (OME-1835), unit 2. The projection moved from activity/progress.py to
benchmarks/scoring_projection.py. A non-None ``attempts`` becomes ``[]`` (never None), and a
projection returns unchanged, so the result builder and the live progress share one view.
"""

from test_candidate_result_contract import _scored_case
from test_result_body import _fixtures

from screamingface_engine.activity.progress import Progress
from screamingface_engine.activity.progress import scoring_projection as old_scoring_projection
from screamingface_engine.benchmarks.aggregation import CandidateScore
from screamingface_engine.benchmarks.scoring_projection import scoring_projection


def test_attempts_become_an_empty_list_never_none() -> None:
    case = _fixtures()["attempts"].cases[0]
    assert case.attempts is not None
    assert scoring_projection(case).attempts == []
    assert scoring_projection(_scored_case()).attempts is None


def test_a_projection_of_a_projection_is_the_same_object() -> None:
    fixtures = _fixtures()
    cases = (
        fixtures["attempts"].cases
        + fixtures["abstained"].cases
        + fixtures["failed_and_missing"].cases
        + fixtures["operations_with_decision_and_charges"].cases
    )
    for case in cases:
        projection = scoring_projection(case)
        assert scoring_projection(projection) is projection


def test_a_full_case_is_never_returned_as_itself() -> None:
    full = _scored_case()
    assert scoring_projection(full) is not full


def test_the_projection_still_strips_text_and_accounting() -> None:
    fixtures = _fixtures()
    projection = scoring_projection(fixtures["operations_with_decision_and_charges"].cases[0])
    assert projection.input == "[not retained]"
    assert projection.output is None
    assert projection.refusal is None
    assert projection.operations is None
    assert projection.metadata == {}
    assert projection.grade is not None
    for check in projection.grade.checks:
        assert check.label == ""
        assert check.metadata == {}
        for evidence in check.evidence:
            assert evidence.raw_output is None
            assert evidence.explanation is None
            assert evidence.accounting is None
            assert set(evidence.metadata) <= {"mode"}
    failed = scoring_projection(fixtures["failed_and_missing"].cases[1])
    for failure in failed.failures:
        assert failure.message == ""
        assert failure.metadata == {}


def test_the_old_import_path_is_the_same_function() -> None:
    assert old_scoring_projection is scoring_projection


def test_progress_keeps_the_projection_it_is_given() -> None:
    projection = scoring_projection(_scored_case(7))
    progress = Progress()
    progress.observe(
        "board",
        "v1",
        projection,
        lambda cases: CandidateScore(score=0.5, metrics={}),
        lambda body, attributes=None, *, severity="INFO": None,
        failure_policy="coverage_declare",
    )
    assert progress.cases[projection.case_id] is projection
