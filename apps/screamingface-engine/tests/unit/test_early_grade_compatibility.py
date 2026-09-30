"""Old production protocols and early grades describe the same scoring exam."""

import json
from pathlib import Path

import pytest
from test_builtin_early_score_timing import _assets

from screamingface_engine.benchmarks.builtins import BUILTIN_REGISTRATIONS
from screamingface_engine.benchmarks.definition import link_candidate
from screamingface_engine.world.candidate_adapter import install_candidate_invocation
from url4.peer.server import Url4Node

BASELINE = json.loads(
    (Path(__file__).parents[1] / "fixtures/early_grade_compatibility.json").read_text()
)["boards"]


def test_semantic_revisions_preserve_ranked_scores():
    assert {r.benchmark.id: r.benchmark.revision for r in BUILTIN_REGISTRATIONS} == {
        name: board["revision"] for name, board in BASELINE.items()
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("registration", BUILTIN_REGISTRATIONS, ids=lambda r: r.benchmark.id)
@pytest.mark.parametrize("limit", [1, 2])
@pytest.mark.parametrize("fusion", [False, True], ids=["solo", "fusion"])
async def test_old_and_early_protocol_requests_and_results_match(
    tmp_path, monkeypatch, registration, limit, fusion
):
    _assets(tmp_path, monkeypatch, registration)
    node = Url4Node("parity")
    registration.benchmark.install(node, tmp_path)
    install_candidate_invocation(node)
    calls = []
    _verify_scoring(monkeypatch)
    _install_calls(node, calls)
    candidate = "/writer($input)!answer"
    if fusion:
        candidate = (
            "(a:0.0:/writer($input)!answer,b:0.0:/writer-b($input)!answer,"
            "c:0.0:/synth($a,$b)!combine)!'$c'"
        )
    try:
        old = json.loads(
            (
                await node.evaluate(
                    link_candidate(
                        candidate, BASELINE[registration.benchmark.id]["protocols"][str(limit)]
                    )
                )
            ).text
        )
        old_calls = list(calls)
        calls.clear()
        new = json.loads(
            (
                await node.evaluate(
                    link_candidate(candidate, registration.benchmark.protocol(limit))
                )
            ).text
        )
        assert new == old
        assert calls == old_calls
    finally:
        await node.aclose()


def _verify_scoring(monkeypatch):
    graded = {}

    def verify_projection(benchmark, revision, result, scorer):
        from screamingface_engine.activity.progress import scoring_projection

        graded[result.case_id] = result
        cases = tuple(
            c for c in graded.values() if c.grade is not None and c.grade.score is not None
        )
        if cases:
            assert scorer(cases) == scorer(tuple(scoring_projection(c) for c in cases))

    monkeypatch.setattr(
        "screamingface_engine.benchmarks.shared_grading.incremental.completed_case",
        verify_projection,
    )
    monkeypatch.setattr(
        "screamingface_engine.benchmarks.shared_grading.benchmark_aggregation.completed_case",
        verify_projection,
    )


def _install_calls(node, calls):
    def answer(request):
        calls.append((request.path, request.context, request.intent, request.params))
        return "(E) Tea is a warm drink"

    def judge(request):
        calls.append((request.path, request.context, request.intent, request.params))
        return '{"explanation":"ok","criteria_met":true,"criterion_status":"MET"}'

    from screamingface_engine.benchmarks.draco.definition import JUDGE_MODEL as draco
    from screamingface_engine.benchmarks.gdpval.revision_inputs import JUDGE_MODEL as gdpval
    from screamingface_engine.benchmarks.healthbench.revision_inputs import JUDGE_MODEL as health

    for model in {draco, gdpval, health}:
        node.endpoint("/" + model)(judge)
    for path in ("/writer", "/writer-b", "/synth"):
        node.endpoint(path)(answer)
