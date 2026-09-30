"""Task-local execution provenance for one complete Candidate Recipe."""

from __future__ import annotations

import contextvars
from collections.abc import Iterator, Sequence
from contextlib import contextmanager

from screamingface_engine.benchmarks.contract import CorrectiveLoopOutcome
from url4.core.errors import ResolutionError

type ExecutionRecorder = list[CorrectiveLoopOutcome]

_recorders: contextvars.ContextVar[tuple[ExecutionRecorder, ...]] = contextvars.ContextVar(
    "screamingface_engine_loop_outcome_recorders", default=()
)


@contextmanager
def capture_loop_outcomes(*, isolated: bool = False) -> Iterator[ExecutionRecorder]:
    """Capture provenance emitted by the Recipe's terminal orchestration boundary."""

    recorder: ExecutionRecorder = []
    active = () if isolated else _recorders.get()
    token = _recorders.set((*active, recorder))
    try:
        yield recorder
    finally:
        _recorders.reset(token)


def record_loop_outcome(execution: CorrectiveLoopOutcome) -> None:
    """Publish one already-decided execution outcome to every active scope."""

    for recorder in _recorders.get():
        recorder.append(execution)


def terminal_loop_outcome(
    executions: Sequence[CorrectiveLoopOutcome],
) -> CorrectiveLoopOutcome | None:
    """Return the one unambiguous execution outcome for the complete Recipe."""

    if not executions:
        return None
    first = executions[0]
    if all(execution == first for execution in executions[1:]):
        return first
    raise ResolutionError(
        "Candidate Recipe emitted ambiguous execution provenance",
        code="candidate_contract_error",
        permanent=True,
    )


__all__ = [
    "capture_loop_outcomes",
    "record_loop_outcome",
    "terminal_loop_outcome",
]
