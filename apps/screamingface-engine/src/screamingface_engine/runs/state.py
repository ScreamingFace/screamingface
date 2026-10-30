"""A Run's state from its Candidates (E5 P1 spec R5).

FEATURE: first-class Runs (OME-1785). INVARIANT: a pure function of the Candidate states, the
cancel flag, the Run's last activity and the clock; the first matching row wins. The registry
stores its result on every write, and its refresh sweep re-applies it as the clock moves.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from screamingface_engine.runs.model import (
    CANDIDATE_STATES,
    CandidateState,
    RunState,
    is_aware,
    is_terminal_candidate,
)


@dataclass(frozen=True, slots=True)
class _Facts:
    states: frozenset[CandidateState]
    canceled: bool
    pending_is_live: bool


def _canceled(facts: _Facts) -> bool:
    # AIDEV-NOTE: a cancel also moves every `pending` Candidate to `stopped` in the same write
    # (spec D12, the registry's job), and sets the flag only while something is non-terminal, so
    # "flag set and all terminal" is exactly "the cancel took effect".
    return facts.canceled and all(is_terminal_candidate(state) for state in facts.states)


def _running(facts: _Facts) -> bool:
    # INVARIANT (spec R5): `pending` is the one non-terminal state with no live work behind it,
    # so it is the only one the grace window applies to.
    live = bool(facts.states & {"scheduled", "running"})
    return live or ("pending" in facts.states and facts.pending_is_live)


def _interrupted(facts: _Facts) -> bool:
    # Past the `running` row, a `pending` Candidate is past the grace, and a `stopped` one
    # without a cancel was reaped. With the flag set, `stopped` was the cancel itself.
    reaped = "stopped" in facts.states and not facts.canceled
    return "lost" in facts.states or "pending" in facts.states or reaped


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


def derive_state(
    candidates: Sequence[CandidateState],
    *,
    canceled: bool,
    last_activity_at: datetime,
    now: datetime,
    grace: timedelta,
) -> RunState:
    """The Run's state, by spec R5's ordered rows.

    WHY `pending` has a grace: a Client waiting for admission has not started a Candidate yet,
    and must not read as dead. Past `last_activity_at + grace` with nothing started, the Client
    is taken to have gone away.
    """
    if not candidates:
        raise ValueError("a Run needs at least one Candidate")
    unknown = set(candidates) - CANDIDATE_STATES
    if unknown:
        # WHY: the Literal is erased at runtime; an unknown state must not fall through to
        # `errored` and report a Run that may have succeeded as failed.
        raise ValueError(f"unknown Candidate state: {sorted(unknown)}")
    if grace <= timedelta(0):
        raise ValueError("the pending grace must be positive")
    if not (is_aware(last_activity_at) and is_aware(now)):
        raise ValueError("derive_state needs timezone-aware datetimes")
    facts = _Facts(
        states=frozenset(candidates),
        canceled=canceled,
        pending_is_live=now < last_activity_at + grace,
    )
    for state, matches in _ROWS:
        if matches(facts):
            return state
    return "errored"
