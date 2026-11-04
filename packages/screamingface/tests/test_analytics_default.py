"""Default-on enrollment includes headless execution; every opt-out wins."""

import io
import os
import subprocess
import sys
import threading
from contextlib import contextmanager

import pytest

from screamingface import analytics
from screamingface._analytics import prompt, wiring
from screamingface._analytics.local import LocalConsentStore


class MemorySink:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(event)

    def clear(self):
        self.events.clear()


@pytest.fixture
def fresh(tmp_path, monkeypatch):
    path = tmp_path / "preferences.json"
    monkeypatch.setenv("SCREAMINGFACE_ANALYTICS_CONFIG", str(path))
    monkeypatch.delenv("DO_NOT_TRACK", raising=False)
    monkeypatch.setattr(analytics, "_process_disabled", False)
    monkeypatch.setattr(analytics, "_session_only", False)
    monkeypatch.setattr(prompt, "_shown", False)
    monkeypatch.setattr(prompt, "origin", lambda: "local_jupyter")
    monkeypatch.setattr(wiring, "_coordinator", None)
    monkeypatch.setattr(wiring, "BackgroundSink", lambda *args: MemorySink())
    return path


def test_disclosure_precedes_identity_and_is_shown_once(fresh, monkeypatch, capsys):
    write = LocalConsentStore._write

    def observed(store, state):
        assert capsys.readouterr().out.splitlines() == [prompt.NOTICE]
        assert not fresh.exists()
        write(store, state)

    monkeypatch.setattr(LocalConsentStore, "_write", observed)
    prompt.offer()
    assert analytics.status()["enabled"] is True
    identifier = analytics.status()["installation_id"]
    prompt.offer()
    assert capsys.readouterr().out == ""
    assert analytics.status()["installation_id"] == identifier
    assert wiring._coordinator is None


@pytest.mark.parametrize("choice", ["accepted", "declined"])
def test_automatic_notice_preserves_saved_choice(fresh, choice, capsys):
    store = LocalConsentStore(fresh)
    saved = store.change(choice)
    prompt.offer()
    assert store.read() == saved
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("contents", ["{", "{}", '{"version": 2}', "[]"])
def test_corrupt_preferences_are_not_automatically_replaced(fresh, contents, capsys):
    fresh.write_text(contents)
    prompt.offer()
    assert fresh.read_text() == contents
    assert analytics.status()["enabled"] is False
    assert capsys.readouterr().out == ""


def test_enrollment_rechecks_decline_under_lock(fresh, monkeypatch):
    store = LocalConsentStore(fresh)
    lock = store._lock

    @contextmanager
    def competing_writer():
        store.change("declined")
        with lock():
            yield

    monkeypatch.setattr(store, "_lock", competing_writer)
    # The competing write needs the original lock, avoiding recursive test setup.
    monkeypatch.setattr(store, "change", lambda choice: LocalConsentStore(fresh).change(choice))
    assert store.enroll(lambda: True).choice == "declined"


@pytest.mark.parametrize("disabled", ["dnt", "process"])
def test_disable_before_disclosure_creates_nothing(fresh, monkeypatch, capsys, disabled):
    if disabled == "dnt":
        monkeypatch.setenv("DO_NOT_TRACK", "1")
    else:
        analytics.disable(process_only=True)
        capsys.readouterr()
    prompt.offer()
    assert not fresh.exists()
    assert capsys.readouterr().out == ""


def test_disable_during_disclosure_prevents_enrollment(fresh, monkeypatch):
    def display(*args, **kwargs):
        analytics._process_disabled = True

    monkeypatch.setattr(prompt, "show_notice", display)
    prompt.offer()
    assert not fresh.exists()


def test_failed_display_does_not_prevent_enrollment(fresh, monkeypatch):
    closed = io.StringIO()
    closed.close()
    monkeypatch.setattr(sys, "stdout", closed)
    prompt.offer()
    assert analytics.status()["enabled"] is True


class Terminal(io.StringIO):
    def isatty(self):
        return True


def test_terminal_script_uses_stderr_even_without_stdin(fresh, monkeypatch):
    stream = Terminal()
    monkeypatch.setattr(prompt, "origin", lambda: "python")
    monkeypatch.setattr(sys, "stdin", None)
    monkeypatch.setattr(sys, "stderr", stream)
    prompt.offer()
    assert stream.getvalue().splitlines() == [prompt.NOTICE]
    assert analytics.status()["enabled"] is True


