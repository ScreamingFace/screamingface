"""Corrective-loop Candidate values — panel and solo (OME-796 / OME-828).

Mental model: an exam with a proctor and limited retakes. Members draft in
parallel, the benchmark's advertised check surface marks each draft, the first
passing draft is submitted WORD-FOR-WORD, and a no-pass round buys one judge
coaching call plus a retry — at most ``max_rounds`` rounds (a cost cap, not a
target). The whole loop compiles client-side into ONE ``$candidate``
expression, so it runs on ANY benchmark that advertises a check surface.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, ClassVar

from screamingface.recipe import Recipe, _inferred_name, _inferred_self_name, _name, _recipe

# The structural floor is a PANEL rule (a corrective panel needs >=2 drafts to
# select between). The former four-member ceiling belonged to the LANL prototype,
# not to this benchmark-independent Recipe.
_MIN_MEMBERS = 2
_DEFAULT_MAX_ROUNDS = 3


@dataclass(frozen=True, slots=True, init=False)
class CorrectiveLoop(Recipe):
    """A member panel drafting under a benchmark check until one draft passes.

    The single ``judge=`` model plays two constrained internal roles: as
    tie-selector it picks among passing drafts (never writes text), as coach it
    writes hints after a no-pass round (never answers). The role split lives in
    the loop's prompts and gates, not in this signature, so nobody smuggles a
    writer in. There is deliberately no ``stop_when=``: termination belongs
    to the benchmark's check, never to a caller predicate.
    """

    name: str
    members: tuple[Recipe, ...]
    judge: Recipe
    max_rounds: int

    def __init__(
        self,
        members: Sequence[str | Recipe],
        *,
        judge: str | Recipe,
        max_rounds: int = _DEFAULT_MAX_ROUNDS,
        name: str | None = None,
    ) -> None:
        selected_members = _members(members)
        inferred_name = _inferred_name(selected_members)
        object.__setattr__(
            self,
            "name",
            inferred_name if name is None else _name(name, "corrective loop name"),
        )
        object.__setattr__(self, "members", selected_members)
        object.__setattr__(self, "judge", _recipe(judge, "CorrectiveLoop judge"))
        object.__setattr__(self, "max_rounds", _max_rounds(max_rounds))

    @property
    def _recipe_marker(self) -> None:
        return None

    def __repr__(self) -> str:
        members = ", ".join(repr(member.name) for member in self.members)
        inferred_name = _inferred_name(self.members)
        arguments = [f"[{members}]"]
        if self.name != inferred_name:
            arguments.append(f"name={self.name!r}")
        arguments.append(f"judge={self.judge!r}")
        if self.max_rounds != _DEFAULT_MAX_ROUNDS:
            arguments.append(f"max_rounds={self.max_rounds!r}")
        return f"CorrectiveLoop({', '.join(arguments)})"

    __hash__: ClassVar[Any] = None


@dataclass(frozen=True, slots=True, init=False)
class SelfCorrective(Recipe):
    """One model drafting under a benchmark check, coaching itself between rounds.

    The solo shape of the corrective protocol: the same model authors its own
    retry feedback from the check surface's sanitized violations — the role the
    panel gives to a separate judge, played by the only model present.
    """

    name: str
    member: Recipe
    max_rounds: int

    def __init__(
        self,
        model: str | Recipe,
        *,
        max_rounds: int = _DEFAULT_MAX_ROUNDS,
        name: str | None = None,
    ) -> None:
        member = _recipe(model, "SelfCorrective model")
        object.__setattr__(
            self,
            "name",
            _inferred_self_name(member) if name is None else _name(name, "self-corrective name"),
        )
        object.__setattr__(self, "member", member)
        object.__setattr__(self, "max_rounds", _max_rounds(max_rounds))

    @property
    def _recipe_marker(self) -> None:
        return None

    def __repr__(self) -> str:
        arguments = [repr(self.member.name)]
        if self.name != _inferred_self_name(self.member):
            arguments.append(f"name={self.name!r}")
        if self.max_rounds != _DEFAULT_MAX_ROUNDS:
            arguments.append(f"max_rounds={self.max_rounds!r}")
        return f"SelfCorrective({', '.join(arguments)})"

    __hash__: ClassVar[Any] = None


def _members(values: object) -> tuple[Recipe, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise TypeError(
            "CorrectiveLoop members must be an ordered sequence of model routes or Recipes"
        )
    selected = tuple(_recipe(value, "CorrectiveLoop member") for value in values)
    if len(selected) < _MIN_MEMBERS:
        raise ValueError(f"a CorrectiveLoop requires at least {_MIN_MEMBERS} members")
    return selected


def _max_rounds(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("max_rounds must be an integer")
    if value < 1:
        raise ValueError("max_rounds must be at least 1")
    return value


__all__ = ["CorrectiveLoop", "SelfCorrective"]
