"""One failed Candidate does not stop its siblings (spec 2026-09-28 sdk-run-isolation §5).

FEATURE: OME-1071 (runner half) + OME-1067 (multi-Candidate part) — the Evaluation outcome
when one Candidate fails.
STORY: as a researcher who evaluates several Candidates at once, when one Candidate's
stream is lost or the Engine never admits it, the other Candidates still finish, and I get
their results in the error's Partial Report together with the name and the code of each
failed Candidate.

The Runs go through the REAL transport against the multi-Run stub `_isolation_engine.py`,
which records the capability of every `DELETE /`. A thin wrapper replaces only the result
body of a completed Run with a valid Candidate result, because the stub's body is not one.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, cast

import httpx
import pytest
from _isolation_engine import RunPlan, StubEngine, isolation_engine
from test_client_run import _engine as _catalog_engine

import screamingface as sf
from screamingface._core.ports import _RunOutcome
from screamingface._engine.transport import AsyncUrl4CloudTransport, Url4CloudTransport
from screamingface._evaluation.model import Candidate
from screamingface.errors import ExecutionError


def valid_body(case_count: int = 1) -> str:
    """A Candidate result that the SDK decodes against the `draco` fixture Benchmark."""
    return json.dumps(
        {
            "schema": "screamingface.candidate-result.v1",
            "benchmark_id": "draco",
            "benchmark_revision": "fixture-revision",
            "case_count": case_count,
            "score": 0.8,
            "coverage": 1.0,
            "metrics": {},
            "cases": [
                {
                    "status": "scored",
                    "case_id": 1,
                    "input": "Question",
                    "output": "Answer",
                    "finish_reason": "stop",
                    "refusal": None,
                    "stop_reason": None,
                    "rounds_executed": None,
                    "grade": {"method": "fixture", "score": 0.8, "metrics": {}, "checks": []},
                    "failures": [],
                    "metadata": {},
                }
            ],
            "failures": [],
        }
    )


def valid_outcome(name: str) -> _RunOutcome:
    return _RunOutcome(
        run_id=f"run_{name}",
        started_at=datetime(2026, 9, 29, tzinfo=UTC),
        completed_at=datetime(2026, 9, 29, 0, 0, 1, tzinfo=UTC),
        result_body=valid_body(),
        media_type="application/json",
        root_usage=None,
    )


class _PlansByName(dict[str, RunPlan]):
    """The stub looks a plan up by the Run's URL4; the compiled URL4 carries the name."""

    def __missing__(self, url4: str) -> RunPlan:
        for name, plan in self.items():
            if f'"name":"{name}"' in url4:
                return plan
        raise KeyError(url4)


class _Recorder:
    """What a test needs to see around the real transport."""

    def __init__(self, on_failure: threading.Event | None = None) -> None:
        self.url4: dict[str, str] = {}
        self.cancel_calls = 0
        self.on_failure = on_failure

    def enter(self, candidate: Candidate) -> None:
        self.url4[candidate.name] = candidate.url4

    def failed(self) -> None:
        # WHY: the sibling stream is held open until a failure happened, so the sibling is
        # provably still running when its neighbour fails.
        if self.on_failure is not None:
            self.on_failure.set()


class _SyncRecorded(_Recorder):
    def __init__(self, real: Url4CloudTransport, on_failure: threading.Event | None = None) -> None:
        super().__init__(on_failure)
        self.real = real

    def run(self, candidate: Candidate, on_event: Any) -> _RunOutcome:
        self.enter(candidate)
        try:
            return replace(self.real.run(candidate, on_event), result_body=valid_body())
        except BaseException:
            self.failed()
            raise

    def cancel_active(self) -> None:
        self.cancel_calls += 1
        self.real.cancel_active()

    def close(self) -> None:
        self.real.close()


class _AsyncRecorded(_Recorder):
    def __init__(
        self, real: AsyncUrl4CloudTransport, on_failure: threading.Event | None = None
    ) -> None:
        super().__init__(on_failure)
        self.real = real

    async def run(self, candidate: Candidate, on_event: Any) -> _RunOutcome:
        self.enter(candidate)
        try:
            outcome = await self.real.run(candidate, on_event)
        except BaseException:
            self.failed()
            raise
        return replace(outcome, result_body=valid_body())

    async def cancel_active(self) -> None:
        self.cancel_calls += 1
        await self.real.cancel_active()

    async def close(self) -> None:
        await self.real.close()


def _capability(engine: StubEngine, recorder: _Recorder, name: str) -> str | None:
    return engine.state.capability_of(recorder.url4[name])


def _failing_plan(kind: str) -> RunPlan:
    if kind == "refused":
        # A fatal non-Access 401 on the reconnect: the transport stops this Run only (C2).
        return RunPlan(first="drop", reconnects=[401])
    # The Engine never admits the start inside the (short) admission budget (OME-1066).
    return RunPlan(admission=[(503, "1")] * 20)


_FAILURES = [("refused", "websocket_disconnected"), ("capacity", "engine_at_capacity")]
_MODELS = [sf.Model("provider/opus", name="healthy"), sf.Model("provider/opus", name="broken")]


