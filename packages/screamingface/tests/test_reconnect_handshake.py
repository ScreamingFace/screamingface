"""Reconnect-handshake outcomes while following a Run (OME-1016; E5 P2 spec §4.2, D15).

FEATURE: OME-1016 — a deploy mid-Run must not cost the researcher the Run.
STORY: as a researcher whose Evaluation is running during an engine deploy, a proxy's 5xx while
the App restarts is just another reconnect, and a refused or expired sign-in ends the follow at
once with how to pick the Run up again.

Since E5 P2 the Engine drives the Run, so the follow's sign-in is never repaired by a login
mid-follow (D15): the Run does not need it, and a login prompt overnight would wait for nobody.
The fake Engine (`test_run_follow._Engine`) closes the first stream, then answers each reconnect
handshake from a script.
"""

from __future__ import annotations

from typing import Any

import pytest
from test_run_follow import ENDED, RUN_ID, _AsyncEngine, _closed, _Engine, _event, _refused

from screamingface._engine import run_follow
from screamingface.errors import AuthenticationError, ExecutionError

_ACCESS = {"Location": "https://access.example/login?kid=" + "a" * 64}


def _follow(engine: _Engine, *, budget_s: float = 5.0) -> run_follow.RunEnded:
    return run_follow.follow_sync(
        engine.connect, RUN_ID, lambda _f: None, detached=False, budget_s=budget_s, base_delay_s=0
    )


async def _afollow(engine: _AsyncEngine, *, budget_s: float = 5.0) -> run_follow.RunEnded:
    return await run_follow.follow_async(
        engine.connect, RUN_ID, lambda _f: None, detached=False, budget_s=budget_s, base_delay_s=0
    )


def _dropped() -> list[Any]:
    return [_event(0, 1), _event(0, 2), _closed(1012)]


@pytest.mark.parametrize("status", [401, 403])
def test_reconnect_rejected_by_the_engine_fails_fast_and_sweeps(status: int) -> None:
    engine = _Engine(_dropped(), _refused(status))

    with pytest.raises(AuthenticationError) as raised:
        _follow(engine)

    assert raised.value.code == "login_expired"
    assert engine.connects == 2


@pytest.mark.asyncio
async def test_async_reconnect_rejected_by_the_engine_fails_fast_and_sweeps() -> None:
    engine = _AsyncEngine(_dropped(), [_closed(1008, "identity_required")])

    with pytest.raises(AuthenticationError) as raised:
        await _afollow(engine)

    assert raised.value.code == "login_expired"


def test_access_challenge_during_reconnect_resumes_on_the_same_capability() -> None:
    """D15: an Access challenge ends the follow, with how to pick the Run up; no login."""
    engine = _Engine(_dropped(), _refused(302, _ACCESS))

    with pytest.raises(AuthenticationError) as raised:
        _follow(engine)

    assert f"sf.runs.get({RUN_ID!r}).wait()" in (raised.value.hint or "")
    assert engine.connects == 2


@pytest.mark.parametrize("status", [502, 503, 504])
def test_reconnect_handshake_5xx_backs_off_and_resumes(status: int) -> None:
    engine = _Engine(_dropped(), _refused(status), _refused(status), [ENDED])

    assert _follow(engine).state == "complete"
    assert engine.connects == 4


@pytest.mark.asyncio
async def test_async_reconnect_handshake_5xx_backs_off_and_resumes() -> None:
    engine = _AsyncEngine(_dropped(), [_closed(1013, "registry_unavailable")], [ENDED])

    assert (await _afollow(engine)).state == "complete"


def test_reconnect_handshake_5xx_still_ends_when_the_budget_is_spent() -> None:
    engine = _Engine(_dropped(), *([_refused(503)] * 20))

    with pytest.raises(ExecutionError) as raised:
        _follow(engine, budget_s=0.0)

    assert raised.value.code == "websocket_disconnected"
    assert engine.connects == 1


def test_a_5xx_on_the_first_handshake_stays_fatal() -> None:
    """Changed with E5 P2: the Run was started by the Engine when it was registered, so a 5xx
    on the first follow is the App restarting, and is followed again like any other."""
    engine = _Engine(_refused(503), [ENDED])

    assert _follow(engine).state == "complete"
    assert engine.connects == 2


def test_a_non_transient_5xx_on_the_reconnect_is_fatal() -> None:
    engine = _Engine(_dropped(), _refused(501))

    with pytest.raises(ExecutionError) as raised:
        _follow(engine)

    assert (raised.value.code, raised.value.status) == ("run_follow_refused", 501)


def test_a_repeatedly_challenging_edge_stops_after_the_challenge_cap() -> None:
    """No challenge is ever retried: the first one ends the follow (D15)."""
    engine = _Engine(_dropped(), _refused(302, _ACCESS), _refused(302, _ACCESS))

    with pytest.raises(AuthenticationError):
        _follow(engine)

    assert engine.connects == 2
