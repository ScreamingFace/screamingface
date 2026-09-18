"""Stage telemetry is optional and never changes benchmark execution."""

import asyncio
import inspect

import pytest

from screamingface_engine.activity.observer import ActivityObserver
from screamingface_engine.activity.scope import current_operation
from screamingface_engine.activity_kinds import ActivityKind
from screamingface_engine.benchmarks.stages import observe_stage
from screamingface_engine.observations import ModelCall, RunObservations


def capture():
    records = []

    def emit(body, attributes=None, **kwargs):
        records.append(dict(attributes or {}))

    return records, emit


@pytest.mark.parametrize(
    "stage", [kind for kind in ActivityKind if kind != ActivityKind.MODEL_CALL]
)
def test_sync_stages_preserve_values_and_only_emit_safe_lifecycle(monkeypatch, stage):
    records, emit = capture()
    monkeypatch.setattr("screamingface_engine.benchmarks.stages.current_log_sink", lambda: emit)
    sentinel = object()
    wrapped = observe_stage(stage)(lambda: sentinel)
    with RunObservations((ActivityObserver,)).bind():
        assert wrapped() is sentinel
    assert not inspect.iscoroutinefunction(wrapped)
    assert [r["sf.activity.state"] for r in records] == ["started", "completed"]
    assert {r["sf.activity.kind"] for r in records} == {stage.value}
    assert records[0]["sf.activity.id"] == records[1]["sf.activity.id"]
    assert set(records[0]) == {
        "sf.activity.schema",
        "sf.activity.kind",
        "sf.activity.state",
        "sf.activity.id",
        "sf.activity.revision",
        "sf.activity.elapsed_ms",
        "sf.activity.observed_at_ms",
    }


@pytest.mark.asyncio
async def test_async_stage_owns_nested_model_and_preserves_exception(monkeypatch):
    records, emit = capture()
    monkeypatch.setattr("screamingface_engine.benchmarks.stages.current_log_sink", lambda: emit)
    observer = ActivityObserver()
    failure = ValueError("private prompt must never be logged")

    async def answer():
        async with ModelCall("model", emit):
            await asyncio.sleep(0)
            raise failure

    wrapped = observe_stage(ActivityKind.ANSWERING)(answer)
    assert inspect.iscoroutinefunction(wrapped)
    run = RunObservations((lambda: observer,))
    with run.bind(), pytest.raises(ValueError) as caught:
        await wrapped()
    assert caught.value is failure
    await run.aclose()
    assert not observer._calls
    stage_start, model_start, model_end, stage_end = records
    assert model_start["sf.activity.parent_id"] == stage_start["sf.activity.id"]
    assert model_end["sf.activity.state"] == stage_end["sf.activity.state"] == "failed"
    assert "private" not in str(records)


@pytest.mark.asyncio
async def test_stage_cancellation_joins_timer(monkeypatch):
    records, emit = capture()
    monkeypatch.setattr("screamingface_engine.benchmarks.stages.current_log_sink", lambda: emit)
    entered = asyncio.Event()
    observer = ActivityObserver()

    async def answer():
        entered.set()
        await asyncio.Event().wait()

    run = RunObservations((lambda: observer,))
    with run.bind():
        task = asyncio.create_task(observe_stage(ActivityKind.ANSWERING)(answer)())
        await entered.wait()
        operations = tuple(observer._calls)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert records[-1]["sf.activity.state"] == "cancelled"
    assert all(op._task is not None and op._task.done() for op in operations)
    assert not observer._calls
    await run.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("factories", [(), (lambda: ActivityObserver(enabled=False),)])
async def test_empty_or_off_inner_run_cannot_inherit_outer_activity(monkeypatch, factories):
    records, emit = capture()
    monkeypatch.setattr("screamingface_engine.benchmarks.stages.current_log_sink", lambda: emit)
    outer = RunObservations((ActivityObserver,))
    inner = RunObservations(factories)
    with outer.bind():
        with inner.bind():
            assert observe_stage(ActivityKind.GRADING)(lambda: "ok")() == "ok"
            assert current_operation() is None
        assert records == []
    await inner.aclose()
    await outer.aclose()