def _client(transport: object) -> sf.Client:
    return sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_catalog_engine),
        run_transport=cast(Any, transport),
    )


def _async_client(transport: object) -> sf.AsyncClient:
    return sf.AsyncClient(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_catalog_engine),
        run_transport=cast(Any, transport),
    )


def _assert_isolated_failure(
    error: ExecutionError, engine: StubEngine, recorder: _Recorder, code: str
) -> None:
    # INVARIANT (spec §5 item 5): the error names each failed Candidate and its code, and
    # its cause is that failure itself.
    assert error.code == "candidates_failed"
    assert error.details == {"failed": {"broken": code}}
    assert isinstance(error.__cause__, ExecutionError)
    assert error.__cause__.code == code
    assert "1 of 2 Candidates failed: broken (" + code + ")" in error.message
    # INVARIANT (spec §5.2): the Partial Report holds the sibling that succeeded, only.
    assert error.partial_report is not None
    assert [result.name for result in error.partial_report.candidates] == ["healthy"]
    assert error.partial_report.candidates.only.score == 0.8
    # WHY: IPython shows only message, hint and code, so the hint points to the results.
    assert error.hint is not None and "error.partial_report" in error.hint
    # INVARIANT (spec 4.1 C1b): nothing swept; the healthy Run was never stopped.
    assert recorder.cancel_calls == 0
    assert _capability(engine, recorder, "healthy") not in engine.state.deleted


@pytest.mark.parametrize(("kind", "code"), _FAILURES)
def test_one_failed_candidate_lets_its_sibling_finish(kind: str, code: str) -> None:
    hold = threading.Event()
    plans = _PlansByName(healthy=RunPlan(hold=hold), broken=_failing_plan(kind))
    with isolation_engine(plans) as engine:
        real = Url4CloudTransport(engine.url, reconnect_base_delay_s=0.01, admission_budget_s=0.3)
        recorder = _SyncRecorded(real, on_failure=hold)
        with _client(recorder) as client, pytest.raises(ExecutionError) as caught:
            client.evaluate(_MODELS, benchmark="draco", progress=False)
        recorder.close()

    _assert_isolated_failure(caught.value, engine, recorder, code)


@pytest.mark.asyncio
@pytest.mark.parametrize(("kind", "code"), _FAILURES)
async def test_async_one_failed_candidate_lets_its_sibling_finish(kind: str, code: str) -> None:
    hold = threading.Event()
    plans = _PlansByName(healthy=RunPlan(hold=hold), broken=_failing_plan(kind))
    with isolation_engine(plans) as engine:
        real = AsyncUrl4CloudTransport(
            engine.url, reconnect_base_delay_s=0.01, admission_budget_s=0.3
        )
        recorder = _AsyncRecorded(real, on_failure=hold)
        async with _async_client(recorder) as client:
            with pytest.raises(ExecutionError) as caught:
                await client.evaluate(_MODELS, benchmark="draco", progress=False)
        # INVARIANT (task hygiene): every Candidate task was awaited before the raise.
        assert [task for task in asyncio.all_tasks() if task is not asyncio.current_task()] == []
        await recorder.close()

    _assert_isolated_failure(caught.value, engine, recorder, code)


_BOTH_BROKEN = [sf.Model("provider/opus", name="first"), sf.Model("provider/opus", name="second")]


def _assert_all_failed(error: ExecutionError) -> None:
    assert error.code == "candidates_failed"
    assert error.details == {
        "failed": {"first": "websocket_disconnected", "second": "websocket_disconnected"}
    }
    # WHY None: a Report requires at least one Candidate (spec §5.2).
    assert error.partial_report is None
    assert isinstance(error.__cause__, ExecutionError)
    assert "2 of 2 Candidates failed" in error.message
    assert error.hint is not None and "No Candidate succeeded" in error.hint
    # WHY (review fix 7): raised outside the carrier's `except`, so the context does not
    # keep every settled result body alive.
    assert error.__context__ is None or error.__context__ is error.__cause__


def test_when_every_candidate_fails_there_is_no_partial_report() -> None:
    plans = _PlansByName(first=_failing_plan("refused"), second=_failing_plan("refused"))
    with isolation_engine(plans) as engine:
        recorder = _SyncRecorded(Url4CloudTransport(engine.url, reconnect_base_delay_s=0.01))
        with _client(recorder) as client, pytest.raises(ExecutionError) as caught:
            client.evaluate(_BOTH_BROKEN, benchmark="draco", progress=False)
        recorder.close()

    _assert_all_failed(caught.value)
    assert recorder.cancel_calls == 0


@pytest.mark.asyncio
async def test_async_when_every_candidate_fails_there_is_no_partial_report() -> None:
    plans = _PlansByName(first=_failing_plan("refused"), second=_failing_plan("refused"))
    with isolation_engine(plans) as engine:
        recorder = _AsyncRecorded(AsyncUrl4CloudTransport(engine.url, reconnect_base_delay_s=0.01))
        async with _async_client(recorder) as client:
            with pytest.raises(ExecutionError) as caught:
                await client.evaluate(_BOTH_BROKEN, benchmark="draco", progress=False)
        await recorder.close()

    _assert_all_failed(caught.value)
    assert recorder.cancel_calls == 0


