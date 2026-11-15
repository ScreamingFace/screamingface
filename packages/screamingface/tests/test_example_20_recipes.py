"""Notebook 20 builds every router and cascade recipe, and each one compiles offline (E4c, docs).

FEATURE: OME-1291 docs PRD rows #16 and #17 (DC-10, DC-14, DC-16): ``examples/
20_routers_cascades.ipynb`` shows the README recipes of "Choose whether a model runs" with real
routes. STORY: a researcher runs it cell by cell, and every recipe must build and compile before
any paid call. The notebook gate only checks that the builder regenerates the file, so this test
scans the code cells for network markers, runs them (they make no request: the evaluation cell
is off by default) and compiles each recipe with the Engine operator catalog.
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Any

import pytest
from _combine_contract import engine_operators
from test_e4c_docs_fixtures import RECIPES
from test_routers_cascades_docs import refuse_network_markers

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate

_NOTEBOOK = Path(__file__).resolve().parents[1] / "examples" / "20_routers_cascades.ipynb"
# WHY not RUN_EVALUATION: the evaluation cell names sf.evaluate behind the flag that keeps it off.
_EVALUATION_CELL = "RUN_EVALUATION = False"
# WHY: the TARGET block names the local and hosted Engine URLs. It only calls sf.configure (no
# request), and tests/test_notebook_targets.py pins it. The scan reads the rest of that cell.
_TARGET = 'TARGET = "local"'
_TARGET_BLOCK_END = "raise ValueError(f'TARGET must be"


def _code_cells() -> list[str]:
    cells = json.loads(_NOTEBOOK.read_text(encoding="utf-8"))["cells"]
    return ["".join(cell["source"]) for cell in cells if cell["cell_type"] == "code"]


def _scanned(code: str) -> str:
    """The cell text that the network scan reads: a TARGET cell without its TARGET block."""
    if _TARGET not in code:
        return code
    _, found, rest = code.partition(_TARGET_BLOCK_END)
    assert found, f"{_NOTEBOOK.name}: the TARGET cell has no end marker {_TARGET_BLOCK_END!r}"
    return rest.partition("\n")[2]


def _run_notebook() -> dict[str, Any]:
    names: dict[str, Any] = {}
    for code in _code_cells():
        if _EVALUATION_CELL not in code:
            refuse_network_markers(_scanned(code), _NOTEBOOK.name)
        exec(code, names)  # the notebook is ours; its cells are offline
    return names


@pytest.fixture(scope="module")
def namespace() -> dict[str, Any]:
    with warnings.catch_warnings():
        warnings.simplefilter("error", sf.CascadeSeedWarning)
        return _run_notebook()


def _url4(recipe: sf.Recipe) -> str:
    return compile_candidate(recipe, operators=engine_operators()).url4


def test_the_notebook_does_not_evaluate_by_default(namespace: dict[str, Any]) -> None:
    # #16 (DC-16)
    assert namespace["RUN_EVALUATION"] is False
    assert namespace["report"] is None
    evaluation = [code for code in _code_cells() if "sf.evaluate(" in code]
    assert len(evaluation) == 1
    assert _EVALUATION_CELL in evaluation[0]


def test_each_recipe_has_its_own_cell_that_shows_it() -> None:
    # #16 (DC-10)
    cells = _code_cells()
    for name in RECIPES:
        assigning = [code for code in cells if f"\n{name} = " in f"\n{code}"]
        assert len(assigning) == 1, name
        last = assigning[0].rstrip().splitlines()[-1]
        assert name in last, f"the {name} cell does not show the recipe"


@pytest.mark.parametrize("name", list(RECIPES))
def test_every_recipe_of_notebook_20_compiles_offline(namespace: dict[str, Any], name: str) -> None:
    # #16 (DC-10)
    recipe = namespace[name]
    assert isinstance(recipe, sf.Recipe)
    assert "/ensemble/branch/v1/decide" in _url4(recipe)


def test_the_gate_form_behind_one_cascade(namespace: dict[str, Any]) -> None:
    # #16 (DC-10, CA-1): the Cascade is the Gate form, by value, repr and url4.
    cascade, gate_form = namespace["d4_cope_cascade"], namespace["gate_form"]
    assert gate_form == cascade
    assert repr(gate_form) == repr(cascade)
    assert "Gate(when=agreement() >= 0.8" in repr(cascade)
    assert _url4(gate_form) == _url4(cascade)


def test_the_evaluation_cell_names_each_recipe_once(namespace: dict[str, Any]) -> None:
    recipes: dict[str, sf.Recipe] = namespace["recipes"]
    candidates: list[sf.Recipe] = namespace["candidates"]
    assert [name.replace("-", "_") for name in recipes] == list(RECIPES)
    for name, recipe in recipes.items():
        assert recipe is namespace[name.replace("-", "_")], name
    assert [candidate.name for candidate in candidates] == list(recipes)
    for candidate in candidates:
        _url4(candidate)
