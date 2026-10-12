"""Serial Candidate values."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, ClassVar

from screamingface.recipe import Recipe, _name, _optional, _recipe


@dataclass(frozen=True, slots=True, init=False)
class Pipeline(Recipe):
    """Pass one input through an ordered sequence of Recipe stages."""

    name: str
    optional: bool
    stages: tuple[Recipe, ...]
    _is_named: bool

    def __init__(
        self,
        stages: Sequence[str | Recipe],
        *,
        name: str | None = None,
        optional: bool = False,
    ) -> None:
        object.__setattr__(self, "optional", _optional(optional))
        selected_stages = _stages(stages)
        inferred_name = "->".join(stage.name for stage in selected_stages)
        object.__setattr__(
            self,
            "name",
            inferred_name if name is None else _name(name, "pipeline name"),
        )
        object.__setattr__(self, "stages", selected_stages)
        object.__setattr__(self, "_is_named", name is not None)

    @property
    def _recipe_marker(self) -> None:
        return None

    def __repr__(self) -> str:
        stages = ", ".join(repr(stage.name) for stage in self.stages)
        arguments = [f"[{stages}]"]
        # WHY: explicit naming is behavioral, not cosmetic — a named Pipeline keeps its
        # grouping when nested instead of flattening, and `_is_named` participates in
        # equality. The repr therefore shows `name=` whenever the value was explicitly
        # named, even when it equals the inferred name, so equal-looking reprs never
        # hide unequal values.
        if self._is_named:
            arguments.append(f"name={self.name!r}")
        if self.optional:
            arguments.append("optional=True")
        return f"Pipeline({', '.join(arguments)})"

    def _repr_html_(self) -> str:
        from screamingface._ui.cards import pipeline_card_html

        return pipeline_card_html(self)

    __hash__: ClassVar[Any] = None


def _stages(values: object) -> tuple[Recipe, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise TypeError("Pipeline stages must be an ordered sequence of model routes or Recipes")
    normalized = tuple(_recipe(value, "Pipeline stage") for value in values)
    selected = tuple(
        nested
        for stage in normalized
        for nested in (
            stage.stages if isinstance(stage, Pipeline) and not stage._is_named else (stage,)
        )
    )
    if not selected:
        raise ValueError("a Pipeline requires at least one stage")
    return selected


__all__ = ["Pipeline"]
