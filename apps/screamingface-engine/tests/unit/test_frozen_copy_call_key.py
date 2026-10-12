"""E14 F-B3 review round 2026-10-12 — the call key of a frozen-copy call (design §5.4, Q27).

FEATURE: OME-1307. Every chat call and every web-tool call names itself by a case key and an
occurrence: capture and replay send the same pair for the same logical call, so replay reads the
exact entry capture stored. The gateway is faked with `httpx.MockTransport`.
STORY: as a researcher who reproduces a score, I get the same answer for each call, even when the
calls of one case run at the same time and finish in a different order.

A separate module (append-only gate).
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from frozen_copy_support import (
    CHAT,
    EXPRESSION,
    REPLAY_CHAT,
    TOOL_RESULTS,
    Gateway,
    Tavily,
    capture_scope,
    chat,
    error,
    replay_scope,
    run_call,
    stored,
)

from screamingface_engine.benchmarks.case_context import (
    case_attempt_scope,
    case_scope,
    current_case_key,
)
from screamingface_engine.capture_outcomes import (
    CALL_OCCURRENCE_HEADER,
    CASE_KEY_HEADER,
    case_key_for,
)
from screamingface_engine.grading_call_scope import grading_call_scope
from screamingface_engine.world import connector


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(connector, "_TRANSPORT_BACKOFF_BASE_S", 0.0)
    monkeypatch.setattr(connector, "_TRANSPORT_BACKOFF_JITTER_S", 0.0)


def _keys(gateway: Gateway, path: str) -> list[tuple[str | None, str]]:
    """The (case key, occurrence) each call of ``path`` sent, in arrival order."""
    return [(h.get(CASE_KEY_HEADER), h[CALL_OCCURRENCE_HEADER]) for h, _body in gateway.calls(path)]


# ── TDD 1: capture and replay send the same key sequence ───────────────────────────────────


@pytest.mark.asyncio
async def test_capture_and_replay_send_the_same_key_sequence() -> None:
    expressions = [EXPRESSION, EXPRESSION]
    capture = Gateway([chat("a", stored()), chat("b", stored())])
    with case_scope(1):
        await run_call(capture, capture_scope(), expressions=expressions, web_search=False)

    replay = Gateway(replay_steps=[chat("a"), chat("b")])
    with case_scope(1):
        await run_call(replay, replay_scope(), expressions=expressions, web_search=False)

    assert _keys(capture, CHAT) == [(case_key_for(1, 1), "0"), (case_key_for(1, 1), "1")]
    assert _keys(replay, REPLAY_CHAT) == _keys(capture, CHAT)


# ── TDD 2: the same request in two concurrent cases ────────────────────────────────────────


@pytest.mark.asyncio
async def test_same_request_in_two_concurrent_cases_takes_occurrence_0_in_each() -> None:
    gateway = Gateway([chat("a", stored()), chat("b", stored())])
    gateway.hold_until(CHAT, 2)

    async def one_case(case_id: int) -> None:
        with case_scope(case_id):
            await run_call(gateway, capture_scope(), web_search=False)

    await asyncio.gather(one_case(1), one_case(2))

    assert sorted(_keys(gateway, CHAT)) == sorted(
        [(case_key_for(1, 1), "0"), (case_key_for(2, 1), "0")]
    )


# ── TDD 3: transport retries of one call reuse its occurrence ──────────────────────────────


@pytest.mark.asyncio
async def test_transport_retries_of_one_call_reuse_its_occurrence() -> None:
    gateway = Gateway([httpx.ConnectError("down"), chat("ok", stored())])

    await run_call(gateway, capture_scope(), web_search=False)

    assert len(gateway.calls(CHAT)) == 2
    assert _keys(gateway, CHAT) == [(None, "0"), (None, "0")]


# ── TDD 4: a new logical call takes the next occurrence and never gives it back ────────────


@pytest.mark.asyncio
async def test_a_new_logical_call_takes_the_next_occurrence_and_it_is_never_given_back() -> None:
    gateway = Gateway([error(400, "bad"), chat("ok", stored())])

    _tally, answer, failure = await run_call(
        gateway, capture_scope(), expressions=[EXPRESSION, EXPRESSION], web_search=False
    )

    assert failure is None and answer == "ok"
    assert _keys(gateway, CHAT) == [(None, "0"), (None, "1")]


# ── TDD 5: gathered identical tool calls take occurrences in task-creation order ───────────


class _SecondFinishesFirst(Tavily):
    """The first Tavily call parks until the second has answered, so the second task's call
    finishes first. Each answer names its call, so a test can tell the two tasks apart."""

    def __init__(self) -> None:
        super().__init__()
        self._second_answered = asyncio.Event()

    async def handle(self, request: httpx.Request) -> httpx.Response:  # type: ignore[override]
        self.requests.append(request)
        if len(self.requests) == 1:
            await self._second_answered.wait()
            return _search_answer("first")
        self._second_answered.set()
        return _search_answer("second")


def _search_answer(title: str) -> httpx.Response:
    return httpx.Response(
        200, json={"results": [{"title": title, "url": "https://x.test/a", "content": "c"}]}
    )


@pytest.mark.asyncio
async def test_gathered_identical_tool_calls_take_occurrences_in_task_creation_order() -> None:
    calls = [
        {
            "id": f"call_{n}",
            "type": "function",
            "function": {"name": "web_search", "arguments": '{"query": "q"}'},
        }
        for n in (1, 2)
    ]
    two_tool_calls = httpx.Response(
        200,
        json={
            "choices": [{"message": {"role": "assistant", "content": None, "tool_calls": calls}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        },
    )
    gateway = Gateway([two_tool_calls, chat("done", stored())])

    _tally, answer, failure = await run_call(
        gateway, capture_scope(), tavily=_SecondFinishesFirst()
    )

    assert failure is None and answer == "done"
    # Task creation order: the first task's call is occurrence 0 even though its answer came last.
    stored_at = {
        body["result"].split("\n")[0]: h[CALL_OCCURRENCE_HEADER]
        for h, body in gateway.calls(TOOL_RESULTS)
    }
    assert stored_at == {"Title: first": "0", "Title: second": "1"}


# ── TDD 6: the case key of a grading call and of each Attempt ──────────────────────────────


def test_grading_call_uses_the_grading_case_key_or_empty() -> None:
    assert current_case_key() == ""
    with grading_call_scope(7):
        assert current_case_key() == case_key_for(7, 1)


def test_attempt_2_of_a_case_has_its_own_case_key() -> None:
    with case_scope(7):
        first = current_case_key()
        with case_attempt_scope(2):
            second = current_case_key()

    assert first == case_key_for(7, 1)
    assert second == case_key_for(7, 2)
    assert first != second


def test_the_case_id_keeps_its_type_in_the_key() -> None:
    assert case_key_for(1, 1) != case_key_for("1", 1)
