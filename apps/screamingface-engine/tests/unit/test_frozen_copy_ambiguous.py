"""E14 F-B3 review — capture records `ambiguous` for a call that may have stored a spare answer.

FEATURE: OME-1307 (design §5.2 item 7). A call that the engine re-issued under a `max-age` bound,
or whose transport attempt was retried, may leave a stored answer the model never used AHEAD of the
one it used. Replay serves entries in capture order, so it could hand back the wrong one. Such a
call records `ambiguous`, which no later call forgives, so the run is `partial`. A tool-lane error
is recorded like the chat lane's (D1), and the copy-side helpers never raise into the run.

A separate module (append-only gate).
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from frozen_copy_support import (
    CHAT,
    COPY,
    EXPRESSION,
    TOOL_RESULTS,
    Gateway,
    Tavily,
    capture_scope,
    chat,
    run_call,
    stored,
    tool_call,
)

from screamingface_engine.capture_outcomes import capture_outcomes
from screamingface_engine.world import connector
from screamingface_engine.world.connector import AigatewayConfig
from screamingface_engine.world.web_tools import (
    FrozenToolResults,
    WebToolRuntime,
    append_tool_results,
)
from url4.streaming.protocol import CachePolicy

_CFG = AigatewayConfig()
_HIT = {"X-AIGW-Cache": "hit", **stored()}


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(connector, "_TRANSPORT_BACKOFF_BASE_S", 0.0)
    monkeypatch.setattr(connector, "_TRANSPORT_BACKOFF_JITTER_S", 0.0)


@pytest.mark.asyncio
async def test_a_call_reissued_under_a_max_age_bound_is_ambiguous() -> None:
    # The first answer is a hit of unknown age: the bound refuses it and the call is re-issued.
    # BOTH answers are stored in the copy, and the model used the second.
    gateway = Gateway([chat("stale", _HIT), chat("fresh", stored())])
    scope = capture_scope(cache=CachePolicy(max_age=60))

    tally, answer, failure = await run_call(gateway, scope, web_search=False)

    assert failure is None and answer == "fresh"
    assert len(gateway.calls(CHAT)) == 2
    assert [(o.lane, o.status) for o in tally.outcomes] == [("chat", "ambiguous")]
    assert tally.attributes()["capture.partial.ambiguous"] == 1


@pytest.mark.asyncio
async def test_a_call_with_no_bound_that_hit_is_not_reissued_and_stays_stored() -> None:
    tally, _answer, _failure = await run_call(
        Gateway([chat("hit", _HIT)]), capture_scope(), web_search=False
    )

    assert [o.status for o in tally.outcomes] == ["stored"]


@pytest.mark.asyncio
async def test_a_call_whose_transport_attempt_was_retried_is_ambiguous() -> None:
    # The lost attempt may have been processed and stored before its reply was lost.
    gateway = Gateway([httpx.ConnectError("reset"), chat("answer", stored())])

    tally, answer, failure = await run_call(gateway, capture_scope(), web_search=False)

    assert failure is None and answer == "answer"
    assert [o.status for o in tally.outcomes] == ["ambiguous"]
    assert tally.attributes()["capture.partial.ambiguous"] == 1


@pytest.mark.asyncio
async def test_an_error_after_a_retried_attempt_is_ambiguous_too() -> None:
    gateway = Gateway(
        [
            httpx.ConnectError("reset"),
            httpx.Response(400, headers=stored(), json={"detail": {"code": "bad"}}),
        ]
    )

    tally, _answer, failure = await run_call(gateway, capture_scope(), web_search=False)

    assert failure is not None
    assert [o.status for o in tally.outcomes] == ["ambiguous"]


@pytest.mark.asyncio
async def test_a_later_stored_call_of_the_same_request_never_forgives_an_ambiguous_one() -> None:
    gateway = Gateway([httpx.ConnectError("reset"), chat("a", stored()), chat("b", stored())])

    tally, _answer, _failure = await run_call(
        gateway, capture_scope(), web_search=False, expressions=[EXPRESSION] * 2
    )

    assert [o.status for o in tally.outcomes] == ["ambiguous", "stored"]
    assert tally.attributes()["capture.partial.ambiguous"] == 1


# ── a cancelled or crashed tool execution is an error outcome (D1) ─────────────────────────


def _runtime(handler: object) -> tuple[WebToolRuntime, list[httpx.AsyncClient]]:
    gateway_client = Gateway().client()
    tavily_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
        base_url="https://tavily.test",
    )
    runtime = WebToolRuntime(
        client=tavily_client,
        config=_CFG,
        api_key="tvly-test-key",  # noqa: S106
        excluded_domains=(),
        frozen=FrozenToolResults(gateway_client, {}, COPY, replay=False),
    )
    return runtime, [gateway_client, tavily_client]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [asyncio.CancelledError(), KeyError("unexpected")],
    ids=["cancelled", "crashed"],
)
async def test_a_cancelled_or_crashed_tool_execution_records_error_then_reraises(
    failure: BaseException,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise failure

    runtime, clients = _runtime(handler)
    call = {"id": "c", "function": {"name": "web_search", "arguments": '{"query": "q"}'}}

    with capture_outcomes() as tally:
        with pytest.raises(type(failure)):
            await append_tool_results([], [call], runtime, _CFG)

    assert [(o.lane, o.status) for o in tally.outcomes] == [("tool", "error")]
    for client in clients:
        await client.aclose()


# ── the copy-side helpers catch Exception and never raise into the tool loop or the run ─────


@pytest.mark.asyncio
async def test_a_tool_result_post_that_crashes_is_failed_not_raised() -> None:
    def store(_request: httpx.Request) -> httpx.Response:
        raise RuntimeError("boom")

    gateway = Gateway(
        [tool_call("web_search", {"query": "q"}, stored()), chat("done", stored())],
        tool_store=store,
    )

    tally, answer, failure = await run_call(gateway, capture_scope(), tavily=Tavily())

    assert failure is None and answer == "done"
    assert [o.status for o in tally.outcomes if o.lane == "tool"] == ["failed"]
    assert len(gateway.calls(TOOL_RESULTS)) == 1
