"""Exact, derived views of retained completed-Report accounting (OME-1031).

These views never serialize another accounting truth or recompute a score.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Hashable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal

from screamingface._report_primitives import CaseId, Usage
from screamingface.case_result import CaseResult
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


def member_usage(cases: Iterable[CaseResult], operation_id: str) -> Usage | None:
    """Stream exact operation observations; retain only nullable field totals."""
    totals = Usage(
        input_tokens=0,
        output_tokens=0,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        reasoning_tokens=0,
        cost_usd=Decimal(0),
    )
    seen = False
    for case in cases:
        matches = (op for op in case.operations or () if op.operation_id == operation_id)
        match = next(matches, None)
        if match is None or match.accounting is None or next(matches, None) is not None:
            return None
        usage = match.accounting.usage
        # INVARIANT: a missing observation poisons only its field; known zero stays zero.
        totals = Usage(
            input_tokens=_add(totals.input_tokens, usage.input_tokens),
            output_tokens=_add(totals.output_tokens, usage.output_tokens),
            cache_read_tokens=_add(totals.cache_read_tokens, usage.cache_read_tokens),
            cache_creation_tokens=_add(totals.cache_creation_tokens, usage.cache_creation_tokens),
            reasoning_tokens=_add(totals.reasoning_tokens, usage.reasoning_tokens),
            cost_usd=_add(totals.cost_usd, usage.cost_usd),
        )
        seen = True
    return totals if seen else None


def _add[T: (int, Decimal)](left: T | None, right: T | None) -> T | None:
    return None if left is None or right is None else left + right


def _declared_operation_models(candidate: CandidateResult) -> dict[str, str]:
    declarations: dict[str, list[str]] = {}
    for member in candidate.members:
        if member.kind == "model":
            declarations.setdefault(member.operation_id, []).extend(member.models)
    if candidate.kind == "model" and len(candidate.operations) == 1:
        declarations[candidate.operations[0].id] = list(candidate.models)
    models = {key: values[0] for key, values in declarations.items() if len(values) == 1}
    for case in candidate.cases:
        for op in case.operations or ():
            if op.accounting is not None and op.accounting.request_model != models.get(
                op.operation_id
            ):
                models.pop(op.operation_id, None)
    return models


def _declared_judge_models(candidate: CandidateResult) -> dict[str, str]:
    models: dict[str, str] = {}
    conflicts: set[str] = set()
    # INVARIANT: judge evidence is streamed; raw outputs never accumulate across Cases.
    for case in candidate.cases:
        if case.grade is None:
            continue
        for check in case.grade.checks:
            for item in check.evidence:
                if item.producer.type != "model":
                    continue
                name = item.producer.id
                if item.accounting is not None and item.accounting.request_model != name:
                    conflicts.add(name)
                    models.pop(name, None)
                elif name not in conflicts:
                    models[name] = name
    return models


def _candidate_rows(
    candidate: CandidateResult, case: CaseResult, models: Mapping[str, str]
) -> list[AccountingRow]:
    operations = {op.id: op for op in candidate.operations}
    retained = {op.operation_id: op for op in case.operations or ()}
    if len(retained) != len(case.operations or ()):
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


def _grading_rows(case: CaseResult, models: Mapping[str, str]) -> list[AccountingRow]:
    rows = []
    if case.grade is None:
        return rows
    for check in case.grade.checks:
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


@dataclass(frozen=True, slots=True)
class _AccountingContext:
    operation_models: Mapping[str, str]
    judge_models: Mapping[str, str]
    unattributed_cost_usd: Decimal | None
    consistent: bool = True


def _iter_rows(
    candidate: CandidateResult,
    cases: Iterable[CaseResult],
    operation_models: Mapping[str, str],
    judge_models: Mapping[str, str],
) -> Iterator[AccountingRow]:
    for case in cases:
        # INVARIANT: loop internals are not attributable by this retained contract.
        if candidate.kind not in {"corrective_loop", "self_corrective"}:
            yield from _candidate_rows(candidate, case, operation_models)
        yield from _grading_rows(case, judge_models)


def _rows(candidate: CandidateResult) -> tuple[AccountingRow, ...]:
    return tuple(
        _iter_rows(
            candidate,
            candidate.cases,
            _declared_operation_models(candidate),
            _declared_judge_models(candidate),
        )
    )


def _remainder(root: Decimal | None, rows: Iterable[AccountingRow]) -> Decimal | None:
    total, unknown = Decimal(0), False
    for row in rows:
        if row.accounting is not None:
            cost = row.accounting.usage.cost_usd
            if cost is None:
                unknown = True
            elif root is not None:
                total += cost
    if root is None or unknown:
        return None
    result = root - total
    if result < 0:
        raise ValueError("inconsistent accounting cost")
    return result


def _accounting_context(candidate: CandidateResult) -> _AccountingContext:
    # WHY: pages reuse only global attribution/consistency, never rows or Case payloads.
    try:
        operations = _declared_operation_models(candidate)
        judges = _declared_judge_models(candidate)
        remainder = _remainder(
            candidate.usage.cost_usd,
            _iter_rows(candidate, candidate.cases, operations, judges),
        )
        return _AccountingContext(MappingProxyType(operations), MappingProxyType(judges), remainder)
    except ValueError:
        _LOG.warning("completed accounting projection unavailable: ValueError")
        return _AccountingContext({}, {}, None, consistent=False)


def accounting_breakdown(candidate: CandidateResult) -> AccountingBreakdown:
    """Project retained, disjoint Engine owners; inconsistent data disables this view."""
    try:
        rows = _rows(candidate)
        return AccountingBreakdown(rows, _remainder(candidate.usage.cost_usd, rows))
    except ValueError:
        # INVARIANT: bookkeeping cannot fail a Report; diagnostics contain no payload.
        _LOG.warning("completed accounting projection unavailable: ValueError")
        return AccountingBreakdown((), None, consistent=False)
