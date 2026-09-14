"""Optional observation dispatch preserves execution outcomes and context isolation."""

import pytest


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
