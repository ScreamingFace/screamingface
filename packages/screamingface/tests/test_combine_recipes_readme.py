"""The README "Combine recipes" code compiles to the recipe fixtures (recipes PRD RC-9, RC-D3).

FEATURE: an author copies a recipe from the README. This test runs the README code block and
compiles each recipe it assigns. The url4 must be byte-equal to the builder in
``_combine_recipes.py``, which ``test_combine_recipe_fixtures.py`` keeps byte-equal to the fixture
that the Engine runs. So the README code is the code that the Engine proves.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from _combine_flow_fixtures import flow_operators
from _combine_recipes import RECIPES, compile_recipe

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate

_README = Path(__file__).resolve().parents[1] / "README.md"
_HEADING = "### Combine recipes"
_NEXT_HEADING = re.compile(r"^#{2,3} ", re.MULTILINE)
_CODE = re.compile(r"```python\n(.*?)\n```", re.DOTALL)


def _section() -> str:
    text = _README.read_text(encoding="utf-8")
    assert _HEADING in text, f"README.md has no {_HEADING!r} section"
    rest = text[text.index(_HEADING) + len(_HEADING) :]
    end = _NEXT_HEADING.search(rest)
    return rest if end is None else rest[: end.start()]


def _readme_recipes() -> dict[str, Any]:
    code = _CODE.search(_section())
    assert code is not None, "the Combine recipes section has no python code block"
    namespace: dict[str, Any] = {}
    exec(code.group(1), namespace)  # the README code is ours, and this is what an author runs
    return namespace


def test_readme_combine_recipes_compile() -> None:
    namespace = _readme_recipes()

    for entry in RECIPES.values():
        assert entry.readme_name in namespace, (
            f"the README code does not assign {entry.readme_name}"
        )
        written = namespace[entry.readme_name]
        assert isinstance(written, sf.Recipe)
        url4 = compile_candidate(written, operators=flow_operators()).url4
        assert url4 == compile_recipe(entry.fixture), entry.readme_name


def test_readme_combine_recipes_table_lists_each_scenario_and_the_scale_rule() -> None:
    section = _section()

    for entry in RECIPES.values():
        assert f"| {entry.scenario} |" in section
        assert f"`{entry.readme_name}`" in section
    assert "same confidence scale" in section
