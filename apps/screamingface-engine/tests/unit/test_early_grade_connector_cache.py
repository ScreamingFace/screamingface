"""Early grading preserves real connector cache accounting without provider calls.

MedXpertQA is the subject since OME-1527 moved IFEval, the original one, to a local inspect Task:
each Case asks the model twice (a reasoning turn, then the commit turn).

WHY a recorded baseline (spec 2026-10-20-url4-benchmark-expression, D5): the retired protocol's
routes are gone, so it cannot run beside the rebuilt one. The fixture keeps its report and the
exact gateway requests from origin/main; the rebuilt protocol must reproduce both.
"""

import json
from dataclasses import replace
from decimal import Decimal

import httpx
import pytest
from test_cache_hit_tokens import _HIT_HEADERS, _MODEL, _body, _Recorder, _served_aigw
from test_early_grade_compatibility import BASELINE
from test_medxpert_protocol_turns import _assets

from screamingface_engine.activity.observer import ActivityObserver
from screamingface_engine.benchmarks.definition import link_candidate
from screamingface_engine.benchmarks.medxpert import aggregate
from screamingface_engine.benchmarks.medxpert.definition import MEDXPERT
from screamingface_engine.observations import RunObservations
from screamingface_engine.world.candidate_adapter import install_candidate_invocation
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4.dag import run as url4_run


@pytest.mark.asyncio
@pytest.mark.parametrize("observed", [False, True])
async def test_cached_connector_requests_results_and_consumption_match(
    tmp_path, monkeypatch, observed
):
    _assets(tmp_path, 2)
    marked = _count_grades(monkeypatch)
    calls, reports, snapshots = [], [], []
    monkeypatch.setattr(
        "screamingface_engine.benchmarks.progress.current_log_sink",
        lambda: lambda body, attrs: snapshots.append(dict(attrs)),
    )

    def handle(request):
        assert request.url.path == "/v1/chat/completions"
        calls.append(json.loads(request.content))
        body = _body(_served_aigw())
        body["choices"][0]["message"]["content"] = "Fresh tea"
        return httpx.Response(200, headers=_HIT_HEADERS, json=body)

    cfg = AigatewayConfig(models=(ModelSpec(id=_MODEL, web_search=False),), default_model=_MODEL)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://aigateway.test"
    ) as client:
        world = await build_aigateway_world(cfg, client=client)
        MEDXPERT.install(world.node, tmp_path)
        install_candidate_invocation(world.node)
        reports.append(await _evaluate(world.node, MEDXPERT.protocol(2), observed))
        await world.node.aclose()
    recorded = BASELINE["medxpert"]["connector_cache"]
    assert reports[0] == recorded["report"]
    # Two Cases x two turns, byte for byte the requests the retired protocol sent.
    assert len(calls) == 4
    assert calls == recorded["requests"]
    assert marked == [1, 2]
    if observed:
        assert snapshots[-1]["sf.progress.completed"] == 2
        assert snapshots[-1]["sf.progress.graded"] == 2
    else:
        assert snapshots == []


def _count_grades(monkeypatch):
    """Record each Case MedXpertQA's grade hook marks, in order."""

    marked = []
    original = aggregate._PATH.grade_case

    async def counted(request):
        marked.append(request.case_id)
        return await original(request)

    monkeypatch.setattr(aggregate, "_PATH", replace(aggregate._PATH, grade_case=counted))
    return marked


async def _evaluate(node, protocol, observed):
    rec = _Recorder()
    observations = RunObservations((ActivityObserver,) if observed else ())
    try:
        with observations.bind():
            report = json.loads(
                await url4_run(
                    link_candidate(f"/{_MODEL}($input)!answer", protocol),
                    io=node,
                    observer=rec,
                )
            )
    finally:
        await observations.aclose()
    assert len(rec.usages) == 4
    for usage in rec.usages:
        assert (
            usage.input_tokens,
            usage.output_tokens,
            usage.cache_read_tokens,
            usage.cache_creation_tokens,
            usage.reasoning_tokens,
        ) == (0, 0, 0, 0, 0)
        assert usage.cost_usd == Decimal("0")
    return report
