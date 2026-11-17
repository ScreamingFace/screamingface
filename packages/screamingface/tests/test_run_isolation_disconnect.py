"""A lost follow ends its own evaluation; a completed Run is never stopped (OME-1067).

FEATURE: OME-1067 — one lost socket must not destroy work that is healthy or already done.
STORY: as a researcher, when my follow of a Run is lost past its reconnect budget, my evaluation
says so and the Run is left to the Engine; and a Run whose Candidates have all finished is never
canceled, even when my callback raises on its last frame.

Since E5 P2 the Engine drives each Run and stops a Candidate itself (spec D1); the Client cancels
the whole Run only for Ctrl-C or its caller's own failure (D14).
"""

from __future__ import annotations

import httpx
import pytest
from _run_engine import RUN_ID, ended, event, run_engine, settled, state
from test_client_run import _engine as _catalog_engine
from test_evaluation_outcome import valid_body

import screamingface as sf
from screamingface._engine.run_client import FollowTimings
from screamingface.errors import ExecutionError

BODY = valid_body().encode()
_MODELS = [sf.Model("provider/opus", name="left"), sf.Model("provider/opus", name="right")]


class _CallerBug(Exception):
    pass


def _client(url: str, *, budget_s: float = 5.0) -> sf.Client:
    client = sf.Client(engine_url=url, http_transport=httpx.MockTransport(_catalog_engine))
    client._transport._runs._timings = FollowTimings(budget_s, 0.0)  # type: ignore[union-attr]
    return client


def _async_client(url: str) -> sf.AsyncClient:
    return sf.AsyncClient(engine_url=url, http_transport=httpx.MockTransport(_catalog_engine))


def test_a_stream_lost_past_its_budget_stops_only_its_own_run() -> None:
    script = [[state(0, "scheduled"), settled(1, BODY), 1011]]
    with run_engine(script, {1: BODY}) as engine, _client(engine.url, budget_s=0.0) as client:
        with pytest.raises(ExecutionError) as raised:
            client.evaluate(_MODELS, benchmark="draco", progress=False)

    assert raised.value.code == "websocket_disconnected"
    assert RUN_ID in raised.value.message
    assert engine.state.deleted == []


def _raise_on_the_last(index: int):
    def on_event(event: sf.Event) -> None:
        if event.sequence == 2 and event.run_id.endswith(f"{index:032x}"):
            raise _CallerBug("the notebook cell's handler failed")

    return on_event


_DONE_THEN_LAST_EVENT = [
    [settled(0, BODY), event(1, 1), settled(1, BODY), event(1, 2), ended()],
]


def test_an_owner_sweep_never_stops_a_completed_run() -> None:
    """A callback that raises once every Candidate has settled sends no cancel."""
    with run_engine(_DONE_THEN_LAST_EVENT, {0: BODY, 1: BODY}) as engine:
        with _client(engine.url) as client, pytest.raises(_CallerBug):
            client.evaluate(
                _MODELS, benchmark="draco", progress=False, on_event=_raise_on_the_last(1)
            )

    assert engine.state.deleted == []


@pytest.mark.asyncio
async def test_async_an_owner_sweep_never_stops_a_completed_run() -> None:
    with run_engine(_DONE_THEN_LAST_EVENT, {0: BODY, 1: BODY}) as engine:
        async with _async_client(engine.url) as client:
            with pytest.raises(_CallerBug):
                await client.evaluate(
                    _MODELS, benchmark="draco", progress=False, on_event=_raise_on_the_last(1)
                )

    assert engine.state.deleted == []


def test_a_raising_terminal_callback_sends_no_stop_for_the_completed_run() -> None:
    """While a sibling still runs, the same callback failure does cancel the Run (C1c)."""
    script = [[event(1, 1), event(1, 2), "hold"]]
    with run_engine(script, {}) as engine, _client(engine.url) as client:
        with pytest.raises(_CallerBug):
            client.evaluate(
                _MODELS, benchmark="draco", progress=False, on_event=_raise_on_the_last(1)
            )

    assert engine.state.deleted == [f"/runs/{RUN_ID}"]
