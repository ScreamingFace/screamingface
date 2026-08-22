"""Exact run discovery and terminal accounting for Benchmark progress."""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from screamingface_engine.benchmarks.aggregation import Scorer
from screamingface_engine.benchmarks.contract import CaseId, CaseResult
from screamingface_engine.benchmarks.definition import Benchmark
from screamingface_engine.benchmarks.registry import BenchmarkRegistry
from url4 import Node, RelExpr, Text, build, walk
from url4.core.errors import Url4Error

_AGGREGATE_INTENT = re.compile(r"aggregate:([1-9][0-9]*)")
PROGRESS_BODY = "evaluation progress"
PROGRESS_SCHEMA = "screamingface.evaluation-progress.v1"

type CaseProjector = Callable[[str], CaseResult]


@dataclass(frozen=True, slots=True)
class ProgressSnapshot:
    """One complete, privacy-bounded terminal progress state."""

    total: int
    completed: int
    graded: int
    failed: int
    refused: int
    provisional_score: float | None

    def attributes(self) -> dict[str, str | int | float | bool | None]:
        return {
            "screamingface.event.schema": PROGRESS_SCHEMA,
            "cases.total": self.total,
            "cases.completed": self.completed,
            "cases.graded": self.graded,
            "cases.failed": self.failed,
            "cases.refused": self.refused,
            "score.provisional": self.provisional_score,
            "score.coverage": self.graded / self.total,
        }


@dataclass(frozen=True, slots=True)
class _CaseProjection:
    selected_index: int
    grade_case: CaseProjector
    scorer: Scorer


@dataclass(frozen=True, slots=True)
class _TerminalCase:
    raw: str
    selected_index: int | None
    result: CaseResult | None
    status: str | None


class EvaluationProgressTracker:
    """Own terminal observations for one exact Benchmark execution."""

    __slots__ = (
        "_candidate_failures",
        "_case_executions",
        "_projections",
        "_scorer",
        "benchmark_id",
        "total",
    )

    def __init__(self, *, benchmark_id: str, total: int) -> None:
        if not isinstance(benchmark_id, str) or not benchmark_id:
            raise ValueError("benchmark_id must be non-empty text")
        if isinstance(total, bool) or not isinstance(total, int) or total < 1:
            raise ValueError("total must be a positive integer")
        self.benchmark_id = benchmark_id
        self.total = total
        self._case_executions: dict[CaseId, _TerminalCase] = {}
        self._projections: dict[CaseId, _CaseProjection] = {}
        self._scorer: Scorer | None = None
        self._candidate_failures = 0

    @property
    def completed(self) -> int:
        return len(self._case_executions) + self._candidate_failures

    @property
    def candidate_failures(self) -> int:
        return self._candidate_failures

    @property
    def case_executions(self) -> tuple[str, ...]:
        return tuple(terminal.raw for terminal in self._case_executions.values())

    def register_case_projection(
        self,
        benchmark_id: str,
        *,
        case_id: CaseId,
        selected_index: int,
        grade_case: CaseProjector,
        scorer: Scorer,
    ) -> bool:
        """Bind one private Benchmark projector before its shared Case return becomes terminal."""

        accepted = (
            benchmark_id == self.benchmark_id
            and isinstance(selected_index, int)
            and not isinstance(selected_index, bool)
            and 0 <= selected_index < self.total
            and case_id not in self._case_executions
            and callable(grade_case)
            and callable(scorer)
        )
        if accepted:
            self._projections[case_id] = _CaseProjection(selected_index, grade_case, scorer)
            self._scorer = scorer
        return accepted

    def record_case_execution(self, value: str) -> ProgressSnapshot | None:
        """Retain one new valid terminal Case, bounded by the selected total."""

        accepted = False
        if self.completed < self.total:
            try:
                # Lazy import keeps the shared Case endpoint free to notify the run-Log adapter
                # without forming a module cycle through this tracker.
                from screamingface_engine.benchmarks.case_execution import case_execution_outcome

                outcome = case_execution_outcome(value)
            except (TypeError, ValueError):
                outcome = None
            if outcome is not None and outcome.case_id not in self._case_executions:
                projection = _take_projection(self._projections, outcome.case_id)
                result = _project_case(projection, value, outcome.case_id)
                status = (
                    result.status
                    if result is not None
                    else "refused"
                    if outcome.error is not None and outcome.candidate.status == "refused"
                    else "failed"
                    if outcome.error is not None
                    else None
                )
                self._case_executions[outcome.case_id] = _TerminalCase(
                    value,
                    projection.selected_index if projection is not None else None,
                    result,
                    status,
                )
                accepted = True
        return self.snapshot() if accepted else None

    def record_candidate_failure(self) -> ProgressSnapshot | None:
        """Account one anonymous Candidate failure when capacity remains."""

        if self.completed >= self.total:
            return None
        self._candidate_failures += 1
        return self.snapshot()

    def snapshot(self) -> ProgressSnapshot:
        cases = tuple(self._case_executions.values())
        graded = [
            terminal
            for terminal in cases
            if terminal.result is not None
            and terminal.result.grade is not None
            and terminal.result.grade.score is not None
        ]
        provisional = _provisional_score(graded, self._scorer)
        return ProgressSnapshot(
            total=self.total,
            completed=self.completed,
            graded=len(graded),
            failed=self._candidate_failures + sum(case.status == "failed" for case in cases),
            refused=sum(case.status == "refused" for case in cases),
            provisional_score=provisional,
        )


