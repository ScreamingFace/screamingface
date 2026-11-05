"""Every evaluate registers a Run before it spends, and binds each start to it (E5 P1 spec R1,
R2, R8, D7, D8; plan C2).

FEATURE: first-class Runs (OME-1785). STORY: as a researcher, each evaluation I start is on the
Engine as a Run I can reopen elsewhere; stopping it with Ctrl-C reads `canceled`, and a cancel
from another notebook stops the starts this one has not made yet.

INVARIANT (D7): when the Engine does not register the Run, the evaluation runs exactly as
before, with one notice.
"""

from __future__ import annotations

import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx
import pytest
from _isolation_engine import RunPlan, candidate, isolation_engine, url4_of
from test_answer_seed_report import _CandidateRecordingTransport
from test_client_run import REPLAY_URL4, _ReplayTransport
from test_draco_vertical_slice import _AsyncFakeTransport
from test_draco_vertical_slice import _engine as _draco_engine

import screamingface as sf
from screamingface._engine import run_binding
from screamingface._engine import runs as wire
from screamingface._engine import transport as transport_module
from screamingface._engine.transport import (
    AsyncUrl4CloudTransport,
    Url4CloudTransport,
    _start_sync,
)
from screamingface.errors import ExecutionError
from screamingface.warnings import EvaluationWarning

RUN_ID = "run_" + "c" * 32
_MODEL = sf.Model("anthropic/claude-haiku-4-5", name="haiku")


@contextmanager
def _sync_transport(url: str) -> Iterator[Url4CloudTransport]:
    transport = Url4CloudTransport(url)
    try:
        yield transport
    finally:
        transport.close()


def _recorded(transport: Url4CloudTransport | AsyncUrl4CloudTransport) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> None:
        seen.append(request)

    async def record_async(request: httpx.Request) -> None:
        seen.append(request)

    hook = record_async if isinstance(transport, AsyncUrl4CloudTransport) else record
    transport._http.event_hooks = {"request": [hook], "response": []}
    return seen


def _starts(seen: list[httpx.Request]) -> list[httpx.Request]:
    return [r for r in seen if r.method == "GET" and r.url.path == "/" and "q" in r.url.params]


# --- the transport ------------------------------------------------------------------------


def test_a_registered_run_binds_every_start() -> None:
    alpha, beta = candidate("alpha"), candidate("beta")
    plans = {url4_of("alpha"): RunPlan(), url4_of("beta"): RunPlan()}
    with isolation_engine(plans) as engine, _sync_transport(engine.url) as transport:
        seen = _recorded(transport)
        run_id = transport.open_run("gsm8k", 3, (alpha, beta))
        transport.run(beta, None)
        transport.run(alpha, None)

    (body,) = engine.state.registered
    assert body["candidates"] == ["alpha", "beta"]
    assert (body["benchmark"], body["case_count"]) == ("gsm8k", 3)
    assert body["client_version"] == sf.__version__
    assert run_id is not None and run_id.startswith("run_")
    # INVARIANT (spec R1): the Run is registered before the first token.
    assert [r.url.path for r in seen[:2]] == ["/runs", "/token"]
    # A Candidate is named by its index, so any name binds (spec §4.1).
    assert [(r.headers["X-SF-Run"], r.headers["X-SF-Run-Candidate"]) for r in _starts(seen)] == [
        (run_id, "1"),
        (run_id, "0"),
    ]


def test_a_client_key_is_sent_without_a_result_store() -> None:
    with isolation_engine({}) as engine, _sync_transport(engine.url) as transport:
        assert transport._result_store is None
        transport.open_run("gsm8k", 1, (candidate("alpha"),))
        transport.open_run("gsm8k", 1, (candidate("alpha"),))

    keys = [body["client_key"] for body in engine.state.registered]
    assert all(isinstance(key, str) and len(key) == 32 for key in keys)
    # A fresh key for every evaluate: two evaluations are two Runs.
    assert keys[0] != keys[1]


def test_an_unregistered_run_starts_as_before_with_one_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wire, "create_sync", lambda *_a: wire.Unavailable("HTTP 404"))
    alpha = candidate("alpha")
    with isolation_engine({url4_of("alpha"): RunPlan()}) as engine:
        with _sync_transport(engine.url) as transport:
            seen = _recorded(transport)
            with pytest.warns(EvaluationWarning, match="not recorded as a Run") as caught:
                run_id = transport.open_run("gsm8k", 1, (alpha,))
            registered = transport.run(alpha, None)
        with _sync_transport(engine.url) as transport:
            unregistered = transport.run(candidate("alpha"), None)

    assert run_id is None and len(caught) == 1
    assert not any(name.startswith("x-sf-run") for name in _starts(seen)[0].headers)
    assert (registered.result_body, registered.media_type, registered.root_usage) == (
        unregistered.result_body,
        unregistered.media_type,
        unregistered.root_usage,
    )


