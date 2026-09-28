"""Hop 2 of the cross-stack cache-hit contract: the Engine CONSUMES the gateway's hit fixture and
PRODUCES the run-events fixture the SDK consumes.

FEATURE: run-level saved cost across the stack (spec
``docs/spec/2026-09-28-aigateway-cache-hit-metadata.md`` §3.2).
STORY: as an operator I trust that the money a cache hit saved, as the gateway reported it, is
the money the Engine publishes on the run and the Client carries to the board.

The input is ``apps/aigateway/tests/fixtures/cache_hit_contract/openrouter_hit.json`` — produced
by aigateway's own chat route and guarded there by ``test_cache_hit_contract_fixture.py``. It is
read by repository path, never imported: aigateway is a separate uv project and is not installed
here (the same arrangement as ``test_declared_models_match_aigateway.py``). The real world, the
real executor and the real ``url4.streaming.lifecycle.run`` turn it into the CloudEvents stream a
subscriber receives, encoded with the wire codec.

The output ``tests/unit/data/cache_hit_contract/run_events.json`` is that stream with per-run
values normalized. ``packages/screamingface/tests/test_cache_hit_contract.py`` decodes it.

AIDEV-NOTE: when aigateway regenerates its fixture, this test fails until the stream is
regenerated too: ``SF_REGENERATE_CONTRACT_FIXTURES=1 uv run pytest
tests/unit/test_cache_hit_contract.py``. Then run the SDK suite.
"""

from __future__ import annotations

import json
import os
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

from screamingface_engine.adapters.memory import InMemoryEventStream
from screamingface_engine.request_scope import RequestScope, request_scope
from screamingface_engine.runner.cache_counters import (
    CACHE_HITS,
    SAVED_COST_REPORTED_HITS,
    SAVED_COST_UNPRICED_HITS,
    SAVED_COST_USD,
)
from screamingface_engine.runner.executor import Url4Executor
from screamingface_engine.runner.summary import RunSummary
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4.streaming.codec import encode
from url4.streaming.lifecycle import run
from url4.streaming.protocol import CachePolicy

_REPO_ROOT = Path(__file__).resolve().parents[4]
GATEWAY_HIT = _REPO_ROOT / "apps/aigateway/tests/fixtures/cache_hit_contract/openrouter_hit.json"
RUN_EVENTS = Path(__file__).resolve().parent / "data/cache_hit_contract/run_events.json"
REGENERATE = "SF_REGENERATE_CONTRACT_FIXTURES"

_MODEL = "openrouter/anthropic/claude-fable-5"
URL4 = f"/{_MODEL}(ctx)!go"
_TOPIC = "runs.cache-hit-contract"
_SAVED = "0.012345"

_TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
_TRACEPARENT = re.compile(r"00-([0-9a-f]{32})-([0-9a-f]{16})-01")


def _gateway_hit() -> dict[str, Any]:
    return json.loads(GATEWAY_HIT.read_text(encoding="utf-8"))


async def _published_run() -> tuple[list[dict[str, Any]], RunSummary | None, int]:
    """One real run whose only model call the gateway answers with the fixture hit."""
    hit = _gateway_hit()
    served = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal served
        assert request.url.path == "/v1/chat/completions"
        served += 1
        return httpx.Response(200, headers=hit["headers"], json=hit["body"])

    stream = InMemoryEventStream()
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://aigateway.test"
    )
    config = AigatewayConfig(models=(ModelSpec(id=_MODEL),), default_model=_MODEL)
    async with client:
        world = await build_aigateway_world(config, client=client)
        executor = Url4Executor(world.node)
        with request_scope(RequestScope(origin="run", cache=CachePolicy(participate=True))):
            await run(stream, executor, _TOPIC, URL4)
    # Through the wire codec, byte for byte what a subscriber receives — not a model dump.
    events = [json.loads(encode(event)) async for event in _drain(stream)]
    return events, executor.last_summary(), served


async def _drain(stream: InMemoryEventStream):
    subscription = stream.subscribe(_TOPIC)
    async for event in subscription:
        yield event
        if event.type == "ai.url4.terminated":
            return