def test_headless_enrolls_immediately_and_does_not_repeat_notice(fresh, monkeypatch):
    stream = io.StringIO()
    monkeypatch.setattr(prompt, "origin", lambda: "python")
    monkeypatch.setattr(sys, "stderr", stream)
    prompt.offer()
    assert analytics.status()["enabled"] is True
    assert stream.getvalue().splitlines() == [prompt.NOTICE]
    identifier = analytics.status()["installation_id"]
    prompt.offer()
    assert stream.getvalue().splitlines() == [prompt.NOTICE]
    assert analytics.status()["installation_id"] == identifier


def test_storage_failure_does_not_interrupt_import_or_evaluation(fresh, monkeypatch):
    def fail(*args):
        raise PermissionError("read only")

    monkeypatch.setattr(LocalConsentStore, "_write", fail)
    prompt.offer()
    assert not fresh.exists()
    assert analytics.status()["enabled"] is False


def test_concurrent_offers_print_once(fresh, monkeypatch):
    shown = []
    monkeypatch.setattr(prompt, "show_notice", lambda *a: shown.append(True))
    callers = [threading.Thread(target=prompt.offer) for _ in range(4)]
    for caller in callers:
        caller.start()
    for caller in callers:
        caller.join(1)
        assert not caller.is_alive()
    assert shown == [True]
    assert analytics.status()["enabled"] is True


def test_import_enrolls_only_after_terminal_disclosure(fresh):
    code = """
import io, sys
class Terminal(io.StringIO):
    def isatty(self):
        return True
sys.stderr = Terminal()
import screamingface as sf
from screamingface._analytics.prompt import NOTICE
assert sys.stderr.getvalue().splitlines() == [NOTICE]
assert sf.analytics.status()['enabled']
"""
    subprocess.run([sys.executable, "-c", code], env=os.environ.copy(), check=True, timeout=10)
    assert LocalConsentStore(fresh).read().choice == "accepted"


def test_first_evaluation_enrolls_before_operation(fresh):
    from screamingface._analytics.tracking import tracked

    @tracked("evaluation")
    def evaluate():
        assert analytics.status()["enabled"]

    evaluate()


@pytest.mark.parametrize("output", ["redirected", "missing", "closed"])
def test_headless_import_enrolls_without_emitting_events(fresh, output):
    code = """
import io, sys
if sys.argv[1] == 'missing':
    sys.stderr = None
elif sys.argv[1] == 'closed':
    sys.stderr = io.StringIO()
    sys.stderr.close()
import screamingface as sf
from screamingface._analytics import wiring
assert sf.analytics.status()['enabled']
assert wiring._coordinator is None
print('product output')
"""
    result = subprocess.run(
        [sys.executable, "-c", code, output],
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    assert result.stdout == "product output\n"
    assert result.stderr.splitlines() == ([prompt.NOTICE] if output == "redirected" else [])
    assert LocalConsentStore(fresh).read().choice == "accepted"


@pytest.mark.parametrize("value", ["1", "true", "YES", "on", "anything"])
def test_dnt_prevents_headless_import_enrollment(fresh, value):
    environment = {**os.environ, "DO_NOT_TRACK": value}
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import screamingface as sf; assert not sf.analytics.status()['enabled']",
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    assert not fresh.exists()
    assert result.stderr == ""


def test_persisted_opt_out_survives_headless_import(fresh):
    LocalConsentStore(fresh).change("declined")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import screamingface as sf; assert not sf.analytics.status()['enabled']",
        ],
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    assert LocalConsentStore(fresh).read().choice == "declined"
    assert result.stderr == ""


def test_dnt_stops_events_after_default_headless_enrollment(fresh, monkeypatch):
    sink = MemorySink()
    monkeypatch.setattr(wiring, "BackgroundSink", lambda *args: sink)
    monkeypatch.setattr(prompt, "origin", lambda: "python")
    prompt.offer()
    core = wiring.coordinator()
    operation = core.begin("evaluation", "recipe", "sync", "python", "byok")
    assert operation is not None
    assert len(sink.events) == 1
    event = sink.events[0]
    monkeypatch.setenv("DO_NOT_TRACK", "1")
    assert not analytics.status()["enabled"]
    assert not core.accepts(event), "queued events must be rejected before dispatch"
    core.finish(operation, "succeeded")
    assert core.begin("evaluation", "recipe", "sync", "python", "byok") is None
    assert len(sink.events) == 1
