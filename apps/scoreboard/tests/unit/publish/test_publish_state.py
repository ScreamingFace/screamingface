"""PB-13, PB-15, PB-16 — the publication state machine (erd 2.6), its table and its routes.

FEATURE: OME-1307 (E14). INVARIANT under test: every cell of the erd 2.6 table, and no other write
of `state` outside `state.apply`.
"""

from __future__ import annotations

from typing import get_args

import pytest

from scoreboard.core.publish.state import Event, State, Transition, TransitionRejected, apply

_REJECT = None

# The table of erd 2.6, cell by cell: (state, event) -> (to, changed, reset_attempts) or reject.
TABLE: dict[tuple[State, Event], tuple[State, bool, bool] | None] = {
    ("private", "owner_publishes"): ("requested", True, False),
    ("private", "worker_succeeds"): _REJECT,
    ("private", "worker_fails_retryable"): _REJECT,
    ("private", "attempts_exhausted"): _REJECT,
    ("private", "admin_takedown"): ("withdrawn", True, False),
    ("requested", "owner_publishes"): ("requested", False, False),
    ("requested", "worker_succeeds"): ("published", True, False),
    ("requested", "worker_fails_retryable"): ("requested", False, False),
    ("requested", "attempts_exhausted"): ("failed", True, False),
    ("requested", "admin_takedown"): ("withdrawn", True, False),
    ("failed", "owner_publishes"): ("requested", True, True),
    ("failed", "worker_succeeds"): _REJECT,
    ("failed", "worker_fails_retryable"): _REJECT,
    ("failed", "attempts_exhausted"): _REJECT,
    ("failed", "admin_takedown"): ("withdrawn", True, False),
    ("published", "owner_publishes"): ("published", False, False),
    ("published", "worker_succeeds"): _REJECT,
    ("published", "worker_fails_retryable"): _REJECT,
    ("published", "attempts_exhausted"): _REJECT,
    ("published", "admin_takedown"): ("withdrawn", True, False),
    ("withdrawn", "owner_publishes"): _REJECT,
    ("withdrawn", "worker_succeeds"): _REJECT,
    ("withdrawn", "worker_fails_retryable"): _REJECT,
    ("withdrawn", "attempts_exhausted"): _REJECT,
    ("withdrawn", "admin_takedown"): ("withdrawn", False, False),
}


def test_the_table_covers_every_state_and_event() -> None:
    # WHY: a cell missing from this test would be a cell nothing checks.
    cells = {(s, e) for s in get_args(State) for e in get_args(Event)}

    assert set(TABLE) == cells


@pytest.mark.parametrize(("cell", "expected"), list(TABLE.items()), ids=lambda v: str(v))
def test_double_publish_is_noop_table(
    cell: tuple[State, Event], expected: tuple[State, bool, bool] | None
) -> None:
    state, event = cell

    if expected is None:
        with pytest.raises(TransitionRejected) as raised:
            apply(state, event)
        assert (raised.value.state, raised.value.event) == cell
    else:
        result = apply(state, event)
        assert result == Transition(*expected)


def test_publish_after_withdraw_is_rejected_by_the_machine() -> None:
    with pytest.raises(TransitionRejected):
        apply("withdrawn", "owner_publishes")
