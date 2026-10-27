import pytest

from screamingface._analytics.core import Coordinator
from screamingface._analytics.ports import Consent


class Store:
    state = Consent()

    def read(self):
        return self.state


class Sink:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(event)

    def clear(self):
        self.events.clear()


def test_no_retroactive_tracking_and_shared_session():
    store, sink = Store(), Sink()
    core = Coordinator(store, sink, version="0.1.0")
    assert core.begin("evaluation", "recipe", "sync", "python", "hosted") is None
    store.state = Consent("accepted", "5ee8e0bd-916b-42fa-a3fa-df1de9d1f9d7")
    first = core.begin("evaluation", "recipe", "sync", "python", "hosted")
    second = core.begin("evaluation", "raw_url4", "async", "python", "byok")
    assert first is not None and second is not None
    core.finish(first, "completed_with_failures")
    assert len({e["session_id"] for e in sink.events}) == 1
    assert first.fields["operation_id"] != second.fields["operation_id"]
    assert sink.events[-1]["outcome"] == "completed_with_failures"
    assert len({e["event_id"] for e in sink.events}) == 3


@pytest.mark.parametrize("origin,mode", [("unknown", "hosted"), ("python", "unknown")])
def test_invalid_metadata_drops_without_ids(origin, mode):
    store, sink = Store(), Sink()
    store.state = Consent("accepted")
    core = Coordinator(store, sink, version="0.1.0")
    assert core.begin("evaluation", "recipe", "sync", origin, mode) is None
    assert sink.events == []


def test_opt_out_or_rotation_suppresses_old_terminal_event():
    store, sink = Store(), Sink()
    store.state = Consent("accepted", "old")
    core = Coordinator(store, sink, version="0.1.0")
    operation = core.begin("submission", "submission", "async", "python", "hosted")
    assert operation is not None
    store.state = Consent("accepted", "new")
    core.finish(operation, "succeeded")
    assert len(sink.events) == 1
    core.clear()
    assert sink.events == []


def test_session_only_has_no_persistent_identifier():
    store, sink = Store(), Sink()
    store.state = Consent("accepted")
    core = Coordinator(store, sink, version="0.1.0")
    core.begin("evaluation", "recipe", "sync", "local_jupyter", "byok")
    assert sink.events[0]["id_scope"] == "session"
    assert "persistent_id" not in sink.events[0]


@pytest.mark.parametrize(
    "seconds,bucket",
    [
        (0, "under_1s"),
        (1, "1_10s"),
        (10, "10_60s"),
        (60, "1_10m"),
        (600, "10_60m"),
        (3600, "over_60m"),
    ],
)
def test_duration_boundaries(seconds, bucket):
    from screamingface._analytics.core import duration_bucket

    assert duration_bucket(seconds) == bucket


def test_dispatch_rechecks_consent_and_reset_invalidates_old_operations():
    store, sink = Store(), Sink()
    store.state = Consent("accepted")
    core = Coordinator(store, sink, version="0.1.0")
    operation = core.begin("evaluation", "recipe", "sync", "python", "hosted")
    assert operation is not None
    event = sink.events[0]
    assert core.accepts(event)
    store.state = Consent("declined")
    assert not core.accepts(event)
    store.state = Consent("accepted")
    core.clear()
    core.finish(operation, "succeeded")
    assert not core.accepts(event)
    assert sink.events == []


def test_fork_replaces_coordinator_and_session(monkeypatch):
    from screamingface._analytics import wiring

    first = wiring.coordinator()
    monkeypatch.setattr(wiring, "_pid", -1)
    assert wiring.coordinator() is not first


def test_identifier_reset_in_another_process_cannot_link_through_old_session():
    store, sink = Store(), Sink()
    core = Coordinator(store, sink, version="0.1.0")
    store.state = Consent("accepted", "old")
    first = core.begin("evaluation", "recipe", "sync", "python", "byok")
    store.state = Consent("accepted", "new")
    second = core.begin("evaluation", "recipe", "sync", "python", "byok")
    assert first is not None and second is not None
    assert first.fields["session_id"] != second.fields["session_id"]
