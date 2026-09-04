"""Immutable public Report values."""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from os import PathLike
from pathlib import Path
from types import MappingProxyType
from typing import Literal, overload

from screamingface._evaluation.model import _canonical_url4
from screamingface._immutable_json import freeze_mapping, thaw_mapping
from screamingface._named_values import _NamedValues
from screamingface._operation_projection import _operation_dict, _require_operation_references
from screamingface._report_primitives import (
    CaseId,
    Failure,
    Usage,
    _case_id,
    _duration,
    _nonblank,
    _usage,
)
from screamingface.case_result import (
    CaseGrade,
    CaseResult,
    Check,
    Evidence,
    EvidenceProducer,
)
from screamingface.discovery import BenchmarkInfo
from screamingface.operation import OperationInfo, _operation_dag
from screamingface.operation_accounting import OperationAccounting, OperationCache
from screamingface.url4 import Url4

type RecipeKind = Literal["model", "fusion", "pipeline", "corrective_loop", "self_corrective"]


@dataclass(frozen=True, slots=True, init=False)
class MemberResult:
    """Compact outcome for one direct Fusion member.

    Runtime fields are ``None`` until the Engine attributes spans to this member's stable
    operation ID. An empty Usage or Failure collection means attribution was available and
    observed no activity or failures; it must not stand in for unavailable attribution.
    """

    operation_id: str
    name: str
    kind: RecipeKind
    models: tuple[str, ...]
    failures: tuple[Failure, ...] | None
    duration_ms: int | None
    usage: Usage | None

    def __init__(
        self,
        *,
        operation_id: str,
        name: str,
        kind: RecipeKind,
        models: Sequence[str],
        failures: Sequence[Failure] | None,
        duration_ms: int | None,
        usage: Usage | None,
    ) -> None:
        object.__setattr__(
            self,
            "operation_id",
            _nonblank(operation_id, "Member operation_id"),
        )
        object.__setattr__(self, "name", _nonblank(name, "Member name"))
        object.__setattr__(self, "kind", _kind(kind, "Member"))
        object.__setattr__(self, "models", _models(models, "Member"))
        object.__setattr__(
            self,
            "failures",
            None if failures is None else _failures(failures, "Member"),
        )
        object.__setattr__(self, "duration_ms", _duration(duration_ms, "Member"))
        object.__setattr__(self, "usage", None if usage is None else _usage(usage, "Member"))

    def to_dict(self) -> dict[str, object]:
        return {
            "operation_id": self.operation_id,
            "name": self.name,
            "kind": self.kind,
            "models": list(self.models),
            "failures": (
                None if self.failures is None else [failure.to_dict() for failure in self.failures]
            ),
            "duration_ms": self.duration_ms,
            "usage": None if self.usage is None else self.usage.to_dict(),
        }


class _CaseResults(Sequence[CaseResult]):
    """Ordered Case Results with explicit identity lookup.

    Integer ``[]`` access remains ordinary sequence position. Domain identity is
    intentionally spelled ``by_id(...)`` so an integer Case ID can never be
    mistaken for an index.
    """

    __slots__ = ("_by_id", "_items")

    def __init__(self, values: Sequence[CaseResult]) -> None:
        if isinstance(values, str | bytes) or not isinstance(values, Sequence):
            raise TypeError("Candidate cases must be an ordered sequence")
        items = tuple(values)
        if any(not isinstance(value, CaseResult) for value in items):
            raise TypeError("Candidate cases must contain sf.CaseResult values")
        if not items:
            raise ValueError("a Candidate Result requires at least one Case Result")
        by_id: dict[CaseId, CaseResult] = {}
        for item in items:
            if item.case_id in by_id:
                raise ValueError(f"duplicate Candidate Case Result id {item.case_id!r}")
            by_id[item.case_id] = item
        self._items = items
        self._by_id = MappingProxyType(by_id)

    @overload
    def __getitem__(self, index: int) -> CaseResult: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[CaseResult, ...]: ...

    def __getitem__(self, index: int | slice) -> CaseResult | tuple[CaseResult, ...]:
        return self._items[index]

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Iterator[CaseResult]:
        return iter(self._items)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, _CaseResults):
            return self._items == other._items
        if isinstance(other, Sequence):
            return self._items == tuple(other)
        return NotImplemented

    def __repr__(self) -> str:
        return repr(self._items)

    def by_id(self, case_id: CaseId) -> CaseResult:
        """Return the Case with this domain ID without treating integers as positions."""

        selected = _case_id(case_id)
        try:
            return self._by_id[selected]
        except KeyError:
            raise KeyError(f"unknown Case id {selected!r}") from None


