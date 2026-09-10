"""Real model producer -> URL4 node -> Engine stream; no paid provider calls."""

import asyncio

import httpx
import pytest

from screamingface_engine.activity.contract import ActivityLevel
from screamingface_engine.runner.main import build_executor
from screamingface_engine.testing import InMemoryEventStream
from screamingface_engine.world_config import AigatewaySection, ModelSpec, WorldConfig
from url4.streaming.lifecycle import run as publish_run
from url4.streaming.protocol import LogEvent, TerminatedEvent


def config():
    return WorldConfig(
        aigateway=AigatewaySection(
            base_url="http://gateway",
            default_model="model",
            models=(ModelSpec(id="model"),),
        )
    )


def completion(refused=False):
    return {
        "choices": [
            {
                "message": {
                    "content": "PRIVATE ANSWER",
                    "refusal": "PRIVATE REFUSAL" if refused else None,
                },
                "finish_reason": "stop",
            }
        ]
    }


async def publish(handler, *, level="full", expression="/model('PRIVATE PROMPT')!go"):
    async with httpx.AsyncClient(
        base_url="http://gateway", transport=httpx.MockTransport(handler)
    ) as client:
        executor = build_executor({"URL4_CLOUD_ACTIVITY_LEVEL": level}, config(), client=client)
        stream = InMemoryEventStream()
        await publish_run(stream, executor, "test-activity", expression)
        frames = []
        async for frame in stream.subscribe("test-activity", from_sequence=1):
            frames.append(frame)
            if isinstance(frame, TerminatedEvent):
                break
        return frames


def activities(frames):
    return [
        f
        for f in frames
        if isinstance(f, LogEvent)
        and f.data.attributes.get("sf.activity.schema") == "screamingface.activity.v1"
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("refused", [False, True])
async def test_real_round_trip_emits_safe_node_scoped_outcome(refused):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=completion(refused))

    frames = await publish(handler)
    logs = activities(frames)
    assert len(calls) == 1
    assert [r.data.attributes["sf.activity.state"] for r in logs] == [
        "started",
        "refused" if refused else "completed",
    ]
    assert logs[0].traceparent == logs[1].traceparent
    assert logs[0].data.attributes["sf.activity.id"] == logs[1].data.attributes["sf.activity.id"]
    assert "PRIVATE" not in str([r.data for r in logs])
    assert logs[-1].data.attributes["sf.activity.model_id"] == "model"


@pytest.mark.asyncio
async def test_transport_retry_emits_actual_delay_without_an_extra_call(monkeypatch):
    from screamingface_engine.runner import connector

    monkeypatch.setattr(connector, "_transport_backoff", lambda attempt: 0.0)
    attempts = 0

    def handler(request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ReadError("SECRET TRANSPORT DETAIL")
        return httpx.Response(200, json=completion())

    logs = activities(await publish(handler))
    assert attempts == 2
    assert [r.data.attributes["sf.activity.state"] for r in logs] == [
        "started",
        "retrying",
        "completed",
    ]
    assert logs[1].data.attributes["sf.activity.retry_delay_ms"] == 0
    assert "SECRET" not in str(logs)


@pytest.mark.asyncio
async def test_off_cannot_be_escalated_by_expression():
    frames = await publish(
        lambda _: httpx.Response(200, json=completion()),
        level="off",
        expression="/model(activity_level=full,'x')!go",
    )
    assert activities(frames) == []


def test_unknown_deployment_policy_fails_at_composition():
    with pytest.raises(ValueError):
        build_executor({"URL4_CLOUD_ACTIVITY_LEVEL": "aggregate"}, config())
    assert ActivityLevel("off") == ActivityLevel.OFF


@pytest.mark.asyncio
async def test_concurrent_runs_keep_distinct_occurrences():
    first, second = await asyncio.gather(
        *[publish(lambda _: httpx.Response(200, json=completion())) for _ in range(2)]
    )
    assert (
        activities(first)[0].data.attributes["sf.activity.id"]
        != (activities(second)[0].data.attributes["sf.activity.id"])
    )


@pytest.mark.asyncio
async def test_safe_failure_does_not_expose_provider_details_or_retry_http():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503, json={"detail": {"code": "PRIVATE CODE", "message": "SECRET"}})

    frames = await publish(handler)
    logs = activities(frames)
    assert len(calls) == 1
    assert [r.data.attributes["sf.activity.state"] for r in logs] == ["started", "failed"]
    assert logs[-1].data.attributes["sf.activity.failure_code"] == "internal_error"
    assert "SECRET" not in str(logs) and "PRIVATE" not in str(logs)
    assert frames[-1].data.status == "failed"


