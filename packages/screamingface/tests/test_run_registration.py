"""Every evaluate registers a Run before it spends, with every Candidate's start (E5 P1 spec R1,
R8, D8; E5 P2 spec D1, D2, D14; plan C1).

FEATURE: first-class Runs (OME-1785). STORY: as a researcher, each evaluation I start is on the
Engine as a Run I can reopen elsewhere, and stopping it with Ctrl-C reads `canceled`.

INVARIANT (P2 D2): Runs are required. When the Engine does not register the Run, the evaluation
raises before anything runs (it no longer runs without one, as P1's D7 allowed).
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from test_answer_seed_report import _CandidateRecordingTransport
from test_client_run import REPLAY_URL4, _ReplayTransport
from test_draco_vertical_slice import _AsyncFakeTransport
from test_draco_vertical_slice import _engine as _draco_engine

import screamingface as sf
from screamingface._core.ports import SyncRunTransport
from screamingface.errors import ExecutionError

RUN_ID = "run_" + "c" * 32
_MODEL = sf.Model("anthropic/claude-haiku-4-5", name="haiku")


# --- the transport ------------------------------------------------------------------------


# --- the start's answer -------------------------------------------------------------------


# --- the evaluation -----------------------------------------------------------------------


class _RegisteringTransport(_CandidateRecordingTransport):
    def __init__(self) -> None:
        super().__init__()
        self.opened: list[tuple[str, int, tuple[Any, ...]]] = []

    def register_run(self, evaluation: Any, candidates: tuple[Any, ...], **options: Any) -> str:
        assert not self.candidates, "registered before any Candidate ran"
        self.opened.append((evaluation.benchmark.id, evaluation.case_count, candidates))
        return RUN_ID


def _client(transport: SyncRunTransport) -> sf.Client:
    return sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_draco_engine),
        run_transport=transport,
    )


def test_a_recipe_evaluation_registers_and_names_its_run() -> None:
    transport = _RegisteringTransport()
    with _client(transport) as client:
        report = client.evaluate(_MODEL, benchmark="draco", limit=1)

    ((benchmark, case_count, registered),) = transport.opened
    assert (benchmark, case_count) == ("draco", 1)
    assert registered == tuple(transport.candidates)
    assert report.run_id == RUN_ID


class _RegisteringReplayTransport(_ReplayTransport):
    def __init__(self) -> None:
        super().__init__()
        self.opened: list[tuple[Any, tuple[Any, ...]]] = []

    def register_run(self, evaluation: Any, candidates: tuple[Any, ...], **options: Any) -> str:
        assert self.candidate is None, "registered before the Candidate ran"
        self.opened.append((evaluation, candidates))
        return RUN_ID


def test_a_raw_url4_evaluation_registers() -> None:
    transport = _RegisteringReplayTransport()
    with _client(transport) as client:
        report = client.evaluate(REPLAY_URL4)

    # A Run with no benchmark, of its one Candidate (E5 P2 spec D1).
    ((evaluation, registered),) = transport.opened
    assert (evaluation, len(registered)) == (None, 1)
    assert report.run_id == RUN_ID


class _AsyncRegisteringTransport(_AsyncFakeTransport):
    def __init__(self) -> None:
        super().__init__()
        self.opened: list[str] = []

    async def register_run(
        self, evaluation: Any, candidates: tuple[Any, ...], **options: Any
    ) -> str:
        self.opened.append(evaluation.benchmark.id)
        return RUN_ID


@pytest.mark.asyncio
async def test_an_async_recipe_evaluation_registers() -> None:
    transport = _AsyncRegisteringTransport()
    client = sf.AsyncClient(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_draco_engine),
        run_transport=transport,
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


# --- an abort of a one-Candidate evaluate (spec R8) ----------------------------------------


# --- abort order, a failed save and a partial report ---------------------------------------


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


# --- the real transport against a stub Engine that drives the Run (E5 P2) -----------------


def _stub_client(url: str, **options: Any) -> sf.Client:
    return sf.Client(engine_url=url, http_transport=httpx.MockTransport(_draco_engine), **options)


_PAIR = [_MODEL, sf.Model("anthropic/claude-haiku-4-5", name="sonnet")]


def test_a_registered_run_binds_every_start() -> None:
    from _run_engine import ended, run_engine, settled
    from test_evaluation_outcome import valid_body

    body = valid_body().encode()
    script = [[settled(0, body), settled(1, body), ended()]]
    with run_engine(script, {0: body, 1: body}) as engine, _stub_client(engine.url) as client:
        report = client.evaluate(_PAIR, benchmark="draco", limit=1, progress=False)

    (sent,) = engine.state.registered
    assert [start["name"] for start in sent["candidates"]] == ["haiku", "sonnet"]
    assert all(start["url4"] for start in sent["candidates"])
    assert report.run_id is not None


def test_a_client_key_is_sent_without_a_result_store() -> None:
    import re

    from _run_engine import ended, run_engine, settled
    from test_evaluation_outcome import valid_body

    body = valid_body().encode()
    with run_engine([[settled(0, body), ended()]], {0: body}) as engine:
        with _stub_client(engine.url, save_results=False) as client:
            client.evaluate(_MODEL, benchmark="draco", limit=1, progress=False)

    (sent,) = engine.state.registered
    assert re.fullmatch(r"[0-9a-f]{32}", sent["client_key"])


@pytest.mark.parametrize(("status", "code"), [(404, "runs_off"), (404, None), (422, None)])
def test_an_unregistered_run_starts_as_before_with_one_notice(
    status: int, code: str | None
) -> None:
    from _run_engine import run_engine

    with run_engine([], {}, refuse_create=(status, code)) as engine:
        with _stub_client(engine.url) as client, pytest.raises(sf.ScreamingFaceError) as raised:
            client.evaluate(_MODEL, benchmark="draco", limit=1, progress=False)

    assert raised.value.code == (code or "engine_upgrade_required")
    assert engine.state.followed == []


def test_an_interrupted_run_cancels_its_run() -> None:
    from _run_engine import RUN_ID, event, run_engine

    def interrupt(_event: sf.Event) -> None:
        raise KeyboardInterrupt

    with run_engine([[event(0, 1), "hold"]], {}) as engine, _stub_client(engine.url) as client:
        with pytest.raises(KeyboardInterrupt):
            client.evaluate(_MODEL, benchmark="draco", limit=1, progress=False, on_event=interrupt)

    assert engine.state.deleted == [f"/runs/{RUN_ID}"]


def test_a_failed_cancel_changes_nothing_else(monkeypatch: pytest.MonkeyPatch) -> None:
    """A cancel the Engine could not take is noted on the interruption the user sees, which is
    still the one raised (spec R8)."""
    from _run_engine import event, run_engine

    from screamingface._engine import run_client

    def refused(*_args: object) -> None:
        raise sf.EngineUnavailableError("down", engine_url="https://engine.example")

    monkeypatch.setattr(run_client.runs, "cancel_sync", refused)

    def interrupt(_event: sf.Event) -> None:
        raise KeyboardInterrupt

    with run_engine([[event(0, 1), "hold"]], {}) as engine, _stub_client(engine.url) as client:
        with pytest.raises(KeyboardInterrupt) as raised:
            client.evaluate(_MODEL, benchmark="draco", limit=1, progress=False, on_event=interrupt)

    assert any("also failed" in note for note in getattr(raised.value, "__notes__", []))


def test_the_manifest_is_keyed_by_the_run(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from _run_engine import RUN_ID, ended, run_engine, settled
    from test_evaluation_outcome import valid_body

    monkeypatch.setenv("SCREAMINGFACE_RESULTS_DIR", str(tmp_path))
    body = valid_body().encode()
    with run_engine([[settled(0, body), ended()]], {0: body}) as engine:
        with _stub_client(engine.url) as client:
            client.evaluate(_MODEL, benchmark="draco", limit=1, progress=False)

    assert [path.stem for path in (tmp_path / "evaluations").glob("*.json")] == [RUN_ID]


def test_a_failed_result_save_forgets_the_run_bindings(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A result that could not be saved fails its Candidate; the Run is not canceled."""
    from _run_engine import ended, run_engine, settled
    from test_evaluation_outcome import valid_body

    from screamingface._engine import transport as transport_module

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise ExecutionError("disk full", code="result_storage_failed")

    monkeypatch.setenv("SCREAMINGFACE_RESULTS_DIR", str(tmp_path))
    monkeypatch.setattr(transport_module, "download_sync", refuse)
    body = valid_body().encode()
    with run_engine([[settled(0, body), ended()]], {0: body}) as engine:
        with _stub_client(engine.url) as client, pytest.raises(ExecutionError) as raised:
            client.evaluate(_MODEL, benchmark="draco", limit=1, progress=False)

    assert raised.value.code == "result_storage_failed"
    assert engine.state.deleted == []


@pytest.mark.asyncio
async def test_a_cancelled_async_run_cancels_its_run() -> None:
    import asyncio

    from _run_engine import RUN_ID, run_engine, state

    with run_engine([[state(0, "scheduled"), "hold"]], {}) as engine:
        client = sf.AsyncClient(
            engine_url=engine.url, http_transport=httpx.MockTransport(_draco_engine)
        )
        task = asyncio.create_task(
            client.evaluate(_MODEL, benchmark="draco", limit=1, progress=False)
        )
        assert await asyncio.to_thread(engine.state.holding.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await client.aclose()

    assert engine.state.deleted == [f"/runs/{RUN_ID}"]
