"""Optional observation dispatch preserves execution outcomes and context isolation."""

import ast
from pathlib import Path

import pytest

from screamingface_engine.runner.operation_capture import OperationCapturingExecutor
from url4.streaming.interfaces import Executor
from url4.streaming.protocol import LogData


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


def test_failed_factory_is_inert_and_diagnostic_excludes_exception_text(caplog):
    from screamingface_engine.observations import RunObservations

    def broken():
        raise ValueError("PRIVATE factory detail")

    run = RunObservations((broken,))
    assert run.observers == [] and run.active
    assert "execution observer failed" in caplog.text and "PRIVATE" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["start", "retry", "close"])
async def test_call_fault_budget_belongs_to_captured_run(fault, caplog):
    from screamingface_engine.observations import ModelCall, RunObservations

    owner = RunObservations((lambda: ObservingRun([], fault),))
    nested = RunObservations(())
    with owner.bind():
        call = ModelCall("model", None)
        with nested.bind():
            async with call:
                call.retry(attempt=2, delay_seconds=0)
        assert owner.fault_reported and not nested.fault_reported
        async with ModelCall("model", None) as again:
            again.retry(attempt=2, delay_seconds=0)
    assert caplog.text.count("execution observer failed") == 1


@pytest.mark.parametrize("outcome", ["success", "error", "cancel"])
def test_bind_receives_step_exception_but_cannot_suppress_it(outcome, monkeypatch):
    import asyncio

    from screamingface_engine.observations import RunObservations

    error = {"success": None, "error": ValueError("work"), "cancel": asyncio.CancelledError()}[
        outcome
    ]
    seen = []

    class Binding:
        def __enter__(self):
            return None

        def __exit__(self, kind, value, tb):
            seen.append((kind, value, tb))
            return True

    observer = ObservingRun([], "")
    monkeypatch.setattr(observer, "bind", Binding)
    try:
        with RunObservations((lambda: observer,)).bind():
            if error is not None:
                raise error
    except BaseException as raised:
        assert raised is error
    else:
        assert error is None
    assert seen[0][:2] == (type(error) if error is not None else None, error)
    assert (seen[0][2] is None) == (error is None)


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
async def test_composition_injects_observer_for_real_model_retry_and_outcome(monkeypatch):
    import httpx

    from screamingface_engine.runner import connector
    from screamingface_engine.runner.main import build_executor
    from screamingface_engine.world_config import AigatewaySection, ModelSpec, WorldConfig

    events, requests = [], []

    class Call(ObservingCall):
        def retry(self, *, attempt, delay_seconds):
            assert (attempt, delay_seconds) == (2, 0.0)
            super().retry(attempt=attempt, delay_seconds=delay_seconds)

        def completed(self, finish_reason):
            assert finish_reason == "stop"
            super().completed(finish_reason)

    observer = ObservingRun(events, "")
    observer.call = Call(events, "")

    def respond(request):
        requests.append(request)
        if len(requests) == 1:
            raise httpx.ReadError("retry once")
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "answer"}, "finish_reason": "stop"}],
            },
        )

    config = WorldConfig(
        aigateway=AigatewaySection(
            base_url="http://gateway",
            default_model="model",
            models=(ModelSpec(id="model"),),
        )
    )
    monkeypatch.setattr(connector, "_transport_backoff", lambda _: 0.0)
    async with httpx.AsyncClient(
        base_url="http://gateway",
        transport=httpx.MockTransport(respond),
    ) as client:
        executor = build_executor({}, config, client=client, observers=(lambda: observer,))
        frames = [frame async for frame in executor.execute("/model('question')!go")]
    assert len(requests) == 2
    assert frames
    assert [e for e in events if e not in {"bind", "unbind"}] == [
        "model_call",
        "start",
        "retry",
        "completed",
        "close",
        "aclose",
    ]


@pytest.mark.asyncio
async def test_execution_rebinds_observer_for_cross_task_close():
    import asyncio
    from contextlib import contextmanager
    from contextvars import ContextVar

    bound = ContextVar[ObservingRun | None]("test_observer", default=None)
    seen = []

    class Observer(ObservingRun):
        @contextmanager
        def bind(self):
            token = bound.set(self)
            try:
                yield
            finally:
                bound.reset(token)

    class Probe(Executor):
        async def execute(self, url4, *, trace=None):
            seen.append(bound.get())
            try:
                yield LogData.at("INFO", "result")
            finally:
                seen.append(bound.get())

    events = []
    observer = Observer(events, "")
    iterator = OperationCapturingExecutor(Probe(), observers=(lambda: observer,)).execute("x")

    async def advance():
        return await anext(iterator)

    await asyncio.create_task(advance())
    assert bound.get() is None
    await asyncio.create_task(getattr(iterator, "aclose")())
    assert seen == [observer, observer]
    assert events == ["aclose"]
    assert bound.get() is None


@pytest.mark.asyncio
async def test_concurrent_executions_construct_and_close_distinct_observers():
    import asyncio

    made = []

    def factory():
        observer = ObservingRun([], "")
        made.append(observer)
        return observer

    class Probe(Executor):
        async def execute(self, url4, *, trace=None):
            await asyncio.sleep(0)
            yield LogData.at("INFO", "result")

    executor = OperationCapturingExecutor(Probe(), observers=(factory,))

    async def consume():
        return [s async for s in executor.execute("x")]

    await asyncio.gather(consume(), consume())
    assert len(made) == 2 and made[0] is not made[1]
    assert all(o.call.events[-1] == "aclose" for o in made)


def test_bridge_loss_observation_decorates_existing_diagnostic_only():
    from screamingface_engine.observations import RunObservations
    from screamingface_engine.runner.cache_counters import RunCacheCounters
    from screamingface_engine.runner.executor import _Bridge, _closing_logs
    from url4.observe import Log

    bridge = _Bridge(maxsize=1)
    bridge.on_event(Log(None, "INFO", "one"))
    bridge.on_event(Log(None, "INFO", "two"))
    run = RunObservations((lambda: ObservingRun([], ""),))
    with run.bind():
        frame = _closing_logs(bridge, RunCacheCounters())[0]
    original = _closing_logs(bridge, RunCacheCounters())[0]
    assert isinstance(frame.payload, LogData) and isinstance(original.payload, LogData)
    assert frame.payload.body == original.payload.body
    assert frame.payload.attributes == {"test.loss": 1}
    assert original.payload.attributes == {}
    assert frame.span is original.span is None


@pytest.mark.asyncio
async def test_iterator_creation_failure_closes_run_observers():
    events = []
    error = ValueError("iterator creation failed")

    class Broken(Executor):
        def execute(self, url4, *, trace=None):
            raise error

    observer = ObservingRun(events, "")
    executor = OperationCapturingExecutor(Broken(), observers=(lambda: observer,))
    with pytest.raises(ValueError) as raised:
        await anext(executor.execute("x"))
    assert raised.value is error
    assert events == ["aclose"]
