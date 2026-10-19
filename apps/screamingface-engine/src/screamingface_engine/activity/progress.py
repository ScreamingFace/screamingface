"""Per-run cumulative score projection; no scoring evidence crosses the log boundary."""

import math
import time
from dataclasses import dataclass, field

from screamingface_engine.benchmarks.aggregation import gradeable_cases, policy_cases
from screamingface_engine.benchmarks.contract import CaseId, CaseResult
from screamingface_engine.benchmarks.definition import FailurePolicy
from screamingface_engine.benchmarks.progress import ScoreCases
from screamingface_engine.observations import LogEmitter

PROGRESS_INTERVAL_SECONDS = 0.1


@dataclass
class Progress:
    cases: dict[CaseId, CaseResult] = field(default_factory=dict)
    revision: int = 0
    emitted_revision: int = 0
    emitted_at: float = float("-inf")

    def observe(
        self,
        benchmark: str,
        revision: str,
        result: CaseResult,
        scorer: ScoreCases,
        emit: LogEmitter,
        *,
        failure_policy: FailurePolicy,
    ) -> None:
        result = scoring_projection(result)
        if self.cases.get(result.case_id) == result:
            return
        self.cases[result.case_id] = result
        self.revision += 1
        now = time.monotonic()
        # WHY: avoid reducing every prefix in a fast batch. Coalesced tails
        # are flushed before leaving the grading scope.
        terminal_failure = bool(result.failures) and (
            result.grade is None or result.grade.score is None
        )
        # INVARIANT: an unscored terminal failure still advances completed coverage.
        if not terminal_failure and now - self.emitted_at < PROGRESS_INTERVAL_SECONDS:
            return
        self.flush(benchmark, revision, scorer, emit, failure_policy=failure_policy)

    def flush(
        self,
        benchmark: str,
        revision: str,
        scorer: ScoreCases,
        emit: LogEmitter,
        *,
        failure_policy: FailurePolicy,
    ) -> None:
        if self.revision == self.emitted_revision:
            return
        observed = tuple(self.cases.values())
        graded = gradeable_cases(observed)
        # INVARIANT (OME-1642): the same Case selection as the finalized result.
        scoring_cases = policy_cases(observed, failure_policy)
        score = scorer(scoring_cases).score if scoring_cases is not None else None
        if score is not None and not math.isfinite(score):
            return
        emit(
            "Benchmark progress",
            {
                "sf.progress.schema": "screamingface.benchmark-progress.v1",
                "sf.progress.benchmark": benchmark,
                "sf.progress.benchmark_revision": revision,
                "sf.progress.revision": self.revision,
                "sf.progress.completed": len(self.cases),
                "sf.progress.graded": len(graded),
                "sf.progress.score": score,
            },
        )
        self.emitted_at = time.monotonic()
        self.emitted_revision = self.revision


def scoring_projection(result: CaseResult) -> CaseResult:
    """Retain scorer facts; discard prompt/answer, diagnostic text and accounting.

    Native scorers inspect grade metrics, check outcomes and (IFEval) evidence
    mode/outcome. Those facts remain intact; this copy never becomes a Report case.
    """
    grade = result.grade
    if grade is not None:
        checks = [
            check.model_copy(
                update={
                    "label": "",
                    "metadata": {},
                    "evidence": [
                        evidence.model_copy(
                            update={
                                "raw_output": None,
                                "explanation": None,
                                "accounting": None,
                                "metadata": {
                                    k: v for k, v in evidence.metadata.items() if k == "mode"
                                },
                            }
                        )
                        for evidence in check.evidence
                    ],
                }
            )
            for check in grade.checks
        ]
        grade = grade.model_copy(update={"checks": checks})
    return result.model_copy(
        update={
            "input": "[not retained]",
            "output": None,
            "refusal": None,
            "operations": None,
            "metadata": {},
            "grade": grade,
            "failures": [
                failure.model_copy(update={"message": "", "metadata": {}})
                for failure in result.failures
            ],
        }
    )
