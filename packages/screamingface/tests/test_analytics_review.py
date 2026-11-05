"""Regression coverage for optional setup and test-run analytics isolation."""

import asyncio
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from test_analytics_default import fresh as fresh

from screamingface import analytics
from screamingface._analytics import prompt
from screamingface._analytics.local import LocalConsentStore


@pytest.mark.parametrize("enrolled", [False, True])
def test_plain_pytest_disables_analytics_before_collection(tmp_path, enrolled):
    home = tmp_path / "home"
    home.mkdir()
    saved = home / ".screamingface" / "analytics.json"
    if enrolled:
        LocalConsentStore(saved).change("accepted")
    original = saved.read_bytes() if enrolled else None
    suite = tmp_path / "suite"
    suite.mkdir()
    shutil.copyfile(Path(__file__).with_name("conftest.py"), suite / "conftest.py")
    (suite / "test_probe.py").write_text("""
import os
import screamingface as sf
from screamingface._analytics import prompt, wiring
from screamingface._analytics.delivery import BackgroundSink
assert os.environ.get("DO_NOT_TRACK") == "1"
assert not sf.analytics.status()["enabled"]

def test_evaluation_cannot_send(monkeypatch):
    def forbidden(*args):
        raise AssertionError("test attempted to emit analytics")
    monkeypatch.setattr(BackgroundSink, "emit", forbidden)
    monkeypatch.setattr(prompt, "_shown", False)
    monkeypatch.setattr(wiring, "_coordinator", None)
    prompt.before_evaluation()
    assert not sf.analytics.status()["enabled"]
    assert wiring.coordinator().begin("evaluation", "recipe", "sync", "python", "byok") is None
    assert not os.path.exists(os.environ["SCREAMINGFACE_ANALYTICS_CONFIG"])
""")
    environment = {**os.environ, "HOME": str(home), "USERPROFILE": str(home)}
    for name in ("DO_NOT_TRACK", "SCREAMINGFACE_ANALYTICS_CONFIG", "PYTEST_ADDOPTS"):
        environment.pop(name, None)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", str(suite)],
        cwd=suite,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (saved.read_bytes() if saved.exists() else None) == original


@pytest.mark.parametrize("error", [AttributeError, TypeError, LookupError])
def test_unexpected_setup_failure_does_not_escape(fresh, monkeypatch, caplog, error):
    def unavailable(*args):
        raise error("private preference details")

    monkeypatch.setattr(LocalConsentStore, "missing", unavailable)
    with caplog.at_level("DEBUG", logger=prompt.__name__):
        prompt.before_evaluation()
    assert not fresh.exists()
    assert [record.getMessage() for record in caplog.records] == ["Analytics setup skipped"]


@pytest.mark.parametrize("error", [KeyboardInterrupt, SystemExit, asyncio.CancelledError])
def test_setup_does_not_swallow_interruptions(fresh, monkeypatch, error):
    def interrupted(*args):
        raise error()

    monkeypatch.setattr(LocalConsentStore, "missing", interrupted)
    with pytest.raises(error):
        prompt.offer()


@pytest.mark.asyncio
async def test_local_async_enrollment_does_not_block_loop(fresh, monkeypatch):
    release = threading.Event()
    entered = asyncio.Event()
    loop = asyncio.get_running_loop()
    enroll = LocalConsentStore.enroll

    def waiting_enrollment(store, allowed):
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(1), "enrollment blocked the event loop"
        return enroll(store, allowed)

    async def release_from_loop():
        await asyncio.wait_for(entered.wait(), timeout=2)
        release.set()

    monkeypatch.setattr(LocalConsentStore, "enroll", waiting_enrollment)
    try:
        await asyncio.gather(prompt.before_evaluation_async(), release_from_loop())
        assert analytics.status()["enabled"]
    finally:
        release.set()


def test_import_survives_unexpected_preference_error(fresh):
    code = """
import pathlib
original = pathlib.Path.lstat
def broken(path, *args, **kwargs):
    if path.name == "preferences.json":
        raise AttributeError("private preference details")
    return original(path, *args, **kwargs)
pathlib.Path.lstat = broken
import screamingface as sf
assert sf.__version__
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert not fresh.exists()


@pytest.mark.asyncio
async def test_unavailable_executor_does_not_block_local_evaluation(fresh, monkeypatch):
    async def unavailable(*args):
        raise RuntimeError("cannot schedule new futures after shutdown")

    monkeypatch.setattr(asyncio, "to_thread", unavailable)
    await prompt.before_evaluation_async()
    assert not fresh.exists()


@pytest.mark.asyncio
async def test_completed_local_setup_does_not_queue_more_work(fresh, monkeypatch):
    await prompt.before_evaluation_async()
    assert analytics.status()["enabled"]
    calls = []

    async def unexpected(*args):
        calls.append(args)

    monkeypatch.setattr(asyncio, "to_thread", unexpected)
    await prompt.before_evaluation_async()
    assert calls == []
