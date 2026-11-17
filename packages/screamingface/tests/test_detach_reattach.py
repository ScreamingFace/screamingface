"""Detach a Run, and pick it up again from anywhere (E5 P2 spec D11, D14, §4.6; plan C2).

FEATURE: a detached Run (OME-1837). STORY: as a researcher, I start an evaluation with
`detach=True` and close my notebook; later, from any machine, `sf.runs.get(run_id).wait()` gives
me the same Report I would have got had I stayed.

INVARIANT (D14): a Report rebuilt from the Engine (context, records, results) equals, field by
field, the Report an attached evaluation of the same Run returns.
"""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from _run_engine import RUN_ID, ended, event, one_candidate, run_engine, settled, state
from test_client_run import REPLAY_URL4
from test_client_run import _engine as _catalog_engine
from test_evaluation_outcome import valid_body

import screamingface as sf
from screamingface import runs
from screamingface.errors import ExecutionError

BODY = valid_body().encode()
_MODELS = [sf.Model("provider/opus", name="left"), sf.Model("provider/opus", name="right")]
_SCRIPT = [[state(0, "scheduled"), event(0, 1), settled(0, BODY), settled(1, BODY), ended()]]
_RESULTS = {0: BODY, 1: BODY}


def _routed(engine_url: str) -> httpx.MockTransport:
    """The catalog fixture, with `/runs` reads forwarded to the stub Engine that holds the Run."""

    def handle(request: httpx.Request) -> httpx.Response:
        if not request.url.path.startswith("/runs"):
            return _catalog_engine(request)
        answer = httpx.request(
            request.method,
            engine_url + request.url.raw_path.decode(),
            content=request.content,
            headers={"content-type": request.headers.get("content-type", "application/json")},
        )
        return httpx.Response(
            answer.status_code,
            headers={"content-type": answer.headers.get("content-type", "application/json")},
            content=answer.content,
        )

    return httpx.MockTransport(handle)


def _client(url: str) -> sf.Client:
    return sf.Client(engine_url=url, http_transport=_routed(url))


@pytest.fixture
def results_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "first-machine"
    monkeypatch.setenv("SCREAMINGFACE_RESULTS_DIR", str(directory))
    return directory


