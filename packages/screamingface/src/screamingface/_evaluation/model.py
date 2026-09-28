"""Private compiled-Evaluation values and validation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, NoReturn

from url4 import Url4Error, build, render

from screamingface._candidate_policy import GenerationParams
from screamingface._named_values import _NamedValues
from screamingface.discovery import BenchmarkInfo
from screamingface.operation import OperationInfo, _operation_dag
from screamingface.recipe import Recipe

type CandidateKind = Literal["model", "fusion", "pipeline", "corrective_loop", "self_corrective"]


@dataclass(frozen=True, slots=True)
class _MemberProjection:
    """Compile-time identity for one direct Fusion member."""

    operation_id: str
    name: str
    kind: CandidateKind
    models: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _ModelParameterAssignment:
    """Explicit parameters attached to one compiled model-call operation."""

    operation_id: str
    model: str
    params: GenerationParams


@dataclass(frozen=True, slots=True, init=False)
class Candidate:
    """One internally compiled, independently runnable Candidate."""

    name: str
    kind: CandidateKind
    models: tuple[str, ...]
    url4: str
    operations: tuple[OperationInfo, ...]
    members: tuple[_MemberProjection, ...]
    parameter_assignments: tuple[_ModelParameterAssignment, ...]
    # FEATURE (OME-1193): the run's declared answer seed rides the Candidate the transport
    # already receives, so the run-transport protocol (and every fake implementing it)
    # never widens. None = unseeded, the default for every compiled Candidate.
    answer_seed: int | None

    def __init__(self) -> NoReturn:
        raise TypeError("Candidate values are derived internally; they are not constructed")

    def __repr__(self) -> str:
        return (
            f"Candidate(name={self.name!r}, kind={self.kind!r}, "
            f"models={len(self.models)}, operations={len(self.operations)})"
        )


class _Candidates(_NamedValues[Candidate]):
    """Ordered compiled Candidates behind one Evaluation."""

    def __init__(self, values: Sequence[Candidate]) -> None:
        super().__init__(
            values,
            empty_message="an Evaluation requires at least one Candidate",
            item_type=Candidate,
            type_message="Evaluation candidates must be compiled Candidate values",
            duplicate_label="Candidate",
        )


@dataclass(frozen=True, slots=True, init=False)
class _Evaluation:
    """One private, compiled Candidate comparison."""

    benchmark: BenchmarkInfo
    limit: int | None
    case_count: int
    candidates: _Candidates
    required_models: tuple[str, ...]

    def __init__(self) -> NoReturn:
        raise TypeError("Evaluation values are derived internally; they are not constructed")

    def __repr__(self) -> str:
        names = ", ".join(candidate.name for candidate in self.candidates)
        return (
            f"_Evaluation(benchmark={self.benchmark.id!r}, "
            f"cases={self.case_count}, candidates=[{names}])"
        )


def _compiled_operation(
    *,
    id: str,
    kind: str,
    label: str,
    depends_on: Sequence[str],
) -> OperationInfo:
    """Build one validated Operation from no-spend Candidate compilation."""

    return OperationInfo(id=id, kind=kind, label=label, depends_on=depends_on)


def _compiled_candidate(
    *,
    name: str,
    kind: CandidateKind,
    models: Sequence[str],
    url4: str,
    operations: Sequence[OperationInfo],
    members: Sequence[_MemberProjection] = (),
    parameter_assignments: Sequence[_ModelParameterAssignment] = (),
    known_operation_ids: Sequence[str] | None = None,
) -> Candidate:
    """Build one validated Candidate from its locally linked compilation."""

    selected_kind = _candidate_kind(kind)
    selected_models = _unique_texts(models, "Candidate models")
    if selected_kind == "model" and len(selected_models) != 1:
        raise ValueError("a planned Model Candidate must contain exactly one model route")
    candidate = object.__new__(Candidate)
    object.__setattr__(candidate, "name", _nonblank(name, "Candidate name"))
    object.__setattr__(candidate, "kind", selected_kind)
    object.__setattr__(candidate, "models", selected_models)
    object.__setattr__(candidate, "url4", _canonical_url4(url4, "Candidate"))
    object.__setattr__(candidate, "operations", _operation_dag(operations))
    selected_members = _candidate_members(members, selected_kind)
    operation_ids = {operation.id for operation in candidate.operations}
    known_ids = (
        operation_ids
        if known_operation_ids is None
        else set(_unique_texts(known_operation_ids, "Candidate known_operation_ids"))
    )
    if unknown := operation_ids - known_ids:
        raise ValueError(f"Candidate has unknown selected Operation ID {min(unknown)!r}")
    if unknown := {
        member.operation_id for member in selected_members if member.operation_id not in known_ids
    }:
        raise ValueError(f"Candidate member has unknown Operation ID {min(unknown)!r}")
    object.__setattr__(candidate, "members", selected_members)
    object.__setattr__(
        candidate,
        "parameter_assignments",
        _candidate_parameter_assignments(parameter_assignments, operation_ids),
    )
    object.__setattr__(candidate, "answer_seed", None)
    return candidate


def _answer_seed_value(value: object) -> int | None:
    """Validate a declared answer seed: any integer, or None for an unseeded run.

    WHY the explicit bool exclusion: ``bool`` is an ``int`` subclass, so ``True`` would
    type-check and then serialize as ``true`` — a sitting no engine run can have.
    """
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("answer_seed must be an integer or None")
    return value


def _with_answer_seed(candidate: Candidate, answer_seed: int) -> Candidate:
    """Copy one compiled Candidate with the run's declared sitting stamped on."""
    stamped = object.__new__(Candidate)
    for name in (
        "name",
        "kind",
        "models",
        "url4",
        "operations",
        "members",
        "parameter_assignments",
    ):
        object.__setattr__(stamped, name, getattr(candidate, name))
    object.__setattr__(stamped, "answer_seed", answer_seed)
    return stamped