@pytest.mark.asyncio
async def test_concurrent_stage_instances_never_share_parent_or_occurrence(monkeypatch):
    records, emit = capture()
    monkeypatch.setattr("screamingface_engine.benchmarks.stages.current_log_sink", lambda: emit)

    async def answer():
        await asyncio.sleep(0)
        return "same output"

    run = RunObservations((ActivityObserver,))
    with run.bind():
        assert (
            await asyncio.gather(
                *(observe_stage(ActivityKind.ANSWERING)(answer)() for _ in range(3))
            )
            == ["same output"] * 3
        )
    await run.aclose()
    assert len({r["sf.activity.id"] for r in records}) == 3
    assert all("sf.activity.parent_id" not in r for r in records)


def test_stage_observer_fault_does_not_replace_execution_error(monkeypatch, caplog):
    records, emit = capture()
    monkeypatch.setattr("screamingface_engine.benchmarks.stages.current_log_sink", lambda: emit)

    class Broken(ActivityObserver):
        def stage(self, stage, emit):
            raise RuntimeError("private observer detail")

    def fail():
        raise ValueError("original")

    with RunObservations((Broken,)).bind():
        for _ in range(2):
            with pytest.raises(ValueError, match="original"):
                observe_stage(ActivityKind.GRADING)(fail)()
    assert len(caplog.records) == 1
    assert "private" not in caplog.text
    assert records == []


@pytest.mark.asyncio
async def test_stage_heartbeat_is_fixed_and_run_cleanup_joins_abandoned_scope(monkeypatch):
    from screamingface_engine.activity import scope

    records, emit = capture()
    first_tick = asyncio.Event()
    hold = asyncio.Event()
    delays = []

    async def sleep(seconds):
        delays.append(seconds)
        if len(delays) == 1:
            return
        first_tick.set()
        await hold.wait()

    monkeypatch.setattr(scope, "_sleep", sleep)
    observer = ActivityObserver()
    with observer.bind():
        stage = observer.stage(ActivityKind.GRADING, emit)
        assert stage is not None
        await stage.__aenter__()
        await first_tick.wait()
        operations = tuple(observer._calls)
        await observer.aclose()
        assert all(op._task is not None and op._task.done() for op in operations)
        await stage.__aexit__(None, None, None)
    assert delays == [60.0, 60.0]
    assert [r["sf.activity.state"] for r in records] == ["started", "running"]
    assert not observer._calls


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_observer_teardown_cannot_suppress_original_failure(monkeypatch, asynchronous):
    monkeypatch.setattr("screamingface_engine.benchmarks.stages.current_log_sink", lambda: None)

    class Observer(ActivityObserver):
        def stage(self, stage, emit):
            return Suppressor()

    def fail():
        raise ValueError("original")

    async def async_fail():
        fail()

    run = RunObservations((Observer,))
    with run.bind(), pytest.raises(ValueError, match="original"):
        if asynchronous:
            await observe_stage(ActivityKind.GRADING)(async_fail)()
        else:
            observe_stage(ActivityKind.GRADING)(fail)()
    await run.aclose()


class Suppressor:
    def __enter__(self):
        return self

    def __exit__(self, typ, exc, tb):
        return True

    async def __aenter__(self):
        return self

    async def __aexit__(self, typ, exc, tb):
        return True


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_cleanup_interruption_unwinds_all_observers(monkeypatch, asynchronous):
    records, emit = capture()
    monkeypatch.setattr("screamingface_engine.benchmarks.stages.current_log_sink", lambda: emit)
    activity = ActivityObserver()

    class Interrupt(Suppressor):
        def __exit__(self, typ, exc, tb):
            raise asyncio.CancelledError()

        async def __aexit__(self, typ, exc, tb):
            raise asyncio.CancelledError()

    class Observer(ActivityObserver):
        def stage(self, stage, emit):
            return Interrupt()

    async def answer():
        return "ok"

    run = RunObservations((lambda: activity, Observer))
    with run.bind():
        with pytest.raises(asyncio.CancelledError):
            if asynchronous:
                await observe_stage(ActivityKind.ANSWERING)(answer)()
            else:
                observe_stage(ActivityKind.ANSWERING)(lambda: "ok")()
        assert current_operation() is None
        assert not activity._calls
    await run.aclose()
