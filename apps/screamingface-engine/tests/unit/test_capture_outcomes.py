"""E14 F-B3 — the run-scoped capture tally and the `capture.status` rule (design §5.2 item 5).

FEATURE: OME-1307 — a capture run is `complete` only when the copy opened, sealed, and every chat
call and tool result is `stored`. D1: a cancelled or crashed call is an `error`. D2: an `error` that
a later call of the same request replaced is forgiven; nothing else is.
STORY: as a researcher who submits a score, the run's summary tells me whether it can be replayed.

A separate module (append-only gate).
"""

from __future__ import annotations

import pytest

from screamingface_engine.capture_outcomes import (
    CaptureOutcome,
    CaptureTally,
    Lane,
    Status,
    capture_outcomes,
    current_capture_tally,
    record_capture_outcome,
)

_COPY = "6f1c2b0e-4c0a-4d7e-9a53-2f4f0f3a9b11"


def _tally(
    *outcomes: tuple[Lane, Status, str | None],
    open_failed: bool = False,
    seal_failed: bool = False,
) -> CaptureTally:
    tally = CaptureTally(
        mode="capture",
        frozen_copy_id=None if open_failed else _COPY,
        open_failed=open_failed,
        seal_failed=seal_failed,
    )
    tally.outcomes.extend(CaptureOutcome(*outcome) for outcome in outcomes)
    return tally


@pytest.mark.parametrize(
    ("tally", "status", "partial"),
    [
        (_tally(), "complete", {}),
        (_tally(("chat", "stored", "a"), ("tool", "stored", "b")), "complete", {}),
        (_tally(("chat", "failed", "a")), "partial", {"failed": 1}),
        (_tally(("tool", "refused", "a"), ("chat", "refused", "b")), "partial", {"refused": 2}),
        (_tally(("chat", "missing", "a")), "partial", {"missing": 1}),
        (_tally(("chat", "stored", "a"), open_failed=True), "partial", {"open": 1}),
        (_tally(("chat", "stored", "a"), seal_failed=True), "partial", {"seal": 1}),
        # D1: a cancelled or crashed call is an error, and nothing replaced it.
        (_tally(("chat", "error", "a")), "partial", {"error": 1}),
        # D2: a later stored answer to the SAME request forgives the error.
        (_tally(("chat", "error", "a"), ("chat", "stored", "a")), "complete", {}),
        (_tally(("tool", "error", "a"), ("tool", "stored", "a")), "complete", {}),
        # ... but not one to a different request, and not one that came BEFORE the error.
        (_tally(("chat", "error", "a"), ("chat", "stored", "b")), "partial", {"error": 1}),
        (_tally(("chat", "stored", "a"), ("chat", "error", "a")), "partial", {"error": 1}),
        # ... and only an `error` is forgiven: failed, refused and missing stay lost.
        (
            _tally(("chat", "failed", "a"), ("chat", "stored", "a")),
            "partial",
            {"failed": 1},
        ),
        (
            _tally(("chat", "error", "a"), ("chat", "failed", "a")),
            "partial",
            {"failed": 1, "error": 1},
        ),
        # An outcome with no digest cannot be matched to a retry.
        (_tally(("chat", "error", None), ("chat", "stored", None)), "partial", {"error": 1}),
        (
            _tally(("chat", "failed", "a"), ("tool", "missing", "b"), seal_failed=True),
            "partial",
            {"failed": 1, "missing": 1, "seal": 1},
        ),
    ],
)
def test_capture_status_rule(tally: CaptureTally, status: str, partial: dict[str, int]) -> None:
    assert tally.status() == status
    attributes = tally.attributes()
    assert attributes["capture.status"] == status
    assert {
        key.removeprefix("capture.partial."): value
        for key, value in attributes.items()
        if key.startswith("capture.partial.")
    } == partial


def test_a_capture_run_states_its_copy_even_with_no_call() -> None:
    attributes = _tally().attributes()

    assert attributes == {"capture.frozen_copy_id": _COPY, "capture.status": "complete"}


def test_a_capture_run_whose_copy_never_opened_states_no_copy() -> None:
    attributes = _tally(open_failed=True).attributes()

    assert attributes == {"capture.status": "partial", "capture.partial.open": 1}


def test_a_replay_run_states_only_the_copy_it_replays() -> None:
    tally = CaptureTally(mode="replay", frozen_copy_id=_COPY)
    tally.outcomes.append(CaptureOutcome("chat", "failed", "a"))

    assert tally.attributes() == {"capture.replay": _COPY}


def test_a_normal_run_states_nothing() -> None:
    assert CaptureTally().attributes() == {}


def test_a_capture_attributes_carry_no_request_content() -> None:
    attributes = _tally(("chat", "failed", "a" * 64)).attributes()

    assert all(isinstance(value, (str, int)) for value in attributes.values())
    assert "a" * 64 not in str(attributes)


def test_the_tally_is_bound_for_a_scope_and_restored_after_it() -> None:
    assert current_capture_tally() is None
    record_capture_outcome(CaptureOutcome("chat", "stored"))  # no tally bound: a no-op

    with capture_outcomes() as tally:
        record_capture_outcome(CaptureOutcome("chat", "stored", "a"))
        assert current_capture_tally() is tally

    assert tally.outcomes == [CaptureOutcome("chat", "stored", "a")]
    assert current_capture_tally() is None
