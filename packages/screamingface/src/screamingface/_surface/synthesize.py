"""``Synthesize``: the write step that closes a block with a model call (E4b surface, §8, D6).

FEATURE: ``Synthesize(model, *, prompt=None)`` names the writer and its prompt in one step. The
prompt has one home: it is refused when the model already has one, or when the model is a recipe
that is not a ``sf.Model`` (SY-1).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from screamingface._candidate_policy import prompt as _generation_prompt
from screamingface._surface.chain import Step, _Category
from screamingface.model import Model
from screamingface.recipe import Recipe, _recipe


@dataclass(frozen=True, slots=True, init=False, repr=False)
class Synthesize(Step):
    """Write the answer with one model or recipe: the write step that closes a block.

    ``model`` is a route string, a ``sf.Model`` or a recipe. ``prompt`` is the writer prompt; with
    no prompt, the default synthesis prompt applies. The writer gets one of three inputs:

    - right after ``sf.Fanout``: the fanout context, the request ``input`` and the member
      ``outputs`` (or the ``panel`` of the members that answered, with a quorum);
    - after ``sf.Rank`` or ``sf.Filter``: the envelope ``{"input", "selected"}``, with the
      selected members only;
    - after ``sf.Concat``: the joined text of the members, with no envelope.
    """

    _category: ClassVar[_Category] = "write"
    model: Recipe
    prompt: str | None

    def __init__(self, model: str | Recipe, *, prompt: str | None = None) -> None:
        selected = _recipe(model, "sf.Synthesize model")
        selected_prompt = _generation_prompt(prompt, "synthesize prompt")
        if selected_prompt is not None:
            _check_prompt_home(selected)
        object.__setattr__(self, "model", selected)
        object.__setattr__(self, "prompt", selected_prompt)

    def _recipes(self) -> tuple[Recipe, ...]:
        return (self.model,)

    __hash__: ClassVar[Any] = None


def _check_prompt_home(model: Recipe) -> None:
    """SY-1: ``prompt=`` goes to a model that has no prompt, never to a recipe writer."""

    if not isinstance(model, Model):
        raise ValueError(
            "sf.Synthesize prompt= needs a model route or a sf.Model: "
            "a recipe writer uses its own prompts"
        )
    if model.prompt is not None:
        raise ValueError(
            "sf.Synthesize prompt= sets the writer prompt: the sf.Model already has one"
        )


__all__ = ["Synthesize"]
