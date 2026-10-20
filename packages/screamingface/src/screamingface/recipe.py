"""Client-independent values shared by composable Candidate Recipes."""

from __future__ import annotations

import unicodedata
from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import TYPE_CHECKING, Literal

from screamingface.reducer import Reducer

if TYPE_CHECKING:
    from screamingface._surface.chain import Pipeline as Chain
    from screamingface._surface.chain import Step
    from screamingface.pipeline import Pipeline


class Recipe(ABC):
    """Non-constructible umbrella type for answer-producing Recipe values."""

    name: str
    optional: bool

    def then(self, next_recipe: str | Recipe) -> Pipeline:
        """Return an immutable serial Pipeline ending in ``next_recipe``.

        WHY: unnamed-Pipeline flattening lives once, in the Pipeline constructor —
        this method only expresses "these two, in order".
        """

        from screamingface.pipeline import Pipeline

        return Pipeline((self, next_recipe))

    def __rshift__(self, other: str | Recipe | Step) -> Chain:
        """``a >> b`` is the chain ``Pipeline([a, b])`` (D7-3)."""

        # WHY lazy: screamingface._surface builds on this module
        from screamingface._surface.chain import Pipeline as Chain

        return Chain([self, other])

    def __rrshift__(self, other: str | Recipe | Step) -> Chain:
        """``"route" >> recipe``: a route string on the left of a recipe."""

        from screamingface._surface.chain import Pipeline as Chain

        return Chain([other, self])

    @property
    @abstractmethod
    def _recipe_marker(self) -> None:
        """Keep Recipe non-constructible without adding public behavior."""


def _optional(value: object) -> bool:
    if not isinstance(value, bool):
        raise TypeError("optional must be a bool")
    return value


def _name(value: object, label: str) -> str:
    text = _text(value, label).strip()
    if any(unicodedata.category(char).startswith("C") for char in text):
        raise ValueError(f"{label} must not contain control characters")
    return text


def _inferred_name(members: Sequence[Recipe]) -> str:
    """The name a Fusion or CorrectiveLoop gets from its members: their names joined by ``+``."""

    return "+".join(member.name for member in members)


def _inferred_self_name(member: Recipe) -> str:
    """The name a SelfCorrective gets from its member: the member's own name."""

    return member.name


def _kept_name(name: str, inferred: str) -> str | None:
    """``name=`` for a rebuilt value: None (infer again) when ``name`` was the inferred one."""

    return None if name == inferred else name


def _model_route(value: object) -> str:
    return _name(value, "model route")


OPTIONAL_MEMBERS_ONLY = "optional=True is only supported on Fusion members"


def _recipe(value: object, label: str, *, allow_optional: bool = False) -> Recipe:
    """Normalize the one intentional shorthand at every Recipe-valued position."""

    if isinstance(value, str):
        from screamingface.model import Model

        return Model(value)
    if isinstance(value, Reducer):
        raise TypeError(f"{label} cannot be a reducer: a reducer must be a Fusion synthesizer")
    # WHY lazy: screamingface._surface builds on this module. Until the swap (E4b surface unit 7)
    # the new chain steps live there: a step or an open chain is not a recipe (CH-8, CH-11).
    from screamingface._surface.chain import refuse_step

    refuse_step(value)
    if not _is_supported_recipe(value):
        raise TypeError(f"{label} must be a model route or sf.Model, sf.Fusion, or sf.Pipeline")
    assert isinstance(value, Recipe)
    if value.optional and not allow_optional:
        raise ValueError(OPTIONAL_MEMBERS_ONLY)
    return value


def _recipe_kind(
    value: Recipe,
) -> Literal["model", "fusion", "pipeline", "corrective_loop", "self_corrective"]:
    """The single authority mapping a Recipe value to its kind.

    WHY: kinds are the Recipe's type, never its Python class name — a renamed
    subclass is still its base kind, and every consumer (compiler, cards, future
    Recipe kinds) reads this one function instead of forking its own mapping.
    """

    from screamingface.corrective import CorrectiveLoop, SelfCorrective
    from screamingface.fusion import FusionNode
    from screamingface.model import Model
    from screamingface.pipeline import Pipeline

    kinds: tuple[
        tuple[type, Literal["model", "fusion", "pipeline", "corrective_loop", "self_corrective"]],
        ...,
    ] = (
        (Model, "model"),
        (FusionNode, "fusion"),
        (Pipeline, "pipeline"),
        (CorrectiveLoop, "corrective_loop"),
        (SelfCorrective, "self_corrective"),
    )
    for recipe_type, kind in kinds:
        if isinstance(value, recipe_type):
            return kind
    raise TypeError("candidate must be an sf.Model, sf.Fusion, or sf.Pipeline")


def _is_supported_recipe(value: object) -> bool:
    from screamingface._surface.chain import Pipeline as Chain
    from screamingface.fusion import FusionNode
    from screamingface.model import Model
    from screamingface.pipeline import Pipeline

    # A closed chain of the new surface is a recipe; lower() turns it into today's values before
    # the compile reads it (E4b surface lowering §2.4).
    return isinstance(value, Model | FusionNode | Pipeline | Chain)


def _text(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    if not value.strip():
        raise ValueError(f"{label} must not be empty")
    return value


__all__ = ["Recipe"]
