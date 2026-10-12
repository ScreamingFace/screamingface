"""E14 F-B3 review round 2026-10-12 — the capture tally's outcome rules (design §5.2, Q23, Q27).

FEATURE: OME-1307. No outcome of a capture run is forgiven: an error that a later call of the same
request made up for still leaves the run partial (Q27). A local capture is partial with reason
`local` (Q23), and the seal states the engine version (Q28).
STORY: as a researcher who reproduces a score, a run is `complete` only when every call has an
entry at its key, so a replay can never miss one.

A separate module (append-only gate).
"""

from __future__ import annotations

from screamingface_engine.capture_outcomes import CaptureOutcome, CaptureTally

_COPY = "6f1c2b0e-4c0a-4d7e-9a53-2f4f0f3a9b11"


# ── TDD 8: an unstored error is no longer forgiven ─────────────────────────────────────────


def test_an_unstored_error_is_no_longer_forgiven() -> None:
    tally = CaptureTally(mode="capture", frozen_copy_id=_COPY, sealed=True)
    tally.outcomes.extend(
        [CaptureOutcome("chat", "error", "a"), CaptureOutcome("chat", "stored", "a")]
    )

    assert tally.status() == "partial"
    assert tally.attributes()["capture.partial.error"] == 1
