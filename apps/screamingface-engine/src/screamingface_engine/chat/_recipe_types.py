"""The plain data and the refusals of the chat recipe check; `chat.recipe` re-exports each name.

WHY a module of its own: it holds no url4 import, so the url4 code of the check stays in
`chat/recipe.py`, the one chat module that may import the url4 engine (plan decision D7).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

__all__ = [
    "FINAL_NOT_UNIQUE_MESSAGE",
    "FINAL_SEARCH_MESSAGE",
    "FINAL_STEP_NOT_MODEL_MESSAGE",
    "LINKED_EXPRESSION_MESSAGE",
    "UNKNOWN_FINAL_MESSAGE",
    "FinalModelStep",
    "FinalPosition",
    "PositionKind",
    "RecipeRefusal",
    "RefusalCode",
    "RepointError",
]

FINAL_STEP_NOT_MODEL_MESSAGE = (
    "With tools, the last step of the recipe must be a model step. Add a final model stage, "
    "for example cascade >> model."
)
LINKED_EXPRESSION_MESSAGE = (
    "the model value is a benchmark-linked expression; send the Candidate URL4 as the model"
)
UNKNOWN_FINAL_MESSAGE = "with tools, the check cannot find the last step of the recipe"
FINAL_SEARCH_MESSAGE = "with tools, a final step cannot search on this model route"
FINAL_NOT_UNIQUE_MESSAGE = (
    "with tools, the final step of the recipe is not unique: its binding names more than one step"
)

RefusalCode = Literal["recipe_invalid", "recipe_not_supported", "final_step_not_model"]
PositionKind = Literal["model", "reducer", "step", "outcome", "loop", "unknown"]


class RecipeRefusal(ValueError):
    """The chat route refuses the recipe. The message never echoes recipe text."""

    def __init__(self, code: RefusalCode, message: str) -> None:
        super().__init__(message)
        self.code: RefusalCode = code
        self.message = message


class RepointError(ValueError):
    """The re-point could not prove that its copy changed only the selected steps."""


@dataclass(frozen=True)
class FinalPosition:
    """One place whose output can be the answer of the recipe (prd/tool-calls.md §3.1)."""

    kind: PositionKind
    binding: str | None
    scope: tuple[str, ...]
    route: str | None


@dataclass(frozen=True)
class FinalModelStep:
    """One final model step as plain data; no url4 node leaves the recipe check.

    `route` is the model route path of the step's model call, for example "/prov/a".
    """

    binding: str
    route: str
    params: Mapping[str, str | None]