def test_an_abort_cancels_the_run() -> None:
    alpha = candidate("alpha")
    with isolation_engine({}) as engine, _sync_transport(engine.url) as transport:
        run_id = transport.open_run("gsm8k", 1, (alpha,))
        transport.abort_evaluation((alpha,))

    assert engine.state.canceled_runs == [run_id]


def test_an_abort_leaves_another_evaluations_run_alone() -> None:
    alpha, beta = candidate("alpha"), candidate("beta")
    with isolation_engine({}) as engine, _sync_transport(engine.url) as transport:
        aborted = transport.open_run("gsm8k", 1, (alpha,))
        transport.open_run("gsm8k", 1, (beta,))
        transport.abort_evaluation((alpha,))
        transport._runs.refuse_if_canceled(beta)

    assert engine.state.canceled_runs == [aborted]


def test_a_failed_cancel_changes_nothing_else(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: object) -> None:
        raise ExecutionError("down", status=503)

    monkeypatch.setattr(wire, "cancel_sync", refuse)
    alpha = candidate("alpha")
    with isolation_engine({}) as engine, _sync_transport(engine.url) as transport:
        transport.open_run("gsm8k", 1, (alpha,))
        transport.abort_evaluation((alpha,))

        # The abort still took effect: the Run's later starts are refused.
        with pytest.raises(ExecutionError):
            transport._runs.refuse_if_canceled(alpha)


def test_a_finished_candidate_is_not_canceled() -> None:
    alpha = candidate("alpha")
    with isolation_engine({url4_of("alpha"): RunPlan()}) as engine:
        with _sync_transport(engine.url) as transport:
            transport.open_run("gsm8k", 1, (alpha,))
            transport.run(alpha, None)
            transport.abort_evaluation((alpha,))

    assert engine.state.canceled_runs == []


def test_a_canceled_run_stops_its_remaining_starts(monkeypatch: pytest.MonkeyPatch) -> None:
    alpha, beta = candidate("alpha"), candidate("beta")

    def refused(*_args: object, **_kwargs: object) -> None:
        raise run_binding.canceled_error()

    monkeypatch.setattr(transport_module, "_start_sync", refused)
    with isolation_engine({}) as engine, _sync_transport(engine.url) as transport:
        transport.open_run("gsm8k", 2, (alpha, beta))
        with pytest.raises(ExecutionError, match="canceled"):
            transport.run(alpha, None)
        minted = len(engine.state.topics)
        with pytest.raises(ExecutionError) as caught:
            transport.run(beta, None)

    assert caught.value.code == "run_canceled"
    assert len(engine.state.topics) == minted, "the remaining start minted nothing"


@pytest.mark.asyncio
async def test_the_async_transport_registers_binds_and_cancels() -> None:
    alpha, beta = candidate("alpha"), candidate("beta")
    with isolation_engine({url4_of("alpha"): RunPlan()}) as engine:
        transport = AsyncUrl4CloudTransport(engine.url)
        seen = _recorded(transport)
        run_id = await transport.open_run("gsm8k", 2, (alpha, beta))
        await transport.run(alpha, None)
        await transport.abort_evaluation((alpha, beta))
        await transport.close()

    assert [r.url.path for r in seen[:2]] == ["/runs", "/token"]
    assert _starts(seen)[0].headers["X-SF-Run"] == run_id
    # `beta` never started, so the Run was still in flight.
    assert engine.state.canceled_runs == [run_id]


# --- the start's answer -------------------------------------------------------------------


def _problem(status: int, code: str | None, **headers: str) -> httpx.Response:
    body: dict[str, Any] = {"type": "about:blank", "title": "x", "status": status}
    if code is not None:
        body["code"] = code
    return httpx.Response(
        status, json=body, headers={"content-type": "application/problem+json", **headers}
    )


@pytest.mark.parametrize("code", ["run_canceled", "candidate_already_started", "run_not_found"])
def test_a_refused_run_start_keeps_its_code_after_a_resend(code: str) -> None:
    # INVARIANT: a re-sent start's 409 is normally its own earlier attempt; a Run refusal is not.
    answers = [_problem(503, None, **{"Retry-After": "0"}), _problem(409, code)]
    http = httpx.Client(
        base_url="https://engine.test", transport=httpx.MockTransport(lambda _r: answers.pop(0))
    )

    with pytest.raises(ExecutionError) as caught:
        _start_sync(http, "cap", "(@)!'go'", wait=lambda _delay: False)

    assert caught.value.code == code