def _project_case(
    projection: _CaseProjection | None,
    raw: str,
    case_id: CaseId,
) -> CaseResult | None:
    if projection is None:
        return None
    try:
        result = projection.grade_case(raw)
    except Exception:  # noqa: BLE001 - a progress projector is observational
        return None
    return (
        result
        if isinstance(result, CaseResult) and _case_ids_match(result.case_id, case_id)
        else None
    )


def _take_projection(
    projections: dict[CaseId, _CaseProjection],
    case_id: CaseId,
) -> _CaseProjection | None:
    key = next(
        (candidate for candidate in projections if _case_ids_match(candidate, case_id)),
        None,
    )
    return projections.pop(key) if key is not None else None


def _case_ids_match(left: CaseId, right: CaseId) -> bool:
    return left == right or (
        isinstance(left, int)
        and not isinstance(left, bool)
        and isinstance(right, str)
        and right == str(left)
        or isinstance(right, int)
        and not isinstance(right, bool)
        and isinstance(left, str)
        and left == str(right)
    )


def _provisional_score(
    terminals: list[_TerminalCase],
    scorer: Scorer | None,
) -> float | None:
    if not terminals or scorer is None or any(case.selected_index is None for case in terminals):
        return None
    ordered = sorted(terminals, key=lambda case: int(case.selected_index or 0))
    typed = [case.result for case in ordered if case.result is not None]
    try:
        value = scorer(typed).score
    except Exception:  # noqa: BLE001 - the final aggregate remains authoritative
        return None
    return (
        float(value)
        if not isinstance(value, bool) and isinstance(value, int | float) and math.isfinite(value)
        else None
    )


def discover_evaluation_progress(
    registry: BenchmarkRegistry,
    rendered_url4: str,
) -> EvaluationProgressTracker | None:
    """Discover exactly one registered aggregate call or decline fail-open."""

    root = _parse(rendered_url4)
    if root is None:
        return None
    matches = _matching_aggregate_calls(root, _aggregate_routes(registry))
    if matches is None or len(matches) != 1:
        return None
    benchmark_id, selected = matches[0]
    return EvaluationProgressTracker(benchmark_id=benchmark_id, total=selected)


def _parse(rendered_url4: str) -> Node | None:
    try:
        return build(rendered_url4)
    except (TypeError, ValueError, Url4Error):
        return None


def _aggregate_routes(registry: BenchmarkRegistry) -> dict[str, tuple[Benchmark, ...]]:
    declared: dict[str, list[Benchmark]] = {}
    for benchmark in registry:
        if benchmark.aggregate_route is None:
            continue
        declared.setdefault(benchmark.aggregate_route, []).append(benchmark)
    return {route: tuple(benchmarks) for route, benchmarks in declared.items()}


def _matching_aggregate_calls(
    root: Node,
    routes: Mapping[str, tuple[Benchmark, ...]],
) -> list[tuple[str, int]] | None:
    matches: list[tuple[str, int]] = []
    for node in walk(root):
        if not isinstance(node, RelExpr) or node.path not in routes:
            continue
        benchmarks = routes[node.path]
        if len(benchmarks) != 1:
            return None
        if not isinstance(node.intent, Text):
            continue
        match = _AGGREGATE_INTENT.fullmatch(node.intent.value)
        if match is None:
            continue
        benchmark = benchmarks[0]
        selected = int(match.group(1))
        if selected <= benchmark.case_count:
            matches.append((benchmark.id, selected))
    return matches


__all__ = [
    "PROGRESS_BODY",
    "PROGRESS_SCHEMA",
    "EvaluationProgressTracker",
    "ProgressSnapshot",
    "discover_evaluation_progress",
]
