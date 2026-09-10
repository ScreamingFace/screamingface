"""Free preflight of linked Candidate Models against Engine model details."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence

from screamingface._candidate_policy import GenerationParams
from screamingface._evaluation.model import Candidate
from screamingface.discovery import ModelDetails
from screamingface.errors import PlanningError

type _Assignments = dict[str, tuple[GenerationParams, ...]]
type _SyncDetailsLoading = Callable[[str], ModelDetails]
type _AsyncDetailsLoading = Callable[[str], Awaitable[ModelDetails]]


def preflight_sync(candidates: Sequence[Candidate], load: _SyncDetailsLoading) -> None:
    """Validate explicit parameters against each affected Model contract once."""

    assignments = _assignments(candidates)
    for model, selected in assignments.items():
        _validate_assignments(load(model), selected)


async def preflight_async(
    candidates: Sequence[Candidate],
    load: _AsyncDetailsLoading,
) -> None:
    """Asynchronous counterpart of :func:`preflight_sync`."""

    assignments = _assignments(candidates)
    models = tuple(assignments)
    if not models:
        return
    details = await asyncio.gather(*(load(model) for model in models))
    for model, selected in zip(models, details, strict=True):
        _validate_assignments(selected, assignments[model])


def _assignments(candidates: Sequence[Candidate]) -> _Assignments:
    grouped: dict[str, list[GenerationParams]] = {}
    for candidate in candidates:
        for assignment in candidate.parameter_assignments:
            grouped.setdefault(assignment.model, []).append(assignment.params)
    return {model: tuple(values) for model, values in grouped.items()}


def _validate_assignments(details: ModelDetails, assignments: tuple[GenerationParams, ...]) -> None:
    for values in assignments:
        for name, value in values.items():
            _validate_parameter(details, name, value)


def _validate_parameter(details: ModelDetails, name: str, value: object) -> None:
    parameter = details.parameters.get(name)
    if parameter is None:
        raise PlanningError(
            f"Parameter {name!r} is not available for Model {details.id!r}",
            code="unsupported_model_parameter",
            permanent=True,
            details={"model": details.id, "parameter": name},
        )
    if not parameter.enabled:
        raise PlanningError(
            f"Parameter {name!r} is disabled for Model {details.id!r}",
            code="unsupported_model_parameter",
            permanent=True,
            details={
                "model": details.id,
                "parameter": name,
                "reason": parameter.gateway_reason,
                "applicable_auth_modes": list(parameter.applicable_auth_modes),
            },
        )
    assert parameter.schema is not None
    try:
        parameter.schema.validate(value)
    except ValueError as exc:
        raise PlanningError(
            f"Parameter {name!r} for Model {details.id!r} {exc}",
            code="invalid_model_parameter",
            permanent=True,
            details={"model": details.id, "parameter": name},
        ) from exc


__all__: list[str] = []