def test_a_resent_start_still_reads_its_own_409() -> None:
    answers = [_problem(503, None, **{"Retry-After": "0"}), _problem(409, None)]
    http = httpx.Client(
        base_url="https://engine.test", transport=httpx.MockTransport(lambda _r: answers.pop(0))
    )

    _start_sync(http, "cap", "(@)!'go'", wait=lambda _delay: False)


# --- the evaluation -----------------------------------------------------------------------


class _RegisteringTransport(_CandidateRecordingTransport):
    def __init__(self) -> None:
        super().__init__()
        self.opened: list[tuple[str, int, tuple[Any, ...]]] = []

    def open_run(self, benchmark: str, case_count: int, candidates: tuple[Any, ...]) -> str:
        assert not self.candidates, "registered before any Candidate ran"
        self.opened.append((benchmark, case_count, candidates))
        return RUN_ID

    def abort_evaluation(self, candidates: tuple[Any, ...]) -> None:
        self.cancel_active()


def _client(transport: object) -> sf.Client:
    return sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_draco_engine),
        run_transport=transport,  # pyright: ignore[reportArgumentType]
    )


def test_a_recipe_evaluation_registers_and_names_its_run() -> None:
    transport = _RegisteringTransport()
    with _client(transport) as client:
        report = client.evaluate(_MODEL, benchmark="draco", limit=1)

    ((benchmark, case_count, registered),) = transport.opened
    assert (benchmark, case_count) == ("draco", 1)
    assert registered == tuple(transport.candidates)
    assert report.run_id == RUN_ID


def test_an_evaluation_without_a_run_is_unchanged() -> None:
    with _client(_RegisteringTransport()) as client:
        registered = client.evaluate(_MODEL, benchmark="draco", limit=1)
    with _client(_CandidateRecordingTransport()) as client, warnings.catch_warnings():
        warnings.simplefilter("error")
        plain = client.evaluate(_MODEL, benchmark="draco", limit=1)

    assert plain.run_id is None
    assert (plain.benchmark, plain.case_count, plain.candidates) == (
        registered.benchmark,
        registered.case_count,
        registered.candidates,
    )


class _RegisteringReplayTransport(_ReplayTransport):
    def __init__(self) -> None:
        super().__init__()
        self.opened: list[tuple[str, int, tuple[Any, ...]]] = []

    def open_run(self, benchmark: str, case_count: int, candidates: tuple[Any, ...]) -> str:
        assert self.candidate is None, "registered before the Candidate ran"
        self.opened.append((benchmark, case_count, candidates))
        return RUN_ID

    def abort_evaluation(self, candidates: tuple[Any, ...]) -> None:
        self.cancel_active()


def test_a_raw_url4_evaluation_registers() -> None:
    transport = _RegisteringReplayTransport()
    with _client(transport) as client:
        report = client.evaluate(REPLAY_URL4)

    ((benchmark, case_count, registered),) = transport.opened
    assert (benchmark, case_count, len(registered)) == ("URL4 replay", 0, 1)
    assert report.run_id == RUN_ID


class _AsyncRegisteringTransport(_AsyncFakeTransport):
    def __init__(self) -> None:
        super().__init__()
        self.opened: list[str] = []

    async def open_run(self, benchmark: str, case_count: int, candidates: tuple[Any, ...]) -> str:
        self.opened.append(benchmark)
        return RUN_ID

    async def abort_evaluation(self, candidates: tuple[Any, ...]) -> None:
        await self.cancel_active()


@pytest.mark.asyncio
async def test_an_async_recipe_evaluation_registers() -> None:
    transport = _AsyncRegisteringTransport()
    client = sf.AsyncClient(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_draco_engine),
        run_transport=transport,  # pyright: ignore[reportArgumentType]
    )
    async with client:
        report = await client.evaluate(_MODEL, benchmark="draco", limit=1)

    assert transport.opened == ["draco"] and report.run_id == RUN_ID


# --- the local manifest (spec D8) ---------------------------------------------------------


def _evaluation(selected: Any) -> Any:
    from screamingface._evaluation.model import _compiled_evaluation
    from screamingface.discovery import BenchmarkInfo

    return _compiled_evaluation(
        benchmark=BenchmarkInfo("draco", "fixture-revision", 1),
        limit=None,
        case_count=1,
        candidates=(selected,),
        required_models=selected.models,
    )


