"""Early grading preserves real connector cache accounting without provider calls."""

import json
from decimal import Decimal

import httpx
import pytest
from test_cache_hit_tokens import _HIT_HEADERS, _MODEL, _body, _Recorder, _served_aigw
from test_early_grade_compatibility import BASELINE
from test_ifeval_incremental_proof import _assets
from test_ifeval_production_grades import _count_grades

from screamingface_engine.activity.observer import ActivityObserver
from screamingface_engine.benchmarks.definition import link_candidate
from screamingface_engine.benchmarks.ifeval.definition import IFEVAL
from screamingface_engine.benchmarks.ifeval.runtime import install
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
    _assets(tmp_path)
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
        install(world.node, tmp_path)
        install_candidate_invocation(world.node)
        for protocol in (BASELINE["ifeval"]["protocols"]["2"], IFEVAL.protocol(2)):
            reports.append(await _evaluate(world.node, protocol, observed))
        await world.node.aclose()
    assert reports[0] == reports[1]
    assert len(calls) == 4
    assert calls[:2] == calls[2:]
    assert marked == [1, 2, 1, 2]
    if observed:
        assert snapshots[-1]["sf.progress.completed"] == 2
        assert snapshots[-1]["sf.progress.graded"] == 2
    else:
        assert snapshots == []


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
    assert len(rec.usages) == 2
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
