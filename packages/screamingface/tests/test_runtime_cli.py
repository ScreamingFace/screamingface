from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import types
from pathlib import Path

import pytest

from screamingface._runtime import cli, runtime_logging
from screamingface._runtime.bootstrap import enable_local_providers, scoreboard_seed_json
from screamingface._runtime.config import RuntimeConfig


def test_parser_exposes_public_commands() -> None:
    parser = cli._parser()

    for command in ("up", "down", "restart", "status", "logs", "prepare", "doctor"):
        assert parser.parse_args([command]).command == command


def test_data_dir_is_accepted_before_or_after_the_command(tmp_path: Path) -> None:
    parser = cli._parser()

    assert parser.parse_args(["--data-dir", str(tmp_path), "up"]).data_dir == tmp_path
    assert parser.parse_args(["up", "--data-dir", str(tmp_path)]).data_dir == tmp_path


def test_runtime_data_is_user_scoped(tmp_path: Path) -> None:
    config = RuntimeConfig(data_dir=tmp_path)

    assert config.state_path == tmp_path / "runtime.json"
    assert config.log_path == tmp_path / "runtime.log"
    assert config.assets_dir == tmp_path / "benchmark-assets"


def test_runtime_ports_are_configurable_and_unique(tmp_path: Path) -> None:
    config = RuntimeConfig(
        data_dir=tmp_path, gateway_port=19105, scoreboard_port=19106, engine_port=19108
    )

    assert config.services == {
        "gateway": "http://127.0.0.1:19105",
        "scoreboard": "http://127.0.0.1:19106",
        "engine": "http://127.0.0.1:19108",
    }
    with pytest.raises(ValueError, match="unique"):
        RuntimeConfig(data_dir=tmp_path, gateway_port=19105, scoreboard_port=19105)


def test_port_configuration_prefers_flags_then_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SCREAMINGFACE_GATEWAY_PORT", "18105")
    args = cli._parser().parse_args(["--data-dir", str(tmp_path), "up", "--gateway-port", "19105"])

    config = cli._config(args)

    assert config.gateway_port == 19105
    assert config.scoreboard_port == 9106


def test_recovery_commands_ignore_invalid_port_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SCREAMINGFACE_GATEWAY_PORT", "invalid")
    args = cli._parser().parse_args(["--data-dir", str(tmp_path), "down"])

    config = cli._config(args)

    assert config.gateway_port == 9105


def test_owned_state_is_removed_but_foreign_state_is_preserved(tmp_path: Path) -> None:
    config = RuntimeConfig(data_dir=tmp_path)
    config.state_path.write_text(json.dumps({"pid": 42, "owner_token": "ours"}))

    cli._remove_owned_state(config, "theirs")
    assert config.state_path.exists()
    cli._remove_owned_state(config, "ours")
    assert not config.state_path.exists()


def test_state_is_written_atomically_with_private_permissions(tmp_path: Path) -> None:
    config = RuntimeConfig(data_dir=tmp_path)

    cli._write_state(config, {"pid": 42, "owner_token": "secret"})

    assert json.loads(config.state_path.read_text()) == {"pid": 42, "owner_token": "secret"}
    if os.name != "nt":
        assert config.state_path.stat().st_mode & 0o777 == 0o600
    assert not list(tmp_path.glob("*.tmp"))


