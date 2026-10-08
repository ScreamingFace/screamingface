"""Benchmark-owned Case identity, scoped to the execution that supplied it."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from screamingface_engine.benchmarks.contract import CaseId, validate_case_id
from screamingface_engine.observations import RunObservations, current_observations

_CURRENT: ContextVar[
    tuple[RunObservations | None, CaseId | None, tuple[int, int] | None, bool] | None
] = ContextVar("benchmark_case", default=None)


@contextmanager
def case_scope(
    case_id: CaseId | None, *, position: tuple[int, int] | None = None, recording: bool = False
) -> Iterator[None]:
    """Carry explicit metadata through nested work; unlabelled calls mask outer cases."""
    token = _CURRENT.set(
        (current_observations(), validate_case_id(case_id, optional=True), position, recording)
    )
    try:
        yield
    finally:
        _CURRENT.reset(token)


def current_case_id() -> CaseId | None:
    """Read request identity; join activity to result IDs with str(), never int()."""
    value = _CURRENT.get()
    # INVARIANT: a child run cannot borrow the surrounding run's Case identity.
    if value is None or value[0] is not current_observations():
        return None
    return value[1]


def current_case_position() -> tuple[int, int] | None:
    """Read the selected position only inside its owning run and case scope."""
    value = _CURRENT.get()
    if value is None or value[0] is not current_observations():
        return None
    return value[2]


def is_answer_recording() -> bool:
    """Recording stores an answer; it does not establish a grading verdict."""
    value = _CURRENT.get()
    return bool(value and value[0] is current_observations() and value[3])


# FEATURE (OME-1458): which Attempt of the Case this Candidate Invocation is. A Benchmark that
# declares N Attempts asks each Case N times; Attempt 1 is the ordinary call and carries no
# number, so only Attempt 2 and later open this scope.
_ATTEMPT: ContextVar[tuple[RunObservations | None, int] | None] = ContextVar(
    "benchmark_case_attempt", default=None
)


@contextmanager
def case_attempt_scope(attempt: int) -> Iterator[None]:
    """Mark nested work as Attempt ``attempt`` (2 or more) of the current Case."""

    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 2:
        raise ValueError("a numbered Attempt is 2 or more; Attempt 1 carries no number")
    token = _ATTEMPT.set((current_observations(), attempt))
    try:
        yield
    finally:
        _ATTEMPT.reset(token)


def current_case_attempt() -> int | None:
    """The Attempt number (2 or more) of the work in progress; None for Attempt 1 and all else.

    INVARIANT: like the Case identity, a child run cannot borrow the surrounding run's Attempt.
    """

    value = _ATTEMPT.get()
    if value is None or value[0] is not current_observations():
        return None
    return value[1]
