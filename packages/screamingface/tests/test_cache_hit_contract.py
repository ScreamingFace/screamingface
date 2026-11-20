"""Hop 3 of the cross-stack cache-hit contract: the Client CONSUMES the Engine's record of a run.

FEATURE: what the cache saved, carried from the gateway to the board (spec
``docs/spec/2026-09-28-aigateway-cache-hit-metadata.md`` §3.2; OME-1155, OME-1326).
STORY: as a researcher whose run the gateway served from its cache, my Report and my board
submission show the saving the gateway recorded when it filled the cache — the same number, not
a re-derived one.

Hop 2 is the Engine's. Its
``apps/screamingface-engine/tests/unit/data/cache_hit_contract/run_events.json`` is the real
Engine's CloudEvents stream for a run whose only model call aigateway answered with its real hit
response, regenerated there (``test_cache_hit_contract.py``) from aigateway's own fixture, and the
Engine's fold reads the gateway's saving from it into the Candidate's record
(``test_candidate_record_evidence_rules.py`` there). The Client folds no frames: it reads that
record. So this hop reads the Engine's recorded cache-hit run,
``apps/screamingface-engine/tests/fixtures/candidate_runs/cache_hit.json``, whose ``record`` the
Engine's fold gives for its frames (``test_candidate_record.py`` there), through the Client's
record reader, and a change to the record the Engine writes reaches this file. Both are read by
repository path: the Engine is not a dependency of the Client.
"""

from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
from test_client_run import REPLAY_URL4, _engine, _ReplayTransport

import screamingface as sf
from screamingface._core.ports import _RunOutcome
from screamingface._engine.run_record import candidate_outcome
from screamingface._engine.runs import CandidateRecord
from screamingface._scoreboard.leaderboards import _submission

_REPO_ROOT = Path(__file__).resolve().parents[3]
RUN_EVENTS = (
    _REPO_ROOT / "apps/screamingface-engine/tests/unit/data/cache_hit_contract/run_events.json"
)
CACHE_HIT_RUN = (
    _REPO_ROOT / "apps/screamingface-engine/tests/fixtures/candidate_runs/cache_hit.json"
)

# The expression the Engine ran to produce the stream; the Engine's fold identifies the root by it.
_URL4 = "/openrouter/anthropic/claude-fable-5(ctx)!go"


def _events() -> list[dict[str, Any]]:
    return json.loads(RUN_EVENTS.read_text(encoding="utf-8"))


def _record() -> dict[str, Any]:
    return json.loads(CACHE_HIT_RUN.read_text(encoding="utf-8"))["record"]


def _recorded() -> _RunOutcome:
    """The Engine's record of the cache-hit run, as the Client's record reader reads it."""
    candidate = CandidateRecord(
        name="opus",
        state="succeeded",
        attempt_id="cache-hit-run",
        started_at=None,
        finished_at=None,
        cost_usd=None,
        error_code=None,
        record=_record(),
    )
    return candidate_outcome("run_" + "c" * 32, candidate)


class _RecordedCacheTransport(_ReplayTransport):
    """The replay Candidate, with the usage and the cache evidence of the Engine's record.

    WHAT IS TESTED WHERE: the record's result is a reference the Client fetches, and the recorded
    run is not a benchmark, so this transport copies what the Client's record reader decodes from
    the record (its usage, cache hits and both savings) onto a benchmark-shaped replay outcome. The
    Report / `_submission` assertions check that what the Engine recorded is what they carry.
    """

    def run(self, candidate: object, on_event: object) -> _RunOutcome:
        outcome = super().run(candidate, on_event)  # type: ignore[arg-type]
        recorded = _recorded()
        return replace(
            outcome,
            root_usage=recorded.root_usage,
            cache_hits=recorded.cache_hits,
            cache_unpriced_hits=recorded.cache_unpriced_hits,
            cache_saved_cost_usd=recorded.cache_saved_cost_usd,
            cache_saved_cost_archive_usd=recorded.cache_saved_cost_archive_usd,
        )


def _evaluate() -> sf.Report:
    with sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_engine),
        run_transport=_RecordedCacheTransport(),
    ) as client:
        return client.evaluate(REPLAY_URL4, progress=False)


def test_the_stream_is_the_run_the_engine_fixture_names() -> None:
    started = next(event for event in _events() if event["type"] == "ai.url4.started")

    assert started["data"]["url4"] == _URL4


def test_the_report_and_the_submission_carry_the_engines_recorded_saving() -> None:
    record = _record()
    report = _evaluate()
    (result,) = report.candidates

    assert result.cache_saved_cost_usd == Decimal(record["cache_saved_cost_usd"])
    assert result.cache_saved_cost_archive_usd == Decimal(record["cache_saved_cost_archive_usd"])
    assert result.to_dict()["cache_saved_cost_usd"] == record["cache_saved_cost_usd"]
    exported = json.loads(report.to_json())
    assert exported["candidates"][0]["cache_saved_cost_usd"] == record["cache_saved_cost_usd"]

    payload = _submission(result)
    assert payload["cache_saved_cost_usd"] == record["cache_saved_cost_usd"]
    assert payload["cache_saved_cost_archive_usd"] == record["cache_saved_cost_archive_usd"]
    # INVARIANT (OME-1251 D5): spend and saving travel apart; the board adds them, not the Client.
    spend = Decimal(record["usage"]["cost"]["total_usd"])
    assert Decimal(str(payload["run_cost_usd"])) == spend
    assert payload["run_cost_status"] == "complete"
