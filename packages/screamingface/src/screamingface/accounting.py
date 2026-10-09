"""Exact, derived views of retained completed-Report accounting (OME-1031).

These views never serialize another accounting truth or recompute a score.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal

from screamingface._report_primitives import CaseId, Usage
from screamingface.case_result import CaseGrade, CaseOperation, CaseResult
from screamingface.operation_accounting import OperationAccounting, OperationCache

if TYPE_CHECKING:
    from screamingface.report import CandidateResult

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AccountingRow:
    """One semantic owner; a missing record remains explicitly unavailable."""

    case_id: CaseId
    stage: Literal["generation", "synthesis", "grading"]
    operation_id: str
    label: str
    member_id: str | None
    model: str | None
    accounting: OperationAccounting | None


@dataclass(frozen=True, slots=True)
class AccountingSummary:
    """Strict field-wise totals over a group, not estimates of absent work."""

    usage: Usage
    calls: int | None
    cache: OperationCache | None
    provider_latency_ms: int | None
    provider_attempts: int | None


@dataclass(frozen=True, slots=True)
class AccountingBreakdown:
    """Immutable, non-serialized views for one Candidate's retained accounting."""

    rows: tuple[AccountingRow, ...]
    unattributed_cost_usd: Decimal | None
    consistent: bool = True

    @property
    def by_stage(self) -> Mapping[str, AccountingSummary]:
        return _group(self.rows, lambda row: row.stage)

    @property
    def by_operation(self) -> Mapping[tuple[str, str], AccountingSummary]:
        return _group(self.rows, lambda row: (row.stage, row.operation_id))

    @property
    def by_model(self) -> Mapping[str | None, AccountingSummary]:
        groups = _group(self.rows, lambda row: row.model)
        if None not in groups:
            return groups
        # INVARIANT: an anonymous call could belong to any named model. Its own
        # bucket remains a strict observation summary, never a named model total.
        unknown = summarize([None])
        return MappingProxyType(
            {model: summary if model is None else unknown for model, summary in groups.items()}
        )

    @property
    def by_member(self) -> Mapping[str, AccountingSummary]:
        return _group(
            tuple(row for row in self.rows if row.member_id is not None),
            lambda row: row.member_id or "",
        )

    @property
    def by_case(self) -> Mapping[CaseId, AccountingSummary]:
        return _group(self.rows, lambda row: row.case_id)


def _group[K: Hashable](
    rows: tuple[AccountingRow, ...],
    key: Callable[[AccountingRow], K],
) -> Mapping[K, AccountingSummary]:
    groups: dict[K, list[OperationAccounting | None]] = {}
    for row in rows:
        groups.setdefault(key(row), []).append(row.accounting)
    return MappingProxyType({name: summarize(values) for name, values in groups.items()})


def _sum_counts(values: Sequence[int | None]) -> int | None:
    if not values or any(value is None for value in values):
        return None
    return sum(value for value in values if value is not None)


def _sum_costs(values: Sequence[Decimal | None]) -> Decimal | None:
    if not values or any(value is None for value in values):
        return None
    return sum((value for value in values if value is not None), Decimal(0))


def _usage_sum(values: Sequence[Usage]) -> Usage:
    # INVARIANT: missing observations poison each affected field, never become zero.
    return Usage(
        input_tokens=_sum_counts([v.input_tokens for v in values]),
        output_tokens=_sum_counts([v.output_tokens for v in values]),
        cache_read_tokens=_sum_counts([v.cache_read_tokens for v in values]),
        cache_creation_tokens=_sum_counts([v.cache_creation_tokens for v in values]),
        reasoning_tokens=_sum_counts([v.reasoning_tokens for v in values]),
        cost_usd=_sum_costs([v.cost_usd for v in values]),
    )


def summarize(values: Sequence[OperationAccounting | None]) -> AccountingSummary:
    """Aggregate only complete observations; preserve per-field unknowns."""
    if not values or any(value is None for value in values):
        return AccountingSummary(Usage(), None, None, None, None)
    known = [value for value in values if value is not None]
    cache = OperationCache(
        hits=sum(v.cache.hits for v in known),
        misses=sum(v.cache.misses for v in known),
        bypasses=sum(v.cache.bypasses for v in known),
        unknown=sum(v.cache.unknown for v in known),
    )
    return AccountingSummary(
        _usage_sum([v.usage for v in known]),
        cache.hits + cache.misses + cache.bypasses + cache.unknown,
        cache,
        _sum_counts([v.provider_latency_ms for v in known]),
        _sum_counts([v.provider_attempts for v in known]),
    )


@dataclass(frozen=True, slots=True)
class _BilledAnswer:
    """One answer the Candidate was billed for: its model calls and the grade marking it."""

    operations: tuple[CaseOperation, ...] | None
    grade: CaseGrade | None


def _billed_answers(case: CaseResult) -> tuple[_BilledAnswer, ...]:
    """The answers a Case paid for: the Case itself, or each of its Attempts.

    WHY (OME-1458): a Case with Attempts carries its cost records on each Attempt and none
    of its own, and its folded grade's evidence is a view of an Attempt's evidence. Reading
    the Attempts, never the Case-level fields, bills every model call exactly once.
    Worked example: two Attempts, each one call costing $0.01 → two generation rows, $0.02
    for the Case; the folded Check's judge evidence is not counted a third time.
    """

    if case.attempts is None:
        return (_BilledAnswer(case.operations, case.grade),)
    return tuple(_BilledAnswer(item.operations, item.grade) for item in case.attempts)


