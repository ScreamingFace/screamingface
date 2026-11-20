"""The rules the Client's fold held, pinned on the Engine's fold (E5 P2 plan, CP1).

FEATURE: a detached Run (OME-1837). The Client used to fold a Candidate's frames into its outcome
(`screamingface/_engine/contract.py`, `_RunState`); it now reads the record this fold builds, so
the fold is where its rules live. This file holds root detection and the result;
`test_candidate_record_evidence_rules.py` holds cache evidence, the capture summary, client
provenance and span time clamping. Each test names the Client test it ports.

STORY: as a researcher, my Report says what the Client's own fold would have said for the same
run: the same root and the same result.

The input is the real Engine stream of the cache-hit contract (`data/cache_hit_contract/`), which
the Client's tests decoded, fed to the fold in publish order.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from screamingface_engine.candidate_record import CandidateRecordFold
from url4.streaming.codec import decode

RUN_EVENTS = Path(__file__).parent / "data" / "cache_hit_contract" / "run_events.json"
# The expression the Engine ran to produce the stream; the fold identifies the root by it.
_URL4 = "/openrouter/anthropic/claude-fable-5(ctx)!go"
_ROOT = "/trace/runs.cache-hit-contract/node/root"
_CHILD = "/trace/runs.cache-hit-contract/node/child"

type _Frames = list[dict[str, Any]]


def _events() -> _Frames:
    return json.loads(RUN_EVENTS.read_text(encoding="utf-8"))


def _record(frames: _Frames, url4: str = _URL4) -> dict[str, Any] | None:
    fold = CandidateRecordFold(url4, trace_id=None)
    for frame in frames:
        fold.observe(decode(json.dumps(frame).encode()))
    return fold.record()


def _succeeded(frames: _Frames) -> dict[str, Any]:
    record = _record(frames)
    assert record is not None, "the frames never produced a record"
    assert "error" not in record
    return record


def _frame(kind: str, data: dict[str, Any], *, source: str = _ROOT, at: int = 0) -> dict[str, Any]:
    """A frame of the stream's own shape, as the runner publishes it."""
    template = json.loads(json.dumps(_events()[0]))
    return {
        **template,
        "id": hashlib.sha256(f"{kind}{source}{at}{json.dumps(data)}".encode()).hexdigest()[:32],
        "source": source,
        "type": kind,
        "time": f"2026-09-28T00:01:{at:02d}Z",
        "data": data,
    }


def _started(url4: str = _URL4, *, source: str = _ROOT, at: int = 0) -> dict[str, Any]:
    return _frame("ai.url4.started", {"url4": url4}, source=source, at=at)


def _result(body: str = "ANSWER", *, source: str = _ROOT, media_type: str | None = None) -> Any:
    return _frame("ai.url4.result", {"body": body, "media_type": media_type}, source=source, at=2)


def _terminated(status: str = "succeeded", error: Any = None, *, source: str = _ROOT) -> Any:
    return _frame("ai.url4.terminated", {"status": status, "error": error}, source=source, at=3)


def _body_ref(body: str, media_type: str | None = None) -> dict[str, Any]:
    digest = hashlib.sha256(body.encode()).hexdigest()
    return {"media_type": media_type, "size_bytes": len(body.encode()), "sha256": digest}


# --- Root detection (test_engine_contract.py, test_candidate_root_lifecycle.py) ------------------


def test_the_roots_start_end_and_result_make_the_record() -> None:
    """Ports `test_state_decodes_public_events_and_root_lifecycle`."""
    record = _succeeded([_started(at=0), _result('{"schema":"result"}'), _terminated()])

    assert record["started_at"] == "2026-09-28T00:01:00+00:00"
    assert record["completed_at"] == "2026-09-28T00:01:03+00:00"
    assert record["result"] == _body_ref('{"schema":"result"}')


@pytest.mark.parametrize("status", ["succeeded", "failed", "stopped", "timed_out"])
def test_an_end_with_no_root_naming_the_url4_has_no_record(status: str) -> None:
    """Ports `test_termination_without_an_identified_root_raises`, and the early child of
    `test_decoded_child_lifecycle_does_not_finish_candidate`: no outcome is built from a root
    that was never identified (the Client then reads the Candidate as lost)."""
    frames = [_started("(@)!'different'", source=_CHILD), _terminated(status, source=_CHILD)]

    assert _record(frames) is None


def test_a_mismatched_url4_gives_the_real_stream_no_record() -> None:
    """Ports `test_mismatched_root_url4_raises_instead_of_leaving_the_stream_without_an_outcome`."""
    assert _record(_events(), "/openrouter/anthropic/claude-fable-5(ctx);retry=2!go") is None


@pytest.mark.parametrize("same_expression", [False, True])
def test_a_childs_lifecycle_neither_ends_the_candidate_nor_gives_its_result(
    same_expression: bool,
) -> None:
    """Ports `test_decoded_child_lifecycle_does_not_finish_candidate`,
    `test_equal_looking_child_started_event_does_not_replace_root_identity` and the child result
    of `test_state_decodes_log_span_and_non_root_lifecycle`."""
    child = [
        _started(),
        _started(_URL4 if same_expression else "()!'child'", source=_CHILD, at=1),
        _result("child", source=_CHILD),
        _terminated(source=_CHILD),
    ]

    assert _record(child) is None
    record = _succeeded([*child, _result("root"), _terminated()])
    assert record["result"] == _body_ref("root")


