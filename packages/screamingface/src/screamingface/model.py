"""Atomic model-backed Candidate values."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar

from screamingface._candidate_policy import GenerationParams
from screamingface._candidate_policy import params as _generation_params
from screamingface._candidate_policy import prompt as _generation_prompt
from screamingface.recipe import Recipe, _model_route, _name, _optional


@dataclass(frozen=True, slots=True, init=False)
class Model(Recipe):
    """Select one model route with optional Candidate-owned answer policy."""

    model: str
    name: str
    optional: bool
    prompt: str | None
    _params: GenerationParams
    _sample_id: str | None

    def __init__(
        self,
        model: str,
        *,
        name: str | None = None,
        prompt: str | None = None,
        params: Mapping[str, str | int | float | bool] | None = None,
        optional: bool = False,
    ) -> None:
        object.__setattr__(self, "optional", _optional(optional))
        route = _model_route(model)
        inferred_name = route.rsplit("/", 1)[-1]
        explicit_name = None if name is None else _name(name, "model name")
        object.__setattr__(self, "model", route)
        object.__setattr__(self, "name", inferred_name if explicit_name is None else explicit_name)
        object.__setattr__(self, "prompt", _generation_prompt(prompt, "model prompt"))
        object.__setattr__(self, "_params", _generation_params(params, "model params"))
        object.__setattr__(self, "_sample_id", explicit_name)

    @property
    def params(self) -> GenerationParams:
        return self._params

    @property
    def _recipe_marker(self) -> None:
        return None

    __hash__: ClassVar[Any] = None

    def __repr__(self) -> str:
        arguments = [repr(self.model)]
        if self._sample_id is not None:
            arguments.append(f"name={self.name!r}")
        if self.prompt is not None:
            arguments.append(f"prompt={self.prompt!r}")
        if self.params:
            arguments.append(f"params={dict(self.params)!r}")
        if self.optional:
            arguments.append("optional=True")
        return f"Model({', '.join(arguments)})"

    def _repr_html_(self) -> str:
        from screamingface._ui.cards import model_card_html

        return model_card_html(self)


__all__ = ["Model"]
