"""A cache hit consumed nothing, so it reports nothing consumed.

FEATURE: per-run cost reporting (`OME-849`/`OME-868`). `OME-851` reads aigateway's `_aigw` block
and refuses to price the cache reference, because the producer labels it
`incurred_in_current_request: false`. The TOKEN counts crossed that same boundary in the opposite
direction: with no attempts to read, `_report_usage` fell back to the replayed cached body's
`usage` and published the ORIGINAL call's tokens as freshly consumed.

STORY: as a researcher running a cache-heavy benchmark, the token totals describe what my run
actually spent. A hit that reports 12,480 input tokens beside `$0` invites exactly the wrong
conclusion — that the gateway gave away real work — and inflates every consumption figure
downstream.

INVARIANT under test: a published `cache_status` of `hit` and a non-zero token count are a
contradiction. `runner/cache_readback` already says so in its own module docstring ("a cache hit
costs nothing upstream, yet `_report_usage` bills it exactly like a fresh call"); this module
pins the fix.

A separate module rather than an append to `test_run_cost_capture.py`: the repo's append-only gate
compares file status, so growing an existing test file reads as a modified prior test even when
the diff is purely additive.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx
import pytest

from screamingface_engine.world.accounting import OPENROUTER_CREDIT_UNIT, PRICING_VERSION
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4.dag import run as url4_run
from url4.observe import ObservationEvent, Usage

_MODEL = "openrouter/anthropic/claude-x"

_HIT_HEADERS = {"X-AIGW-Cache": "hit", "X-AIGW-Cache-Reason": "fresh"}
_MISS_HEADERS = {"X-AIGW-Cache": "miss", "X-AIGW-Cache-Reason": "absent"}
_BYPASS_HEADERS = {"X-AIGW-Cache": "bypass", "X-AIGW-Cache-Reason": "opted_out"}


class _Recorder:
    def __init__(self) -> None:
        self.events: list[ObservationEvent] = []

    def on_event(self, event: ObservationEvent) -> None:
        self.events.append(event)

    @property
    def usages(self) -> list[Usage]:
        return [e for e in self.events if isinstance(e, Usage)]


def _served_aigw() -> dict[str, Any]:
    """The `_aigw` shape a HIT produces: no attempts, no subtotals, `not_applicable`."""
    return {
        "usage_accounting": {
            "capture_status": "complete",
            "cache": {"status": "hit", "reference": None},
            "attempts": [],
        },
        "request_economics": {
            "direct_cost_status": "not_applicable",
            "known_direct_cost_subtotals": [],
        },
    }


def _billed_aigw() -> dict[str, Any]:
    """The `_aigw` shape a real provider call produces."""
    return {
        "usage_accounting": {
            "capture_status": "complete",
            "cache": {"status": "miss", "reference": None},
            "attempts": [
                {
                    "provider": "openrouter",
                    "response_model": "anthropic/claude-x-20260801",
                    "outcome": "succeeded",
                    "usage": {
                        "input": {"total": 12480, "cache_read": 8000, "cache_write": 4000},
                        "output": {"total": 742, "reasoning": 610},
                    },
                }
            ],
        },
        "request_economics": {
            "direct_cost_status": "complete",
            "known_direct_cost_subtotals": [
                {"amount": "0.001", "unit": OPENROUTER_CREDIT_UNIT, "source": "openrouter"}
            ],
        },
    }


def _body(aigw: dict[str, Any] | None) -> dict[str, Any]:
    """A replayed cached response still carries the ORIGINAL call's `usage` — that is the trap."""
    body: dict[str, Any] = {
        "choices": [
            {"message": {"role": "assistant", "content": "an answer"}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 651, "completion_tokens": 25},
    }
    if aigw is not None:
        body["_aigw"] = aigw
    return body


async def _run(body: dict[str, Any], headers: dict[str, str], rec: _Recorder) -> str:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(200, headers=headers, json=body)

    cfg = AigatewayConfig(models=(ModelSpec(id=_MODEL, web_search=False),), default_model=_MODEL)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://aigateway.test"
    ) as client:
        world = await build_aigateway_world(cfg, client=client)
        return await url4_run(f"/{_MODEL}(ctx)!go", io=world.node, observer=rec)


