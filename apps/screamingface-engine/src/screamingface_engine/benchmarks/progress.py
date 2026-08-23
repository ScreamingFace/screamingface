"""Exact run discovery and terminal accounting for Benchmark progress."""

from __future__ import annotations

import logging
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from screamingface_engine.benchmarks.contract import CaseId, CaseResult
from screamingface_engine.benchmarks.definition import (
    Benchmark,
    BoundEvaluation,
    IndexedCaseResult,
)
from screamingface_engine.benchmarks.registry import BenchmarkRegistry
from url4 import Node, RelExpr, Text, build, walk
from url4.core.errors import Url4Error

_AGGREGATE_INTENT = re.compile(r"aggregate:([1-9][0-9]*)")
PROGRESS_BODY = "evaluation progress"
PROGRESS_SCHEMA = "screamingface.evaluation-progress.v1"
_logger = logging.getLogger(__name__)


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
        "_diagnostic_type",
        "_evaluation",
        "benchmark_id",
        "total",
    )

    def __init__(
        self,
        *,
        benchmark_id: str,
        total: int,
        evaluation: BoundEvaluation | None = None,
    ) -> None:
        if not isinstance(benchmark_id, str) or not benchmark_id:
            raise ValueError("benchmark_id must be non-empty text")
        if isinstance(total, bool) or not isinstance(total, int) or total < 1:
            raise ValueError("total must be a positive integer")
        self.benchmark_id = benchmark_id
        self.total = total
        self._case_executions: dict[CaseId, _TerminalCase] = {}
        self._diagnostic_type: str | None = None
        self._evaluation = evaluation
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

    def take_diagnostic_type(self) -> str | None:
        diagnostic = self._diagnostic_type
        self._diagnostic_type = None
        return diagnostic

    def _has_terminal(self, case_id: CaseId) -> bool:
        return any(_case_ids_match(case_id, terminal) for terminal in self._case_executions)

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
            if outcome is not None and not self._has_terminal(outcome.case_id):
                projected, diagnostic = _project_case(
                    self._evaluation,
                    value,
                    outcome.case_id,
                    self.total,
                )
                if diagnostic is not None:
                    self._diagnostic_type = diagnostic
                    return None
                result = projected.result if projected is not None else None
                if result is None and outcome.error is None:
                    self._diagnostic_type = "MissingCaseProjection"
                status = (
                    result.status
                    if result is not None
                    else "refused"
                    if outcome.error is not None and outcome.candidate.status == "refused"
                    else "failed"
                    if outcome.error is not None
                    else "failed"
                )
                self._case_executions[outcome.case_id] = _TerminalCase(
                    value,
                    projected.selected_index if projected is not None else None,
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
        provisional, diagnostic = _provisional_score(graded, self._evaluation)
        if diagnostic is not None:
            self._diagnostic_type = diagnostic
        return ProgressSnapshot(
            total=self.total,
            completed=self.completed,
            graded=len(graded),
            failed=self._candidate_failures + sum(case.status == "failed" for case in cases),
            refused=sum(case.status == "refused" for case in cases),
            provisional_score=provisional,
        )


def _project_case(
    evaluation: BoundEvaluation | None,
    raw: str,
    case_id: CaseId,
    total: int,
) -> tuple[IndexedCaseResult | None, str | None]:
    if evaluation is None:
        return None, None
    result: IndexedCaseResult | None
    diagnostic: str | None
    try:
        projected = evaluation.grade_case(raw)
    except Exception as exc:  # noqa: BLE001 - a progress projector is observational
        result, diagnostic = None, type(exc).__name__
    else:
        valid = (
            isinstance(projected, IndexedCaseResult)
            and projected.selected_index < total
            and _case_ids_match(projected.result.case_id, case_id)
        )
        result = projected if valid else None
        diagnostic = None if valid else "InvalidCaseProjection"
    return result, diagnostic


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
    evaluation: BoundEvaluation | None,
) -> tuple[float | None, str | None]:
    if (
        not terminals
        or evaluation is None
        or any(case.selected_index is None for case in terminals)
    ):
        return None, None
    ordered = sorted(terminals, key=lambda case: int(case.selected_index or 0))
    typed = [case.result for case in ordered if case.result is not None]
    try:
        value = evaluation.score_cases(typed).score
    except Exception as exc:  # noqa: BLE001 - the final aggregate remains authoritative
        score, diagnostic = None, type(exc).__name__
    else:
        valid = (
            not isinstance(value, bool) and isinstance(value, int | float) and math.isfinite(value)
        )
        score = float(value) if valid else None
        diagnostic = None if valid else "InvalidProvisionalScore"
    return score, diagnostic


def discover_evaluation_progress(
    registry: BenchmarkRegistry,
    rendered_url4: str,
    *,
    assets_root: Path,
) -> EvaluationProgressTracker | None:
    """Discover exactly one registered aggregate call or decline fail-open."""

    root = _parse(rendered_url4)
    if root is None:
        return None
    matches = _matching_aggregate_calls(root, _aggregate_routes(registry))
    if matches is None or len(matches) != 1:
        return None
    benchmark, selected = matches[0]
    return _bind_evaluation_progress(benchmark, selected, assets_root)


def _bind_evaluation_progress(
    benchmark: Benchmark,
    selected: int,
    assets_root: Path,
) -> EvaluationProgressTracker | None:
    evaluation = benchmark.evaluation
    # INVARIANT: aggregate matching admits only routes owned by an Evaluation adapter.
    assert evaluation is not None
    try:
        bound = evaluation.bind(assets_root, selected)
    except Exception as exc:  # noqa: BLE001 - discovery is observational and fail-open
        _logger.warning("Benchmark Evaluation binding failed (%s)", type(exc).__name__)
        return None
    if not isinstance(bound, BoundEvaluation):
        _logger.warning("Benchmark Evaluation binding failed (InvalidBoundEvaluation)")
        return None
    return EvaluationProgressTracker(
        benchmark_id=benchmark.id,
        total=selected,
        evaluation=bound,
    )


def _parse(rendered_url4: str) -> Node | None:
    try:
        return build(rendered_url4)
    except (TypeError, ValueError, Url4Error):
        return None


def _aggregate_routes(registry: BenchmarkRegistry) -> dict[str, tuple[Benchmark, ...]]:
    declared: dict[str, list[Benchmark]] = {}
    for benchmark in registry:
        if benchmark.evaluation is None:
            continue
        declared.setdefault(benchmark.evaluation.aggregate_route, []).append(benchmark)
    return {route: tuple(benchmarks) for route, benchmarks in declared.items()}


def _matching_aggregate_calls(
    root: Node,
    routes: Mapping[str, tuple[Benchmark, ...]],
) -> list[tuple[Benchmark, int]] | None:
    matches: list[tuple[Benchmark, int]] = []
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
            matches.append((benchmark, selected))
    return matches


__all__ = [
    "PROGRESS_BODY",
    "PROGRESS_SCHEMA",
    "EvaluationProgressTracker",
    "ProgressSnapshot",
    "discover_evaluation_progress",
]
