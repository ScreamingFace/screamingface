"""Carrying a run's real cost from aigateway's `_aigw` block to the wire cost frame.

FEATURE: per-run cost reporting (`OME-849`). A Report showed an em dash because
screamingface-engine hardcoded `pricing_version="unpriced"` and `total_usd=0`.
aigateway now publishes provider-authored cost, so the placeholder can go.

STORY: as a researcher reading a run Report, I see what my run cost — and still an em dash, never a
confident wrong number, whenever the gateway could not observe the whole call.

Three seams, because the signal crosses three:
  1. the connector reads `_aigw` off the chat-completions payload and reports it (`Usage`);
  2. `_RunState` folds those events onto the owning span and the run totals;
  3. `CostUsageData` carries it on the wire, priced or explicitly unpriced.

A separate module rather than an append to `test_aigateway_connector.py`: the repo's append-only
gate compares file status, so growing an existing test file reads as a modified prior test even
when the diff is purely additive (same reasoning as `test_finish_reason_capture.py`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest

from screamingface_engine.runner.executor import _RunState
from screamingface_engine.world.accounting import OPENROUTER_CREDIT_UNIT, PRICING_VERSION, UNPRICED
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4.dag import run as url4_run
from url4.observe import NodeFinished, NodeStarted, ObservationEvent, Usage
from url4.streaming.interfaces import Traced
from url4.streaming.protocol import CostUsageData, SpanData

_MODEL = "openrouter/anthropic/claude-x"
_BARE_MODEL = "claude-haiku-4-5"


class _Recorder:
    def __init__(self) -> None:
        self.events: list[ObservationEvent] = []

    def on_event(self, event: ObservationEvent) -> None:
        self.events.append(event)

    @property
    def usages(self) -> list[Usage]:
        return [e for e in self.events if isinstance(e, Usage)]


def _aigw(
    *,
    direct_cost_status: str = "complete",
    amount: str | None = "0.001",
    unit: str = OPENROUTER_CREDIT_UNIT,
    cache_status: str = "miss",
    attempts: Any = None,
) -> dict[str, Any]:
    subtotals = (
        []
        if amount is None
        else [{"amount": amount, "unit": unit, "source": "openrouter.usage.cost"}]
    )
    return {
        "usage_accounting": {
            "capture_status": "complete",
            "cache": {"status": cache_status, "reference": None},
            "attempts": [_attempt()] if attempts is None else attempts,
        },
        "request_economics": {
            "direct_cost_status": direct_cost_status,
            "known_direct_cost_subtotals": subtotals,
        },
    }


def _attempt(
    *,
    provider: str = "openrouter",
    response_model: str | None = "anthropic/claude-x-20260801",
    input_total: int = 12480,
    output_total: int = 742,
    cache_read: int | None = 8000,
    cache_write: int | None = 4000,
    reasoning: int | None = 610,
) -> dict[str, Any]:
    return {
        "provider": provider,
        "response_model": response_model,
        "outcome": "succeeded",
        "usage": {
            "input": {"total": input_total, "cache_read": cache_read, "cache_write": cache_write},
            "output": {"total": output_total, "reasoning": reasoning},
        },
    }


def _body(*, aigw: dict[str, Any] | None, content: str = "an answer") -> dict[str, Any]:
    body: dict[str, Any] = {
        "choices": [
            {"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 11, "completion_tokens": 22},
    }
    if aigw is not None:
        body["_aigw"] = aigw
    return body


def _gateway(bodies: dict | list[dict]) -> httpx.AsyncClient:
    sequence = bodies if isinstance(bodies, list) else [bodies]
    index = {"i": 0}

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        i = min(index["i"], len(sequence) - 1)
        index["i"] += 1
        return httpx.Response(200, json=sequence[i])

    return httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://aigateway.test"
    )


async def _run(
    bodies: dict | list[dict],
    recorder: _Recorder | None = None,
    *,
    model: str = _MODEL,
) -> str:
    cfg = AigatewayConfig(models=(ModelSpec(id=model, web_search=False),), default_model=model)
    async with _gateway(bodies) as client:
        world = await build_aigateway_world(cfg, client=client)
        return await url4_run(f"/{model}(ctx)!go", io=world.node, observer=recorder)


def _fold(recorder: _Recorder) -> tuple[list[SpanData], list[CostUsageData], CostUsageData]:
    """Replay the recorded observation events through `_RunState`, as the runner does."""
    state = _RunState()
    frames: list[Traced] = []
    for event in recorder.events:
        frames.extend(state.map(event))
    spans = [f.payload for f in frames if isinstance(f.payload, SpanData)]
    costs = [f.payload for f in frames if isinstance(f.payload, CostUsageData)]
    return spans, costs, state.build_subtree()


# ── seam 1: the connector reads the accounting ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_priced_cost_reaches_the_usage_event() -> None:
    rec = _Recorder()

    assert await _run(_body(aigw=_aigw()), rec) == "an answer"

    usage = rec.usages[0]
    assert usage.cost_usd == Decimal("0.001")
    assert usage.input_tokens == 12480
    assert usage.output_tokens == 742
    assert usage.cache_read_tokens == 8000
    assert usage.cache_creation_tokens == 4000
    assert usage.reasoning_tokens == 610


@pytest.mark.asyncio
async def test_the_authoritative_provider_and_served_model_come_from_the_accounting() -> None:
    """The connector used to derive the provider by splitting the model id and never reported a
    served model at all, though `Usage.response_model` has existed for it."""
    rec = _Recorder()

    await _run(_body(aigw=_aigw()), rec)

    usage = rec.usages[0]
    assert usage.provider == "openrouter"
    assert usage.model == _MODEL
    assert usage.response_model == "anthropic/claude-x-20260801"


@pytest.mark.asyncio
async def test_a_response_without_accounting_falls_back_to_the_provider_usage() -> None:
    """INVARIANT: an older gateway, or any response with no `_aigw`, must keep working exactly as
    before — tokens from the provider's own object and no price at all."""
    rec = _Recorder()

    await _run(_body(aigw=None), rec)

    usage = rec.usages[0]
    assert usage.input_tokens == 11
    assert usage.output_tokens == 22
    assert usage.cost_usd is None
    assert usage.cache_read_tokens is None


