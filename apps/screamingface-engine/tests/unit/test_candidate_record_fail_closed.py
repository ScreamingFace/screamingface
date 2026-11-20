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

AIDEV-NOTE: these replay a recorded success, its `succeeded` terminal frame included, so they read
the fold's rule through `SettlementWatch`'s backstop. A real run is failed by its executor before
its terminal frame: `test_run_summary_refused_before_terminal.py` (review round 1).
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
from collections.abc import AsyncIterator, Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from test_inprocess_outcomes import _published, _subtree

from screamingface_engine.adapters.inprocess import InProcessJobRunner
from screamingface_engine.adapters.memory import (
    InMemoryCandidateOutcomeStream,
    InMemoryEventStream,
)
from screamingface_engine.candidate_outcomes import CandidateOutcome
from screamingface_engine.candidate_record import CandidateRecordFold
from screamingface_engine.run_evidence import SettlementWatch, settlement_of
from url4.streaming.codec import decode
from url4.streaming.interfaces import Completed, ExecStep, Executor, TraceContext
from url4.streaming.protocol import LogData, ResultData, TerminatedEvent

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


# --- A summary amount is the run's own fixed-point string (review round 1) ------------------------


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("1E+999999999", id="huge-exponent"),
        pytest.param("1E+3", id="exponent"),
        pytest.param("1e3", id="lower-exponent"),
        pytest.param("1_000", id="underscore"),
        pytest.param(" 1 ", id="spaces"),
        pytest.param("+1", id="sign"),
        pytest.param("1.", id="bare-point"),
        pytest.param(".5", id="no-integer-part"),
        pytest.param("１", id="full-width-digit"),
    ],
)
async def test_an_amount_the_run_never_writes_is_refused(value: str) -> None:
    """The run writes each total with `format(total, "f")`: ASCII digits, at most one point
    between them. `Decimal` reads far more, and an exponent it reads `_amount` writes out in
    fixed point (`1E+999999999` is about 1 GB)."""
    _assert_refused(await _settle(_stream({_SAVED: value})), _SAVED)


# --- Only the run's own closing log is its summary (review round 2) -------------------------------


def _summary_frame(events: list[dict[str, Any]]) -> dict[str, Any]:
    return next(
        event
        for event in events
        if event["type"] == "ai.url4.log" and "cache.hits" in event["data"]["attributes"]
    )


@pytest.mark.parametrize("under", ["a-nodes-span", "a-tracestate"])
async def test_a_log_that_is_not_the_runs_own_is_no_run_summary(under: str) -> None:
    """Finding 1: url4 stamps every frame of a run with the root's `source`, so a node's
    `ctx.log` carrying `cache.hits` used to pass for the run summary. The run's closing log is
    published with no span, so under the root traceparent with no tracestate; a node's log is
    published under its own span's."""
    events = _stream({"cache.hits": -1})
    frame = _summary_frame(events)
    if under == "a-nodes-span":
        frame["traceparent"] = next(e["traceparent"] for e in events if e["type"] == "ai.url4.span")
    else:
        frame["tracestate"] = "url4.parent=0000000000000005"

    outcome = await _settle(events)

    assert (outcome.status, outcome.error_code) == ("succeeded", None)
    assert outcome.record is not None
    # The summary was not read: no unpriced count, which only a summary states.
    assert outcome.record["cache_unpriced_hits"] is None


@pytest.mark.parametrize(
    ("first", "second"),
    [
        pytest.param({}, {"cache.hits": -1}, id="well-formed-then-malformed"),
        pytest.param({"cache.hits": -1}, {}, id="malformed-then-well-formed"),
    ],
)
async def test_one_malformed_closing_summary_refuses_the_run_for_good(
    first: dict[str, object], second: dict[str, object]
) -> None:
    """Round 1 fix 5, moved here in round 2: a run states one closing summary, so two are a
    fold rule. One malformed refuses the run whatever comes before or after it."""
    events = _events()
    frame = _summary_frame(events)
    again = copy.deepcopy(frame)
    again["id"] = "f" * 32
    frame["data"]["attributes"].update(first)
    again["data"]["attributes"].update(second)
    events.insert(events.index(frame) + 1, again)

    _assert_refused(await _settle(events), "cache.hits")


# --- Every reader agrees on the backstop path (review round 2) ------------------------------------


class _Unbound(Executor):
    """An executor that does not read `bound_refusal`: it states a malformed closing summary (no
    span, as `executor._closing_logs` does) and succeeds all the same."""

    async def execute(
        self, url4: str, *, trace: TraceContext | None = None
    ) -> AsyncIterator[ExecStep]:
        yield LogData.at("INFO", "cache summary", {"cache.hits": -1})
        yield Completed(result=ResultData(body="ANSWER"), subtree_cost=_subtree())


async def test_a_success_its_record_refused_reads_failed_to_every_reader(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Finding 4: the outcome said `failed`, but `outcome_of` (the `run terminated` line) and the
    runner's verdict (`status`) still read the `succeeded` frame."""
    caplog.set_level(logging.INFO)
    outcomes = InMemoryCandidateOutcomeStream()
    local = InProcessJobRunner(InMemoryEventStream(), lambda env: _Unbound(), outcomes=outcomes)

    await local.schedule(TOPIC, "q", 60, result_prefix=f"runs/run_{'a' * 32}/0")
    outcome = (await _published(outcomes)).outcome

    frame = await local.last_frame(TOPIC)
    assert isinstance(frame, TerminatedEvent)
    assert frame.data.status == "succeeded"
    _assert_refused(outcome, "cache.hits")
    assert await local.status(TOPIC) == "failed"
    (terminated,) = [
        record.getMessage()
        for record in caplog.records
        if record.getMessage().startswith("run terminated")
    ]
    message = "SF Engine run summary cache.hits is invalid"
    assert f"outcome=failed error={CODE}: {message}" in terminated
