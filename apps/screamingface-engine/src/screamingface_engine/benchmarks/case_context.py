"""Benchmark-owned Case identity, scoped to the execution that supplied it."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from screamingface_engine.benchmarks.contract import CaseId, validate_case_id
from screamingface_engine.observations import RunObservations, current_observations

_CURRENT: ContextVar[
    tuple[RunObservations | None, CaseId | None, tuple[int, int] | None] | None
] = ContextVar("benchmark_case", default=None)


@contextmanager
def case_scope(
    case_id: CaseId | None, *, position: tuple[int, int] | None = None
) -> Iterator[None]:
    """Carry explicit metadata through nested work; unlabelled calls mask outer cases."""
    token = _CURRENT.set(
        (current_observations(), validate_case_id(case_id, optional=True), position)
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
