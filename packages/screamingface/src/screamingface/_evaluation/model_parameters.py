"""Free preflight of linked Candidate Models against Engine model details."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence

from screamingface._candidate_policy import GenerationParams
from screamingface._evaluation.model import Candidate
from screamingface.discovery import ModelDetails
from screamingface.errors import PlanningError, ProviderConnectionError

type _Assignments = dict[str, tuple[GenerationParams, ...]]
type _SyncDetailsLoading = Callable[[str], ModelDetails]
type _AsyncDetailsLoading = Callable[[str], Awaitable[ModelDetails]]


def preflight_sync(
    candidates: Sequence[Candidate],
    load: _SyncDetailsLoading,
    prefetched: Mapping[str, ModelDetails] | None = None,
) -> None:
    """Check provider access and explicit parameters for every required Model."""

    known = prefetched or {}
    assignments = _assignments(candidates)
    for model, selected in assignments.items():
        _validate_assignments(known.get(model) or load(model), selected)


async def preflight_async(
    candidates: Sequence[Candidate],
    load: _AsyncDetailsLoading,
    prefetched: Mapping[str, ModelDetails] | None = None,
) -> None:
    """Asynchronous counterpart of :func:`preflight_sync`."""

    assignments = _assignments(candidates)
    models = tuple(assignments)
    if not models:
        return
    known = dict(prefetched or {})
    missing = tuple(model for model in models if model not in known)
    details = await asyncio.gather(*(load(model) for model in missing))
    known.update(zip(missing, details, strict=True))
    for model in models:
        _validate_assignments(known[model], assignments[model])


def _assignments(candidates: Sequence[Candidate]) -> _Assignments:
    grouped: dict[str, list[GenerationParams]] = {}
    for candidate in candidates:
        for model in candidate.models:
            grouped.setdefault(model, [])
        for assignment in candidate.parameter_assignments:
            grouped.setdefault(assignment.model, []).append(assignment.params)
    return {model: tuple(values) for model, values in grouped.items()}


def _validate_assignments(details: ModelDetails, assignments: tuple[GenerationParams, ...]) -> None:
    _validate_access(details)
    for values in assignments:
        for name, value in values.items():
            _validate_parameter(details, name, value)


def _validate_access(details: ModelDetails) -> None:
    # FEATURE: OME-1042 fails before observers or Candidate dispatch, including
    # parameter-free recipes. Only Gateway's authoritative absence may reject;
    # hosted/profileless configuration and legacy unknown access remain valid.
    if details.execution_access == "missing":
        raise ProviderConnectionError(
            f"Provider {details.provider!r} is not connected for Model {details.id!r}",
            provider=details.provider,
            code="provider_not_connected",
            permanent=True,
            details={"model": details.id, "provider": details.provider},
            hint=(
                "Open sf.connect() to configure provider access, or enable the selected "
                "provider profile on your hosted Engine, then retry."
            ),
        )


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
