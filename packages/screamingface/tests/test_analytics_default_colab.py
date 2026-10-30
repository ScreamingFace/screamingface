"""Disclosure-gated Colab defaults and bounded first-evaluation setup."""

import threading
import time

import pytest
from test_analytics_colab import accepted
from test_analytics_colab import browser as browser

from screamingface import analytics
from screamingface._analytics import colab, prompt


def test_default_setup_discloses_before_enrollment_and_id(browser, monkeypatch, capsys):
    calls = []

    def exchange(command, event, **kwargs):
        calls.append(command)
        if command == "state":
            return {"choice": "unknown", "consent_version": "1"}
        if command == "enroll":
            assert prompt.NOTICE in capsys.readouterr().out
        return accepted()

    monkeypatch.setattr(colab, "exchange", exchange)
    prompt.offer()
    browser.wait_for_setup()
    assert browser.read().choice == "accepted"
    assert calls == ["state", "enroll", "id"]


@pytest.mark.parametrize("choice", ["accepted", "declined"])
def test_default_setup_preserves_saved_browser_choice(browser, monkeypatch, capsys, choice):
    calls = []

    def exchange(command, event, **kwargs):
        calls.append(command)
        return accepted() if choice == "accepted" else {"choice": choice, "consent_version": "1"}

    monkeypatch.setattr(colab, "exchange", exchange)
    prompt.offer()
    browser.wait_for_setup()
    assert browser.read().choice == choice
    assert calls == (["state", "id"] if choice == "accepted" else ["state"])
    assert capsys.readouterr().out == ""


def test_default_setup_failed_notice_never_enrolls(browser, monkeypatch):
    calls = []

    def exchange(command, event, **kwargs):
        calls.append(command)
        return {"choice": "unknown", "consent_version": "1"}

    def unavailable(*args):
        raise OSError("closed output")

    monkeypatch.setattr(colab, "exchange", exchange)
    monkeypatch.setattr(prompt, "show_notice", unavailable)
    prompt.offer()
    browser.wait_for_setup()
    assert browser.read().choice == "unknown"
    assert calls == ["state"]


def test_default_setup_timeout_invalidates_late_reply(browser, monkeypatch):
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    calls = []

    def exchange(command, event, **kwargs):
        calls.append(command)
        entered.set()
        release.wait(4)
        finished.set()
        return accepted()

    monkeypatch.setattr(colab, "exchange", exchange)
    try:
        prompt.offer()
        assert entered.wait(1)
        start = time.monotonic()
        browser.wait_for_setup()
        assert 1.5 < time.monotonic() - start < 2.5
        assert browser.read().choice == "unknown"
        assert not browser.pending
        release.set()
        assert finished.wait(1)
        browser.wait_for_setup()
        assert browser.read().choice == "unknown"
        assert calls == ["state"]
    finally:
        release.set()


def test_disable_during_automatic_setup_prevents_enrollment(browser, monkeypatch):
    calls = []

    def exchange(command, event, **kwargs):
        calls.append(command)
        analytics.disable(process_only=True)
        return {"choice": "unknown", "consent_version": "1"}

    monkeypatch.setattr(colab, "exchange", exchange)
    prompt.offer()
    browser.wait_for_setup()
    assert browser.read().choice == "declined"
    assert calls == ["state"]


@pytest.mark.asyncio
async def test_first_async_evaluation_waits_without_blocking_event_loop(browser, monkeypatch):
    import asyncio

    from screamingface._analytics.tracking import tracked

    release = threading.Event()

    def exchange(command, event, **kwargs):
        assert release.wait(1), "event loop was blocked by setup wait"
        return accepted()

    @tracked("evaluation")
    async def evaluate():
        assert browser.read().choice == "accepted"
        return "ran"

    async def release_from_loop():
        await asyncio.sleep(0.02)
        release.set()

    monkeypatch.setattr(colab, "exchange", exchange)
    result, _ = await asyncio.gather(evaluate(), release_from_loop())
    assert result == "ran"


def test_first_sync_evaluation_waits_for_browser_setup(browser, monkeypatch):
    from screamingface._analytics.tracking import tracked

    monkeypatch.setattr(colab, "exchange", lambda *a, **kw: accepted())

    @tracked("evaluation")
    def evaluate():
        assert browser.read().choice == "accepted"
        return "ran"

    assert evaluate() == "ran"


def test_decline_at_conditional_enrollment_prevents_id(browser, monkeypatch):
    calls = []

    def exchange(command, event, **kwargs):
        calls.append(command)
        return {
            "choice": "declined" if command == "enroll" else "unknown",
            "consent_version": "1",
        }

    monkeypatch.setattr(colab, "exchange", exchange)
    prompt.offer()
    browser.wait_for_setup()
    assert calls == ["state", "enroll"]
    assert browser.read().choice == "declined"


@pytest.mark.asyncio
async def test_async_setup_deadline_includes_executor_delay(browser, monkeypatch):
    import asyncio

    release = threading.Event()

    def exchange(*args, **kwargs):
        release.wait(4)
        return accepted()

    async def saturated_executor(*args):
        await asyncio.sleep(4)

    monkeypatch.setattr(colab, "exchange", exchange)
    monkeypatch.setattr(asyncio, "to_thread", saturated_executor)
    start = time.monotonic()
    try:
        await prompt.before_evaluation_async()
        assert time.monotonic() - start < 2.5
        assert not browser.pending
        assert browser.read().choice == "unknown"
    finally:
        release.set()


@pytest.mark.asyncio
async def test_async_opt_out_never_waits_for_executor(browser, monkeypatch):
    import asyncio

    async def forbidden(*args):
        raise AssertionError("opt-out must not wait for browser setup")

    monkeypatch.setattr(asyncio, "to_thread", forbidden)
    monkeypatch.setenv("DO_NOT_TRACK", "1")
    await prompt.before_evaluation_async()


@pytest.mark.asyncio
async def test_async_evaluations_after_setup_never_wait_again(browser, monkeypatch):
    import asyncio

    monkeypatch.setattr(colab, "exchange", lambda *a, **kw: accepted())
    await prompt.before_evaluation_async()
    assert browser.read().choice == "accepted"

    async def forbidden(*args):
        raise AssertionError("completed setup must not use the executor")

    monkeypatch.setattr(asyncio, "to_thread", forbidden)
    await prompt.before_evaluation_async()