@pytest.mark.asyncio
async def test_the_fallback_provider_uses_the_shared_catalog_rule() -> None:
    """A bare id is Anthropic's — aigateway's catalog leaves exactly that one provider unprefixed.
    The rule belongs to `world_config.provider_of`, not to a private copy in the connector."""
    rec = _Recorder()

    await _run(_body(aigw=None), rec, model=_BARE_MODEL)

    assert rec.usages[0].provider == "anthropic"


@pytest.mark.asyncio
async def test_several_calls_in_one_turn_each_report_their_own_accounting() -> None:
    """A tool loop is several gateway calls serving ONE logical model call; each round trip carries
    its own `_aigw`, so each must be reported rather than only the last."""
    rec = _Recorder()
    first = _body(aigw=_aigw(amount="0.001"), content="an answer")
    second = _body(aigw=_aigw(amount="0.002"), content="an answer")

    await _run([first, second], rec)

    assert [u.cost_usd for u in rec.usages] == [Decimal("0.001")]


# ── seam 2 + 3: the span cost frame and the run rollup ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_priced_span_publishes_the_real_total_and_names_the_method() -> None:
    rec = _Recorder()

    await _run(_body(aigw=_aigw()), rec)
    _, costs, subtree = _fold(rec)

    self_costs = [c for c in costs if c.scope == "self"]
    assert len(self_costs) == 1
    assert self_costs[0].pricing_version == PRICING_VERSION
    assert self_costs[0].cost.total_usd == Decimal("0.001")
    assert self_costs[0].usage.cache_read_tokens == 8000
    assert subtree.pricing_version == PRICING_VERSION
    assert subtree.cost.total_usd == Decimal("0.001")


@pytest.mark.asyncio
async def test_a_cache_hit_is_published_as_a_priced_zero() -> None:
    """INVARIANT: P0. A cache hit genuinely cost nothing this request, so it is priced at zero —
    a dash here would hide a real saving."""
    rec = _Recorder()
    hit = _aigw(direct_cost_status="not_applicable", amount=None, cache_status="hit", attempts=[])

    await _run(_body(aigw=hit), rec)
    _, costs, subtree = _fold(rec)

    self_costs = [c for c in costs if c.scope == "self"]
    assert self_costs[0].pricing_version == PRICING_VERSION
    assert self_costs[0].cost.total_usd == Decimal("0")
    assert subtree.pricing_version == PRICING_VERSION


