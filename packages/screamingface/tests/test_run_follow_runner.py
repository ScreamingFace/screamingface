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
