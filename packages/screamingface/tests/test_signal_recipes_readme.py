"""The README "Signal sources" code compiles to the signal recipe fixtures (E4b part 3 RC-2, RC-D3).

FEATURE: an author copies a signal recipe from the README. This test runs the README code block
and compiles each recipe it assigns. The url4 must be byte-equal to the builder in
``_signal_recipes.py``, which ``test_signal_recipe_fixtures.py`` keeps byte-equal to the fixture
that the Engine runs. The section also states the guidance that the PRDs require (one scale, the
64 KiB window, ``sum`` favors short replies, the size caps, the S16 limit, the refusal and its fix).
So the README code is the code that the Engine proves.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from _combine_flow_fixtures import flow_operators
from _signal_recipes import SIGNAL_RECIPES, compile_signal_recipe

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate

_README = Path(__file__).resolve().parents[1] / "README.md"
_HEADING = "### Signal sources"
_NEXT_HEADING = re.compile(r"^#{2,3} ", re.MULTILINE)
_CODE = re.compile(r"```python\n(.*?)\n```", re.DOTALL)
# The guidance that the section must state (RC-D3, RC-D4, LP-D3, EN-D5, RC-E1, RC-E2, N1-N4).
_GUIDANCE = (
    "same confidence scale",  # VB-D4, RC-D3
    "last 64 KiB",  # RC-D3, P7
    "`sum` favors short replies",  # LP-D3, N1
    "`mean` and `prob` do not depend on the reply length",  # LP-D3
    "Keep `top_logprobs` small",  # EN-D5, RC-D4
    "1,000,000 bytes",  # RC-D4, N3
    "2,000,000 bytes",  # RC-D4, N4
    "larger model still runs",  # RC-D2, N2
    "E4c",  # RC-D2
    "nats",  # entropy unit (entropy PRD §4)
    "logprobs_unsupported",  # RC-E1 / Q5
    "openrouter/openai/gpt-4o-mini",  # Q2 pinned model
    'sf.Logprob("prob")',  # RC-E2 fix
)
_PROB_HINT = re.compile(r"""Logprob\(['"]prob['"]\)""")


def _section() -> str:
    text = _README.read_text(encoding="utf-8")
    assert _HEADING in text, f"README.md has no {_HEADING!r} section"
    rest = text[text.index(_HEADING) + len(_HEADING) :]
    end = _NEXT_HEADING.search(rest)
    return rest if end is None else rest[: end.start()]


def _code_blocks() -> list[str]:
    return _CODE.findall(_section())


def _readme_recipes() -> dict[str, Any]:
    blocks = _code_blocks()
    assert blocks, "the Signal sources section has no python code block"
    namespace: dict[str, Any] = {}
    exec(blocks[0], namespace)  # the README code is ours, and this is what an author runs
    return namespace


def test_readme_signal_sources_blocks_compile_and_carry_the_guidance(
    capsys: pytest.CaptureFixture[str],
) -> None:
    blocks = _code_blocks()
    assert len(blocks) == 2, "the Signal sources section has a recipe block and an error block"
    namespace = _readme_recipes()  # execs blocks[0]

    for entry in SIGNAL_RECIPES.values():
        assert entry.readme_name in namespace, (
            f"the README code does not assign {entry.readme_name}"
        )
        written = namespace[entry.readme_name]
        assert isinstance(written, sf.Recipe)
        url4 = compile_candidate(written, operators=flow_operators()).url4
        assert url4 == compile_signal_recipe(entry.fixture), entry.readme_name

    section = _section()
    for entry in SIGNAL_RECIPES.values():
        assert f"| {entry.scenario} |" in section
        assert f"`{entry.readme_name}`" in section
    flat = " ".join(section.split())  # line wraps do not matter
    for phrase in _GUIDANCE:
        assert phrase in flat, phrase

    capsys.readouterr()  # drop earlier output
    exec(blocks[1], namespace)  # the README error example (RC-E2)
    printed = capsys.readouterr().out
    assert printed.strip(), "the README error example did not raise"
    assert _PROB_HINT.search(printed), printed
