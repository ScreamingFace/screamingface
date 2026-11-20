"""A Candidate whose run summary has a malformed cost, cache or capture figure fails (OME-1988).

FEATURE: a detached Run (OME-1837). The Client reads the record the Engine folds for each Candidate
and no longer folds the frames itself (E5 P2 spec D9, §4.3), so the Client's fail-closed rules for
the run summary (OME-1463, OME-1307) are the Engine's to apply now.
STORY: as a reader of the leaderboard, a cost or a frozen copy that the run summary cannot vouch
for is never published as exact: the Candidate fails with `run_summary_invalid` instead.

INVARIANT: each ported case is a case of the Client's `_RunState` tests
(`origin/OME-1943-e5-p2-client`, `packages/screamingface/tests/`), with the same input on the same
real Engine stream (`data/cache_hit_contract/run_events.json`) and the same fail-closed outcome.
A refused success both settles the Candidate `failed` and leaves the result out of its record: the
Client reads a succeeded Candidate's record and ignores an `error` on it.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from screamingface_engine.adapters.memory import InMemoryEventStream
from screamingface_engine.candidate_outcomes import CandidateOutcome
from screamingface_engine.candidate_record import CandidateRecordFold
from screamingface_engine.run_evidence import SettlementWatch, settlement_of
from url4.streaming.codec import decode

pytestmark = pytest.mark.asyncio

RUN_EVENTS = Path(__file__).parent / "data" / "cache_hit_contract" / "run_events.json"
# The expression the Engine ran to produce the stream; the fold finds the root by it.
URL4 = "/openrouter/anthropic/claude-fable-5(ctx)!go"
TOPIC = "runs.cache-hit-contract"
# WHY the literal: the code is what the registry stores and the Client raises with.
CODE = "run_summary_invalid"

_UNPRICED = "cache.saved_cost.unpriced_hits"
_SAVED = "cache.saved_cost_usd"
_PARTIAL_LOCAL = "capture.partial.local"


def _events() -> list[dict[str, Any]]:
    return json.loads(RUN_EVENTS.read_text(encoding="utf-8"))


def _summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    """The run summary's attributes: the root log that carries `cache.hits`."""
    return next(
        event["data"]["attributes"]
        for event in events
        if event["type"] == "ai.url4.log" and "cache.hits" in event["data"]["attributes"]
    )


def _stream(attributes: Mapping[str, object]) -> list[dict[str, Any]]:
    """The real stream, with ``attributes`` set on its run summary (the Client tests' setup)."""
    events = _events()
    _summary(events).update(attributes)
    return events


async def _nothing() -> object:
    return None


async def _settle(events: list[dict[str, Any]]) -> CandidateOutcome:
    """The Candidate's outcome as its runner reports it: every frame published through the run's
    `SettlementWatch`, which folds the record, then `settlement_of`."""
    watch = SettlementWatch(InMemoryEventStream(), record=CandidateRecordFold(URL4, trace_id=None))
    for event in events:
        await watch.publish(TOPIC, decode(json.dumps(event).encode()))
    task = asyncio.ensure_future(_nothing())
    await task
    return settlement_of(watch, task, cost_usd=Decimal("0"))


def _assert_refused(outcome: CandidateOutcome, attribute: str) -> None:
    assert (outcome.status, outcome.error_code) == ("failed", CODE)
    record = outcome.record
    assert record is not None
    assert "result" not in record
    assert record["error"] == {
        "code": CODE,
        "message": f"SF Engine run summary {attribute} is invalid",
        "permanent": True,
        "details": None,
    }


# --- The control ---------------------------------------------------------------------------------


async def test_the_real_stream_succeeds_with_its_result_and_its_figures() -> None:
    """The harness alone fails nothing: the unchanged stream is the success the cases corrupt."""
    outcome = await _settle(_events())

    assert (outcome.status, outcome.error_code) == ("succeeded", None)
    record = outcome.record
    assert record is not None
    assert "error" not in record
    assert record["result"]["size_bytes"] == len(b"ANSWER")
    assert record["cache_hits"] == 1
    assert record["cache_unpriced_hits"] == 0
    assert record["cache_saved_cost_usd"] == "0.012345"


# --- Ported from the Client's `_RunState` tests ---------------------------------------------------


async def test_a_malformed_summary_count_is_refused() -> None:
    """`test_cached_run_not_complete.py::test_a_malformed_summary_count_is_refused`."""
    _assert_refused(await _settle(_stream({"cache.hits": -1})), "cache.hits")


