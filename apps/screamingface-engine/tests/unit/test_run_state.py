"""E5 P1 spec R5: a Run's state is a pure function, and the first matching row wins.

FEATURE: first-class Runs (OME-1785). STORY: as a researcher listing my runs, I see one state per
run that never contradicts what its Candidates did.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, tzinfo
from typing import cast

import pytest

from screamingface_engine.runs.model import CandidateState, RunState
from screamingface_engine.runs.state import derive_state

_GRACE = timedelta(seconds=1800)
_LAST = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
_WITHIN = _LAST + _GRACE - timedelta(seconds=1)
_PAST = _LAST + _GRACE


def _state(
    candidates: list[CandidateState], *, canceled: bool = False, now: datetime = _WITHIN
) -> RunState:
    return derive_state(
        candidates, canceled=canceled, last_activity_at=_LAST, now=now, grace=_GRACE
    )


@pytest.mark.parametrize(
    ("candidates", "canceled", "now", "expected"),
    [
        # 1. canceled: the flag is set and every Candidate is terminal.
        (["stopped", "stopped"], True, _WITHIN, "canceled"),
        (["succeeded", "stopped"], True, _PAST, "canceled"),
        (["succeeded", "succeeded"], True, _WITHIN, "canceled"),
        # 2. running: something scheduled or running, or pending within the grace.
        (["running", "succeeded"], False, _PAST, "running"),
        (["scheduled", "failed"], False, _PAST, "running"),
        (["pending", "succeeded"], False, _WITHIN, "running"),
        (["running", "stopped"], True, _WITHIN, "running"),  # flag set, a stop still in flight
        (["pending", "stopped"], True, _WITHIN, "running"),
        # 3. interrupted: lost, reaped, or pending past the grace.
        (["succeeded", "lost"], False, _WITHIN, "interrupted"),
        (["failed", "stopped"], False, _WITHIN, "interrupted"),  # stopped without a cancel
        (["pending", "succeeded"], False, _PAST, "interrupted"),
        (["pending", "stopped"], True, _PAST, "interrupted"),
        # 4-6. complete, partial, errored.
        (["succeeded", "succeeded"], False, _WITHIN, "complete"),
        (["succeeded", "failed", "timed_out"], False, _WITHIN, "partial"),
        (["failed", "timed_out"], False, _WITHIN, "errored"),
        (["failed"], False, _PAST, "errored"),
    ],
)
def test_the_first_matching_row_wins(
    candidates: list[CandidateState], canceled: bool, now: datetime, expected: RunState
) -> None:
    assert _state(candidates, canceled=canceled, now=now) == expected


def test_the_grace_boundary_is_exclusive() -> None:
    """INVARIANT: `pending` is live strictly before last_activity_at + grace, and not at it."""
    assert _state(["pending"], now=_PAST - timedelta(microseconds=1)) == "running"
    assert _state(["pending"], now=_PAST) == "interrupted"


def test_the_order_of_the_candidates_does_not_matter() -> None:
    assert _state(["lost", "succeeded"]) == _state(["succeeded", "lost"]) == "interrupted"


def test_a_run_needs_at_least_one_candidate() -> None:
    with pytest.raises(ValueError, match="at least one Candidate"):
        _state([])


def test_naive_datetimes_are_refused() -> None:
    """WHY: mixing naive and aware times would make the grace comparison silently wrong."""
    with pytest.raises(ValueError, match="timezone-aware"):
        derive_state(
            ["pending"],
            canceled=False,
            last_activity_at=_LAST.replace(tzinfo=None),
            now=_WITHIN,
            grace=_GRACE,
        )


def test_an_unknown_candidate_state_is_refused() -> None:
    """WHY: the Literal is erased at runtime; a misspelt state must not read as `errored`."""
    with pytest.raises(ValueError, match="unknown Candidate state"):
        _state(cast(list[CandidateState], ["succeeded", "SUCCEEDED"]))


@pytest.mark.parametrize("grace", [timedelta(0), timedelta(seconds=-1)])
def test_the_grace_must_be_positive(grace: timedelta) -> None:
    with pytest.raises(ValueError, match="grace"):
        derive_state(["pending"], canceled=False, last_activity_at=_LAST, now=_WITHIN, grace=grace)


def test_a_tzinfo_without_an_offset_is_naive() -> None:
    class _NoOffset(tzinfo):
        def utcoffset(self, dt: datetime | None) -> None:
            return None

        def dst(self, dt: datetime | None) -> None:
            return None

        def tzname(self, dt: datetime | None) -> None:
            return None

    with pytest.raises(ValueError, match="timezone-aware"):
        derive_state(
            ["pending"],
            canceled=False,
            last_activity_at=_LAST.replace(tzinfo=_NoOffset()),
            now=_WITHIN,
            grace=_GRACE,
        )
