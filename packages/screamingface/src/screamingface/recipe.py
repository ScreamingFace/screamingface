"""Client-independent values shared by composable Candidate Recipes."""

from __future__ import annotations

import unicodedata
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
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


def _model_route(value: object) -> str:
    return _name(value, "model route")


def _recipe(value: object, label: str, *, allow_optional: bool = False) -> Recipe:
    """Normalize the one intentional shorthand at every Recipe-valued position."""

    if isinstance(value, str):
        from screamingface.model import Model

        return Model(value)
    if not _is_supported_recipe(value):
        raise TypeError(f"{label} must be a model route or sf.Model, sf.Fusion, or sf.Pipeline")
    assert isinstance(value, Recipe)
    if value.optional and not allow_optional:
        raise ValueError("optional=True is only supported on Fusion members")
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
    from screamingface.fusion import Fusion
    from screamingface.model import Model
    from screamingface.pipeline import Pipeline

    kinds: tuple[
        tuple[type, Literal["model", "fusion", "pipeline", "corrective_loop", "self_corrective"]],
        ...,
    ] = (
        (Model, "model"),
        (Fusion, "fusion"),
        (Pipeline, "pipeline"),
        (CorrectiveLoop, "corrective_loop"),
        (SelfCorrective, "self_corrective"),
    )
    for recipe_type, kind in kinds:
        if isinstance(value, recipe_type):
            return kind
    raise TypeError("candidate must be an sf.Model, sf.Fusion, or sf.Pipeline")


def _is_supported_recipe(value: object) -> bool:
    from screamingface.fusion import Fusion
    from screamingface.model import Model
    from screamingface.pipeline import Pipeline

    return isinstance(value, Model | Fusion | Pipeline)


def _text(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    if not value.strip():
        raise ValueError(f"{label} must not be empty")
    return value


__all__ = ["Recipe"]
