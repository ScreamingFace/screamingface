"""`sf.runs`: list, reopen, wait on and cancel Runs (E5 P1 spec §4.4, D9, D11; plan C3).

FEATURE: first-class Runs (OME-1785). STORY: as a researcher, I open last week's evaluation from
another notebook with `sf.runs.get(run_id)`, wait for it, and open its report on the machine
that ran it.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from decimal import Decimal
from typing import Any, cast

import httpx
import pytest

import screamingface as sf
from screamingface import _default_client
from screamingface import runs as runs_module
from screamingface.errors import ExecutionError

RUN_ID = "run_" + "d" * 32
_Handler = Callable[[httpx.Request], httpx.Response]


def _candidate(name: str, state: str, cost: str | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "state": state,
        "attempt_id": None,
        "started_at": None,
        "finished_at": None,
        "cost_usd": cost,
        "error_code": "run_failed" if state == "failed" else None,
    }


def _record(state: str = "running", *candidates: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": RUN_ID,
        "state": state,
        "created_at": "2026-11-03T10:00:00Z",
        "finished_at": None if state == "running" else "2026-11-03T10:05:00Z",
        "benchmark": "gsm8k",
        "case_count": 3,
        "candidates": list(candidates) or [_candidate("alpha", "running")],
    }


def _problem(status: int, code: str | None = None) -> httpx.Response:
    body: dict[str, Any] = {"type": "about:blank", "title": "x", "status": status}
    if code is not None:
        body["code"] = code
    return httpx.Response(status, json=body, headers={"content-type": "application/problem+json"})


@pytest.fixture
def engine(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[_Handler], list[httpx.Request]]]:
    """Point the default Client at a fake Engine; returns the requests it received."""
    clients: list[sf.Client] = []

    def install(handler: _Handler) -> list[httpx.Request]:
        seen: list[httpx.Request] = []

        def respond(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return handler(request)

        client = sf.Client(
            engine_url="http://engine.test",
            scoreboard_url="http://scoreboard.test",
            http_transport=httpx.MockTransport(respond),
            save_results=False,
        )
        clients.append(client)
        monkeypatch.setattr(_default_client, "_client", client)
        return seen

    yield install
    for client in clients:
        client.close()


def test_get_reopens_a_run(engine: Callable[[_Handler], list[httpx.Request]]) -> None:
    record = _record(
        "partial",
        _candidate("alpha", "succeeded", "0.25"),
        _candidate("beta", "failed", "0.5"),
        _candidate("gamma", "lost"),
    )
    seen = engine(lambda _r: httpx.Response(200, json=record))

    run = sf.runs.get(RUN_ID)

    assert isinstance(run, sf.Run)
    assert (run.id, run.state, run.benchmark) == (RUN_ID, "partial", "gsm8k")
    assert run.candidates[1] == sf.CandidateRun(
        name="beta", state="failed", cost_usd=Decimal("0.5"), error_code="run_failed"
    )
    # Only the known costs: `gamma` was lost and its cost is unknown.
    assert run.cost_usd == Decimal("0.75")
    assert seen[0].url.path == f"/runs/{RUN_ID}"


def test_a_run_without_a_known_cost_has_none(
    engine: Callable[[_Handler], list[httpx.Request]],
) -> None:
    engine(lambda _r: httpx.Response(200, json=_record()))

    assert sf.runs.get(RUN_ID).cost_usd is None


def test_an_unknown_run_is_a_key_error(engine: Callable[[_Handler], list[httpx.Request]]) -> None:
    engine(lambda _r: _problem(404, "run_not_found"))

    with pytest.raises(KeyError):
        sf.runs.get(RUN_ID)


@pytest.mark.parametrize("call", ["get", "list"])
def test_an_engine_without_runs_says_so(
    engine: Callable[[_Handler], list[httpx.Request]], call: str
) -> None:
    engine(lambda _r: httpx.Response(404, text="Not Found"))

    with pytest.raises(ExecutionError) as caught:
        sf.runs.get(RUN_ID) if call == "get" else sf.runs.list()

    assert caught.value.code == "runs_unavailable"


def test_list_returns_runs_newest_first(engine: Callable[[_Handler], list[httpx.Request]]) -> None:
    seen = engine(
        lambda _r: httpx.Response(200, json={"runs": [_record("complete")], "next_cursor": None})
    )

    runs = sf.runs.list(state="complete", limit=5)

    assert [run.id for run in runs] == [RUN_ID]
    assert dict(seen[0].url.params) == {"state": "complete", "limit": "5"}


def test_list_refuses_a_naive_since(engine: Callable[[_Handler], list[httpx.Request]]) -> None:
    from datetime import datetime

    engine(lambda _r: httpx.Response(500))

    with pytest.raises(ValueError, match="timezone"):
        sf.runs.list(since=datetime(2026, 11, 1))


@pytest.mark.asyncio
async def test_async_twins(engine: Callable[[_Handler], list[httpx.Request]]) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/runs":
            return httpx.Response(200, json={"runs": [_record()], "next_cursor": None})
        return httpx.Response(200, json=_record())

    engine(respond)

    assert (await sf.runs.get_async(RUN_ID)).id == RUN_ID
    assert [run.id for run in await sf.runs.list_async()] == [RUN_ID]


# --- the Run's methods --------------------------------------------------------------------


def _sequence(*states: str) -> _Handler:
    answers = list(states)

    def respond(_request: httpx.Request) -> httpx.Response:
        state = answers.pop(0) if len(answers) > 1 else answers[0]
        candidate = _candidate("alpha", "running" if state == "running" else "succeeded", "0.1")
        return httpx.Response(200, json=_record(state, candidate))

    return respond


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    slept: list[float] = []
    clock = [0.0]

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(runs_module, "_sleep", sleep)
    monkeypatch.setattr(runs_module, "_monotonic", lambda: clock[0])
    return slept


@pytest.mark.parametrize("terminal", ["complete", "partial", "errored", "canceled", "interrupted"])
def test_wait_returns_on_every_terminal_state(
    engine: Callable[[_Handler], list[httpx.Request]], no_sleep: list[float], terminal: str
) -> None:
    engine(_sequence("running", "running", terminal))
    run = sf.runs.get(RUN_ID)

    finished = run.wait()

    assert finished.state == terminal
    assert len(no_sleep) == 2
    assert run.state == "running", "a Run is a frozen snapshot"


def test_wait_gives_up_at_its_timeout(
    engine: Callable[[_Handler], list[httpx.Request]], no_sleep: list[float]
) -> None:
    engine(_sequence("running"))

    with pytest.raises(TimeoutError, match=RUN_ID):
        sf.runs.get(RUN_ID).wait(timeout=30)

    assert sum(no_sleep) <= 30


def test_progress_counts_finished_candidates_and_spend(
    engine: Callable[[_Handler], list[httpx.Request]],
) -> None:
    record = _record(
        "running", _candidate("alpha", "succeeded", "0.2"), _candidate("beta", "running")
    )
    engine(lambda _r: httpx.Response(200, json=record))

    progress = sf.runs.get(RUN_ID).progress()

    assert progress == sf.RunProgress(done=1, total=2, cost_usd=Decimal("0.2"))


def test_cancel_cancels_the_run(engine: Callable[[_Handler], list[httpx.Request]]) -> None:
    seen = engine(
        lambda r: (
            httpx.Response(202) if r.method == "DELETE" else httpx.Response(200, json=_record())
        )
    )

    sf.runs.get(RUN_ID).cancel()

    assert (seen[-1].method, seen[-1].url.path) == ("DELETE", f"/runs/{RUN_ID}")


def test_report_reads_the_local_store(
    engine: Callable[[_Handler], list[httpx.Request]], monkeypatch: pytest.MonkeyPatch
) -> None:
    engine(_sequence("complete"))
    saved = object()
    monkeypatch.setattr(sf.reports, "get", lambda report_id: (report_id, saved))
    monkeypatch.setattr(runs_module, "with_run_id", lambda report, run_id: (report, run_id))

    # The local manifest is keyed by the Run's id (spec D8), and the report names its Run.
    assert sf.runs.get(RUN_ID).report() == ((RUN_ID, saved), RUN_ID)


def test_report_off_this_machine_names_the_run(
    engine: Callable[[_Handler], list[httpx.Request]], monkeypatch: pytest.MonkeyPatch
) -> None:
    engine(_sequence("complete"))

    def missing(report_id: str) -> None:
        raise KeyError(report_id)

    monkeypatch.setattr(sf.reports, "get", missing)

    with pytest.raises(ExecutionError, match=RUN_ID) as caught:
        sf.runs.get(RUN_ID).report()

    assert caught.value.code == "results_not_local"


def test_report_of_a_running_run_is_refused(
    engine: Callable[[_Handler], list[httpx.Request]], monkeypatch: pytest.MonkeyPatch
) -> None:
    engine(_sequence("running"))
    monkeypatch.setattr(sf.reports, "get", pytest.fail)

    with pytest.raises(ExecutionError) as caught:
        sf.runs.get(RUN_ID).report()

    assert caught.value.code == "run_not_finished"


def test_report_of_an_unfinished_evaluation_keeps_the_settlement_rule(
    engine: Callable[[_Handler], list[httpx.Request]], monkeypatch: pytest.MonkeyPatch
) -> None:
    engine(_sequence("partial"))
    failed = ExecutionError("some failed", code="candidates_failed")

    def incomplete(_report_id: str) -> None:
        raise failed

    monkeypatch.setattr(sf.reports, "get", incomplete)

    with pytest.raises(ExecutionError) as caught:
        sf.runs.get(RUN_ID).report()

    assert caught.value is failed


def test_report_reads_again_a_snapshot_taken_while_running(
    engine: Callable[[_Handler], list[httpx.Request]], monkeypatch: pytest.MonkeyPatch
) -> None:
    engine(_sequence("running", "complete"))
    run = sf.runs.get(RUN_ID)
    monkeypatch.setattr(sf.reports, "get", lambda report_id: report_id)
    monkeypatch.setattr(runs_module, "with_run_id", lambda report, _run_id: report)

    assert run.report() == RUN_ID


def test_report_of_a_raw_url4_run_reads_its_attempt(
    engine: Callable[[_Handler], list[httpx.Request]], monkeypatch: pytest.MonkeyPatch
) -> None:
    # WHY: a raw-URL4 or replay evaluation saves its one result under the attempt id.
    attempt = "t" * 64
    candidate = {**_candidate("alpha", "succeeded"), "attempt_id": attempt}
    engine(lambda _r: httpx.Response(200, json=_record("complete", candidate)))
    saved = object()

    def by_attempt(report_id: str) -> object:
        if report_id != attempt:
            raise KeyError(report_id)
        return saved

    monkeypatch.setattr(sf.reports, "get", by_attempt)
    monkeypatch.setattr(runs_module, "with_run_id", lambda report, _run_id: report)

    assert sf.runs.get(RUN_ID).report() is saved


def test_the_partial_report_of_a_failed_run_names_the_run(
    engine: Callable[[_Handler], list[httpx.Request]], monkeypatch: pytest.MonkeyPatch
) -> None:
    engine(_sequence("partial"))
    partial = object()
    failed = ExecutionError(
        "some failed", code="candidates_failed", partial_report=cast(Any, partial)
    )

    def incomplete(_report_id: str) -> None:
        raise failed

    monkeypatch.setattr(sf.reports, "get", incomplete)
    monkeypatch.setattr(runs_module, "with_run_id", lambda report, run_id: (report, run_id))

    with pytest.raises(ExecutionError) as caught:
        sf.runs.get(RUN_ID).report()

    assert caught.value.partial_report == (partial, RUN_ID)
