"""Per-run cumulative score projection; no scoring evidence crosses the log boundary."""

import math
import time
from dataclasses import dataclass, field

from screamingface_engine.benchmarks.contract import CaseId, CaseResult
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
    ) -> None:
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
        self.flush(benchmark, revision, scorer, emit)

    def flush(self, benchmark: str, revision: str, scorer: ScoreCases, emit: LogEmitter) -> None:
        if self.revision == self.emitted_revision:
            return
        graded = tuple(
            c for c in self.cases.values() if c.grade is not None and c.grade.score is not None
        )
        score = scorer(graded).score if graded else None
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