def test_control_endpoint_proves_identity_and_accepts_authenticated_shutdown() -> None:
    stopped = threading.Event()
    server = cli._control_server("ours", stopped)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    state: dict[str, object] = {
        "pid": os.getpid(),
        "owner_token": "ours",
        "control_url": f"http://127.0.0.1:{server.server_port}",
    }
    try:
        assert cli._verify_owner(state)
        foreign = dict(state)
        foreign["owner_token"] = "theirs"
        assert not cli._verify_owner(foreign)
        cli._request_shutdown(state)
        assert stopped.wait(1)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_json_status_is_stable_and_redacts_the_owner_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = RuntimeConfig(data_dir=tmp_path)
    state = {
        "schema_version": 1,
        "pid": 42,
        "started_at": "now",
        "owner_token": "secret",
        "services": config.services,
    }
    cli._write_state(config, state)
    monkeypatch.setattr(cli, "_verify_owner", lambda _state: True)
    monkeypatch.setattr(cli, "_health", lambda services: dict.fromkeys(services, True))

    assert cli._print_status(config, json_output=True) == 0

    output = capsys.readouterr().out
    assert "secret" not in output
    assert json.loads(output)["schema"] == "screamingface.runtime-status.v1"


def test_status_rejects_owned_state_without_services(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = RuntimeConfig(data_dir=tmp_path)
    cli._write_state(config, {"schema_version": 1, "pid": 42, "owner_token": "secret"})
    monkeypatch.setattr(cli, "_verify_owner", lambda _state: True)
    monkeypatch.setattr(cli, "_health", lambda services: dict.fromkeys(services, True))

    assert cli._print_status(config, json_output=True) == 1

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "invalid_runtime_state"
    assert output["ownership_verified"] is False
    assert output["state_valid"] is False


def test_down_never_signals_an_unverified_pid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = RuntimeConfig(data_dir=tmp_path)
    cli._write_state(config, {"pid": os.getpid(), "owner_token": "stale"})
    monkeypatch.setattr(cli, "_verify_owner", lambda _state: False)

    cli._down(config)

    assert "no owned ScreamingFace runtime was stopped" in capsys.readouterr().out
    assert not config.state_path.exists()


def test_connection_diagnostic_requires_an_active_connection() -> None:
    assert not cli._has_connections({"data": [{"provider": "codex", "status": "not_connected"}]})
    assert cli._has_connections({"data": [{"provider": "codex", "status": "connected"}]})


def test_logs_rejects_negative_tail(tmp_path: Path) -> None:
    config = RuntimeConfig(data_dir=tmp_path)

    with pytest.raises(RuntimeError, match="zero or greater"):
        cli._logs(config, tail=-1, follow=False)


def test_runtime_log_prefixes_services_and_rotates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "runtime.log"
    monkeypatch.setattr(runtime_logging, "MAX_LOG_BYTES", 100)
    monkeypatch.setattr(runtime_logging, "LOG_BACKUPS", 2)
    log = runtime_logging.RuntimeLog(path)

    with runtime_logging.log_service("engine"):
        log.write("first engine line\n")
        log.write("x" * 100 + "\n")
    with runtime_logging.log_service("gateway"):
        log.write("gateway line\n")
    log.close()

    rendered = "".join(candidate.read_text() for candidate in cli._log_paths(path))
    assert "[engine] first engine line" in rendered
    assert "[gateway] gateway line" in rendered
    assert path.with_name("runtime.log.1").exists()


def test_logs_filter_by_service(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = RuntimeConfig(data_dir=tmp_path)
    config.log_path.write_text("time [engine] one\ntime [gateway] two\n")

    cli._logs(config, tail=10, follow=False, service="engine")

    assert capsys.readouterr().out == "time [engine] one\n"


def test_benchmark_manifest_distinguishes_prepared_stale_and_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = RuntimeConfig(data_dir=tmp_path)
    destination = config.assets_dir / "draco"
    destination.mkdir(parents=True)
    monkeypatch.setattr(cli, "_benchmark_fingerprint", lambda _name: "draco:revision")

    assert cli._benchmark_status(config, "draco") == "incomplete"
    for relative in ("criteria", "rubrics"):
        (destination / relative).mkdir()
    (destination / "cases.json").write_text('[{"id":1}]')
    cli._write_json_atomic(
        cli._benchmark_manifest_path(destination),
        {"fingerprint": "draco:old"},
    )
    assert cli._benchmark_status(config, "draco") == "stale"
    cli._write_json_atomic(
        cli._benchmark_manifest_path(destination),
        {"fingerprint": "draco:revision"},
    )
    assert cli._benchmark_status(config, "draco") == "prepared"


@pytest.mark.parametrize("name", ("draco", "ifeval", "healthbench"))
def test_benchmark_fingerprint_uses_engine_preparation_revision(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    imported: list[str] = []

    def import_module(module: str) -> object:
        imported.append(module)
        return type("Preparation", (), {"DATASET_REVISION": "revision"})

    monkeypatch.setattr(cli.importlib, "import_module", import_module)

    assert cli._benchmark_fingerprint(name) == f"{name}:revision"
    assert imported == [f"screamingface_engine.benchmarks.{name}.prepare"]


def test_prepare_list_rejects_mutating_options(tmp_path: Path) -> None:
    config = RuntimeConfig(data_dir=tmp_path)

    with pytest.raises(RuntimeError, match="cannot be combined"):
        cli._prepare(
            config,
            "draco",
            all_benchmarks=False,
            list_benchmarks=True,
            force=False,
        )


def test_plain_sdk_import_does_not_load_server_packages() -> None:
    output = subprocess.check_output(
        [
            sys.executable,
            "-c",
            "import sys, screamingface; "
            "print(any(name in sys.modules "
            "for name in ('uvicorn', 'aigateway', 'screamingface_engine')))",
        ],
        text=True,
    )

    assert output.strip() == "False"


def test_local_runtime_enables_openrouter_without_overriding_an_explicit_choice() -> None:
    default_environment: dict[str, str] = {}
    disabled_environment = {"AIGW_OPENROUTER_ENABLED": "false"}

    enable_local_providers(default_environment)
    enable_local_providers(disabled_environment)

    # WHY no exact-dict assert since OME-1001: the local default set grew; this test
    # keeps guarding only its original invariant — the default enables, an explicit
    # choice survives.
    assert default_environment["AIGW_OPENROUTER_ENABLED"] == "true"
    assert disabled_environment["AIGW_OPENROUTER_ENABLED"] == "false"


def test_local_gateway_defaults_provide_exactly_the_required_environment() -> None:
    # FEATURE: one stack command (OME-1001) — the runtime itself supplies the env the
    # local stack needs, or local evals regress the moment it starts any other way.
    environment: dict[str, str] = {}

    enable_local_providers(environment)

    assert environment == {
        "AIGW_OPENROUTER_ENABLED": "true",
        # WHY 32: one Engine run fans out up to 32 concurrent model calls but the
        # gateway's per-provider default admits 4 — queued calls burn the Engine's
        # 600s per-call budget and full HealthBench evals die (OME-889).
        "AIGW_PROVIDER_MAX_CONCURRENCY_OVERRIDES": '{"openrouter": 32}',
    }
    # INVARIANT: provider credential bootstrap stays opt-in — the gateway's own
    # consent rule; the runtime never defaults AIGATEWAY_BOOTSTRAP_FROM_CLAUDE_CODE.
    assert "AIGATEWAY_BOOTSTRAP_FROM_CLAUDE_CODE" not in environment


def test_local_gateway_defaults_never_override_an_explicit_operator_choice() -> None:
    explicit = {
        "AIGW_OPENROUTER_ENABLED": "false",
        "AIGW_PROVIDER_MAX_CONCURRENCY_OVERRIDES": '{"openrouter": 4}',
    }

    environment = dict(explicit)
    enable_local_providers(environment)

    assert environment == explicit


def _running_state(config: RuntimeConfig, source_record: dict[str, object] | None) -> None:
    state: dict[str, object] = {
        "schema_version": 1,
        "pid": 42,
        "owner_token": "secret",
        "services": config.services,
    }
    if source_record is not None:
        state["source"] = source_record
    cli._write_state(config, state)


def _stub_runtime_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    # WHY a sys.modules stub: the server module imports uvicorn at import time, and
    # the SDK test environment deliberately installs no runtime extra.
    module = types.ModuleType("screamingface._runtime.server")
    module.require_runtime_extra = lambda: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "screamingface._runtime.server", module)


def _healthy_owned_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_runtime_extra(monkeypatch)
    monkeypatch.setattr(cli, "_verify_owner", lambda _state: True)
    monkeypatch.setattr(cli, "_health", lambda services: dict.fromkeys(services, True))


def test_up_adopts_a_healthy_stack_from_the_same_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = RuntimeConfig(data_dir=tmp_path)
    _running_state(config, {"mode": "bundled", "root": None})
    _healthy_owned_runtime(monkeypatch)
    monkeypatch.setenv("SCREAMINGFACE_RUNTIME_SOURCE", "bundled")

    cli._up(config, foreground=False)

    assert "already running" in capsys.readouterr().out


def test_up_refuses_a_healthy_stack_owned_by_a_different_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # INVARIANT (OME-1001): two worktrees must not silently share one stack — a
    # benchmark would run another branch's code and produce results that look
    # right but aren't.
    config = RuntimeConfig(data_dir=tmp_path)
    _running_state(config, {"mode": "checkout", "root": "/somewhere/else"})
    _healthy_owned_runtime(monkeypatch)
    monkeypatch.setenv("SCREAMINGFACE_RUNTIME_SOURCE", "bundled")

    with pytest.raises(RuntimeError, match="screamingface down"):
        cli._up(config, foreground=False)


def test_up_still_adopts_state_written_before_source_records_existed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # WHY: a stack started by a pre-OME-1001 build carries no source record; there
    # is no identity to compare, so adoption keeps working across the upgrade.
    config = RuntimeConfig(data_dir=tmp_path)
    _running_state(config, None)
    _healthy_owned_runtime(monkeypatch)
    monkeypatch.setenv("SCREAMINGFACE_RUNTIME_SOURCE", "bundled")

    cli._up(config, foreground=False)

    assert "already running" in capsys.readouterr().out


def test_up_refuses_a_partially_healthy_stack_owned_by_a_different_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # WHY: covering only the all-healthy branch would walk the user into `restart`
    # via the partially-healthy advice — silently replacing the other checkout's
    # stack.
    config = RuntimeConfig(data_dir=tmp_path)
    _running_state(config, {"mode": "checkout", "root": "/somewhere/else"})
    _stub_runtime_extra(monkeypatch)
    monkeypatch.setattr(cli, "_verify_owner", lambda _state: True)
    monkeypatch.setattr(cli, "_health", lambda services: dict.fromkeys(services, False))
    monkeypatch.setenv("SCREAMINGFACE_RUNTIME_SOURCE", "bundled")

    with pytest.raises(RuntimeError, match="screamingface down"):
        cli._up(config, foreground=False)


def test_restart_refuses_to_tear_down_another_checkouts_stack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # INVARIANT: restart = down + up, so it must refuse a foreign stack the same way
    # `up` does — otherwise it silently replaces another checkout's running services.
    config = RuntimeConfig(data_dir=tmp_path)
    _running_state(config, {"mode": "checkout", "root": "/somewhere/else"})
    _healthy_owned_runtime(monkeypatch)
    monkeypatch.setenv("SCREAMINGFACE_RUNTIME_SOURCE", "bundled")
    args = cli._parser().parse_args(["--data-dir", str(tmp_path), "restart"])

    with pytest.raises(RuntimeError, match="screamingface down"):
        cli._restart(config, args, foreground=False)

    # Refusal means the other stack was left untouched.
    assert config.state_path.exists()


def test_recovery_commands_ignore_an_invalid_runtime_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # WHY: `down` and `logs` are how a user recovers from a broken environment; a
    # typoed SCREAMINGFACE_RUNTIME_SOURCE must not lock them out (mirrors the
    # recovery-command rule for invalid port environments above).
    monkeypatch.setenv("SCREAMINGFACE_RUNTIME_SOURCE", "editable")

    cli.main(["--data-dir", str(tmp_path), "down"])

    assert "not running" in capsys.readouterr().out


def test_up_surfaces_an_invalid_runtime_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SCREAMINGFACE_RUNTIME_SOURCE", "editable")

    with pytest.raises(SystemExit, match="SCREAMINGFACE_RUNTIME_SOURCE"):
        cli.main(["--data-dir", str(tmp_path), "up"])


def test_prepare_children_inherit_the_live_checkout_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from screamingface._runtime import source as runtime_source

    config = RuntimeConfig(data_dir=tmp_path)
    checkout = runtime_source.RuntimeSource(
        mode=runtime_source.MODE_CHECKOUT, root=tmp_path / "monorepo"
    )
    recorded: dict[str, object] = {}

    def record_run(command: list[str], *, check: bool, env: dict[str, str]) -> None:
        recorded["env"] = env

    _stub_runtime_extra(monkeypatch)
    monkeypatch.setattr(runtime_source, "resolve_source", lambda _environment: checkout)
    monkeypatch.setattr(cli, "_benchmark_status", lambda _config, _name: "missing")
    monkeypatch.setattr(cli, "_validate_benchmark_output", lambda _name, _out: ["cases.json"])
    monkeypatch.setattr(cli, "_benchmark_fingerprint", lambda _name: "draco:revision")
    monkeypatch.setattr(cli.subprocess, "run", record_run)

    cli._prepare(config, "draco", all_benchmarks=False)

    # INVARIANT: the preparer child is a fresh interpreter with no sys.path
    # activation of its own — PYTHONPATH is how the live engine code reaches it.
    environment = recorded["env"]
    assert isinstance(environment, dict)
    assert str(tmp_path / "monorepo" / "apps/screamingface-engine/src") in environment[
        "PYTHONPATH"
    ].split(os.pathsep)


def test_scoreboard_seed_is_derived_from_engine_benchmark_identity() -> None:
    class Benchmark:
        id = "ifeval"
        title = "IFEval"
        description = "Deterministic instruction following"
        revision = "revision-from-engine"

    assert json.loads(scoreboard_seed_json([Benchmark()])) == [
        {
            "id": "ifeval",
            "display_name": "IFEval",
            "description": "Deterministic instruction following",
            "revision": "revision-from-engine",
        }
    ]


def test_the_local_projection_carries_the_leaderboard_display_fields() -> None:
    # INVARIANT: the local board must show what the deployed board shows (OME-904). The Engine
    # publishes focus and dataset_url in its catalogue; a local stack reads the same registry by
    # import, so dropping them here would make a local leaderboard quietly poorer than the real
    # one — the two projections have to stay in step.
    class Benchmark:
        id = "draco"
        title = "DRACO"
        description = "Research reports"
        revision = "revision-from-engine"
        focus = "Research reports with citations"
        dataset_url = "https://huggingface.co/datasets/perplexity-ai/draco"

    projected = json.loads(scoreboard_seed_json([Benchmark()]))[0]

    assert projected["focus"] == "Research reports with citations"
    assert projected["dataset_url"] == "https://huggingface.co/datasets/perplexity-ai/draco"


def test_the_local_projection_omits_display_fields_a_benchmark_did_not_declare() -> None:
    # WHY omit rather than send null: the seed contract forbids unknown keys and treats an
    # absent optional as "leave it alone", which is what an undeclared focus line means.
    class Benchmark:
        id = "ifeval"
        title = "IFEval"
        description = "Deterministic instruction following"
        revision = "revision-from-engine"
        focus = None
        dataset_url = None

    projected = json.loads(scoreboard_seed_json([Benchmark()]))[0]

    assert "focus" not in projected
    assert "dataset_url" not in projected
