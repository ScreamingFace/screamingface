"""Policy is deployment-owned; closing loss evidence is structured and run-local."""

import json
from dataclasses import dataclass

import pytest

from screamingface_engine.activity.contract import MAX_INTEGER
from screamingface_engine.config import Settings
from screamingface_engine.observation_plugins import observation_factories
from screamingface_engine.observations import RunObservations
from screamingface_engine.runner.cache_counters import RunCacheCounters
from screamingface_engine.runner.executor import _Bridge, _closing_logs
from screamingface_engine.worker.supervisor import RunSupervisor
from url4.observe import Log
from url4.streaming.protocol import LogData


@dataclass
class Message:
    data: bytes
    metadata: object = None

    async def ack(self) -> None:
        pass

    async def in_progress(self) -> None:
        pass


def test_settings_validate_activity_level(monkeypatch):
    monkeypatch.delenv("URL4_CLOUD_ACTIVITY_LEVEL", raising=False)
    assert Settings().activity_level == "off"
    monkeypatch.setenv("URL4_CLOUD_ACTIVITY_LEVEL", "full")
    assert Settings().activity_level == "full"
    monkeypatch.setenv("URL4_CLOUD_ACTIVITY_LEVEL", "limited")
    with pytest.raises(ValueError):
        Settings()


@pytest.mark.parametrize("deployed", [None, "off", "full"])
def test_queue_message_cannot_override_worker_activity_policy(monkeypatch, deployed):
    if deployed is None:
        monkeypatch.delenv("URL4_CLOUD_ACTIVITY_LEVEL", raising=False)
    else:
        monkeypatch.setenv("URL4_CLOUD_ACTIVITY_LEVEL", deployed)
    supervisor = object.__new__(RunSupervisor)
    monkeypatch.setattr(RunSupervisor, "_io_budget", lambda self: 1)
    msg = Message(data=json.dumps({"URL4_CLOUD_ACTIVITY_LEVEL": "full"}).encode())
    assert supervisor._child_env(msg)["URL4_CLOUD_ACTIVITY_LEVEL"] == (deployed or "off")


def test_bridge_loss_attributes_are_cumulative_safe_and_disabled_when_off():
    bridge = _Bridge(maxsize=1)
    bridge.on_event(Log(None, "INFO", "secret payload"))
    bridge.on_event(Log(None, "INFO", "secret payload"))
    with RunObservations(observation_factories({"URL4_CLOUD_ACTIVITY_LEVEL": "full"})).bind():
        frame = _closing_logs(bridge, RunCacheCounters())[0]
    assert frame.span is None
    assert isinstance(frame.payload, LogData)
    assert frame.payload.attributes == {
        "sf.telemetry.schema": "screamingface.telemetry.v1",
        "sf.telemetry.loss.scope": "engine_bridge_logs",
        "sf.telemetry.loss.dropped_total": 1,
    }
    off = _closing_logs(bridge, RunCacheCounters())[0].payload
    assert isinstance(off, LogData)
    assert off.attributes == {}
    bridge._dropped = MAX_INTEGER + 10
    with RunObservations(observation_factories({"URL4_CLOUD_ACTIVITY_LEVEL": "full"})).bind():
        saturated = _closing_logs(bridge, RunCacheCounters())[0].payload
    assert isinstance(saturated, LogData)
    assert saturated.attributes["sf.telemetry.loss.dropped_total"] == MAX_INTEGER


def test_local_invalid_activity_policy_is_rejected_before_startup():
    from screamingface_engine.local import create_local_app

    with pytest.raises(ValueError, match="ActivityLevel"):
        create_local_app(settings=Settings(), env={"URL4_CLOUD_ACTIVITY_LEVEL": "limited"})


@pytest.mark.asyncio
@pytest.mark.parametrize("level", ["off", "full"])
async def test_local_entrypoint_registers_deployment_policy(level):
    from screamingface_engine.activity.session import current_session
    from screamingface_engine.local import create_local_app

    app = create_local_app(settings=Settings(activity_level=level), env={})
    observers = RunObservations(app.state.job_runner._factory.keywords["observers"])
    with observers.bind():
        assert (current_session() is not None) == (level == "full")
    await observers.aclose()
    await app.state.job_runner.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("level,ambient", [("off", "full"), ("full", "off")])
@pytest.mark.parametrize("injected", [False, True])
async def test_explicit_local_settings_win_over_conflicting_environment(
    monkeypatch, level, ambient, injected
):
    from screamingface_engine.activity.session import current_session
    from screamingface_engine.local import create_local_app

    monkeypatch.setenv("URL4_CLOUD_ACTIVITY_LEVEL", ambient)
    app = create_local_app(
        settings=Settings(activity_level=level),
        env={"URL4_CLOUD_ACTIVITY_LEVEL": ambient} if injected else None,
    )
    observers = RunObservations(app.state.job_runner._factory.keywords["observers"])
    try:
        with observers.bind():
            assert (current_session() is not None) == (level == "full")
    finally:
        await observers.aclose()
        await app.state.job_runner.aclose()


@pytest.mark.asyncio
async def test_unset_local_settings_keep_injected_activity_policy(monkeypatch):
    from screamingface_engine.activity.session import current_session
    from screamingface_engine.local import create_local_app

    monkeypatch.delenv("URL4_CLOUD_ACTIVITY_LEVEL", raising=False)
    app = create_local_app(settings=Settings(), env={"URL4_CLOUD_ACTIVITY_LEVEL": "full"})
    observers = RunObservations(app.state.job_runner._factory.keywords["observers"])
    try:
        with observers.bind():
            assert current_session() is not None
    finally:
        await observers.aclose()
        await app.state.job_runner.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ambient,injected,enabled",
    [
        ("full", "off", False),
        ("off", "full", True),
        ("full", None, False),
        ("limited", "off", False),
    ],
)
async def test_injected_environment_wins_when_settings_are_not_supplied(
    monkeypatch, ambient, injected, enabled
):
    from screamingface_engine.activity.session import current_session
    from screamingface_engine.local import create_local_app

    monkeypatch.setenv("URL4_CLOUD_ACTIVITY_LEVEL", ambient)
    env = {} if injected is None else {"URL4_CLOUD_ACTIVITY_LEVEL": injected}
    app = create_local_app(env=env)
    observers = RunObservations(app.state.job_runner._factory.keywords["observers"])
    try:
        with observers.bind():
            assert (current_session() is not None) == enabled
    finally:
        await observers.aclose()
        await app.state.job_runner.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("ambient", ["off", "full"])
async def test_omitted_environment_uses_process_activity_policy(monkeypatch, ambient):
    from screamingface_engine.activity.session import current_session
    from screamingface_engine.local import create_local_app

    monkeypatch.setenv("URL4_CLOUD_ACTIVITY_LEVEL", ambient)
    app = create_local_app()
    observers = RunObservations(app.state.job_runner._factory.keywords["observers"])
    try:
        with observers.bind():
            assert (current_session() is not None) == (ambient == "full")
    finally:
        await observers.aclose()
        await app.state.job_runner.aclose()
