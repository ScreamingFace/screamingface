"""OME-1947 stack C — a replay of an expired frozen copy says that the copy expired.

FEATURE: OME-1947 — the gateway answers a replay of an expired copy with a 410
`frozen_copy_expired`. The engine fails the case with its own code `frozen_copy_unavailable`
and its own fixed text, on the chat route and on the tool lookup.
INVARIANT (OME-941): the gateway's `message` never reaches the case, and `frozen_copy_expired`
is not an engine code.
STORY: as someone who reads a leaderboard result, a replay of an expired copy says why it failed.

A separate module (append-only gate).
"""

from __future__ import annotations

import httpx
import pytest
from frozen_copy_support import (
    REPLAY_CHAT,
    TOOL_LOOKUP,
    Gateway,
    Tavily,
    chat,
    replay_scope,
    run_call,
    tool_call,
)

from screamingface_engine.benchmarks.contract import DECLARED_FAILURE_CODES
from screamingface_engine.capture_outcomes import (
    REPLAY_EXPIRED,
    REPLAY_EXPIRED_TEXT,
    replay_refusal_code,
)
from screamingface_engine.error_text import ENGINE_ERROR_CODES, ENGINE_RESERVED_CODES

_GATEWAY_TEXT = "gateway-authored text that must never reach the case"
_UNAVAILABLE = "frozen_copy_unavailable"
_CHAT_UNSERVED = "the frozen copy is not available for replay"
_LOOKUP_UNSERVED = "the frozen copy cannot serve a web tool call of this replay"


def _refusal(status: int, detail: object) -> httpx.Response:
    return httpx.Response(status, json={"detail": detail})


def _expired() -> httpx.Response:
    return _refusal(
        410, {"code": "frozen_copy_expired", "state": "expired", "message": _GATEWAY_TEXT}
    )


@pytest.mark.asyncio
async def test_r4_chat_replay_of_an_expired_copy_fails_with_the_expired_text() -> None:
    gateway = Gateway(replay_steps=[_expired()])

    _tally, answer, failure = await run_call(gateway, replay_scope())

    assert answer is None
    assert failure is not None
    assert failure.code == _UNAVAILABLE
    assert failure.permanent is True
    assert str(failure) == REPLAY_EXPIRED_TEXT
    assert gateway.paths() == [REPLAY_CHAT]


@pytest.mark.asyncio
async def test_r5_the_gateway_message_never_reaches_the_case() -> None:
    gateway = Gateway(replay_steps=[_expired()])

    _tally, _answer, failure = await run_call(gateway, replay_scope())

    assert failure is not None
    assert _GATEWAY_TEXT not in str(failure)


@pytest.mark.asyncio
async def test_r6_tool_lookup_of_an_expired_copy_fails_with_the_expired_text() -> None:
    tavily = Tavily()
    gateway = Gateway(
        replay_steps=[tool_call("web_search", {"query": "q"}), chat("never reached")],
        tool_lookup=lambda _r: _expired(),
    )

    _tally, answer, failure = await run_call(gateway, replay_scope(), tavily=tavily)

    assert answer is None
    assert failure is not None
    assert (failure.code, failure.permanent) == (_UNAVAILABLE, True)
    assert str(failure) == REPLAY_EXPIRED_TEXT
    assert _GATEWAY_TEXT not in str(failure)
    assert len(gateway.calls(REPLAY_CHAT)) == 1
    assert len(gateway.calls(TOOL_LOOKUP)) == 1
    assert tavily.requests == []


_OTHER_410S = [
    _refusal(410, {"code": "frozen_copy_miss", "message": _GATEWAY_TEXT}),
    httpx.Response(410, text="gone"),
    httpx.Response(410),
]
_OTHER_410_IDS = ["other-code", "text-body", "empty-body"]


@pytest.mark.asyncio
@pytest.mark.parametrize("response", _OTHER_410S, ids=_OTHER_410_IDS)
async def test_r7_chat_410_without_the_expired_code_keeps_the_unserved_text(
    response: httpx.Response,
) -> None:
    gateway = Gateway(replay_steps=[response])

    _tally, answer, failure = await run_call(gateway, replay_scope())

    assert answer is None
    assert failure is not None
    assert (failure.code, failure.permanent) == (_UNAVAILABLE, True)
    assert str(failure) == _CHAT_UNSERVED
    assert gateway.paths() == [REPLAY_CHAT]


@pytest.mark.asyncio
@pytest.mark.parametrize("lookup", _OTHER_410S, ids=_OTHER_410_IDS)
async def test_r7_tool_lookup_410_without_the_expired_code_keeps_the_unserved_text(
    lookup: httpx.Response,
) -> None:
    tavily = Tavily()
    gateway = Gateway(
        replay_steps=[tool_call("web_search", {"query": "q"}), chat("never reached")],
        tool_lookup=lambda _r: lookup,
    )

    _tally, answer, failure = await run_call(gateway, replay_scope(), tavily=tavily)

    assert answer is None
    assert failure is not None
    assert (failure.code, failure.permanent) == (_UNAVAILABLE, True)
    assert str(failure) == _LOOKUP_UNSERVED
    assert len(gateway.calls(TOOL_LOOKUP)) == 1
    assert tavily.requests == []


def test_r7_the_expired_code_is_the_gateways_and_never_an_engine_code() -> None:
    assert REPLAY_EXPIRED == "frozen_copy_expired"
    assert REPLAY_EXPIRED_TEXT == (
        "the frozen copy expired: no leaderboard score used it in its retention period, "
        "and the gateway deleted its answers"
    )
    assert "frozen_copy_expired" not in ENGINE_ERROR_CODES
    assert "frozen_copy_expired" not in ENGINE_RESERVED_CODES
    assert "frozen_copy_expired" not in DECLARED_FAILURE_CODES


@pytest.mark.parametrize(
    ("status", "payload", "code"),
    [
        (410, {"detail": {"code": "frozen_copy_expired"}}, "frozen_copy_expired"),
        (410, {"detail": {"code": "frozen_copy_miss"}}, None),
        (410, {"detail": "Not Found"}, None),
        (410, None, None),
        (404, {"detail": {"code": "frozen_copy_expired"}}, None),
        (404, {"detail": {"code": "frozen_copy_miss"}}, "frozen_copy_miss"),
        (404, {"detail": "Not Found"}, "frozen_copy_unavailable"),
        (500, {"detail": {"code": "frozen_copy_expired"}}, None),
    ],
    ids=[
        "410-expired",
        "410-miss",
        "410-not-found",
        "410-no-object",
        "404-expired",
        "404-miss",
        "404-not-found",
        "500-expired",
    ],
)
def test_replay_refusal_code_reads_the_expired_code_only_on_a_410(
    status: int, payload: object, code: str | None
) -> None:
    assert replay_refusal_code(status, payload) == code
