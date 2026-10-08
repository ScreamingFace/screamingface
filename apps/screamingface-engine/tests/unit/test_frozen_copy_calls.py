"""E14 F-B3 — the connector's chat and tool calls in capture mode and in replay mode.

FEATURE: OME-1307 (`02-frozen-copy-design.md` §4, §5.2, §5.3). In capture mode every chat call
names the frozen copy and its `X-AIGW-Capture` answer is recorded. In replay mode every chat call
goes to the copy's own route, and nothing reaches the normal chat route or Tavily. The gateway is
faked with `httpx.MockTransport`.
STORY: as someone who reads a leaderboard result, I can replay it with no provider and no search
cost, and a call the copy cannot answer fails loudly.

A separate module (append-only gate).
"""

from __future__ import annotations

import httpx
import pytest
from frozen_copy_support import (
    CHAT,
    COPY,
    REPLAY_CHAT,
    TOOL_LOOKUP,
    Gateway,
    Tavily,
    capture_scope,
    chat,
    replay_scope,
    run_call,
    stored,
    tool_call,
)

from screamingface_engine.world import connector


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(connector, "_TRANSPORT_BACKOFF_BASE_S", 0.0)
    monkeypatch.setattr(connector, "_TRANSPORT_BACKOFF_JITTER_S", 0.0)


# ── TDD 1: replay never reaches a provider or Tavily ───────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("with_tavily", [False, True], ids=["no-tavily-key", "tavily-configured"])
async def test_replay_mode_never_calls_tavily_or_the_normal_chat_route(with_tavily: bool) -> None:
    gateway = Gateway(
        replay_steps=[tool_call("web_search", {"query": "q"}), chat("final")],
        tool_lookup=lambda _r: httpx.Response(200, json={"result": "stored result"}),
    )
    tavily = Tavily() if with_tavily else None

    _tally, answer, failure = await run_call(gateway, replay_scope(), tavily=tavily)

    assert failure is None
    assert answer == "final"
    # INVARIANT: only the copy's own routes are reached, whatever the Tavily wiring is.
    assert set(gateway.paths()) == {REPLAY_CHAT, TOOL_LOOKUP}
    assert tavily is None or tavily.requests == []
    first, second = (body for _headers, body in gateway.calls(REPLAY_CHAT))
    # The model is offered the tools the original run was offered, so the request keys the same.
    assert "tools" in first
    assert "cache" not in first
    assert second["messages"][-1]["content"] == "stored result"


# ── TDD 2: capture names the copy and records what the gateway says ────────────────────────


@pytest.mark.asyncio
async def test_capture_mode_sends_the_copy_header_on_every_chat_call_and_records_status() -> None:
    gateway = Gateway(
        [tool_call("web_search", {"query": "q"}, stored()), chat("final", stored())],
    )

    tally, answer, failure = await run_call(gateway, capture_scope(), tavily=Tavily())

    assert failure is None
    assert answer == "final"
    calls = gateway.calls(CHAT)
    assert len(calls) == 2
    assert [headers["X-AIGW-Frozen-Copy"] for headers, _body in calls] == [COPY, COPY]
    assert [(o.lane, o.status) for o in tally.outcomes if o.lane == "chat"] == [
        ("chat", "stored"),
        ("chat", "stored"),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("step", "expected"),
    [
        (chat(headers={"X-AIGW-Capture": "stored"}), "stored"),
        (chat(headers={"X-AIGW-Capture": "failed"}), "failed"),
        (chat(headers={"X-AIGW-Capture": "refused"}), "refused"),
        (chat(), "missing"),
        (chat(headers={"X-AIGW-Capture": "surprise"}), "missing"),
        (
            httpx.Response(
                400, headers={"X-AIGW-Capture": "stored"}, json={"detail": {"code": "bad"}}
            ),
            "stored",
        ),
        (
            httpx.Response(
                500, headers={"X-AIGW-Capture": "failed"}, json={"detail": {"code": "boom"}}
            ),
            "failed",
        ),
        (httpx.Response(400, json={"detail": {"code": "bad"}}), "missing"),
        (httpx.ConnectError("down"), "error"),
    ],
    ids=[
        "stored",
        "failed",
        "refused",
        "no-header",
        "unknown-value",
        "error-response-stored",
        "error-response-failed",
        "error-response-no-header",
        "transport-failure",
    ],
)
async def test_the_capture_header_is_read_from_every_response_including_errors(
    step: httpx.Response | BaseException, expected: str
) -> None:
    tally, _answer, _failure = await run_call(Gateway([step]), capture_scope(), web_search=False)

    assert [(o.lane, o.status) for o in tally.outcomes] == [("chat", expected)]
