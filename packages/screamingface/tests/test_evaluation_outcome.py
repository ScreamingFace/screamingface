"""One failed Candidate does not stop its siblings (spec 2026-09-28 sdk-run-isolation §5).

FEATURE: OME-1071 (runner half) + OME-1067 (multi-Candidate part) — the Evaluation outcome
when one Candidate fails.
STORY: as a researcher who evaluates several Candidates at once, when one Candidate's
stream is lost or the Engine never admits it, the other Candidates still finish, and I get
their results in the error's Partial Report together with the name and the code of each
failed Candidate.

The Runs go through the REAL transport against the Run stub `_run_engine.py` (E5 P2): the
Engine drives the Run and settles each Candidate, and the stub records every `DELETE /runs`.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from _run_engine import RUN_ID, RunEngine, ended, event, run_engine, settled, state, topic
from test_client_run import _engine as _catalog_engine

import screamingface as sf
from screamingface._core.ports import _RunOutcome
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


_HEALTHY = valid_body().encode()
_RESULTS = {0: _HEALTHY, 1: _HEALTHY}
# The two ways one Candidate fails on a Run the Engine drives: its run failed, or the Engine
# refused its start. The Candidate's code comes from its record, or from its row (§4.3).
_FAILURES = [("run", "provider_error"), ("refused", "start_refused")]
_MODELS = [sf.Model("provider/opus", name="healthy"), sf.Model("provider/opus", name="broken")]


def _failed(index: int, kind: str) -> str:
    if kind == "run":
        error = {"code": "provider_error", "message": "upstream down", "permanent": False}
        return settled(index, b"", state="failed", error={**error, "details": None})
    frame = json.loads(settled(index, b"", state="failed"))
    frame.update(record=None, error_code="start_refused", attempt_id=None)
    return json.dumps(frame)


def _client(url: str) -> sf.Client:
    return sf.Client(engine_url=url, http_transport=httpx.MockTransport(_catalog_engine))


def _async_client(url: str) -> sf.AsyncClient:
    return sf.AsyncClient(engine_url=url, http_transport=httpx.MockTransport(_catalog_engine))


def _assert_isolated_failure(error: ExecutionError, engine: RunEngine, code: str) -> None:
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
    # INVARIANT (spec 4.1 C1b): one Candidate's failure cancels nothing.
    assert engine.state.deleted == []


def _one_broken(kind: str) -> list[list[str | int]]:
    # WHY the failure first: the sibling is provably still running when its neighbour fails.
    return [
        [
            state(0, "scheduled"),
            event(0, 1),
            _failed(1, kind),
            settled(0, _HEALTHY),
            ended("partial"),
        ]
    ]


@pytest.mark.parametrize(("kind", "code"), _FAILURES)
def test_one_failed_candidate_lets_its_sibling_finish(kind: str, code: str) -> None:
    with run_engine(_one_broken(kind), _RESULTS) as engine, _client(engine.url) as client:
        with pytest.raises(ExecutionError) as caught:
            client.evaluate(_MODELS, benchmark="draco", progress=False)

    _assert_isolated_failure(caught.value, engine, code)


@pytest.mark.asyncio
@pytest.mark.parametrize(("kind", "code"), _FAILURES)
async def test_async_one_failed_candidate_lets_its_sibling_finish(kind: str, code: str) -> None:
    with run_engine(_one_broken(kind), _RESULTS) as engine:
        async with _async_client(engine.url) as client:
            with pytest.raises(ExecutionError) as caught:
                await client.evaluate(_MODELS, benchmark="draco", progress=False)
        # INVARIANT (task hygiene): nothing the evaluation started outlives the raise.
        assert [task for task in asyncio.all_tasks() if task is not asyncio.current_task()] == []

    _assert_isolated_failure(caught.value, engine, code)


_BOTH_BROKEN = [sf.Model("provider/opus", name="first"), sf.Model("provider/opus", name="second")]


def _assert_all_failed(error: ExecutionError) -> None:
    assert error.code == "candidates_failed"
    assert error.details == {"failed": {"first": "provider_error", "second": "provider_error"}}
    # WHY None: a Report requires at least one Candidate (spec §5.2).
    assert error.partial_report is None
    assert isinstance(error.__cause__, ExecutionError)
    assert "2 of 2 Candidates failed" in error.message
    assert error.hint is not None and "No Candidate succeeded" in error.hint
    # WHY (review fix 7): raised outside the carrier's `except`, so the context does not
    # keep every settled result body alive.
    assert error.__context__ is None or error.__context__ is error.__cause__


_ALL_BROKEN = [[_failed(0, "run"), _failed(1, "run"), ended("errored")]]


def test_when_every_candidate_fails_there_is_no_partial_report() -> None:
    with run_engine(_ALL_BROKEN, {}) as engine, _client(engine.url) as client:
        with pytest.raises(ExecutionError) as caught:
            client.evaluate(_BOTH_BROKEN, benchmark="draco", progress=False)

    _assert_all_failed(caught.value)
    assert engine.state.deleted == []


@pytest.mark.asyncio
async def test_async_when_every_candidate_fails_there_is_no_partial_report() -> None:
    with run_engine(_ALL_BROKEN, {}) as engine:
        async with _async_client(engine.url) as client:
            with pytest.raises(ExecutionError) as caught:
                await client.evaluate(_BOTH_BROKEN, benchmark="draco", progress=False)

    _assert_all_failed(caught.value)
    assert engine.state.deleted == []


_ONE = sf.Model("provider/opus", name="broken")
_ONE_BROKEN = [[_failed(0, "run"), ended("errored")]]


def test_a_one_candidate_evaluation_raises_the_failure_itself() -> None:
    # INVARIANT (spec §5 item 6): today's behavior — the error itself, no Partial Report.
    with run_engine(_ONE_BROKEN, {}) as engine, _client(engine.url) as client:
        with pytest.raises(ExecutionError) as caught:
            client.evaluate(_ONE, benchmark="draco", progress=False)

    assert caught.value.code == "provider_error"
    assert caught.value.partial_report is None


@pytest.mark.asyncio
async def test_async_a_one_candidate_evaluation_raises_the_failure_itself() -> None:
    with run_engine(_ONE_BROKEN, {}) as engine:
        async with _async_client(engine.url) as client:
            with pytest.raises(ExecutionError) as caught:
                await client.evaluate(_ONE, benchmark="draco", progress=False)

    assert caught.value.code == "provider_error"
    assert caught.value.partial_report is None


# --- C1c: the caller's callback raises -------------------------------------------------


class _CallerBug(Exception):
    pass


def _raise_for(index: int, raised: list[BaseException]) -> Any:
    def on_event(event: sf.Event) -> None:
        if event.run_id == topic(index):
            error = _CallerBug("the notebook cell's handler failed")
            raised.append(error)
            raise error

    return on_event


_CALLBACK_MODELS = [
    sf.Model("provider/opus", name="raiser"),
    sf.Model("provider/opus", name="other"),
]
_RUNNING = [
    [
        state(0, "scheduled"),
        state(1, "scheduled"),
        event(1, 1),
        event(0, 1),
        settled(1, _HEALTHY),
        settled(0, _HEALTHY),
        ended(),
    ]
]


def test_a_callback_exception_aborts_the_evaluation_and_is_re_raised() -> None:
    # INVARIANT (spec §5.1, owner Q3): the caller's own code failed, so the Evaluation is
    # aborted: the Run is canceled, and the caller gets THEIR exception back (identity).
    raised: list[BaseException] = []
    with run_engine(_RUNNING, _RESULTS) as engine, _client(engine.url) as client:
        with pytest.raises(_CallerBug) as caught:
            client.evaluate(
                _CALLBACK_MODELS,
                benchmark="draco",
                progress=False,
                on_event=_raise_for(0, raised),
            )

    assert raised == [caught.value]
    assert engine.state.deleted == [f"/runs/{RUN_ID}"]


@pytest.mark.asyncio
async def test_async_a_callback_exception_aborts_the_evaluation_and_is_re_raised() -> None:
    raised: list[BaseException] = []
    with run_engine(_RUNNING, _RESULTS) as engine:
        async with _async_client(engine.url) as client:
            with pytest.raises(_CallerBug) as caught:
                await client.evaluate(
                    _CALLBACK_MODELS,
                    benchmark="draco",
                    progress=False,
                    on_event=_raise_for(0, raised),
                )

    assert raised == [caught.value]
    assert engine.state.deleted == [f"/runs/{RUN_ID}"]
