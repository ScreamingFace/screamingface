"""E14 F-B3 review round 2026-10-12 — the capture tally's outcome rules (design §5.2, Q23, Q27).

FEATURE: OME-1307. No outcome of a capture run is forgiven: an error that a later call of the same
request made up for still leaves the run partial (Q27). A local capture is partial with reason
`local` (Q23), and the seal states the engine version (Q28).
STORY: as a researcher who reproduces a score, a run is `complete` only when every call has an
entry at its key, so a replay can never miss one.

A separate module (append-only gate).
"""

from __future__ import annotations

from screamingface_engine import job_env
from screamingface_engine.capture_outcomes import CaptureOutcome, CaptureTally
from screamingface_engine.request_scope import RequestScope, request_scope
from screamingface_engine.runner.executor import _bind_frozen_copy_mode
from screamingface_engine.runner.main import request_scope_from_env

_COPY = "6f1c2b0e-4c0a-4d7e-9a53-2f4f0f3a9b11"


# ── TDD 8: an unstored error is no longer forgiven ─────────────────────────────────────────


def test_an_unstored_error_is_no_longer_forgiven() -> None:
    tally = CaptureTally(mode="capture", frozen_copy_id=_COPY, sealed=True)
    tally.outcomes.extend(
        [CaptureOutcome("chat", "error", "a"), CaptureOutcome("chat", "stored", "a")]
    )

    assert tally.status() == "partial"
    assert tally.attributes()["capture.partial.error"] == 1


# ── TDD 7: a local capture is partial with reason `local`; a hosted capture is unchanged ───


def test_local_runtime_capture_is_partial_with_reason_local() -> None:
    tally = CaptureTally(mode="capture", frozen_copy_id=_COPY, sealed=True, local=True)
    tally.outcomes.append(CaptureOutcome("chat", "stored", "a"))

    assert tally.status() == "partial"
    assert tally.attributes()["capture.partial.local"] == 1


def test_hosted_capture_is_unchanged() -> None:
    tally = CaptureTally(mode="capture", frozen_copy_id=_COPY, sealed=True)
    tally.outcomes.append(CaptureOutcome("chat", "stored", "a"))

    assert tally.status() == "complete"
    assert tally.attributes() == {
        "capture.frozen_copy_id": _COPY,
        "capture.status": "complete",
    }


def test_the_local_marker_travels_from_the_job_env_to_the_scope() -> None:
    local = {job_env.CAPTURE: "1", job_env.LOCAL_RUNTIME: "1"}
    hosted = {job_env.CAPTURE: "1"}

    assert request_scope_from_env(local).local_runtime is True
    assert request_scope_from_env(hosted).local_runtime is False


def test_the_executor_binds_the_local_marker_to_the_tally() -> None:
    tally = CaptureTally()
    with request_scope(RequestScope(origin="run", capture=True, local_runtime=True)):
        _bind_frozen_copy_mode(tally)

    assert tally.mode == "capture"
    assert tally.local is True
