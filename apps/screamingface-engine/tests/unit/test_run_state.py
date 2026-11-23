"""E5 P1 spec R5, as E5 P2 spec R12 changes it: a Run's state is a pure function, and the first
matching row wins.

FEATURE: first-class Runs (OME-1785). STORY: as a researcher listing my runs, I see one state per
run that never contradicts what its Candidates did.
"""

from __future__ import annotations

from typing import cast

import pytest

from screamingface_engine.runs.records import CandidateState, RunState
from screamingface_engine.runs.state import derive_state


@pytest.mark.parametrize(
    ("candidates", "canceled", "expected"),
    [
        # 1. canceled: a cancel stopped the Run and every Candidate is terminal.
        (["stopped", "stopped"], True, "canceled"),
        (["succeeded", "stopped"], True, "canceled"),
        (["succeeded", "succeeded"], True, "canceled"),
        # 2. running: something pending, scheduled or running. A `pending` Candidate is live
        # however long it waits for a slot (E5 P2 spec R12).
        (["running", "succeeded"], False, "running"),
        (["scheduled", "failed"], False, "running"),
        (["pending", "succeeded"], False, "running"),
        (["running", "stopped"], True, "running"),  # canceled, a stop still in flight
        (["pending", "stopped"], True, "running"),
        # 3. interrupted: lost, or stopped by something other than a cancel.
        (["succeeded", "lost"], False, "interrupted"),
        (["failed", "stopped"], False, "interrupted"),  # orphaned, a deadline, the reaper
        # 4-6. complete, partial, errored.
        (["succeeded", "succeeded"], False, "complete"),
        (["succeeded", "failed", "timed_out"], False, "partial"),
        (["failed", "timed_out"], False, "errored"),
        (["failed"], False, "errored"),
    ],
)
def test_the_first_matching_row_wins(
    candidates: list[CandidateState], canceled: bool, expected: RunState
) -> None:
    assert derive_state(candidates, canceled=canceled) == expected


def test_the_order_of_the_candidates_does_not_matter() -> None:
    assert derive_state(["lost", "succeeded"], canceled=False) == "interrupted"
    assert derive_state(["succeeded", "lost"], canceled=False) == "interrupted"


def test_a_run_needs_at_least_one_candidate() -> None:
    with pytest.raises(ValueError, match="at least one Candidate"):
        derive_state([], canceled=False)


def test_an_unknown_candidate_state_is_refused() -> None:
    """WHY: the Literal is erased at runtime; a misspelt state must not read as `errored`."""
    with pytest.raises(ValueError, match="unknown Candidate state"):
        derive_state(cast(list[CandidateState], ["succeeded", "SUCCEEDED"]), canceled=False)
