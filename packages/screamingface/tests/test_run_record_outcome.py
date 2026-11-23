"""A Candidate's outcome from the Engine's record (E5 P2 spec §4.3, D9; plan C1).

FEATURE: a detached Run (OME-1837). STORY: as a researcher who reattaches from another machine,
each Candidate's result reads exactly as it would have had I watched it run.

INVARIANT: the recorded runs (`apps/screamingface-engine/tests/fixtures/candidate_runs`) are the
frames the Engine's fold reads and the record it gives. The outcomes below are what the Client's
own fold gave for those frames, so the Engine's record and the Client agree on every field.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from screamingface._core.ports import _RunResult
from screamingface._engine.run_record import candidate_outcome
from screamingface._engine.runs import CandidateRecord
from screamingface.errors import ExecutionError
from screamingface.report import Usage

RUNS = (
    Path(__file__).resolve().parents[3] / "apps/screamingface-engine/tests/fixtures/candidate_runs"
)
RUN_ID = "run_" + "a" * 32
TOPIC = "t" * 32
USAGE = Usage(
    input_tokens=1200,
    output_tokens=300,
    cache_read_tokens=0,
    cache_creation_tokens=0,
    reasoning_tokens=0,
    cost_usd=Decimal("0.00036"),
)
STARTED = datetime(2026, 11, 12, 9, 0, 0, tzinfo=UTC)
COMPLETED = datetime(2026, 11, 12, 9, 0, 4, tzinfo=UTC)


def _recorded(name: str) -> dict[str, Any]:
    return json.loads((RUNS / f"{name}.json").read_text())["record"]


def _candidate(state: str, record: dict[str, Any] | None, **fields: Any) -> CandidateRecord:
    values: dict[str, Any] = {
        "name": "alpha",
        "state": state,
        "attempt_id": TOPIC,
        "started_at": None,
        "finished_at": None,
        "cost_usd": None,
        "error_code": None,
        "index": 2,
        "record": record,
    }
    values.update(fields)
    return CandidateRecord(**values)


@pytest.mark.parametrize(
    ("name", "evidence"),
    [
        ("success", (0, None, None, None, None, None, None, ())),
        ("cache_hit", (2, 0, Decimal("0.00042"), Decimal("0.0011"), None, None, None, ())),
        ("capture", (0, None, None, None, "fc_7d1e", "partial", None, ("seal",))),
        ("large_result", (0, None, None, None, None, None, None, ())),
    ],
)
def test_a_recorded_run_gives_the_outcome_the_clients_fold_gave(
    name: str, evidence: tuple[object, ...]
) -> None:
    record = _recorded(name)

    outcome = candidate_outcome(RUN_ID, _candidate("succeeded", record))

    assert (outcome.run_id, outcome.started_at, outcome.completed_at) == (TOPIC, STARTED, COMPLETED)
    assert (outcome.root_usage, outcome.media_type, outcome.client_version) == (
        USAGE,
        "application/json",
        "1.4.0",
    )
    assert (
        outcome.cache_hits,
        outcome.cache_unpriced_hits,
        outcome.cache_saved_cost_usd,
        outcome.cache_saved_cost_archive_usd,
        outcome.frozen_copy_id,
        outcome.capture_status,
        outcome.capture_replay,
        outcome.capture_partial_reasons,
    ) == evidence
    assert outcome.trace_id == record["trace_id"]
    # WHY no body: the Client reads it from the result route, checked against this reference.
    assert (outcome.result_body, outcome.artifact) == (None, None)
    assert outcome.run_result == _RunResult(
        run_id=RUN_ID,
        index=2,
        size_bytes=record["result"]["size_bytes"],
        sha256=record["result"]["sha256"],
    )


def test_a_failed_run_raises_what_its_terminal_frame_said() -> None:
    record = _recorded("failure")

    with pytest.raises(ExecutionError) as raised:
        candidate_outcome(RUN_ID, _candidate("failed", record, error_code="provider_error"))

    assert (raised.value.code, raised.value.message, raised.value.permanent) == (
        "provider_error",
        "upstream überlastet (529)",
        False,
    )
    assert raised.value.details == record["error"]["details"]


@pytest.mark.parametrize(
    ("state", "error_code", "code"),
    [
        ("stopped", None, "stopped"),
        ("lost", "lost", "lost"),
        ("failed", "start_refused", "start_refused"),
    ],
)
def test_a_candidate_no_runner_reported_raises_with_its_state(
    state: str, error_code: str | None, code: str
) -> None:
    """A Candidate stopped before it ran, refused at start or lost has no record (§4.3)."""
    with pytest.raises(ExecutionError) as raised:
        candidate_outcome(RUN_ID, _candidate(state, None, error_code=error_code))

    assert raised.value.code == code


def test_a_succeeded_candidate_with_no_record_reads_as_its_result_lost() -> None:
    with pytest.raises(ExecutionError) as raised:
        candidate_outcome(RUN_ID, _candidate("succeeded", None))

    assert (raised.value.code, raised.value.permanent) == ("run_result_lost", True)


def test_a_succeeded_record_with_no_result_is_refused() -> None:
    record = {key: value for key, value in _recorded("success").items() if key != "result"}

    with pytest.raises(ExecutionError) as raised:
        candidate_outcome(RUN_ID, _candidate("succeeded", record))

    assert "without a root result" in raised.value.message


def test_a_client_version_that_is_not_one_is_left_out() -> None:
    record = {**_recorded("success"), "client_version": "not a version"}

    assert candidate_outcome(RUN_ID, _candidate("succeeded", record)).client_version is None


@pytest.mark.parametrize(
    "change",
    [
        {"started_at": "yesterday"},
        {"completed_at": None},
        {"cache_hits": "2"},
        {"cache_saved_cost_usd": 0.5},
        {"capture_status": "sealed"},
        {"usage": {"scope": "subtree"}},
        {"result": {"media_type": "application/json", "size_bytes": -1, "sha256": "0" * 64}},
        {"result": {"media_type": "application/json", "size_bytes": 1, "sha256": "zz"}},
    ],
    ids=["started", "completed", "hits", "saved", "capture", "usage", "size", "sha"],
)
def test_a_malformed_record_is_a_contract_error(change: dict[str, Any]) -> None:
    record = {**_recorded("success"), **change}

    with pytest.raises(ExecutionError) as raised:
        candidate_outcome(RUN_ID, _candidate("succeeded", record))

    assert raised.value.code == "engine_contract_error"


def test_a_candidate_that_has_not_ended_has_no_outcome() -> None:
    """#1878 review: an Engine contract error that says to upgrade, not a bare ValueError."""
    with pytest.raises(ExecutionError) as raised:
        candidate_outcome(RUN_ID, _candidate("scheduled", None))

    assert raised.value.code == "engine_contract_error"


def test_a_failure_whose_message_the_engine_cut_to_nothing_keeps_its_code() -> None:
    """The Engine trims an oversized record's error message, possibly to nothing; the
    Candidate still fails with its own code, as the Client's fold read it."""
    failure = _recorded("failure")
    record = {**failure, "error": {**failure["error"], "message": ""}}

    with pytest.raises(ExecutionError) as raised:
        candidate_outcome(RUN_ID, _candidate("failed", record, error_code="provider_error"))

    assert (raised.value.code, raised.value.message) == ("provider_error", "")


def test_a_failure_keeps_the_candidates_own_error_code_over_its_records() -> None:
    """#1878 review: the Candidate's error code is first-wins on the Engine; the record gives
    the message and details."""
    record = _recorded("failure")

    with pytest.raises(ExecutionError) as raised:
        candidate_outcome(RUN_ID, _candidate("failed", record, error_code="first_wins"))

    assert (raised.value.code, raised.value.message) == ("first_wins", "upstream überlastet (529)")