@dataclass(frozen=True, slots=True, init=False)
class CandidateResult:
    """One independently executed Candidate outcome; a higher score is always better."""

    benchmark: BenchmarkInfo
    run_id: str
    trace_id: str | None
    started_at: datetime
    completed_at: datetime
    name: str
    kind: RecipeKind
    url4: Url4
    models: tuple[str, ...]
    operations: tuple[OperationInfo, ...]
    score: float | None
    coverage: float
    cases: _CaseResults
    members: tuple[MemberResult, ...]
    failures: tuple[Failure, ...]
    usage: Usage
    _metric_items: tuple[tuple[str, object], ...] = field(repr=False)

    def __init__(
        self,
        *,
        benchmark: BenchmarkInfo,
        run_id: str,
        started_at: datetime,
        completed_at: datetime,
        name: str,
        kind: RecipeKind,
        url4: str,
        models: Sequence[str],
        operations: Sequence[OperationInfo],
        score: float | None,
        coverage: float,
        metrics: Mapping[str, object],
        cases: Sequence[CaseResult],
        members: Sequence[MemberResult],
        failures: Sequence[Failure],
        usage: Usage,
        trace_id: str | None = None,
    ) -> None:
        if not isinstance(benchmark, BenchmarkInfo):
            raise TypeError("Candidate benchmark must be an sf.BenchmarkInfo")
        selected_score = _optional_number(score, "Candidate score")
        selected_coverage = _coverage(coverage)
        metric_items = _metrics(metrics)
        if selected_score is None and metric_items:
            raise ValueError("a failed or unscored Candidate cannot contain metrics")
        selected_kind, selected_models, selected_members, selected_failures = _candidate_shape(
            kind,
            models,
            members,
            failures,
        )
        selected_operations = _operation_dag(operations)
        selected_cases = _CaseResults(cases)
        _validate_candidate_outcome(
            selected_score,
            selected_coverage,
            metric_items,
            selected_cases,
        )
        _require_operation_references(
            selected_operations,
            selected_members,
            selected_failures,
        )
        start, end = _time_range(
            started_at,
            completed_at,
            label="Candidate",
        )
        values = {
            "benchmark": benchmark,
            "run_id": _nonblank(run_id, "Candidate run_id"),
            # WHY nullable and unvalidated (OME-1121): this is the id the CLIENT minted,
            # carried across the report boundary verbatim. A Report decoded from a stored
            # url4 replay has no live run behind it, and inventing a value would produce an
            # id that joins to nothing. Empty is normalized to None so callers have one
            # falsy case to test rather than two.
            "trace_id": trace_id or None,
            "started_at": start,
            "completed_at": end,
            "name": _nonblank(name, "Candidate name"),
            "kind": selected_kind,
            "url4": Url4(_canonical_url4(url4, "Candidate")),
            "models": selected_models,
            "operations": selected_operations,
            "score": selected_score,
            "coverage": selected_coverage,
            "cases": selected_cases,
            "members": selected_members,
            "failures": selected_failures,
            "usage": _usage(usage, "Candidate"),
            "_metric_items": metric_items,
        }
        for attribute, value in values.items():
            object.__setattr__(self, attribute, value)

    @property
    def metrics(self) -> Mapping[str, object]:
        return MappingProxyType(dict(self._metric_items))

    @property
    def duration_ms(self) -> int:
        return round((self.completed_at - self.started_at).total_seconds() * 1000)

    def to_dict(self) -> dict[str, object]:
        return {
            # INVARIANT: the two case_count values in a serialized Report mean different
            # things, and both are load-bearing. This candidate block carries the COMPLETE
            # Benchmark size; the Report root (see Report.to_dict) carries the SELECTED
            # Evaluation size. Their difference is what makes an exported limited run
            # recognisably partial on reload, which the submission advisory depends on.
            "benchmark": self.benchmark._result_dict(self.benchmark.case_count),
            "run_id": self.run_id,
            "started_at": _timestamp_text(self.started_at),
            "completed_at": _timestamp_text(self.completed_at),
            "name": self.name,
            "kind": self.kind,
            "url4": self.url4,
            "models": list(self.models),
            "operations": [_operation_dict(operation) for operation in self.operations],
            "score": self.score,
            "coverage": self.coverage,
            "metrics": thaw_mapping(dict(self._metric_items)),
            "cases": [case.to_dict() for case in self.cases],
            "members": [member.to_dict() for member in self.members],
            "failures": [failure.to_dict() for failure in self.failures],
            "duration_ms": self.duration_ms,
            "usage": self.usage.to_dict(),
        }


