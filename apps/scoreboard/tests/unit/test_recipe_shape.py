"""A stored run is solo or a fusion by the Recipe it carries (HubSpot SOTA rule, 2026-11-26).

FEATURE: one model called once is solo; anything else, one model sampled and combined included,
is a fusion. A run whose Recipe cannot be read is neither.
"""

from __future__ import annotations

import json

import pytest
from url4 import expr, render, src, text

from scoreboard.classification.recipe_shape import recipe_shape


def _candidate(recipe_source: str | None) -> str:
    sources = [src("/openrouter/acme/m1", name="model_1")]
    if recipe_source is not None:
        sources.append(src(text(recipe_source), name="_sf_recipe", weight=0.0))
    return render(expr(*sources, intent=text("$model_1")))


def _stored(candidate: str) -> str:
    return render(
        expr(
            src(text(candidate), name="candidate", weight=0.0),
            src("/benchmarks/mmlu/aggregate", name="result"),
            intent=text(""),
        )
    )


def _recipe(kind: object, schema: str = "screamingface.recipe.v1") -> str:
    return json.dumps({"schema": schema, "recipe": {"kind": kind}})


@pytest.mark.parametrize(
    ("kind", "shape"),
    [
        ("model", "solo"),
        ("fusion", "fusion"),
        ("pipeline", "fusion"),
        ("self_corrective", "fusion"),
        ("corrective_loop", "fusion"),
        ("gate", "fusion"),
    ],
)
def test_one_model_is_solo_and_anything_else_a_fusion(kind: str, shape: str) -> None:
    assert recipe_shape(_stored(_candidate(_recipe(kind)))) == shape


@pytest.mark.parametrize(
    "stored",
    [
        None,
        "",
        "url4://x",
        "(((",
        _stored(_candidate(None)),
        _stored(_candidate("not json")),
        _stored(_candidate(_recipe("fusion", schema="screamingface.recipe.v2"))),
        _stored(_candidate(_recipe(7))),
        _stored(_candidate(json.dumps({"schema": "screamingface.recipe.v1", "recipe": []}))),
        _stored("((("),
    ],
)
def test_an_unreadable_recipe_is_neither(stored: str | None) -> None:
    assert recipe_shape(stored) is None
