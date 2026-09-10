"""Optional activity preserves work while bounding rate and private facts."""

import asyncio

import pytest

from screamingface_engine.activity.contract import ActivityKind, ActivityLevel
from screamingface_engine.activity.scope import operation
from screamingface_engine.activity.session import ActivitySession, activate


class Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def wall(self):
        return 1_800_000_000 + self.now


class Sink:
    def __init__(self):
        self.records = []

    def __call__(self, body, attributes=None, *, severity="INFO"):
        self.records.append((body, dict(attributes or {}), severity))


def session(clock):
    return ActivitySession(monotonic=clock.monotonic, wall=clock.wall)


def test_policy_accepts_only_full_off():
    assert ActivityLevel("off") is ActivityLevel.OFF
    with pytest.raises(ValueError):
        ActivityLevel("aggregate")


def test_disabled_or_missing_emitter_is_inert():
    sink = Sink()
    with operation(emit=sink, kind=ActivityKind.MODEL_CALL):
        pass
    with activate(session(Clock())):
        with operation(emit=None, kind=ActivityKind.MODEL_CALL) as op:
            assert not op.enabled
    assert sink.records == []


def test_observed_time_identity_duration_and_safe_terminal_facts():
    clock, sink = Clock(), Sink()
    with activate(session(clock)):
        with operation(emit=sink, kind=ActivityKind.MODEL_CALL, model_id="public-model") as op:
            clock.now = 8.2
            op.finish(finish_reason="stop")
    first, last = [row[1] for row in sink.records]
    assert first["sf.activity.state"] == "started"
    assert last["sf.activity.state"] == "completed"
    assert first["sf.activity.id"] == last["sf.activity.id"]
    assert last["sf.activity.elapsed_ms"] == 8200
    assert last["sf.activity.observed_at_ms"] == 1_800_000_008_200
    assert last["sf.activity.finish_reason"] == "stop"
    assert last["sf.activity.model_id"] == "public-model"


def test_priority_reserve_and_recovery_have_no_lifetime_cutoff():
    clock, sink = Clock(), Sink()
    with activate(session(clock)):
        for _ in range(160):
            with operation(emit=sink, kind=ActivityKind.MODEL_CALL):
                pass
        assert len(sink.records) == 200
        assert sum(r[1]["sf.activity.state"] == "completed" for r in sink.records) > 80
        clock.now += 2
        with operation(emit=sink, kind=ActivityKind.MODEL_CALL):
            pass
        assert sink.records[-2][1]["sf.activity.suppressed.rate"] > 0
        for _ in range(10_001):
            clock.now += 1
            with operation(emit=sink, kind=ActivityKind.MODEL_CALL):
                pass
    assert len(sink.records) > 20_000
    assert sink.records[-1][1]["sf.activity.state"] == "completed"


def test_sink_fault_never_retries_or_replaces_work_error():
    def broken(*args, **kwargs):
        raise RuntimeError("private sink detail")

    with activate(session(Clock())), pytest.raises(ValueError, match="original"):
        with operation(emit=broken, kind=ActivityKind.MODEL_CALL):
            raise ValueError("original")


def test_unknown_failure_and_finish_are_never_copied():
    sink = Sink()
    with activate(session(Clock())):
        with operation(emit=sink, kind=ActivityKind.MODEL_CALL) as op:
            op.finish(outcome="failed", failure_code="secret/token", finish_reason="private")
    assert "secret" not in str(sink.records)
    assert "private" not in str(sink.records)
    assert sink.records[-1][1]["sf.activity.failure_code"] == "internal_error"


@pytest.mark.asyncio
async def test_fixed_heartbeat_is_joined_before_terminal(monkeypatch):
    from screamingface_engine.activity import scope as module

    clock, sink, waits = Clock(), Sink(), []
    tick, proceed = asyncio.Event(), asyncio.Event()

    async def sleep(delay):
        waits.append(delay)
        tick.set()
        await proceed.wait()
        proceed.clear()
        clock.now += delay

    monkeypatch.setattr(module, "_sleep", sleep)
    with activate(session(clock)):
        async with operation(emit=sink, kind=ActivityKind.MODEL_CALL):
            for _ in range(4):
                await tick.wait()
                tick.clear()
                proceed.set()
                await asyncio.sleep(0)
    assert waits == [60.0] * 5
    assert [r[1]["sf.activity.state"] for r in sink.records] == [
        "started",
        "running",
        "running",
        "running",
        "running",
        "completed",
    ]


def test_nested_parent_and_revocation():
    sink, active = Sink(), session(Clock())
    with activate(active):
        with operation(emit=sink, kind=ActivityKind.ANSWERING):
            with operation(emit=sink, kind=ActivityKind.MODEL_CALL):
                pass
        active.revoke()
        with operation(emit=sink, kind=ActivityKind.MODEL_CALL):
            pass
    assert len(sink.records) == 4
    assert sink.records[1][1]["sf.activity.parent_id"] == sink.records[0][1]["sf.activity.id"]


