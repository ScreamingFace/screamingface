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

_PROVIDER_DENIED = "unsupported"
"""The one ``provider_support`` value that refuses a call (OME-1231).

The gateway states the distinction this constant turns into a rule
(`aigateway/core/chat_parameters/_types.py`): ``gateway_status`` carries POLICY — what the
gateway will forward — and ``provider_support`` carries EVIDENCE — what the provider's own
catalogue says about THIS model. They are not the same claim, and evidence is the only per-model
signal: OpenRouter rules `seed` as a blanket passthrough for every model it serves, so policy is
``enabled`` even where the provider accepts no seed at all.

POLICY for the other three values, decided rather than fallen into: ``supported`` obviously
passes. ``unknown`` passes SILENTLY — it is what the field holds when no discovery source spoke,
so refusing on it would refuse on our own ignorance and block models that work today.
``conditional`` passes silently too — the provider does accept the parameter, under a condition a
catalogue row cannot express, so refusing would be a false negative.
"""

_SEED_PARAM = "seed"
"""The sampling seed's wire name — the one parameter whose denial costs reproducibility.

The name is the GATEWAY contract's own key for this parameter (each provider plugin rules it as
``seed``), which is also what the Engine's ``ANSWER_SEED_PARAM`` spells. Both sides bind to the
contract independently rather than to each other, so this is a lookup key, not a copy of the
Engine's constant. A run's ambient seed and a Candidate-declared ``seed`` land on that same key,
so a denial means the same thing to the reader whichever door it arrived through.
"""


def preflight_sync(
    candidates: Sequence[Candidate],
    load: _SyncDetailsLoading,
    *,
    answer_seed: int | None = None,
    prefetched: Mapping[str, ModelDetails] | None = None,
) -> None:
    """Validate access, explicit parameters and any answer seed against each Model once.

    FEATURE (OME-1193 review round): a declared answer seed is stamped onto every answer
    call, so every candidate Model must carry an enabled `seed` in its gateway contract.
    Some routes never do (Anthropic's Messages API has no seed field), and without this
    gate the failure is a mid-run gateway error after spend — or worse, a silently
    unseeded sample. Checked ONLY when a seed is declared: unseeded evaluations keep
    today's behavior for seed-less models.
    """

    assignments = _assignments(candidates)
    seed_models = _seed_models(candidates) if answer_seed is not None else ()
    known = prefetched if prefetched is not None else {}
    details_by_model: dict[str, ModelDetails] = {}
    for model in _preflight_models(candidates, assignments):
        details = known.get(model)
        details_by_model[model] = load(model) if details is None else details
    _validate(details_by_model, assignments, seed_models, answer_seed)


async def preflight_async(
    candidates: Sequence[Candidate],
    load: _AsyncDetailsLoading,
    *,
    answer_seed: int | None = None,
    prefetched: Mapping[str, ModelDetails] | None = None,
) -> None:
    """Asynchronous counterpart of :func:`preflight_sync`."""

    assignments = _assignments(candidates)
    seed_models = _seed_models(candidates) if answer_seed is not None else ()
    models = _preflight_models(candidates, assignments)
    if not models:
        return
    details_by_model = dict(prefetched) if prefetched is not None else {}
    missing = tuple(model for model in models if model not in details_by_model)
    details = await asyncio.gather(*(load(model) for model in missing))
    details_by_model.update(zip(missing, details, strict=True))
    _validate(details_by_model, assignments, seed_models, answer_seed)


def _preflight_models(
    candidates: Sequence[Candidate], assignments: _Assignments
) -> tuple[str, ...]:
    """Check access for every required Model, including parameter-free evaluations."""
    return tuple(dict.fromkeys((*_seed_models(candidates), *assignments)))


def _seed_models(candidates: Sequence[Candidate]) -> tuple[str, ...]:
    """Every answer-producing Model a declared seed will be stamped onto."""
    return tuple(dict.fromkeys(model for candidate in candidates for model in candidate.models))


