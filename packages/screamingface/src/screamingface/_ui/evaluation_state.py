"""Candidate-scoped state for the live Evaluation panel."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import cast

from screamingface._evaluation.model import Candidate
from screamingface.events import Event, Log, Span, Started, Terminated, Usage
from screamingface.report import CandidateResult, Report

_BYPASS_REASON_PREFIX = "cache.bypass."
UNSTATED_BYPASS_REASON = "unstated"


@dataclass(slots=True)
class _CandidateProgress:
    candidate: Candidate
    total_cases: int | None
    completed_cases: int = 0
    failed_cases: int = 0
    model_calls: int = 0
    failed_calls: int = 0
    refusals: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    have_tokens: bool = False
    cost_usd: Decimal | None = None
    submitted: bool = False
    started: bool = False
    terminal_status: str | None = None
    root_sources: set[str] = field(default_factory=set)
    cache_counts: dict[str, tuple[int, int, int]] = field(default_factory=dict)
    cache_bypass_reasons: dict[str, dict[str, int]] = field(default_factory=dict)
    activity: str | None = None
    result: CandidateResult | None = None
    workflow_status: str | None = None
    started_elapsed_seconds: float | None = None

    @property
    def status(self) -> str:
        if self.result is not None:
            status = "finished"
        elif self.terminal_status == "failed":
            status = "run_failed"
        elif self.terminal_status in {"stopped", "timed_out"}:
            status = self.terminal_status
        elif self.workflow_status is not None:
            status = self.workflow_status
        else:
            status = "running" if self.started else "queued"
        return status

    @property
    def score(self) -> float | None:
        return None if self.result is None else self.result.score

    @property
    def score_available(self) -> bool:
        return self.result is not None

    @property
    def qualifier(self) -> str | None:
        if self.result is None:
            qualifier = None
        elif self.result.score is None:
            qualifier = "Incomplete"
        elif self.result.coverage < 1.0:
            graded = sum(
                case.grade is not None and case.grade.score is not None
                for case in self.result.cases
            )
            qualifier = f"{graded} / {len(self.result.cases)} graded"
        elif self.result.failures:
            qualifier = "Warnings"
        else:
            qualifier = None
        return qualifier

    @property
    def duration_seconds(self) -> float | None:
        if self.result is None:
            return None
        return (self.result.completed_at - self.result.started_at).total_seconds()

    @property
    def cache_totals(self) -> tuple[int, int, int] | None:
        if not self.cache_counts:
            return None
        return (
            sum(counts[0] for counts in self.cache_counts.values()),
            sum(counts[1] for counts in self.cache_counts.values()),
            sum(counts[2] for counts in self.cache_counts.values()),
        )

    @property
    def cache_hit_rate(self) -> float | None:
        totals = self.cache_totals
        if totals is None:
            return None
        hits, misses, _ = totals
        cacheable = hits + misses
        return None if cacheable == 0 else hits / cacheable

    @property
    def fully_cached(self) -> bool:
        totals = self.cache_totals
        if self.model_calls == 0 or totals is None:
            return False
        hits, misses, bypasses = totals
        cost_consistent = self.cost_usd is None or self.cost_usd == 0
        tokens_consistent = not self.have_tokens or (
            self.input_tokens == 0 and self.output_tokens == 0
        )
        return (
            hits == self.model_calls
            and misses == 0
            and bypasses == 0
            and cost_consistent
            and tokens_consistent
        )

    def observe(self, event: Event, elapsed_seconds: float | None = None) -> None:
        if isinstance(event, Started):
            self._observe_started(event, elapsed_seconds)
        elif isinstance(event, Log):
            self._observe_cache_log(event)
        elif isinstance(event, Usage):
            self._observe_usage(event)
        elif isinstance(event, Terminated):
            self._observe_terminated(event)
        elif isinstance(event, Span):
            self._observe_span(event)

    def begin(self) -> None:
        self.submitted = True
        self.activity = "Run submitted"

    def _observe_started(self, event: Started, elapsed_seconds: float | None) -> None:
        self.submitted = True
        self.started = True
        self.root_sources.add(event.source)
        self.activity = "Run started"
        self.started_elapsed_seconds = elapsed_seconds

    def _observe_terminated(self, event: Terminated) -> None:
        if event.source not in self.root_sources:
            return
        self.terminal_status = event.status
        self.activity = (
            "Run finished"
            if event.status == "succeeded"
            else f"Run {event.status.replace('_', ' ')}"
        )

    def _observe_span(self, event: Span) -> None:
        if event.operation == "RelUrlNode" and event.name == "/benchmarks/case-execution":
            self._observe_case_span(event)
        if event.request_model is not None:
            self._observe_model_span(event)

    def _observe_case_span(self, event: Span) -> None:
        self.completed_cases += 1
        if self.total_cases is not None:
            self.completed_cases = min(self.total_cases, self.completed_cases)
        if event.status == "error":
            self.failed_cases += 1
        unit = "case" if self.completed_cases == 1 else "cases"
        self.activity = (
            f"{self.completed_cases} {unit} finished"
            if self.total_cases is None
            else f"{self.completed_cases} / {self.total_cases} {unit} finished"
        )

    def _observe_model_span(self, event: Span) -> None:
        self._observe_cache_status(event)
        self.model_calls += 1
        if event.status == "error":
            self.failed_calls += 1
        if event.refusal is not None:
            self.refusals += 1
        if event.input_tokens is not None:
            self.input_tokens += event.input_tokens
            self.have_tokens = True
        if event.output_tokens is not None:
            self.output_tokens += event.output_tokens
            self.have_tokens = True
        outcome = (
            "refused"
            if event.refusal is not None
            else "failed"
            if event.status == "error"
            else "finished"
        )
        self.activity = f"Model call {outcome}"

    def _observe_cache_log(self, event: Log) -> None:
        names = ("cache.hits", "cache.misses", "cache.bypasses")
        values = tuple(event.attributes.get(name) for name in names)
        if not all(isinstance(value, int) and not isinstance(value, bool) for value in values):
            return
        self.cache_counts[event.run_id] = cast(tuple[int, int, int], values)
        self.cache_bypass_reasons[event.run_id] = {
            key[len(_BYPASS_REASON_PREFIX) :]: value
            for key, value in event.attributes.items()
            if key.startswith(_BYPASS_REASON_PREFIX)
            and isinstance(value, int)
            and not isinstance(value, bool)
        }

    def _observe_cache_status(self, event: Span) -> None:
        if event.cache_status is None:
            return
        counts = list(self.cache_counts.get(event.run_id, (0, 0, 0)))
        counts[{"hit": 0, "miss": 1, "bypass": 2}[event.cache_status]] += 1
        self.cache_counts[event.run_id] = cast(tuple[int, int, int], tuple(counts))
        if event.cache_status != "bypass":
            return
        reason = (event.cache_reason or "").strip() or UNSTATED_BYPASS_REASON
        observed = self.cache_bypass_reasons.setdefault(event.run_id, {})
        observed[reason] = observed.get(reason, 0) + 1

    def _observe_usage(self, event: Usage) -> None:
        if event.scope != "self" or event.usage.cost_usd is None:
            return
        amount = event.usage.cost_usd
        self.cost_usd = amount if self.cost_usd is None else self.cost_usd + amount

    def reconcile(self, result: CandidateResult) -> None:
        self.result = result
        self.total_cases = len(result.cases)
        self.completed_cases = self.total_cases
        if result.usage.cost_usd is not None:
            self.cost_usd = result.usage.cost_usd
        if result.usage.input_tokens is not None:
            self.input_tokens = result.usage.input_tokens
            self.have_tokens = True
        if result.usage.output_tokens is not None:
            self.output_tokens = result.usage.output_tokens
            self.have_tokens = True
        self.activity = "Result ready"

    def abort(self, exc: BaseException) -> None:
        if self.result is not None or self.status not in {"queued", "running"}:
            return
        if not self.submitted:
            self.workflow_status = "not_run"
            self.activity = "Not started"
            return
        if not self.started:
            self.workflow_status = "run_failed"
            self.activity = "Run outcome unavailable"
            return
        if isinstance(exc, KeyboardInterrupt):
            self.workflow_status = "stopped"
            self.activity = "Run stopped"
        elif isinstance(exc, TimeoutError):
            self.workflow_status = "timed_out"
            self.activity = "Run timed out"
        else:
            self.workflow_status = "run_failed"
            self.activity = "Run failed"


@dataclass(slots=True, init=False)
class _EvaluationProgress:
    case_count: int | None
    rows: tuple[_CandidateProgress, ...]
    _rows_by_name: dict[str, _CandidateProgress]
    error: str | None
    announcement: str

    def __init__(self, *, candidates: tuple[Candidate, ...], case_count: int | None) -> None:
        if not candidates:
            raise ValueError("live Evaluation progress requires at least one Candidate")
        if case_count is not None and (
            isinstance(case_count, bool) or not isinstance(case_count, int) or case_count < 1
        ):
            raise ValueError("live Evaluation progress case_count must be positive")
        rows = tuple(
            _CandidateProgress(candidate=candidate, total_cases=case_count)
            for candidate in candidates
        )
        self.case_count = case_count
        self.rows = rows
        self._rows_by_name = {row.candidate.name: row for row in rows}
        self.error = None
        self.announcement = ""

    def observe(
        self,
        candidate: Candidate,
        event: Event,
        *,
        elapsed_seconds: float | None = None,
    ) -> None:
        try:
            row = self._rows_by_name[candidate.name]
        except KeyError:
            raise ValueError(f"unknown Evaluation Candidate {candidate.name!r}") from None
        before = row.status
        row.observe(event, elapsed_seconds)
        after = row.status
        if isinstance(event, Started) and row.started:
            self.announcement = "Evaluation started"
        elif after != before and after not in {"queued", "running"}:
            self.announcement = f"{candidate.name} {after.replace('_', ' ')}"

    def begin(self, candidate: Candidate) -> None:
        try:
            row = self._rows_by_name[candidate.name]
        except KeyError:
            raise ValueError(f"unknown Evaluation Candidate {candidate.name!r}") from None
        row.begin()

    @property
    def finished(self) -> bool:
        return all(row.status not in {"queued", "running"} for row in self.rows)

    @property
    def complete(self) -> bool:
        return all(row.result is not None for row in self.rows)

    @property
    def duration_seconds(self) -> float | None:
        if not self.complete:
            return None
        results = tuple(row.result for row in self.rows if row.result is not None)
        started_at = min(result.started_at for result in results)
        completed_at = max(result.completed_at for result in results)
        return (completed_at - started_at).total_seconds()

    @property
    def model_calls(self) -> int:
        return sum(row.model_calls for row in self.rows)

    @property
    def failed_calls(self) -> int:
        return sum(row.failed_calls for row in self.rows)

    @property
    def input_tokens(self) -> int:
        return sum(row.input_tokens for row in self.rows)

    @property
    def output_tokens(self) -> int:
        return sum(row.output_tokens for row in self.rows)

    @property
    def have_tokens(self) -> bool:
        return any(row.have_tokens for row in self.rows)

    @property
    def cost_usd(self) -> Decimal | None:
        reported = tuple(row.cost_usd for row in self.rows if row.cost_usd is not None)
        return None if not reported else sum(reported, Decimal())

    @property
    def cache_totals(self) -> tuple[int, int, int] | None:
        reported = tuple(row.cache_totals for row in self.rows if row.cache_totals is not None)
        if not reported:
            return None
        return cast(
            tuple[int, int, int],
            tuple(sum(counts[index] for counts in reported) for index in range(3)),
        )

    @property
    def cache_hit_rate(self) -> float | None:
        totals = self.cache_totals
        if totals is None:
            return None
        hits, misses, _ = totals
        cacheable = hits + misses
        return None if cacheable == 0 else hits / cacheable

    @property
    def fully_cached(self) -> bool:
        return (
            self.complete
            and self.model_calls > 0
            and all(row.model_calls == 0 or row.fully_cached for row in self.rows)
        )

    @property
    def cache_bypass_breakdown(self) -> tuple[tuple[str, int], ...]:
        totals: dict[str, int] = {}
        for row in self.rows:
            for reasons in row.cache_bypass_reasons.values():
                for reason, count in reasons.items():
                    totals[reason] = totals.get(reason, 0) + count
        return tuple(sorted(totals.items(), key=lambda item: (-item[1], item[0])))

    def reconcile(self, report: Report) -> None:
        if self.case_count is not None and report.case_count != self.case_count:
            raise ValueError("final Report has the wrong selected Case count")
        results = {result.name: result for result in report.candidates}
        if set(results) != set(self._rows_by_name):
            raise ValueError("final Report has the wrong Candidates")
        self.case_count = report.case_count
        for row in self.rows:
            row.reconcile(results[row.candidate.name])
        self.announcement = "Evaluation complete"

    def abort(self, exc: BaseException) -> None:
        for row in self.rows:
            row.abort(exc)
        message = str(exc).strip()
        self.error = message or None
        self.announcement = "Evaluation stopped"


__all__: list[str] = []
