"""DOC-1: the Candidate URL4 helper of the docs page gives a value that the chat route accepts.

FEATURE: OpenAI-compatible Engine API, unit U7 (prd/docs.md DOC-1, review F2). The SDK has no
call that returns the bare Candidate URL4 of a recipe: `report.candidates[name].url4` is the
evaluation URL4, which the chat route refuses. The docs page shows a helper that takes the text of
the top-level `candidate` source. This test runs the exact helper file that the page shows
(public-docs/src/snippets/openai-chat/candidate_url4.py) on a benchmark-linked expression of the
SDK surface corpus.

STORY: as a developer, I copy the helper of the docs page, give it the url4 of my evaluated
candidate, and send the result as `model`; the chat route accepts it.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest
from _chat_corpus import corpus

from screamingface_engine.chat.recipe import RecipeRefusal, check_recipe

REPO = Path(__file__).resolve().parents[4]
DOCS = REPO / "public-docs"
SNIPPET = DOCS / "src" / "snippets" / "openai-chat" / "candidate_url4.py"
LINKED = "lowering:pair-synthesize-evaluation"
pytestmark = pytest.mark.skipif(not DOCS.is_dir(), reason="public-docs is not in this checkout")


def _helper() -> Callable[[str], str]:
    """The `candidate_url4` function of the docs snippet, loaded from the file as the page shows
    it."""
    namespace: dict[str, object] = {"__name__": "candidate_url4_snippet"}
    exec(compile(SNIPPET.read_text(encoding="utf-8"), str(SNIPPET), "exec"), namespace)
    return cast("Callable[[str], str]", namespace["candidate_url4"])


def test_the_evaluation_url4_is_refused_and_the_extracted_candidate_url4_is_accepted() -> None:
    evaluation_url4 = corpus()[LINKED]
    with pytest.raises(RecipeRefusal) as caught:
        check_recipe(evaluation_url4, with_tools=False)
    assert caught.value.code == "recipe_invalid"

    candidate = _helper()(evaluation_url4)

    assert candidate.startswith("(")
    checked = check_recipe(candidate, with_tools=False)
    assert checked.positions


def test_the_helper_refuses_a_text_that_is_not_an_evaluation_url4() -> None:
    with pytest.raises(ValueError, match="not an evaluation URL4"):
        _helper()("(model_1:0.0:/prov/a($input)!'')!'$model_1'")
