"""Audit real model-call observations through every built-in benchmark recipe."""

import json

import httpx

from screamingface_engine.activity.observer import ActivityObserver
from screamingface_engine.benchmarks.definition import link_candidate
from screamingface_engine.benchmarks.draco.definition import JUDGE_MODEL as DRACO_JUDGE
from screamingface_engine.benchmarks.gdpval.pins import JUDGE_MODEL as GDPVAL_JUDGE
from screamingface_engine.benchmarks.healthbench.pins import JUDGE_MODEL as HEALTH_JUDGE
from screamingface_engine.grading_accounting import capture_grading_requests
from screamingface_engine.observations import RunObservations
from screamingface_engine.operation_calls import capture_request_accounting
from screamingface_engine.world.candidate_adapter import install_candidate_invocation
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4.dag import run as execute
from url4.observe import Log


class Events:
    def __init__(self):
        self.events = []

    def on_event(self, event):
        self.events.append(event)


async def _run(registration, root, fusion):
    def respond(request):
        model = json.loads(request.content)["model"]
        answer = (
            "(E) Tea is a warm drink"
            if model in {"writer", "synth"}
            else ('{"explanation":"ok","criteria_met":true,"criterion_status":"MET"}')
        )
        return httpx.Response(
            200, json={"choices": [{"message": {"content": answer}, "finish_reason": "stop"}]}
        )

    async with httpx.AsyncClient(
        base_url="http://gateway", transport=httpx.MockTransport(respond)
    ) as client:
        world = await build_aigateway_world(
            AigatewayConfig(
                base_url="http://gateway",
                default_model="writer",
                allow_outbound=False,
                models=tuple(
                    ModelSpec(id=m, web_search=True)
                    for m in {"writer", "synth", DRACO_JUDGE, GDPVAL_JUDGE, HEALTH_JUDGE}
                ),
            ),
            client=client,
            tavily_api_key="test-only",
            tavily_client=client,
        )
        registration.benchmark.install(world.node, root)
        install_candidate_invocation(world.node)
        candidate = "(answer:0.0:/writer($input)!'Answer')!'$answer'"
        if fusion:
            candidate = (
                "(a:0.0:/writer($input)!'First',b:0.0:/writer($input)!'Second',"
                "answer:0.0:/synth($a,$b)!'Synthesize')!'$answer'"
            )
        events = Events()
        run = RunObservations((ActivityObserver,))
        try:
            with run.bind(), capture_request_accounting(), capture_grading_requests():
                result = await execute(
                    link_candidate(candidate, registration.benchmark.protocol(1)),
                    io=world.node,
                    observer=events,
                )
        finally:
            await run.aclose()
            await world.aclose()
    return json.loads(result), [e.attributes for e in events.events if isinstance(e, Log)]
