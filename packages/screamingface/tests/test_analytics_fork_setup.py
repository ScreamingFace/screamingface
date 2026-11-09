"""A child's fresh Colab bridge must not inherit its parent's setup guard."""

import asyncio

import pytest
from test_analytics_colab import accepted
from test_analytics_colab import browser as browser

from screamingface import analytics
from screamingface._analytics import colab, prompt


def evaluate(asynchronous):
    if asynchronous:
        asyncio.run(prompt.before_evaluation_async())
    else:
        prompt.before_evaluation()


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("saved", ["unknown", "accepted", "declined"])
def test_child_first_evaluation_reinitializes_browser_once(
    browser, monkeypatch, asynchronous, saved
):
    commands = []
    identifier = accepted()

    def exchange(command, event, **kwargs):
        commands.append(command)
        if command == "state":
            return {"choice": saved, "consent_version": "1"}
        return identifier

    monkeypatch.setattr(colab, "exchange", exchange)
    evaluate(asynchronous)
    assert prompt._shown
    commands.clear()
    # WHY: reproduce inherited parent globals with a changed PID without forking
    # a pytest process that may already have unrelated worker threads.
    monkeypatch.setattr(prompt, "_pid", -1)
    monkeypatch.setattr(colab, "_pid", -1)
    try:
        evaluate(asynchronous)
        child = colab.bridge()
        assert child is not browser
        expected = ["state", "enroll", "id"] if saved == "unknown" else ["state"]
        if saved == "accepted":
            expected.append("id")
        assert commands == expected
        assert child.read().choice == ("declined" if saved == "declined" else "accepted")
        evaluate(asynchronous)
        assert commands == expected
    finally:
        colab.bridge().stop(persist=False)


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("optout", ["environment", "process"])
def test_child_keeps_inherited_optouts(browser, monkeypatch, asynchronous, optout):
    monkeypatch.setattr(colab, "exchange", lambda *args, **kwargs: accepted())
    evaluate(asynchronous)
    assert prompt._shown
    if optout == "environment":
        monkeypatch.setenv("DO_NOT_TRACK", "1")
    else:
        analytics.disable(process_only=True)
    monkeypatch.setattr(prompt, "_pid", -1)
    monkeypatch.setattr(colab, "_pid", -1)
    commands = []
    monkeypatch.setattr(
        colab, "exchange", lambda command, *args, **kwargs: commands.append(command)
    )
    try:
        evaluate(asynchronous)
        child = colab.bridge()
        assert child is not browser
        assert not child.setup_pending()
        assert child.read().choice == "unknown"
        assert commands == []
        assert not analytics.status()["enabled"]
    finally:
        colab.bridge().stop(persist=False)
