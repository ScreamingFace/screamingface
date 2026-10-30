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

from screamingface_engine.benchmarks.case_context import case_scope
from screamingface_engine.capture_outcomes import (
    CaptureTally,
    capture_outcomes,
    current_capture_tally,
)
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
async def test_a_call_reissued_under_a_max_age_bound_takes_the_reissue_status() -> None:
    # The first answer is a hit of unknown age: the bound refuses it and the call is re-issued.
    # BOTH answers are stored in the copy, and the model used the second.
    # OME-1775 R2: the re-issue is the last response and it is 2xx, so `find` serves it.
    gateway = Gateway([chat("stale", _HIT), chat("fresh", stored())])
    scope = capture_scope(cache=CachePolicy(max_age=60))

    tally, answer, failure = await run_call(gateway, scope, web_search=False)

    assert failure is None and answer == "fresh"
    assert len(gateway.calls(CHAT)) == 2
    assert [(o.lane, o.status) for o in tally.outcomes] == [("chat", "stored")]
    assert "capture.partial.ambiguous" not in tally.attributes()


@pytest.mark.asyncio
async def test_a_call_with_no_bound_that_hit_is_not_reissued_and_stays_stored() -> None:
    tally, _answer, _failure = await run_call(
        Gateway([chat("hit", _HIT)]), capture_scope(), web_search=False
    )

    assert [o.status for o in tally.outcomes] == ["stored"]


@pytest.mark.asyncio
async def test_a_call_whose_transport_attempt_was_retried_is_ambiguous() -> None:
    # The lost attempt may have been processed and stored before its reply was lost.
    # OME-1775 (owner-approved, D5): a ReadError, as a ConnectError is not ambiguous (R3).
    gateway = Gateway([httpx.ReadError("reset"), chat("answer", stored())])

    tally, answer, failure = await run_call(gateway, capture_scope(), web_search=False)

    assert failure is None and answer == "answer"
    assert [o.status for o in tally.outcomes] == ["ambiguous"]
    assert tally.attributes()["capture.partial.ambiguous"] == 1


@pytest.mark.asyncio
async def test_an_error_after_a_retried_attempt_is_ambiguous_too() -> None:
    gateway = Gateway(
        [
            # OME-1775 (owner-approved, D5): a ReadError, as a ConnectError is not ambiguous (R3).
            httpx.ReadError("reset"),
            httpx.Response(400, headers=stored(), json={"detail": {"code": "bad"}}),
        ]
    )

    tally, _answer, failure = await run_call(gateway, capture_scope(), web_search=False)

    assert failure is not None
    assert [o.status for o in tally.outcomes] == ["ambiguous"]


@pytest.mark.asyncio
async def test_a_later_stored_call_of_the_same_request_never_forgives_an_ambiguous_one() -> None:
    # OME-1775 (owner-approved, D5): a ReadError, as a ConnectError is not ambiguous (R3).
    gateway = Gateway([httpx.ReadError("reset"), chat("a", stored()), chat("b", stored())])

    tally, _answer, _failure = await run_call(
        gateway, capture_scope(), web_search=False, expressions=[EXPRESSION] * 2
    )

    assert [o.status for o in tally.outcomes] == ["ambiguous", "stored"]
    assert tally.attributes()["capture.partial.ambiguous"] == 1


# ── OME-1775: R2 (a max-age re-issue) and R3 (a connect-phase failure) ─────────────────────


@pytest.mark.asyncio
async def test_a_connect_failure_before_the_send_leaves_the_retried_call_stored() -> None:
    # R3: a ConnectError proves no byte left the Engine, so the gateway stored nothing for that try.
    gateway = Gateway([httpx.ConnectError("refused"), chat("answer", stored())])

    tally, answer, failure = await run_call(gateway, capture_scope(), web_search=False)

    assert failure is None and answer == "answer"
    assert [(o.lane, o.status) for o in tally.outcomes] == [("chat", "stored")]
    assert "capture.partial.ambiguous" not in tally.attributes()


