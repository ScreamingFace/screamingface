from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from workbench import targets
from workbench.evidence import FileLogSource, ServiceLogSource
from workbench.targets import KNOWN_TARGETS, TARGET_ENV, selected_target, start_target


def test_default_target_is_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(TARGET_ENV, raising=False)
    assert selected_target() == "replay"


def test_explicit_target_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(TARGET_ENV, "local")
    assert selected_target() == "local"


def test_unknown_target_is_refused_with_the_known_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(TARGET_ENV, "prod")
    with pytest.raises(ValueError) as caught:
        selected_target()
    assert all(name in str(caught.value) for name in KNOWN_TARGETS)


def test_start_target_refuses_an_unknown_name(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="prod"):
        with start_target("prod", tmp_path):
            pass


def test_local_target_skips_without_paid_opt_in(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SCREAMINGFACE_TEST_PAID", raising=False)
    with pytest.raises(pytest.skip.Exception, match="SCREAMINGFACE_TEST_PAID"):
        with start_target("local", tmp_path):
            pass


def test_local_target_skips_without_the_byok_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SCREAMINGFACE_TEST_PAID", "1")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(pytest.skip.Exception, match="OPENROUTER_API_KEY"):
        with start_target("local", tmp_path):
            pass


def test_replay_target_skips_through_the_e2e_gate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SCREAMINGFACE_TEST_E2E", raising=False)
    with pytest.raises(pytest.skip.Exception, match="SCREAMINGFACE_TEST_E2E"):
        with start_target("replay", tmp_path):
            pass


def _paid_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    # A placeholder key: every path below stops before anything could call a provider.
    monkeypatch.setenv("SCREAMINGFACE_TEST_PAID", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "placeholder-not-a-key")


def _no_boot(*args: str, **kw: object) -> None:
    raise AssertionError(f"the runtime must not be invoked: {args}")


def test_local_target_skips_without_prepared_ifeval_assets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _paid_opt_in(monkeypatch)
    empty = tmp_path / "assets"
    empty.mkdir()
    monkeypatch.setenv("SCREAMINGFACE_E2E_ASSETS", str(empty))
    monkeypatch.setattr(targets, "_runtime_cli", _no_boot)
    with pytest.raises(pytest.skip.Exception) as caught:
        with start_target("local", tmp_path / "work"):
            pass
    reason = str(caught.value)
    assert "ifeval" in reason and "SCREAMINGFACE_E2E_ASSETS" in reason
    # The hint names the Engine's own preparer (as screamingface-e2e-replay.yml runs it), not
    # `screamingface prepare`, which does not build ifeval.
    assert "screamingface_engine.benchmarks.prepare" in reason
    assert "--extra benchmarks" in reason and "--bundle ifeval" in reason


def _prepared_assets(tmp_path: Path) -> Path:
    root = tmp_path / "assets"
    (root / "ifeval").mkdir(parents=True)
    (root / "ifeval" / "cases.json").write_text("[]")
    return root


class _FakeEngine:
    """Stands in for harness.stack.EngineProcess; records into a shared event list."""

    url = "http://127.0.0.1:45678"

    def __init__(
        self,
        events: list[tuple[str, ...]],
        *,
        work_dir: Path,
        assets_dir: Path,
        telemetry: dict[str, str] | None = None,
    ) -> None:
        self._events = events
        self.telemetry = telemetry
        events.append(("engine-init", str(work_dir), str(assets_dir)))

    def start(self, aigateway_base_url: str) -> str:
        self._events.append(("engine-start", aigateway_base_url))
        return self.url

    def stop(self) -> None:
        self._events.append(("engine-stop",))


def _fake_stack(
    monkeypatch: pytest.MonkeyPatch, listed: list[str]
) -> tuple[list[tuple[str, ...]], list[str]]:
    events: list[tuple[str, ...]] = []
    probed: list[str] = []
    monkeypatch.setattr(targets, "_runtime_cli", lambda *args, **kw: events.append(args))
    monkeypatch.setattr(
        targets,
        "EngineProcess",
        lambda **kwargs: _FakeEngine(events, **kwargs),
    )

    def listed_at(url: str) -> list[str]:
        probed.append(url)
        return listed

    monkeypatch.setattr(targets, "_listed_benchmarks", listed_at)
    return events, probed


def test_local_target_serves_through_an_inspect_engine_on_the_up_gateway(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _paid_opt_in(monkeypatch)
    assets = _prepared_assets(tmp_path)
    monkeypatch.setenv("SCREAMINGFACE_E2E_ASSETS", str(assets))
    events, probed = _fake_stack(monkeypatch, ["ifeval", "medxpert"])
    work = tmp_path / "work"
    with start_target("local", work) as target:
        names = [e[0] for e in events]
        assert names == ["up", "engine-init", "engine-start"]
        up = events[0]
        assert up[up.index("--gateway-port") + 1] == "9105"
        # The runtime reads <data-dir>/benchmark-assets (RuntimeConfig.assets_dir).
        assert (work / "data" / "benchmark-assets").resolve() == assets.resolve()
        # The separate Engine reads the prepared root itself and logs into work_dir.
        assert events[1] == ("engine-init", str(work), str(assets))
        assert events[2] == ("engine-start", "http://127.0.0.1:9105")
        assert target.engine_url == _FakeEngine.url
        assert probed == [_FakeEngine.url]
        assert target.scoreboard_url == "http://127.0.0.1:9106"
        assert target.required_hops == ("engine", "aigateway")
        engine_src, gateway_src = target.sources
        assert isinstance(engine_src, FileLogSource)
        assert (engine_src.name, engine_src.path) == ("engine", work / "engine.log")
        assert isinstance(gateway_src, ServiceLogSource)
        assert gateway_src.name == "aigateway"
        assert gateway_src.path == work / "data" / "runtime.log"
        assert gateway_src.service == "gateway"
    assert [e[0] for e in events[-2:]] == ["engine-stop", "down"]


def test_runtime_cli_scrubs_the_foreign_gateway_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIGATEWAY_DATABASE_URL", "postgres://example.invalid/db")
    seen: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> None:
        seen.update(kwargs)

    monkeypatch.setattr(targets.subprocess, "run", fake_run)
    targets._runtime_cli("status")
    env = seen["env"]
    assert isinstance(env, dict)
    assert "AIGATEWAY_DATABASE_URL" not in env
    assert env.get("PATH") == os.environ.get("PATH")


def test_runtime_cli_child_env_is_an_allowlist_not_the_parent_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Review finding 3: a copied parent env let a forced runtime source, AIGW_* gateway
    # settings, port overrides and the provider key reach the runtime, so a green bundle
    # could come from a different source tree or a reconfigured service.
    leaks = {
        "SCREAMINGFACE_RUNTIME_SOURCE": "bundled",
        "SCREAMINGFACE_GATEWAY_PORT": "1",
        "SCREAMINGFACE_DATA_DIR": "/elsewhere",
        "AIGW_AUTH_MODE": "jwt",
        "AIGATEWAY_DATABASE_URL": "postgres://example.invalid/db",
        "SCOREBOARD_DATABASE_URL": "postgres://example.invalid/sb",
        "OPENROUTER_API_KEY": "placeholder-not-a-key",
        "PYTHONPATH": "/foreign/tree",
        "VIRTUAL_ENV": "/foreign/venv",
    }
    for name, value in leaks.items():
        monkeypatch.setenv(name, value)
    seen: dict[str, object] = {}
    monkeypatch.setattr(targets.subprocess, "run", lambda command, **kw: seen.update(kw))
    targets._runtime_cli("status")
    env = seen["env"]
    assert isinstance(env, dict)
    allowed = {"PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "SCREAMINGFACE_RUNTIME_SOURCE"}
    assert set(env) <= allowed, sorted(set(env) - allowed)
    # Pinned, not inherited: the runtime serves THIS checkout's code or refuses to start.
    assert env["SCREAMINGFACE_RUNTIME_SOURCE"] == "checkout"
    assert env.get("PATH") == os.environ.get("PATH")


def test_local_target_fails_and_tears_down_when_the_engine_does_not_list_ifeval(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # WHY a failure, not a skip: this Engine is synced with the inspect extra and handed the
    # prepared ifeval root, so not listing ifeval is a broken target, not a missing optional.
    _paid_opt_in(monkeypatch)
    monkeypatch.setenv("SCREAMINGFACE_E2E_ASSETS", str(_prepared_assets(tmp_path)))
    events, _ = _fake_stack(monkeypatch, ["medxpert"])
    with pytest.raises(RuntimeError, match=r"does not list ifeval.*medxpert"):
        with start_target("local", tmp_path / "work"):
            pass
    assert [e[0] for e in events] == ["up", "engine-init", "engine-start", "engine-stop", "down"]


def test_local_target_downs_the_runtime_when_the_engine_fails_to_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _paid_opt_in(monkeypatch)
    monkeypatch.setenv("SCREAMINGFACE_E2E_ASSETS", str(_prepared_assets(tmp_path)))
    events, _ = _fake_stack(monkeypatch, ["ifeval"])

    def boom(self: _FakeEngine, aigateway_base_url: str) -> str:
        raise RuntimeError("engine did not come up")

    monkeypatch.setattr(_FakeEngine, "start", boom)
    with pytest.raises(RuntimeError, match="engine did not come up"):
        with start_target("local", tmp_path / "work"):
            pass
    assert [e[0] for e in events] == ["up", "engine-init", "engine-stop", "down"]


def test_replay_scoreboard_is_an_explicit_loopback_placeholder() -> None:
    from screamingface.client import DEFAULT_SCOREBOARD_URL

    assert targets.REPLAY_SCOREBOARD_URL.startswith("http://127.0.0.1:")
    assert targets.REPLAY_SCOREBOARD_URL != DEFAULT_SCOREBOARD_URL


def test_local_target_downs_the_runtime_when_up_fails_partway(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # `up` can start the Gateway and then fail on the Scoreboard: `down` must still run, and
    # no Engine is built on a half-up runtime.
    _paid_opt_in(monkeypatch)
    monkeypatch.setenv("SCREAMINGFACE_E2E_ASSETS", str(_prepared_assets(tmp_path)))
    events, _ = _fake_stack(monkeypatch, ["ifeval"])

    def up_fails(*args: str, **kw: object) -> None:
        events.append(args)
        if args[0] == "up":
            raise subprocess.CalledProcessError(1, ["screamingface", "up"])

    monkeypatch.setattr(targets, "_runtime_cli", up_fails)
    with pytest.raises(subprocess.CalledProcessError):
        with start_target("local", tmp_path / "work"):
            pass
    assert [e[0] for e in events] == ["up", "down"]


def test_local_target_downs_the_runtime_when_the_engine_cannot_be_built(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _paid_opt_in(monkeypatch)
    monkeypatch.setenv("SCREAMINGFACE_E2E_ASSETS", str(_prepared_assets(tmp_path)))
    events, _ = _fake_stack(monkeypatch, ["ifeval"])

    def no_engine(**kwargs: object) -> _FakeEngine:
        raise OSError("cannot build the engine")

    monkeypatch.setattr(targets, "EngineProcess", no_engine)
    with pytest.raises(OSError, match="cannot build the engine"):
        with start_target("local", tmp_path / "work"):
            pass
    # Nothing was started on the Engine side, so there is nothing to stop — only `down`.
    assert [e[0] for e in events] == ["up", "down"]


def test_local_target_downs_the_runtime_when_engine_stop_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _paid_opt_in(monkeypatch)
    monkeypatch.setenv("SCREAMINGFACE_E2E_ASSETS", str(_prepared_assets(tmp_path)))
    events, _ = _fake_stack(monkeypatch, ["ifeval"])

    def stop_fails(self: _FakeEngine) -> None:
        events.append(("engine-stop",))
        raise RuntimeError("engine would not stop")

    monkeypatch.setattr(_FakeEngine, "stop", stop_fails)
    with pytest.raises(RuntimeError, match="engine would not stop"):
        with start_target("local", tmp_path / "work"):
            pass
    assert [e[0] for e in events] == ["up", "engine-init", "engine-start", "engine-stop", "down"]


# -- Unit 6 Task 3: both targets export spans to the workbench's OTLP receiver ---------------

_RECEIVER = "http://127.0.0.1:47000/v1/traces"
_BASE = "http://127.0.0.1:47000"
_BSP = {"OTEL_BSP_SCHEDULE_DELAY": "200"}  # unit 6 Task 4: spans reach the bundle in time


def test_local_target_points_the_runtime_and_the_engine_at_the_receiver(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _paid_opt_in(monkeypatch)
    monkeypatch.setenv("SCREAMINGFACE_E2E_ASSETS", str(_prepared_assets(tmp_path)))
    calls: list[tuple[tuple[str, ...], object]] = []
    monkeypatch.setattr(
        targets, "_runtime_cli", lambda *args, **kw: calls.append((args, kw.get("telemetry")))
    )
    engines: list[_FakeEngine] = []

    def engine(**kwargs: object) -> _FakeEngine:
        built = _FakeEngine([], **kwargs)  # type: ignore[arg-type]
        engines.append(built)
        return built

    monkeypatch.setattr(targets, "EngineProcess", engine)
    monkeypatch.setattr(targets, "_listed_benchmarks", lambda url: ["ifeval"])
    with start_target("local", tmp_path / "work", otlp_endpoint=_RECEIVER):
        pass
    # `up` (and `down`) carry the gateway's telemetry: the in-process Gateway is served by the
    # runtime's background child, which inherits the env `up` runs under.
    assert [c[0][0] for c in calls] == ["up", "down"]
    gateway_env = {"OTEL_EXPORTER_OTLP_ENDPOINT": _BASE, "OTEL_SERVICE_NAME": "aigateway", **_BSP}
    assert calls[0][1] == gateway_env
    assert engines[0].telemetry == {
        "OTEL_EXPORTER_OTLP_ENDPOINT": _BASE,
        "OTEL_SERVICE_NAME": "screamingface-engine",
        **_BSP,
    }


def test_local_target_without_a_receiver_sets_no_telemetry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _paid_opt_in(monkeypatch)
    monkeypatch.setenv("SCREAMINGFACE_E2E_ASSETS", str(_prepared_assets(tmp_path)))
    seen: list[object] = []
    monkeypatch.setattr(targets, "_runtime_cli", lambda *a, **kw: seen.append(kw.get("telemetry")))
    engines: list[_FakeEngine] = []
    monkeypatch.setattr(
        targets,
        "EngineProcess",
        lambda **kw: engines.append(_FakeEngine([], **kw)) or engines[-1],  # type: ignore[arg-type]
    )
    monkeypatch.setattr(targets, "_listed_benchmarks", lambda url: ["ifeval"])
    with start_target("local", tmp_path / "work"):
        pass
    assert seen == [{}, {}]
    assert engines[0].telemetry == {}


def test_runtime_child_env_admits_the_telemetry_and_nothing_else(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "placeholder-not-a-key")
    telemetry = {"OTEL_EXPORTER_OTLP_ENDPOINT": _BASE, "OTEL_SERVICE_NAME": "aigateway", **_BSP}
    seen: dict[str, object] = {}
    monkeypatch.setattr(targets.subprocess, "run", lambda command, **kw: seen.update(kw))
    targets._runtime_cli("up", telemetry=telemetry)
    env = seen["env"]
    assert isinstance(env, dict)
    allowed = {"PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "SCREAMINGFACE_RUNTIME_SOURCE"}
    assert set(env) - allowed == set(telemetry)
    assert {k: env[k] for k in telemetry} == telemetry


def test_runtime_cli_refuses_a_non_otel_telemetry_variable() -> None:
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        targets._runtime_cli("up", telemetry={"OPENROUTER_API_KEY": "x"})


def test_replay_target_points_the_engine_and_the_gateway_at_the_receiver(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assets = _prepared_assets(tmp_path)
    monkeypatch.setattr(targets, "require_e2e_stack", lambda: None)
    monkeypatch.setattr(targets, "assets_root", lambda: assets)
    gateways: list[dict[str, object]] = []
    stacks: list[dict[str, object]] = []

    class _Gateway:
        def __init__(self, **kwargs: object) -> None:
            gateways.append(kwargs)

    class _Stack:
        engine_url = "http://127.0.0.1:2"

    @contextmanager
    def fake_replay_stack(backend: object, **kwargs: object) -> Iterator[_Stack]:
        stacks.append(kwargs)
        yield _Stack()

    monkeypatch.setattr(targets, "CacheSeededGateway", _Gateway)
    monkeypatch.setattr(targets, "replay_stack", fake_replay_stack)
    with start_target("replay", tmp_path / "work", otlp_endpoint=_RECEIVER) as target:
        assert target.engine_url == "http://127.0.0.1:2"
    assert gateways[0]["telemetry"] == {
        "OTEL_EXPORTER_OTLP_ENDPOINT": _BASE,
        "OTEL_SERVICE_NAME": "aigateway",
        **_BSP,
    }
    assert stacks[0]["engine_telemetry"] == {
        "OTEL_EXPORTER_OTLP_ENDPOINT": _BASE,
        "OTEL_SERVICE_NAME": "screamingface-engine",
        **_BSP,
    }