def _another_machine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty local result store: nothing of the Run is on this machine."""
    monkeypatch.setenv("SCREAMINGFACE_RESULTS_DIR", str(tmp_path / "second-machine"))


def test_detach_returns_the_run_at_once_and_follows_nothing(results_dir: Path) -> None:
    with run_engine(_SCRIPT, _RESULTS) as engine, _client(engine.url) as client:
        run = client.evaluate(
            _MODELS, benchmark="draco", progress=False, detach=True, deadline=timedelta(hours=2)
        )

    assert isinstance(run, runs.Run)
    assert run.id == RUN_ID
    (sent,) = engine.state.registered
    assert (sent["detach"], sent["deadline_s"]) == (True, 7200)
    assert engine.state.followed == []


def test_detach_without_a_deadline_takes_the_engines_default(results_dir: Path) -> None:
    with run_engine(_SCRIPT, _RESULTS) as engine, _client(engine.url) as client:
        client.evaluate(_MODELS, benchmark="draco", progress=False, detach=True)

    assert engine.state.registered[0]["deadline_s"] is None


@pytest.mark.parametrize(
    "deadline", [timedelta(hours=1), timedelta(0), timedelta(seconds=-5), 3600]
)
def test_a_deadline_needs_detach_and_a_positive_timedelta(results_dir: Path, deadline: Any) -> None:
    detach = deadline != timedelta(hours=1)
    with run_engine(_SCRIPT, _RESULTS) as engine, _client(engine.url) as client:
        with pytest.raises((ValueError, TypeError)):
            client.evaluate(
                _MODELS, benchmark="draco", progress=False, detach=detach, deadline=deadline
            )

    assert engine.state.registered == []


def test_wait_follows_the_run_and_returns_the_report_an_attached_run_gives(
    results_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with run_engine(_SCRIPT, _RESULTS) as engine, _client(engine.url) as client:
        attached = client.evaluate(_MODELS, benchmark="draco", progress=False)
    with run_engine(_SCRIPT, _RESULTS) as engine:
        engine.state.run_state = "running"
        with _client(engine.url) as client:
            run_id = client.evaluate(_MODELS, benchmark="draco", progress=False, detach=True).id
        _another_machine(tmp_path, monkeypatch)
        with _client(engine.url) as elsewhere:
            run = runs._run(runs._wire.get_sync(elsewhere._http_request, run_id), elsewhere)
            report = run.wait()

    assert engine.state.followed == [f"/runs/{RUN_ID}/events"]
    assert report.to_json() == attached.to_json()


def test_report_on_another_machine_is_built_from_the_engine_and_kept(
    results_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with run_engine(_SCRIPT, _RESULTS) as engine:
        with _client(engine.url) as client:
            attached = client.evaluate(_MODELS, benchmark="draco", progress=False)
        _another_machine(tmp_path, monkeypatch)
        with _client(engine.url) as elsewhere:
            run = runs._run(runs._wire.get_sync(elsewhere._http_request, RUN_ID), elsewhere)
            first = run.report()
            fetched = list(engine.state.fetched)
            again = run.report()

    assert first.to_json() == attached.to_json()
    assert again.to_json() == attached.to_json()
    # The second read came from this machine's store: no result was fetched again.
    results = [path for path in engine.state.fetched if path.endswith("/result")]
    assert results == [path for path in fetched if path.endswith("/result")]


def test_a_run_still_going_has_no_report_yet(results_dir: Path) -> None:
    with run_engine(_SCRIPT, _RESULTS) as engine, _client(engine.url) as client:
        engine.state.run_state = "running"
        run = client.evaluate(_MODELS, benchmark="draco", progress=False, detach=True)
        with pytest.raises(ExecutionError) as raised:
            run.report()

    assert raised.value.code == "run_not_finished"


def test_a_context_that_does_not_match_the_runs_checksum_is_refused(
    results_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with run_engine(_SCRIPT, _RESULTS) as engine, _client(engine.url) as client:
        run = client.evaluate(_MODELS, benchmark="draco", progress=False, detach=True)
        _another_machine(tmp_path, monkeypatch)
        engine.state.served_context = '{"schema": "replaced"}'
        with pytest.raises(ExecutionError) as raised:
            run.report()

    assert raised.value.code == "context_mismatch"


def test_a_failed_candidate_reattaches_as_a_partial_report(
    results_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    error = {"code": "provider_error", "message": "upstream down", "permanent": False}
    script = [[settled(0, BODY), settled(1, b"", state="failed", error=error), ended("partial")]]
    with run_engine(script, {0: BODY}) as engine, _client(engine.url) as client:
        run = client.evaluate(_MODELS, benchmark="draco", progress=False, detach=True)
        _another_machine(tmp_path, monkeypatch)
        with pytest.raises(ExecutionError) as raised:
            run.report()

    assert raised.value.code == "candidates_failed"
    assert raised.value.details == {"failed": {"right": "provider_error"}}
    assert raised.value.partial_report is not None
    assert raised.value.partial_report.run_id == RUN_ID


def test_progress_and_refresh_read_the_summary(results_dir: Path) -> None:
    with run_engine(_SCRIPT, _RESULTS) as engine, _client(engine.url) as client:
        run = client.evaluate(_MODELS, benchmark="draco", progress=False, detach=True)
        progress = run.progress()

    assert (progress.done, progress.total) == (2, 2)
    reads = [path for path in engine.state.fetched if path.startswith(f"/runs/{RUN_ID}")]
    assert reads and all("view=summary" in path for path in reads)


def test_a_raw_url4_evaluation_detaches_too(results_dir: Path) -> None:
    with run_engine(_SCRIPT, _RESULTS) as engine, _client(engine.url) as client:
        run = client.evaluate(REPLAY_URL4, progress=False, detach=True)

    assert isinstance(run, runs.Run)
    assert engine.state.registered[0]["detach"] is True
    assert engine.state.followed == []


@pytest.mark.asyncio
async def test_the_async_client_detaches_too(results_dir: Path) -> None:
    with run_engine(_SCRIPT, _RESULTS) as engine:
        async with sf.AsyncClient(
            engine_url=engine.url, http_transport=_routed(engine.url)
        ) as client:
            run = await client.evaluate(_MODELS, benchmark="draco", progress=False, detach=True)

    assert isinstance(run, runs.Run)
    assert engine.state.followed == []


# --- Review fixes ---------------------------------------------------------------------------


def _run_reads(engine: Any) -> list[str]:
    return [path for path in engine.state.fetched if path.startswith(f"/runs/{RUN_ID}")]


def test_detach_returns_the_run_the_engine_registered_without_reading_it_again(
    results_dir: Path,
) -> None:
    """A read after the Run is registered could fail and lose its id while it spends; the
    registration's answer already is the Run."""
    with run_engine(_SCRIPT, _RESULTS) as engine, _client(engine.url) as client:
        run = client.evaluate(_MODELS, benchmark="draco", progress=False, detach=True)

    assert (run.id, run.state, run.detached) == (RUN_ID, "running", True)
    assert _run_reads(engine) == []