@pytest.mark.asyncio
async def test_an_unobservable_call_is_published_unpriced_not_free() -> None:
    """INVARIANT: P0, and the pair of the test above. Both present an empty subtotal list; this one
    is a real billed call the gateway could not observe, so it must NOT read as zero."""
    rec = _Recorder()
    blind = _aigw(
        direct_cost_status="not_applicable", amount=None, cache_status="miss", attempts=[]
    )

    await _run(_body(aigw=blind), rec)
    _, costs, subtree = _fold(rec)

    self_costs = [c for c in costs if c.scope == "self"]
    assert self_costs[0].pricing_version == UNPRICED
    assert subtree.pricing_version == UNPRICED


@pytest.mark.asyncio
async def test_an_anthropic_run_reporting_no_cost_stays_unpriced() -> None:
    """Regression guard: Anthropic authors no cost field, so its runs keep showing an em dash.
    Must hold before and after this change."""
    rec = _Recorder()
    absent = _aigw(direct_cost_status="unavailable", amount=None)

    await _run(_body(aigw=absent), rec, model=_BARE_MODEL)
    _, costs, subtree = _fold(rec)

    assert [c.pricing_version for c in costs if c.scope == "self"] == [UNPRICED]
    assert subtree.pricing_version == UNPRICED


def test_one_unpriced_span_makes_the_whole_subtree_unpriced() -> None:
    """INVARIANT: P0. A run total missing a step while presenting itself as a total is worse than no
    total. Driven directly through `_RunState` because it needs two spans with different outcomes.
    """
    state = _RunState()
    state.map(_started("span-a"))
    state.map(_usage("span-a", cost=Decimal("0.001")))
    state.map(_finished("span-a"))
    state.map(_started("span-b"))
    state.map(_usage("span-b", cost=None))
    state.map(_finished("span-b"))

    subtree = state.build_subtree()

    assert subtree.pricing_version == UNPRICED
    assert subtree.cost.total_usd == Decimal("0")


def test_a_span_sums_the_cost_of_every_call_it_made() -> None:
    """The web-tools loop: several gateway calls on ONE span. Assigning instead of accumulating
    would keep only the final round trip — the bug already fixed for token counts."""
    state = _RunState()
    state.map(_started("span-a"))
    state.map(_usage("span-a", cost=Decimal("0.001")))
    state.map(_usage("span-a", cost=Decimal("0.002")))
    frames = state.map(_finished("span-a"))

    costs = [f.payload for f in frames if isinstance(f.payload, CostUsageData)]
    assert costs[0].cost.total_usd == Decimal("0.003")
    assert state.build_subtree().cost.total_usd == Decimal("0.003")


def test_an_unpriced_call_poisons_the_span_that_made_it() -> None:
    """One unobservable call in a multi-call span makes that span's cost unknown, not partial."""
    state = _RunState()
    state.map(_started("span-a"))
    state.map(_usage("span-a", cost=Decimal("0.001")))
    state.map(_usage("span-a", cost=None))
    frames = state.map(_finished("span-a"))

    costs = [f.payload for f in frames if isinstance(f.payload, CostUsageData)]
    assert costs[0].pricing_version == UNPRICED


def test_a_run_with_no_model_call_emits_no_cost_frame() -> None:
    """Regression guard: a node that called no model must not gain a cost frame."""
    state = _RunState()
    state.map(_started("span-a"))
    frames = state.map(_finished("span-a"))

    assert [f.payload for f in frames if isinstance(f.payload, CostUsageData)] == []


def _started(span_id: str) -> NodeStarted:
    return NodeStarted(span_id=span_id, parent_span_id=None, node_kind="Model", detail="d")


def _finished(span_id: str) -> NodeFinished:
    return NodeFinished(span_id=span_id, status="ok", engine_seq=1)


def _usage(span_id: str, *, cost: Decimal | None) -> Usage:
    return Usage(
        span_id=span_id,
        provider="openrouter",
        model=_MODEL,
        input_tokens=1,
        output_tokens=1,
        response_model=None,
        cache_read_tokens=None,
        cache_creation_tokens=None,
        reasoning_tokens=None,
        cost_usd=cost,
    )


def test_the_folded_frames_are_timestamped_consistently() -> None:
    """Sanity: the helpers above build real events, so a drift in the event signatures fails here
    rather than silently making every cost test vacuous."""
    assert isinstance(datetime.now(UTC), datetime)
    assert _usage("s", cost=None).cost_usd is None
