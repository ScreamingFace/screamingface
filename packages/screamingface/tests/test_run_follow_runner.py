"""`evaluate` on the follow path: the Engine drives the Run, the Client follows it (E5 P2 spec
D1, D13, D14; plan C1).

FEATURE: a detached Run (OME-1837). STORY: as a researcher, my evaluation reads the same as before:
results in the order I gave the Candidates, a failed Candidate named while its siblings finish,
and Ctrl-C stops what I started, though my notebook now starts nothing itself.

INVARIANT (D1): the Client sends the Run once and starts no Candidate; it follows one stream.
INVARIANT (D14): Ctrl-C, or an `on_event` that raises, cancels the Run once; a follow that ends
on its own (an expired sign-in, a connection it could not get back) leaves the Run to the Engine.
"""

from __future__ import annotations

import threading
from typing import Any, cast

import httpx
import pytest
from test_client_run import _engine as _catalog_engine
from test_evaluation_outcome import valid_outcome
from test_run_follow import _cloudevent

import screamingface as sf
from screamingface._engine.contract import display_event
from screamingface._engine.run_follow import login_expired
from screamingface.errors import AuthenticationError, ExecutionError

RUN_ID = "run_" + "e" * 32


def _event(sequence: int) -> sf.Event:
    event = display_event(_cloudevent(sequence))
    assert event is not None
    return event


class _Following:
    """A transport the Engine drives: ``script`` is what the Run's stream says, by name."""

    def __init__(self, *script: tuple[Any, ...]) -> None:
        self.script = script
        self.registered: tuple[str, ...] = ()
        self.canceled: list[str] = []
        self.threads: list[int] = []

    def register_run(self, evaluation, candidates, *, detach=False, deadline_s=None) -> str:
        self.registered = tuple(candidate.name for candidate in candidates)
        return RUN_ID

    def follow_run(self, run_id, candidates, sink) -> None:
        assert run_id == RUN_ID
        names = [candidate.name for candidate in candidates]
        for step in self.script:
            self.threads.append(threading.active_count())
            kind, name, *rest = step
            if kind == "raise":
                raise name
            index = names.index(name)
            if kind == "state":
                sink.state(index, rest[0])
            elif kind == "event":
                sink.event(index, _event(rest[0]))
            else:
                state, outcome = rest
                sink.settled(index, state, outcome)

    def cancel_run(self, run_id: str) -> None:
        self.canceled.append(run_id)

    def close(self) -> None:
        pass


class _AsyncFollowing:
    def __init__(self, *script: tuple[Any, ...]) -> None:
        self.script = script
        self.canceled: list[str] = []

    async def register_run(self, evaluation, candidates, *, detach=False, deadline_s=None) -> str:
        return RUN_ID

    async def follow_run(self, run_id, candidates, sink) -> None:
        names = [candidate.name for candidate in candidates]
        for kind, name, *rest in self.script:
            if kind == "raise":
                raise name
            index = names.index(name)
            if kind == "state":
                await sink.state(index, rest[0])
            elif kind == "event":
                await sink.event(index, _event(rest[0]))
            else:
                await sink.settled(index, rest[0], rest[1])

    async def cancel_run(self, run_id: str) -> None:
        self.canceled.append(run_id)

    async def close(self) -> None:
        pass


def _models(*names: str) -> list[sf.Model]:
    return [sf.Model("provider/opus", name=name) for name in names]


def _evaluate(transport: _Following, *names: str, **options: Any) -> sf.Report:
    with sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_catalog_engine),
        run_transport=cast(Any, transport),
    ) as client:
        return client.evaluate(_models(*names), benchmark="draco", progress=False, **options)


def _ok(name: str) -> tuple[Any, ...]:
    return ("settled", name, "succeeded", valid_outcome(name))


def test_the_run_is_sent_once_and_its_results_come_back_in_the_order_given() -> None:
    transport = _Following(_ok("b"), _ok("c"), _ok("a"))

    report = _evaluate(transport, "a", "b", "c")

    assert transport.registered == ("a", "b", "c")
    assert [candidate.name for candidate in report.candidates] == ["a", "b", "c"]
    assert report.run_id == RUN_ID
    assert transport.canceled == []


