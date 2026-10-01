"""Observation keeps scoring facts, not response text or accounting copies."""

from test_graded_result_transport import _result

from screamingface_engine.activity.progress import Progress
from screamingface_engine.benchmarks.aggregation import CandidateScore


def test_progress_drops_large_payloads_without_mutating_authoritative_result():
    result = _result().model_copy(
        update={"input": "private prompt", "output": "private answer", "refusal": "private refusal"}
    )
    original = result.model_dump()
    progress = Progress()
    progress.observe(
        "board",
        "v1",
        result,
        lambda cases: CandidateScore(score=0.5, metrics={}),
        lambda body, attributes=None, *, severity="INFO": None,
    )
    retained = progress.cases[result.case_id]
    assert retained.input != result.input
    assert retained.output is None
    assert retained.refusal is None
    assert retained.operations is None
    assert retained.grade is not None
    for check in retained.grade.checks:
        assert check.label == ""
        for evidence in check.evidence:
            assert evidence.raw_output is None
            assert evidence.explanation is None
            assert evidence.accounting is None
    assert result.model_dump() == original
    progress.observe(
        "board",
        "v1",
        result,
        lambda cases: CandidateScore(score=0.5, metrics={}),
        lambda body, attributes=None, *, severity="INFO": None,
    )
    assert progress.revision == 1


def test_shared_imported_scorer_preserves_every_prefix_after_projection():
    from screamingface_engine.activity.progress import scoring_projection
    from screamingface_engine_inspect.single_shot import _accuracy

    result = _result()
    assert result.grade is not None
    cases = []
    for index, score in enumerate([1.0, 0.0, 0.5, 1.0]):
        cases.append(
            result.model_copy(
                update={
                    "case_id": index + 1,
                    "grade": result.grade.model_copy(update={"score": score}),
                }
            )
        )
        assert _accuracy(cases) == _accuracy([scoring_projection(case) for case in cases])
