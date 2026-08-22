"""Exact run discovery and terminal accounting for Benchmark progress."""

from __future__ import annotations

import re
from collections.abc import Mapping

from screamingface_engine.benchmarks.contract import CaseId
from screamingface_engine.benchmarks.definition import Benchmark
from screamingface_engine.benchmarks.registry import BenchmarkRegistry
from url4 import Node, RelExpr, Text, build, walk
from url4.core.errors import Url4Error

_AGGREGATE_INTENT = re.compile(r"aggregate:([1-9][0-9]*)")


class EvaluationProgressTracker:
    """Own terminal observations for one exact Benchmark execution."""

    __slots__ = ("_candidate_failures", "_case_executions", "benchmark_id", "total")

    def __init__(self, *, benchmark_id: str, total: int) -> None:
        if not isinstance(benchmark_id, str) or not benchmark_id:
            raise ValueError("benchmark_id must be non-empty text")
        if isinstance(total, bool) or not isinstance(total, int) or total < 1:
            raise ValueError("total must be a positive integer")
        self.benchmark_id = benchmark_id
        self.total = total
        self._case_executions: dict[CaseId, str] = {}
        self._candidate_failures = 0

    @property
    def completed(self) -> int:
        return len(self._case_executions) + self._candidate_failures

    @property
    def candidate_failures(self) -> int:
        return self._candidate_failures

    @property
    def case_executions(self) -> tuple[str, ...]:
        return tuple(self._case_executions.values())

    def record_case_execution(self, value: str) -> bool:
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
                self._case_executions[outcome.case_id] = value
                accepted = True
        return accepted

    def record_candidate_failure(self) -> bool:
        """Account one anonymous Candidate failure when capacity remains."""

        if self.completed >= self.total:
            return False
        self._candidate_failures += 1
        return True


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


__all__ = ["EvaluationProgressTracker", "discover_evaluation_progress"]
