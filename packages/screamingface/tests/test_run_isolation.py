"""One Run's failure stops that Run only (spec 2026-09-28 sdk-run-isolation, OME-1071).

FEATURE: OME-1071 — a failure must not destroy healthy work.
STORY: as a researcher running several evaluations on one Client, when one Run's follow is
refused, only that evaluation stops; nothing is canceled for it, and a later evaluation on the
same Client follows its own Run as usual.

Since E5 P2 the Engine drives each Run (spec D1, D14): a refused or lost follow ends that
evaluation and leaves the Run to the Engine; only Ctrl-C or the caller's own callback cancels it.
"""

from __future__ import annotations

import httpx
import pytest
from _run_engine import RUN_ID, ended, event, run_engine, run_id_of, settled, state
from test_client_run import _engine as _catalog_engine
from test_evaluation_outcome import valid_body

import screamingface as sf
from screamingface.errors import ExecutionError

BODY = valid_body().encode()
_MODELS = [sf.Model("provider/opus", name="left"), sf.Model("provider/opus", name="right")]
_COMPLETE = [state(0, "scheduled"), settled(0, BODY), settled(1, BODY), ended()]


def _client(url: str) -> sf.Client:
    return sf.Client(engine_url=url, http_transport=httpx.MockTransport(_catalog_engine))


def _async_client(url: str) -> sf.AsyncClient:
    return sf.AsyncClient(engine_url=url, http_transport=httpx.MockTransport(_catalog_engine))


# A 1008 with no reason: the Engine refused this follow.
_REFUSED: list[str | int] = [state(0, "scheduled"), event(0, 1), 1008]


def test_a_fatal_reconnect_refusal_stops_only_its_own_run() -> None:
    with run_engine([_REFUSED], {}) as engine, _client(engine.url) as client:
        with pytest.raises(ExecutionError) as raised:
            client.evaluate(_MODELS, benchmark="draco", progress=False)

    assert raised.value.code == "run_follow_refused"
    assert engine.state.deleted == []


@pytest.mark.asyncio
async def test_async_a_fatal_reconnect_refusal_stops_only_its_own_run() -> None:
    with run_engine([_REFUSED], {}) as engine:
        async with _async_client(engine.url) as client:
            with pytest.raises(ExecutionError) as raised:
                await client.evaluate(_MODELS, benchmark="draco", progress=False)

    assert raised.value.code == "run_follow_refused"
    assert engine.state.deleted == []


def _interrupt(_event: sf.Event) -> None:
    raise KeyboardInterrupt


def test_a_run_after_an_owner_abort_reconnects_again() -> None:
    script = [[event(0, 1), "hold"], _COMPLETE]
    with run_engine(script, {0: BODY, 1: BODY}) as engine, _client(engine.url) as client:
        with pytest.raises(KeyboardInterrupt):
            client.evaluate(_MODELS, benchmark="draco", progress=False, on_event=_interrupt)
        engine.state.release.set()
        report = client.evaluate(_MODELS, benchmark="draco", progress=False)

    # The abort canceled its own Run only; the next evaluation followed its Run to the end.
    assert engine.state.deleted == [f"/runs/{RUN_ID}"]
    assert report.run_id == run_id_of(1)
    assert [c.name for c in report.candidates] == ["left", "right"]


@pytest.mark.asyncio
async def test_async_a_run_after_an_owner_abort_reconnects_again() -> None:
    script = [[event(0, 1), "hold"], _COMPLETE]
    with run_engine(script, {0: BODY, 1: BODY}) as engine:
        async with _async_client(engine.url) as client:
            with pytest.raises(KeyboardInterrupt):
                await client.evaluate(
                    _MODELS, benchmark="draco", progress=False, on_event=_interrupt
                )
            engine.state.release.set()
            report = await client.evaluate(_MODELS, benchmark="draco", progress=False)

    assert engine.state.deleted == [f"/runs/{RUN_ID}"]
    assert report.run_id == run_id_of(1)


def test_a_run_after_an_owner_abort_stops_its_own_run_when_its_budget_ends() -> None:
    """A follow that cannot get its connection back ends that evaluation; the Run is the
    Engine's from then on (its orphan grace stops an attached one), so nothing is canceled."""
    from screamingface._engine.run_client import FollowTimings

    with run_engine([[event(0, 1), 1011]], {}) as engine:
        client = sf.Client(
            engine_url=engine.url, http_transport=httpx.MockTransport(_catalog_engine)
        )
        client._transport._runs._timings = FollowTimings(0.0, 0.0)  # type: ignore[union-attr]
        with client, pytest.raises(ExecutionError) as raised:
            client.evaluate(_MODELS, benchmark="draco", progress=False)

    assert raised.value.code == "websocket_disconnected"
    assert engine.state.deleted == []
