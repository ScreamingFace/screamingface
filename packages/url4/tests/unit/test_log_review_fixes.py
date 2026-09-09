"""Public Log serialization and payload-free producer diagnostics regressions."""

import copy
import json
import pickle
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from operator import setitem
from typing import Any, cast

import pytest

import url4.observe as observe
from url4.observe import Log, _bind_node_sinks, current_log_sink


@pytest.mark.parametrize("attributes", [{}, {"text": "v", "n": 2, "f": 1.5, "ok": True, "x": None}])
@pytest.mark.parametrize("protocol", range(pickle.HIGHEST_PROTOCOL + 1))
def test_log_pickle_roundtrip_preserves_immutable_snapshot(attributes, protocol):
    event = Log("span", "INFO", "body", attributes)
    restored = pickle.loads(pickle.dumps(event, protocol=protocol))
    assert restored == event
    assert hash(restored) == hash(event)
    with pytest.raises(TypeError):
        setitem(cast(Any, restored.attributes), "new", 3)


@pytest.mark.parametrize("attributes", [{}, {"attempt": 2}])
def test_log_deepcopy_and_asdict_support_detached_json(attributes):
    event = Log("span", "INFO", "body", attributes)
    cloned = copy.deepcopy(event)
    assert cloned == event
    with pytest.raises(TypeError):
        setitem(cast(Any, cloned.attributes), "attempt", 3)
    serialized = asdict(event)
    assert json.loads(json.dumps(serialized)) == {
        "span_id": "span",
        "severity": "INFO",
        "body": "body",
        "attributes": attributes,
    }
    serialized["attributes"]["attempt"] = 99
    assert event.attributes == attributes
    assert cloned.attributes == attributes


def counts():
    return observe.log_sink_drop_counts()


def ignore(*args, **kwargs):
    pass


@pytest.mark.parametrize(
    "body, attributes, severity, reason",
    [
        ("", None, "INFO", "body"),
        (None, None, "INFO", "body"),
        ("private", None, "WARNING", "severity"),
        ("private", None, 3, "severity"),
        ("private", {"secret": []}, "INFO", "attributes"),
        ("private", {"secret": float("nan")}, "INFO", "attributes"),
    ],
)
def test_rejected_records_count_only_first_reason(body, attributes, severity, reason, caplog):
    before = counts()
    emitted = []
    with _bind_node_sinks(ignore, ignore, lambda *a, **kw: emitted.append((a, kw))):
        sink = current_log_sink()
        assert sink is not None
        for _ in range(20):
            sink(body, attributes, severity=severity)
    after = counts()
    assert {key: after[key] - before[key] for key in after} == {
        key: 20 if key == reason else 0 for key in after
    }
    assert emitted == []
    assert caplog.text == ""
    assert "private" not in repr(after)
    with pytest.raises(TypeError):
        setitem(cast(Any, after), reason, 0)
    assert before[reason] + 20 == after[reason]


def test_observer_errors_count_without_payload_or_recursive_logging(caplog):
    before = counts()

    def fail(*args, **kwargs):
        raise RuntimeError("private exception body")

    with _bind_node_sinks(ignore, ignore, fail):
        sink = current_log_sink()
        assert sink is not None
        for _ in range(100):
            sink("private message", {"secret": "value"})
    after = counts()
    assert after["emit"] - before["emit"] == 100
    assert len(after) == 6
    assert all(type(value) is int for value in after.values())
    assert caplog.text == ""
    assert "private" not in repr(after)


def test_expired_and_concurrent_off_thread_calls_count_without_emission():
    before = counts()
    emitted = []
    with _bind_node_sinks(ignore, ignore, lambda *a, **kw: emitted.append((a, kw))):
        sink = current_log_sink()
        assert sink is not None
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(sink, ["private"] * 1000))
    sink("expired")
    after = counts()
    assert after["thread"] - before["thread"] == 1000
    assert after["expired"] - before["expired"] == 1
    assert emitted == []


def test_success_and_process_control_leave_counts_unchanged():
    before = counts()
    with _bind_node_sinks(ignore, ignore, ignore):
        sink = current_log_sink()
        assert sink is not None
        sink("success")
    for error in (KeyboardInterrupt(), SystemExit()):

        def fail(*args, **kwargs):
            raise error

        with _bind_node_sinks(ignore, ignore, fail):
            sink = current_log_sink()
            assert sink is not None
            with pytest.raises(type(error)):
                sink("private")
    assert counts() == before


def test_drop_counters_saturate_without_growing_diagnostic_state(monkeypatch):
    # INVARIANT: even permanently broken producers cannot grow counter storage forever.
    monkeypatch.setitem(observe._log_drop_counts, "body", sys.maxsize - 1)
    with _bind_node_sinks(ignore, ignore, ignore):
        sink = current_log_sink()
        assert sink is not None
        for _ in range(3):
            sink("")
    assert counts()["body"] == sys.maxsize
    assert set(counts()) == {"expired", "thread", "body", "severity", "attributes", "emit"}


def test_legacy_three_argument_log_serialization():
    event = Log("span", "custom", "body")
    assert pickle.loads(pickle.dumps(event)) == event
    assert copy.deepcopy(event) == event
    assert asdict(event)["attributes"] == {}


def test_attribute_mapping_copies_preserve_read_only_interface():
    event = Log("span", "INFO", "body", {"attempt": 2})
    assert len(event.attributes) == 1
    assert "attempt" in repr(event.attributes)
    for attributes in (
        event.attributes,
        copy.copy(event.attributes),
        pickle.loads(pickle.dumps(event.attributes)),
    ):
        assert attributes == {"attempt": 2}
        with pytest.raises(AttributeError):
            setattr(attributes, "_values", {})
        with pytest.raises(AttributeError):
            delattr(attributes, "_values")
        with pytest.raises(TypeError):
            setitem(cast(Any, attributes), "attempt", 99)


def test_broken_mapping_counts_attribute_failure_without_inspecting_exception():
    from collections.abc import Mapping

    class BrokenMapping(Mapping):
        def __iter__(self):
            raise RuntimeError("secret mapping")

        def __len__(self):
            return 1

        def __getitem__(self, key):
            raise RuntimeError("secret mapping")

    before = counts()
    with _bind_node_sinks(ignore, ignore, ignore):
        sink = current_log_sink()
        assert sink is not None
        sink("body", BrokenMapping())
    assert counts()["attributes"] - before["attributes"] == 1
