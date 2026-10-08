"""E14 F-B3 — a replay the copy cannot answer fails the case with its own code (design §5.3).

FEATURE: OME-1307 — a 404 `frozen_copy_miss` or `frozen_copy_unavailable` from the replay route
fails the case with that code; any other failure status is the captured original error and is
raised as the original run raised it. A tool lookup that the copy cannot answer fails the case too:
the model must never carry on from a made-up tool result.
INVARIANT (OME-941): both codes are engine-authored, so their message is the engine's own text.
STORY: as someone who reads a leaderboard result, a replay that cannot be exact fails loudly.

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
from screamingface_engine.error_text import ENGINE_ERROR_CODES, ENGINE_RESERVED_CODES

_GATEWAY_TEXT = "gateway-authored text that must never reach the case"


def _refusal(status: int, detail: object) -> httpx.Response:
    return httpx.Response(status, json={"detail": detail})


@pytest.mark.parametrize("code", ["frozen_copy_miss", "frozen_copy_unavailable"])
def test_both_codes_are_declared_and_engine_authored(code: str) -> None:
    assert code in ENGINE_ERROR_CODES
    assert code in ENGINE_RESERVED_CODES
    assert code in DECLARED_FAILURE_CODES


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "code"),
    [
        (_refusal(404, {"code": "frozen_copy_miss", "message": _GATEWAY_TEXT}), "frozen_copy_miss"),
        (
            _refusal(404, {"code": "frozen_copy_unavailable", "message": _GATEWAY_TEXT}),
            "frozen_copy_unavailable",
        ),
        # A gateway older than the frozen copy has no replay route (design §9).
        (_refusal(404, "Not Found"), "frozen_copy_unavailable"),
    ],
    ids=["miss", "unavailable", "gateway-without-the-route"],
)
async def test_replay_404_miss_and_unavailable_fail_the_case_with_their_codes(
    response: httpx.Response, code: str
) -> None:
    gateway = Gateway(replay_steps=[response])

    _tally, answer, failure = await run_call(gateway, replay_scope())

    assert answer is None
    assert failure is not None
    assert failure.code == code
    assert failure.permanent is True
    assert _GATEWAY_TEXT not in str(failure)
    assert gateway.paths() == [REPLAY_CHAT]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "code", "permanent"),
    [
        # A captured original error: a provider 404, a rate limit, a server error.
        (_refusal(404, {"code": "model_not_found", "message": "m"}), "model_not_found", True),
        (_refusal(429, {"code": "rate_limited", "message": "m"}), "rate_limited", False),
        (_refusal(500, {"code": "boom", "message": "m"}), "boom", False),
        (httpx.Response(502, text="bad gateway"), "aigateway_http_502", False),
    ],
)
async def test_any_other_status_is_the_captured_original_error_handled_as_today(
    response: httpx.Response, code: str, permanent: bool
) -> None:
    gateway = Gateway(replay_steps=[response])

    _tally, _answer, failure = await run_call(gateway, replay_scope())

    assert failure is not None
    assert (failure.code, failure.permanent) == (code, permanent)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("lookup", "code", "permanent"),
    [
        (httpx.Response(404, json={}), "frozen_copy_miss", True),
        (_refusal(404, {"code": "frozen_copy_miss"}), "frozen_copy_miss", True),
        (_refusal(404, {"code": "frozen_copy_unavailable"}), "frozen_copy_unavailable", True),
        (_refusal(404, "Not Found"), "frozen_copy_unavailable", True),
        # The gateway did not answer at all: the copy is unavailable, and a retry may fix it.
        (httpx.Response(500), "frozen_copy_unavailable", False),
        (httpx.Response(200, json={"result": 7}), "frozen_copy_unavailable", False),
        (httpx.Response(200, content=b"not json"), "frozen_copy_unavailable", False),
    ],
    ids=[
        "miss",
        "miss-with-code",
        "unavailable",
        "gateway-without-the-route",
        "gateway-error",
        "malformed-result",
        "not-json",
    ],
)
async def test_tool_lookup_miss_fails_the_case(
    lookup: httpx.Response, code: str, permanent: bool
) -> None:
    tavily = Tavily()
    gateway = Gateway(
        replay_steps=[tool_call("web_search", {"query": "q"}), chat("never reached")],
        tool_lookup=lambda _r: lookup,
    )

    _tally, answer, failure = await run_call(gateway, replay_scope(), tavily=tavily)

    assert answer is None
    assert failure is not None
    assert (failure.code, failure.permanent) == (code, permanent)
    # The model never carries on from a result nobody stored, and Tavily is never the fallback.
    assert len(gateway.calls(REPLAY_CHAT)) == 1
    assert len(gateway.calls(TOOL_LOOKUP)) == 1
    assert tavily.requests == []


@pytest.mark.asyncio
async def test_a_tool_lookup_transport_failure_fails_the_case_as_unavailable() -> None:
    def lookup(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    gateway = Gateway(
        replay_steps=[tool_call("web_search", {"query": "q"}), chat("never reached")],
        tool_lookup=lookup,
    )

    _tally, _answer, failure = await run_call(gateway, replay_scope())

    assert failure is not None
    assert (failure.code, failure.permanent) == ("frozen_copy_unavailable", False)
