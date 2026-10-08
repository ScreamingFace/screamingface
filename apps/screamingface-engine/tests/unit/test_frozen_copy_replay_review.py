"""E14 F-B3 review — replay slots, the no-avoided-cost accounting, and no model admission.

FEATURE: OME-1307 (design §5.3 items 1, 1a, 2). The occurrence slot of a request is reserved when
the call is sent and given back when it does not succeed, so concurrent identical requests get
distinct entries. A replayed answer is accounted as served from the cache at $0 WITHOUT a saved-cost
claim: nothing was avoided, the copy answered. A replay never asks the gateway to admit a model.

A separate module (append-only gate).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx
import pytest
from frozen_copy_support import (
    ADMIT,
    EXPRESSION,
    REPLAY_CHAT,
    TOOL_LOOKUP,
    Gateway,
    capture_scope,
    chat,
    error,
    replay_scope,
    run_call,
)

from screamingface_engine.world.accounting import OPENROUTER_CREDIT_UNIT
from url4.observe import ModelResponse, ObservationEvent, Usage

_OCCURRENCE = "X-AIGW-Replay-Occurrence"


def _two_identical_tool_calls() -> httpx.Response:
    calls = [
        {
            "id": f"call_{n}",
            "type": "function",
            "function": {"name": "web_search", "arguments": '{"query": "q"}'},
        }
        for n in (1, 2)
    ]
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"role": "assistant", "content": None, "tool_calls": calls}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        },
    )


@pytest.mark.asyncio
async def test_two_identical_concurrent_replay_requests_get_occurrences_0_and_1() -> None:
    gateway = Gateway(replay_steps=[chat("first"), chat("second")])
    gateway.hold_until(REPLAY_CHAT, 2)  # both requests are on the wire before either answers

    _tally, _answer, failure = await run_call(
        gateway, replay_scope(), expressions=[EXPRESSION, EXPRESSION], concurrent=True
    )

    assert failure is None
    sent = [headers[_OCCURRENCE] for headers, _body in gateway.calls(REPLAY_CHAT)]
    assert sorted(sent) == ["0", "1"]


@pytest.mark.asyncio
async def test_two_identical_concurrent_tool_lookups_get_occurrences_0_and_1() -> None:
    gateway = Gateway(
        replay_steps=[_two_identical_tool_calls(), chat("done")],
        tool_lookup=lambda _r: httpx.Response(200, json={"result": "r"}),
    )
    gateway.hold_until(TOOL_LOOKUP, 2)

    _tally, answer, failure = await run_call(gateway, replay_scope())

    assert failure is None and answer == "done"
    sent = [headers[_OCCURRENCE] for headers, _body in gateway.calls(TOOL_LOOKUP)]
    assert sorted(sent) == ["0", "1"]


@pytest.mark.asyncio
async def test_a_reserved_slot_is_given_back_when_the_call_does_not_succeed() -> None:
    gateway = Gateway(replay_steps=[error(500, "boom"), chat(), chat()])

    tally, _answer, failure = await run_call(gateway, replay_scope(), expressions=[EXPRESSION] * 3)

    assert failure is None
    assert [h[_OCCURRENCE] for h, _b in gateway.calls(REPLAY_CHAT)] == ["0", "0", "1"]
    assert sorted(tally.slots.values()) == [2]


# ── accounting ─────────────────────────────────────────────────────────────────────────────


class _Recorder:
    def __init__(self) -> None:
        self.events: list[ObservationEvent] = []

    def on_event(self, event: ObservationEvent) -> None:
        self.events.append(event)

    def of(self, kind: type) -> list[Any]:
        return [e for e in self.events if isinstance(e, kind)]


def _body_with_a_saved_cost_reference() -> dict[str, Any]:
    """The captured body of an original cache hit: its `_aigw` still names what that hit saved."""
    return {
        "choices": [
            {"message": {"role": "assistant", "content": "an answer"}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 651, "completion_tokens": 25},
        "_aigw": {
            "usage_accounting": {
                "capture_status": "complete",
                "cache": {
                    "status": "hit",
                    "reference": {
                        "direct_cost": {
                            "status": "reported",
                            "amount": "0.0125",
                            "unit": OPENROUTER_CREDIT_UNIT,
                        }
                    },
                },
                "attempts": [],
            },
            "request_economics": {
                "direct_cost_status": "not_applicable",
                "known_direct_cost_subtotals": [],
            },
        },
    }


@pytest.mark.asyncio
async def test_a_replayed_answer_claims_no_avoided_cost_and_spends_nothing() -> None:
    body = _body_with_a_saved_cost_reference()
    recorder = _Recorder()
    await run_call(
        Gateway(replay_steps=[httpx.Response(200, json=body)]),
        replay_scope(),
        web_search=False,
        observer=recorder,
    )

    (response,) = recorder.of(ModelResponse)
    (usage,) = recorder.of(Usage)
    assert response.cache_status == "hit"
    assert response.cache_saved_cost_usd is None
    assert response.cache_saved_cost_provenance is None
    assert usage.cost_usd == Decimal(0)
    assert (usage.input_tokens, usage.output_tokens) == (0, 0)


@pytest.mark.asyncio
async def test_the_same_body_from_a_live_cache_hit_does_claim_the_saving() -> None:
    # The control: the saving claim is real on the normal path, so the test above proves the
    # replay path withdraws it rather than the body never carrying one.
    recorder = _Recorder()
    await run_call(
        Gateway(
            [
                httpx.Response(
                    200, headers={"X-AIGW-Cache": "hit"}, json=_body_with_a_saved_cost_reference()
                )
            ]
        ),
        capture_scope(),
        web_search=False,
        observer=recorder,
        bind_copy=False,
    )

    (response,) = recorder.of(ModelResponse)
    assert response.cache_saved_cost_usd == Decimal("0.0125")


# ── no model admission ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_replay_never_calls_the_model_admission_route() -> None:
    gateway = Gateway(replay_steps=[chat("done")])

    _tally, answer, failure = await run_call(gateway, replay_scope(), web_search=False)

    assert failure is None and answer == "done"
    assert ADMIT not in gateway.paths()
    assert gateway.paths() == [REPLAY_CHAT]
