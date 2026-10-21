"""Notebook 18 builds every recipe it shows, and each one compiles offline (E4b surface, unit 8).

FEATURE: ``examples/18_map_select_reduce.ipynb`` is the Product Owner notebook in the map → score →
narrow → reduce form: the 13 combine cases and the new steps. STORY: a researcher runs it cell by
cell, and every recipe must build and compile before any paid call. The notebook gate only checks
that the builder regenerates the file, so this test runs its code cells (they make no request:
the evaluation cell is off by default) and compiles each recipe with the flow operator catalog.
"""

from __future__ import annotations

import json
import urllib.parse
from pathlib import Path
from typing import Any

import pytest
from _combine_flow_fixtures import flow_operators

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate

_NOTEBOOK = Path(__file__).resolve().parents[1] / "examples" / "18_map_select_reduce.ipynb"
_CASES = (
    "s1",
    "s2",
    "s3",
    "s4",
    "s4_median",
    "s5",
    "s7",
    "s8",
    "s9",
    "s10",
    "s10_threshold",
    "s11",
    "s11_min",
)
_NEW = ("confident_mean", "best_two_vote", "gated_vote", "most_consistent", "logprob_vote")
_NARROW_BEFORE_REDUCER = ("confident_mean", "best_two_vote")
_SCORING_JUDGE = ("s10", "s10_threshold", "s11", "s11_min", "best_two_vote")


@pytest.fixture(scope="module")
def namespace() -> dict[str, Any]:
    cells = json.loads(_NOTEBOOK.read_text(encoding="utf-8"))["cells"]
    names: dict[str, Any] = {}
    for cell in cells:
        if cell["cell_type"] == "code":
            exec("".join(cell["source"]), names)  # the notebook is ours; its cells are offline
    return names


def _url4(recipe: sf.Recipe) -> str:
    return urllib.parse.unquote(compile_candidate(recipe, operators=flow_operators()).url4)


def test_the_notebook_does_not_evaluate_by_default(namespace: dict[str, Any]) -> None:
    assert namespace["RUN_EVALUATION"] is False
    assert namespace["report"] is None


@pytest.mark.parametrize("name", _CASES + _NEW)
def test_every_recipe_of_notebook_18_compiles_offline(namespace: dict[str, Any], name: str) -> None:
    recipe = namespace[name]

    assert isinstance(recipe, sf.Recipe)
    assert "/ensemble/combine/v1" in _url4(recipe)


def test_the_evaluation_cell_names_each_recipe_once_and_runs_s5_only_once(
    namespace: dict[str, Any],
) -> None:
    recipes: dict[str, sf.Recipe] = namespace["recipes"]
    candidates: list[sf.Pipeline] = namespace["candidates"]

    assert namespace["s8"] == namespace["s5"]  # every by= reads a signal (D3)
    assert namespace["s8"] not in [recipes[name] for name in recipes if name != "s5"]
    shown = set(_CASES + _NEW) - {"s8"}
    assert len(recipes) == len(shown)
    for name in shown:
        assert any(recipe is namespace[name] for recipe in recipes.values()), name
    assert [candidate.name for candidate in candidates] == list(recipes)
    for candidate in candidates:
        assert "/ensemble/combine/v1" in _url4(candidate)


@pytest.mark.parametrize("name", _NARROW_BEFORE_REDUCER)
def test_a_narrow_step_before_a_reducer_writes_the_narrow_key(
    namespace: dict[str, Any], name: str
) -> None:
    assert '"narrow":[' in _url4(namespace[name])


@pytest.mark.parametrize("name", _SCORING_JUDGE)
def test_a_scoring_judge_uses_the_neutral_template(namespace: dict[str, Any], name: str) -> None:
    url4 = _url4(namespace[name])

    assert "judge-template@2 returns=scores" in url4
    assert "judge-template@1 returns=scores" not in url4
