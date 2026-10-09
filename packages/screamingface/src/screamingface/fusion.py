"""Composite Candidate values."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, Literal

from screamingface.recipe import Recipe, _name, _optional, _recipe


@dataclass(frozen=True, slots=True, init=False)
class Fusion(Recipe):
    """Combine ordered parallel members through an explicit synthesizer Recipe.

    ``quorum`` is the successful-member floor, checked after members finish.
    Member Recipes marked ``optional=True`` tolerate failure; required members
    must succeed. ``all`` requires every member; zero permits
    synthesis with no successful member. The synthesizer itself stays required.
    """

    name: str
    members: tuple[Recipe, ...]
    synthesizer: Recipe
    quorum: int | Literal["all"]
    optional: bool

    def __init__(
        self,
        members: Sequence[str | Recipe],
        *,
        name: str | None = None,
        synthesizer: str | Recipe,
        quorum: int | Literal["all"] = "all",
        optional: bool = False,
    ) -> None:
        selected_members = _members(members)
        optional = _optional(optional)
        object.__setattr__(self, "quorum", _quorum(quorum, len(selected_members)))
        object.__setattr__(self, "optional", optional)
        inferred_name = "+".join(member.name for member in selected_members)
        object.__setattr__(
            self,
            "name",
            inferred_name if name is None else _name(name, "fusion name"),
        )
        object.__setattr__(self, "members", selected_members)
        object.__setattr__(self, "synthesizer", _recipe(synthesizer, "Fusion synthesizer"))

    @property
    def _recipe_marker(self) -> None:
        return None

    def __repr__(self) -> str:
        members = ", ".join(repr(member.name) for member in self.members)
        inferred_name = "+".join(member.name for member in self.members)
        arguments = [f"[{members}]"]
        if self.name != inferred_name:
            arguments.append(f"name={self.name!r}")
        arguments.append(f"synthesizer={self.synthesizer!r}")
        if self.quorum != "all":
            arguments.append(f"quorum={self.quorum!r}")
        if self.optional:
            arguments.append("optional=True")
        return f"Fusion({', '.join(arguments)})"

    def _repr_html_(self) -> str:
        from screamingface._ui.cards import fusion_card_html

        return fusion_card_html(self)

    __hash__: ClassVar[Any] = None


def _quorum(value: object, member_count: int) -> int | Literal["all"]:
    if value == "all":
        return "all"
    if type(value) is not int:
        raise TypeError("Fusion quorum must be an integer or 'all'")
    if value < 0 or value > member_count:
        raise ValueError("Fusion quorum must be between zero and the member count")
    return value


def _members(values: object) -> tuple[Recipe, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise TypeError("Fusion members must be an ordered sequence of model routes or Recipes")
    selected = tuple(_recipe(value, "Fusion member", allow_optional=True) for value in values)
    if not selected:
        raise ValueError("a Fusion requires at least one member")
    return selected


__all__ = ["Fusion"]