def test_a_second_root_started_frame_leaves_the_first_as_the_roots_start() -> None:
    """Ports `test_state_rejects_duplicate_root_events_and_consumes_protocol_nacks` (started).
    The Client stopped the Candidate on it; the owner accepted the fold's reading (2026-11-20):
    the first started frame naming the url4 is the root's, and a later one changes nothing."""
    record = _succeeded([_started(at=0), _started(at=1), _result(), _terminated()])

    assert record["started_at"] == "2026-09-28T00:01:00+00:00"
    assert record["result"] == _body_ref("ANSWER")


def test_a_second_root_result_leaves_the_first_as_the_result() -> None:
    """Ports `test_state_rejects_duplicate_root_events_and_consumes_protocol_nacks` (result).
    The Client stopped the Candidate on it; the owner accepted the fold's reading (2026-11-20)."""
    first = _result("first")
    second = {**_result("second"), "id": "e" * 32}
    record = _succeeded([_started(), first, second, _terminated()])

    assert record["result"] == _body_ref("first")


def test_a_root_that_succeeds_without_a_result_records_none() -> None:
    """Ports `test_succeeded_root_requires_exactly_one_result`: the record holds no result, which
    the Client reads as `succeeded without a root result`."""
    assert "result" not in _succeeded([_started(), _terminated()])


def test_a_failed_root_records_its_structured_error() -> None:
    """Ports `test_failed_root_becomes_a_structured_execution_error`."""
    error = {"code": "gateway_timeout", "message": "The model timed out.", "permanent": False}
    record = _record([_started(), _terminated("failed", error)])

    assert record is not None
    assert record["error"]["code"] == "gateway_timeout"
    assert record["error"]["message"] == "The model timed out."
    assert record["error"]["permanent"] is False
    assert record["error"]["details"]["error"] == error


def test_a_root_ended_with_no_error_records_its_status_as_the_code() -> None:
    """The Client's rule for a terminal frame with no error: the status names the failure."""
    record = _record([_started(), _terminated("timed_out")])

    assert record is not None
    assert record["error"]["code"] == "timed_out"
    assert record["error"]["message"] == "SF Engine Run timed_out"
    assert record["error"]["permanent"] is None


def test_a_result_keeps_its_absent_media_type_and_its_exact_body() -> None:
    """Ports `test_root_result_preserves_optional_media_type_without_interpreting_the_body`."""
    record = _succeeded([_started(), _result("[mock] done"), _terminated()])

    assert record["result"] == _body_ref("[mock] done")


def test_an_artifact_result_records_its_tickets_size_and_checksum() -> None:
    """Ports `test_state_decodes_an_artifact_result`: the record names the spilled result, never
    a guessed body."""
    sha = "9f" * 32
    artifact = {
        "body": None,
        "media_type": None,
        "artifact": {"id": sha, "size_bytes": 11, "sha256": sha},
    }
    record = _succeeded([_started(), _frame("ai.url4.result", artifact), _terminated()])

    assert record["result"] == {"media_type": None, "size_bytes": 11, "sha256": sha}


@pytest.mark.parametrize(
    "data",
    [
        {"body": None, "artifact": {"id": "../etc/passwd", "size_bytes": 11, "sha256": "9f" * 32}},
        {"body": None, "artifact": {"id": "9f" * 32, "size_bytes": 11}},
        {"body": None, "artifact": "not a mapping"},
        {"body": None, "media_type": None},
        {"body": "x", "media_type": 123},
        {"body": "x", "artifact": {"id": "9f" * 32, "size_bytes": 11, "sha256": "9f" * 32}},
    ],
)
def test_a_result_the_client_refused_is_no_frame_at_all(data: dict[str, Any]) -> None:
    """Ports `test_state_rejects_malformed_artifact_references`,
    `test_state_rejects_a_result_with_neither_body_nor_artifact` and the result case of
    `test_state_rejects_invalid_event_payloads`: the runner cannot publish such a frame, so the
    fold never records one."""
    with pytest.raises(ValueError, match="validation error"):
        decode(json.dumps(_frame("ai.url4.result", data)).encode())


def test_the_usage_is_the_roots_subtree_usage_only() -> None:
    """The Client's rule: the root's `subtree` usage is the run's; a `self` one and a child's are
    not."""
    frames = _events()
    subtree = next(
        f for f in frames if f["type"] == "ai.url4.cost.usage" and f["data"]["scope"] == "subtree"
    )
    child = json.loads(json.dumps(subtree))
    child["source"], child["id"] = _CHILD, "c" * 32
    child["data"]["cost"]["total_usd"] = "9"
    frames.insert(-1, child)

    assert _succeeded(frames)["usage"] == subtree["data"]
