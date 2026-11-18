"""MI-7, MI-8, MI-10, MI-30 at the level of the model rule (contracts C1.1, P1, P2, P14, P17)."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from _chat_engine import (
    BENCH_ROUTE,
    CAND,
    CATALOG,
    EVAL,
    NOT_TEXT,
    cascade,
    corrective_loop,
    fusion,
    gate,
    model,
    pipeline,
    self_corrective,
    vote,
)

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.operators import _OperatorCatalog
from screamingface._inference.request import model_source, model_text, url4_text
from screamingface.errors import PlanningError
from screamingface.recipe import Recipe


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("openrouter/a", "openrouter/a"),
        (" openrouter/a ", " openrouter/a "),
        (CAND, CAND),
        ("\n " + CAND, "\n " + CAND),
        ("(not url4", "(not url4"),
        (NOT_TEXT, NOT_TEXT),
    ],
)
def test_model_string_rule_matches_the_engine(value: str, expected: str) -> None:
    result = model_source(value)
    assert result == expected
    assert type(result) is str


def test_a_url4_value_is_url4_text() -> None:
    result = model_source(sf.Url4(CAND))
    assert result == CAND
    assert type(result) is str


@pytest.mark.parametrize("value", ["", "   ", "\n"])
def test_blank_model_is_a_value_error(value: str) -> None:
    with pytest.raises(ValueError):
        model_source(value)


@pytest.mark.parametrize("value", [None, 3, b"openrouter/a", ["openrouter/a"], sf.Vote()])
def test_model_of_a_wrong_type_is_a_type_error(value: object) -> None:
    with pytest.raises(TypeError):
        model_source(value)


@pytest.mark.parametrize("build", [model, fusion, pipeline])
def test_recipe_compiles_to_the_candidate_text_of_an_evaluation(
    build: Callable[[], Recipe],
) -> None:
    recipe = build()
    assert model_source(recipe) == compile_candidate(recipe).url4


@pytest.mark.parametrize("build", [vote, gate, cascade])
def test_reducer_recipe_compiles_at_each_call(build: Callable[[], Recipe]) -> None:
    calls: list[int] = []

    def loader() -> _OperatorCatalog:
        calls.append(1)
        return CATALOG

    source = model_source(build())
    assert not isinstance(source, str)
    assert len(calls) == 0
    assert model_text(source, loader) == compile_candidate(build(), operators=CATALOG).url4
    # WHY the count is 2: the client caches the catalogue, not this module.
    model_text(source, loader)
    assert len(calls) == 2


@pytest.mark.parametrize("build", [self_corrective, corrective_loop])
def test_corrective_loop_is_recipe_not_supported(build: Callable[[], Recipe]) -> None:
    with pytest.raises(PlanningError) as caught:
        model_source(build())
    assert caught.value.code == "recipe_not_supported"
    assert "chat route" in caught.value.message
    assert "benchmark" not in caught.value.message.lower()


def test_compiler_errors_keep_their_type() -> None:
    source = model_source(sf.Fanout(["prov/a", "prov/b"]) >> sf.Vote(over="benchmark"))
    with pytest.raises(ValueError, match="over='benchmark' needs a benchmark"):
        model_text(source, lambda: CATALOG)


def test_evaluation_url4_sends_its_candidate_source() -> None:
    assert model_source(EVAL) == CAND
    assert model_source(sf.Url4(EVAL)) == CAND
    assert url4_text(EVAL) == CAND


def test_evaluation_url4_with_no_candidate_is_a_planning_error() -> None:
    with pytest.raises(PlanningError) as caught:
        model_source(BENCH_ROUTE)
    assert caught.value.code == "recipe_invalid"


# WHY: MI-10, also inside WithBudget. sf.WithBudget refuses the loop when it is made, so no
# ModelInference can get it.
@pytest.mark.parametrize(
    "build",
    [
        lambda: sf.SelfCorrective("provider/a"),
        lambda: sf.CorrectiveLoop(["provider/a", "provider/b"], judge="provider/j"),
    ],
)
def test_with_budget_refuses_a_corrective_loop_when_it_is_made(
    build: Callable[[], Recipe],
) -> None:
    with pytest.raises(TypeError):
        sf.WithBudget(build(), budget_usd=0.05)
