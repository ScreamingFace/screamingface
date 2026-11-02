"""The gateway's image/file input tokens reach the run cost, and unknown stays unknown.

FEATURE: image/file token accounting (OME-1744, engine half of OME-1546). aigateway states at
`usage.prompt_tokens_details.image_and_file_tokens` how much of `prompt_tokens` was image or
document input: an integer when the provider broke it down, `null` or absent when it did not.
STORY: as a researcher running a vision benchmark, my run's `cost.usage` frames carry that count,
and say nothing — never `0` — when the provider gave no breakdown.

INVARIANTS under test:
- present → forwarded onto the `Usage` event and the `self` / `subtree` frames;
- absent, `null` or malformed → unknown (`None`, key omitted from the frame), never `0`;
- one unknown contributing call makes the span AND the run total unknown;
- a text-only run's `cost.usage` frames are byte-identical to the pre-OME-1744 encoding;
- totals are unchanged: the class is a subset of input tokens, never added to them.

A new module rather than an append to an existing one: the repo's append-only gate compares file
status, so growing a prior test file reads as a modified prior test.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx
import pytest

from screamingface_engine.runner.executor import _RunState
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4.dag import run as url4_run
from url4.observe import NodeFinished, NodeStarted, ObservationEvent, Usage
from url4.streaming.protocol import CostUsageData

_MODEL = "openrouter/anthropic/claude-x"
_KEY = "gen_ai.usage.image_and_file_tokens"
_SPAN = "a" * 16
_OTHER_SPAN = "b" * 16
_HIT_HEADERS = {"X-AIGW-Cache": "hit", "X-AIGW-Cache-Reason": "fresh"}
_MISS_HEADERS = {"X-AIGW-Cache": "miss", "X-AIGW-Cache-Reason": "absent"}

# The pre-OME-1744 encodings of a text-only run's `self` and `subtree` frames, captured from the
# code before the field existed (two round trips on one span, the second reporting no cache or
# reasoning classes). LITERALS on purpose: recomputing them would agree with any regression.
_TEXT_ONLY_SELF = (
    '{"scope":"self","gen_ai.provider.name":"openrouter","gen_ai.response.model":"openrouter/x",'
    '"pricing_version":"openrouter-credits-1usd","usage":{"gen_ai.usage.input_tokens":150,'
    '"gen_ai.usage.output_tokens":30,"gen_ai.usage.cache_read_tokens":0,'
    '"gen_ai.usage.cache_creation_tokens":0,"gen_ai.usage.reasoning_tokens":0},'
    '"cost":{"input_usd":"0","output_usd":"0","cache_read_usd":"0","cache_creation_usd":"0",'
    '"reasoning_usd":"0","total_usd":"0.0015"}}'
)
_TEXT_ONLY_SUBTREE = (
    '{"scope":"subtree","gen_ai.provider.name":"openrouter","gen_ai.response.model":"openrouter/x",'
    '"pricing_version":"openrouter-credits-1usd","usage":{"gen_ai.usage.input_tokens":150,'
    '"gen_ai.usage.output_tokens":30,"gen_ai.usage.cache_read_tokens":8,'
    '"gen_ai.usage.cache_creation_tokens":4,"gen_ai.usage.reasoning_tokens":3},'
    '"cost":{"input_usd":"0","output_usd":"0","cache_read_usd":"0","cache_creation_usd":"0",'
    '"reasoning_usd":"0","total_usd":"0.0015"}}'
)


class _Recorder:
    def __init__(self) -> None:
        self.events: list[ObservationEvent] = []

    def on_event(self, event: ObservationEvent) -> None:
        self.events.append(event)

    @property
    def usages(self) -> list[Usage]:
        return [e for e in self.events if isinstance(e, Usage)]


def _aigw() -> dict[str, Any]:
    """The `_aigw` shape a real provider call produces (the gateway's own accounting)."""
    return {
        "usage_accounting": {
            "capture_status": "complete",
            "cache": {"status": "miss", "reference": None},
            "attempts": [
                {
                    "provider": "openrouter",
                    "response_model": "anthropic/claude-x-20260801",
                    "outcome": "succeeded",
                    "usage": {"input": {"total": 900}, "output": {"total": 12}},
                }
            ],
        },
        "request_economics": {"direct_cost_status": "unsupported"},
    }


_ABSENT = object()


def _body(details: object = _ABSENT, *, aigw: dict[str, Any] | None = None) -> dict[str, Any]:
    usage: dict[str, Any] = {"prompt_tokens": 900, "completion_tokens": 12}
    if details is not _ABSENT:
        usage["prompt_tokens_details"] = details
    body: dict[str, Any] = {
        "choices": [
            {"message": {"role": "assistant", "content": "an answer"}, "finish_reason": "stop"}
        ],
        "usage": usage,
    }
    if aigw is not None:
        body["_aigw"] = aigw
    return body


async def _usage_for(body: dict[str, Any], headers: dict[str, str] | None = None) -> Usage:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers=headers or _MISS_HEADERS, json=body)

    rec = _Recorder()
    cfg = AigatewayConfig(models=(ModelSpec(id=_MODEL, web_search=False),), default_model=_MODEL)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://aigateway.test"
    ) as client:
        world = await build_aigateway_world(cfg, client=client)
        assert await url4_run(f"/{_MODEL}(ctx)!go", io=world.node, observer=rec) == "an answer"
    [usage] = rec.usages
    return usage


