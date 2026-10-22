"""The replay harness hands its children an OTLP endpoint, and nothing else (unit 6, Task 3).

Default lane: no docker, no subprocess. ``ManagedProcess`` is replaced by a recorder, so these
pin the ENVIRONMENT a child would get, which is the whole contract: the clean-env rule
(``harness._local_proc``) admits exactly the ``OTEL_*`` telemetry variables a caller passes,
and refuses any other name, so the telemetry seam can never become a way to leak a key.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from harness import cache_seeded, stack
from harness._local_proc import telemetry_env
from harness.cache_seeded import CacheSeededGateway
from harness.stack import EngineProcess

_OTEL = {
    "OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:4318",
    "OTEL_SERVICE_NAME": "svc",
}


class _Recorder:
    """Stands in for ``ManagedProcess``: records the env, starts nothing."""

    seen: list[dict[str, str]] = []

    def __init__(self, *, env: dict[str, str], **_: Any) -> None:
        _Recorder.seen.append(env)

    def start(self, health_url: str) -> None:
        pass

    def stop(self) -> None:
        pass


@pytest.fixture
def recorded(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[dict[str, str]]:
    _Recorder.seen = []
    for module in (stack, cache_seeded):
        monkeypatch.setattr(module, "ManagedProcess", _Recorder)
        monkeypatch.setattr(module, "sync_project", lambda *a, **k: None)
        monkeypatch.setattr(module, "venv_bin", lambda d, exe: tmp_path / exe)
    return _Recorder.seen


def test_telemetry_env_is_empty_without_an_endpoint() -> None:
    assert telemetry_env(None, service="aigateway") == {}


def test_telemetry_env_turns_the_receiver_url_into_the_otlp_base() -> None:
    # WHY the base: the generic variable is a BASE the exporters extend with /v1/traces
    # (engine tracing.otlp._endpoint, the OTel SDK); the full URL would post to
    # /v1/traces/v1/traces and be refused 404.
    env = telemetry_env("http://127.0.0.1:5555/v1/traces", service="aigateway")
    assert env == {
        "OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:5555",
        "OTEL_SERVICE_NAME": "aigateway",
    }


def test_engine_process_passes_telemetry_through(
    recorded: list[dict[str, str]], tmp_path: Path
) -> None:
    EngineProcess(work_dir=tmp_path, telemetry=_OTEL).start("http://127.0.0.1:1")
    (env,) = recorded
    assert {k: env[k] for k in _OTEL} == _OTEL
    assert env["AIGATEWAY_BASE_URL"] == "http://127.0.0.1:1"


def test_engine_process_without_telemetry_sets_no_otel_variable(
    recorded: list[dict[str, str]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The shell's own OTEL_* never reaches a child: the clean-env rule, not discipline.
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector.example.invalid")
    EngineProcess(work_dir=tmp_path).start("http://127.0.0.1:1")
    (env,) = recorded
    assert not [k for k in env if k.startswith("OTEL_")]


def test_cache_seeded_gateway_passes_telemetry_through(
    recorded: list[dict[str, str]], tmp_path: Path
) -> None:
    gateway = CacheSeededGateway(
        snapshot=tmp_path / "s.gz", manifest=None, work_dir=tmp_path, telemetry=_OTEL
    )
    gateway._start_gateway("postgres://u:p@127.0.0.1:1/db")
    (env,) = recorded
    assert {k: env[k] for k in _OTEL} == _OTEL
    assert env["AIGW_AUTH_MODE"] == "disabled"


@pytest.mark.parametrize(
    "build",
    [
        lambda tmp, env: EngineProcess(work_dir=tmp, telemetry=env),
        lambda tmp, env: CacheSeededGateway(
            snapshot=tmp / "s.gz", manifest=None, work_dir=tmp, telemetry=env
        ),
    ],
    ids=["engine", "gateway"],
)
@pytest.mark.parametrize(
    "name", ["OPENROUTER_API_KEY", "AIGW_AUTH_MODE", "AIGATEWAY_BASE_URL", "PYTHONPATH"]
)
def test_telemetry_refuses_any_non_otel_variable(build: Any, name: str, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=name):
        build(tmp_path, {name: "x"})


def test_replay_stack_hands_the_engine_its_telemetry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    built: list[dict[str, Any]] = []

    class _Engine:
        def __init__(self, **kwargs: Any) -> None:
            built.append(kwargs)

        def start(self, url: str) -> str:
            return "http://127.0.0.1:2"

        def stop(self) -> None:
            pass

    class _Backend:
        async def start(self) -> str:
            return "http://127.0.0.1:1"

        async def stop(self) -> None:
            pass

    monkeypatch.setattr(stack, "EngineProcess", _Engine)
    with stack.replay_stack(_Backend(), work_dir=tmp_path, engine_telemetry=_OTEL):
        pass
    assert built[0]["telemetry"] == _OTEL
