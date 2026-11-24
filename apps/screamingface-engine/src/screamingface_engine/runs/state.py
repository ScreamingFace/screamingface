"""A Run's state from its Candidates (E5 P1 spec R5, E5 P2 spec R12).

FEATURE: first-class Runs (OME-1785). INVARIANT: a pure function of the Candidate states and
whether a cancel stopped the Run; the first matching row wins. The registry stores only the facts
and calls this on every read, so the state is always that of the moment.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from screamingface_engine.runs.records import (
    CANDIDATE_STATES,
    CandidateState,
    RunState,
    is_terminal_candidate,
)


@dataclass(frozen=True, slots=True)
class _Facts:
    states: frozenset[CandidateState]
    canceled: bool


def _canceled(facts: _Facts) -> bool:
    # AIDEV-NOTE: a stop settles every unstarted Candidate in the same write (E5 P2 spec R9, the
    # registry's job), and records its reason only while something is non-terminal, so "canceled
    # and all terminal" is exactly "the cancel took effect".
    return facts.canceled and all(is_terminal_candidate(state) for state in facts.states)


def _running(facts: _Facts) -> bool:
    # INVARIANT (E5 P2 spec R12): a `pending` Candidate is live, however long it waits: the
    # Engine's driver starts it when a slot frees, or a stop settles it.
    return bool(facts.states & {"pending", "scheduled", "running"})


def _interrupted(facts: _Facts) -> bool:
    # Past the `running` row: `stopped` without a cancel was a stop for another reason (orphaned,
    # a deadline, the reaper), and `lost` an outcome that never came.
    reaped = "stopped" in facts.states and not facts.canceled
    return "lost" in facts.states or reaped


def _complete(facts: _Facts) -> bool:
    return facts.states == {"succeeded"}


def _partial(facts: _Facts) -> bool:
    return "succeeded" in facts.states


# INVARIANT (spec R5): evaluated in this order, and the first match wins. `errored` is the rest:
# every Candidate is `failed` or `timed_out`.
_ROWS: tuple[tuple[RunState, Callable[[_Facts], bool]], ...] = (
    ("canceled", _canceled),
    ("running", _running),
    ("interrupted", _interrupted),
    ("complete", _complete),
    ("partial", _partial),
)


def derive_state(candidates: Sequence[CandidateState], *, canceled: bool) -> RunState:
    """The Run's state, by spec R5's ordered rows. ``canceled`` is whether a cancel stopped the
    Run (`stopped_by == "canceled"`, E5 P2 spec R12)."""
    if not candidates:
        raise ValueError("a Run needs at least one Candidate")
    unknown = set(candidates) - CANDIDATE_STATES
    if unknown:
        # WHY: the Literal is erased at runtime; an unknown state must not fall through to
        # `errored` and report a Run that may have succeeded as failed.
        raise ValueError(f"unknown Candidate state: {sorted(unknown)}")
    facts = _Facts(states=frozenset(candidates), canceled=canceled)
    for state, matches in _ROWS:
        if matches(facts):
            return state
    return "errored"
