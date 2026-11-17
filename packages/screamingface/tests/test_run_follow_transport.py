"""The Client's transports on a Run the Engine drives, end to end (E5 P2 spec D1, D9a, D13,
D14; plan C1).

FEATURE: a detached Run (OME-1837). STORY: as a researcher, `evaluate` sends my evaluation once,
follows it on one stream, reads each result from the Run, and Ctrl-C cancels what I started.

INVARIANT (D1): the Client sends `POST /runs` once and starts no Candidate itself.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from _run_engine import RUN_ID, ended, event, run_engine, settled, state
from test_client_run import _engine as _catalog_engine
from test_evaluation_outcome import valid_body

import screamingface as sf

BODY = valid_body().encode()
NAMES = ("alpha", "beta")


@pytest.fixture(autouse=True)
def _results_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("SCREAMINGFACE_RESULTS_DIR", str(tmp_path / "results"))
    yield tmp_path / "results"


def _models() -> list[sf.Model]:
    return [sf.Model("provider/opus", name=name) for name in NAMES]


def _client(url: str, **options: Any) -> sf.Client:
    return sf.Client(engine_url=url, http_transport=httpx.MockTransport(_catalog_engine), **options)


def _script() -> list[list[str | int]]:
    return [
        [
            state(0, "pending"),
            state(1, "scheduled"),
            event(1, 1),
            settled(1, BODY),
            state(0, "scheduled"),
            event(0, 1),
            settled(0, BODY),
            ended(),
        ]
    ]


def test_an_evaluation_is_sent_once_followed_and_read_from_the_run() -> None:
    with run_engine(_script(), {0: BODY, 1: BODY}) as engine, _client(engine.url) as client:
        report = client.evaluate(_models(), benchmark="draco", progress=False)

    (sent,) = engine.state.registered
    assert [start["name"] for start in sent["candidates"]] == list(NAMES)
    assert all(start["url4"] for start in sent["candidates"])
    assert json.loads(sent["context"])["benchmark"]["id"] == "draco"
    assert sent["detach"] is False
    assert engine.state.followed == [f"/runs/{RUN_ID}/events"]
    assert sorted(engine.state.fetched) == [
        f"/runs/{RUN_ID}/candidates/0/result",
        f"/runs/{RUN_ID}/candidates/1/result",
    ]
    assert [candidate.name for candidate in report.candidates] == list(NAMES)
    assert report.run_id == RUN_ID
    assert engine.state.deleted == []


def test_a_saved_result_is_kept_under_the_run(_results_dir: Path) -> None:
    with run_engine(_script(), {0: BODY, 1: BODY}) as engine, _client(engine.url) as client:
        client.evaluate(_models(), benchmark="draco", progress=False)

    manifests = list((_results_dir / "evaluations").glob("*.json"))
    assert [path.stem for path in manifests] == [RUN_ID]
    saved = [json.loads(path.read_text()) for path in _results_dir.glob("*/run.json")]
    assert sorted(run["outcome"]["run_result"]["index"] for run in saved) == [0, 1]
    assert all(
        (path.parent / "result.json").read_bytes() == BODY
        for path in _results_dir.glob("*/run.json")
    )


def test_a_follow_that_drops_picks_up_and_shows_each_event_once() -> None:
    script = [
        [event(0, 1, "one"), event(1, 1, "one"), 1011],
        [
            event(0, 1, "one"),
            event(0, 2, "two"),
            settled(0, BODY),
            event(1, 1, "one"),
            settled(1, BODY),
            ended(),
        ],
    ]
    seen: list[tuple[str, int]] = []

    with run_engine(script, {0: BODY, 1: BODY}) as engine, _client(engine.url) as client:
        client.evaluate(
            _models(),
            benchmark="draco",
            progress=False,
            on_event=lambda e: seen.append((e.run_id, e.sequence)),
        )

    assert sorted(seen) == sorted(
        [(f"url4-cloud.{0:032x}", 1), (f"url4-cloud.{0:032x}", 2), (f"url4-cloud.{1:032x}", 1)]
    )
    assert len(engine.state.followed) == 2


def test_ctrl_c_while_following_cancels_the_run_once() -> None:
    def interrupt(event: sf.Event) -> None:
        raise KeyboardInterrupt

    with run_engine(_script(), {0: BODY, 1: BODY}) as engine, _client(engine.url) as client:
        with pytest.raises(KeyboardInterrupt):
            client.evaluate(_models(), benchmark="draco", progress=False, on_event=interrupt)

    assert engine.state.deleted == [f"/runs/{RUN_ID}"]


@pytest.mark.asyncio
async def test_the_async_client_follows_the_same_run() -> None:
    with run_engine(_script(), {0: BODY, 1: BODY}) as engine:
        async with sf.AsyncClient(
            engine_url=engine.url, http_transport=httpx.MockTransport(_catalog_engine)
        ) as client:
            report = await client.evaluate(_models(), benchmark="draco", progress=False)

    assert [candidate.name for candidate in report.candidates] == list(NAMES)
    assert engine.state.followed == [f"/runs/{RUN_ID}/events"]
    assert len(engine.state.fetched) == 2


# --- Review fixes: a download never stalls the follow; a bad index leaves the Run alone ----------


class _Auth:
    def __init__(self, *tokens: str) -> None:
        self._tokens = iter(tokens)

    def websocket_headers(self) -> dict[str, str]:
        return {}

    async def websocket_headers_async(self) -> dict[str, str]:
        return {"Cf-Access-Token": next(self._tokens)}


_PAIR_SCRIPT = [[settled(0, BODY), state(1, "running"), settled(1, BODY), ended()]]


def _pair() -> tuple[Any, ...]:
    from _isolation_engine import candidate

    return (candidate("alpha"), candidate("beta"))


def test_each_result_downloads_beside_the_follow_and_settles_on_its_thread() -> None:
    """E5 P2 spec D14, R10 (#1878 review): a settled Candidate's result downloads beside the
    follow, after it is marked ended and before its outcome is handed over; every sink call
    stays on the thread that follows."""
    from _run_engine import CollectingSink

    follower = threading.current_thread()
    calls: list[tuple[str, int]] = []
    sink_threads: list[bool] = []
    download_threads: list[bool] = []

    class _Sink(CollectingSink):
        def state(self, index: int, state: str) -> None:
            sink_threads.append(threading.current_thread() is follower)
            if state in ("succeeded", "failed"):
                calls.append(("ended", index))

        def settled(self, index: int, state: str, outcome: Any) -> None:
            sink_threads.append(threading.current_thread() is follower)
            calls.append(("settled", index))
            super().settled(index, state, outcome)

    def save(candidate: Any, outcome: Any) -> Any:
        download_threads.append(threading.current_thread() is follower)
        calls.append(("fetched", 0 if candidate.name == "alpha" else 1))
        return outcome

    sink = _Sink()
    _follow_pair(sink, save)

    assert all(sink_threads) and sink_threads
    assert download_threads == [False, False]
    for index in (0, 1):
        assert [c for c in calls if c[1] == index] == [
            ("ended", index),
            ("fetched", index),
            ("settled", index),
        ]
    assert [c for c in calls if c[0] == "settled"] == [("settled", 0), ("settled", 1)]


def test_a_candidate_whose_download_ends_first_still_settles_after_the_one_before() -> None:
    """#1878 review: downloads run side by side, and the Candidates settle in the order the
    Engine settled them."""
    from _run_engine import CollectingSink

    beta_downloaded = threading.Event()
    alpha_saw_beta: list[bool] = []
    order: list[int] = []

    class _Sink(CollectingSink):
        def settled(self, index: int, state: str, outcome: Any) -> None:
            order.append(index)
            super().settled(index, state, outcome)

    def save(candidate: Any, outcome: Any) -> Any:
        if candidate.name == "alpha":
            alpha_saw_beta.append(beta_downloaded.wait(5))
        else:
            beta_downloaded.set()
        return outcome

    _follow_pair(_Sink(), save)

    assert alpha_saw_beta == [True]
    assert order == [0, 1]


def test_ctrl_c_while_a_result_downloads_does_not_wait_for_it() -> None:
    from _run_engine import CollectingSink

    release = threading.Event()

    class _Sink(CollectingSink):
        def state(self, index: int, state: str) -> None:
            if index == 1:
                raise KeyboardInterrupt

    def save(candidate: Any, outcome: Any) -> Any:
        release.wait(5)
        return outcome

    started = time.monotonic()
    try:
        with pytest.raises(KeyboardInterrupt):
            _follow_pair(_Sink(), save)
        assert time.monotonic() - started < 2
    finally:
        release.set()


@pytest.mark.asyncio
async def test_the_async_follow_signs_each_connect_with_the_current_sign_in() -> None:
    """A reconnect sends the sign-in the Client holds now, as the sync follow does."""
    from _run_engine import AsyncCollectingSink

    from screamingface._engine.run_client import AsyncRunClient, FollowTimings

    script = [[state(0, "running"), 1012], [settled(0, BODY), ended()]]
    with run_engine(script, {}) as engine:
        async with httpx.AsyncClient(base_url=engine.url) as http:
            auth = cast(Any, _Auth("first", "second"))
            runs = AsyncRunClient(http, engine.url, auth, None, FollowTimings(5.0, 0.0))
            await runs.follow(RUN_ID, _pair()[:1], AsyncCollectingSink(), _kept)

    sent = [
        next(value for key, value in headers.items() if key.casefold() == "cf-access-token")
        for headers in engine.state.follow_headers
    ]
    assert sent == ["first", "second"]


async def _kept(candidate: Any, outcome: Any) -> Any:
    return outcome


@pytest.mark.parametrize(
    "frame",
    [
        settled(5, BODY),
        state(2, "running"),
        json.dumps({"type": ["candidate.state"], "index": 0}),
    ],
    ids=["settled-past-the-end", "state-past-the-end", "type-not-a-string"],
)
def test_a_frame_the_run_cannot_have_is_a_contract_error_and_cancels_nothing(frame: str) -> None:
    with run_engine([[frame, ended()]], {}) as engine, _client(engine.url) as client:
        with pytest.raises(sf.ExecutionError) as raised:
            client.evaluate(_models(), benchmark="draco", progress=False)

    assert raised.value.code == "engine_contract_error"
    assert engine.state.deleted == []


class _SinkBug(Exception):
    pass


def _follow_pair(sink: Any, save: Any) -> None:
    from screamingface._engine.run_client import FollowTimings, RunClient

    with run_engine(_PAIR_SCRIPT, {}) as engine, httpx.Client(base_url=engine.url) as http:
        runs = RunClient(http, engine.url, cast(Any, _Auth()), None, FollowTimings(5.0, 0.0))
        runs.follow(RUN_ID, _pair(), sink, save)


async def _afollow_pair(sink: Any, save: Any) -> None:
    from screamingface._engine.run_client import AsyncRunClient, FollowTimings

    with run_engine(_PAIR_SCRIPT, {}) as engine:
        async with httpx.AsyncClient(base_url=engine.url) as http:
            auth = cast(Any, _Auth("one"))
            runs = AsyncRunClient(http, engine.url, auth, None, FollowTimings(5.0, 0.0))
            await runs.follow(RUN_ID, _pair(), sink, save)


def test_a_download_that_fails_is_that_candidates_failure() -> None:
    from _run_engine import CollectingSink

    def save(candidate: Any, outcome: Any) -> Any:
        if candidate.name == "alpha":
            raise sf.ExecutionError("result gone", code="result_expired")
        return outcome

    sink = CollectingSink()
    _follow_pair(sink, save)

    assert isinstance(sink.outcomes[0], sf.ExecutionError)
    assert sink.outcomes[0].code == "result_expired"
    assert not isinstance(sink.outcomes[1], Exception)


def test_what_a_settled_candidates_sink_call_raises_ends_the_follow() -> None:
    """A downloaded Candidate is handed to the sink beside the follow; what that raises (the
    caller's callback) still ends the follow, as it did when the follow handed it over."""
    from _run_engine import CollectingSink

    class _Sink(CollectingSink):
        def settled(self, index: int, state: str, outcome: Any) -> None:
            raise _SinkBug("the notebook cell's handler failed")

    with pytest.raises(_SinkBug):
        _follow_pair(_Sink(), lambda candidate, outcome: outcome)


@pytest.mark.asyncio
async def test_an_async_download_that_fails_is_that_candidates_failure() -> None:
    from _run_engine import AsyncCollectingSink

    async def save(candidate: Any, outcome: Any) -> Any:
        if candidate.name == "alpha":
            raise sf.ExecutionError("result gone", code="result_expired")
        return outcome

    sink = AsyncCollectingSink()
    await _afollow_pair(sink, save)

    assert isinstance(sink.outcomes[0], sf.ExecutionError)
    assert not isinstance(sink.outcomes[1], Exception)


@pytest.mark.asyncio
async def test_what_an_async_settled_candidates_sink_call_raises_ends_the_follow() -> None:
    from _run_engine import AsyncCollectingSink

    class _Sink(AsyncCollectingSink):
        async def settled(self, index: int, state: str, outcome: Any) -> None:
            raise _SinkBug("the notebook cell's handler failed")

    with pytest.raises(_SinkBug):
        await _afollow_pair(_Sink(), _kept)


# --- review round 3 ------------------------------------------------------------------------


_FLOOD = 500


def _queues_kept(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """Each follow socket's `max_queue`, as the Client opens it."""
    from screamingface._engine import run_client

    queues: list[object] = []
    real_sync, real_async = run_client.sync_ws.connect, run_client.async_ws.connect

    def sync_connect(*args: Any, **kwargs: Any) -> Any:
        queues.append(kwargs.get("max_queue", "default"))
        return real_sync(*args, **kwargs)

    def async_connect(*args: Any, **kwargs: Any) -> Any:
        queues.append(kwargs.get("max_queue", "default"))
        return real_async(*args, **kwargs)

    monkeypatch.setattr(run_client.sync_ws, "connect", sync_connect)
    monkeypatch.setattr(run_client.async_ws, "connect", async_connect)
    return queues


class _Flood:
    """An Engine that floods the stream while Candidate 0's result download is held open, and
    checks, meanwhile, that every frame reaches the sink and that the socket answers a ping."""

    def __init__(self) -> None:
        self.downloading, self.release = threading.Event(), threading.Event()
        self.all_seen = threading.Event()
        self.checks: dict[str, bool] = {}

    def engine(self, socket: Any) -> None:
        socket.send(settled(0, BODY))
        self.downloading.wait(5)
        for sequence in range(1, _FLOOD + 1):
            socket.send(event(1, sequence))
        self.checks["pong"] = socket.ping().wait(5)
        self.checks["frames"] = self.all_seen.wait(5)
        self.release.set()
        socket.send(settled(1, BODY))
        socket.send(ended())

    def save(self, candidate: Any, outcome: Any) -> Any:
        if candidate.name == "alpha":
            self.downloading.set()
            # WHY longer than the Engine's checks: the old inline fetch would free the frame
            # loop in time to pass them.
            self.release.wait(10)
        return outcome

    def seen(self, events: int) -> None:
        if events == _FLOOD:
            self.all_seen.set()


class _AsyncFlood:
    """The async twin of ``_Flood``."""

    def __init__(self) -> None:
        self.downloading, self.release = asyncio.Event(), asyncio.Event()
        self.all_seen = asyncio.Event()
        self.checks: dict[str, bool] = {}

    async def engine(self, socket: Any) -> None:
        await socket.send(settled(0, BODY))
        await _within(self.downloading.wait(), 5)
        for sequence in range(1, _FLOOD + 1):
            await socket.send(event(1, sequence))
        self.checks["pong"] = await _within(await socket.ping(), 5)
        self.checks["frames"] = await _within(self.all_seen.wait(), 5)
        self.release.set()
        await socket.send(settled(1, BODY))
        await socket.send(ended())

    async def save(self, candidate: Any, outcome: Any) -> Any:
        if candidate.name == "alpha":
            self.downloading.set()
            await _within(self.release.wait(), 10)  # longer than the checks, as in ``_Flood``
        return outcome

    def seen(self, events: int) -> None:
        if events == _FLOOD:
            self.all_seen.set()


async def _within(waited: Any, timeout_s: float) -> bool:
    try:
        await asyncio.wait_for(waited, timeout_s)
    except TimeoutError:
        return False
    return True


def test_frames_keep_flowing_and_keepalives_answered_while_a_result_downloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#1878 review, spec R10: while one result's download is held open, the Engine floods
    the stream. Every frame reaches the sink before the download ends, so none piles up in
    the socket's bounded queue, and the socket still answers a ping."""
    from _run_engine import CollectingSink
    from websockets.sync.server import serve

    from screamingface._engine.run_client import FollowTimings, RunClient

    flood = _Flood()

    class _Sink(CollectingSink):
        def event(self, index: int, event: Any) -> None:
            super().event(index, event)
            flood.seen(len(self.events))

    queues = _queues_kept(monkeypatch)
    sink = _Sink()
    with serve(flood.engine, "127.0.0.1", 0) as server:
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{server.socket.getsockname()[1]}"
        with httpx.Client(base_url=url) as http:
            runs = RunClient(http, url, cast(Any, _Auth()), None, FollowTimings(5.0, 0.0))
            runs.follow(RUN_ID, _pair(), sink, flood.save)
        server.shutdown()

    assert flood.checks == {"pong": True, "frames": True}
    assert None not in queues
    assert sorted(sink.outcomes) == [0, 1]


@pytest.mark.asyncio
async def test_async_frames_keep_flowing_and_keepalives_answered_while_a_result_downloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from _run_engine import AsyncCollectingSink
    from websockets.asyncio.server import serve

    from screamingface._engine.run_client import AsyncRunClient, FollowTimings

    flood = _AsyncFlood()

    class _Sink(AsyncCollectingSink):
        async def event(self, index: int, event: Any) -> None:
            await super().event(index, event)
            flood.seen(len(self.events))

    queues = _queues_kept(monkeypatch)
    sink = _Sink()
    async with serve(flood.engine, "127.0.0.1", 0) as server:
        url = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"
        async with httpx.AsyncClient(base_url=url) as http:
            auth = cast(Any, _Auth("one"))
            runs = AsyncRunClient(http, url, auth, None, FollowTimings(5.0, 0.0))
            await runs.follow(RUN_ID, _pair(), sink, flood.save)

    assert flood.checks == {"pong": True, "frames": True}
    assert None not in queues
    assert sorted(sink.outcomes) == [0, 1]


@pytest.mark.parametrize("refusal", [ValueError("blank provider"), TypeError("bad field")])
def test_an_event_the_event_types_refuse_is_dropped_not_raised(
    monkeypatch: pytest.MonkeyPatch, refusal: Exception
) -> None:
    """Events are for display: one the public event types refuse (a whitespace-only provider
    name, a negative saving) is dropped, never raised, since a raise ends the follow and the
    runner reads anything but a ScreamingFaceError as an interruption that cancels the Run."""
    from screamingface._engine import run_follow

    def refused(payload: Any) -> Any:
        raise refusal

    monkeypatch.setattr(run_follow, "display_event", refused)

    assert run_follow._Frames().accept(event(0, 1)) is None


def test_a_result_fetch_that_would_need_a_sign_in_ends_the_follow_with_how_to_resume() -> None:
    """Spec D15: the follow never starts a sign-in; it ends with `login_expired`, and the Run
    goes on."""
    from _run_engine import CollectingSink

    from screamingface._core.wire import LOGIN_NOT_STARTED
    from screamingface.errors import AuthenticationError

    def save(candidate: Any, outcome: Any) -> Any:
        raise AuthenticationError("Access wants a sign-in", code=LOGIN_NOT_STARTED)

    with pytest.raises(AuthenticationError) as raised:
        _follow_pair(CollectingSink(), save)

    assert raised.value.code == "login_expired"
    assert "sf.runs.get" in (raised.value.hint or "")


def test_the_transport_fetches_a_followed_runs_results_without_a_sign_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logins: list[bool] = []
    with run_engine(_script(), {0: BODY, 1: BODY}) as engine, _client(engine.url) as client:
        transport: Any = client._transport
        real = transport._save_result

        def spy(candidate: Any, outcome: Any, *, login: bool = True) -> Any:
            logins.append(login)
            return real(candidate, outcome, login=login)

        monkeypatch.setattr(transport, "_save_result", spy)
        client.evaluate(_models(), benchmark="draco", progress=False)

    assert logins == [False, False]


@pytest.mark.parametrize("shown", [False, True], ids=["nothing-shown", "on-event"])
def test_an_attached_follow_asks_for_events_only_when_something_shows_them(shown: bool) -> None:
    """With no progress output and no `on_event`, nothing reads a Candidate's events, so the
    follow asks the Run's stream to leave them out (`?events=false`)."""
    seen: list[object] = []
    options: dict[str, Any] = {"on_event": seen.append} if shown else {}
    with run_engine(_script(), {0: BODY, 1: BODY}) as engine, _client(engine.url) as client:
        client.evaluate(_models(), benchmark="draco", progress=False, **options)

    assert engine.state.follow_queries == ["" if shown else "events=false"]


def test_a_candidate_settled_in_a_state_this_client_does_not_know_says_to_upgrade() -> None:
    """#1878 review: a newer Engine's end state failed the Candidate with a bare ValueError: no
    code and no hint, even when it succeeded there."""
    script = [[state(0, "scheduled"), settled(0, BODY, state="archived"), ended()]]
    with run_engine(script, {0: BODY}) as engine, _client(engine.url) as client:
        with pytest.raises(sf.ExecutionError) as raised:
            client.evaluate(
                [sf.Model("provider/opus", name="alpha")], benchmark="draco", progress=False
            )

    assert raised.value.code == "engine_contract_error"
    assert "archived" in str(raised.value) and "Upgrade" in (raised.value.hint or "")


def _without_record(frame: str) -> str:
    value = json.loads(frame)
    value["record"] = None
    return json.dumps(value)


_LATE_SCRIPT = [[settled(0, BODY), _without_record(settled(1, BODY)), ended()]]


def test_a_candidate_settled_without_its_record_is_read_again_once_the_run_ends() -> None:
    """#1878 review: the Engine sends a succeeded Candidate's settled frame without its record
    past its outcome grace, and may fill the record after."""
    with run_engine(_LATE_SCRIPT, {0: BODY, 1: BODY}) as engine, _client(engine.url) as client:
        engine.state.settled_by_index[1] = json.loads(settled(1, BODY))
        report = client.evaluate(_models(), benchmark="draco", progress=False)

    assert [candidate.name for candidate in report.candidates] == list(NAMES)
    assert f"/runs/{RUN_ID}" in engine.state.fetched


@pytest.mark.asyncio
async def test_an_async_candidate_settled_without_its_record_is_read_again() -> None:
    with run_engine(_LATE_SCRIPT, {0: BODY, 1: BODY}) as engine:
        engine.state.settled_by_index[1] = json.loads(settled(1, BODY))
        async with sf.AsyncClient(
            engine_url=engine.url, http_transport=httpx.MockTransport(_catalog_engine)
        ) as client:
            report = await client.evaluate(_models(), benchmark="draco", progress=False)

    assert [candidate.name for candidate in report.candidates] == list(NAMES)


def test_a_record_the_engine_never_filled_reads_as_the_result_lost() -> None:
    with run_engine(_LATE_SCRIPT, {0: BODY, 1: BODY}) as engine, _client(engine.url) as client:
        with pytest.raises(sf.ExecutionError) as raised:
            client.evaluate(_models(), benchmark="draco", progress=False)

    assert "run_result_lost" in str(raised.value.details)