def _candidate_members(
    values: Sequence[_MemberProjection],
    kind: CandidateKind,
) -> tuple[_MemberProjection, ...]:
    selected = tuple(values)
    if any(not isinstance(member, _MemberProjection) for member in selected):
        raise TypeError("Candidate members must contain only compiled member projections")
    if kind == "model" and selected:
        raise ValueError("a planned Model Candidate cannot contain members")
    if kind == "pipeline" and selected:
        raise ValueError("a planned Pipeline Candidate cannot contain direct Fusion members")
    if kind == "fusion" and not selected:
        raise ValueError("a planned Fusion Candidate requires at least one direct member")
    return selected


def _candidate_parameter_assignments(
    values: Sequence[_ModelParameterAssignment],
    operation_ids: set[str],
) -> tuple[_ModelParameterAssignment, ...]:
    assignments = tuple(values)
    if any(not isinstance(value, _ModelParameterAssignment) for value in assignments):
        raise TypeError("Candidate parameter_assignments must contain compiled assignments")
    if unknown := {value.operation_id for value in assignments} - operation_ids:
        raise ValueError(
            f"Candidate parameter assignment has unknown Operation ID {min(unknown)!r}"
        )
    return assignments


def _model_parameter_assignment(
    *,
    operation_id: str,
    model: str,
    params: Mapping[str, str | int | float | bool],
) -> _ModelParameterAssignment:
    selected = MappingProxyType(dict(params))
    if not selected:
        raise ValueError("Model parameter assignment must not be empty")
    return _ModelParameterAssignment(
        operation_id=_nonblank(operation_id, "Parameter assignment operation_id"),
        model=_nonblank(model, "Parameter assignment model"),
        params=selected,
    )


def _member_projection(
    *,
    operation_id: str,
    name: str,
    kind: CandidateKind,
    models: Sequence[str],
) -> _MemberProjection:
    return _MemberProjection(
        operation_id=_nonblank(operation_id, "Member operation_id"),
        name=_nonblank(name, "Member name"),
        kind=_candidate_kind(kind),
        models=_unique_texts(models, "Member models"),
    )


def _compiled_evaluation(
    *,
    benchmark: BenchmarkInfo,
    limit: int | None,
    case_count: int,
    candidates: Sequence[Candidate],
    required_models: Sequence[str],
) -> _Evaluation:
    """Build one validated private Evaluation after no-spend compilation."""

    if not isinstance(benchmark, BenchmarkInfo):
        raise TypeError("Evaluation benchmark must be an sf.BenchmarkInfo")
    _validate_limit(limit)
    selected_count = _positive_count(case_count, "Evaluation case_count")
    expected_count = benchmark.case_count if limit is None else min(limit, benchmark.case_count)
    if selected_count != expected_count:
        raise ValueError("Evaluation case_count must match its Benchmark and limit")
    evaluation = object.__new__(_Evaluation)
    values = {
        "benchmark": benchmark,
        "limit": limit,
        "case_count": selected_count,
        "candidates": _Candidates(candidates),
        "required_models": _unique_texts(
            required_models,
            "Evaluation required_models",
        ),
    }
    for name, value in values.items():
        object.__setattr__(evaluation, name, value)
    return evaluation


def _candidate_values(value: Recipe | Sequence[Recipe]) -> tuple[Recipe, ...]:
    if isinstance(value, Recipe):
        values = (value,)
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes):
        values = tuple(value)
    else:
        raise TypeError("candidates must be a complete sf.Recipe or an ordered sequence of Recipes")
    if not values:
        raise ValueError("an Evaluation requires at least one Candidate")
    if any(not isinstance(candidate, Recipe) for candidate in values):
        raise TypeError("candidates must contain only complete sf.Recipe values")
    names: set[str] = set()
    for candidate in values:
        if candidate.name in names:
            raise ValueError(f"duplicate Candidate name {candidate.name!r}")
        names.add(candidate.name)
    return values


def _validate_limit(limit: int | None) -> None:
    if limit is None:
        return
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise TypeError("limit must be a positive integer or None")
    if limit < 1:
        raise ValueError("limit must be a positive integer or None")


def _positive_count(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} must be a positive integer")
    if value < 1:
        raise ValueError(f"{label} must be a positive integer")
    return value


_CANDIDATE_KINDS: dict[str, CandidateKind] = {
    "model": "model",
    "fusion": "fusion",
    "pipeline": "pipeline",
    "corrective_loop": "corrective_loop",
    "self_corrective": "self_corrective",
}


def _candidate_kind(value: object) -> CandidateKind:
    if isinstance(value, str) and value in _CANDIDATE_KINDS:
        return _CANDIDATE_KINDS[value]
    raise ValueError(
        "Candidate kind must be 'model', 'fusion', 'pipeline', 'corrective_loop', "
        "or 'self_corrective'"
    )


def _nonblank(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    if not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _unique_texts(
    values: object,
    label: str,
    *,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    if isinstance(values, str | bytes) or not isinstance(values, Sequence):
        raise TypeError(f"{label} must be an ordered sequence of strings")
    selected = tuple(_nonblank(value, label) for value in values)
    if not selected and not allow_empty:
        raise ValueError(f"{label} must not be empty")
    if len(selected) != len(set(selected)):
        raise ValueError(f"{label} must be unique")
    return selected


def _canonical_url4(value: object, label: str) -> str:
    selected = _nonblank(value, f"{label} URL4")
    try:
        return render(build(selected))
    except Url4Error as exc:
        raise ValueError(f"{label} URL4 must be valid URL4: {exc}") from exc


__all__: list[str] = []
