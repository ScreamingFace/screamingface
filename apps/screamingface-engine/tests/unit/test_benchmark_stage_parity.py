"""Healthy, deterministic benchmark runs preserve complete results with activity on/off."""

import json

import pytest
from test_medxpert_protocol_turns import _assets as medxpert_assets

from screamingface_engine.activity.observer import ActivityObserver
from screamingface_engine.benchmarks.builtins import BUILTIN_REGISTRATIONS
from screamingface_engine.benchmarks.definition import link_candidate
from screamingface_engine.observations import RunObservations
from screamingface_engine.world.candidate_adapter import install_candidate_invocation
from url4.dag import run as execute
from url4.observe import Log
from url4.peer.server import Url4Node


def assets(registration, root, monkeypatch):
    name = registration.asset_bundle.id
    if name == "medxpert":
        medxpert_assets(root, 1)


class Events:
    def __init__(self):
        self.events = []

    def on_event(self, event):
        self.events.append(event)


async def run_benchmark(registration, root, enabled):
    node = Url4Node("parity")
    registration.benchmark.install(node, root)
    install_candidate_invocation(node)
    requests = []

    @node.endpoint("/writer")
    def answer(request):
        requests.append((request.path, request.context, request.intent))
        return "(E) Tea is a warm drink"

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
async def test_healthy_benchmarks_preserve_requests_and_full_results(
    tmp_path, monkeypatch, registration
):
    assets(registration, tmp_path, monkeypatch)
    plain, requests, off = await run_benchmark(registration, tmp_path, False)
    observed, observed_requests, events = await run_benchmark(registration, tmp_path, True)
    assert observed == plain
    assert observed_requests == requests
    assert observed["score"] is not None, observed
    assert not [e for e in off if isinstance(e, Log)]
    logs = [e for e in events if isinstance(e, Log) and e.attributes.get("sf.activity.schema")]
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