class _CandidateResults(_NamedValues[CandidateResult]):
    """Private collection behind Report.candidates."""

    def __init__(self, values: Sequence[CandidateResult]) -> None:
        super().__init__(
            values,
            empty_message="a Report requires at least one Candidate",
            item_type=CandidateResult,
            type_message="Report candidates must be sf.CandidateResult values",
            duplicate_label="Candidate",
        )


@dataclass(frozen=True, slots=True, init=False)
class Report:
    """One ordered collection of independently executed Candidate Results."""

    benchmark: BenchmarkInfo
    case_count: int
    candidates: _CandidateResults

    def __init__(
        self,
        *,
        benchmark: BenchmarkInfo,
        case_count: int,
        candidates: Sequence[CandidateResult],
    ) -> None:
        if not isinstance(benchmark, BenchmarkInfo):
            raise TypeError("Report benchmark must be an sf.BenchmarkInfo")
        benchmark._result_dict(case_count)
        selected_candidates = _CandidateResults(candidates)
        for candidate in selected_candidates:
            if candidate.benchmark != benchmark:
                raise ValueError("every Candidate Result must belong to the Report Benchmark")
            if len(candidate.cases) != case_count:
                raise ValueError(
                    "every Candidate Result must contain the Report's selected Case count"
                )
        values = {
            "benchmark": benchmark,
            "case_count": case_count,
            "candidates": selected_candidates,
        }
        for attribute, value in values.items():
            object.__setattr__(self, attribute, value)

    @property
    def started_at(self) -> datetime:
        return min(candidate.started_at for candidate in self.candidates)

    @property
    def completed_at(self) -> datetime:
        return max(candidate.completed_at for candidate in self.candidates)

    @property
    def duration_ms(self) -> int:
        return round((self.completed_at - self.started_at).total_seconds() * 1000)

    @property
    def usage(self) -> Usage:
        return _combined_usage(tuple(candidate.usage for candidate in self.candidates))

    @property
    def failures(self) -> tuple[Failure, ...]:
        flattened: list[Failure] = []
        for candidate in self.candidates:
            flattened.extend(candidate.failures)
            for member in candidate.members:
                if member.failures is not None:
                    flattened.extend(member.failures)
            for case in candidate.cases:
                flattened.extend(case.failures)
        return tuple(flattened)

    @property
    def ok(self) -> bool:
        return not self.failures and all(
            candidate.score is not None for candidate in self.candidates
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": "screamingface.report.v1",
            "started_at": _timestamp_text(self.started_at),
            "completed_at": _timestamp_text(self.completed_at),
            "benchmark": self.benchmark._result_dict(self.case_count),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "usage": self.usage.to_dict(),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))

    def export(self, path: str | PathLike[str] = "report.json") -> Path:
        """Write the complete Report JSON document and return its selected path.

        Parent directories are created as needed. An existing file is replaced so repeated
        notebook runs deterministically leave one current artifact.
        """

        selected = Path(path)
        if selected.suffix.lower() != ".json":
            raise ValueError("Report export path must be a .json file")
        selected.parent.mkdir(parents=True, exist_ok=True)
        selected.write_text(self.to_json(), encoding="utf-8")
        return selected

    def __repr__(self) -> str:
        candidates = ", ".join(repr(candidate.name) for candidate in self.candidates)
        return f"Report(benchmark={self.benchmark.id!r}, candidates=[{candidates}], ok={self.ok})"

    def _repr_html_(self) -> str:
        from screamingface._ui.report_view import report_html

        return report_html(self)


