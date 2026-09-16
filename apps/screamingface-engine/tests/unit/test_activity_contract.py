"""Safe activity facts and constant-storage admission, independent of operation scopes."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from screamingface_engine.activity.contract import (
    MAX_INTEGER,
    ActivityKind,
    ActivityLevel,
    facts,
    validate_state,
)
from screamingface_engine.activity.session import ActivitySession, activate, current_session


class Clock:
    now = 0.0

    def monotonic(self):
        return self.now


class Sink:
    def __init__(self):
        self.records = []

    def __call__(self, body, attributes=None, *, severity="INFO"):
        self.records.append((body, dict(attributes or {}), severity))


def emit(session, sink, state="completed", **attributes):
    session.emit(sink, "Activity", {"sf.activity.state": state, **attributes})


def test_policy_and_state_vocabulary():
    assert ActivityLevel("off") is ActivityLevel.OFF
    assert ActivityLevel("full") is ActivityLevel.FULL
    with pytest.raises(ValueError):
        ActivityLevel("aggregate")
    for kind in ActivityKind:
        for state in ("started", "running", "completed", "failed", "cancelled"):
            validate_state(kind, state)
    validate_state(ActivityKind.MODEL_CALL, "retrying")
    validate_state(ActivityKind.ANSWERING, "refused")
    for kind, state in [
        (ActivityKind.AGGREGATION, "retrying"),
        (ActivityKind.GRADING_CHECK, "refused"),
        (ActivityKind.MODEL_CALL, "unknown"),
    ]:
        with pytest.raises(ValueError):
            validate_state(kind, state)


def test_safe_facts_omit_unknown_finish_and_replace_private_failure():
    assert facts(
        {
            "model_id": "public-model",
            "case_id": 0,
            "loaded_count": 2,
            "attempt": 2,
            "retry_delay_ms": 12.5,
            "finish_reason": "private",
            "failure_code": "secret/token",
            "provider": None,
        }
    ) == {
        "sf.activity.model_id": "public-model",
        "sf.activity.case_id": 0,
        "sf.activity.loaded_count": 2,
        "sf.activity.attempt": 2,
        "sf.activity.retry_delay_ms": 12.5,
        "sf.activity.failure_code": "internal_error",
    }
    assert facts({"finish_reason": "stop", "result_count": MAX_INTEGER}) == {
        "sf.activity.finish_reason": "stop",
        "sf.activity.result_count": MAX_INTEGER,
    }


@pytest.mark.parametrize(
    "values",
    [
        {"model_id": "https://secret.example"},
        {"model_id": "x" * 129},
        {"model_id": "/private/file"},
        {"model_id": "a/../b"},
        {"model_id": 1},
        {"case_id": True},
        {"loaded_count": -1},
        {"loaded_count": 1.5},
        {"loaded_count": MAX_INTEGER + 1},
        {"attempt": 0},
        {"retry_delay_ms": float("inf")},
        {"retry_delay_ms": float("nan")},
        {"prompt": "secret"},
    ],
)
def test_invalid_facts_are_rejected(values):
    with pytest.raises(ValueError):
        facts(values)


def test_exact_reserve_fractional_refill_and_loss_snapshot():
    clock, sink = Clock(), Sink()
    session = ActivitySession(monotonic=clock.monotonic)
    for _ in range(160):
        emit(session, sink, "running")
    emit(session, sink, "running")
    assert len(sink.records) == 160
    for _ in range(40):
        emit(session, sink)
    emit(session, sink, "failed")
    assert len(sink.records) == 200
    clock.now = 0.01
    emit(session, sink, "failed")
    assert len(sink.records) == 201
    assert sink.records[-1][1]["sf.activity.suppressed.rate"] == 2
    clock.now += 0.01
    emit(session, sink)
    assert "sf.activity.suppressed.rate" not in sink.records[-1][1]


def test_recovery_continues_for_three_days_without_retaining_payloads():
    clock, count = Clock(), 0
    session = ActivitySession(monotonic=clock.monotonic)

    def sink(*args, **kwargs):
        nonlocal count
        count += 1

    for second in range(259_201):
        clock.now = second
        emit(session, sink)
    assert count == 259_201
    assert session._suppressed == {"invalid": 0, "oversize": 0, "rate": 0}


def test_oversize_invalid_and_sink_fault_recover_with_safe_counts():
    sink, session = Sink(), ActivitySession()
    session.emit(sink, "x" * 257, {"sf.activity.state": "started"})
    emit(session, sink, detail="x" * 4096)
    emit(session, sink, detail=float("nan"))

    def broken(*args, **kwargs):
        raise RuntimeError("PRIVATE sink error")

    emit(session, broken)
    emit(session, sink)
    assert len(sink.records) == 1
    assert sink.records[0][1]["sf.activity.suppressed.oversize"] == 2
    assert sink.records[0][1]["sf.activity.suppressed.invalid"] == 1
    assert "PRIVATE" not in str(sink.records)


def test_snapshot_is_immutable_and_process_control_propagates():
    session = ActivitySession()

    def sink(body, attributes, *, severity):
        with pytest.raises(TypeError):
            attributes["mutation"] = True
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        emit(session, sink)


@pytest.mark.parametrize(
    "state,severity",
    [
        ("started", "INFO"),
        ("running", "INFO"),
        ("completed", "INFO"),
        ("retrying", "WARN"),
        ("refused", "WARN"),
        ("cancelled", "WARN"),
        ("failed", "ERROR"),
    ],
)
def test_record_severity(state, severity):
    sink = Sink()
    emit(ActivitySession(), sink, state)
    assert sink.records[0][2] == severity


def test_nested_disabled_context_and_revocation():
    outer, inner, sink = ActivitySession(), ActivitySession(), Sink()
    with activate(outer):
        assert current_session() is outer
        with activate(None):
            assert current_session() is None
        with activate(inner):
            assert current_session() is inner
        assert current_session() is outer
        outer.revoke()
        assert current_session() is None
        emit(outer, sink)
    assert current_session() is None and sink.records == []


def test_shared_admission_cannot_exceed_burst_under_concurrency():
    sink, clock = Sink(), Clock()
    session = ActivitySession(monotonic=clock.monotonic)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: emit(session, sink), range(500)))
    assert len(sink.records) == 200


def test_suppression_counters_saturate():
    session, sink = ActivitySession(), Sink()
    session._suppressed["invalid"] = MAX_INTEGER
    session.suppress("invalid")
    emit(session, sink)
    assert sink.records[0][1]["sf.activity.suppressed.invalid"] == MAX_INTEGER


@pytest.mark.parametrize("delivered", [False, True])
def test_sink_failure_is_not_producer_suppression(delivered):
    session, sink = ActivitySession(), Sink()
    session.suppress("oversize")

    def broken(body, attributes, *, severity):
        if delivered:
            sink(body, attributes, severity=severity)
        raise RuntimeError("private sink failure")

    emit(session, broken)
    emit(session, sink)
    assert len(sink.records) == (2 if delivered else 1)
    assert session._suppressed == {"invalid": 0, "oversize": 1, "rate": 0}
    assert sink.records[-1][1]["sf.activity.suppressed.oversize"] == 1
    assert sink.records[-1][1]["sf.activity.suppressed.invalid"] == 0
    emit(session, sink)
    assert "sf.activity.suppressed.oversize" not in sink.records[-1][1]
