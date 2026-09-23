"""Run-level cache counters: hits, misses, and bypasses BY REASON (spec §7 / D7, plan Batch 8).

FEATURE: turning the gateway's response cache on is unobservable without these. A hit costs
nothing upstream, so the failure mode of caching is *silent* in both directions — nobody notices
the savings, and nobody notices when a run that asked for no caching got some anyway.
STORY: as an operator I can answer "did this run actually use the cache, and if not, why not?"
from the run's own telemetry, without correlating spans by hand.

WHY the counters are RUN-level and ride the telemetry stream rather than
`/metrics`: the run mode is a one-shot Job with no scrape endpoint, and
`.claude/scripts/check_layering.py` forbids `screamingface_engine.runner.*` from
importing `screamingface_engine.metrics` at all. The run's own log frame is the
only channel that exists — and it is the right one, since the question is about
ONE run.

**The load-bearing rule this file guards (spec §7): no metric may be labelled by cache key,
prompt or credential.** `test_the_summary_carries_counts_and_nothing_else` and
`test_a_cache_key_on_the_wire_never_reaches_the_summary` are that guard, at the unit and the
end-to-end seam respectively.

A separate module rather than an append to `test_url4_executor.py` / `test_cache_readback.py`:
the repo's append-only gate compares file status, so growing an existing test file reads as "a
prior test was modified" even when the diff is purely additive (OME-369).
"""

from __future__ import annotations

from typing import cast

import httpx
import pytest

from screamingface_engine.runner.cache_counters import (
    BYPASS_REASON_PREFIX,
    CACHE_BYPASSES,
    CACHE_HITS,
    CACHE_MISSES,
    OVERFLOW_REASON,
    REASON_BUCKET_CAP,
    UNSTATED_REASON,
    RunCacheCounters,
)
from screamingface_engine.runner.executor import Url4Executor, _RunState
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4.observe import ModelResponse, NodeFinished, NodeStarted, ObservationEvent
from url4.streaming.interfaces import Completed, Traced
from url4.streaming.protocol import LogData

_MODEL = "anthropic/claude-haiku-4-5"


# ── layer 1: the counter itself ───────────────────────────────────────────────────────────


def test_a_run_that_saw_no_outcome_has_nothing_to_report() -> None:
    # The gate the executor uses. Most runs call no gateway at all, and a summary reading
    # "0 hit, 0 miss, 0 bypass" on every static expression would be noise that trains readers to
    # ignore the line that matters.
    assert RunCacheCounters().observed is False


def test_an_unreported_outcome_counts_as_nothing_rather_than_a_miss() -> None:
    # Boundary: an older gateway, or a non-cache error path, reports no status at all. "Nothing
    # reported" is not "the cache was not used" — counting it as a miss would invent a cache
    # interaction that never happened.
    counters = RunCacheCounters()
    counters.record(None, None)

    assert counters.observed is False
    assert (counters.hits, counters.misses, counters.bypasses) == (0, 0, 0)


def test_hits_misses_and_bypasses_each_land_in_their_own_total() -> None:
    counters = RunCacheCounters()
    counters.record("hit", None)
    counters.record("hit", None)
    counters.record("miss", "not_found")
    counters.record("bypass", "opted_out")

    assert (counters.hits, counters.misses, counters.bypasses) == (2, 1, 1)
    assert counters.observed is True


def test_bypasses_are_broken_down_by_reason() -> None:
    # THE load-bearing counter (spec §7). "I asked for caching and got none" is only answerable
    # if `opted_out` (url4 asked for no cache) stays distinct from `unsupported_control` (url4
    # sent a key the gateway does not know and silently lost every hit).
    counters = RunCacheCounters()
    counters.record("bypass", "opted_out")
    counters.record("bypass", "unsupported_control")
    counters.record("bypass", "opted_out")

    assert counters.bypass_reasons == {"opted_out": 2, "unsupported_control": 1}
    assert counters.bypasses == 3


def test_only_bypasses_are_broken_down_by_reason() -> None:
    # A miss carries a reason too, but it answers nothing: the entry simply was not there. Only
    # a bypass means the cache was never consulted, which is the case that needs a why.
    counters = RunCacheCounters()
    counters.record("miss", "not_found")
    counters.record("hit", "fresh")

    assert counters.bypass_reasons == {}


def test_a_bypass_with_no_stated_reason_gets_its_own_bucket() -> None:
    # Boundary: the reason field is optional on both sources. Dropping the count would make the
    # per-reason breakdown fail to sum to the total, which is worse than an honest "unstated".
    counters = RunCacheCounters()
    counters.record("bypass", None)
    counters.record("bypass", "")

    assert counters.bypass_reasons == {UNSTATED_REASON: 2}
    assert counters.bypasses == 2


def test_reason_buckets_are_bounded_and_the_surplus_still_sums() -> None:
    # INVARIANT: the reason is an upstream free string, so the bucket set must be bounded — the
    # same cardinality doctrine `metrics._route_label` applies to a Prometheus label. Overflow
    # collapses into one bucket rather than being dropped, so the breakdown never under-reports
    # the total it belongs to.
    counters = RunCacheCounters()
    surplus = REASON_BUCKET_CAP + 5
    for i in range(surplus):
        counters.record("bypass", f"reason_{i}")

    reasons = counters.bypass_reasons
    assert len(reasons) <= REASON_BUCKET_CAP + 1
    assert reasons[OVERFLOW_REASON] == surplus - REASON_BUCKET_CAP
    assert sum(reasons.values()) == counters.bypasses == surplus


