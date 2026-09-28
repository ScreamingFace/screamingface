"""The shipped IFEval expression produces grades before the next answer finishes."""

import asyncio
import inspect
import json

import pytest
from test_ifeval_incremental_proof import _assets

from screamingface_engine.benchmarks.definition import link_candidate
from screamingface_engine.benchmarks.ifeval import grade, grading
from screamingface_engine.benchmarks.ifeval.definition import IFEVAL
from screamingface_engine.benchmarks.ifeval.runtime import install
from screamingface_engine.world.candidate_adapter import install_candidate_invocation
from url4.peer.server import Url4Node


def _count_grades(monkeypatch):
    marked = []
    original = grade._grade_case

    async def counted(request):
        marked.append(request.case_id)
        return await original(request)

    monkeypatch.setattr(grade, "_grade_case", counted)
    return marked


@pytest.mark.asyncio
async def test_canonical_expression_grades_before_next_candidate(tmp_path, monkeypatch) -> None:
    _assets(tmp_path)
    node = Url4Node("test")
    install(node, tmp_path)
    install_candidate_invocation(node)
    second_started, release = asyncio.Event(), asyncio.Event()
    marked = _count_grades(monkeypatch)

    async def candidate(request):
        if "(2)" in request.context:
            second_started.set()
            await release.wait()
        return "Fresh tea"

    node.endpoint("/proof")(candidate)
    task = asyncio.create_task(
        node.evaluate(link_candidate("/proof($input)!answer", IFEVAL.protocol(2)))
    )
    try:
        await asyncio.wait_for(second_started.wait(), 5)
        assert marked == [1]
        release.set()
        result = json.loads((await asyncio.wait_for(task, 5)).text)
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert marked == [1, 2]
    assert result["score"] == 1.0


@pytest.mark.asyncio
async def test_aggregate_reuses_serialized_grade_without_checking(tmp_path, monkeypatch) -> None:
    from test_ifeval_aggregate import _evaluation
    from test_ifeval_incremental_proof import _call

    from screamingface_engine.benchmarks.ifeval.definition import CASE_RESULT_ROUTE
    from screamingface_engine.benchmarks.ifeval.incremental import aggregate

    _assets(tmp_path)
    node = Url4Node("test")
    install(node, tmp_path)
    # The real checker has already produced this evidence; adapt fixture instruction IDs.
    row = json.loads(json.dumps(_evaluation(2, [True], [True])))
    raw = json.loads(row["grading"][0]) if isinstance(row["grading"][0], str) else row["grading"][0]
    raw["attempts"][0]["instruction_id_list"] = ["punctuation:no_comma"]
    encoded = await _call(node, CASE_RESULT_ROUTE, json.dumps(row), "2")

    def forbidden(*args, **kwargs):
        pytest.fail("replayed typed result must never run grading or checking")

    monkeypatch.setattr(grade, "_grade_case", forbidden)
    monkeypatch.setattr(grading, "check_case", forbidden)
    # Preserve selected position 2 and its earlier failure across the serialized boundary.
    error = {"error": {"message": "unavailable", "code": "provider_error"}}
    result = aggregate(tmp_path)(json.dumps([error, encoded]), 2)
    assert result["score"] == 1.0
    assert result["coverage"] == 0.5
    assert result["cases"][0]["failures"][0]["metadata"]["row_index"] == 0


@pytest.mark.asyncio
async def test_corrupt_grading_is_not_downgraded_to_failed_case(tmp_path) -> None:
    from test_ifeval_aggregate import _evaluation
    from test_ifeval_incremental_proof import _call

    from screamingface_engine.benchmarks.ifeval.definition import CASE_RESULT_ROUTE
    from screamingface_engine.benchmarks.ifeval.incremental import aggregate
    from url4.core.errors import ResolutionError
    from url4.dag.nodes._shared import _error_payload

    _assets(tmp_path)
    node = Url4Node("test")
    install(node, tmp_path)
    # The case-2 record declares quotation checking; installed spec expects no commas.
    with pytest.raises(ResolutionError) as error:
        await _call(node, CASE_RESULT_ROUTE, json.dumps(_evaluation(2, [True], [True])), "2")
    collected = _error_payload(error.value)
    with pytest.raises(ValueError):
        aggregate(tmp_path)(json.dumps([collected]), 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", ["Fresh tea", "Fresh, tea"])
async def test_production_matches_batch_payload_and_checks_once(tmp_path, monkeypatch, answer):
    from screamingface_engine.benchmarks.ifeval.definition import CASE_RESULT_ROUTE

    specs = _assets(tmp_path)
    node = Url4Node("test")
    install(node, tmp_path)
    install_candidate_invocation(node)
    rows, checked = [], []
    original_handler = node._endpoints[CASE_RESULT_ROUTE]
    original_check = grading.check_case

    async def capture(request):
        rows.append(json.loads(request.context))
        result = original_handler(request)
        return await result if inspect.isawaitable(result) else result

    def check(**kwargs):
        checked.append(kwargs["response"])
        return original_check(**kwargs)

    async def candidate(request):
        return answer

    node._endpoints[CASE_RESULT_ROUTE] = capture
    node.endpoint("/proof")(candidate)
    monkeypatch.setattr(grading, "check_case", check)
    result = json.loads(
        (await node.evaluate(link_candidate("/proof($input)!answer", IFEVAL.protocol(2)))).text
    )
    assert checked == [answer, answer]
    batch = grade.aggregate(json.dumps(rows), specs, "ifeval", [1, 2], selected_case_count=2)
    assert result == batch
    assert checked == [answer, answer]