@pytest.mark.parametrize(
    "values",
    [
        {"model_id": "https://secret.example"},
        {"model_id": "x" * 129},
        {"case_id": True},
        {"loaded_count": -1},
        {"loaded_count": 1.5},
        {"attempt": 0},
        {"retry_delay_ms": float("inf")},
        {"prompt": "secret"},
    ],
)
def test_invalid_facts_suppress_only_telemetry(values):
    sink = Sink()
    with activate(session(Clock())):
        with operation(emit=sink, kind=ActivityKind.MODEL_CALL, **values) as op:
            assert not op.enabled
        with operation(emit=sink, kind=ActivityKind.MODEL_CALL):
            pass
    assert len(sink.records) == 2
    assert sink.records[0][1]["sf.activity.suppressed.invalid"] == 1


@pytest.mark.asyncio
async def test_cancellation_joins_timer_and_preserves_original_cancel():
    sink, entered = Sink(), asyncio.Event()

    async def work():
        with activate(session(Clock())):
            async with operation(emit=sink, kind=ActivityKind.MODEL_CALL):
                entered.set()
                await asyncio.Event().wait()

    task = asyncio.create_task(work())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert sink.records[-1][1]["sf.activity.state"] == "cancelled"
    assert not [t for t in asyncio.all_tasks() if "Operation._heartbeat" in str(t.get_coro())]


@pytest.mark.asyncio
async def test_timer_creation_fault_is_optional(monkeypatch):
    def broken(coro):
        raise RuntimeError("timer unavailable")

    sink = Sink()
    monkeypatch.setattr(asyncio, "create_task", broken)
    with activate(session(Clock())):
        async with operation(emit=sink, kind=ActivityKind.MODEL_CALL):
            answer = 42
    assert answer == 42
    assert sink.records[-1][1]["sf.activity.state"] == "completed"


def test_oversize_record_does_not_poison_later_records():
    from screamingface_engine.activity.contract import PREFIX

    sink, active = Sink(), session(Clock())
    active.emit(sink, "x" * 5000, {PREFIX + "state": "started"})
    with activate(active):
        with operation(emit=sink, kind=ActivityKind.MODEL_CALL):
            pass
    assert len(sink.records) == 2
    assert sink.records[0][1][PREFIX + "suppressed.oversize"] == 1


def test_nested_off_scope_cannot_report_to_outer_full_operation():
    from screamingface_engine.activity.scope import current_operation

    with activate(session(Clock())):
        with operation(emit=Sink(), kind=ActivityKind.MODEL_CALL) as outer:
            assert current_operation() is outer
            with activate(None):
                with operation(emit=Sink(), kind=ActivityKind.MODEL_CALL):
                    assert current_operation() is None
            with activate(session(Clock())):
                assert current_operation() is None
            assert current_operation() is outer


def test_missing_sink_scope_masks_outer_operation():
    from screamingface_engine.activity.scope import current_operation

    with activate(session(Clock())):
        with operation(emit=Sink(), kind=ActivityKind.MODEL_CALL) as outer:
            with operation(emit=None, kind=ActivityKind.MODEL_CALL):
                assert current_operation() is None
            assert current_operation() is outer


def test_exact_reserved_capacity_and_fractional_refill():
    sink, clock = Sink(), Clock()
    active = session(clock)
    for _ in range(159):
        active.emit(sink, "start", {"sf.activity.state": "started"})
    active.emit(sink, "at41", {"sf.activity.state": "running"})
    active.emit(sink, "at40", {"sf.activity.state": "running"})
    assert len(sink.records) == 160
    assert sink.records[-1][0] == "at41"
    for _ in range(40):
        active.emit(sink, "terminal", {"sf.activity.state": "completed"})
    active.emit(sink, "empty", {"sf.activity.state": "failed"})
    assert len(sink.records) == 200
    clock.now = 0.01
    active.emit(sink, "recovered", {"sf.activity.state": "failed"})
    assert sink.records[-1][0] == "recovered"


def test_concurrent_admission_never_exceeds_shared_burst():
    from concurrent.futures import ThreadPoolExecutor

    sink, active = Sink(), session(Clock())
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(
            pool.map(
                lambda _: active.emit(sink, "done", {"sf.activity.state": "completed"}), range(500)
            )
        )
    assert len(sink.records) == 200


@pytest.mark.asyncio
async def test_three_simulated_days_keep_fixed_heartbeat_and_terminal(monkeypatch):
    from screamingface_engine.activity import scope

    clock, sink, done = Clock(), Sink(), asyncio.Event()
    ticks = 0

    async def sleep(delay):
        nonlocal ticks
        assert delay == 60
        if ticks == 4320:
            done.set()
            await asyncio.Event().wait()
        await asyncio.sleep(0)
        ticks += 1
        clock.now += delay

    monkeypatch.setattr(scope, "_sleep", sleep)
    with activate(session(clock)):
        async with operation(emit=sink, kind=ActivityKind.MODEL_CALL):
            await done.wait()
    assert len(sink.records) == 4322
    assert sink.records[-1][1]["sf.activity.elapsed_ms"] == 259_200_000
    assert sink.records[-1][1]["sf.activity.state"] == "completed"
