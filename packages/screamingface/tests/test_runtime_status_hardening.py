"""Status does not invent legacy serving paths or hide permission failures as zero."""

import json
import os
from pathlib import Path

import pytest

from screamingface._runtime import cli
from screamingface._runtime.config import ARTIFACTS_DIR_ENV, RuntimeConfig


def active_state(config, monkeypatch, artifacts=None):
    state = {
        "schema_version": 1,
        "pid": os.getpid(),
        "services": config.services,
        "started_at": "fixture",
    }
    if artifacts is not None:
        state["artifacts_dir"] = str(artifacts)
    monkeypatch.setattr(cli, "_read_state", lambda _: state)
    monkeypatch.setattr(cli, "_verify_owner", lambda _: True)
    monkeypatch.setattr(cli, "_health", lambda services: dict.fromkeys(services, True))
    return state


@pytest.mark.parametrize("override", [None, "different-shell-directory"])
def test_active_legacy_runtime_has_unknown_storage_and_restart_guidance(
    tmp_path, monkeypatch, capsys, override
):
    config = RuntimeConfig(data_dir=tmp_path)
    config.artifacts_dir.mkdir()
    (config.artifacts_dir / "unrelated").write_bytes(b"not the running engine")
    if override is None:
        monkeypatch.delenv(ARTIFACTS_DIR_ENV, raising=False)
    else:
        monkeypatch.setenv(ARTIFACTS_DIR_ENV, override)
    active_state(config, monkeypatch)
    assert cli._print_status(config, json_output=True) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "running"
    assert payload["artifacts_dir"] is None
    assert payload["artifacts_bytes"] is None
    assert "restart" in payload["artifacts_hint"]
    assert cli._print_status(config) == 0
    human = capsys.readouterr().out
    assert "location unknown" in human and "screamingface restart" in human
    assert str(config.artifacts_dir) not in human


@pytest.mark.skipif(
    os.name != "posix" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="requires POSIX permission enforcement for an unprivileged user",
)
@pytest.mark.parametrize("denied", ["parent", "entry"])
def test_real_permission_failure_reports_unknown_size(tmp_path, monkeypatch, capsys, denied):
    config = RuntimeConfig(data_dir=tmp_path / "data")
    parent = tmp_path / "storage-parent"
    folder = parent / "artifacts"
    folder.mkdir(parents=True)
    entry = folder / "result"
    entry.write_bytes(b"paid result")
    active_state(config, monkeypatch, folder)
    blocked = parent if denied == "parent" else folder
    blocked.chmod(0 if denied == "parent" else 0o400)
    try:
        if denied == "parent":
            with pytest.raises(PermissionError):
                folder.stat()
        else:
            assert list(folder.iterdir()) == [entry]
            with pytest.raises(PermissionError):
                entry.stat()
        assert cli._print_status(config, json_output=True) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["artifacts_dir"] == str(folder)
        assert payload["artifacts_bytes"] is None
        cli._print_status(config)
        assert "size unknown" in capsys.readouterr().out
    finally:
        blocked.chmod(0o700)


def test_size_retains_zero_when_directory_vanishes_after_stat(tmp_path, monkeypatch):
    folder = tmp_path / "artifacts"
    folder.mkdir()
    original = Path.iterdir

    def vanish(path):
        if path == folder:
            path.rmdir()
        return original(path)

    monkeypatch.setattr(Path, "iterdir", vanish)
    assert cli._artifacts_bytes(folder) == 0


def test_up_adopts_legacy_process_without_inventing_storage(tmp_path, monkeypatch, capsys):
    from screamingface._runtime import server

    config = RuntimeConfig(data_dir=tmp_path)
    state = active_state(config, monkeypatch)
    monkeypatch.setattr(server, "require_runtime_extra", lambda: None)
    monkeypatch.setattr(cli, "_ensure_adoptable", lambda _: None)
    monkeypatch.delenv("AIGATEWAY_DATABASE_URL", raising=False)
    monkeypatch.setenv(ARTIFACTS_DIR_ENV, "different-shell-directory")
    cli._up(config, foreground=False)
    assert "already running" in capsys.readouterr().out
    assert "artifacts_dir" not in state
    cli._print_status(config, json_output=True)
    assert json.loads(capsys.readouterr().out)["artifacts_dir"] is None


@pytest.mark.parametrize("recorded", ["", " ", "relative/path", 12])
def test_invalid_recorded_artifact_location_is_unknown(tmp_path, monkeypatch, capsys, recorded):
    config = RuntimeConfig(data_dir=tmp_path)
    state = active_state(config, monkeypatch)
    state["artifacts_dir"] = recorded
    cli._print_status(config, json_output=True)
    payload = json.loads(capsys.readouterr().out)
    assert payload["artifacts_dir"] is None and payload["artifacts_bytes"] is None


def test_plain_file_is_not_an_artifact_directory(tmp_path):
    path = tmp_path / "file"
    path.write_bytes(b"plain file")
    assert cli._artifacts_bytes(path) == 0
    assert cli._artifacts_bytes(path / "absent") == 0
