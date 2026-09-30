"""The publication state machine of erd 2.6, cell by cell.

FEATURE: OME-1307 (E14). INVARIANT: pure, standard library only. `PublicationStore` is the only
writer of `state`, and it calls `apply` for every change, so this table is the one place that says
which change is allowed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

State = Literal["private", "requested", "published", "failed", "withdrawn"]
Event = Literal[
    "owner_publishes",
    "worker_succeeds",
    "worker_fails_retryable",
    "attempts_exhausted",
    "admin_takedown",
]


class TransitionRejected(Exception):
    def __init__(self, state: State, event: Event) -> None:
        super().__init__(f"event {event} is not allowed in state {state}")
        self.state = state
        self.event = event


@dataclass(frozen=True, slots=True)
class Transition:
    to: State
    changed: bool  # False for the no-op cells
    reset_attempts: bool  # True only for failed --owner_publishes--> requested


def _to(to: State, *, changed: bool = True, reset_attempts: bool = False) -> Transition:
    return Transition(to=to, changed=changed, reset_attempts=reset_attempts)


# WHY one dict: the table is the spec (erd 2.6). None is a rejected cell. A withdrawn row accepts
# only a repeated takedown, as a no-op; withdrawn is terminal.
_TABLE: dict[tuple[State, Event], Transition | None] = {
    ("private", "owner_publishes"): _to("requested"),
    ("private", "worker_succeeds"): None,
    ("private", "worker_fails_retryable"): None,
    ("private", "attempts_exhausted"): None,
    ("private", "admin_takedown"): _to("withdrawn"),
    ("requested", "owner_publishes"): _to("requested", changed=False),
    ("requested", "worker_succeeds"): _to("published"),
    ("requested", "worker_fails_retryable"): _to("requested", changed=False),
    ("requested", "attempts_exhausted"): _to("failed"),
    ("requested", "admin_takedown"): _to("withdrawn"),
    ("failed", "owner_publishes"): _to("requested", reset_attempts=True),
    ("failed", "worker_succeeds"): None,
    ("failed", "worker_fails_retryable"): None,
    ("failed", "attempts_exhausted"): None,
    ("failed", "admin_takedown"): _to("withdrawn"),
    ("published", "owner_publishes"): _to("published", changed=False),
    ("published", "worker_succeeds"): None,
    ("published", "worker_fails_retryable"): None,
    ("published", "attempts_exhausted"): None,
    ("published", "admin_takedown"): _to("withdrawn"),
    ("withdrawn", "owner_publishes"): None,
    ("withdrawn", "worker_succeeds"): None,
    ("withdrawn", "worker_fails_retryable"): None,
    ("withdrawn", "attempts_exhausted"): None,
    ("withdrawn", "admin_takedown"): _to("withdrawn", changed=False),
}


def apply(state: State, event: Event) -> Transition:
    """The transition of `event` in `state`, or `TransitionRejected`.

    A withdrawn row plus `owner_publishes` is a reject that the route maps to 409 `withdrawn`.
    """
    transition = _TABLE[(state, event)]
    if transition is None:
        raise TransitionRejected(state, event)
    return transition