_RECIPE_KINDS: dict[str, RecipeKind] = {
    "model": "model",
    "fusion": "fusion",
    "pipeline": "pipeline",
    "corrective_loop": "corrective_loop",
    "self_corrective": "self_corrective",
}


def _kind(value: object, label: str) -> RecipeKind:
    if isinstance(value, str) and value in _RECIPE_KINDS:
        return _RECIPE_KINDS[value]
    raise ValueError(
        f"{label} kind must be 'model', 'fusion', 'pipeline', 'corrective_loop', "
        "or 'self_corrective'"
    )


def _models(values: Sequence[str], label: str) -> tuple[str, ...]:
    if isinstance(values, str | bytes) or not isinstance(values, Sequence):
        raise TypeError(f"{label} models must be an ordered sequence")
    selected = tuple(_nonblank(value, f"{label} model route") for value in values)
    if not selected:
        raise ValueError(f"{label} models must not be empty")
    if len(selected) != len(set(selected)):
        raise ValueError(f"{label} models must be unique")
    return selected


def _failures(values: Sequence[Failure], label: str) -> tuple[Failure, ...]:
    selected = tuple(values)
    if any(not isinstance(value, Failure) for value in selected):
        raise TypeError(f"{label} failures must be sf.Failure values")
    return selected


def _members(values: Sequence[MemberResult]) -> tuple[MemberResult, ...]:
    selected = tuple(values)
    if any(not isinstance(value, MemberResult) for value in selected):
        raise TypeError("Candidate members must be sf.MemberResult values")
    # WHY: display names are cosmetic and may collide (the same model reached via two
    # providers); identity is the operation_id. INVARIANT: fail-before-spend — this
    # constructor runs after the paid evaluation, so it must never reject a shape the
    # authoring constructors accepted. Collisions are disambiguated at render instead.
    operation_ids = [value.operation_id for value in selected]
    if len(operation_ids) != len(set(operation_ids)):
        raise ValueError("Candidate member operation IDs must be unique")
    return selected


def _candidate_shape(
    kind: object,
    models: Sequence[str],
    members: Sequence[MemberResult],
    failures: Sequence[Failure],
) -> tuple[
    RecipeKind,
    tuple[str, ...],
    tuple[MemberResult, ...],
    tuple[Failure, ...],
]:
    selected_kind = _kind(kind, "Candidate")
    selected_models = _models(models, "Candidate")
    selected_members = _members(members)
    selected_failures = _failures(failures, "Candidate")
    _validate_candidate_structure(selected_kind, selected_models, selected_members)
    _validate_candidate_failures(selected_failures)
    return selected_kind, selected_models, selected_members, selected_failures


def _validate_candidate_structure(
    kind: RecipeKind,
    models: Sequence[str],
    members: Sequence[MemberResult],
) -> None:
    _STRUCTURE_RULES[kind](models, members)


def _validate_model_candidate(models: Sequence[str], members: Sequence[MemberResult]) -> None:
    if len(models) != 1:
        raise ValueError("a Model Candidate must contain exactly one model route")
    if members:
        raise ValueError("a Model Candidate cannot contain members")


def _validate_fusion_candidate(models: Sequence[str], members: Sequence[MemberResult]) -> None:
    if not members:
        raise ValueError("a Fusion Candidate requires at least one direct member")


def _validate_pipeline_candidate(models: Sequence[str], members: Sequence[MemberResult]) -> None:
    if members:
        raise ValueError("a Pipeline Candidate cannot contain direct Fusion members")


def _validate_corrective_loop_candidate(
    models: Sequence[str], members: Sequence[MemberResult]
) -> None:
    if len(members) < 2:
        raise ValueError("a CorrectiveLoop Candidate requires at least two members")


def _validate_self_corrective_candidate(
    models: Sequence[str], members: Sequence[MemberResult]
) -> None:
    if members:
        raise ValueError("a SelfCorrective Candidate cannot contain members")


