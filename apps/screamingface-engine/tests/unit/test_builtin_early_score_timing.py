"""Every built-in exposes case one's score while case two is still answering."""

import asyncio
import json

import pytest
from test_benchmark_stage_parity import assets
from test_medxpert_protocol_turns import _assets as medxpert_assets

from screamingface_engine.activity.observer import ActivityObserver
from screamingface_engine.benchmarks.builtins import BUILTIN_REGISTRATIONS
from screamingface_engine.benchmarks.case_context import current_case_position
from screamingface_engine.benchmarks.definition import link_candidate
from screamingface_engine.observations import RunObservations
from screamingface_engine.world.candidate_adapter import install_candidate_invocation
from url4 import RelExpr, Text, expr, render, src
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
    if name == "medxpert":
        medxpert_assets(tmp_path, 2)
    else:
        assets(registration, tmp_path, monkeypatch)


async def _call(node: Url4Node, route: str, payload: str, intent: str) -> str:
    """Call one route on ``node`` with ``payload`` as its context; the route's text back.

    Moved here from the hand-built IFEval's incremental proof (OME-1527) for the tests that
    still call one route directly.
    """

    expression = expr(
        src(Text(payload), name="payload", weight=0.0),
        src(
            RelExpr(path=route, context="$payload", intent=Text(intent)), name="result", weight=0.0
        ),
        intent=Text("$result"),
    )
    return (await node.evaluate(render(expression))).text


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
    return snapshots, Collector()


def _assert_live(task, snapshots, benchmark_id):
    assert not task.done()
    assert snapshots, benchmark_id
    assert snapshots[0]["sf.progress.graded"] == 1
    assert snapshots[0]["sf.progress.score"] is not None
