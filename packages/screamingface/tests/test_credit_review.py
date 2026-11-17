"""Review regressions: optional UI dependency and bounded run-start observation."""

import threading
import time
import warnings

import httpx
from test_credit_notice import candidate_for
from test_credit_refresh import panel_for
from test_credits import payload

from screamingface._engine import credit_notice


def test_card_survives_missing_anywidget_and_manual_refresh_still_works(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "anywidget", None)
    client, panel, calls = panel_for()
    try:
        widget = panel.widget()
        from ipywidgets import Box

        assert isinstance(widget, Box) and widget.children
        before = len(calls)
        panel.refresh_credits()
        assert len(calls) == before + 1
        assert calls[-1].url.params["refresh"] == "true"
    finally:
        panel.close()
        client.close()


def test_sync_notice_has_total_deadline_and_no_late_warning(monkeypatch):
    # Block a response past the deadline, without trusting network phase timeouts.
    release, entered, finished = threading.Event(), threading.Event(), threading.Event()
    calls = []

    from functools import partial

    handle = partial(
        _delayed_response, release=release, entered=entered, finished=finished, calls=calls
    )

    monkeypatch.setattr(credit_notice, "_SYNC_WAIT_SECONDS", 0.02, raising=False)
    with httpx.Client(base_url="http://localhost", transport=httpx.MockTransport(handle)) as c:
        try:
            start = time.monotonic()
            with warnings.catch_warnings(record=True) as caught:
                credit_notice.check_sync(c, (candidate_for("openrouter/example"),))
                elapsed = time.monotonic() - start
                assert entered.is_set()
                assert elapsed < 0.5
                # Another evaluation must not accumulate another blocked lookup.
                credit_notice.check_sync(c, (candidate_for("openrouter/example"),))
                assert len(calls) == 1
                release.set()
                assert finished.wait(1)
                assert not caught
        finally:
            release.set()
            finished.wait(1)
            _join_notice_workers()


def _join_notice_workers():
    for worker in threading.enumerate():
        if worker.name == "sf-credit-notice":
            worker.join(1)


def _delayed_response(request, *, release, entered, finished, calls):
    calls.append(request)
    entered.set()
    release.wait(3)
    finished.set()
    body = payload()
    from datetime import UTC, datetime

    body["key"].update(amount_usd="0", as_of=datetime.now(UTC).isoformat())
    return httpx.Response(200, json=body)
