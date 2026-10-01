"""N independent samples of one model (OME-1289).

WHY a private module: a public ``screamingface.samples`` submodule would be shadowed by the
``sf.samples`` function in the package namespace.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from screamingface.model import Model

_MAX_SAMPLES = 256
_SEED_PARAM_ERROR = "samples() sets the seed; pass seeds= instead"


def samples(
    model: str | Model,
    n: int,
    *,
    seeds: Sequence[int] | None = None,
    temperature: float | None = None,
    prompts: Sequence[str] | None = None,
    params: Mapping[str, str | int | float | bool] | None = None,
) -> tuple[Model, ...]:
    """Build ``n`` Models of one route that differ in an integer ``seed``.

    A reducer over these members counts ``n`` real answers, not one cached answer ``n`` times.
    The seed is an ``int`` because the gateway's seed schema is ``integer``. A model whose
    provider does not accept ``seed`` fails the ordinary preflight with
    ``PlanningError(code="unsupported_model_parameter")`` before any request is sent.
    """

    count = _sample_count(n)
    base = model if isinstance(model, Model) else Model(model)
    if "seed" in base.params:
        raise ValueError(_SEED_PARAM_ERROR)
    selected_seeds = _sample_seeds(seeds, count)
    selected_prompts = _sample_prompts(prompts, count)
    shared = _sample_params(base, params, temperature)
    return tuple(
        Model(
            base.model,
            prompt=base.prompt if selected_prompts is None else selected_prompts[index],
            params={**shared, "seed": selected_seeds[index]},
        )
        for index in range(count)
    )


def _sample_count(n: object) -> int:
    if isinstance(n, bool) or not isinstance(n, int):
        raise TypeError("samples() n must be an int")
    if not 1 <= n <= _MAX_SAMPLES:
        raise ValueError(f"samples() n must be between 1 and {_MAX_SAMPLES}, not {n}")
    return n


def _sample_seeds(seeds: object, count: int) -> tuple[int, ...]:
    if seeds is None:
        return tuple(range(count))
    if isinstance(seeds, str | bytes) or not isinstance(seeds, Sequence):
        raise TypeError("samples() seeds must be a sequence of ints")
    if any(isinstance(seed, bool) or not isinstance(seed, int) for seed in seeds):
        raise TypeError("samples() seeds must be ints")
    if len(seeds) != count:
        raise ValueError(f"samples() got {len(seeds)} seeds for {count} samples")
    if len(set(seeds)) != count:
        raise ValueError("samples() seeds must be unique")
    return tuple(seeds)


def _sample_prompts(prompts: object, count: int) -> tuple[str, ...] | None:
    if prompts is None:
        return None
    if isinstance(prompts, str | bytes) or not isinstance(prompts, Sequence):
        raise TypeError("samples() prompts must be a sequence of strings")
    if len(prompts) != count:
        raise ValueError(f"samples() got {len(prompts)} prompts for {count} samples")
    return tuple(prompts)


def _sample_params(
    base: Model, params: object, temperature: object
) -> dict[str, str | int | float | bool]:
    if params is not None and not isinstance(params, Mapping):
        raise TypeError("samples() params must be a mapping or None")
    extra = {} if params is None else dict(params)
    if "seed" in extra:
        raise ValueError(_SEED_PARAM_ERROR)
    shared = {**base.params, **extra}
    if temperature is None:
        return shared
    if "temperature" in extra:
        raise ValueError("pass temperature either as temperature= or in params, not both")
    if isinstance(temperature, bool) or not isinstance(temperature, int | float):
        raise TypeError("samples() temperature must be a number")
    if not math.isfinite(temperature):
        raise ValueError("samples() temperature must be finite")
    return {**shared, "temperature": temperature}


__all__ = ["samples"]