def test_the_summary_carries_counts_and_nothing_else() -> None:
    # SPEC §7: "No metric may be labelled by cache key, prompt, or credential." The guard is
    # structural — every attribute is an integer count under `cache.`, so there is no slot a key
    # or a prompt could occupy even if one reached this far.
    counters = RunCacheCounters()
    counters.record("hit", None)
    counters.record("bypass", "opted_out")

    attributes = counters.attributes()

    assert attributes[CACHE_HITS] == 1
    assert attributes[CACHE_MISSES] == 0
    assert attributes[CACHE_BYPASSES] == 1
    assert attributes[f"{BYPASS_REASON_PREFIX}opted_out"] == 1
    assert all(isinstance(v, int) for v in attributes.values())
    assert all(k.startswith("cache.") for k in attributes)


def test_the_summary_body_states_the_three_totals() -> None:
    # The attributes are for machines; a human reading the log line must not have to open them.
    counters = RunCacheCounters()
    counters.record("hit", None)
    counters.record("miss", None)
    counters.record("bypass", "disabled")

    body = counters.summary_body()

    assert "1" in body and "hit" in body and "miss" in body and "bypass" in body


# ── layer 2: the run state accumulates them ───────────────────────────────────────────────


def _drive(state: _RunState, events: list[ObservationEvent]) -> None:
    for event in events:
        state.map(event)


def test_run_state_counts_every_round_trips_outcome() -> None:
    state = _RunState()
    _drive(
        state,
        [
            NodeStarted("span1", None, "Node", "detail"),
            ModelResponse("span1", "tool_calls", None, "miss", None),
            ModelResponse("span1", "stop", None, "hit", None),
            NodeFinished("span1", "ok", 1),
        ],
    )

    assert (state.cache_counters.hits, state.cache_counters.misses) == (1, 1)


def test_run_state_counts_an_outcome_whose_span_it_never_opened() -> None:
    # DIFFERENT rule from `_fold_response`'s span guard, deliberately: a span frame must not be
    # fabricated for an id this run never opened, but the round trip still happened and still
    # cost (or saved) money. A run-level total that dropped it would under-report.
    state = _RunState()

    assert state.map(ModelResponse("ghost", "stop", None, "bypass", "opted_out")) == []
    assert state.cache_counters.bypass_reasons == {"opted_out": 1}


# ── layer 3: the run publishes the summary ────────────────────────────────────────────────


def _gateway(headers: dict[str, str]) -> httpx.AsyncClient:
    """A chat-completions endpoint that answers once, with `headers` on the response."""

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(
            200,
            headers=headers,
            json={
                "choices": [{"message": {"role": "assistant", "content": "an answer"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    return httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://aigateway.test"
    )


async def _run_frames(headers: dict[str, str]) -> list[object]:
    cfg = AigatewayConfig(models=(ModelSpec(id=_MODEL),), default_model=_MODEL)
    async with _gateway(headers) as client:
        world = await build_aigateway_world(cfg, client=client)
        executor = Url4Executor(world.node)
        return [frame async for frame in executor.execute(f"/{_MODEL}(ctx)!go")]


def _logs(frames: list[object]) -> list[LogData]:
    payloads = [f.payload if isinstance(f, Traced) else f for f in frames]
    return [p for p in payloads if isinstance(p, LogData)]


@pytest.mark.asyncio
async def test_a_run_that_touched_the_cache_publishes_one_summary_log() -> None:
    frames = await _run_frames({"X-AIGW-Cache": "hit", "X-AIGW-Cache-Reason": "fresh"})

    assert isinstance(frames[-1], Completed)
    summaries = [log for log in _logs(frames) if CACHE_HITS in log.attributes]
    assert len(summaries) == 1
    assert summaries[0].severity_text == "INFO"
    assert summaries[0].attributes[CACHE_HITS] == 1


@pytest.mark.asyncio
async def test_a_run_that_never_reached_a_cache_publishes_no_summary() -> None:
    # Boundary: an older gateway reports nothing, and a run made entirely of static nodes calls
    # no gateway at all. Neither should emit a line saying the cache did nothing.
    frames = await _run_frames({})

    assert [log for log in _logs(frames) if CACHE_HITS in log.attributes] == []


@pytest.mark.asyncio
async def test_a_cache_key_on_the_wire_never_reaches_the_summary() -> None:
    # SPEC §7, end to end. The gateway sends its entry key on every hit; it is read (so the
    # hit/miss-only rule is enforced at the seam that would otherwise leak it) and it must go no
    # further. A key on a run-level counter is a per-entry identifier in telemetry.
    secret = "e3b0c44298fc1c14"
    frames = await _run_frames(
        {"X-AIGW-Cache": "hit", "X-AIGW-Cache-Key": secret, "X-AIGW-Cache-Reason": "fresh"}
    )

    summary = next(log for log in _logs(frames) if CACHE_HITS in log.attributes)
    rendered = summary.model_dump_json()
    assert secret not in rendered
    assert all(isinstance(v, int) for v in cast("dict", summary.attributes).values())


@pytest.mark.asyncio
async def test_the_summary_names_the_bypass_reason_the_gateway_gave() -> None:
    # The whole point of Batch 8: "I asked for caching and got none" becomes answerable from the
    # run's own stream, in the gateway's vocabulary rather than a normalised one.
    frames = await _run_frames(
        {"X-AIGW-Cache": "bypass", "X-AIGW-Cache-Reason": "unsupported_control"}
    )

    summary = next(log for log in _logs(frames) if CACHE_HITS in log.attributes)
    assert summary.attributes[CACHE_BYPASSES] == 1
    assert summary.attributes[f"{BYPASS_REASON_PREFIX}unsupported_control"] == 1