@pytest.mark.asyncio
async def test_real_wait_uses_fixed_activity_and_independent_operator_heartbeat(monkeypatch):
    from screamingface_engine.activity import scope
    from screamingface_engine.runner import connector

    release, intervals, calls = asyncio.Event(), [], []

    async def heartbeat_sleep(delay):
        intervals.append(delay)
        await asyncio.sleep(0)
        if len(intervals) >= 3:
            release.set()

    operator_started = []

    async def independent_operator(*args):
        operator_started.append(True)
        await asyncio.Event().wait()

    async def handler(request):
        calls.append(request)
        await release.wait()
        return httpx.Response(200, json=completion())

    monkeypatch.setattr(scope, "_sleep", heartbeat_sleep)
    monkeypatch.setattr(connector, "_in_flight_heartbeat", independent_operator)
    logs = activities(await publish(handler))
    assert len(calls) == 1
    assert operator_started == [True]
    assert len(intervals) >= 3 and set(intervals) == {60.0}
    assert any(r.data.attributes["sf.activity.state"] == "running" for r in logs)
    assert logs[-1].data.attributes["sf.activity.state"] == "completed"
    assert not [t for t in asyncio.all_tasks() if "Operation._heartbeat" in str(t.get_coro())]


@pytest.mark.asyncio
async def test_actual_connector_cancellation_keeps_error_and_joins_timer(monkeypatch):
    from screamingface_engine.observation_plugins import observation_factories
    from screamingface_engine.observations import RunObservations
    from screamingface_engine.runner import connector
    from url4.streaming.protocol import CachePolicy

    entered, calls, logs = asyncio.Event(), [], []

    async def handler(request):
        calls.append(request)
        entered.set()
        await asyncio.Event().wait()
        return httpx.Response(200, json=completion())

    def sink(body, attributes=None, *, severity="INFO"):
        logs.append(dict(attributes or {}))

    monkeypatch.setattr(connector, "current_log_sink", lambda: sink)
    async with httpx.AsyncClient(
        base_url="http://gateway", transport=httpx.MockTransport(handler)
    ) as client:

        async def work():
            observations = RunObservations(
                observation_factories({"URL4_CLOUD_ACTIVITY_LEVEL": "full"})
            )
            with observations.bind():
                return await connector._logged_round_trip(
                    client,
                    real_model_id="model",
                    headers={},
                    body={},
                    cache=CachePolicy(),
                    max_tokens=None,
                    operation_accounting=[],
                )

        task = asyncio.create_task(work())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert len(calls) == 1
    assert logs[-1]["sf.activity.state"] == "cancelled"
    assert not [t for t in asyncio.all_tasks() if "Operation._heartbeat" in str(t.get_coro())]


@pytest.mark.asyncio
async def test_existing_independent_client_accepts_real_model_activity_wire():
    import os
    import subprocess
    import sys
    from pathlib import Path

    frames = await publish(lambda _: httpx.Response(200, json=completion()))
    script = """
import sys
from screamingface._engine.contract import _RunState
from screamingface.events import Log
state = _RunState("/model('PRIVATE PROMPT')!go")
logs = []
for line in sys.stdin:
    accepted = state.accept(line)
    if isinstance(accepted.event, Log) and 'sf.activity.schema' in accepted.event.attributes:
        logs.append(accepted.event)
assert [log.attributes['sf.activity.state'] for log in logs] == ['started', 'completed']
assert logs[0].traceparent == logs[1].traceparent
assert accepted.outcome is not None
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        input="\n".join(f.model_dump_json(by_alias=True) for f in frames),
        text=True,
        capture_output=True,
        timeout=15,
        env={
            **os.environ,
            "PYTHONPATH": str(Path(__file__).resolve().parents[4] / "packages/screamingface/src"),
        },
    )
    assert result.returncode == 0, result.stderr


def test_real_model_activity_survives_hosted_websocket_pump():
    import json

    from fastapi.testclient import TestClient

    from screamingface_engine.adapters.inprocess import InProcessJobRunner
    from screamingface_engine.app import create_app
    from screamingface_engine.config import Settings

    stream = InMemoryEventStream()
    http_client = httpx.AsyncClient(
        base_url="http://gateway",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=completion())),
    )
    runner = InProcessJobRunner(
        stream,
        lambda env: build_executor(env, config(), client=http_client),
        base_env={"URL4_CLOUD_ACTIVITY_LEVEL": "full"},
    )
    app = create_app(
        Settings(jwt_secret="activity-test-secret-at-least-32-bytes"),
        stream=stream,
        job_runner=runner,
    )
    app.router.on_shutdown.append(runner.aclose)
    frames = []
    try:
        with TestClient(app) as client:
            token = client.post("/token").json()["token"]
            with client.websocket_connect(f"/ws?ticket={token}") as ws:
                ws.send_json(
                    {
                        "specversion": "1.0",
                        "id": "attach",
                        "source": "/test",
                        "type": "ai.url4.attach",
                        "data": {},
                    }
                )
                response = client.get(
                    "/",
                    params={"q": "/model('PRIVATE PROMPT')!go"},
                    headers={"URL4-Capability": token},
                )
                assert response.status_code == 200
                while not frames or frames[-1]["type"] != "ai.url4.terminated":
                    frames.append(json.loads(ws.receive_text()))
    finally:
        asyncio.run(http_client.aclose())
    logs = [
        f
        for f in frames
        if f["type"] == "ai.url4.log" and "sf.activity.schema" in f["data"].get("attributes", {})
    ]
    assert [f["data"]["attributes"]["sf.activity.state"] for f in logs] == ["started", "completed"]
    assert "PRIVATE" not in str([f["data"] for f in logs])