# ── the defect ─────────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_cache_hit_reports_no_tokens_consumed() -> None:
    """INVARIANT: the replayed body's `usage` describes the ORIGINAL call. Publishing it here
    claims the provider did the work twice."""
    rec = _Recorder()

    assert await _run(_body(_served_aigw()), _HIT_HEADERS, rec) == "an answer"

    usage = rec.usages[0]
    assert usage.input_tokens == 0
    assert usage.output_tokens == 0


@pytest.mark.asyncio
async def test_a_cache_hit_zeroes_every_token_class_not_just_the_two() -> None:
    """Nothing was consumed, so no class may claim otherwise — `None` would read as "unknown"."""
    rec = _Recorder()

    await _run(_body(_served_aigw()), _HIT_HEADERS, rec)

    usage = rec.usages[0]
    assert usage.cache_read_tokens == 0
    assert usage.cache_creation_tokens == 0
    assert usage.reasoning_tokens == 0


@pytest.mark.asyncio
async def test_a_cache_hit_stays_priced_at_zero_rather_than_unpriced() -> None:
    """INVARIANT: `OME-851`'s P0, restated so this unit cannot regress it. Zero is a real claim —
    the call genuinely cost nothing — and a dash here would hide a true saving."""
    rec = _Recorder()

    await _run(_body(_served_aigw()), _HIT_HEADERS, rec)

    assert rec.usages[0].cost_usd == Decimal("0")
    assert PRICING_VERSION == "openrouter-credits-1usd"


@pytest.mark.asyncio
async def test_a_cache_hit_without_any_accounting_block_still_reports_no_tokens() -> None:
    """INVARIANT: hit-ness is decided from the published cache outcome, not from `_aigw`.

    An older gateway emits the `X-AIGW-Cache` header and no accounting at all. Deriving the hit
    from `_aigw` alone would leave that gateway reporting phantom consumption forever.
    """
    rec = _Recorder()

    await _run(_body(None), _HIT_HEADERS, rec)

    usage = rec.usages[0]
    assert usage.input_tokens == 0
    assert usage.output_tokens == 0


# ── the guard: the zeroing is narrow ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_miss_reports_the_real_token_counts() -> None:
    """INVARIANT: a miss is a real provider call. The guard must not blanket-zero every response
    that happens to carry a cache header."""
    rec = _Recorder()

    await _run(_body(_billed_aigw()), _MISS_HEADERS, rec)

    usage = rec.usages[0]
    assert usage.input_tokens == 12480
    assert usage.output_tokens == 742
    assert usage.cache_read_tokens == 8000
    assert usage.cost_usd == Decimal("0.001")


@pytest.mark.asyncio
async def test_a_bypass_reports_the_real_token_counts() -> None:
    """A bypass means the cache refused to serve it, so the provider ran — same as a miss."""
    rec = _Recorder()

    await _run(_body(_billed_aigw()), _BYPASS_HEADERS, rec)

    assert rec.usages[0].input_tokens == 12480
    assert rec.usages[0].output_tokens == 742


@pytest.mark.asyncio
async def test_a_response_with_no_cache_header_at_all_is_untouched() -> None:
    """The overwhelming majority of calls. An absent outcome is not a hit."""
    rec = _Recorder()

    await _run(_body(_billed_aigw()), {}, rec)

    assert rec.usages[0].input_tokens == 12480


@pytest.mark.asyncio
async def test_the_pre_aigw_fallback_survives_for_a_non_hit() -> None:
    """INVARIANT: `OME-851` kept an older gateway working by falling back to the provider's own
    `usage` object. That path must remain for every call that is not a hit."""
    rec = _Recorder()

    await _run(_body(None), _MISS_HEADERS, rec)

    usage = rec.usages[0]
    assert usage.input_tokens == 651
    assert usage.output_tokens == 25
    assert usage.cost_usd is None