def test_a_failed_candidate_is_named_and_its_siblings_still_report() -> None:
    failed = ExecutionError("upstream down", code="provider_error")
    transport = _Following(("settled", "b", "failed", failed), _ok("a"))

    with pytest.raises(ExecutionError) as raised:
        _evaluate(transport, "a", "b")

    assert raised.value.code == "candidates_failed"
    assert cast(dict[str, Any], raised.value.details)["failed"] == {"b": "provider_error"}
    assert raised.value.partial_report is not None
    assert [c.name for c in raised.value.partial_report.candidates] == ["a"]
    assert transport.canceled == []


def test_a_lone_candidate_that_failed_raises_its_own_error() -> None:
    failed = ExecutionError("upstream down", code="provider_error")

    with pytest.raises(ExecutionError) as raised:
        _evaluate(_Following(("settled", "a", "failed", failed)), "a")

    assert raised.value.code == "provider_error"


def test_on_event_gets_every_event_in_order_for_each_candidate() -> None:
    seen: list[tuple[str, int]] = []
    transport = _Following(
        ("state", "a", "pending"),
        ("state", "a", "scheduled"),
        ("event", "a", 1),
        ("event", "b", 1),
        ("event", "a", 2),
        _ok("a"),
        ("event", "b", 2),
        _ok("b"),
    )

    _evaluate(transport, "a", "b", on_event=lambda e: seen.append((e.run_id, e.sequence)))

    assert [sequence for _, sequence in seen] == [1, 1, 2, 2]


def test_an_on_event_that_raises_cancels_the_run_once() -> None:
    transport = _Following(("event", "a", 1), _ok("a"), _ok("b"))

    def explode(event: sf.Event) -> None:
        raise RuntimeError("my callback")

    with pytest.raises(RuntimeError, match="my callback"):
        _evaluate(transport, "a", "b", on_event=explode)

    assert transport.canceled == [RUN_ID]


def test_ctrl_c_cancels_the_run_once() -> None:
    transport = _Following(_ok("a"), ("raise", KeyboardInterrupt()))

    with pytest.raises(KeyboardInterrupt):
        _evaluate(transport, "a", "b")

    assert transport.canceled == [RUN_ID]


def test_a_follow_that_ends_on_its_own_leaves_the_run_to_the_engine() -> None:
    transport = _Following(("raise", login_expired(RUN_ID, detached=False)))

    with pytest.raises(AuthenticationError) as raised:
        _evaluate(transport, "a", "b")

    assert raised.value.code == "login_expired"
    assert transport.canceled == []


def test_many_candidates_are_followed_without_a_thread_each() -> None:
    names = [f"m{i}" for i in range(64)]
    transport = _Following(*(_ok(name) for name in reversed(names)))
    before = threading.active_count()

    report = _evaluate(transport, *names)

    assert len(report.candidates) == 64
    assert max(transport.threads) <= before + 1


def _aevaluate(transport: _AsyncFollowing, *names: str, **options: Any):
    async def run() -> sf.Report:
        async with sf.AsyncClient(
            engine_url="https://engine.example",
            http_transport=httpx.MockTransport(_catalog_engine),
            run_transport=cast(Any, transport),
        ) as client:
            return await client.evaluate(
                _models(*names), benchmark="draco", progress=False, **options
            )

    return run()


@pytest.mark.asyncio
async def test_the_async_follow_path_reports_in_order() -> None:
    transport = _AsyncFollowing(_ok("b"), _ok("a"))

    report = await _aevaluate(transport, "a", "b")

    assert [candidate.name for candidate in report.candidates] == ["a", "b"]
    assert report.run_id == RUN_ID


@pytest.mark.asyncio
async def test_an_async_on_event_that_raises_cancels_the_run_once() -> None:
    transport = _AsyncFollowing(("event", "a", 1), _ok("a"), _ok("b"))

    async def explode(event: sf.Event) -> None:
        raise RuntimeError("my callback")

    with pytest.raises(RuntimeError, match="my callback"):
        await _aevaluate(transport, "a", "b", on_event=explode)

    assert transport.canceled == [RUN_ID]


class _FailsToPrepare(_Following):
    """Registers the Run, then cannot set up this machine's result store."""

    def prepare_results(self, evaluation, candidates):
        raise OSError("No space left on device")


class _AsyncFailsToPrepare(_AsyncFollowing):
    def prepare_results(self, evaluation, candidates):
        raise OSError("No space left on device")


