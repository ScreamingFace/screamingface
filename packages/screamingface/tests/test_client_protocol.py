"""The SF Engine transport contract on a Run the Engine drives (E5 P2 spec D1, D13, D14).

FEATURE: a detached Run (OME-1837). The transport registers the evaluation, follows the Run on one
stream and builds each Candidate's outcome from the Engine's record; a controlled stub Engine
(`_run_engine.py`) plays each scenario.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import closing

import httpx
import pytest
from _run_engine import (
    RUN_ID,
    AsyncCollectingSink,
    CollectingSink,
    ended,
    event,
    run_engine,
    settled,
    state,
    topic,
)
from test_client_run import _engine as _catalog_engine
from test_evaluation_outcome import valid_body

import screamingface as sf
from screamingface._core.ports import _RunOutcome
from screamingface._engine.transport import AsyncUrl4CloudTransport, Url4CloudTransport
from screamingface._evaluation.model import (
    Candidate,
    _compiled_candidate,
    _compiled_operation,
)

BODY = valid_body().encode()


def _candidate() -> Candidate:
    return _compiled_candidate(
        name="opus",
        kind="model",
        models=("provider/opus",),
        url4="(@)!'hello'",
        operations=(
            _compiled_operation(
                id="op_opus",
                kind="model",
                label="opus answer",
                depends_on=(),
            ),
        ),
    )


def _follow(url: str) -> CollectingSink:
    sink = CollectingSink()
    with closing(Url4CloudTransport(url, reconnect_base_delay_s=0.0)) as transport:
        run_id = transport.register_run(None, (_candidate(),))
        transport.follow_run(run_id, (_candidate(),), sink)
    return sink


async def _afollow(url: str) -> AsyncCollectingSink:
    sink = AsyncCollectingSink()
    transport = AsyncUrl4CloudTransport(url, reconnect_base_delay_s=0.0)
    try:
        run_id = await transport.register_run(None, (_candidate(),))
        await transport.follow_run(run_id, (_candidate(),), sink)
    finally:
        await transport.close()
    return sink


def _client(url: str) -> sf.Client:
    return sf.Client(engine_url=url, http_transport=httpx.MockTransport(_catalog_engine))


_MODELS = [sf.Model("provider/opus", name="left"), sf.Model("provider/opus", name="right")]
_SCRIPT = [[state(0, "scheduled"), event(0, 1), event(0, 2), settled(0, BODY), ended()]]


def test_transport_attaches_before_start_and_returns_the_root_outcome() -> None:
    with run_engine(_SCRIPT, {0: BODY}) as engine:
        sink = _follow(engine.url)

    outcome = sink.outcomes[0]
    assert isinstance(outcome, _RunOutcome)
    assert (outcome.run_id, outcome.result_body) == (topic(0), BODY.decode())
    # One Run registered, then one stream followed: the Client starts nothing itself.
    assert len(engine.state.registered) == 1
    assert engine.state.followed == [f"/runs/{RUN_ID}/events"]


@pytest.mark.asyncio
async def test_async_transport_has_the_same_attach_and_result_boundary() -> None:
    with run_engine(_SCRIPT, {0: BODY}) as engine:
        sink = await _afollow(engine.url)

    assert sink.outcomes[0].result_body == BODY.decode()
    assert engine.state.followed == [f"/runs/{RUN_ID}/events"]


def test_transport_observer_receives_public_events_in_order() -> None:
    with run_engine(_SCRIPT, {0: BODY}) as engine:
        sink = _follow(engine.url)

    assert [(index, e.sequence) for index, e in sink.events] == [(0, 1), (0, 2)]
    assert all(isinstance(e, sf.events.Log) for _, e in sink.events)


def test_heartbeat_is_consumed_as_internal_liveness() -> None:
    heartbeat = json.dumps({"type": "heartbeat"})
    script = [[heartbeat, state(0, "scheduled"), heartbeat, settled(0, BODY), heartbeat, ended()]]
    with run_engine(script, {0: BODY}) as engine:
        sink = _follow(engine.url)

    assert sink.events == []
    assert isinstance(sink.outcomes[0], _RunOutcome)


def test_disconnect_before_terminal_state_is_followed_again() -> None:
    script = [[state(0, "scheduled"), event(0, 1), 1011], [event(0, 1), settled(0, BODY), ended()]]
    with run_engine(script, {0: BODY}) as engine:
        sink = _follow(engine.url)

    assert [e.sequence for _, e in sink.events] == [1]
    assert len(engine.state.followed) == 2


def test_callback_failure_stops_the_attached_run_and_reraises() -> None:
    class _Boom(Exception):
        pass

    def explode(_event: sf.Event) -> None:
        raise _Boom

    with run_engine(_SCRIPT, {0: BODY, 1: BODY}) as engine, _client(engine.url) as client:
        with pytest.raises(_Boom):
            client.evaluate(_MODELS, benchmark="draco", progress=False, on_event=explode)

    assert engine.state.deleted == [f"/runs/{RUN_ID}"]


def test_keyboard_interrupt_stops_the_attached_run_and_reraises() -> None:
    def interrupt(_event: sf.Event) -> None:
        raise KeyboardInterrupt

    with run_engine(_SCRIPT, {0: BODY, 1: BODY}) as engine, _client(engine.url) as client:
        with pytest.raises(KeyboardInterrupt):
            client.evaluate(_MODELS, benchmark="draco", progress=False, on_event=interrupt)

    assert engine.state.deleted == [f"/runs/{RUN_ID}"]


@pytest.mark.asyncio
async def test_async_cancellation_stops_the_attached_run_and_reraises() -> None:
    script = [[state(0, "scheduled"), "hold"]]
    with run_engine(script, {}) as engine:
        client = sf.AsyncClient(
            engine_url=engine.url, http_transport=httpx.MockTransport(_catalog_engine)
        )
        task = asyncio.create_task(client.evaluate(_MODELS, benchmark="draco", progress=False))
        assert await asyncio.to_thread(engine.state.holding.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await client.aclose()

    assert engine.state.deleted == [f"/runs/{RUN_ID}"]


@pytest.mark.parametrize(
    "raised", [OSError("disk full"), TimeoutError("mine")], ids=["os", "timeout"]
)
def test_transport_preserves_disconnect_shaped_callback_exceptions(raised: Exception) -> None:
    """INVARIANT: the caller's own OSError or TimeoutError is theirs, never read as a lost
    connection that the follower would reconnect after."""

    def fail(_event: sf.Event) -> None:
        raise raised

    with run_engine(_SCRIPT, {0: BODY, 1: BODY}) as engine, _client(engine.url) as client:
        with pytest.raises(type(raised)) as caught:
            client.evaluate(_MODELS, benchmark="draco", progress=False, on_event=fail)

    assert caught.value is raised
    assert len(engine.state.followed) == 1
    assert engine.state.deleted == [f"/runs/{RUN_ID}"]


def test_the_trace_id_the_client_sent_is_the_one_it_reports_on_the_outcome() -> None:
    """The Engine mints one trace per Candidate and keeps it on the record (spec §4.3)."""
    with run_engine(_SCRIPT, {0: BODY}) as engine:
        sink = _follow(engine.url)

    assert sink.outcomes[0].trace_id == f"{0:032x}"


def test_start_connection_failure_is_reported_as_engine_unavailable() -> None:
    with closing(Url4CloudTransport("http://127.0.0.1:1")) as transport:
        with pytest.raises(sf.EngineUnavailableError):
            transport.register_run(None, (_candidate(),))