# ── connector: the gateway field onto the Usage event ────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [0, 1, 640])
async def test_a_reported_image_class_is_forwarded(count: int) -> None:
    # A known 0 is forwarded as 0: the provider broke the input down and it held no media.
    usage = await _usage_for(_body({"image_and_file_tokens": count}))

    assert usage.image_and_file_tokens == count


@pytest.mark.asyncio
async def test_the_image_class_is_read_from_usage_even_when_aigw_is_authoritative() -> None:
    # WHY: the gateway writes the field under `usage`, not under `_aigw`; preferring `_aigw` for
    # the other classes must not hide this one.
    usage = await _usage_for(_body({"image_and_file_tokens": 640}, aigw=_aigw()))

    assert usage.image_and_file_tokens == 640
    assert usage.input_tokens == 900  # the total is the gateway's, untouched by the subset


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "details",
    [
        _ABSENT,  # a pass-through provider: no details object at all
        None,  # `prompt_tokens_details: null` (Antigravity/Codex per spike OME-1598)
        {},  # details without the key
        {"cached_tokens": 5},  # details from another class only
        {"image_and_file_tokens": None},  # the gateway's own "unknown"
        {"image_and_file_tokens": True},  # bool is an int subclass, not a count
        {"image_and_file_tokens": -1},
        {"image_and_file_tokens": 1.5},
        {"image_and_file_tokens": "640"},
        {"image_and_file_tokens": 2**53},  # past the gateway's own bound
        ["image_and_file_tokens", 640],  # details that are not an object
    ],
    ids=lambda d: "absent" if d is _ABSENT else repr(d),
)
async def test_an_unreported_or_malformed_image_class_is_unknown_never_zero(
    details: object,
) -> None:
    usage = await _usage_for(_body(details))

    assert usage.image_and_file_tokens is None


@pytest.mark.asyncio
async def test_a_cache_hit_reports_the_image_class_unknown_not_zero() -> None:
    # Owner decision (2026-10-27): the replayed body's breakdown is the ORIGINAL call's, so a hit
    # states nothing about this class rather than the zero its sibling classes get.
    usage = await _usage_for(_body({"image_and_file_tokens": 640}), _HIT_HEADERS)

    assert usage.image_and_file_tokens is None
    assert usage.input_tokens == 0


# ── executor: the Usage events onto the cost.usage frames ────────────────────────────────────────


def _usage(
    span_id: str = _SPAN, *, image: int | None = None, tokens: int = 100, cost: str = "0.001"
) -> Usage:
    return Usage(
        span_id,
        "openrouter",
        "openrouter/x",
        tokens,
        5,
        None,
        None,
        None,
        None,
        Decimal(cost),
        image,
    )


