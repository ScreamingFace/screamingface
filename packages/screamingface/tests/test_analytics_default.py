"""Disclosure precedes automatic enrollment; opt-out always wins."""

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
    return path


def test_disclosure_precedes_identity_and_is_shown_once(fresh, monkeypatch, capsys):
    write = LocalConsentStore._write

    def observed(store, state):
        assert prompt.NOTICE in capsys.readouterr().out
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


def test_failed_display_does_not_enroll_and_can_retry(fresh, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("output closed")

    with monkeypatch.context() as patch:
        patch.setattr(prompt, "show_notice", fail)
        prompt.offer()
    assert not fresh.exists()
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
    assert prompt.NOTICE in stream.getvalue()
    assert analytics.status()["enabled"] is True


def test_headless_can_enroll_at_later_interactive_touchpoint(fresh, monkeypatch):
    monkeypatch.setattr(prompt, "origin", lambda: "python")
    monkeypatch.setattr(sys, "stderr", io.StringIO())
    prompt.offer()
    assert not fresh.exists()
    monkeypatch.setattr(sys, "stderr", Terminal())
    prompt.offer()
    assert analytics.status()["enabled"] is True


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
assert NOTICE in sys.stderr.getvalue()
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
