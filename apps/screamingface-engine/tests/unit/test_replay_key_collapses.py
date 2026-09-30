"""E14 (RP-13d, RP-15) — the version header is parsed, and repeated version hits are counted.

FEATURE: reproducible submissions (OME-1307). The gateway answers a replay call with
`X-AIGW-Cache-Version: hit|miss`. The engine tallies those answers per run and publishes the
counts on the closing cache-summary frame; a hit whose entry key this run already served from the
version is a repeated-key collapse (RP-D5, CV-D6) — an upper bound, because the same key can be
asked twice legitimately.

INVARIANT (spec §7): the entry key is used in memory only, to recognise a repeat. It is never
published in an attribute, the summary body, a log line or an error.
"""

from __future__ import annotations

from typing import cast

import httpx
import pytest

from screamingface_engine.replay_outcomes import VersionOutcome
from screamingface_engine.request_scope import RequestScope
from screamingface_engine.runner.cache_counters import (
    VERSION_HITS,
    VERSION_MISSES,
    VERSION_REPEATED_KEY_COLLAPSES,
    RunCacheCounters,
)
from screamingface_engine.runner.executor import Url4Executor
from screamingface_engine.world.cache_readback import read_cache_outcome
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4.streaming.interfaces import Completed, Traced
from url4.streaming.protocol import LogData

MODEL = "anthropic/claude-haiku-4-5"
GRANT = "eyJhbGciOiJFZERTQSIsImtpZCI6ImsxIn0.eyJ2aWQiOiJ2In0.c2ln"


# --- RP-13d: the header parse -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("hit", "hit"),
        ("HIT ", "hit"),
        ("miss", "miss"),
        ("bogus", None),
        (None, None),
    ],
)
def test_read_cache_outcome_parses_the_version_header(
    raw: str | None, expected: VersionOutcome | None
) -> None:
    headers = {} if raw is None else {"X-AIGW-Cache-Version": raw}

    assert read_cache_outcome(headers).version == expected


def test_the_version_is_read_beside_a_reported_cache_status() -> None:
    """Both return paths of the parse carry it: with a status and without one."""
    with_status = read_cache_outcome({"X-AIGW-Cache": "hit", "X-AIGW-Cache-Version": "hit"})
    without_status = read_cache_outcome({"X-AIGW-Cache-Version": "miss"})

    assert with_status.version == "hit"
    assert without_status.status is None
    assert without_status.version == "miss"


# --- RP-15: the counter -----------------------------------------------------------------------


def test_repeated_key_collapse_counted_in_report() -> None:
    counters = RunCacheCounters()

    counters.record_version("hit", "k1")
    counters.record_version("hit", "k1")
    counters.record_version("hit", "k2")

    assert counters.version_hits == 3
    assert counters.version_repeated_key_collapses == 1
    assert counters.attributes()[VERSION_REPEATED_KEY_COLLAPSES] == 1


def test_a_keyless_hit_is_never_a_collapse() -> None:
    counters = RunCacheCounters()

    counters.record_version("hit", None)
    counters.record_version("hit", None)

    assert counters.version_hits == 2
    assert counters.version_repeated_key_collapses == 0


def test_a_miss_is_counted_and_never_a_collapse() -> None:
    counters = RunCacheCounters()

    counters.record_version("miss", "k1")
    counters.record_version("miss", "k1")

    assert counters.version_misses == 2
    assert counters.version_repeated_key_collapses == 0


def test_the_collapse_key_never_reaches_the_summary() -> None:
    secret = "e3b0c44298fc1c14"
    counters = RunCacheCounters()

    counters.record_version("hit", secret)
    counters.record_version("hit", secret)

    assert secret not in counters.summary_body()
    attributes = counters.attributes()
    assert all(secret not in key for key in attributes)
    assert all(secret not in str(value) for value in attributes.values())


def test_a_run_with_no_version_outcome_publishes_no_version_keys() -> None:
    """Byte identity: a plain run's attributes and summary are what they were before E14."""
    counters = RunCacheCounters()
    counters.record("hit", None)

    assert not any(key.startswith("cache.version.") for key in counters.attributes())
    assert "cache version" not in counters.summary_body()
    assert counters.version_observed is False


def test_a_version_outcome_alone_makes_the_run_observed() -> None:
    counters = RunCacheCounters()

    counters.record_version("miss", None)

    assert counters.observed is True
    assert counters.version_observed is True


def test_the_summary_body_states_the_version_counts() -> None:
    counters = RunCacheCounters()
    counters.record_version("hit", "k1")
    counters.record_version("hit", "k1")
    counters.record_version("miss", None)

    assert counters.summary_body().endswith(
        "; cache version: 2 hit, 1 miss, 1 repeated-key collapse"
    )


def test_the_first_grant_rejection_wins() -> None:
    counters = RunCacheCounters()

    counters.record_grant_rejection("expired")
    counters.record_grant_rejection("subject")

    assert counters.grant_rejection_reason == "expired"


# --- RP-15d: the run publishes the collapse end to end ----------------------------------------


def _gateway(headers: dict[str, str]) -> httpx.AsyncClient:
    def handle(request: httpx.Request) -> httpx.Response:
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


@pytest.mark.asyncio
async def test_a_run_publishes_collapses_end_to_end() -> None:
    # NO `Cache-Status`: a member without `key=` would win over the legacy triple and yield
    # key=None (`cache_readback._from_cache_status`), so the key rides the legacy header here.
    headers = {
        "X-AIGW-Cache-Version": "hit",
        "X-AIGW-Cache": "hit",
        "X-AIGW-Cache-Key": "k1",
    }
    cfg = AigatewayConfig(models=(ModelSpec(id=MODEL),), default_model=MODEL)
    async with _gateway(headers) as client:
        world = await build_aigateway_world(cfg, client=client)
        executor = Url4Executor(
            world.node,
            request_scope_factory=lambda: RequestScope(origin="run", replay_grant=GRANT),
        )
        frames = [f async for f in executor.execute(f"/{MODEL}(/{MODEL}('a')!'x')!'y'")]

    assert isinstance(frames[-1], Completed)
    logs = [f.payload if isinstance(f, Traced) else f for f in frames]
    summaries = [p for p in logs if isinstance(p, LogData) and VERSION_HITS in p.attributes]
    assert len(summaries) == 1
    assert summaries[0].attributes[VERSION_HITS] == 2
    assert summaries[0].attributes[VERSION_MISSES] == 0
    assert summaries[0].attributes[VERSION_REPEATED_KEY_COLLAPSES] == 1
    assert "k1" not in summaries[0].model_dump_json()
    assert all(isinstance(v, int) for v in cast("dict", summaries[0].attributes).values())
