"""Is a stored run a single model, or anything more? Read from the Recipe the run carries.

FEATURE: the HubSpot sync's SOTA rule (Filip and Irina, 2026-11-26): a solo run is one model,
called once; everything else, a model sampled several times and combined ("self fusion")
included, is a fusion.

WHY the Recipe, not `Score.models` or `metadata.candidate_kind`: `models` lists each route once,
so three samples of one model plus a selector look like one plain call; the Client's label calls
real multi-model runs `pipeline`. The Client writes the run's Recipe as JSON into a `_sf_recipe`
source of the Candidate expression (`screamingface/_evaluation/topology.py`), and the stored
`url4_expression` keeps it. Parsed with the url4 grammar, never searched as text.
"""

from __future__ import annotations

import json
from typing import Literal

from url4 import Expression, Source, Text, Url4Error, build

RECIPE_SOURCE = "_sf_recipe"
RECIPE_SCHEMA = "screamingface.recipe.v1"
CANDIDATE_SOURCE = "candidate"

type RecipeShape = Literal["solo", "fusion"]


def _named_text(expression: object, name: str) -> str | None:
    if not isinstance(expression, Expression):
        return None
    matches = [
        node.value
        for node in expression.sources
        if isinstance(node, Source) and node.name == name and isinstance(node.value, Text)
    ]
    return matches[0].value if len(matches) == 1 else None


def _recipe_kind(url4_expression: str) -> object:
    """The top Recipe node's `kind`, or None when the Recipe cannot be read."""
    try:
        candidate = _named_text(build(url4_expression), CANDIDATE_SOURCE)
        raw = None if candidate is None else _named_text(build(candidate), RECIPE_SOURCE)
        payload = None if raw is None else json.loads(raw)
    except (Url4Error, ValueError, RecursionError):  # ValueError covers JSONDecodeError
        return None
    if not isinstance(payload, dict) or payload.get("schema") != RECIPE_SCHEMA:
        return None
    recipe = payload.get("recipe")
    return recipe.get("kind") if isinstance(recipe, dict) else None


def recipe_shape(url4_expression: str | None) -> RecipeShape | None:
    """`solo` when the run's Recipe is one model node, `fusion` for any other Recipe.

    INVARIANT: None (neither) when the Recipe cannot be read: no expression, an unparsable one,
    no single `_sf_recipe`, or another schema. The SOTA rule then neither flags the run nor
    counts it as a solo reference.
    """
    kind = _recipe_kind(url4_expression) if url4_expression else None
    if not isinstance(kind, str):
        return None
    return "solo" if kind == "model" else "fusion"
