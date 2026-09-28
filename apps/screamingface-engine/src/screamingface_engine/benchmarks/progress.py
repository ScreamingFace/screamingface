"""Optional completed-grade observations; grading remains execution-owned."""

from collections.abc import Callable, Sequence
from typing import Protocol, runtime_checkable

from screamingface_engine.benchmarks.aggregation import CandidateScore
from screamingface_engine.benchmarks.contract import CaseResult
from screamingface_engine.candidate_scope import in_candidate_invocation
from screamingface_engine.observations import LogEmitter, current_observations
from url4.observe import current_log_sink

type ScoreCases = Callable[[Sequence[CaseResult]], CandidateScore]


@runtime_checkable
class ProgressObserver(Protocol):
    def case_completed(
        self,
        benchmark: str,
        revision: str,
        result: CaseResult,
        scorer: ScoreCases,
        emit: LogEmitter | None,
    ) -> None: ...


def completed_case(benchmark: str, revision: str, result: CaseResult, scorer: ScoreCases) -> None:
    # INVARIANT: an evaluation nested inside a candidate must not score its outer run.
    if in_candidate_invocation():
        return
    run = current_observations()
    if run is not None:
        for observer in run.observers:
            with run.guard():
                if isinstance(observer, ProgressObserver):
                    observer.case_completed(benchmark, revision, result, scorer, current_log_sink())