@pytest.mark.parametrize("value", [-1, True, 1.5, "0"])
async def test_a_malformed_unpriced_count_is_refused(value: object) -> None:
    """`test_archive_cost.py::test_a_malformed_unpriced_count_is_refused`."""
    _assert_refused(await _settle(_stream({_UNPRICED: value})), _UNPRICED)


@pytest.mark.parametrize("value", ["-1", "NaN", "abc", 0.5])
async def test_a_malformed_summary_amount_is_refused(value: object) -> None:
    """`test_archive_cost.py::test_a_malformed_summary_amount_is_refused`."""
    _assert_refused(await _settle(_stream({_SAVED: value})), _SAVED)


@pytest.mark.parametrize("count", [-1, True, "one", 1.5])
async def test_a_malformed_partial_count_fails_closed(count: object) -> None:
    """`test_capture_summary.py::test_a_malformed_partial_count_fails_closed`."""
    attributes = {"capture.status": "partial", _PARTIAL_LOCAL: count}

    _assert_refused(await _settle(_stream(attributes)), _PARTIAL_LOCAL)


@pytest.mark.parametrize(
    ("attributes", "attribute"),
    [
        ({"capture.status": "maybe"}, "capture.status"),
        ({"capture.status": True}, "capture.status"),
        ({"capture.status": "complete", "capture.frozen_copy_id": 7}, "capture.frozen_copy_id"),
        ({"capture.status": "complete", "capture.replay": 7}, "capture.replay"),
    ],
)
async def test_a_malformed_capture_attribute_stops_the_run(
    attributes: dict[str, object], attribute: str
) -> None:
    """`test_capture_summary.py::test_a_malformed_capture_attribute_stops_the_run`."""
    _assert_refused(await _settle(_stream(attributes)), attribute)


# --- The rule's edges -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("attributes", "attribute"),
    [
        ({"cache.saved_cost.reported_hits": -1}, "cache.saved_cost.reported_hits"),
        ({"cache.saved_cost.archive_hits": "0"}, "cache.saved_cost.archive_hits"),
        ({"cache.saved_cost_archive_usd": "Infinity"}, "cache.saved_cost_archive_usd"),
        ({"capture.status": "complete", "capture.frozen_copy_id": ""}, "capture.frozen_copy_id"),
        ({"capture.replay": None}, "capture.replay"),
    ],
)
async def test_the_same_rule_holds_for_the_summarys_other_figures(
    attributes: dict[str, object], attribute: str
) -> None:
    """The Client's `_CacheSummary.parse` read every figure of one kind with one parser; its tests
    named one key of each kind."""
    _assert_refused(await _settle(_stream(attributes)), attribute)


async def test_a_root_log_without_cache_hits_is_no_run_summary() -> None:
    """The Client's rule: only the root log carrying `cache.hits` is the summary. A failed capture
    run's state line carries none (`executor._failed_run_logs`), and nothing on it is refused."""
    events = _events()
    summary = _summary(events)
    for key in [key for key in summary if key.startswith("cache.")]:
        del summary[key]
    summary["capture.status"] = "maybe"

    outcome = await _settle(events)

    assert (outcome.status, outcome.error_code) == ("succeeded", None)
    assert outcome.record is not None
    assert outcome.record["capture_status"] is None


async def test_a_run_that_failed_keeps_its_own_error() -> None:
    """Only a success is refused: a run that failed already says why, in its terminal frame."""
    events = [event for event in _stream({"cache.hits": -1}) if event["type"] != "ai.url4.result"]
    events[-1]["data"] = {
        "status": "failed",
        "error": {"code": "provider_error", "message": "upstream 500", "permanent": False},
    }

    outcome = await _settle(events)

    assert (outcome.status, outcome.error_code) == ("failed", "provider_error")
    assert outcome.record is not None
    assert outcome.record["error"]["code"] == "provider_error"


async def test_the_candidate_fails_even_when_its_record_is_too_large_to_report() -> None:
    """§4.3: a record still over 48 KiB after every cut is reported without. The refusal is the
    fold's own verdict, not a field of the record, so the Candidate fails all the same."""
    events = _stream({"cache.hits": -1})
    usage = next(
        event
        for event in events
        if event["type"] == "ai.url4.cost.usage" and event["data"]["scope"] == "subtree"
    )
    usage["data"]["gen_ai.response.model"] = "m" * 64 * 1024

    outcome = await _settle(events)

    assert (outcome.status, outcome.error_code) == ("failed", CODE)
    assert outcome.record is None