def _frames(*usages: Usage) -> tuple[list[CostUsageData], CostUsageData]:
    """Drive `_RunState` through one span per distinct span id, then return the self frames and
    the run's subtree frame."""
    state = _RunState()
    span_ids = list(dict.fromkeys(u.span_id for u in usages if u.span_id is not None))
    for span_id in span_ids:
        state.map(NodeStarted(span_id=span_id, parent_span_id=None, node_kind="N", detail="m"))
    for usage in usages:
        state.map(usage)
    selves: list[CostUsageData] = []
    for seq, span_id in enumerate(span_ids):
        for frame in state.map(NodeFinished(span_id=span_id, status="ok", engine_seq=seq)):
            if isinstance(frame.payload, CostUsageData):
                selves.append(frame.payload)
    return selves, state.build_subtree()


def test_a_known_image_class_reaches_the_self_and_subtree_frames() -> None:
    [self_frame], subtree = _frames(_usage(image=40), _usage(image=2))

    assert self_frame.usage.image_and_file_tokens == 42
    assert subtree.usage.image_and_file_tokens == 42
    assert self_frame.usage.model_dump(by_alias=True)[_KEY] == 42


def test_the_run_total_sums_known_image_classes_across_spans() -> None:
    _, subtree = _frames(_usage(_SPAN, image=40), _usage(_OTHER_SPAN, image=2))

    assert subtree.usage.image_and_file_tokens == 42


def test_the_image_class_never_changes_the_input_total() -> None:
    # INVARIANT: a subset of input tokens, like `cached_tokens` — never added on top.
    [self_frame], subtree = _frames(_usage(image=90, tokens=100))

    assert self_frame.usage.input_tokens == 100
    assert subtree.usage.input_tokens == 100


@pytest.mark.parametrize("order", ["known_first", "unknown_first"])
def test_one_unknown_call_makes_the_span_unknown(order: str) -> None:
    calls = [_usage(image=40), _usage(image=None)]
    if order == "unknown_first":
        calls.reverse()

    [self_frame], subtree = _frames(*calls)

    assert self_frame.usage.image_and_file_tokens is None
    assert _KEY not in self_frame.usage.model_dump(by_alias=True)
    assert subtree.usage.image_and_file_tokens is None


@pytest.mark.parametrize("order", ["known_first", "unknown_first"])
def test_one_unknown_span_makes_the_run_total_unknown(order: str) -> None:
    # Owner decision (2026-10-27): unlike the cache/reasoning classes (OME-869), the run total of
    # this class poisons — the wire can say "unknown" for it, so a partial sum would be a lie.
    calls = [_usage(_SPAN, image=40), _usage(_OTHER_SPAN, image=None)]
    if order == "unknown_first":
        calls.reverse()

    selves, subtree = _frames(*calls)

    assert sorted((f.usage.image_and_file_tokens for f in selves), key=lambda v: v is None) == [
        40,
        None,
    ]
    assert subtree.usage.image_and_file_tokens is None
    assert _KEY not in subtree.usage.model_dump(by_alias=True)


def test_a_run_that_made_no_model_call_states_no_image_class() -> None:
    subtree = _RunState().build_subtree()

    assert subtree.usage.image_and_file_tokens is None


def test_a_usage_on_an_unopened_span_still_counts_toward_the_run() -> None:
    # Mirrors the run-total rule for money: a round trip on a span this run never opened still
    # consumed tokens, so it still contributes (and still poisons when unknown).
    state = _RunState()
    state.map(_usage("c" * 16, image=7))

    assert state.build_subtree().usage.image_and_file_tokens == 7

    state.map(_usage("c" * 16, image=None))

    assert state.build_subtree().usage.image_and_file_tokens is None


def test_a_text_only_runs_cost_frames_are_byte_identical_to_before() -> None:
    state = _RunState()
    state.map(NodeStarted(span_id=_SPAN, parent_span_id=None, node_kind="RelUrlNode", detail="m"))
    state.map(
        Usage(_SPAN, "openrouter", "openrouter/x", 100, 20, "x-1", 8, 4, 3, Decimal("0.0012"))
    )
    state.map(
        Usage(
            _SPAN, "openrouter", "openrouter/x", 50, 10, None, None, None, None, Decimal("0.0003")
        )
    )
    frames = state.map(NodeFinished(span_id=_SPAN, status="ok", engine_seq=1))
    [self_frame] = [f.payload for f in frames if isinstance(f.payload, CostUsageData)]

    assert self_frame.model_dump_json(by_alias=True) == _TEXT_ONLY_SELF
    assert state.build_subtree().model_dump_json(by_alias=True) == _TEXT_ONLY_SUBTREE