_STRUCTURE_RULES: dict[RecipeKind, Callable[[Sequence[str], Sequence[MemberResult]], None]] = {
    "model": _validate_model_candidate,
    "fusion": _validate_fusion_candidate,
    "pipeline": _validate_pipeline_candidate,
    "corrective_loop": _validate_corrective_loop_candidate,
    "self_corrective": _validate_self_corrective_candidate,
}


def _validate_candidate_failures(failures: Sequence[Failure]) -> None:
    if any(failure.case_id is not None for failure in failures):
        raise ValueError("a Candidate Failure cannot claim a Case id")


def _time_range(start: object, end: object, *, label: str) -> tuple[datetime, datetime]:
    selected_start = _timestamp(start, f"{label} started_at")
    selected_end = _timestamp(end, f"{label} completed_at")
    if selected_end < selected_start:
        raise ValueError(f"{label} completed_at cannot precede started_at")
    return selected_start, selected_end


def _combined_usage(values: tuple[Usage, ...]) -> Usage:
    """Sum fields only when every Candidate Run reported that field."""

    def total(name: str) -> int | None:
        observed = tuple(getattr(value, name) for value in values)
        if any(value is None for value in observed):
            return None
        return sum(value for value in observed if value is not None)

    costs = tuple(value.cost_usd for value in values)
    cost = (
        None
        if any(value is None for value in costs)
        else sum((value for value in costs if value is not None), Decimal())
    )
    return Usage(
        input_tokens=total("input_tokens"),
        output_tokens=total("output_tokens"),
        cache_read_tokens=total("cache_read_tokens"),
        cache_creation_tokens=total("cache_creation_tokens"),
        reasoning_tokens=total("reasoning_tokens"),
        cost_usd=cost,
    )


def _optional_number(value: object, label: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{label} must be a finite number or None")
    selected = float(value)
    if not math.isfinite(selected):
        raise ValueError(f"{label} must be a finite number or None")
    return selected


def _coverage(value: object) -> float:
    selected = _optional_number(value, "Candidate coverage")
    if selected is None:
        raise TypeError("Candidate coverage must be a finite number")
    if not 0.0 <= selected <= 1.0:
        raise ValueError("Candidate coverage must be between 0 and 1")
    return selected


def _validate_candidate_outcome(
    score: float | None,
    coverage: float,
    metrics: tuple[tuple[str, object], ...],
    cases: Sequence[CaseResult],
) -> None:
    """Independently enforce the Engine's Candidate Result wire invariants."""

    gradeable = tuple(
        case for case in cases if case.grade is not None and case.grade.score is not None
    )
    expected_coverage = round(len(gradeable) / len(cases), 4)
    if coverage != expected_coverage:
        raise ValueError(
            "Candidate coverage must equal numeric Case grades / selected Cases "
            f"({expected_coverage})"
        )
    if score is None:
        if gradeable:
            raise ValueError("an unscored Candidate cannot contain a numeric Case grade")
        if metrics:
            raise ValueError("a failed or unscored Candidate cannot contain metrics")
        return
    if not gradeable:
        raise ValueError("a scored Candidate requires at least one numeric Case grade")


def _metrics(values: Mapping[str, object]) -> tuple[tuple[str, object], ...]:
    if not isinstance(values, Mapping):
        raise TypeError("Candidate metrics must be a mapping")
    selected: dict[str, object] = {}
    for name, value in values.items():
        normalized_name = _nonblank(name, "Candidate metric name")
        if normalized_name == "coverage":
            raise ValueError("Candidate metrics cannot contain top-level field 'coverage'")
        if normalized_name in selected:
            raise ValueError(f"Candidate metric name {normalized_name!r} is duplicated")
        selected[normalized_name] = value
    frozen = freeze_mapping(selected, "Candidate metrics")
    return tuple(frozen.items())


def _timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{label} must be a timezone-aware datetime")
    return value


def _timestamp_text(value: datetime) -> str:
    text = value.isoformat()
    return text[:-6] + "Z" if text.endswith("+00:00") else text


__all__ = [
    "CaseGrade",
    "CaseResult",
    "CandidateResult",
    "Check",
    "Evidence",
    "EvidenceProducer",
    "Failure",
    "MemberResult",
    "OperationAccounting",
    "OperationCache",
    "OperationInfo",
    "Report",
    "Usage",
]
