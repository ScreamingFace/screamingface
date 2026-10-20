"""Consent and continuity must precede every event, independently of product auth."""

import json
from uuid import UUID

import pytest

from screamingface import analytics
from screamingface._analytics.local import LocalConsentStore


@pytest.fixture
def config(tmp_path, monkeypatch):
    path = tmp_path / "analytics.json"
    monkeypatch.setenv("SCREAMINGFACE_ANALYTICS_CONFIG", str(path))
    monkeypatch.delenv("DO_NOT_TRACK", raising=False)
    analytics.disable(process_only=True)
    yield path
    analytics.disable(process_only=True)


def test_status_does_not_create_identity_or_storage(config):
    assert analytics.status()["choice"] == "unknown"
    assert not config.exists()


def test_enable_reuses_id_reset_rotates_and_disable_removes_it(config):
    first = analytics.enable()["installation_id"]
    assert UUID(first).version == 4
    assert analytics.enable()["installation_id"] == first
    assert analytics.reset_identifier()["installation_id"] != first
    assert config.stat().st_mode & 0o777 == 0o600
    assert analytics.disable()["choice"] == "declined"
    assert "installation_id" not in json.loads(config.read_text())
    assert analytics.reset_identifier()["choice"] == "declined"


@pytest.mark.parametrize("contents", ["{", "{}", '{"choice":"accepted"}', "[]"])
def test_bad_state_fails_off(config, contents):
    config.write_text(contents)
    assert LocalConsentStore(config).read().choice == "unknown"


def test_dnt_overrides_explicit_enable(config, monkeypatch):
    monkeypatch.setenv("DO_NOT_TRACK", "1")
    assert analytics.enable()["enabled"] is False
    assert not config.exists()


def test_session_only_enable_does_not_claim_persistence(config):
    state = analytics.enable(persist=False)
    assert state["enabled"] is True
    assert state["scope"] == "session"
    assert not config.exists()


def test_cli_preferences_do_not_start_runtime(config, capsys, monkeypatch):
    from screamingface._runtime import cli

    def forbidden(*args):
        raise AssertionError("Analytics controls must not activate runtime services")

    monkeypatch.setattr(cli.runtime_source, "activate", forbidden)
    cli.main(["analytics", "enable"])
    assert json.loads(capsys.readouterr().out)["enabled"] is True
    cli.main(["analytics", "disable"])
    assert json.loads(capsys.readouterr().out)["enabled"] is False


def test_concurrent_processes_share_one_installation(config):
    import os
    import subprocess
    import sys

    code = "from screamingface import analytics; print(analytics.enable()['installation_id'])"
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", code], env=os.environ.copy(), stdout=subprocess.PIPE, text=True
        )
        for _ in range(4)
    ]
    identifiers = [p.communicate(timeout=15)[0].strip() for p in processes]
    assert all(p.returncode == 0 for p in processes)
    assert len(set(identifiers)) == 1
    assert UUID(identifiers[0]).version == 4


def test_stale_consent_and_invalid_uuid_fail_off(config):
    for version, identifier in [("2", "5ee8e0bd-916b-42fa-a3fa-df1de9d1f9d7"), ("1", "not-an-id")]:
        config.write_text(
            json.dumps(
                {
                    "version": 1,
                    "consent_version": version,
                    "choice": "accepted",
                    "installation_id": identifier,
                }
            )
        )
        assert LocalConsentStore(config).read().choice == "unknown"


def test_preferences_lock_is_bounded(config):
    with LocalConsentStore(config)._lock():
        with pytest.raises(OSError, match="busy"):
            analytics.enable()
    assert not config.exists()


def test_unwritable_choice_is_not_silently_persisted(config, monkeypatch):
    def fail(*args):
        raise PermissionError("read only")

    monkeypatch.setattr(LocalConsentStore, "_write", fail)
    with pytest.raises(PermissionError):
        analytics.enable()
    assert not config.exists()
    # The inode remains, but ownership was released after the failed write.
    with LocalConsentStore(config)._lock():
        pass


def test_setup_notice_once_without_waiting(config, monkeypatch, capsys):
    from screamingface._analytics import prompt

    analytics._process_disabled = False
    monkeypatch.setattr(prompt, "_shown", False)
    monkeypatch.setattr(prompt, "origin", lambda: "local_jupyter")
    prompt.offer()
    prompt.offer()
    assert capsys.readouterr().out.count("Optional ScreamingFace analytics") == 1
    assert not config.exists()
    assert analytics.status()["enabled"] is False


def test_colab_is_deferred(config, monkeypatch):
    import sys
    import types

    monkeypatch.setitem(sys.modules, "google.colab", types.ModuleType("google.colab"))
    assert analytics.enable()["enabled"] is False
    assert not config.exists()


def test_symlinked_preferences_do_not_enable_collection(config):
    target = config.with_name("other.json")
    LocalConsentStore(target).change("accepted")
    config.symlink_to(target)
    assert LocalConsentStore(config).read().choice == "unknown"


def test_crashed_writer_does_not_block_persisted_opt_out(config):
    import subprocess
    import sys

    analytics.enable()
    code = """
import time
from screamingface._analytics.local import LocalConsentStore, config_path
with LocalConsentStore(config_path())._lock():
    print('locked', flush=True)
    time.sleep(30)
"""
    writer = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    try:
        assert writer.stdout is not None
        assert writer.stdout.readline().strip() == "locked"
        writer.kill()
        writer.wait(timeout=5)
        assert analytics.disable()["choice"] == "declined"
        check = subprocess.run(
            [
                sys.executable,
                "-c",
                "from screamingface import analytics; print(analytics.status()['enabled'])",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        assert check.stdout.strip() == "False"
    finally:
        if writer.poll() is None:
            writer.kill()
            writer.wait(timeout=5)
