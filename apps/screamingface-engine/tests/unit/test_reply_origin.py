"""Where a model reply came from: a live call, the gateway cache, or a frozen-copy replay.

FEATURE: a recorded judge reply is final (spec 2026-10-16-judge-redraw-live-only, R1-R4). The
connector knows, per round trip, whether the gateway served the reply from its cache or replayed
it from a frozen copy; a judge step reads that fact to decide whether a redraw is allowed.

STORY: as someone replaying a recorded benchmark run, every judge reply comes from the recording,
so the replay reproduces the recorded score and never makes a paid call.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from frozen_copy_support import Gateway, chat, replay_scope, run_call
from test_cache_hit_tokens import _HIT_HEADERS, _MISS_HEADERS

from screamingface_engine.request_scope import RequestScope
from screamingface_engine.world.cache_readback import CacheOutcome, CacheStatus
from screamingface_engine.world.reply_origin import (
    ReplyOrigin,
    record_reply_origin,
    round_trip_origin,
    watch_reply_origin,
)

# --- the mapping from one round trip's facts to its origin ---------------------------------


@pytest.mark.parametrize(
    ("cache_status", "replay_frozen_copy", "origin"),
    [
        ("hit", None, "cache"),
        ("miss", None, "live"),
        ("bypass", None, "live"),
        # R4: no cache outcome reported (an older gateway, a stubbed round trip) → the reply
        # counts as live, which is today's behaviour.
        (None, None, "live"),
        # A replay is a replay whatever the copy's stored headers say about the cache.
        ("miss", "copy-1", "replay"),
        ("hit", "copy-1", "replay"),
        (None, "copy-1", "replay"),
    ],
)
def test_a_round_trip_maps_to_its_origin(
    cache_status: CacheStatus | None, replay_frozen_copy: str | None, origin: ReplyOrigin
) -> None:
    cache: CacheOutcome | None = (
        None
        if cache_status is None
        else CacheOutcome(status=cache_status, reason=None, key=None, age_s=None)
    )
    assert round_trip_origin(cache, replay_frozen_copy) == origin


# --- the watch: what a caller reads after its call -----------------------------------------


def test_a_watch_reads_the_last_recorded_origin() -> None:
    with watch_reply_origin() as watch:
        assert watch.origin is None
        record_reply_origin("live")
        record_reply_origin("cache")
    # INVARIANT: the reply a caller acts on is the LAST round trip's; a tool loop's earlier
    # rounds never decide it.
    assert watch.origin == "cache"


def test_recording_with_no_watch_is_a_no_op() -> None:
    record_reply_origin("cache")  # must not raise: most model calls have no watcher


def test_a_nested_watch_sees_only_its_own_calls_and_the_outer_one_is_restored() -> None:
    with watch_reply_origin() as outer:
        record_reply_origin("live")
        with watch_reply_origin() as inner:
            record_reply_origin("replay")
        record_reply_origin("cache")
    assert (outer.origin, inner.origin) == ("cache", "replay")


@pytest.mark.asyncio
async def test_a_call_in_a_child_task_reaches_the_callers_watch() -> None:
    # WHY: the node may dispatch a judge call in a task of its own; that task inherits a COPY
    # of the caller's context, so the watch must be a shared object, not a value set later.
    async def call() -> None:
        record_reply_origin("cache")

    with watch_reply_origin() as watch:
        await asyncio.create_task(call())
    assert watch.origin == "cache"


# --- the connector records each round trip's origin (V1) -----------------------------------


@pytest.mark.asyncio
async def test_the_connector_records_a_live_reply() -> None:
    with watch_reply_origin() as watch:
        _tally, answer, failure = await run_call(
            Gateway([chat(headers=_MISS_HEADERS)]), RequestScope(origin="run"), web_search=False
        )
    assert (answer, failure) == ("an answer", None)
    assert watch.origin == "live"


@pytest.mark.asyncio
async def test_the_connector_records_a_reply_served_from_the_gateway_cache() -> None:
    with watch_reply_origin() as watch:
        _tally, answer, failure = await run_call(
            Gateway([chat(headers=_HIT_HEADERS)]), RequestScope(origin="run"), web_search=False
        )
    assert (answer, failure) == ("an answer", None)
    assert watch.origin == "cache"


@pytest.mark.asyncio
async def test_the_connector_records_a_reply_with_no_cache_outcome_as_live() -> None:
    with watch_reply_origin() as watch:
        await run_call(Gateway([chat()]), RequestScope(origin="run"), web_search=False)
    assert watch.origin == "live"


@pytest.mark.asyncio
async def test_the_connector_records_a_frozen_copy_replay() -> None:
    with watch_reply_origin() as watch:
        _tally, answer, failure = await run_call(
            Gateway(replay_steps=[chat()]), replay_scope(), web_search=False
        )
    assert (answer, failure) == ("an answer", None)
    assert watch.origin == "replay"


@pytest.mark.asyncio
async def test_a_failed_round_trip_records_nothing() -> None:
    # WHY: a failure stores nothing in the cache, so there is no reply whose origin could
    # forbid a retry (R3); the watch must stay empty rather than claim a reply.
    with watch_reply_origin() as watch:
        _tally, answer, failure = await run_call(
            Gateway([httpx.Response(400, json={"error": {"message": "bad"}})]),
            RequestScope(origin="run"),
            web_search=False,
        )
    assert answer is None and failure is not None
    assert watch.origin is None
