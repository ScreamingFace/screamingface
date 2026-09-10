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