@pytest.mark.asyncio
async def test_a_max_age_reissue_whose_last_response_failed_is_ambiguous() -> None:
    # R2: the re-issue is the last response and it is not 2xx, so `find` would prefer the unused
    # first 200 to the stored error. The call stays ambiguous.
    gateway = Gateway(
        [
            chat("stale", _HIT),
            httpx.Response(400, headers=stored(), json={"detail": {"code": "bad"}}),
        ]
    )
    scope = capture_scope(cache=CachePolicy(max_age=60))

    tally, _answer, failure = await run_call(gateway, scope, web_search=False)

    assert failure is not None
    assert [(o.lane, o.status) for o in tally.outcomes] == [("chat", "ambiguous")]
    assert tally.attributes()["capture.partial.ambiguous"] == 1


@pytest.mark.asyncio
async def test_a_max_age_reissue_that_never_reached_the_gateway_is_ambiguous() -> None:
    # R2/R3 review: the stale 2xx stays stored at the key, and the re-issue never left the Engine,
    # so a replay serves the 200 the model never used. The call stays ambiguous, not `stored`.
    gateway = Gateway(
        [chat("stale", _HIT), httpx.ConnectError("refused"), httpx.ConnectError("refused")]
    )
    scope = capture_scope(cache=CachePolicy(max_age=60))

    tally, _answer, failure = await run_call(gateway, scope, web_search=False)

    assert failure is not None
    assert [(o.lane, o.status) for o in tally.outcomes] == [("chat", "ambiguous")]
    assert tally.attributes()["capture.partial.ambiguous"] == 1


@pytest.mark.asyncio
async def test_a_call_cancelled_during_its_max_age_reissue_is_ambiguous() -> None:
    # R1 review: the cancel comes after a stored 2xx was read, so the copy holds a 200 the model
    # never used. The call is not a no-answer outcome that R1 could forgive.
    tallies: list[CaptureTally | None] = []
    sent: list[str] = []

    async def cancel_the_reissue(request: httpx.Request) -> None:
        sent.append(request.url.path)
        if len(sent) == 2:
            tallies.append(current_capture_tally())
            raise asyncio.CancelledError()

    gateway = Gateway([chat("stale", _HIT)])
    gateway.gate = cancel_the_reissue
    scope = capture_scope(cache=CachePolicy(max_age=60))
    with case_scope(7), pytest.raises(asyncio.CancelledError):
        await run_call(gateway, scope, web_search=False)

    (tally,) = tallies
    assert tally is not None
    assert [(o.lane, o.status) for o in tally.outcomes] == [("chat", "ambiguous")]


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


@pytest.mark.asyncio
async def test_a_cancelled_tool_call_records_its_case_and_that_it_gave_no_answer() -> None:
    # OME-1775 R1: a cancelled tool call gave the model no result, and it names its Case.
    def handler(_request: httpx.Request) -> httpx.Response:
        raise asyncio.CancelledError()

    runtime, clients = _runtime(handler)
    call = {"id": "c", "function": {"name": "web_search", "arguments": '{"query": "q"}'}}

    with case_scope(7), capture_outcomes() as tally:
        with pytest.raises(asyncio.CancelledError):
            await append_tool_results([], [call], runtime, _CFG)

    assert [(o.lane, o.status, o.case_id, o.answered) for o in tally.outcomes] == [
        ("tool", "error", "7", False)
    ]
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


@pytest.mark.asyncio
async def test_a_call_whose_every_attempt_lost_its_reply_is_ambiguous_and_never_forgiven() -> None:
    # Every attempt of the first call lost its reply, so the call failed. The gateway may still
    # have stored those answers AHEAD of the one the next call stored and the model used.
    lost: list[httpx.Response | BaseException] = [
        httpx.ReadError("lost") for _ in range(connector._TRANSPORT_RETRIES + 1)
    ]
    gateway = Gateway([*lost, chat("consumed-answer", stored())])

    tally, answer, failure = await run_call(
        gateway, capture_scope(), web_search=False, expressions=[EXPRESSION] * 2
    )

    assert failure is None and answer == "consumed-answer"
    assert [o.status for o in tally.outcomes] == ["ambiguous", "stored"]
    assert tally.status() == "partial"
    assert tally.attributes()["capture.partial.ambiguous"] == 1