def test_sf_evaluate_refuses_a_deadline_on_a_replay_as_the_client_does(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from screamingface import _default_client

    class _NoReplay:
        def _evaluate_replay(self, **_options: object) -> None:
            raise AssertionError("the deadline is refused before the replay starts")

    monkeypatch.setattr(_default_client, "default_client", lambda: _NoReplay())

    # The overloads refuse this call too; at runtime the door must refuse it as the Client does.
    evaluate: Any = sf.evaluate
    with pytest.raises(ValueError, match="deadline needs detach=True"):
        evaluate(pinned_cache="fc_7d1e", deadline=timedelta(hours=1))


def test_a_raw_url4_runs_report_is_read_from_this_machine_after_the_first(
    results_dir: Path,
) -> None:
    script, results = one_candidate(BODY)
    with run_engine(script, results) as engine, _client(engine.url) as client:
        run = client.evaluate(REPLAY_URL4, progress=False, detach=True)
        first = run.report()
        again = run.report()

    assert again.to_json() == first.to_json()
    assert [path for path in engine.state.fetched if path.endswith("/result")] == [
        f"/runs/{RUN_ID}/candidates/0/result"
    ]


@pytest.mark.parametrize(("replayed", "raises"), [("fc_7d1e", False), (None, True)])
def test_a_replay_reopened_from_the_engine_must_have_replayed_from_its_frozen_copy(
    replayed: str | None, raises: bool
) -> None:
    """#1878 review round 5: the attached replay refuses a Run whose worker did not state the
    replay (OME-1307); the same Run's Report built from the Engine refuses it too."""
    from dataclasses import replace

    from test_evaluation_outcome import valid_outcome

    from screamingface._evaluation import reattach
    from screamingface._evaluation.model import _with_replay_frozen_copy
    from screamingface._evaluation.url4 import _candidate_from_url4

    candidate = _with_replay_frozen_copy(_candidate_from_url4(REPLAY_URL4), "fc_7d1e")
    outcome = replace(valid_outcome("replay"), capture_replay=replayed)

    if not raises:
        assert reattach._url4_report(((candidate, outcome),), RUN_ID).run_id == RUN_ID
        return
    with pytest.raises(ExecutionError) as raised:
        reattach._url4_report(((candidate, outcome),), RUN_ID)
    assert raised.value.code == "replay_unsupported"


@pytest.mark.parametrize("url4", [False, True], ids=["recipes", "raw-url4"])
def test_the_transport_keeps_no_binding_for_a_run_it_will_not_save_under(
    results_dir: Path, url4: bool
) -> None:
    """A detached or raw-URL4 Run's results are never kept under the Run's id here, so its
    Candidates are not remembered: a long-lived Client does not grow with every evaluate."""
    script, results = one_candidate(BODY)
    candidates: Any = REPLAY_URL4 if url4 else [_MODELS[0]]
    options: dict[str, Any] = {} if url4 else {"benchmark": "draco"}
    with run_engine(script + _SCRIPT, results) as engine, _client(engine.url) as client:
        client.evaluate(candidates, progress=False, detach=True, **options)
        client.evaluate(candidates, progress=False, **options)

        assert client._transport._report_ids == {}  # type: ignore[union-attr]


def test_a_run_this_machine_saved_only_part_of_is_built_from_the_engine(
    results_dir: Path,
) -> None:
    """An attached follow that ended early saved the first Candidate only; `report()` (and so
    `wait()`) then builds the whole Report from the Engine, not a partial one from here."""
    from screamingface._engine.run_client import FollowTimings

    with run_engine([[settled(0, BODY), 1011]], _RESULTS) as engine, _client(engine.url) as client:
        engine.state.settled_by_index[1] = json.loads(settled(1, BODY))
        client._transport._runs._timings = FollowTimings(0.0, 0.0)  # type: ignore[union-attr]
        with pytest.raises(ExecutionError, match="Lost the SF Engine WebSocket"):
            client.evaluate(_MODELS, benchmark="draco", progress=False)
        run = runs._run(runs._wire.get_sync(client._http_request, RUN_ID), client)
        report = run.report()

    assert [candidate.name for candidate in report.candidates] == ["left", "right"]


@pytest.mark.parametrize(
    "options",
    [{"on_event": print}, {"progress": True}],
    ids=["on_event", "progress"],
)
def test_a_detached_evaluation_refuses_what_only_a_follower_could_show(
    results_dir: Path, options: dict[str, Any]
) -> None:
    with run_engine(_SCRIPT, _RESULTS) as engine, _client(engine.url) as client:
        with pytest.raises(TypeError, match=r"run\.wait\(\)"):
            client.evaluate(_MODELS, benchmark="draco", detach=True, **options)

    assert engine.state.registered == []


def test_a_deadline_under_a_second_says_so(results_dir: Path) -> None:
    with run_engine(_SCRIPT, _RESULTS) as engine, _client(engine.url) as client:
        with pytest.raises(ValueError, match="at least 1 second"):
            client.evaluate(
                _MODELS,
                benchmark="draco",
                progress=False,
                detach=True,
                deadline=timedelta(milliseconds=500),
            )


def test_wait_follows_without_events(results_dir: Path) -> None:
    """`wait()` needs only when the Run ends, so it asks the Engine for no events."""
    with run_engine(_SCRIPT, _RESULTS) as engine, _client(engine.url) as client:
        engine.state.run_state = "running"
        run = client.evaluate(_MODELS, benchmark="draco", progress=False, detach=True)
        run.wait()

    assert engine.state.follow_queries == ["events=false"]


@pytest.mark.asyncio
async def test_a_run_is_waited_on_and_reported_without_blocking_the_event_loop(
    results_dir: Path,
) -> None:
    with run_engine(_SCRIPT, _RESULTS) as engine, _client(engine.url) as client:
        engine.state.run_state = "running"
        run = client.evaluate(_MODELS, benchmark="draco", progress=False, detach=True)
        waited = await run.wait_async()
        reported = await run.report_async()

    assert waited.to_json() == reported.to_json()
    assert [candidate.name for candidate in waited.candidates] == ["left", "right"]


def test_report_on_the_machine_that_followed_fetches_no_result_again(results_dir: Path) -> None:
    """E5 P2 spec D14: `report()` builds from the Engine's records, as the attached evaluation
    did, and reuses each result its follow saved here with the record's checksum."""
    with run_engine(_SCRIPT, _RESULTS) as engine, _client(engine.url) as client:
        attached = client.evaluate(_MODELS, benchmark="draco", progress=False)
        fetched = [path for path in engine.state.fetched if path.endswith("/result")]
        run = runs._run(runs._wire.get_sync(client._http_request, RUN_ID), client)
        report = run.report()

    assert report.to_json() == attached.to_json()
    assert [path for path in engine.state.fetched if path.endswith("/result")] == fetched
    assert len(fetched) == 2


def test_a_run_the_engine_no_longer_keeps_is_read_from_this_machine(
    results_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Retention deleted the Run from the Engine after this machine saved its Report."""
    from screamingface._engine import runs as wire

    with run_engine(_SCRIPT, _RESULTS) as engine, _client(engine.url) as client:
        attached = client.evaluate(_MODELS, benchmark="draco", progress=False)
        run = runs._run(runs._wire.get_sync(client._http_request, RUN_ID), client)

        def deleted(*args: Any, **kwargs: Any) -> Any:
            raise KeyError(RUN_ID)

        monkeypatch.setattr(wire, "get_sync", deleted)
        report = run.report()

    assert report.to_json() == attached.to_json()


# --- review round 3 ------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancelling_wait_async_ends_its_follow(
    results_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#1878 review round 3: `wait_async()` follows on the event loop, so cancelling it closes the
    socket, and no thread goes on following, and holding, the Run."""
    with run_engine([["hold"]], _RESULTS) as engine:
        engine.state.run_state = "running"
        with _client(engine.url) as client:
            run = client.evaluate(_MODELS, benchmark="draco", progress=False, detach=True)
            monkeypatch.setattr(client._transport, "wait_run", pytest.fail)
            task = asyncio.create_task(run.wait_async())
            assert await asyncio.to_thread(engine.state.holding.wait, 5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 5)

    assert engine.state.follow_queries == ["events=false"]


@pytest.mark.parametrize("code", ["context_not_found", "context_mismatch"])
def test_a_run_whose_context_is_lost_is_read_from_this_machine(
    results_dir: Path, monkeypatch: pytest.MonkeyPatch, code: str
) -> None:
    """#1878 review round 3: the Engine still has the Run but not its context, or one that no
    longer matches; this machine holds the whole Report, so `report()` reads it from here."""
    from screamingface._engine import runs as wire

    with run_engine(_SCRIPT, _RESULTS) as engine, _client(engine.url) as client:
        attached = client.evaluate(_MODELS, benchmark="draco", progress=False)
        run = runs._run(runs._wire.get_sync(client._http_request, RUN_ID), client)

        def lost(*args: Any, **kwargs: Any) -> Any:
            raise ExecutionError("the context is gone", code=code)

        monkeypatch.setattr(wire, "context_sync", lost)
        report = run.report()

    assert report.to_json() == attached.to_json()


def test_a_run_whose_context_is_lost_and_not_here_says_why(
    results_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from screamingface._engine import runs as wire

    with run_engine(_SCRIPT, _RESULTS) as engine:
        with _client(engine.url) as client:
            client.evaluate(_MODELS, benchmark="draco", progress=False)
        _another_machine(tmp_path, monkeypatch)
        with _client(engine.url) as elsewhere:
            run = runs._run(runs._wire.get_sync(elsewhere._http_request, RUN_ID), elsewhere)

            def lost(*args: Any, **kwargs: Any) -> Any:
                raise ExecutionError("the context is gone", code="context_not_found")

            monkeypatch.setattr(wire, "context_sync", lost)
            with pytest.raises(ExecutionError) as raised:
                run.report()

    assert raised.value.code == "context_not_found"


def test_wait_reads_the_run_once_before_following_and_once_after(
    results_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#1878 review round 3: `wait()` reads the Run's summary to know it is running, follows it
    to its end, then builds the Report from one full read; no second summary read."""
    reads: list[str] = []
    with run_engine(_SCRIPT, _RESULTS) as engine:
        engine.state.run_state = "running"
        routed = _routed(engine.url)

        def counted(request: httpx.Request) -> httpx.Response:
            if request.method == "GET" and request.url.path == f"/runs/{RUN_ID}":
                reads.append(request.url.params.get("view", "full"))
            return routed.handle_request(request)

        with sf.Client(engine_url=engine.url, http_transport=httpx.MockTransport(counted)) as c:
            run = c.evaluate(_MODELS, benchmark="draco", progress=False, detach=True)
            reads.clear()
            run.wait()

    assert reads == ["summary", "full"]


def test_a_result_the_follow_could_not_fetch_is_fetched_when_the_run_ends(
    results_dir: Path,
) -> None:
    """E5 P2 spec D14: a fetch that fails during the follow costs only that live score. The
    Candidate succeeded on the Engine, so the build at the Run's end fetches its result again
    instead of failing it."""
    with run_engine(_SCRIPT, _RESULTS) as engine, _client(engine.url) as client:
        engine.state.fail_fetches = 1
        report = client.evaluate(_MODELS, benchmark="draco", progress=False)

    assert [candidate.name for candidate in report.candidates] == ["left", "right"]
    assert len([path for path in engine.state.fetched if path.endswith("/result")]) == 3


def test_a_result_fetched_when_the_run_ends_is_saved_in_its_evaluation(
    results_dir: Path,
) -> None:
    """#1878 review round 5: the follow's failed fetch had already used the Candidate's place
    in its evaluation, so the save at the Run's end recorded it outside it, and the Report
    saved here no longer read whole."""
    with run_engine(_SCRIPT, _RESULTS) as engine, _client(engine.url) as client:
        engine.state.fail_fetches = 1
        client.evaluate(_MODELS, benchmark="draco", progress=False)

    saved = [json.loads(path.read_text()) for path in results_dir.glob("*/run.json")]
    assert [run["evaluation"]["id"] for run in saved] == [RUN_ID, RUN_ID]
    assert [(entry.id, entry.downloaded) for entry in sf.reports.list()] == [(RUN_ID, True)]


def test_report_on_the_machine_that_saved_it_whole_reads_it_without_building_it_again(
    results_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#1878 review round 4: a read writes nothing. The build marks the saved evaluation
    running while it works, so the Report saved here whole is read as it is, and its marker
    is never touched."""
    from screamingface._results import evaluation

    with run_engine(_SCRIPT, _RESULTS) as engine, _client(engine.url) as client:
        attached = client.evaluate(_MODELS, benchmark="draco", progress=False)
        run = runs._run(runs._wire.get_sync(client._http_request, RUN_ID), client)
        read_before = list(engine.state.fetched)

        def never(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("a Report saved here whole is not prepared again")

        monkeypatch.setattr(evaluation, "prepare", never)
        report = run.report()

    assert report.to_json() == attached.to_json()
    assert not [path for path in engine.state.fetched[len(read_before) :] if "/context" in path]


def test_a_run_saved_whole_here_is_still_not_finished_until_the_engine_ends_it(
    results_dir: Path,
) -> None:
    """#1878 review: this machine may hold every result before the Engine ends the Run."""
    with run_engine(_SCRIPT, _RESULTS) as engine, _client(engine.url) as client:
        client.evaluate(_MODELS, benchmark="draco", progress=False)
        engine.state.run_state = "running"
        run = runs._run(runs._wire.get_sync(client._http_request, RUN_ID, summary=True), client)
        with pytest.raises(ExecutionError) as raised:
            run.report()

    assert raised.value.code == "run_not_finished"
