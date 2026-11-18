"""Stage 4b of POST /v1/chat/completions, with tools: the final steps of the recipe.

With `tools` in the request, each final model step must be able to take them. TC-S11: a final
step that asks for a search on a route whose search is the Engine tool loop is refused, as the
final-step endpoint has no tool loop. TC-S10: each final model must list `tools` in its
`supported_parameters` in the catalogue, which is GET /v1/models of the caller. The re-point proof
of the worker (`chat.recipe.repoint_final_steps`) runs here too, so a recipe that fails it is a
400 and not a failed run. Each refusal comes before the input write, so no blob and no run exist.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from screamingface_engine.catalog.port import CatalogError, CatalogSource, Credential
from screamingface_engine.chat.recipe import (
    FINAL_SEARCH_MESSAGE,
    UNKNOWN_FINAL_MESSAGE,
    FinalModelStep,
    RecipeRefusal,
    RepointError,
    check_recipe,
    final_model_steps,
    repoint_final_steps,
)
from screamingface_engine.rest.chat_errors import ChatError
from screamingface_engine.rest.chat_model import catalog_unavailable
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.models.registry import decode_route_id, encode_route_id
from screamingface_engine.world.request_parameters import WEB_SEARCH_PARAM

__all__ = ["check_tool_steps"]

_TOOLS_PARAMETER = "tools"


async def check_tool_steps(
    recipe: str,
    *,
    identity: Mapping[str, str] | None,
    catalog: CatalogSource | None,
) -> None:
    """Refuse a recipe whose final model steps cannot take the client tools (TC-S10, TC-S11)."""
    steps = _final_steps(recipe)
    _refuse_tool_loop_search(steps)
    supported = await _supported_parameters(identity, catalog)
    for step in steps:
        _require_tools(step, supported)


def _final_steps(recipe: str) -> tuple[FinalModelStep, ...]:
    try:
        checked = check_recipe(recipe, with_tools=True)
        steps = final_model_steps(checked)
        models = [position for position in checked.positions if position.kind == "model"]
        if models:
            # WHY: the same proof as the worker (world/chat_turn.py), before any blob or run; only
            # the proof matters here, so the re-pointed text is not used.
            repoint_final_steps(checked.root, models)
        return steps
    except RecipeRefusal as exc:
        raise ChatError(400, exc.code, exc.message, param="model") from None
    except RepointError:
        raise ChatError(400, "recipe_not_supported", UNKNOWN_FINAL_MESSAGE, param="model") from None


def _refuse_tool_loop_search(steps: tuple[FinalModelStep, ...]) -> None:
    """TC-S11, before any catalogue call; a final step that sets no web_search is not refused."""
    for step in steps:
        # WHY ModelSpec: the App cannot read the route table, and ModelSpec derives the search
        # mechanism from the provider of the id, the rule that the Runner uses.
        if (
            step.params.get(WEB_SEARCH_PARAM) == "true"
            and ModelSpec(id=step.route[1:]).uses_web_tools
        ):
            raise ChatError(400, "recipe_not_supported", FINAL_SEARCH_MESSAGE, param="model")


async def _supported_parameters(
    identity: Mapping[str, str] | None, catalog: CatalogSource | None
) -> dict[str, Any]:
    """The supported parameters of each catalogue row by route id; one fetch per request."""
    if catalog is None:
        raise catalog_unavailable(retry=False)
    try:
        fetched = await catalog.fetch(Credential.derive(identity))
    except CatalogError:
        raise catalog_unavailable(retry=True) from None
    rows = fetched.body.get("data")
    return {
        row["id"]: row.get("supported_parameters")
        for row in (rows if isinstance(rows, list) else [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }


def _require_tools(step: FinalModelStep, supported: Mapping[str, Any]) -> None:
    """TC-S10: the row of the final model must list `tools`."""
    key = encode_route_id(decode_route_id(step.route[1:]))
    parameters = supported.get(key)
    if not isinstance(parameters, list) or _TOOLS_PARAMETER not in parameters:
        raise ChatError(
            400,
            "model_does_not_support_tools",
            f"the model {decode_route_id(key)} does not support tools",
            param="model",
        )