def member_usage(cases: Sequence[CaseResult], operation_id: str) -> Usage | None:
    """Use exact operation identity in every answer; never infer subtree ownership."""
    records: list[OperationAccounting] = []
    for case in cases:
        for answer in _billed_answers(case):
            matches = [op for op in answer.operations or () if op.operation_id == operation_id]
            if len(matches) != 1 or matches[0].accounting is None:
                return None
            records.append(matches[0].accounting)
    return _usage_sum([v.usage for v in records]) if records else None


def _declared_operation_models(candidate: CandidateResult) -> dict[str, str]:
    declarations: dict[str, list[str]] = {}
    for member in candidate.members:
        if member.kind == "model":
            declarations.setdefault(member.operation_id, []).extend(member.models)
    if candidate.kind == "model" and len(candidate.operations) == 1:
        declarations[candidate.operations[0].id] = list(candidate.models)
    models = {key: values[0] for key, values in declarations.items() if len(values) == 1}
    for case in candidate.cases:
        for op in (op for answer in _billed_answers(case) for op in answer.operations or ()):
            if op.accounting is not None and op.accounting.request_model != models.get(
                op.operation_id
            ):
                models.pop(op.operation_id, None)
    return models


def _declared_judge_models(candidate: CandidateResult) -> dict[str, str]:
    evidence = [
        item
        for case in candidate.cases
        for answer in _billed_answers(case)
        if answer.grade is not None
        for check in answer.grade.checks
        for item in check.evidence
        if item.producer.type == "model"
    ]
    models = {item.producer.id: item.producer.id for item in evidence}
    for item in evidence:
        if item.accounting is not None and item.accounting.request_model != item.producer.id:
            models.pop(item.producer.id, None)
    return models


def _candidate_rows(
    candidate: CandidateResult,
    case: CaseResult,
    answer: _BilledAnswer,
    models: Mapping[str, str],
) -> list[AccountingRow]:
    operations = {op.id: op for op in candidate.operations}
    retained = {op.operation_id: op for op in answer.operations or ()}
    if len(retained) != len(answer.operations or ()):
        raise ValueError("duplicate accounting operation")
    if set(retained) - operations.keys():
        raise ValueError("unknown accounting operation")
    members = {m.operation_id for m in candidate.members if m.kind == "model"}
    rows = []
    for op in candidate.operations:
        if op.kind not in {"model", "synthesis"}:
            continue
        record = retained.get(op.id)
        value = record.accounting if record else None
        rows.append(
            AccountingRow(
                case.case_id,
                "synthesis" if op.kind == "synthesis" else "generation",
                op.id,
                op.label,
                op.id if op.id in members else None,
                value.request_model if value else models.get(op.id),
                value,
            )
        )
    return rows


def _grading_rows(
    case: CaseResult, grade: CaseGrade | None, models: Mapping[str, str]
) -> list[AccountingRow]:
    rows = []
    if grade is None:
        return rows
    for check in grade.checks:
        for evidence in check.evidence:
            value = evidence.accounting
            # WHY: deterministic checks make no model call. A missing model observation
            # is unknown; an ordinary deterministic check must not imply a paid call.
            if value is None and evidence.producer.type != "model":
                continue
            rows.append(
                AccountingRow(
                    case.case_id,
                    "grading",
                    check.id,
                    check.label,
                    None,
                    value.request_model if value else models.get(evidence.producer.id),
                    value,
                )
            )
    return rows


def _rows(candidate: CandidateResult) -> tuple[AccountingRow, ...]:
    # WHY: declarations may name a different route than retained requests. Resolve
    # across all Cases first so a missing record cannot split into an alias bucket.
    operation_models = _declared_operation_models(candidate)
    judge_models = _declared_judge_models(candidate)
    rows = []
    for case in candidate.cases:
        for answer in _billed_answers(case):
            # INVARIANT: loop internals are not attributable by this retained contract.
            if candidate.kind not in {"corrective_loop", "self_corrective"}:
                rows.extend(_candidate_rows(candidate, case, answer, operation_models))
            rows.extend(_grading_rows(case, answer.grade, judge_models))
    return tuple(rows)


def _remainder(root: Decimal | None, rows: tuple[AccountingRow, ...]) -> Decimal | None:
    costs = [row.accounting.usage.cost_usd for row in rows if row.accounting is not None]
    if root is None or any(cost is None for cost in costs):
        return None
    result = root - sum((cost for cost in costs if cost is not None), Decimal(0))
    if result < 0:
        raise ValueError("inconsistent accounting cost")
    return result


def accounting_breakdown(candidate: CandidateResult) -> AccountingBreakdown:
    """Project retained, disjoint Engine owners; inconsistent data disables this view."""
    try:
        rows = _rows(candidate)
        return AccountingBreakdown(rows, _remainder(candidate.usage.cost_usd, rows))
    except ValueError:
        # INVARIANT: bookkeeping cannot fail a Report; diagnostics contain no payload.
        _LOG.warning("completed accounting projection unavailable: ValueError")
        return AccountingBreakdown((), None, consistent=False)
