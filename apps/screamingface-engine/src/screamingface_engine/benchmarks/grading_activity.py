"""Discrete case-grading facts; no execution scope, timing or payload transport."""

from typing import Literal, Protocol, runtime_checkable

from screamingface_engine.benchmarks.contract import CaseId
from screamingface_engine.candidate_scope import in_candidate_invocation
from screamingface_engine.observations import LogEmitter, current_observations
from url4.observe import current_log_sink

type GradingState = Literal["started", "completed", "failed"]


@runtime_checkable
class CaseGradingObserver(Protocol):
    def case_grading(
        self, case_id: CaseId, state: GradingState, emit: LogEmitter | None
    ) -> None: ...


def grading_activity(case_id: CaseId, state: GradingState) -> None:
    """Report an explicit handoff/outcome without allowing an observer to change it."""
    if in_candidate_invocation():
        return
    run = current_observations()
    if run is not None:
        for observer in run.observers:
            with run.guard():
                if isinstance(observer, CaseGradingObserver):
                    observer.case_grading(case_id, state, current_log_sink())
