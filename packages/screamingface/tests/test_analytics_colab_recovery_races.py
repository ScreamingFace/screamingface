"""Recovery must not revive stale operations or override newer consent decisions."""

import threading

import pytest
from test_analytics_colab import accepted
from test_analytics_colab import browser as browser
from test_analytics_colab_recovery import evaluate as evaluate
from test_analytics_colab_recovery import recover_and_check_pair, settled
from test_analytics_colab_recovery import replies as replies

from screamingface import analytics
from screamingface._analytics import colab, prompt, wiring


@pytest.fixture
def paused(browser, monkeypatch):
    entered, release, returned = (threading.Event() for _ in range(3))
    calls = []
    saved = [accepted()]
    step_to_pause = ["state"]

    def exchange(step, *args, **kwargs):
        calls.append(step)
        response = saved[0].copy()
        if step == step_to_pause[0] and not entered.is_set():
            entered.set()
            release.wait(5)
            returned.set()
        return response

    monkeypatch.setattr(colab, "exchange", exchange)
    yield entered, release, returned, calls, saved, step_to_pause
    release.set()
    if entered.is_set():
        assert returned.wait(1)


def test_concurrent_evaluations_share_setup_and_both_wait(browser, monkeypatch, paused):
    entered, release, _, calls, *_ = paused
    waiting, waiters = threading.Event(), []
    original = browser._changed.wait_for

    def observe(predicate, timeout=None):
        waiters.append(threading.get_ident())
        if len(waiters) == 2:
            waiting.set()
        return original(predicate, timeout)

    monkeypatch.setattr(browser._changed, "wait_for", observe)
    callers = [threading.Thread(target=prompt.before_evaluation) for _ in range(2)]
    try:
        callers[0].start()
        assert entered.wait(1)
        callers[1].start()
        assert waiting.wait(1), "A concurrent evaluation skipped pending setup"
        assert all(caller.is_alive() for caller in callers)
        release.set()
        for caller in callers:
            caller.join(1)
        assert not any(caller.is_alive() for caller in callers)
        assert calls == ["state", "id"]
        assert analytics.status()["setup_attempts"] == 1
        assert analytics.status()["enabled"]
    finally:
        release.set()
        for caller in callers:
            if caller.ident is not None:
                caller.join(1)


def test_stale_waiter_cannot_cancel_or_wait_on_new_setup(browser, paused):
    entered, release, _, calls, saved, _ = paused
    prompt.offer()
    assert entered.wait(1)
    old = browser.setup_token()
    assert old is not None
    browser.expire_setup(old)
    saved[0] = accepted()
    prompt.offer()
    new = browser.setup_token()
    assert new is not None and new != old
    browser.expire_setup(old)
    browser.wait_for_generation(old)
    assert browser.setup_token() == new
    assert analytics.status()["last_error"] == "setup_timeout"
    release.set()
    browser.wait_for_setup()
    assert analytics.status()["enabled"]
    assert analytics.status()["persistent_id"] == saved[0]["persistent_id"]
    assert analytics.status()["last_error"] is None
    assert calls == ["state", "state", "id"]


@pytest.mark.parametrize("stage", ["state", "id"])
@pytest.mark.parametrize("opt_out", ["disable", "dnt"])
def test_opt_out_during_recovery_wins_over_last_browser_reply(
    browser, paused, monkeypatch, stage, opt_out
):
    entered, release, _, calls, _, step_to_pause = paused
    # WHY: exercise a retry, rather than only the very first setup generation.
    browser.control("setup")
    assert entered.wait(1)
    browser.expire_setup()
    release.set()
    settled(browser, lambda: not browser.pending)
    # Start a fresh paused exchange after discarding the old worker's result.
    step_to_pause[0] = stage
    assert paused[2].wait(1)
    entered.clear()
    release.clear()
    prompt.offer()
    assert entered.wait(1)
    if opt_out == "disable":
        analytics.disable(process_only=True)
    else:
        monkeypatch.setenv("DO_NOT_TRACK", "1")
    before = len(calls)
    release.set()
    settled(browser, lambda: not browser.pending)
    assert not analytics.status()["enabled"]
    assert browser.read().choice != "accepted"
    assert calls[before:] == []


def test_recovery_does_not_revive_old_operation_with_same_browser_id(
    browser, replies, evaluate, monkeypatch
):
    recover_and_check_pair(evaluate, browser, replies)
    core = wiring.coordinator()
    old = core.begin("evaluation", "recipe", "sync", "colab", "hosted")
    assert old is not None
    settled(browser, lambda: len(replies.delivered) == 3)
    replies.fail_command = "events"
    evaluate()
    settled(browser, lambda: replies.failure_processed and replies.worker_idle)
    prompt.before_evaluation()
    assert analytics.status()["persistent_id"] == old.consent.installation_id
    emitted = []
    with monkeypatch.context() as patch:
        patch.setattr(browser, "emit", emitted.append)
        core.finish(old, "succeeded")
    assert emitted == [], "Recovery revived an operation that crossed the consent failure"
    recover_and_check_pair(evaluate, browser, replies)
    assert all("revision" not in event for event in replies.delivered)
    assert replies.delivered[-1]["session_id"] != old.fields["session_id"]


def test_pending_setup_deduplicates_repeated_entrypoints(browser, paused):
    entered, release, _, calls, *_ = paused
    prompt.offer()
    assert entered.wait(1)
    for _ in range(100):
        prompt.offer()
    assert analytics.status()["setup_attempts"] == 1
    assert calls == ["state"]
    release.set()
    browser.wait_for_setup()
    assert analytics.status()["enabled"]