@pytest.mark.parametrize("registered", [True, False])
def test_the_manifest_is_keyed_by_the_run(
    registered: bool, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SCREAMINGFACE_RESULTS_DIR", str(tmp_path))
    monkeypatch.setattr(transport_module, "new_client_key", lambda: "k" * 32)
    if not registered:
        monkeypatch.setattr(wire, "create_sync", lambda *_a: wire.Unavailable("HTTP 404"))
    alpha = candidate("alpha")
    with isolation_engine({}) as engine:
        transport = Url4CloudTransport(engine.url, save_results=True)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", EvaluationWarning)
                run_id = transport.open_run("draco", 1, (alpha,))
            path = transport.prepare_results(_evaluation(alpha), (alpha,))
        finally:
            transport.close()

    assert path is not None
    # Unregistered, the evaluation is keyed by the `client_key` it sent (spec §4.1).
    assert path.stem == (run_id if registered else "k" * 32)


# --- an abort of a one-Candidate evaluate (spec R8) ----------------------------------------


def test_an_interrupted_run_cancels_its_run(monkeypatch: pytest.MonkeyPatch) -> None:
    # WHY here and not only in `cancel_active`: a one-Candidate or raw-URL4 evaluate is
    # stopped by the interrupt itself, and never sweeps.
    alpha = candidate("alpha")

    def interrupted(*_args: object) -> None:
        raise KeyboardInterrupt

    with isolation_engine({}) as engine, _sync_transport(engine.url) as transport:
        run_id = transport.open_run("gsm8k", 1, (alpha,))
        monkeypatch.setattr(transport, "_run", interrupted)
        with pytest.raises(KeyboardInterrupt):
            transport.run(alpha, None)

    assert engine.state.canceled_runs == [run_id]


@pytest.mark.asyncio
async def test_a_cancelled_async_run_cancels_its_run(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    alpha = candidate("alpha")

    async def cancelled(*_args: object) -> None:
        raise asyncio.CancelledError

    with isolation_engine({}) as engine:
        transport = AsyncUrl4CloudTransport(engine.url)
        run_id = await transport.open_run("gsm8k", 1, (alpha,))
        monkeypatch.setattr(transport, "_run", cancelled)
        with pytest.raises(asyncio.CancelledError):
            await transport.run(alpha, None)
        await transport.close()

    assert engine.state.canceled_runs == [run_id]


# --- abort order, a failed save and a partial report ---------------------------------------


def test_an_abort_stops_its_runs_before_it_cancels_them(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []
    monkeypatch.setattr(transport_module, "_stop_sync", lambda *_a: order.append("stop"))
    monkeypatch.setattr(wire, "cancel_sync", lambda *_a: order.append("cancel"))
    alpha = candidate("alpha")
    with isolation_engine({}) as engine, _sync_transport(engine.url) as transport:
        transport.open_run("gsm8k", 1, (alpha,))
        transport._active_tokens.add("cap-1")
        transport._minted_by[id(alpha)] = ["cap-1"]
        transport.abort_evaluation((alpha,))

    # WHY: a slow Engine must never delay stopping paid work.
    assert order == ["stop", "cancel"]


def test_a_failed_result_save_forgets_the_run_bindings(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from screamingface._evaluation import runner
    from screamingface.errors import ExecutionError as Failed

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise Failed("disk full", code="result_storage_failed")

    alpha = candidate("alpha")
    with isolation_engine({}) as engine, _sync_transport(engine.url) as transport:
        transport.open_run("gsm8k", 1, (alpha,))
        monkeypatch.setattr(transport, "prepare_results", refuse)
        with pytest.raises(Failed), runner._prepared_results(transport, object(), (alpha,)):
            pass

        assert transport._runs.headers(alpha) == {}


class _FailingRegisteringTransport(_RegisteringTransport):
    def run(self, candidate: Any, on_event: object) -> Any:
        if candidate.name == "broken":
            raise ExecutionError("boom", code="run_failed")
        return super().run(candidate, on_event)


def test_a_partial_report_names_its_run() -> None:
    transport = _FailingRegisteringTransport()
    with _client(transport) as client, pytest.raises(ExecutionError) as caught:
        client.evaluate(
            [_MODEL, sf.Model("anthropic/claude-haiku-4-5", name="broken")],
            benchmark="draco",
            limit=1,
        )

    assert caught.value.code == "candidates_failed"
    assert caught.value.partial_report is not None
    assert caught.value.partial_report.run_id == RUN_ID


def test_an_abort_refuses_queued_starts_while_it_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    alpha, beta = candidate("alpha"), candidate("beta")
    refused: list[bool] = []

    def stop(*_args: object) -> None:
        # A queued Candidate of the aborted Run tries to start during the stops.
        try:
            transport._runs.refuse_if_canceled(beta)
        except ExecutionError:
            refused.append(True)

    monkeypatch.setattr(transport_module, "_stop_sync", stop)
    with isolation_engine({}) as engine, _sync_transport(engine.url) as transport:
        transport.open_run("gsm8k", 2, (alpha, beta))
        transport._active_tokens.add("cap-1")
        transport._minted_by[id(alpha)] = ["cap-1"]
        transport.abort_evaluation((alpha, beta))

    assert refused == [True]
