"""``Fanout``: the map step that opens a block (E4b surface, surface §3).

FEATURE: ``Fanout(members, *, signals=None, quorum="all", name=None, prompt=None)`` sends the
input to every member and declares the signals that the later steps of its block read. The
member, quorum and signal rules of today's Fusion apply here, when the Fanout is built; the rules
that need the terminal step run when the block closes (CH-9).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, Literal

from screamingface._candidate_policy import prompt as _generation_prompt
from screamingface._surface.chain import Step, _Category
from screamingface.fusion import _declaration, _members, _quorum
from screamingface.model import Model
from screamingface.recipe import Recipe, _inferred_name, _name
from screamingface.signal_sources import SignalSource


@dataclass(frozen=True, slots=True, init=False, repr=False)
class Fanout(Step):
    """Send the input to every member, in parallel: the map step that opens a block.

    ``members`` are route strings and recipes; a member may be ``optional=True``. ``signals=``
    maps a declared name to a source (``sf.Verbalized``, ``sf.Logprob``, ``sf.Entropy``,
    ``sf.Sum``, ``sf.Consistency``) that a later step of the block reads. ``quorum`` is the
    successful-member floor: ``"all"`` or a number from 0 to the member count. ``name`` defaults
    to the member names joined by ``+``.

    ``prompt=`` sets the prompt of each member that is a route string or a ``sf.Model`` with no
    prompt. A member with its own prompt, or a member that is not a model, is refused (FA-1).

    A Fanout alone is not a recipe: a reducer or ``sf.Synthesize`` must follow it.
    """

    _category: ClassVar[_Category] = "map"
    members: tuple[Recipe, ...]
    signals: Mapping[str, SignalSource] | None
    quorum: int | Literal["all"]
    name: str
    prompt: str | None

    def __init__(
        self,
        members: Sequence[str | Recipe],
        *,
        signals: Mapping[str, SignalSource] | None = None,
        quorum: int | Literal["all"] = "all",
        name: str | None = None,
        prompt: str | None = None,
    ) -> None:
        selected = _members(members, "Fanout")
        object.__setattr__(self, "members", selected)
        object.__setattr__(self, "signals", _declaration(signals))
        object.__setattr__(self, "quorum", _quorum(quorum, len(selected)))
        object.__setattr__(
            self, "name", _inferred_name(selected) if name is None else _name(name, "fanout name")
        )
        object.__setattr__(self, "prompt", _member_prompt(prompt, selected))

    def _recipes(self) -> tuple[Recipe, ...]:
        return self.members

    __hash__: ClassVar[Any] = None


def _member_prompt(value: object, members: tuple[Recipe, ...]) -> str | None:
    """The checked ``prompt=``: each member must be a model with no prompt of its own (FA-1, O6).

    WHY a refusal and not an override: one prompt rule, and no member prompt that is silently
    lost.
    """

    selected = _generation_prompt(value, "fanout prompt")
    if selected is None:
        return None
    for position, member in enumerate(members, 1):
        if not isinstance(member, Model):
            raise ValueError(
                f"Fanout prompt= sets the member prompts: member {position} is not a model"
            )
        if member.prompt is not None:
            raise ValueError(
                f"Fanout prompt= sets the member prompts: member {position} already has one"
            )
    return selected


__all__ = ["Fanout"]
