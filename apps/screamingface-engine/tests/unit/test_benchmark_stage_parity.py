"""Healthy, deterministic board runs preserve complete results with activity on/off."""

import json

import pytest
from test_draco_corrective_loop_e2e import _assets as draco_assets
from test_healthbench_dual_board_runtime import _write_full_assets as healthbench_assets
from test_ifeval_case_evaluation_route import _assets as ifeval_assets
from test_medxpert_protocol_turns import _assets as medxpert_assets

from screamingface_engine.activity.observer import ActivityObserver
from screamingface_engine.benchmarks.builtins import BUILTIN_REGISTRATIONS
from screamingface_engine.benchmarks.candidate_adapter import install_candidate_invocation
from screamingface_engine.benchmarks.definition import link_candidate
from screamingface_engine.observations import RunObservations
from url4.dag import run as execute
from url4.observe import Log
from url4.peer.server import Url4Node


def assets(registration, root, monkeypatch):
    name = registration.asset_bundle.id
    if name == "draco":
        draco_assets(root)
    elif name == "healthbench":
        healthbench_assets(root / name)
    elif name == "ifeval":
        (root / name).mkdir()
        ifeval_assets(root / name)
    elif name == "medxpert":
        medxpert_assets(root, 1)
    else:
        import test_gdpval_runtime as fixture

        from screamingface_engine.benchmarks.gdpval.definition import TEXT_CASE_IDS

        assert name == "gdpval"
        monkeypatch.setattr(fixture, "_CASE_IDS", TEXT_CASE_IDS)
        fixture._write_assets(root / name)


class Events:
    def __init__(self):
        self.events = []

    def on_event(self, event):
        self.events.append(event)


async def run_board(registration, root, enabled):
    node = Url4Node("parity")
    registration.benchmark.install(node, root)
    install_candidate_invocation(node)
    requests = []

    @node.endpoint("/writer")
    def answer(request):
        requests.append((request.path, request.context, request.intent))
        return "(E) Tea is a warm drink"

    def judge(request):
        requests.append((request.path, request.context, request.intent))
        return '{"explanation":"ok","criteria_met":true,"criterion_status":"MET"}'

    from screamingface_engine.benchmarks.draco.definition import JUDGE_MODEL as draco_judge
    from screamingface_engine.benchmarks.gdpval.pins import JUDGE_MODEL as gdpval_judge
    from screamingface_engine.benchmarks.healthbench.pins import JUDGE_MODEL as health_judge

    for model in {draco_judge, gdpval_judge, health_judge}:
        node.endpoint("/" + model)(judge)
    expression = link_candidate(
        "(answer:0.0:/writer($input)!'Answer')!'$answer'", registration.benchmark.protocol(1)
    )
    events = Events()
    run = RunObservations((lambda: ActivityObserver(enabled=enabled),))
    try:
        with run.bind():
            result = await execute(expression, io=node, observer=events)
    finally:
        await run.aclose()
    return json.loads(result), requests, events.events


@pytest.mark.asyncio
@pytest.mark.parametrize("registration", BUILTIN_REGISTRATIONS, ids=lambda r: r.benchmark.id)
async def test_healthy_boards_preserve_requests_and_full_results(
    tmp_path, monkeypatch, registration
):
    assets(registration, tmp_path, monkeypatch)
    plain, requests, off = await run_board(registration, tmp_path, False)
    observed, observed_requests, events = await run_board(registration, tmp_path, True)
    assert observed == plain
    assert observed_requests == requests
    assert observed["score"] is not None, observed
    assert not [e for e in off if isinstance(e, Log)]
    logs = [e for e in events if isinstance(e, Log)]
    completed = {
        e.attributes["sf.activity.kind"]
        for e in logs
        if e.attributes["sf.activity.state"] == "completed"
    }
    assert {
        "case_loading",
        "answering",
        "grading",
        "aggregation",
    } <= completed
    assert all(e.attributes["sf.activity.state"] in {"started", "completed"} for e in logs)
