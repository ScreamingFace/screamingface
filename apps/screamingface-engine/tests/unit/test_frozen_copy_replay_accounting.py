"""E14 F-B3 — a replayed answer is accounted as a cache hit that spent nothing (design §5.3 item 2).

FEATURE: OME-1307 — the replay route returns the captured body with the call cost set to 0. The
engine reads it through the existing served-from-cache path: no token is consumed, the call is
priced at zero, and the response is published as a hit. A replay never pays a provider, so even a
transport retry of a replay call leaves the zero price intact.
STORY: as a researcher replaying a score, the run's cost total is $0.

A separate module (append-only gate).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx
import pytest
from frozen_copy_support import Gateway, replay_scope, run_call

from screamingface_engine.world import connector
from screamingface_engine.world.accounting import OPENROUTER_CREDIT_UNIT
from url4.observe import ModelResponse, ObservationEvent, Usage


class _Recorder:
    def __init__(self) -> None:
        self.events: list[ObservationEvent] = []

    def on_event(self, event: ObservationEvent) -> None:
        self.events.append(event)

    def of(self, kind: type) -> list[Any]:
        return [e for e in self.events if isinstance(e, kind)]


def _replayed(*, zero_aigw: bool = True) -> httpx.Response:
    """A replayed body: the ORIGINAL call's usage, its cost zeroed, and the replay mark."""
    body: dict[str, Any] = {
        "choices": [
            {"message": {"role": "assistant", "content": "an answer"}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 651, "completion_tokens": 25},
        "frozen_copy_replay": True,
    }
    if zero_aigw:
        body["_aigw"] = {
            "usage_accounting": {"capture_status": "complete", "cache": None, "attempts": []},
            "request_economics": {
                "direct_cost_status": "complete",
                "known_direct_cost_subtotals": [
                    {"amount": "0", "unit": OPENROUTER_CREDIT_UNIT, "source": "openrouter"}
                ],
            },
        }
    return httpx.Response(200, headers={"X-AIGW-Replay": "hit"}, json=body)


@pytest.mark.asyncio
@pytest.mark.parametrize("zero_aigw", [True, False], ids=["zeroed-aigw", "no-aigw"])
async def test_replay_success_is_accounted_as_zero_spend(zero_aigw: bool) -> None:
    recorder = _Recorder()

    _tally, answer, failure = await run_call(
        Gateway(replay_steps=[_replayed(zero_aigw=zero_aigw)]),
        replay_scope(),
        web_search=False,
        observer=recorder,
    )

    assert failure is None and answer == "an answer"
    (usage,) = recorder.of(Usage)
    # The body still carries the original call's tokens; none of them were consumed now.
    assert (usage.input_tokens, usage.output_tokens) == (0, 0)
    assert (usage.cache_read_tokens, usage.cache_creation_tokens, usage.reasoning_tokens) == (
        0,
        0,
        0,
    )
    assert usage.cost_usd == Decimal(0)
    (response,) = recorder.of(ModelResponse)
    assert response.cache_status == "hit"


@pytest.mark.asyncio
async def test_a_replay_call_that_needed_a_transport_retry_is_still_priced_at_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A retried LIVE hit is unpriced because the lost attempt may have been billed. A replay
    # attempt can never have been billed, so the retry says nothing about its price.
    monkeypatch.setattr(connector, "_TRANSPORT_BACKOFF_BASE_S", 0.0)
    monkeypatch.setattr(connector, "_TRANSPORT_BACKOFF_JITTER_S", 0.0)
    recorder = _Recorder()

    _tally, _answer, failure = await run_call(
        Gateway(replay_steps=[httpx.ConnectError("reset"), _replayed()]),
        replay_scope(),
        web_search=False,
        observer=recorder,
    )

    assert failure is None
    assert recorder.of(Usage)[0].cost_usd == Decimal(0)
