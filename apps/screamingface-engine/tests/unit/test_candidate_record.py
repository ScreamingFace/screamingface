"""E5 P2 spec §4.3: a Candidate's record, folded from the frames its run published.

FEATURE: a detached Run (OME-1837). STORY: as a researcher reattaching from another machine, I
get the same Report the machine that started the Run would have built.

INVARIANT: the record equals what the Client's fold gives for the same frames. Both are tested
against `tests/fixtures/candidate_runs/`, whose `record` the Client's `_RunState` produced.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from screamingface_engine.candidate_record import (
    MAX_RECORD_BYTES,
    CandidateRecordFold,
    fit_record,
)
from url4.streaming.codec import decode

RUNS = Path(__file__).parents[1] / "fixtures" / "candidate_runs"


def _run(name: str) -> dict[str, Any]:
    return json.loads((RUNS / f"{name}.json").read_text())


def _fold(run: dict[str, Any], frames: list[dict[str, Any]] | None = None) -> CandidateRecordFold:
    fold = CandidateRecordFold(run["url4"], trace_id=run["trace_id"])
    for frame in run["frames"] if frames is None else frames:
        fold.observe(decode(json.dumps(frame).encode()))
    return fold


def _size(record: dict[str, Any]) -> int:
    return len(json.dumps(record, separators=(",", ":")).encode())


@pytest.mark.parametrize("name", ["success", "failure", "cache_hit", "capture", "large_result"])
def test_the_record_is_the_clients_for_the_same_run(name: str) -> None:
    run = _run(name)

    assert _fold(run).record() == run["record"]


def test_a_run_whose_root_never_ended_has_no_record() -> None:
    """§4.3: a Candidate has no record when no runner reported one."""
    run = _run("success")
    frames = [frame for frame in run["frames"] if frame["type"] != "ai.url4.terminated"]

    assert _fold(run, frames).record() is None


def test_an_end_with_no_started_root_has_no_record() -> None:
    """Without a started root no frame is the root's, so no end is the run's own."""
    run = _run("failure")
    frames = [frame for frame in run["frames"] if frame["type"] != "ai.url4.started"]

    assert _fold(run, frames).record() is None


def test_two_client_versions_on_the_root_record_none() -> None:
    """The Client's rule: conflicting provenance names no caller."""
    run = _run("success")
    frames = list(run["frames"])
    second = json.loads(json.dumps(frames[1]))
    second["id"] = "f" * 32
    second["data"]["attributes"]["screamingface.client.version"] = "1.5.0"
    frames.insert(2, second)

    record = _fold(run, frames).record()

    assert record is not None
    assert record["client_version"] is None


def test_a_child_nodes_frames_never_stand_in_for_the_roots() -> None:
    run = _run("success")
    frames = json.loads(json.dumps(run["frames"]))
    child = next(f for f in frames if f["type"] == "ai.url4.started" and f is not frames[0])
    log = json.loads(json.dumps(frames[1]))
    log["source"] = child["source"]
    log["data"]["attributes"]["screamingface.client.version"] = "9.9.9"
    frames.append(log)

    record = _fold(run, frames).record()

    assert record is not None
    assert record["client_version"] == "1.4.0"


def test_a_record_with_a_huge_error_text_is_cut_to_fit_and_says_so() -> None:
    run = _run("failure")
    frames = json.loads(json.dumps(run["frames"]))
    frames[-1]["data"]["error"]["message"] = "ü" * 100 * 1024

    record = _fold(run, frames).record()

    assert record is not None
    assert _size(record) <= MAX_RECORD_BYTES
    assert record["error"]["message"].startswith("üüü")
    assert record["error"]["details"] is None
    assert record["cut"] == ["error.details", "error.message"]
    assert record["error"]["code"] == "provider_error"


def test_a_record_that_fits_is_left_whole() -> None:
    record = _run("failure")["record"]

    assert fit_record(json.loads(json.dumps(record))) == record


def test_many_partial_reasons_are_cut_to_fit() -> None:
    record = _run("capture")["record"]
    record["capture_partial_reasons"] = [f"reason-{n:06d}" for n in range(10_000)]

    fitted = fit_record(record)

    assert fitted is not None
    assert _size(fitted) <= MAX_RECORD_BYTES
    assert fitted["capture_partial_reasons"][0] == "reason-000000"
    assert fitted["cut"] == ["capture_partial_reasons"]


def test_a_record_too_large_after_every_cut_is_dropped() -> None:
    """§4.3: the outcome is then reported without it, so state and cost are never lost."""
    record = _run("success")["record"]
    record["usage"] = {"huge": "x" * MAX_RECORD_BYTES}

    assert fit_record(record) is None


def test_the_root_is_the_started_frame_naming_the_runs_url4_not_the_first() -> None:
    """The Client's rule: a child that starts first is not the root."""
    run = _run("success")
    frames = list(run["frames"])
    child = next(f for f in frames if f["type"] == "ai.url4.started" and f is not frames[0])
    frames.remove(child)
    frames.insert(0, child)

    assert _fold(run, frames).record() == run["record"]