def _validate(
    details_by_model: dict[str, ModelDetails],
    assignments: _Assignments,
    seed_models: tuple[str, ...],
    answer_seed: int | None,
) -> None:
    """Validate access, explicit parameters and answer seed from once-fetched contracts."""
    for details in details_by_model.values():
        _validate_access(details)
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
    """Admit one parameter value for one Model, or refuse pre-spend saying which gate closed.

    Think of it as four doors a value walks through in order, each answering a different
    question, and the first closed door is the refusal the caller sees.

    Stage 1 — does the contract name this parameter at all? An absent row means the gateway
    publishes no projection for it on this Model, so nothing downstream could honour it.

    Stage 2 — does the GATEWAY forward it? `ModelParameter.enabled` is ``gateway_status ==
    "enabled"``; a disabled row carries the reason and the auth modes that WOULD enable it, so the
    refusal can say which credential would open the door rather than dead-ending.

    Stage 3 — does the PROVIDER accept it? (OME-1231.) This is the axis stages 1 and 2 cannot
    see. Only `_PROVIDER_DENIED` refuses; see that constant for why `conditional` and `unknown`
    pass. Without this stage a seeded fusion containing a model whose provider takes no seed
    reached the wire, and the run died mid-flight AFTER billing the members that worked — the
    catalogue held the verdict the whole time.

    Stage 4 — is the VALUE itself legal? Only now, because a value's validity is moot once a
    door above has closed.

    Args:
        details: the Model's profile-bound parameter contract, already fetched by the caller.
        name: the parameter's wire name, e.g. ``"seed"``.
        value: the value the run intends to send, checked against the published schema in
            stage 4 only.

    Raises:
        PlanningError: ``unsupported_model_parameter`` when a door in stages 1-3 is closed,
            ``invalid_model_parameter`` when stage 4 rejects the value. Always ``permanent``:
            retrying the same request cannot change any of these answers.
    """
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
    # Stage 3 — the provider's own evidence, the axis the two checks above cannot see.
    if parameter.provider_support == _PROVIDER_DENIED:
        raise PlanningError(
            _denied_message(details.id, name),
            code="unsupported_model_parameter",
            permanent=True,
            details={
                "model": details.id,
                "parameter": name,
                "provider_support": parameter.provider_support,
                # WHY the source travels with the verdict: this refusal contradicts the
                # gateway's own `enabled` status, so a reader needs to know which document
                # said no before they trust it over the projection.
                "provider_source": parameter.provider_source,
            },
            # WHY staleness rides the HINT rather than `details`: `provider_stale` is the
            # cache's verdict about THIS read, so a `true` means the refusal may describe a
            # catalogue that has since moved — which is advice about what to DO next, not a
            # fact about the parameter. `details` stays the parameter's own identity.
            hint=_denied_hint(name, stale=parameter.provider_stale),
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


def _denied_message(model: str, name: str) -> str:
    """Name the provider's refusal, adding what it costs when the parameter is the seed."""
    denial: str = f"Parameter {name!r} is not supported by the provider for Model {model!r}"
    if name == _SEED_PARAM:
        return f"{denial} — this run cannot be reproducible"
    return denial


def _denied_hint(name: str, *, stale: bool) -> str:
    """Offer the ways out: stop asking for the parameter, or pick a Model that takes it."""
    if name == _SEED_PARAM:
        hint: str = (
            "Drop the seed to run this line-up unseeded, or swap that Model for one whose "
            "provider accepts a seed."
        )
    else:
        hint = f"Remove {name!r} for that Model, or choose a Model whose provider accepts it."
    if not stale:
        return hint
    # WHY the reader needs this and not just the `details` payload: a stale verdict can refuse a
    # run that would work today, and from the message alone the only visible fix is swapping a
    # Model that may be perfectly fine.
    return (
        f"{hint} This verdict comes from a catalogue read marked stale, so refreshing it may "
        "change the answer."
    )


__all__: list[str] = []
