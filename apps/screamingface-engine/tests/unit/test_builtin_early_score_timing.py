"""Every built-in exposes case one's score while case two is still answering."""

import asyncio
import json

import pytest
from test_benchmark_stage_parity import assets
from test_ifeval_incremental_proof import _assets as ifeval_assets
from test_medxpert_protocol_turns import _assets as medxpert_assets

from screamingface_engine.activity.observer import ActivityObserver
from screamingface_engine.benchmarks.builtins import BUILTIN_REGISTRATIONS
from screamingface_engine.benchmarks.case_context import current_case_position
from screamingface_engine.benchmarks.definition import link_candidate
from screamingface_engine.observations import RunObservations
from screamingface_engine.world.candidate_adapter import install_candidate_invocation
from url4.dag import run as execute
from url4.observe import Log
from url4.peer.server import Url4Node


@pytest.mark.asyncio
@pytest.mark.parametrize("registration", BUILTIN_REGISTRATIONS, ids=lambda r: r.benchmark.id)
@pytest.mark.parametrize("fusion", [False, True], ids=["solo", "fusion"])
async def test_score_precedes_second_case_completion(tmp_path, monkeypatch, registration, fusion):
    _assets(tmp_path, monkeypatch, registration)
    node = Url4Node("timing")
    registration.benchmark.install(node, tmp_path)
    install_candidate_invocation(node)
    waiting, release = asyncio.Event(), asyncio.Event()
    snapshots, collector = _observe(node, waiting, release)
    candidate = "/writer($input)!answer"
    if fusion:
        candidate = (
            "(a:0.0:/writer($input)!answer,b:0.0:/writer-b($input)!answer,"
            "c:0.0:/synth($a,$b)!combine)!'$c'"
        )
    run = RunObservations((ActivityObserver,))
    try:
        with run.bind():
            task = asyncio.create_task(
                execute(
                    link_candidate(candidate, registration.benchmark.protocol(2)),
                    io=node,
                    observer=collector,
                )
            )
            try:
                await asyncio.wait_for(waiting.wait(), 10)
                _assert_live(task, snapshots, registration.benchmark.id)
            finally:
                release.set()
                result = json.loads(await asyncio.wait_for(task, 10))
        assert result["score"] is not None
        assert len(result["cases"]) == 2
    finally:
        await run.aclose()
        await node.aclose()


def _assets(tmp_path, monkeypatch, registration):
    name = registration.asset_bundle.id
    if name == "ifeval":
        (tmp_path / name).mkdir()
        ifeval_assets(tmp_path / name)
    elif name == "medxpert":
        medxpert_assets(tmp_path, 2)
    else:
        assets(registration, tmp_path, monkeypatch)
        if name == "contracteval":
            root = tmp_path / name
            rows = json.loads((root / "cases.json").read_text())
            rows.append({**rows[0], "id": 2})
            (root / "cases.json").write_text(json.dumps(rows))
            (root / "answers" / "2.json").write_text((root / "answers" / "1.json").read_text())


def _judges(node):
    from screamingface_engine.benchmarks.draco.definition import JUDGE_MODEL as draco
    from screamingface_engine.benchmarks.gdpval.revision_inputs import JUDGE_MODEL as gdpval
    from screamingface_engine.benchmarks.healthbench.revision_inputs import JUDGE_MODEL as health

    for model in {draco, gdpval, health}:
        node.endpoint("/" + model)(
            lambda request: '{"explanation":"ok","criteria_met":true,"criterion_status":"MET"}'
        )


def _observe(node, waiting, release):
    snapshots = []

    class Collector:
        def on_event(self, event):
            if isinstance(event, Log) and event.attributes.get("sf.progress.schema"):
                snapshots.append(dict(event.attributes))

    async def answer(request):
        if current_case_position() == (2, 2):
            waiting.set()
            await release.wait()
        return "(E) Tea is a warm drink"

    for path in ("/writer", "/writer-b", "/synth"):
        node.endpoint(path)(answer)
    _judges(node)
    return snapshots, Collector()


def _assert_live(task, snapshots, benchmark_id):
    assert not task.done()
    assert snapshots, benchmark_id
    assert snapshots[0]["sf.progress.graded"] == 1
    assert snapshots[0]["sf.progress.score"] is not None
