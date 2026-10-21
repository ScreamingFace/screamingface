"""Every `evaluate` door reaches the pinned-cache replay, and `reproduce` is gone (OME-1613 row 4).

FEATURE: OME-1613 (spec §1, Q13) — `sf.evaluate`, `Client.evaluate` and `AsyncClient.evaluate`
take `pinned_cache=` or `score_id=` and replay a published run. `sf.reproduce` and
`Client.reproduce` were removed: `evaluate(score_id=…)` replaces them.
INVARIANT: S6 — a replay captures nothing, so only an explicit `capture=True` is refused; a normal
run still captures by default (`capture` defaults to None, which means on).
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from test_client_run import REPLAY_URL4, _engine, _ForbiddenTransport
from test_replay import _async_client, _Board, _client, _lookup
from test_reproduce import COPY, _AsyncReplayer, _Replayer

import screamingface as sf
from screamingface import _default_client


def test_a_normal_run_still_captures_by_default() -> None:
    engine = _Replayer()

    with _client(engine, _Board()) as client:
        client.evaluate(REPLAY_URL4, progress=False)

    assert engine.candidate is not None
    assert engine.candidate.capture is True


def test_client_evaluate_replays_a_pinned_cache() -> None:
    engine = _Replayer()

    with _client(engine, _Board(lookup=_lookup())) as client:
        report = client.evaluate(pinned_cache=COPY, progress=False)

    reproduction = report.candidates[0].reproduction
    assert reproduction is not None and reproduction.outcome == "exact"
    assert engine.candidate is not None
    assert (engine.candidate.replay_frozen_copy, engine.candidate.capture) == (COPY, False)


@pytest.mark.asyncio
async def test_async_client_evaluate_replays_a_pinned_cache() -> None:
    async with _async_client(_AsyncReplayer(), _Board(lookup=_lookup())) as client:
        report = await client.evaluate(pinned_cache=COPY, progress=False)

    reproduction = report.candidates[0].reproduction
    assert reproduction is not None and reproduction.outcome == "exact"


def test_module_level_evaluate_replays_through_the_default_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _Replayer()
    client = _client(engine, _Board(lookup=_lookup()))
    monkeypatch.setattr(_default_client, "default_client", lambda: client)

    with client:
        report = sf.evaluate(pinned_cache=COPY, progress=False)

    reproduction = report.candidates[0].reproduction
    assert reproduction is not None and reproduction.outcome == "exact"


def test_module_level_evaluate_refuses_options_a_replay_does_not_take(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(_ForbiddenTransport(), _Board(lookup=_lookup()))
    monkeypatch.setattr(_default_client, "default_client", lambda: client)

    with client, pytest.raises(TypeError):
        sf.evaluate(pinned_cache=COPY, capture=True)  # type: ignore[call-overload]


@pytest.mark.parametrize(
    "arguments",
    [
        {"pinned_cache": COPY, "capture": True},
        {"pinned_cache": COPY, "benchmark": "draco"},
        {"pinned_cache": COPY, "limit": 1},
        {"candidates": REPLAY_URL4, "pinned_cache": COPY},
        {},
        {"candidates": REPLAY_URL4, "url4": REPLAY_URL4},
        {"candidates": REPLAY_URL4, "record_reproduction": False},
    ],
    ids=[
        "capture-on-a-replay",
        "benchmark-on-a-replay",
        "limit-on-a-replay",
        "candidates-on-a-replay",
        "nothing-to-run",
        "url4-without-a-replay",
        "record-without-a-replay",
    ],
)
def test_options_that_do_not_fit_are_refused_before_any_run(arguments: dict[str, Any]) -> None:
    board = _Board(lookup=_lookup())

    with _client(_ForbiddenTransport(), board) as client, pytest.raises(TypeError):
        client.evaluate(**arguments)

    assert board.requests == []


def test_capture_false_on_a_replay_is_allowed() -> None:
    engine = _Replayer()

    with _client(engine, _Board(lookup=_lookup())) as client:
        client.evaluate(pinned_cache=COPY, capture=False, progress=False)  # type: ignore[call-overload]

    assert engine.runs == 1


def test_reproduce_is_gone_from_every_door() -> None:
    client = sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_engine),
    )

    with client:
        assert not hasattr(client, "reproduce")
    assert not hasattr(sf.AsyncClient, "reproduce")
    assert not hasattr(sf, "reproduce")
    assert "reproduce" not in sf.__all__
