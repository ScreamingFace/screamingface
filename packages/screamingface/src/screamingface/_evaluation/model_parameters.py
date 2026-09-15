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


def preflight_sync(
    candidates: Sequence[Candidate],
    load: _SyncDetailsLoading,
    *,
    answer_seed: int | None = None,
) -> None:
    """Validate explicit parameters — and a declared answer seed — against each Model once.

    FEATURE (OME-1193 review round): a declared answer seed is stamped onto every answer
    call, so every candidate Model must carry an enabled `seed` in its gateway contract.
    Some routes never do (Anthropic's Messages API has no seed field), and without this
    gate the failure is a mid-run gateway error after spend — or worse, a silently
    unseeded sample. Checked ONLY when a seed is declared: unseeded evaluations keep
    today's behavior for seed-less models.
    """

    assignments = _assignments(candidates)
    seed_models = _seed_models(candidates) if answer_seed is not None else ()
    details_by_model: dict[str, ModelDetails] = {
        model: load(model) for model in _preflight_models(assignments, seed_models)
    }
    _validate(details_by_model, assignments, seed_models, answer_seed)


async def preflight_async(
    candidates: Sequence[Candidate],
    load: _AsyncDetailsLoading,
    *,
    answer_seed: int | None = None,
) -> None:
    """Asynchronous counterpart of :func:`preflight_sync`."""

    assignments = _assignments(candidates)
    seed_models = _seed_models(candidates) if answer_seed is not None else ()
    models = _preflight_models(assignments, seed_models)
    if not models:
        return
    details = await asyncio.gather(*(load(model) for model in models))
    details_by_model = dict(zip(models, details, strict=True))
    _validate(details_by_model, assignments, seed_models, answer_seed)


def _preflight_models(assignments: _Assignments, seed_models: tuple[str, ...]) -> tuple[str, ...]:
    """Every Model whose contract this preflight must fetch, each exactly once."""
    return tuple(dict.fromkeys((*assignments, *seed_models)))


def _seed_models(candidates: Sequence[Candidate]) -> tuple[str, ...]:
    """Every answer-producing Model a declared seed will be stamped onto."""
    return tuple(dict.fromkeys(model for candidate in candidates for model in candidate.models))


def _validate(
    details_by_model: dict[str, ModelDetails],
    assignments: _Assignments,
    seed_models: tuple[str, ...],
    answer_seed: int | None,
) -> None:
    """Run both checks off the once-fetched contracts: explicit params, then the seed."""
    for model, selected in assignments.items():
        _validate_assignments(details_by_model[model], selected)
    if answer_seed is not None:
        for model in seed_models:
            _validate_parameter(details_by_model[model], "seed", answer_seed)


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
