"""Execution observations are optional adapters, never execution policy."""

import ast
from pathlib import Path

import pytest

from screamingface_engine.runner.operation_capture import OperationCapturingExecutor
from url4.streaming.interfaces import Executor
from url4.streaming.protocol import LogData


def test_execution_modules_do_not_import_activity():
    root = Path(__file__).resolve().parents[2] / "src/screamingface_engine/runner"
    for name in ("connector.py", "executor.py", "operation_capture.py"):
        tree = ast.parse((root / name).read_text())
        imports = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        assert not [m for m in imports if m and ".activity" in m], name


@pytest.mark.asyncio
async def test_failed_observer_factory_does_not_prevent_execution(caplog):
    class Probe(Executor):
        async def execute(self, url4, *, trace=None):
            yield LogData.at("INFO", "result")

    def broken():
        raise RuntimeError("PRIVATE observer detail")

    frames = [
        s async for s in OperationCapturingExecutor(Probe(), observers=(broken,)).execute("x")
    ]
    assert frames == [LogData.at("INFO", "result")]
    assert "PRIVATE" not in caplog.text


@pytest.mark.asyncio
async def test_nested_off_registration_masks_parent_activity_session():
    from screamingface_engine.activity.session import current_session
    from screamingface_engine.observation_plugins import observation_factories
    from screamingface_engine.observations import RunObservations

    outer = RunObservations(observation_factories({"URL4_CLOUD_ACTIVITY_LEVEL": "full"}))
    inner = RunObservations(observation_factories({"URL4_CLOUD_ACTIVITY_LEVEL": "off"}))
    with outer.bind():
        session = current_session()
        assert session is not None
        with inner.bind():
            assert current_session() is None
        assert current_session() is session
    await inner.aclose()
    await outer.aclose()


class ObservingCall:
    def __init__(self, events, fault):
        self.events, self.fault = events, fault

    def note(self, phase):
        self.events.append(phase)
        if self.fault == phase:
            raise RuntimeError("PRIVATE observer detail")

    async def start(self):
        self.note("start")

    async def close(self, exc_type, exc, tb):
        self.note("close")

    def completed(self, finish_reason):
        self.note("completed")

    def failed(self, code):
        self.note("failed")

    def retry(self, *, attempt, delay_seconds):
        self.note("retry")


class ObservingRun:
    def __init__(self, events, fault):
        self.call = ObservingCall(events, fault)

    def bind(self):
        from contextlib import contextmanager

        @contextmanager
        def context():
            self.call.note("bind")
            try:
                yield
            finally:
                self.call.note("unbind")

        return context()

    async def aclose(self):
        self.call.note("aclose")

    def model_call(self, model_id, emit):
        self.call.note("model_call")
        return self.call

    def bridge_loss(self, dropped):
        self.call.note("bridge_loss")
        return {"test.loss": dropped}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault",
    [
        "bind",
        "unbind",
        "aclose",
        "model_call",
        "start",
        "close",
        "completed",
        "failed",
        "retry",
        "bridge_loss",
    ],
)
async def test_observer_faults_preserve_original_work_and_cleanup(fault, caplog):
    from screamingface_engine.observations import (
        ModelCall,
        RunObservations,
        bridge_loss_attributes,
        current_model_call,
    )

    events = []
    run = RunObservations((lambda: ObservingRun(events, fault),))
    error = ValueError("original execution error")
    with pytest.raises(ValueError) as raised:
        try:
            with run.bind():
                async with ModelCall("model", None) as call:
                    assert current_model_call() is call
                    call.retry(attempt=2, delay_seconds=0.1)
                    call.completed("stop")
                    call.failed("provider_timeout")
                    bridge_loss_attributes(10)
                    raise error
        finally:
            await run.aclose()
    assert raised.value is error
    assert current_model_call() is None
    assert "aclose" in events
    if fault != "model_call":
        assert "close" in events
    assert "PRIVATE" not in caplog.text


@pytest.mark.asyncio
async def test_unregistered_nested_run_cannot_report_retry_on_parent_call():
    from screamingface_engine.observations import ModelCall, RunObservations, current_model_call

    events = []
    outer = RunObservations((lambda: ObservingRun(events, ""),))
    inner = RunObservations(())
    with outer.bind():
        async with ModelCall("model", None) as call:
            with inner.bind():
                assert current_model_call() is None
            assert current_model_call() is call
    assert "retry" not in events
    await inner.aclose()
    await outer.aclose()


@pytest.mark.asyncio
async def test_run_cleanup_stops_abandoned_activity_heartbeat():
    import asyncio

    from screamingface_engine.observation_plugins import observation_factories
    from screamingface_engine.observations import ModelCall, RunObservations

    run = RunObservations(observation_factories({"URL4_CLOUD_ACTIVITY_LEVEL": "full"}))
    entered, release = asyncio.Event(), asyncio.Event()
    records = []

    def emit(body, attributes=None, *, severity="INFO"):
        records.append(attributes)

    async def child():
        async with ModelCall("model", emit):
            entered.set()
            await release.wait()

    with run.bind():
        task = asyncio.create_task(child())
        await entered.wait()
    await run.aclose()
    assert not [t for t in asyncio.all_tasks() if "Operation._heartbeat" in str(t.get_coro())]
    release.set()
    await task
    assert len(records) == 1  # no late terminal after revocation


@pytest.mark.asyncio
async def test_broken_fault_diagnostic_cannot_replace_execution_error(monkeypatch):
    from screamingface_engine import observations

    def broken_diagnostic(*args, **kwargs):
        raise RuntimeError("broken log handler")

    monkeypatch.setattr(observations.logger, "warning", broken_diagnostic)
    run = observations.RunObservations((lambda: ObservingRun([], "retry"),))
    error = ValueError("original work failure")
    with pytest.raises(ValueError) as raised:
        with run.bind():
            async with observations.ModelCall("model", None) as call:
                call.retry(attempt=2, delay_seconds=0.1)
                raise error
    assert raised.value is error
    await run.aclose()


@pytest.mark.asyncio
async def test_repeated_observer_failures_emit_one_safe_warning_per_run(caplog):
    from screamingface_engine.observations import ModelCall, RunObservations

    run = RunObservations((lambda: ObservingRun([], "retry"),))
    with run.bind():
        async with ModelCall("model", None) as call:
            for _ in range(1000):
                call.retry(attempt=2, delay_seconds=0.1)
    await run.aclose()
    assert caplog.text.count("execution observer failed") == 1


@pytest.mark.asyncio
async def test_cancellation_during_observer_start_unwinds_call_and_resources():
    import asyncio

    from screamingface_engine.observations import ModelCall, RunObservations, current_model_call

    events = []

    class CancelledCall(ObservingCall):
        async def start(self):
            raise asyncio.CancelledError()

    observer = ObservingRun(events, "")
    observer.call = CancelledCall(events, "")
    run = RunObservations((lambda: observer,))
    with run.bind():
        with pytest.raises(asyncio.CancelledError):
            async with ModelCall("model", None):
                pytest.fail("work must not start after cancellation")
        assert current_model_call() is None
    await run.aclose()
    assert events == ["bind", "model_call", "close", "unbind", "aclose"]


@pytest.mark.asyncio
async def test_bad_loss_attributes_do_not_break_transport_diagnostic():
    from screamingface_engine.observations import RunObservations, bridge_loss_attributes

    class BadLoss(ObservingRun):
        def bridge_loss(self, dropped):
            return {"bad": float("nan")}

    run = RunObservations((lambda: BadLoss([], ""),))
    with run.bind():
        assert bridge_loss_attributes(3) == {}
    await run.aclose()
