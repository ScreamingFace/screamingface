"""Runtime status retains the serving artifact path across working directories."""

import json
from types import SimpleNamespace

from screamingface._runtime import cli
from screamingface._runtime.config import ARTIFACTS_DIR_ENV, RuntimeConfig


def serving_state(config, monkeypatch):
    record = {}
    control = SimpleNamespace(
        server_port=9999,
        serve_forever=lambda: None,
        shutdown=lambda: None,
        server_close=lambda: None,
    )
    monkeypatch.setattr(cli, "_control_server", lambda *a: control)
    monkeypatch.setattr(cli, "_write_state", lambda config, state: record.update(state))
    monkeypatch.setattr(cli, "_remove_owned_state", lambda *a: None)
    monkeypatch.setattr(cli, "_run_server", lambda *a: None)
    monkeypatch.setattr(cli.runtime_source, "resolve_source", lambda env: None)
    monkeypatch.setattr(cli.runtime_source, "state_record", lambda source: {})
    cli._serve_logged(config, "token")
    return record


def test_relative_artifacts_override_status_uses_serving_cwd(tmp_path, monkeypatch, capsys):
    serving = tmp_path / "serving"
    artifact = serving / "artifacts"
    artifact.mkdir(parents=True)
    (artifact / ("a" * 64)).write_bytes(b"hello world")
    monkeypatch.chdir(serving)
    monkeypatch.setenv(ARTIFACTS_DIR_ENV, "artifacts")
    config = RuntimeConfig(data_dir=tmp_path / "data")
    state = serving_state(config, monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "_read_state", lambda _: state)
    monkeypatch.setattr(cli, "_health", lambda services: dict.fromkeys(services, True))
    cli._print_status(config, json_output=True)
    payload = json.loads(capsys.readouterr().out)
    assert payload["artifacts_dir"] == str(artifact)
    assert payload["artifacts_bytes"] == 11