_ONE = sf.Model("provider/opus", name="broken")


def test_a_one_candidate_evaluation_raises_the_failure_itself() -> None:
    # INVARIANT (spec §5 item 6): today's behavior — the error itself, no Partial Report.
    with isolation_engine(_PlansByName(broken=_failing_plan("refused"))) as engine:
        recorder = _SyncRecorded(Url4CloudTransport(engine.url, reconnect_base_delay_s=0.01))
        with _client(recorder) as client, pytest.raises(ExecutionError) as caught:
            client.evaluate(_ONE, benchmark="draco", progress=False)
        recorder.close()

    assert caught.value.code == "websocket_disconnected"
    assert caught.value.partial_report is None


@pytest.mark.asyncio
async def test_async_a_one_candidate_evaluation_raises_the_failure_itself() -> None:
    with isolation_engine(_PlansByName(broken=_failing_plan("refused"))) as engine:
        recorder = _AsyncRecorded(AsyncUrl4CloudTransport(engine.url, reconnect_base_delay_s=0.01))
        async with _async_client(recorder) as client:
            with pytest.raises(ExecutionError) as caught:
                await client.evaluate(_ONE, benchmark="draco", progress=False)
        await recorder.close()

    assert caught.value.code == "websocket_disconnected"
    assert caught.value.partial_report is None


# --- C1c: the caller's callback raises -------------------------------------------------


class _CallerBug(Exception):
    pass


def _raise_for(name: str, raised: list[BaseException]) -> Any:
    def on_event(event: sf.Event) -> None:
        if isinstance(event, sf.events.Started) and f'"name":"{name}"' in event.url4:
            error = _CallerBug("the notebook cell's handler failed")
            raised.append(error)
            raise error

    return on_event


def _release_after_first_stop(engine: StubEngine, *holds: threading.Event) -> threading.Thread:
    """Release the held streams once the owner sweep sent its `DELETE /`."""

    def watch() -> None:
        deadline = time.monotonic() + 10
        while not engine.state.deleted and time.monotonic() < deadline:
            time.sleep(0.01)
        for hold in holds:
            hold.set()

    thread = threading.Thread(target=watch, daemon=True)
    thread.start()
    return thread


_CALLBACK_MODELS = [
    sf.Model("provider/opus", name="raiser"),
    sf.Model("provider/opus", name="other"),
]


def test_a_callback_exception_aborts_the_evaluation_and_is_re_raised() -> None:
    # INVARIANT (spec §5.1, owner Q3): the caller's own code failed, so the Evaluation is
    # aborted: the sibling is swept, and the caller gets THEIR exception back (identity).
    # WHY the raiser is not held: its transport stops it in-band and then closes the
    # socket, and the stub answers that close only once its held stream is released.
    hold_other = threading.Event()
    plans = _PlansByName(raiser=RunPlan(), other=RunPlan(hold=hold_other))
    raised: list[BaseException] = []
    with isolation_engine(plans) as engine:
        recorder = _SyncRecorded(Url4CloudTransport(engine.url, reconnect_base_delay_s=0.01))
        watcher = _release_after_first_stop(engine, hold_other)
        with _client(recorder) as client, pytest.raises(_CallerBug) as caught:
            client.evaluate(
                _CALLBACK_MODELS,
                benchmark="draco",
                progress=False,
                on_event=_raise_for("raiser", raised),
            )
        watcher.join(timeout=10)
        recorder.close()

    assert raised == [caught.value]
    assert recorder.cancel_calls == 1
    assert engine.state.deleted == [_capability(engine, recorder, "other")]


@pytest.mark.asyncio
async def test_async_a_callback_exception_aborts_the_evaluation_and_is_re_raised() -> None:
    # WHY the raiser is not held: its transport stops it in-band and then closes the
    # socket, and the stub answers that close only once its held stream is released.
    hold_other = threading.Event()
    plans = _PlansByName(raiser=RunPlan(), other=RunPlan(hold=hold_other))
    raised: list[BaseException] = []
    with isolation_engine(plans) as engine:
        recorder = _AsyncRecorded(AsyncUrl4CloudTransport(engine.url, reconnect_base_delay_s=0.01))
        watcher = _release_after_first_stop(engine, hold_other)
        async with _async_client(recorder) as client:
            with pytest.raises(_CallerBug) as caught:
                await client.evaluate(
                    _CALLBACK_MODELS,
                    benchmark="draco",
                    progress=False,
                    on_event=_raise_for("raiser", raised),
                )
        await asyncio.to_thread(watcher.join, 10)
        await recorder.close()

    assert raised == [caught.value]
    assert recorder.cancel_calls == 1
    assert engine.state.deleted == [_capability(engine, recorder, "other")]