def _normalized(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The stream with per-run values replaced by fixed, VALID ones, consistently.

    Span ids are renamed in first-seen order, so parent links in ``tracestate`` still point at
    the same span. Every per-run value is shape-checked before it is replaced.
    """
    spans: dict[str, str] = {}

    def span(value: str) -> str:
        return spans.setdefault(value, f"{len(spans) + 1:016x}")

    out = []
    for index, event in enumerate(events, start=1):
        event = json.loads(json.dumps(event))
        stamp = f"2026-09-28T00:00:{index:02d}Z"
        assert re.fullmatch(r"[0-9a-f]{32}", event["id"])
        event["id"] = f"{index:032x}"
        event["time"] = stamp
        match = _TRACEPARENT.fullmatch(event["traceparent"])
        assert match is not None, event["traceparent"]
        event["traceparent"] = f"00-{_TRACE_ID}-{span(match.group(2))}-01"
        if event["tracestate"] is not None:
            parent = re.fullmatch(r"url4\.parent=([0-9a-f]{16})", event["tracestate"])
            assert parent is not None, event["tracestate"]
            event["tracestate"] = f"url4.parent={span(parent.group(1))}"
        if event["type"] == "ai.url4.span":
            event["data"]["start"] = stamp
            event["data"]["end"] = stamp
        out.append(event)
    return out


def _model_span(events: list[dict[str, Any]]) -> dict[str, Any]:
    (span,) = [
        event["data"]
        for event in events
        if event["type"] == "ai.url4.span"
        and event["data"]["gen_ai.operation.name"] == "RelUrlNode"
    ]
    return span


@pytest.mark.asyncio
async def test_the_gateways_hit_saving_is_the_runs_saving() -> None:
    events, summary, served = await _published_run()

    assert served == 1
    assert summary is not None and summary.cache_attributes is not None
    assert summary.cache_attributes[CACHE_HITS] == 1
    assert summary.cache_attributes[SAVED_COST_REPORTED_HITS] == 1
    assert summary.cache_attributes[SAVED_COST_UNPRICED_HITS] == 0
    # The gateway reported `openrouter_credits`; the Engine converts 1:1 to USD, exactly.
    assert summary.cache_attributes[SAVED_COST_USD] == _SAVED
    # INVARIANT (PRD I1): a hit costs nothing in the run's own total.
    assert summary.cost_usd == Decimal("0")

    span = _model_span(events)
    assert span["cache_status"] == "hit"
    assert span["cache_saved_cost_usd"] == _SAVED
    assert span["cache_saved_cost_archive_usd"] is None


def test_the_saving_the_engine_reads_is_the_one_the_gateway_fixture_carries() -> None:
    # Ties this consumer's expected number to the producer's bytes, so the two cannot drift
    # apart silently when one side edits its constant.
    reference = _gateway_hit()["body"]["_aigw"]["usage_accounting"]["cache"]["reference"]

    assert reference["direct_cost"]["amount"] == _SAVED
    assert reference["direct_cost"]["unit"] == "openrouter_credits"
    assert reference["direct_cost"]["status"] == "reported"


def test_the_engine_ignores_the_reference_fields_it_does_not_price() -> None:
    """Additive-only on the consumer side: the reference's non-money fields are tolerated.

    The Engine reads `cache.reference.direct_cost` and nothing else, so `response_model`,
    `observed_at` and `latency` must never change what it computes.
    """
    from screamingface_engine.world.accounting import avoided_usd_from_aigw

    aigw = _gateway_hit()["body"]["_aigw"]
    reference = aigw["usage_accounting"]["cache"]["reference"]
    assert {"response_model", "observed_at", "latency"} <= set(reference)
    stripped = json.loads(json.dumps(aigw))
    for key in ("response_model", "observed_at", "latency"):
        del stripped["usage_accounting"]["cache"]["reference"][key]

    assert avoided_usd_from_aigw(aigw) == avoided_usd_from_aigw(stripped)
    assert avoided_usd_from_aigw(aigw).usd == Decimal(_SAVED)


@pytest.mark.asyncio
async def test_the_checked_in_run_events_are_what_the_engine_publishes() -> None:
    events, _, _ = await _published_run()
    produced = _normalized(events)

    if os.environ.get(REGENERATE) == "1":
        RUN_EVENTS.parent.mkdir(parents=True, exist_ok=True)
        RUN_EVENTS.write_text(json.dumps(produced, indent=2) + "\n", encoding="utf-8")
    assert RUN_EVENTS.exists(), f"missing {RUN_EVENTS}; generate it with {REGENERATE}=1"
    assert json.loads(RUN_EVENTS.read_text(encoding="utf-8")) == produced, (
        f"the Engine's run stream for the gateway hit changed. If that is deliberate, regenerate "
        f"with {REGENERATE}=1 and run packages/screamingface/tests/test_cache_hit_contract.py."
    )
