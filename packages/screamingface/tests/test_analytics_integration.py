import asyncio
from typing import Any, cast

import pytest

import screamingface as sf
from screamingface import analytics
from screamingface._analytics import wiring
from screamingface._analytics.core import Coordinator
from screamingface._analytics.ports import Consent


class Store:
    def read(self):
        return Consent("accepted")


class Sink:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(event)

    def clear(self):
        self.events.clear()


@pytest.fixture
def events(monkeypatch):
    sink = Sink()
    core = Coordinator(Store(), sink, version="0.1.0")
    monkeypatch.setattr(wiring, "coordinator", lambda: core)
    return sink.events


def test_validation_failure_is_tracked_without_exception_text(events):
    with sf.Client(engine_url="http://localhost:9108") as client:
        with pytest.raises(TypeError):
            client.evaluate(cast(Any, []))
    assert [e["event"] for e in events] == ["evaluation_started", "evaluation_finished"]
    assert events[-1]["outcome"] == "failed"
    assert events[0]["usage_mode"] == "byok"
    assert "exception" not in events[-1]


@pytest.mark.asyncio
async def test_async_cancel_is_preserved(events, monkeypatch):
    from screamingface._evaluation import url4

    failure = asyncio.CancelledError()

    async def cancel(*args, **kwargs):
        raise failure

    monkeypatch.setattr(url4, "evaluate_url4_async", cancel)
    async with sf.AsyncClient() as client:
        with pytest.raises(asyncio.CancelledError) as caught:
            await client.evaluate("anything")
    assert caught.value is failure
    assert events[-1]["outcome"] == "cancelled"
    assert events[0]["interface"] == "async"


@pytest.mark.parametrize("ok,outcome", [(True, "succeeded"), (False, "completed_with_failures")])
def test_returned_report_classification(events, monkeypatch, ok, outcome):
    from screamingface._evaluation import url4

    class Report:
        ok: bool

    report = Report()
    report.ok = ok
    monkeypatch.setattr(url4, "evaluate_url4_sync", lambda *a, **kw: report)
    with sf.Client() as client:
        assert client.evaluate("anything") is report
    assert events[-1]["outcome"] == outcome


def test_no_events_before_enable(monkeypatch):
    analytics.disable(process_only=True)
    with sf.Client() as client:
        with pytest.raises(TypeError):
            client.evaluate(cast(Any, []))
    assert analytics.status()["enabled"] is False


def test_submission_validation_uses_engine_mode(events):
    with sf.Client(engine_url="http://127.0.0.1:9108") as client:
        with pytest.raises((TypeError, AttributeError, ValueError)):
            client.leaderboards.submit(cast(Any, None))
    assert events[0]["event"] == "submission_started"
    assert events[0]["usage_mode"] == "byok"
    assert events[-1]["outcome"] == "failed"


def test_module_wrapper_counts_validation_and_does_not_double_emit(events, monkeypatch):
    from screamingface import _default_client

    with sf.Client() as client:
        monkeypatch.setattr(_default_client, "default_client", lambda: client)
        with pytest.raises(TypeError):
            sf.evaluate(cast(Any, []))
    assert len(events) == 2


def test_setup_notice_is_nonblocking_and_once_per_process(config=None):
    from screamingface._analytics import prompt

    assert "sf.analytics.enable()" in prompt.NOTICE


@pytest.mark.asyncio
async def test_concurrent_async_calls_share_session_but_not_operation(events, monkeypatch):
    from screamingface._evaluation import url4

    class Report:
        ok = True

    async def evaluate(*args, **kwargs):
        await asyncio.sleep(0)
        return Report()

    monkeypatch.setattr(url4, "evaluate_url4_async", evaluate)
    async with sf.AsyncClient() as client:
        await asyncio.gather(client.evaluate("one"), client.evaluate("two"))
    assert len(events) == 4
    assert len({event["session_id"] for event in events}) == 1
    assert len({event["operation_id"] for event in events}) == 2
    assert [e["outcome"] for e in events if "outcome" in e] == ["succeeded", "succeeded"]


def test_emitted_event_matches_ingestion_contract(events, monkeypatch):
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    monkeypatch.syspath_prepend(str(root / "apps/analytics/src"))
    from importlib import import_module

    parse_batch = import_module("analytics_service.contract").parse_batch

    with sf.Client() as client:
        with pytest.raises(TypeError):
            client.evaluate(cast(Any, []))
    batch = parse_batch(
        {"schema_version": 1, "consent_version": "1", "consent_granted": True, "events": events}
    )
    assert len(batch.events) == 2
    assert "fusion.dev.screamingface.ai" not in str(events)


def test_metadata_failure_never_changes_product_exception(monkeypatch):
    def unavailable():
        raise OSError("private storage error")

    monkeypatch.setattr(wiring, "coordinator", unavailable)
    with sf.Client() as client:
        with pytest.raises(TypeError, match="benchmark is required"):
            client.evaluate(cast(Any, []))


def test_inherited_operation_guard_does_not_suppress_child_process(events, monkeypatch):
    from screamingface._analytics import tracking

    # Simulate a context inherited from another PID during an active parent evaluation.
    token = tracking._active.set(-1)
    try:
        with sf.Client() as client:
            with pytest.raises(TypeError):
                client.evaluate(cast(Any, []))
    finally:
        tracking._active.reset(token)
    assert len(events) == 2


def test_unavailable_outcome_does_not_replace_return_value(events, monkeypatch):
    from screamingface._evaluation import url4

    class Report:
        @property
        def ok(self):
            raise RuntimeError("unavailable report summary")

    result = Report()
    monkeypatch.setattr(url4, "evaluate_url4_sync", lambda *a, **kw: result)
    with sf.Client() as client:
        assert client.evaluate("anything") is result
    assert len(events) == 1  # No fabricated terminal classification.


def test_submission_success_never_exports_authors_or_run_ids(events, monkeypatch):
    from screamingface._scoreboard import leaderboards

    result = object()
    monkeypatch.setattr(leaderboards, "_submission", lambda *a, **kw: {})
    monkeypatch.setattr(leaderboards, "prepare_submission_notice", lambda *a: None)
    monkeypatch.setattr(leaderboards, "display_submission_notice", lambda *a: None)
    monkeypatch.setattr(leaderboards, "_sync_json", lambda *a, **kw: {})
    monkeypatch.setattr(leaderboards, "_decode_score", lambda **kw: result)

    class Candidate:
        run_id = "private-execution-id"

    with sf.Client() as client:
        assert (
            client.leaderboards.submit(cast(Any, Candidate()), authors=["private@example.com"])
            is result
        )
    assert events[-1]["outcome"] == "succeeded"
    assert "private" not in str(events)