def test_a_failure_between_registering_and_following_cancels_the_run() -> None:
    # INVARIANT (D14, review fix): the Engine starts the Candidates when the Run is registered,
    # so an evaluation that stops before it follows must not leave the Run spending.
    transport = _FailsToPrepare(_ok("a"))

    with pytest.raises(OSError, match="No space left"):
        _evaluate(transport, "a")

    assert transport.canceled == [RUN_ID]


@pytest.mark.asyncio
async def test_an_async_failure_between_registering_and_following_cancels_the_run() -> None:
    transport = _AsyncFailsToPrepare(_ok("a"))

    with pytest.raises(OSError, match="No space left"):
        await _aevaluate(transport, "a")

    assert transport.canceled == [RUN_ID]


class _Saving:
    """A transport that can rebuild a Run (`_RunReattaching`), counting what it fetches."""

    def __init__(self, barrier: threading.Barrier | None = None) -> None:
        self.fetched: list[str] = []
        self._barrier = barrier

    def adopt_run(self, run_id: str, candidates: Any) -> None:
        pass

    def wait_run(self, run_id: str, *, detached: bool) -> None:
        pass

    def save_result(self, candidate: Any, outcome: Any) -> Any:
        if self._barrier is not None:
            self._barrier.wait()
        self.fetched.append(candidate.name)
        return outcome


def test_a_run_rebuilt_from_the_engine_downloads_its_results_together() -> None:
    """`report()` on another machine fetches its Candidates' results side by side, not one
    after another."""
    from screamingface._evaluation import reattach

    saving = _Saving(threading.Barrier(2, timeout=5))
    candidates = (_models("a")[0], _models("b")[0])
    settled = reattach.settled_from_records(
        saving, cast(Any, candidates), (valid_outcome("a"), valid_outcome("b"))
    )

    assert [type(outcome) for _, outcome in settled] == [type(valid_outcome("a"))] * 2
    assert sorted(saving.fetched) == ["a", "b"]


def test_the_build_reuses_what_the_follow_kept_and_fetches_only_the_rest() -> None:
    """E5 P2 spec D14: one build for every Report of a Run; an attached follow's results are
    reused, not fetched again, and a Candidate that did not succeed keeps its error."""
    from screamingface._evaluation import reattach
    from screamingface._evaluation.outcome import _Failed

    saving = _Saving()
    candidates = cast(Any, (_models("a")[0], _models("b")[0], _models("c")[0]))
    failed = ExecutionError("it failed", code="candidate_failed")
    kept = valid_outcome("a")

    settled = reattach.settled_from_records(
        saving, candidates, (valid_outcome("a"), valid_outcome("b"), failed), {0: kept}
    )

    assert saving.fetched == ["b"]
    assert settled[0][1] is kept
    assert isinstance(settled[2][1], _Failed) and settled[2][1].error is failed


class _AsyncRefetching(_AsyncFollowing):
    """An async transport that fetches results, counting what the build fetched again."""

    def __init__(self, *script: tuple[Any, ...]) -> None:
        super().__init__(*script)
        self.fetched: list[str] = []

    async def save_result(self, candidate: Any, outcome: Any) -> Any:
        self.fetched.append(candidate.name)
        return outcome


@pytest.mark.asyncio
async def test_an_async_result_the_follow_could_not_fetch_is_fetched_when_the_run_ends() -> None:
    """E5 P2 spec D14: the failure the follow hands over carries the Candidate's recorded
    outcome, and the build fetches its result again."""
    from screamingface._core.ports import with_recorded

    failed = with_recorded(ExecutionError("edge down", code="x"), valid_outcome("a"))
    transport = _AsyncRefetching(("settled", "a", "succeeded", failed), _ok("b"))

    report = await _aevaluate(transport, "a", "b")

    assert [candidate.name for candidate in report.candidates] == ["a", "b"]
    assert transport.fetched == ["a"]
    assert transport.canceled == []


def test_a_result_the_follow_could_not_fetch_and_the_build_cannot_either_fails_its_candidate() -> (
    None
):
    from screamingface._core.ports import with_recorded

    class _Refetching(_Following):
        def adopt_run(self, run_id: str, candidates: Any) -> None:
            pass

        def wait_run(self, run_id: str, *, detached: bool) -> None:
            pass

        def save_result(self, candidate: Any, outcome: Any) -> Any:
            raise ExecutionError("still down", code="result_store_unavailable")

    failed = with_recorded(ExecutionError("edge down", code="x"), valid_outcome("a"))
    transport = _Refetching(("settled", "a", "succeeded", failed), _ok("b"))

    with pytest.raises(ExecutionError) as raised:
        _evaluate(transport, "a", "b")

    assert raised.value.code == "candidates_failed"
    assert transport.canceled == []


