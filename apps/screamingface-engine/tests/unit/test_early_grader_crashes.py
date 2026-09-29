"""Execution bugs in the grade fold cannot become ordinary candidate failures."""

import asyncio

import pytest
from test_ifeval_incremental_proof import _assets

from screamingface_engine.benchmarks.definition import link_candidate
from screamingface_engine.benchmarks.ifeval import grade
from screamingface_engine.benchmarks.ifeval.definition import IFEVAL
from screamingface_engine.benchmarks.ifeval.runtime import install
from screamingface_engine.world.candidate_adapter import install_candidate_invocation
from url4.peer.server import Url4Node


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [RuntimeError, AttributeError, ZeroDivisionError])
async def test_grader_crash_fails_real_execution(tmp_path, monkeypatch, error):
    _assets(tmp_path)
    original = grade._grade_case

    async def crash(request):
        if request.case_id == 2:
            raise error("private grading detail")
        return await original(request)

    monkeypatch.setattr(grade, "_grade_case", crash)
    node = Url4Node("test")
    install(node, tmp_path)
    install_candidate_invocation(node)
    node.endpoint("/candidate")(lambda request: "Fresh tea")
    with pytest.raises(Exception) as caught:
        await node.evaluate(link_candidate("/candidate($input)!answer", IFEVAL.protocol(2)))
    assert "private grading detail" not in str(caught.value)


@pytest.mark.asyncio
async def test_case_endpoint_preserves_cancellation():
    from screamingface_engine.benchmarks.spine.incremental_routes import case_result_endpoint
    from url4.peer.server import Request

    def cancel(count):
        raise asyncio.CancelledError()

    handler = case_result_endpoint(cancel, available_case_count=1)
    with pytest.raises(asyncio.CancelledError):
        await handler(Request(path="/case-result", params={}, context="{}", intent="0:1"))


@pytest.mark.asyncio
async def test_corrupt_final_grade_is_contract_error():
    from test_spine_scored import _Hook, _path, _selected

    from screamingface_engine.benchmarks.aggregation import CandidateScore
    from screamingface_engine.benchmarks.spine.incremental import Scoring
    from screamingface_engine.benchmarks.spine.incremental_routes import aggregate_result_endpoint
    from url4.core.errors import ResolutionError
    from url4.peer.server import Request

    scoring = Scoring(
        _path(_Hook()),
        "board",
        "v1",
        _selected(1),
        lambda _: None,
        lambda cases: CandidateScore(score=0.0, metrics={}),
    )

    handler = aggregate_result_endpoint(
        label="test", available_case_count=1, load=lambda count: scoring
    )
    with pytest.raises(ResolutionError) as caught:
        await handler(
            Request(
                path="/aggregate", params={}, context="private corrupt grade", intent="aggregate:1"
            )
        )
    assert caught.value.code == "benchmark_contract_error"
    assert "private corrupt grade" not in str(caught.value)
