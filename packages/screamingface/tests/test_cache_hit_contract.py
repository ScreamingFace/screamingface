"""Hop 3 of the cross-stack cache-hit contract: the Client CONSUMES the Engine's run stream.

FEATURE: what the cache saved, carried from the gateway to the board (spec
``docs/spec/2026-09-28-aigateway-cache-hit-metadata.md`` §3.2; OME-1155, OME-1326).
STORY: as a researcher whose run the gateway served from its cache, my Report and my board
submission show the saving the gateway recorded when it filled the cache — the same number, not
a re-derived one.

The input ``apps/screamingface-engine/tests/unit/data/cache_hit_contract/run_events.json`` is the
real Engine's CloudEvents stream for a run whose only model call aigateway answered with its real
hit response. The Engine regenerates it (``test_cache_hit_contract.py`` there) from aigateway's
own fixture, so a change anywhere upstream reaches this file. It is read by repository path: the
Engine is not a dependency of the Client.
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
from screamingface._engine.contract import _RunState
from screamingface._scoreboard.leaderboards import _submission
from screamingface.errors import ExecutionError

_REPO_ROOT = Path(__file__).resolve().parents[3]
RUN_EVENTS = (
    _REPO_ROOT / "apps/screamingface-engine/tests/unit/data/cache_hit_contract/run_events.json"
)
GATEWAY_HIT = _REPO_ROOT / "apps/aigateway/tests/fixtures/cache_hit_contract/openrouter_hit.json"

# The expression the Engine ran to produce the stream. `_RunState` identifies the root by it.
_URL4 = "/openrouter/anthropic/claude-fable-5(ctx)!go"
_SAVED = Decimal("0.012345")


def _events() -> list[dict[str, Any]]:
    return json.loads(RUN_EVENTS.read_text(encoding="utf-8"))


def _decoded() -> _RunOutcome:
    """Feed the stream, frame by frame as raw wire text, through the Client's own decoder."""
    state = _RunState(_URL4)
    outcome = None
    for event in _events():
        accepted = state.accept(json.dumps(event))
        if accepted.outcome is not None:
            outcome = accepted.outcome
    assert outcome is not None, "the stream never produced a root outcome"
    return outcome


class _StreamedCacheTransport(_ReplayTransport):
    """The replay Candidate, with three fields copied from the decoded stream onto it.

    WHAT IS TESTED WHERE: the hop under test is `_RunState` decoding the Engine's real stream
    (`_decoded`, asserted directly above the Report test). This transport then copies
    `root_usage`, `cache_saved_cost_usd` and `cache_saved_cost_archive_usd` from that decoded
    outcome onto a benchmark-shaped replay outcome, because the stream is a plain model call and
    its result body is not a Candidate Result. The Report / `_submission` assertions therefore
    check the Client's PLUMBING from `_RunOutcome` onward, not a second decode.
    """

    def run(self, candidate: object, on_event: object) -> _RunOutcome:
        outcome = super().run(candidate, on_event)  # type: ignore[arg-type]
        streamed = _decoded()
        return replace(
            outcome,
            root_usage=streamed.root_usage,
            cache_saved_cost_usd=streamed.cache_saved_cost_usd,
            cache_saved_cost_archive_usd=streamed.cache_saved_cost_archive_usd,
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


def test_the_decoder_recovers_the_gateways_saving_from_the_stream() -> None:
    outcome = _decoded()

    assert outcome.cache_saved_cost_usd == _SAVED
    # A hit that no provenance other than `reported` priced leaves the archive total ABSENT.
    assert outcome.cache_saved_cost_archive_usd is None
    assert outcome.root_usage is not None
    # INVARIANT (PRD I1): the hit's own spend is zero; the saving never enters it.
    assert outcome.root_usage.cost_usd == Decimal("0")


def test_the_saving_is_the_one_the_gateway_recorded_at_fill_time() -> None:
    # Ties the last hop to the first one: the number the Client carries is the gateway's own,
    # converted 1:1 from `openrouter_credits`, with no hop re-deriving it.
    reference = json.loads(GATEWAY_HIT.read_text(encoding="utf-8"))["body"]["_aigw"][
        "usage_accounting"
    ]["cache"]["reference"]

    assert reference["direct_cost"]["unit"] == "openrouter_credits"
    assert Decimal(reference["direct_cost"]["amount"]) == _decoded().cache_saved_cost_usd


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