def _waiting_sink(clock: list[float]) -> tuple[Any, Any]:
    from test_admission_retry import _PAIR, _Observer

    from screamingface._evaluation import following

    observer = _Observer()
    sink = following._SyncFollow(
        _PAIR, cast(Any, observer), None, waiting_after_s=5.0, clock=lambda: clock[0]
    )
    return sink, observer


def test_a_candidate_pending_only_until_the_first_tick_shows_no_capacity_wait() -> None:
    """#1878 review round 4: every Candidate is `pending` until the driver's first tick, so a
    brief `pending` is not a wait for capacity."""
    clock = [0.0]
    sink, observer = _waiting_sink(clock)

    sink.state(0, "pending")
    clock[0] = 1.0
    sink.state(0, "scheduled")

    assert observer.listeners["queued"].notices == []


def test_a_candidate_still_pending_after_a_while_shows_it_waits_for_capacity() -> None:
    clock = [0.0]
    sink, observer = _waiting_sink(clock)

    sink.state(0, "pending")
    clock[0] = 6.0
    sink.state(1, "running")  # any later frame looks at who is still pending
    sink.state(0, "scheduled")

    assert observer.listeners["queued"].notices == [
        ("waiting_for_capacity", None),
        ("admitted", None),
    ]


def test_a_candidate_pending_while_only_heartbeats_arrive_shows_it_waits_for_capacity() -> None:
    """#1878 review round 5: with every Candidate waiting for a slot, heartbeats are all the
    Run's stream sends, and the wait must still show."""
    clock = [0.0]
    sink, observer = _waiting_sink(clock)

    sink.state(0, "pending")
    clock[0] = 6.0
    sink.quiet()

    assert observer.listeners["queued"].notices == [("waiting_for_capacity", None)]


def test_the_follow_waits_before_saying_a_candidate_waits_for_capacity() -> None:
    from screamingface._evaluation import following

    assert following._WAITING_AFTER_S > 0


@pytest.mark.asyncio
async def test_an_async_build_fetches_its_results_side_by_side_as_the_sync_one_does() -> None:
    """#1878 review round 5: an AsyncClient's Report of a Run read elsewhere fetched one result
    at a time."""
    import asyncio

    from screamingface._evaluation import reattach

    live = most = 0

    class _Saving:
        async def save_result(self, candidate: Any, outcome: Any) -> Any:
            nonlocal live, most
            live += 1
            most = max(most, live)
            await asyncio.sleep(0.01)
            live -= 1
            return outcome

    outcomes = tuple(valid_outcome(str(index)) for index in range(6))
    candidates = cast(Any, tuple(object() for _ in outcomes))

    fetched, kept = await reattach.refetched_async(_Saving(), candidates, outcomes, {})

    assert most == reattach._DOWNLOADS
    assert fetched == outcomes and sorted(kept) == list(range(6))


class _InterruptedSaving(_Saving):
    """Candidate "a"'s fetch is interrupted (Ctrl-C) while "b"'s is still downloading."""

    def __init__(self) -> None:
        super().__init__()
        self.downloading = threading.Event()
        self.release = threading.Event()

    def save_result(self, candidate: Any, outcome: Any) -> Any:
        if candidate.name == "a":
            self.downloading.wait(5)
            raise KeyboardInterrupt
        self.downloading.set()
        self.release.wait(5)
        return outcome


def test_ctrl_c_in_the_build_does_not_wait_for_the_downloads_still_running() -> None:
    """#1878 review: leaving a `with ThreadPoolExecutor` block waits for every running
    download, so the interrupt seemed to hang until they finished."""
    import time

    from screamingface._evaluation import reattach

    saving = _InterruptedSaving()
    candidates = (_models("a")[0], _models("b")[0])
    began = time.monotonic()
    try:
        with pytest.raises(KeyboardInterrupt):
            reattach.settled_from_records(
                saving, cast(Any, candidates), (valid_outcome("a"), valid_outcome("b"))
            )
        assert time.monotonic() - began < 2
    finally:
        saving.release.set()
