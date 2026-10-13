"""E14 F-B3 review round 2026-10-12 — a failure the copy did not serve is permanent (§5.3 2a).

FEATURE: OME-1307. In replay, a chat call whose every transport attempt failed, a non-2xx gateway
answer without the `X-AIGW-Replay` header, and a tool lookup with a transport error all fail the
case with `frozen_copy_unavailable`, with no retry. A retry would read the next occurrence (§5.4),
so the same occurrence is sent again only inside one logical call (transport attempts).
STORY: as a researcher who reproduces a score, a replay that cannot be served says so at once,
and never answers from another entry.

A separate module (append-only gate).
"""

from __future__ import annotations

import httpx
import pytest
from frozen_copy_support import (
    REPLAY_CHAT,
    TOOL_LOOKUP,
    Gateway,
    chat,
    replay_scope,
    run_call,
    tool_call,
)

from screamingface_engine.capture_outcomes import CALL_OCCURRENCE_HEADER
from screamingface_engine.world import connector

_UNAVAILABLE = "frozen_copy_unavailable"


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(connector, "_TRANSPORT_BACKOFF_BASE_S", 0.0)
    monkeypatch.setattr(connector, "_TRANSPORT_BACKOFF_JITTER_S", 0.0)


def _occurrences(gateway: Gateway, path: str) -> set[str]:
    return {headers[CALL_OCCURRENCE_HEADER] for headers, _body in gateway.calls(path)}


@pytest.mark.asyncio
async def test_a_chat_call_whose_every_transport_attempt_failed_fails_unserved() -> None:
    gateway = Gateway(replay_steps=[httpx.ConnectError("down")])

    _tally, answer, failure = await run_call(gateway, replay_scope(), web_search=False)

    assert answer is None
    assert failure is not None
    assert failure.code == _UNAVAILABLE
    assert failure.permanent is True
    # One POST per transport attempt, all for ONE occurrence: no second occurrence is sent.
    assert len(gateway.calls(REPLAY_CHAT)) == connector._TRANSPORT_RETRIES + 1
    assert _occurrences(gateway, REPLAY_CHAT) == {"0"}


@pytest.mark.asyncio
async def test_a_gateway_answer_without_the_replay_header_fails_unserved() -> None:
    gateway = Gateway(replay_steps=[httpx.Response(500, json={"detail": {"code": "boom"}})])

    _tally, answer, failure = await run_call(gateway, replay_scope(), web_search=False)

    assert answer is None
    assert failure is not None
    assert failure.code == _UNAVAILABLE
    assert failure.permanent is True
    assert len(gateway.calls(REPLAY_CHAT)) == 1
    assert _occurrences(gateway, REPLAY_CHAT) == {"0"}


@pytest.mark.asyncio
async def test_a_tool_lookup_with_a_transport_error_fails_unserved() -> None:
    def down(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    gateway = Gateway(
        replay_steps=[tool_call("web_search", {"query": "q"}), chat("final")],
        tool_lookup=down,
    )

    _tally, answer, failure = await run_call(gateway, replay_scope())

    assert answer is None
    assert failure is not None
    assert failure.code == _UNAVAILABLE
    assert failure.permanent is True
    # The lookup is one attempt for one occurrence, and the case stops at its failure.
    assert _occurrences(gateway, TOOL_LOOKUP) == {"0"}
    assert len(gateway.calls(TOOL_LOOKUP)) == 1
    assert len(gateway.calls(REPLAY_CHAT)) == 1


@pytest.mark.asyncio
async def test_a_captured_error_with_the_replay_header_is_raised_as_the_original_error() -> None:
    # The control: a found entry (X-AIGW-Replay: error) is the original run's error, not a loss.
    captured = httpx.Response(
        500,
        headers={"X-AIGW-Replay": "error"},
        json={"detail": {"code": "boom", "message": "m"}},
    )
    gateway = Gateway(replay_steps=[captured])

    _tally, answer, failure = await run_call(gateway, replay_scope(), web_search=False)

    assert answer is None
    assert failure is not None
    assert failure.code == "boom"
    assert failure.code != _UNAVAILABLE
