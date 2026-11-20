"""Hop 3 of the cross-stack cache-hit contract: the Client CONSUMES the Engine's run.

FEATURE: what the cache saved, carried from the gateway to the board (spec
``docs/spec/2026-09-28-aigateway-cache-hit-metadata.md`` §3.2; OME-1155, OME-1326).
STORY: as a researcher whose run the gateway served from its cache, my Report and my board
submission show the saving the gateway recorded when it filled the cache — the same number, not
a re-derived one.

The input ``apps/screamingface-engine/tests/unit/data/cache_hit_contract/run_events.json`` is the
real Engine's CloudEvents stream for a run whose only model call aigateway answered with its real
hit response. The Engine regenerates it (``test_cache_hit_contract.py`` there) from aigateway's
own fixture, so a change anywhere upstream reaches this file. It is read by repository path: the
Engine is not a dependency of the Client. The Engine's fold reads the saving from it into the
Candidate's record (`test_candidate_record_evidence_rules.py` there); the Client reads the record.
"""

from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from test_client_run import REPLAY_URL4, _engine, _ReplayTransport

import screamingface as sf
from screamingface._core.ports import _RunOutcome
from screamingface._engine.contract import _RunState, usage_value
from screamingface._scoreboard.leaderboards import _submission
from screamingface.errors import ExecutionError

_REPO_ROOT = Path(__file__).resolve().parents[3]
RUN_EVENTS = (
    _REPO_ROOT / "apps/screamingface-engine/tests/unit/data/cache_hit_contract/run_events.json"
)

# The expression the Engine ran to produce the stream. `_RunState` identifies the root by it.
_URL4 = "/openrouter/anthropic/claude-fable-5(ctx)!go"
_SAVED = Decimal("0.012345")


def _events() -> list[dict[str, Any]]:
    return json.loads(RUN_EVENTS.read_text(encoding="utf-8"))


def _recorded_usage() -> sf.Usage:
    """The run's usage as the Engine's record carries it (the root's subtree `cost.usage` data),
    read the way the Client reads a record's usage."""
    data = next(
        event["data"]
        for event in _events()
        if event["type"] == "ai.url4.cost.usage" and event["data"]["scope"] == "subtree"
    )
    return usage_value(data)


class _StreamedCacheTransport(_ReplayTransport):
    """The replay Candidate, with the three fields the Engine's record gives for this run.

    WHAT IS TESTED WHERE: the hop that reads the Engine's real stream is the Engine's fold
    (`test_the_real_stream_carries_the_gateways_saving` there: a saving of 0.012345, no archive
    saving, the root's subtree usage). This transport copies those onto a benchmark-shaped replay
    outcome, because the stream is a plain model call and its result body is not a Candidate
    Result. The Report / `_submission` assertions therefore check the Client's PLUMBING from
    `_RunOutcome` onward, not a second decode.
    """

    def run(self, candidate: object, on_event: object) -> _RunOutcome:
        outcome = super().run(candidate, on_event)  # type: ignore[arg-type]
        return replace(
            outcome,
            root_usage=_recorded_usage(),
            cache_saved_cost_usd=_SAVED,
            cache_saved_cost_archive_usd=None,
        )


def _evaluate() -> sf.Report:
    with sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_engine),
        run_transport=_StreamedCacheTransport(),
    ) as client:
        return client.evaluate(REPLAY_URL4, progress=False)


def test_the_stream_is_the_run_the_engine_fixture_names() -> None:
    started = next(event for event in _events() if event["type"] == "ai.url4.started")

    assert started["data"]["url4"] == _URL4


def test_mismatched_root_url4_raises_instead_of_leaving_the_stream_without_an_outcome() -> None:
    state = _RunState("/openrouter/anthropic/claude-fable-5(ctx);retry=2!go")

    with pytest.raises(ExecutionError, match="run root was never identified.*URL4 mismatch"):
        for event in _events():
            state.accept(json.dumps(event))


def test_the_report_and_the_submission_carry_the_gateways_saving() -> None:
    report = _evaluate()
    (result,) = report.candidates

    assert result.cache_saved_cost_usd == _SAVED
    assert result.to_dict()["cache_saved_cost_usd"] == "0.012345"
    exported = json.loads(report.to_json())
    assert exported["candidates"][0]["cache_saved_cost_usd"] == "0.012345"

    payload = _submission(result)
    assert payload["cache_saved_cost_usd"] == "0.012345"
    # INVARIANT (OME-1251 D5): spend and saving travel apart; the board adds them, not the Client.
    assert Decimal(str(payload["run_cost_usd"])) == Decimal("0")
    assert payload["run_cost_status"] == "complete"
